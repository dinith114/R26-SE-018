"""Turn an Authorization header into an identity, or into nothing.

THE ONLY MODULE THAT IMPORTS firebase_admin FOR AUTH, and it does so inside the
function rather than at module load. Two reasons, both already learned the hard
way on this project: CI installs a trimmed requirements file that has no
firebase-admin in it, and `app/api/routes/__init__.py` has to stay import-free
so one absent dependency cannot stop the whole backend booting.

Identity rides on Firebase CUSTOM CLAIMS, not on a database lookup. The admin
SDK stamps tenantId and role onto the user when the account is created, so they
arrive inside the verified token and cost no Firebase read per request.

Every failure is the same answer: None. A caller cannot act differently on
"expired" than on "forged" than on "no tenant" - all three mean this request has
no identity - so there is nothing to gain from distinguishing them here, and a
raised exception would only invite a route to leak the reason.

`auth_client()` is the second entry point into the same app. A later
tenant-provisioning route runs on a static vendor key with no bearer token, so
`_firebase_decode` never runs and never initialises the app on its own. Without
a shared accessor that route would fall through to the default Firebase app,
which this project never initialises, and fail with "The default Firebase app
does not exist." Both entry points share one `_auth_app` global so there is
exactly one app, initialised once, whichever gets there first.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable, Optional

ROLE_ADMIN = "admin"
ROLE_OPERATOR = "operator"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER)

# Same key the push path uses. One service account, two uses.
FIREBASE_KEY_DEFAULT = os.path.join(
    os.path.expanduser("~"), ".orchid-secrets", "firebase-admin.json")

_auth_app = None
_decoder: Optional[Callable[[str], dict]] = None


@dataclass(frozen=True)
class AuthContext:
    uid: str
    tenant_id: str
    role: str
    email: Optional[str] = None


def set_decoder(fn: Optional[Callable[[str], dict]]) -> None:
    """Replace the Firebase call. Pass None to restore it.

    The seam exists so the tests exercise OUR rules - what counts as a usable
    identity - without a network, a project, or a key.
    """
    global _decoder
    _decoder = fn


def auth_client():
    """The firebase_admin app for auth, initialised on demand.

    Task 4's tenant-provisioning route runs on a vendor key with no bearer
    token, so nothing will have verified a token by the time it needs to
    create a user. Without this it would fall through to the default
    Firebase app, which this project never initialises.
    """
    global _auth_app
    if _auth_app is not None:
        return _auth_app

    # Checked BEFORE the import: it is the cheaper failure, and it is the
    # one that must behave identically whether or not firebase-admin is
    # installed. CI runs on a trimmed requirements file without it, so an
    # import-first order would fail there with ModuleNotFoundError and a
    # test asserting on the missing-key path would pass for the wrong reason.
    path = os.environ.get("FIREBASE_ADMIN_KEY") or FIREBASE_KEY_DEFAULT
    if not os.path.exists(path):
        raise RuntimeError(f"no service-account key at {path}")
    import firebase_admin
    from firebase_admin import credentials
    _auth_app = firebase_admin.initialize_app(
        credentials.Certificate(path), name="orchid-auth")
    return _auth_app


def _firebase_decode(token: str) -> dict:
    """Verify against Firebase. Raises when the token is not good."""
    from firebase_admin import auth as fb_auth

    app = auth_client()
    return fb_auth.verify_id_token(token, app=app)


def verify_bearer(header_value: Optional[str]) -> Optional[AuthContext]:
    """`Authorization: Bearer <idToken>` -> AuthContext, or None."""
    if not header_value:
        return None
    parts = header_value.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    decode = _decoder or _firebase_decode
    try:
        claims = decode(parts[1].strip())
    except Exception:
        return None
    if not isinstance(claims, dict):
        return None

    uid = claims.get("uid") or claims.get("user_id") or claims.get("sub")
    tenant_id = claims.get("tenantId")
    role = claims.get("role")
    # A token can be perfectly valid and still not tell us whose farm this is.
    if not uid or not tenant_id or role not in ROLES:
        return None
    return AuthContext(uid=str(uid), tenant_id=str(tenant_id), role=str(role),
                       email=claims.get("email"))
