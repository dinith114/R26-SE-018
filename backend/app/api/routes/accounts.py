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

import os
from typing import Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.api.deps import require_auth
from app.services import tenant_store as store
from app.services.firebase_auth import ROLE_ADMIN, AuthContext

router = APIRouter()

VENDOR_KEY = os.environ.get("ORCHID_API_KEY", "").strip()

_create_user: Optional[Callable] = None
_set_claims: Optional[Callable] = None
_delete_user: Optional[Callable] = None


def set_identity_backend(create_user, set_claims, delete_user) -> None:
    """Swap the three admin-SDK calls. Pass (None, None, None) to restore."""
    global _create_user, _set_claims, _delete_user
    _create_user, _set_claims, _delete_user = create_user, set_claims, delete_user


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
    if not VENDOR_KEY or request.headers.get("x-api-key", "") != VENDOR_KEY:
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
        raise HTTPException(409, f"Could not create that account: {e}")

    try:
        claims(uid, {"tenantId": tenant_id, "role": ROLE_ADMIN})
        store.create_tenant(tenant_id, body.name, uid, body.plan)
        store.put_user(tenant_id, uid, email, ROLE_ADMIN)
    except Exception as e:
        # create_tenant may have already written meta.json before put_user
        # raised. A tenant with no admin cannot be logged into and cannot be
        # repaired from the app, so both the auth user AND the half-made
        # tenant must be undone - and one failed undo must not abandon the
        # other.
        _, _, rm = _identity()
        for undo in (lambda: rm(uid), lambda: store.delete_tenant(tenant_id)):
            try:
                undo()
            except Exception:
                pass
        raise HTTPException(500, f"Could not provision the tenant: {e}")

    return {"status": "success", "tenantId": tenant_id, "adminUid": uid}


@router.get("/users")
async def list_users(ctx: AuthContext = Depends(require_auth)):
    """Everyone in the CALLER'S tenant. The tenant is not a parameter."""
    return {"status": "success", "tenantId": ctx.tenant_id,
            "users": store.list_users(ctx.tenant_id)}
