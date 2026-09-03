"""Tenants and the people in them.

WHO CREATES A TENANT. Not a customer filling in a signup form - there isn't
one. A plan is sold, and the vendor provisions the tenant and its first admin.
So POST /tenants is guarded by the static ORCHID_API_KEY, which is exactly the
right tool for the one endpoint that has to work before any account exists to
authenticate as. Every other endpoint here is guarded by a bearer token.

THE TENANT IS NEVER A PARAMETER. It is read off the caller's verified token, so
there is no request anyone can shape that reaches another tenant's data. An
endpoint that accepted `?tenantId=` would be one forgotten check away from being
the bug this design exists to prevent.

firebase_admin is imported inside the functions, for the reasons in
firebase_auth.py.
"""
from __future__ import annotations

import hmac
import logging
import os
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import require_auth, require_role
from app.services import tenant_store as store
from app.services.firebase_auth import ROLE_ADMIN, ROLES, AuthContext

router = APIRouter()

_log = logging.getLogger(__name__)

VENDOR_KEY = os.environ.get("ORCHID_API_KEY", "").strip()

_create_user: Optional[Callable] = None
_set_claims: Optional[Callable] = None
_delete_user: Optional[Callable] = None
_revoke_tokens: Optional[Callable] = None


def set_identity_backend(create_user, set_claims, delete_user,
                         revoke_tokens=None) -> None:
    """Swap the admin-SDK calls. Pass (None, None, None) to restore.

    `revoke_tokens` is optional so the seam still reads the way it did before
    session revocation existed; a test that does not care about it passes three
    arguments and gets a no-op.
    """
    global _create_user, _set_claims, _delete_user, _revoke_tokens
    _create_user, _set_claims, _delete_user = create_user, set_claims, delete_user
    _revoke_tokens = revoke_tokens


def _identity():
    if _create_user is not None:
        return _create_user, _set_claims, _delete_user
    from firebase_admin import auth as fb_auth
    from app.services.firebase_auth import auth_client

    # POST /tenants carries a vendor key, never a bearer token, so nothing
    # will have called auth_client() yet by the time this runs. Binding every
    # call to the app it returns - rather than leaving `app` implicit - is
    # what keeps this off the *default* Firebase app, which this project
    # never initialises and which would otherwise raise "The default Firebase
    # app does not exist" on the very first real call.
    app = auth_client()

    def _mk(email, password):
        return fb_auth.create_user(email=email, password=password, app=app).uid

    def _claims(uid, claims):
        fb_auth.set_custom_user_claims(uid, claims, app=app)

    def _rm(uid):
        fb_auth.delete_user(uid, app=app)

    return _mk, _claims, _rm


def _revoker() -> Callable:
    if _create_user is not None:
        return _revoke_tokens or (lambda uid: None)
    from firebase_admin import auth as fb_auth
    from app.services.firebase_auth import auth_client

    app = auth_client()
    return lambda uid: fb_auth.revoke_refresh_tokens(uid, app=app)


def _revoke_sessions(uid: str) -> None:
    """Cut an account's refresh tokens, best effort.

    Defence in depth ONLY. Revocation bites solely on a verify that passes
    `check_revoked=True`, and the read path deliberately does not pay for that,
    so this does not on its own close the window in which a stale ID token
    still carries the old role - `_still_admin` below is what does that. It
    shortens the window for everything downstream of the token instead. A
    failure here must not fail an operation that has already succeeded, and it
    must not be silent either.
    """
    try:
        _revoker()(uid)
    except Exception as e:
        _log.warning("could not revoke refresh tokens for %s: %s", uid, e)


def _auth_user_already_gone(exc: Exception) -> bool:
    """True when firebase_admin is saying the auth user is not there.

    Imported lazily, and matched by name as a fallback, because CI installs a
    trimmed requirements file with no firebase-admin in it and the test seam
    raises its own stand-in - neither can produce the real class.
    """
    try:
        from firebase_admin.auth import UserNotFoundError
        if isinstance(exc, UserNotFoundError):
            return True
    except Exception:
        pass
    return type(exc).__name__ == "UserNotFoundError"


def _still_admin(ctx: AuthContext) -> None:
    """Ask the STORE whether the caller is an admin right now.

    Identity rides on Firebase custom claims, which is what keeps a read at
    zero Firebase lookups - but a claim is a snapshot taken when the ID token
    was minted, and a Firebase token lives an hour. A demoted or deleted admin
    therefore keeps admin claims in their pocket for up to an hour, which is
    long enough to call POST /users and mint themselves a fresh, entirely
    legitimate admin account: the removal undoes itself, and nothing logs it.

    So the three endpoints that CHANGE who can do what pay one Firebase read to
    ask the authority on who is an admin *now*. The read endpoints deliberately
    do not - they cannot escalate anything, and the per-request read budget is
    the reason claims are used at all.
    """
    caller = store.get_user(ctx.tenant_id, ctx.uid)
    if not caller or caller.get("role") != ROLE_ADMIN:
        raise HTTPException(403, "Your account cannot do this.")


# EmailStr is deliberately NOT used. It needs the email-validator package,
# which is in neither requirements.txt nor requirements-ci.txt, and this project
# has lost enough time to dependency pins already - the numpy 1.26.4 floor, the
# duplicate tensorflow, the xgboost that stopped the backend booting. Firebase
# Auth validates the address itself and raises on a bad one, so the only thing a
# second validator would buy is a nicer message for a case the identity provider
# already refuses.
def _looks_like_email(v: str) -> str:
    v = (v or "").strip()
    if "@" not in v or len(v) < 5 or v.startswith("@") or v.endswith("@"):
        raise ValueError("Enter a valid email address.")
    return v


class TenantIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    adminEmail: str = Field(min_length=5, max_length=254)
    adminPassword: str = Field(min_length=8, max_length=128)
    plan: str = Field(default="starter", max_length=40)


@router.post("/tenants")
async def create_tenant(body: TenantIn, request: Request):
    """Provision a customer. Vendor key only - see the module docstring."""
    supplied = request.headers.get("x-api-key", "")
    if not VENDOR_KEY or not hmac.compare_digest(supplied.encode("utf-8"),
                                                 VENDOR_KEY.encode("utf-8")):
        raise HTTPException(401, "This endpoint needs the vendor key.")

    try:
        email = _looks_like_email(body.adminEmail)
    except ValueError as e:
        raise HTTPException(422, str(e))

    mk, claims, _ = _identity()
    tenant_id = store.new_tenant_id()
    try:
        uid = mk(email, body.adminPassword)
    except Exception as e:
        # Nothing was written yet, and nothing may be. A tenant with no admin
        # cannot be logged into and cannot be repaired from the app.
        # The provider's own words are logged, never returned: verbatim they
        # tell the caller whether an address already has an account somewhere
        # on this deployment, which is somebody else's tenant's business.
        _log.warning("tenant provisioning could not create %s: %s", email, e)
        raise HTTPException(409, "Could not create that account.")

    try:
        claims(uid, {"tenantId": tenant_id, "role": ROLE_ADMIN})
        store.create_tenant(tenant_id, body.name, uid, body.plan)
        store.put_user(tenant_id, uid, email, ROLE_ADMIN)
    except Exception:
        # create_tenant may have already written meta.json before put_user
        # failed. A tenant with no admin cannot be logged into and cannot be
        # repaired from the app, so both the auth user AND the half-made
        # tenant must be undone - and one failed undo must not abandon the
        # other. The rollback names the two records provisioning wrote instead
        # of deleting the tenant node; see tenant_store.rollback_new_tenant.
        _log.exception("provisioning tenant %s failed, rolling back", tenant_id)
        _, _, rm = _identity()
        for undo in (lambda: rm(uid),
                     lambda: store.rollback_new_tenant(tenant_id, uid)):
            try:
                undo()
            except Exception:
                _log.exception("rollback step failed for tenant %s", tenant_id)
        raise HTTPException(500, "Could not provision the tenant.")

    return {"status": "success", "tenantId": tenant_id, "adminUid": uid}


@router.get("/users")
async def list_users(ctx: AuthContext = Depends(require_auth)):
    """Everyone in the CALLER'S tenant. The tenant is not a parameter."""
    return {"status": "success", "tenantId": ctx.tenant_id,
            "users": store.list_users(ctx.tenant_id)}


class UserIn(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="viewer")


class RoleIn(BaseModel):
    role: str


def _check_role(role: str) -> str:
    if role not in ROLES:
        raise HTTPException(422, f"Role must be one of {', '.join(ROLES)}.")
    return role


@router.post("/users")
async def add_user(body: UserIn,
                   ctx: AuthContext = Depends(require_role(ROLE_ADMIN))):
    """Create a sub-account inside the caller's own tenant."""
    _still_admin(ctx)
    _check_role(body.role)
    try:
        email = _looks_like_email(body.email)
    except ValueError as e:
        raise HTTPException(422, str(e))
    mk, claims, rm = _identity()
    try:
        uid = mk(email, body.password)
    except Exception as e:
        # Logged, not returned. Verbatim, the provider's message tells one
        # tenant's admin whether an address already has an account in somebody
        # else's tenant on this deployment.
        _log.warning("could not create %s in tenant %s: %s",
                     email, ctx.tenant_id, e)
        raise HTTPException(409, "Could not create that account.")
    try:
        claims(uid, {"tenantId": ctx.tenant_id, "role": body.role})
        rec = store.put_user(ctx.tenant_id, uid, email, body.role)
    except Exception:
        _log.exception("could not add %s to tenant %s, rolling back",
                       email, ctx.tenant_id)
        try:
            rm(uid)
        except Exception:
            _log.exception("could not roll back the auth user %s", uid)
        raise HTTPException(500, "Could not add that user.")
    return {"status": "success", "user": rec}


@router.put("/users/{uid}/role")
async def change_role(uid: str, body: RoleIn,
                      ctx: AuthContext = Depends(require_role(ROLE_ADMIN))):
    _still_admin(ctx)
    role = _check_role(body.role)
    # Looked up INSIDE the caller's tenant, so a uid from elsewhere is simply
    # not found. No cross-tenant check to forget, because there is no path.
    existing = store.get_user(ctx.tenant_id, uid)
    if existing is None:
        raise HTTPException(404, "No such user in your account.")

    if (existing.get("role") == ROLE_ADMIN and role != ROLE_ADMIN
            and store.count_admins(ctx.tenant_id) <= 1):
        raise HTTPException(400, "This is the only admin. Add another admin "
                                 "before changing this one.")

    _, claims, _ = _identity()
    try:
        claims(uid, {"tenantId": ctx.tenant_id, "role": role})
        store.set_role(ctx.tenant_id, uid, role)
    except Exception:
        # Two authorities, written one after the other: if the store write
        # fails the claims already say the new role, and the account would keep
        # a power the store does not grant it. Put the claims back rather than
        # leave the two disagreeing.
        _log.exception("could not change %s to %s in tenant %s",
                       uid, role, ctx.tenant_id)
        if existing.get("role") in ROLES:
            try:
                claims(uid, {"tenantId": ctx.tenant_id,
                             "role": existing["role"]})
            except Exception:
                _log.exception("could not restore the claims of %s", uid)
        raise HTTPException(500, "Could not change that role.")

    # The old ID token still carries the OLD role for up to an hour, in either
    # direction. Cutting the refresh tokens shortens that.
    _revoke_sessions(uid)
    return {"status": "success", "user": store.get_user(ctx.tenant_id, uid)}


@router.delete("/users/{uid}")
async def delete_user(uid: str,
                      ctx: AuthContext = Depends(require_role(ROLE_ADMIN))):
    _still_admin(ctx)
    existing = store.get_user(ctx.tenant_id, uid)
    if existing is None:
        raise HTTPException(404, "No such user in your account.")
    if uid == ctx.uid:
        # The app offers no other way back in; the only remaining route would
        # be a vendor-side repair.
        raise HTTPException(400, "You cannot delete your own account.")
    # Unreachable while the caller must itself be an admin - a lone admin
    # deleting an admin is deleting themselves, and the check above fires
    # first. Kept because that reasoning lives in require_role, not here.
    if (existing.get("role") == ROLE_ADMIN
            and store.count_admins(ctx.tenant_id) <= 1):
        raise HTTPException(400, "This is the only admin.")

    _, _, rm = _identity()
    # Before the delete: deleting an auth user does not invalidate an ID token
    # already issued to it any more than demoting one does.
    _revoke_sessions(uid)
    try:
        rm(uid)
    except Exception as e:
        # An auth user that has already vanished - deleted from the Firebase
        # console, say - must not strand its store record. That record still
        # says `role: admin` to count_admins, which is what lets the real sole
        # admin demote themselves into a tenant with no working admin at all.
        if not _auth_user_already_gone(e):
            _log.exception("could not delete the auth user %s", uid)
            raise HTTPException(500, "Could not remove that user.")
        _log.warning("auth user %s was already gone; clearing its record", uid)
    try:
        store.remove_user(ctx.tenant_id, uid)
    except Exception:
        # The store now raises on a failed delete rather than swallowing it, so
        # this is reachable. Reporting success here would leave a record that
        # count_admins still believes in, behind an auth user that is gone.
        _log.exception("could not remove %s from tenant %s",
                       uid, ctx.tenant_id)
        raise HTTPException(500, "Could not remove that user.")
    return {"status": "success", "removed": uid}
