"""Every Firebase path about tenants and users, in one place.

Isolated for two reasons. The tests need to fake it, and a single module is
where the tenant prefix can later be enforced rather than remembered - Stage 2
moves the farm subtree under /tenants/{id}/farm, and a store that already owns
its own paths is the difference between one edit and a hunt.

The real Firebase helpers are imported LAZILY inside `_fb()`. Importing
smart_care_v2 at module load would drag scikit-learn, PyKrige and the model
bundles into a test run that needs none of them.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from app.services.firebase_auth import ROLE_ADMIN, ROLES

_get: Optional[Callable] = None
_put: Optional[Callable] = None
_delete: Optional[Callable] = None


def set_backend(get, put, delete) -> None:
    """Swap the Firebase layer. Pass (None, None, None) to restore it."""
    global _get, _put, _delete
    _get, _put, _delete = get, put, delete


def _fb():
    if _get is not None:
        return _get, _put, _delete
    from app.api.routes.smart_care_v2 import _fb_delete, _fb_get, _fb_put
    return _fb_get, _fb_put, _fb_delete


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def new_tenant_id() -> str:
    return "t_" + uuid.uuid4().hex[:12]


def create_tenant(tenant_id: str, name: str, owner_uid: str, plan: str) -> dict:
    get, put, _ = _fb()
    meta = {"name": name, "ownerUid": owner_uid, "plan": plan,
            "createdAt": _now()}
    put(f"/tenants/{tenant_id}/meta.json", meta)
    return meta


def get_tenant(tenant_id: str) -> Optional[dict]:
    get, _, _ = _fb()
    return get(f"/tenants/{tenant_id}/meta.json") or None


def list_users(tenant_id: str) -> list:
    get, _, _ = _fb()
    raw = get(f"/tenants/{tenant_id}/users.json") or {}
    if not isinstance(raw, dict):
        return []
    out = []
    for uid, rec in raw.items():
        if not isinstance(rec, dict):
            continue
        out.append({"uid": uid, "email": rec.get("email"),
                    "role": rec.get("role"), "addedAt": rec.get("addedAt")})
    return sorted(out, key=lambda u: u.get("addedAt") or "")


def get_user(tenant_id: str, uid: str) -> Optional[dict]:
    get, _, _ = _fb()
    rec = get(f"/tenants/{tenant_id}/users/{uid}.json")
    if not isinstance(rec, dict):
        return None
    return {"uid": uid, "email": rec.get("email"), "role": rec.get("role"),
            "addedAt": rec.get("addedAt")}


def put_user(tenant_id: str, uid: str, email: Optional[str], role: str) -> dict:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    _, put, _ = _fb()
    rec = {"email": email, "role": role, "addedAt": _now()}
    put(f"/tenants/{tenant_id}/users/{uid}.json", rec)
    return {"uid": uid, **rec}


def set_role(tenant_id: str, uid: str, role: str) -> None:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    get, put, _ = _fb()
    rec = get(f"/tenants/{tenant_id}/users/{uid}.json") or {}
    rec["role"] = role
    put(f"/tenants/{tenant_id}/users/{uid}.json", rec)


def remove_user(tenant_id: str, uid: str) -> None:
    _, _, delete = _fb()
    delete(f"/tenants/{tenant_id}/users/{uid}.json")


def count_admins(tenant_id: str) -> int:
    return sum(1 for u in list_users(tenant_id) if u.get("role") == ROLE_ADMIN)
