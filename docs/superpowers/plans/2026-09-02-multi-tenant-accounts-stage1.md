# Multi-Tenant Accounts — Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add real accounts to the backend — Firebase ID-token verification, Admin/Operator/Viewer role enforcement, and a tenant/user management API — without changing any existing endpoint's behaviour.

**Architecture:** Three new isolated units. `app/services/firebase_auth.py` turns a bearer token into an `AuthContext` and owns the only `firebase_admin` import. `app/services/tenant_store.py` owns every Firebase read/write about tenants and users. `app/api/routes/accounts.py` is a thin HTTP layer over the store, guarded by `app/api/deps.py`. Both services take an injectable seam so tests never touch a real Firebase project.

**Tech Stack:** FastAPI 0.115.0, pydantic 2.9.0, firebase-admin 6.5.0 (lazily imported), pytest 8.3.0, `fastapi.testclient.TestClient` (needs httpx 0.27.0).

**Spec:** `docs/superpowers/specs/2026-09-02-multi-tenant-accounts-design.md`

## Global Constraints

- **Nothing existing may change behaviour.** The `X-API-Key` middleware in `app/main.py` stays exactly as it is. Do not remove it, do not narrow it, do not exempt paths from it. The live mobile app still authenticates with that static key and has no login screen until Stage 4; weakening the middleware now breaks the app in the field.
- **`firebase_admin` must NOT be imported at module load.** Import it inside the function that needs it, matching the existing `_fcm()` pattern at `app/api/routes/automation.py:217`. CI installs `requirements-ci.txt`, which does not include `firebase-admin`, and `app/api/routes/__init__.py` must stay import-free so a missing dependency cannot stop the whole backend booting.
- **A missing service-account key must never raise.** Same rule as FCM: return `None` and let the caller answer 503. The farm has to keep watering whether or not anyone can log in.
- Roles are exactly `"admin"`, `"operator"`, `"viewer"` — lowercase, no others.
- Python 3.12 on the server, 3.13 locally. No syntax newer than 3.12.
- Commit messages: plain sentences. No `feat:`/`chore:` prefixes. Never a `Co-Authored-By` trailer.
- Tenant IDs are generated server-side as `"t_" + uuid4().hex[:12]`. Never accept a client-supplied tenant id on create.

---

### Task 1: Auth context and token verification

The only module in the codebase that knows what a Firebase ID token is.

**Files:**
- Create: `backend/app/services/firebase_auth.py`
- Create: `backend/tests/test_firebase_auth.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `ROLE_ADMIN: str = "admin"`, `ROLE_OPERATOR: str = "operator"`, `ROLE_VIEWER: str = "viewer"`, `ROLES: tuple[str, ...]`
  - `@dataclass(frozen=True) class AuthContext: uid: str; tenant_id: str; role: str; email: str | None`
  - `verify_bearer(header_value: str | None) -> AuthContext | None`
  - `set_decoder(fn: Callable[[str], dict] | None) -> None` — test seam; `None` restores the real Firebase decoder.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_firebase_auth.py`:

```python
"""Token verification, with no Firebase project in the loop.

`set_decoder` replaces the one function that talks to Firebase, so every case
below is about OUR logic: what we accept, what we refuse, and what we refuse to
guess at. A token that verifies cryptographically but carries no tenant is
still useless to us, and saying so here is cheaper than discovering it in a
route.
"""
import pytest

from app.services.firebase_auth import (
    ROLE_ADMIN, ROLE_VIEWER, AuthContext, set_decoder, verify_bearer,
)


@pytest.fixture(autouse=True)
def _restore_decoder():
    yield
    set_decoder(None)


def _decoder_returning(claims):
    def _decode(token):
        assert token == "good-token"
        return claims
    return _decode


def test_valid_token_becomes_an_auth_context():
    set_decoder(_decoder_returning({
        "uid": "u1", "tenantId": "t_abc", "role": ROLE_ADMIN,
        "email": "grower@example.com",
    }))
    ctx = verify_bearer("Bearer good-token")
    assert ctx == AuthContext(uid="u1", tenant_id="t_abc", role=ROLE_ADMIN,
                              email="grower@example.com")


def test_email_is_optional():
    set_decoder(_decoder_returning({"uid": "u1", "tenantId": "t_abc",
                                    "role": ROLE_VIEWER}))
    assert verify_bearer("Bearer good-token").email is None


def test_token_without_a_tenant_is_refused():
    """Cryptographically fine and still unusable: we would not know whose farm
    to show. Refuse rather than fall back to any default."""
    set_decoder(_decoder_returning({"uid": "u1", "role": ROLE_ADMIN}))
    assert verify_bearer("Bearer good-token") is None


def test_token_with_an_unknown_role_is_refused():
    set_decoder(_decoder_returning({"uid": "u1", "tenantId": "t_abc",
                                    "role": "superuser"}))
    assert verify_bearer("Bearer good-token") is None


def test_missing_or_malformed_header_is_refused():
    set_decoder(_decoder_returning({"uid": "u1", "tenantId": "t_abc",
                                    "role": ROLE_ADMIN}))
    assert verify_bearer(None) is None
    assert verify_bearer("") is None
    assert verify_bearer("good-token") is None          # no scheme
    assert verify_bearer("Basic good-token") is None    # wrong scheme


def test_a_decoder_that_raises_is_a_refusal_not_a_crash():
    def _boom(token):
        raise ValueError("expired")
    set_decoder(_boom)
    assert verify_bearer("Bearer good-token") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_firebase_auth.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.firebase_auth'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/services/firebase_auth.py`:

```python
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


def _firebase_decode(token: str) -> dict:
    """Verify against Firebase. Raises when the token is not good."""
    global _auth_app
    import firebase_admin
    from firebase_admin import auth as fb_auth, credentials

    if _auth_app is None:
        path = os.environ.get("FIREBASE_ADMIN_KEY") or FIREBASE_KEY_DEFAULT
        if not os.path.exists(path):
            raise RuntimeError(f"no service-account key at {path}")
        _auth_app = firebase_admin.initialize_app(
            credentials.Certificate(path), name="orchid-auth")
    return fb_auth.verify_id_token(token, app=_auth_app)


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_firebase_auth.py -q`
Expected: PASS, 6 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/firebase_auth.py backend/tests/test_firebase_auth.py
git commit -m "Verify Firebase ID tokens into an AuthContext

Identity rides on custom claims rather than a database lookup, so a request
costs no Firebase read to answer who is asking. firebase_admin is imported
inside the function, not at module load: CI installs a trimmed requirements
file without it, and the routes package has to stay import-free so one missing
dependency cannot stop the backend booting.

Every failure returns None rather than raising. A caller cannot usefully act
differently on expired, forged, or no-tenant - all three mean the request has
no identity - and an exception would invite a route to leak which."
```

---

### Task 2: Route guards

**Files:**
- Create: `backend/app/api/deps.py`
- Create: `backend/tests/test_auth_deps.py`

**Interfaces:**
- Consumes: `AuthContext`, `ROLE_ADMIN`, `ROLE_OPERATOR`, `ROLE_VIEWER`, `verify_bearer` from `app.services.firebase_auth`.
- Produces:
  - `require_auth(request: Request) -> AuthContext` — a FastAPI dependency; raises `HTTPException(401)`.
  - `require_role(*allowed: str) -> Callable[..., AuthContext]` — dependency factory; raises `HTTPException(403)`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_auth_deps.py`:

```python
"""What the guards let through, proved against a real router.

A throwaway FastAPI app rather than calling the dependencies directly: these
only mean anything as FastAPI dependencies, and testing them outside that
machinery would test a function that resembles the shipped behaviour instead of
the shipped behaviour itself.
"""
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import require_auth, require_role
from app.services.firebase_auth import (
    ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER, AuthContext, set_decoder,
)

# token -> claims. The tests speak in these three identities.
_PEOPLE = {
    "admin-a": {"uid": "ua", "tenantId": "t_a", "role": ROLE_ADMIN},
    "operator-a": {"uid": "oa", "tenantId": "t_a", "role": ROLE_OPERATOR},
    "viewer-a": {"uid": "va", "tenantId": "t_a", "role": ROLE_VIEWER},
}


@pytest.fixture(autouse=True)
def _decoder():
    def _decode(token):
        if token not in _PEOPLE:
            raise ValueError("unknown token")
        return _PEOPLE[token]
    set_decoder(_decode)
    yield
    set_decoder(None)


@pytest.fixture
def client():
    app = FastAPI()

    @app.get("/who")
    def who(ctx: AuthContext = Depends(require_auth)):
        return {"uid": ctx.uid, "tenant": ctx.tenant_id, "role": ctx.role}

    @app.post("/act")
    def act(ctx: AuthContext = Depends(require_role(ROLE_ADMIN, ROLE_OPERATOR))):
        return {"ok": True}

    @app.post("/configure")
    def configure(ctx: AuthContext = Depends(require_role(ROLE_ADMIN))):
        return {"ok": True}

    return TestClient(app)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_no_header_is_401(client):
    assert client.get("/who").status_code == 401


def test_bad_token_is_401(client):
    assert client.get("/who", headers=_auth("nonsense")).status_code == 401


def test_valid_token_reaches_the_route_with_its_identity(client):
    r = client.get("/who", headers=_auth("operator-a"))
    assert r.status_code == 200
    assert r.json() == {"uid": "oa", "tenant": "t_a", "role": ROLE_OPERATOR}


def test_operator_may_act_but_not_configure(client):
    assert client.post("/act", headers=_auth("operator-a")).status_code == 200
    assert client.post("/configure", headers=_auth("operator-a")).status_code == 403


def test_viewer_may_read_but_not_act(client):
    assert client.get("/who", headers=_auth("viewer-a")).status_code == 200
    assert client.post("/act", headers=_auth("viewer-a")).status_code == 403


def test_admin_may_do_both(client):
    assert client.post("/act", headers=_auth("admin-a")).status_code == 200
    assert client.post("/configure", headers=_auth("admin-a")).status_code == 200


def test_a_refusal_never_says_which_role_was_needed(client):
    """403 tells the caller they may not; it does not teach them the role
    hierarchy or confirm the endpoint's shape."""
    body = client.post("/configure", headers=_auth("viewer-a")).json()
    assert ROLE_ADMIN not in str(body)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_auth_deps.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.deps'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/api/deps.py`:

```python
"""The two dependencies every guarded route uses.

Deliberately only two. Per-house access lists were considered and rejected in
the design: a tenant is one grower's operation, and a role that applies across
it is the whole of what this product needs. Adding a third axis here would be
paid for on every route and used by none.
"""
from __future__ import annotations

from fastapi import HTTPException, Request

from app.services.firebase_auth import AuthContext, verify_bearer


def require_auth(request: Request) -> AuthContext:
    """Any signed-in member of any tenant."""
    ctx = verify_bearer(request.headers.get("authorization"))
    if ctx is None:
        raise HTTPException(401, "Please sign in.")
    # Handy for logging and for routes that would rather read request.state.
    request.state.auth = ctx
    return ctx


def require_role(*allowed: str):
    """Membership plus one of `allowed`.

    The message names neither the required role nor the caller's own. A refusal
    should not double as documentation of the permission model for somebody
    probing the API.
    """
    def _dep(request: Request) -> AuthContext:
        ctx = require_auth(request)
        if ctx.role not in allowed:
            raise HTTPException(403, "Your account cannot do this.")
        return ctx
    return _dep
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_auth_deps.py -q`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/deps.py backend/tests/test_auth_deps.py
git commit -m "Add require_auth and require_role route guards

Tested through a throwaway FastAPI app rather than by calling the functions:
these only mean anything as FastAPI dependencies, and testing them outside that
machinery would prove something that resembles the shipped behaviour rather
than the shipped behaviour.

A 403 names neither the required role nor the caller's own, so a refusal does
not double as documentation of the permission model for somebody probing."
```

---

### Task 3: Tenant and user store

Every Firebase path about accounts lives here, and nowhere else.

**Files:**
- Create: `backend/app/services/tenant_store.py`
- Create: `backend/tests/test_tenant_store.py`

**Interfaces:**
- Consumes: `ROLES` from `app.services.firebase_auth`.
- Produces:
  - `set_backend(get, put, delete)` — test seam; pass `(None, None, None)` to restore the real Firebase helpers.
  - `new_tenant_id() -> str`
  - `create_tenant(tenant_id: str, name: str, owner_uid: str, plan: str) -> dict`
  - `get_tenant(tenant_id: str) -> dict | None`
  - `list_users(tenant_id: str) -> list[dict]` — each `{"uid", "email", "role", "addedAt"}`
  - `get_user(tenant_id: str, uid: str) -> dict | None`
  - `put_user(tenant_id: str, uid: str, email: str | None, role: str) -> dict`
  - `set_role(tenant_id: str, uid: str, role: str) -> None`
  - `remove_user(tenant_id: str, uid: str) -> None`
  - `count_admins(tenant_id: str) -> int`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tenant_store.py`:

```python
"""The store's own rules, against a dict standing in for Firebase.

The point of these is the two guards that protect a tenant from locking itself
out - the last admin, and a uid that belongs to somebody else's tenant. Both
are the kind of thing that reads as obviously handled and turns out not to be.
"""
import pytest

from app.services import tenant_store as store
from app.services.firebase_auth import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER


@pytest.fixture(autouse=True)
def fake_db():
    """A dict shaped like the Realtime Database paths the store uses."""
    db = {}

    def _get(path):
        return db.get(path)

    def _put(path, value):
        db[path] = value
        return value

    def _delete(path):
        db.pop(path, None)
        return True

    store.set_backend(_get, _put, _delete)
    yield db
    store.set_backend(None, None, None)


def _tenant_with_admin():
    tid = store.new_tenant_id()
    store.create_tenant(tid, "Green Acres", "ua", "starter")
    store.put_user(tid, "ua", "admin@example.com", ROLE_ADMIN)
    return tid


def test_new_tenant_ids_are_prefixed_and_unique():
    a, b = store.new_tenant_id(), store.new_tenant_id()
    assert a.startswith("t_") and b.startswith("t_")
    assert a != b


def test_create_then_read_a_tenant():
    tid = _tenant_with_admin()
    t = store.get_tenant(tid)
    assert t["name"] == "Green Acres"
    assert t["ownerUid"] == "ua"
    assert t["plan"] == "starter"
    assert t["createdAt"]


def test_get_tenant_that_does_not_exist_is_none():
    assert store.get_tenant("t_nope") is None


def test_users_are_listed_with_their_role():
    tid = _tenant_with_admin()
    store.put_user(tid, "ob", "op@example.com", ROLE_OPERATOR)
    got = {u["uid"]: u["role"] for u in store.list_users(tid)}
    assert got == {"ua": ROLE_ADMIN, "ob": ROLE_OPERATOR}


def test_listing_a_tenant_with_no_users_is_empty_not_an_error():
    assert store.list_users("t_nope") == []


def test_set_role_changes_only_that_user():
    tid = _tenant_with_admin()
    store.put_user(tid, "ob", "op@example.com", ROLE_OPERATOR)
    store.set_role(tid, "ob", ROLE_VIEWER)
    assert store.get_user(tid, "ob")["role"] == ROLE_VIEWER
    assert store.get_user(tid, "ua")["role"] == ROLE_ADMIN


def test_put_user_rejects_an_unknown_role():
    tid = _tenant_with_admin()
    with pytest.raises(ValueError):
        store.put_user(tid, "oc", "x@example.com", "superuser")


def test_remove_user():
    tid = _tenant_with_admin()
    store.put_user(tid, "ob", "op@example.com", ROLE_OPERATOR)
    store.remove_user(tid, "ob")
    assert store.get_user(tid, "ob") is None
    assert [u["uid"] for u in store.list_users(tid)] == ["ua"]


def test_count_admins_tracks_role_changes():
    tid = _tenant_with_admin()
    assert store.count_admins(tid) == 1
    store.put_user(tid, "ob", "b@example.com", ROLE_ADMIN)
    assert store.count_admins(tid) == 2
    store.set_role(tid, "ob", ROLE_VIEWER)
    assert store.count_admins(tid) == 1


def test_one_tenants_user_is_invisible_to_another():
    """The isolation this whole design exists for, at the storage layer."""
    a = _tenant_with_admin()
    b = store.new_tenant_id()
    store.create_tenant(b, "Other Farm", "ux", "starter")
    store.put_user(b, "ux", "x@example.com", ROLE_ADMIN)

    assert store.get_user(a, "ux") is None
    assert store.get_user(b, "ua") is None
    assert [u["uid"] for u in store.list_users(a)] == ["ua"]
    assert [u["uid"] for u in store.list_users(b)] == ["ux"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_tenant_store.py -q`
Expected: FAIL — `ImportError: cannot import name 'tenant_store' from 'app.services'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/services/tenant_store.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_tenant_store.py -q`
Expected: PASS, 10 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/tenant_store.py backend/tests/test_tenant_store.py
git commit -m "Put every tenant and user Firebase path in one store

Isolated so the tests can fake it, and so Stage 2 has one module to edit when
the farm subtree moves under /tenants/{id}/farm rather than a hunt through six
route files.

The Firebase helpers are imported lazily inside _fb(): importing smart_care_v2
at module load would drag scikit-learn, PyKrige and the model bundles into a
test run that needs none of them."
```

---

### Task 4: Accounts router — bootstrap and read

**Files:**
- Create: `backend/app/api/routes/accounts.py`
- Create: `backend/tests/test_accounts_api.py`

**Interfaces:**
- Consumes: `require_auth` from `app.api.deps`; the whole `tenant_store` surface; `ROLES` from `app.services.firebase_auth`.
- Produces:
  - `router: APIRouter` — mounted at `/api/v2/accounts` in Task 6.
  - `set_identity_backend(create_user, set_claims, delete_user)` — test seam over the three `firebase_admin.auth` calls; pass `(None, None, None)` to restore.
  - `POST /tenants` -> `{"status", "tenantId", "adminUid"}`
  - `GET /users` -> `{"status", "tenantId", "users": [...]}`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_accounts_api.py`:

```python
"""The accounts API, with Firebase Auth and the database both faked.

Two seams: `tenant_store.set_backend` for the data, and
`accounts.set_identity_backend` for the three admin-SDK calls that create a
user, stamp its claims, and delete it. Between them these tests run offline and
still exercise the real routing, the real guards and the real refusals.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import accounts
from app.services import tenant_store as store
from app.services.firebase_auth import (
    ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER, set_decoder,
)

VENDOR_KEY = "vendor-key-for-tests"


@pytest.fixture
def env(monkeypatch):
    """Fake database, fake identity provider, fake tokens, one client."""
    db, users = {}, {}

    store.set_backend(
        lambda p: db.get(p),
        lambda p, v: db.__setitem__(p, v) or v,
        lambda p: db.pop(p, None) is not None,
    )

    def _create_user(email, password):
        if any(u["email"] == email for u in users.values()):
            raise ValueError("email already exists")
        uid = f"uid{len(users) + 1}"
        users[uid] = {"email": email, "claims": {}}
        return uid

    def _set_claims(uid, claims):
        users[uid]["claims"] = claims

    def _delete_user(uid):
        users.pop(uid, None)

    accounts.set_identity_backend(_create_user, _set_claims, _delete_user)
    monkeypatch.setattr(accounts, "VENDOR_KEY", VENDOR_KEY)

    # Tokens are "<uid>@<tenant>@<role>" so a test can mint any identity.
    def _decode(token):
        uid, tenant, role = token.split("@")
        return {"uid": uid, "tenantId": tenant, "role": role,
                "email": users.get(uid, {}).get("email")}
    set_decoder(_decode)

    app = FastAPI()
    app.include_router(accounts.router, prefix="/api/v2/accounts")
    yield TestClient(app), db, users

    store.set_backend(None, None, None)
    accounts.set_identity_backend(None, None, None)
    set_decoder(None)


def _tok(uid, tenant, role):
    return {"Authorization": f"Bearer {uid}@{tenant}@{role}"}


def _make_tenant(client, name="Green Acres", email="admin@example.com"):
    r = client.post("/api/v2/accounts/tenants",
                    headers={"X-API-Key": VENDOR_KEY},
                    json={"name": name, "adminEmail": email,
                          "adminPassword": "sup3rsecret", "plan": "starter"})
    assert r.status_code == 200, r.text
    return r.json()


def test_creating_a_tenant_needs_the_vendor_key(env):
    client, _, _ = env
    r = client.post("/api/v2/accounts/tenants",
                    json={"name": "X", "adminEmail": "a@b.c",
                          "adminPassword": "sup3rsecret"})
    assert r.status_code == 401


def test_creating_a_tenant_makes_an_admin_with_claims(env):
    client, db, users = env
    body = _make_tenant(client)
    tid, uid = body["tenantId"], body["adminUid"]

    assert tid.startswith("t_")
    assert users[uid]["claims"] == {"tenantId": tid, "role": ROLE_ADMIN}
    assert store.get_tenant(tid)["name"] == "Green Acres"
    assert [u["role"] for u in store.list_users(tid)] == [ROLE_ADMIN]


def test_a_duplicate_admin_email_is_refused_and_leaves_no_tenant(env):
    """The identity provider fails AFTER a tenant id has been minted. Nothing
    half-made may survive that, or the next list shows a tenant with no admin."""
    client, db, _ = env
    _make_tenant(client, email="taken@example.com")
    before = dict(db)

    r = client.post("/api/v2/accounts/tenants",
                    headers={"X-API-Key": VENDOR_KEY},
                    json={"name": "Second", "adminEmail": "taken@example.com",
                          "adminPassword": "sup3rsecret"})
    assert r.status_code == 409
    assert db == before


def test_a_short_password_is_refused(env):
    client, _, _ = env
    r = client.post("/api/v2/accounts/tenants",
                    headers={"X-API-Key": VENDOR_KEY},
                    json={"name": "X", "adminEmail": "a@b.c",
                          "adminPassword": "short"})
    assert r.status_code == 422


def test_listing_users_needs_a_token(env):
    client, _, _ = env
    _make_tenant(client)
    assert client.get("/api/v2/accounts/users").status_code == 401


def test_every_role_may_list_its_own_users(env):
    client, _, _ = env
    tid = _make_tenant(client)["tenantId"]
    for role in (ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER):
        r = client.get("/api/v2/accounts/users", headers=_tok("u9", tid, role))
        assert r.status_code == 200
        assert r.json()["tenantId"] == tid


def test_a_token_for_another_tenant_sees_nothing_of_this_one(env):
    """Tenant isolation at the API. The token is valid; it is simply somebody
    else's, and the response must be shaped by the token, never by a parameter."""
    client, _, _ = env
    a = _make_tenant(client, name="Farm A", email="a@example.com")["tenantId"]
    b = _make_tenant(client, name="Farm B", email="b@example.com")["tenantId"]

    r = client.get("/api/v2/accounts/users", headers=_tok("ub", b, ROLE_ADMIN))
    assert r.status_code == 200
    assert r.json()["tenantId"] == b
    emails = {u["email"] for u in r.json()["users"]}
    assert emails == {"b@example.com"}
    assert a not in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_accounts_api.py -q`
Expected: FAIL — `ImportError: cannot import name 'accounts' from 'app.api.routes'`

- [ ] **Step 3: Write minimal implementation**

Create `backend/app/api/routes/accounts.py`:

```python
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
from app.services.firebase_auth import ROLE_ADMIN, ROLES, AuthContext

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

    def _mk(email, password):
        return fb_auth.create_user(email=email, password=password).uid

    def _claims(uid, claims):
        fb_auth.set_custom_user_claims(uid, claims)

    def _rm(uid):
        fb_auth.delete_user(uid)

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
        _, _, rm = _identity()
        try:
            rm(uid)
        except Exception:
            pass
        raise HTTPException(500, f"Could not provision the tenant: {e}")

    return {"status": "success", "tenantId": tenant_id, "adminUid": uid}


@router.get("/users")
async def list_users(ctx: AuthContext = Depends(require_auth)):
    """Everyone in the CALLER'S tenant. The tenant is not a parameter."""
    return {"status": "success", "tenantId": ctx.tenant_id,
            "users": store.list_users(ctx.tenant_id)}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_accounts_api.py -q`
Expected: PASS, 7 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/accounts.py backend/tests/test_accounts_api.py
git commit -m "Add tenant provisioning and user listing

A plan is sold and the vendor provisions the tenant; there is no signup form,
so POST /tenants is guarded by the static key - the right tool for the one
endpoint that must work before any account exists to authenticate as.

The tenant is never a request parameter. It is read off the verified token, so
there is no request anyone can shape that reaches another tenant's data.

If the identity provider refuses the admin email, the half-made tenant is not
written: a tenant with no admin cannot be logged into and cannot be repaired
from the app."
```

---

### Task 5: Accounts router — create, change role, delete

**Files:**
- Modify: `backend/app/api/routes/accounts.py` (append)
- Modify: `backend/tests/test_accounts_api.py` (append)

**Interfaces:**
- Consumes: everything from Task 4, plus `require_role` from `app.api.deps`.
- Produces:
  - `POST /users` -> `{"status", "user": {"uid", "email", "role", "addedAt"}}`
  - `PUT /users/{uid}/role` -> `{"status", "user": {...}}`
  - `DELETE /users/{uid}` -> `{"status", "removed": uid}`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_accounts_api.py`:

```python
# ── user management ────────────────────────────────────────────────────────

def _add(client, tid, email, role):
    return client.post("/api/v2/accounts/users",
                       headers=_tok("ua", tid, ROLE_ADMIN),
                       json={"email": email, "password": "sup3rsecret",
                             "role": role})


def test_admin_creates_an_operator_with_the_right_claims(env):
    client, _, users = env
    tid = _make_tenant(client)["tenantId"]
    r = _add(client, tid, "op@example.com", ROLE_OPERATOR)
    assert r.status_code == 200, r.text
    uid = r.json()["user"]["uid"]
    assert users[uid]["claims"] == {"tenantId": tid, "role": ROLE_OPERATOR}
    assert store.get_user(tid, uid)["role"] == ROLE_OPERATOR


def test_operator_and_viewer_cannot_create_users(env):
    client, _, _ = env
    tid = _make_tenant(client)["tenantId"]
    for role in (ROLE_OPERATOR, ROLE_VIEWER):
        r = client.post("/api/v2/accounts/users", headers=_tok("u9", tid, role),
                        json={"email": "x@example.com",
                              "password": "sup3rsecret", "role": ROLE_VIEWER})
        assert r.status_code == 403


def test_creating_a_user_with_an_unknown_role_is_refused(env):
    client, _, _ = env
    tid = _make_tenant(client)["tenantId"]
    r = _add(client, tid, "x@example.com", "superuser")
    assert r.status_code == 422


def test_admin_changes_a_role_and_the_claims_follow(env):
    client, _, users = env
    tid = _make_tenant(client)["tenantId"]
    uid = _add(client, tid, "op@example.com", ROLE_OPERATOR).json()["user"]["uid"]

    r = client.put(f"/api/v2/accounts/users/{uid}/role",
                   headers=_tok("ua", tid, ROLE_ADMIN),
                   json={"role": ROLE_VIEWER})
    assert r.status_code == 200
    assert store.get_user(tid, uid)["role"] == ROLE_VIEWER
    assert users[uid]["claims"]["role"] == ROLE_VIEWER


def test_admin_deletes_a_user_from_both_places(env):
    client, _, users = env
    tid = _make_tenant(client)["tenantId"]
    uid = _add(client, tid, "op@example.com", ROLE_OPERATOR).json()["user"]["uid"]

    r = client.delete(f"/api/v2/accounts/users/{uid}",
                      headers=_tok("ua", tid, ROLE_ADMIN))
    assert r.status_code == 200
    assert store.get_user(tid, uid) is None
    assert uid not in users


def test_an_admin_cannot_delete_themselves(env):
    """Not paternalism: the app offers no other way back in, and the only
    remaining route would be a vendor-side repair."""
    client, _, _ = env
    body = _make_tenant(client)
    tid, uid = body["tenantId"], body["adminUid"]
    r = client.delete(f"/api/v2/accounts/users/{uid}",
                      headers=_tok(uid, tid, ROLE_ADMIN))
    assert r.status_code == 400
    assert store.get_user(tid, uid) is not None


def test_the_last_admin_cannot_be_demoted(env):
    client, _, _ = env
    body = _make_tenant(client)
    tid, uid = body["tenantId"], body["adminUid"]
    r = client.put(f"/api/v2/accounts/users/{uid}/role",
                   headers=_tok(uid, tid, ROLE_ADMIN),
                   json={"role": ROLE_VIEWER})
    assert r.status_code == 400
    assert store.get_user(tid, uid)["role"] == ROLE_ADMIN


def test_a_second_admin_makes_demotion_allowed(env):
    client, _, _ = env
    body = _make_tenant(client)
    tid, first = body["tenantId"], body["adminUid"]
    _add(client, tid, "admin2@example.com", ROLE_ADMIN)

    r = client.put(f"/api/v2/accounts/users/{first}/role",
                   headers=_tok(first, tid, ROLE_ADMIN),
                   json={"role": ROLE_VIEWER})
    assert r.status_code == 200
    assert store.count_admins(tid) == 1


def test_an_admin_cannot_touch_a_user_in_another_tenant(env):
    """The isolation test that matters most: a real admin, a real uid, and the
    only thing wrong is that they belong to different tenants."""
    client, _, _ = env
    a = _make_tenant(client, name="Farm A", email="a@example.com")["tenantId"]
    b = _make_tenant(client, name="Farm B", email="b@example.com")["tenantId"]
    victim = _add(client, b, "worker@example.com", ROLE_OPERATOR).json()["user"]["uid"]

    hdr = _tok("ua", a, ROLE_ADMIN)
    assert client.delete(f"/api/v2/accounts/users/{victim}",
                         headers=hdr).status_code == 404
    assert client.put(f"/api/v2/accounts/users/{victim}/role",
                      headers=hdr, json={"role": ROLE_VIEWER}).status_code == 404
    assert store.get_user(b, victim)["role"] == ROLE_OPERATOR
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_accounts_api.py -q`
Expected: FAIL — 405 Method Not Allowed / 404 on the new routes

- [ ] **Step 3: Write minimal implementation**

Append to `backend/app/api/routes/accounts.py`:

```python
from app.api.deps import require_role


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
    _check_role(body.role)
    try:
        email = _looks_like_email(body.email)
    except ValueError as e:
        raise HTTPException(422, str(e))
    mk, claims, rm = _identity()
    try:
        uid = mk(email, body.password)
    except Exception as e:
        raise HTTPException(409, f"Could not create that account: {e}")
    try:
        claims(uid, {"tenantId": ctx.tenant_id, "role": body.role})
        rec = store.put_user(ctx.tenant_id, uid, email, body.role)
    except Exception as e:
        try:
            rm(uid)
        except Exception:
            pass
        raise HTTPException(500, f"Could not add that user: {e}")
    return {"status": "success", "user": rec}


@router.put("/users/{uid}/role")
async def change_role(uid: str, body: RoleIn,
                      ctx: AuthContext = Depends(require_role(ROLE_ADMIN))):
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
    claims(uid, {"tenantId": ctx.tenant_id, "role": role})
    store.set_role(ctx.tenant_id, uid, role)
    return {"status": "success", "user": store.get_user(ctx.tenant_id, uid)}


@router.delete("/users/{uid}")
async def delete_user(uid: str,
                      ctx: AuthContext = Depends(require_role(ROLE_ADMIN))):
    existing = store.get_user(ctx.tenant_id, uid)
    if existing is None:
        raise HTTPException(404, "No such user in your account.")
    if uid == ctx.uid:
        # The app offers no other way back in; the only remaining route would
        # be a vendor-side repair.
        raise HTTPException(400, "You cannot delete your own account.")
    if (existing.get("role") == ROLE_ADMIN
            and store.count_admins(ctx.tenant_id) <= 1):
        raise HTTPException(400, "This is the only admin.")

    _, _, rm = _identity()
    rm(uid)
    store.remove_user(ctx.tenant_id, uid)
    return {"status": "success", "removed": uid}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_accounts_api.py -q`
Expected: PASS, 16 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/accounts.py backend/tests/test_accounts_api.py
git commit -m "Let an admin create, re-role and delete accounts in its tenant

Every lookup goes through the caller's own tenant, so a uid from another tenant
is not found rather than refused - there is no cross-tenant check to forget,
because there is no path that reaches one.

Two guards stop a tenant locking itself out: the last admin cannot be demoted
or deleted, and nobody can delete themselves. The app offers no other way back
in, so the only remaining route would be a vendor-side repair."
```

---

### Task 6: Wire it up, add the Stage 2 seam, and put it in CI

**Files:**
- Modify: `backend/app/main.py` (router registration, after the existing `app.include_router` block)
- Modify: `backend/app/api/routes/smart_care_v2.py` (add `_tpath`)
- Modify: `backend/requirements-ci.txt` (add httpx)
- Modify: `.github/workflows/tests.yml:38-45` (add the four new test files)
- Create: `backend/tests/test_tpath.py`

**Interfaces:**
- Consumes: `accounts.router` from Task 4/5.
- Produces: `smart_care_v2._tpath(tenant_id: str | None, suffix: str) -> str` — returns `/farm/<suffix>` while `tenant_id` is falsy, `/tenants/<id>/farm/<suffix>` otherwise.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_tpath.py`:

```python
"""The seam Stage 2 turns on.

Added now, wired now, switched later. Stage 2 moves the farm subtree under
/tenants/{id}/farm and rewrites ~99 call sites; having the helper already in
place and already proven means that stage is a mechanical substitution rather
than a substitution plus a new function nobody has run.

While every caller passes None, this returns exactly today's paths - which is
the property that lets Stage 1 ship without touching farm behaviour at all.
"""
from app.api.routes.smart_care_v2 import _tpath


def test_no_tenant_gives_todays_path_exactly():
    assert _tpath(None, "houses.json") == "/farm/houses.json"
    assert _tpath("", "meta/autoMode.json") == "/farm/meta/autoMode.json"


def test_a_tenant_nests_the_same_suffix():
    assert _tpath("t_abc", "houses.json") == "/tenants/t_abc/farm/houses.json"


def test_a_leading_slash_on_the_suffix_is_tolerated():
    """Call sites are being rewritten by hand from f"/farm/..." strings, and
    one of them will keep the slash."""
    assert _tpath(None, "/houses.json") == "/farm/houses.json"
    assert _tpath("t_abc", "/houses.json") == "/tenants/t_abc/farm/houses.json"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_tpath.py -q`
Expected: FAIL — `ImportError: cannot import name '_tpath'`

- [ ] **Step 3: Write minimal implementation**

Add to `backend/app/api/routes/smart_care_v2.py`, immediately after the `_fb_delete` definition near line 59:

```python
def _tpath(tenant_id, suffix: str) -> str:
    """Build a farm path, tenant-aware.

    A SEAM FOR STAGE 2, deliberately inert today. The farm subtree is about to
    move from /farm/... to /tenants/{id}/farm/..., which is a rewrite of every
    hardcoded path across six route files. Introducing the helper in its own
    stage - proven, and returning exactly today's strings while every caller
    passes None - makes that rewrite a substitution instead of a substitution
    plus a function nobody has exercised.
    """
    tail = suffix[1:] if suffix.startswith("/") else suffix
    if not tenant_id:
        return f"/farm/{tail}"
    return f"/tenants/{tenant_id}/farm/{tail}"
```

In `backend/app/main.py`, after the existing `app.include_router(smart_care_v2.router, ...)` line, add:

```python
from app.api.routes import accounts
app.include_router(accounts.router, prefix="/api/v2/accounts", tags=["Accounts"])
```

In `backend/requirements-ci.txt`, append:

```
# fastapi.testclient needs httpx. The accounts and guard tests drive real
# routing through TestClient rather than calling the dependencies directly.
httpx==0.27.0
```

In `.github/workflows/tests.yml`, extend the pytest invocation to:

```yaml
        run: |
          pytest -q --no-header \
            tests/test_freshness.py \
            tests/test_farm_clock.py \
            tests/test_auto_switch.py \
            tests/test_alarm_repeat.py \
            tests/test_firebase_auth.py \
            tests/test_auth_deps.py \
            tests/test_tenant_store.py \
            tests/test_accounts_api.py \
            tests/test_tpath.py
```

- [ ] **Step 4: Run the whole suite and check the app still boots**

Run: `cd backend && python -m pytest tests/ -q`
Expected: PASS — the previous 57 plus the new ones, no failures.

Run: `cd backend && python -c "from app.main import app; print(len(app.routes))"`
Expected: prints a route count 5 higher than before (96 -> 101), and no traceback.

Run: `cd backend && python -c "
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app)
print('no key   ', c.post('/api/v2/accounts/tenants', json={}).status_code)
print('health   ', c.get('/health').status_code)
"`
Expected: `no key 401` and `health 200` — the new endpoint is guarded and nothing existing broke.

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/app/api/routes/smart_care_v2.py \
        backend/requirements-ci.txt backend/tests/test_tpath.py \
        .github/workflows/tests.yml
git commit -m "Mount the accounts router and add the tenant-path seam

_tpath is inert today: every caller passes None and it returns exactly the
paths the farm already uses. Stage 2 moves the subtree under
/tenants/{id}/farm and rewrites about 99 call sites, and having the helper
already proven turns that into a substitution rather than a substitution plus
a function nobody has run.

Nothing about existing endpoints changes. The X-API-Key middleware stays as it
is - the mobile app still authenticates with that static key and has no login
screen until Stage 4, so weakening it now would break the app in the field."
```

---

## Definition of done for Stage 1

- `pytest tests/ -q` passes locally and the four new files pass in CI
- `POST /api/v2/accounts/tenants` with the vendor key provisions a tenant and an admin whose custom claims carry `tenantId` and `role`
- An admin bearer token can add, re-role and remove users inside its own tenant, and gets 404 for a uid in another tenant
- An operator token is refused user management; a viewer token is refused everything but reading
- No existing endpoint changed behaviour: the API-key middleware is untouched, `/farm/...` paths are unchanged, and the automation engine is not modified

## Not in this stage

Applying `require_auth` / `require_role` to the existing farm routes, moving data under `/tenants/{id}/farm`, the firmware `TENANT_ID` constant and reflash, and the mobile login and Team screens. Those are Stages 2-4 in the spec.
