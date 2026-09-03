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


def _must(ok, path: str) -> None:
    """Turn a failed Firebase write into an exception.

    The REST helpers report failure by RETURNING FALSE and never by raising -
    `_fb_put` and `_fb_delete` both catch every exception and answer False - so
    a 401 from tightened rules, a 503, and an eight-second timeout all look
    exactly like a successful write from here. accounts.py rolls a half-made
    tenant back only on an exception, so without this that rollback is dead
    code against the real database: the endpoint would answer 200 while the
    admin record it just promised was never stored, leaving a tenant that can
    be signed into and not administered, and which nothing in the app can
    repair.
    """
    if not ok:
        raise RuntimeError(f"firebase write failed: {path}")


def _must_read(rec, path: str) -> dict:
    """A read that did not come back is not an empty record.

    `_fb_get` answers None for a 503 and for a genuinely absent node alike, so
    `get(...) or {}` before a write turns a transient failure into a record
    that has lost every field the caller did not happen to be setting.
    """
    if not isinstance(rec, dict):
        raise RuntimeError(f"firebase read failed: {path}")
    return rec


def new_tenant_id() -> str:
    return "t_" + uuid.uuid4().hex[:12]


def create_tenant(tenant_id: str, name: str, owner_uid: str, plan: str) -> dict:
    _, put, _ = _fb()
    meta = {"name": name, "ownerUid": owner_uid, "plan": plan,
            "createdAt": _now()}
    path = f"/tenants/{tenant_id}/meta.json"
    _must(put(path, meta), path)
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
    path = f"/tenants/{tenant_id}/users/{uid}.json"
    _must(put(path, rec), path)
    return {"uid": uid, **rec}


def set_role(tenant_id: str, uid: str, role: str) -> None:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    get, put, _ = _fb()
    path = f"/tenants/{tenant_id}/users/{uid}.json"
    rec = dict(_must_read(get(path), path))
    rec["role"] = role
    _must(put(path, rec), path)


def remove_user(tenant_id: str, uid: str) -> None:
    _, _, delete = _fb()
    path = f"/tenants/{tenant_id}/users/{uid}.json"
    _must(delete(path), path)


def rollback_new_tenant(tenant_id: str, admin_uid: str) -> None:
    """Undo exactly the two records a failed provisioning may have written.

    There is deliberately NO delete of /tenants/{id}.json here. That path
    cascades over the entire subtree, and Stage 2 moves every house, section,
    plan, tray, pump config and history record beneath it - at which point a
    call named "delete the tenant", made from inside a broad `except
    Exception`, is one wrong branch away from erasing a customer's whole farm
    on a system that runs real pumps. Naming the two paths provisioning
    actually wrote cannot grow that reach by accident, and needs no clock.

    Both deletes are attempted even if the first fails, because a half-made
    tenant with no admin cannot be logged into and cannot be repaired from the
    app - one failed undo must not abandon the other. Whatever failed is then
    raised, so the caller can log it rather than believe the cleanup worked.
    """
    _, _, delete = _fb()
    failed = []
    for path in (f"/tenants/{tenant_id}/users/{admin_uid}.json",
                 f"/tenants/{tenant_id}/meta.json"):
        try:
            if not delete(path):
                failed.append(path)
        except Exception:
            failed.append(path)
    if failed:
        raise RuntimeError("firebase rollback failed: " + ", ".join(failed))


def count_admins(tenant_id: str) -> int:
    return sum(1 for u in list_users(tenant_id) if u.get("role") == ROLE_ADMIN)
