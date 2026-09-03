"""The accounts routes as the REAL application mounts them.

WHY THIS FILE EXISTS. Every other accounts test builds a bare `FastAPI()` and
includes the router, so none of them can see `app/main.py` at all - and
`app/main.py` puts a second, older guard in front of these routes:

    POST / PUT / PATCH / DELETE on /api/v2/*  require the static ORCHID_API_KEY

The accounts router mounts at /api/v2/accounts, so wherever that environment
variable is set - which is production - the three write endpoints need the
static key IN ADDITION to an admin bearer token. Nothing said so, and no test
could have noticed.

THE STAGE 1 ANSWER, DELIBERATELY: writes need both. The middleware is
fail-closed and is not narrowed here, because the app in the field authenticates
with that static key and has no login screen; taking the key out of the write
path would lock out real users watering real plants. Stage 4 gives the mobile
app a login and moves it onto bearer tokens, and that is when this table
changes. Until then it is written down, and it is tested.
"""
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.api.routes import accounts
from app.services.firebase_auth import ROLE_ADMIN, ROLE_OPERATOR, set_decoder

KEY = "static-key-for-tests"
API_KEY_HEADER = {"X-API-Key": KEY}

# The two refusals this file has to tell apart. Verbatim, because "which 401
# came back" is the entire subject of this file.
MIDDLEWARE_401 = ("This action needs an API key. The app sends one "
                  "automatically; if you are seeing this in the app, "
                  "it is out of date and needs rebuilding.")
BEARER_401 = "Please sign in."


@pytest.fixture
def wired(monkeypatch, fake_firebase):
    """The real app, with the static key set and Firebase faked out."""
    users = {}

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
    set_decoder(lambda token: dict(zip(("uid", "tenantId", "role"),
                                       token.split("@"))))

    monkeypatch.setattr(main, "ORCHID_API_KEY", KEY)
    monkeypatch.setattr(accounts, "VENDOR_KEY", KEY)

    # No `with`: the lifespan would start the automation engine, which is a
    # 60-second clock that issues real watering commands.
    yield TestClient(main.app)

    accounts.set_identity_backend(None, None, None)
    set_decoder(None)


def _detail(response):
    try:
        return response.json().get("detail")
    except Exception:                                    # pragma: no cover
        return response.text


def _bearer(uid, tenant, role=ROLE_ADMIN):
    return {"Authorization": f"Bearer {uid}@{tenant}@{role}"}


def _tenant_body(email):
    return {"name": "Green Acres", "adminEmail": email,
            "adminPassword": "sup3rsecret"}


def test_the_five_accounts_routes_against_the_static_key_middleware(wired):
    """All five routes, each with (a) the key only, (b) a bearer only, (c) both.

    Read the assertions as the table they are. A 401 whose detail is
    MIDDLEWARE_401 means main.py's static-key guard refused; a 401 whose detail
    is BEARER_401 means the request got past that and the route's own bearer
    guard refused. Which of the two answers is the whole point.
    """
    client = wired

    # ── POST /tenants ── a write, so the middleware covers it. It happens to
    # take the SAME value as its own vendor key, so one header satisfies both.
    r = client.post("/api/v2/accounts/tenants",
                    headers=_bearer("nobody", "t_none"),
                    json=_tenant_body("a@example.com"))
    assert (r.status_code, _detail(r)) == (401, MIDDLEWARE_401)

    r = client.post("/api/v2/accounts/tenants", headers=API_KEY_HEADER,
                    json=_tenant_body("a@example.com"))
    assert r.status_code == 200, r.text
    tenant, admin = r.json()["tenantId"], r.json()["adminUid"]

    r = client.post("/api/v2/accounts/tenants",
                    headers={**API_KEY_HEADER, **_bearer(admin, tenant)},
                    json=_tenant_body("b@example.com"))
    assert r.status_code == 200, r.text

    as_admin = _bearer(admin, tenant)

    # ── GET /users ── a read. The middleware guards writes only, so the key is
    # neither needed nor sufficient here.
    r = client.get("/api/v2/accounts/users", headers=API_KEY_HEADER)
    assert (r.status_code, _detail(r)) == (401, BEARER_401)

    assert client.get("/api/v2/accounts/users",
                      headers=as_admin).status_code == 200
    assert client.get("/api/v2/accounts/users",
                      headers={**API_KEY_HEADER, **as_admin}).status_code == 200

    # ── POST /users ──
    new_user = {"email": "op@example.com", "password": "sup3rsecret",
                "role": ROLE_OPERATOR}
    r = client.post("/api/v2/accounts/users", headers=API_KEY_HEADER,
                    json=new_user)
    assert (r.status_code, _detail(r)) == (401, BEARER_401)

    r = client.post("/api/v2/accounts/users", headers=as_admin, json=new_user)
    assert (r.status_code, _detail(r)) == (401, MIDDLEWARE_401)

    r = client.post("/api/v2/accounts/users",
                    headers={**API_KEY_HEADER, **as_admin}, json=new_user)
    assert r.status_code == 200, r.text
    victim = r.json()["user"]["uid"]

    # ── PUT /users/{uid}/role ──
    role_path = f"/api/v2/accounts/users/{victim}/role"
    r = client.put(role_path, headers=API_KEY_HEADER, json={"role": "viewer"})
    assert (r.status_code, _detail(r)) == (401, BEARER_401)

    r = client.put(role_path, headers=as_admin, json={"role": "viewer"})
    assert (r.status_code, _detail(r)) == (401, MIDDLEWARE_401)

    r = client.put(role_path, headers={**API_KEY_HEADER, **as_admin},
                   json={"role": "viewer"})
    assert r.status_code == 200, r.text

    # ── DELETE /users/{uid} ──
    user_path = f"/api/v2/accounts/users/{victim}"
    r = client.delete(user_path, headers=API_KEY_HEADER)
    assert (r.status_code, _detail(r)) == (401, BEARER_401)

    r = client.delete(user_path, headers=as_admin)
    assert (r.status_code, _detail(r)) == (401, MIDDLEWARE_401)

    r = client.delete(user_path, headers={**API_KEY_HEADER, **as_admin})
    assert r.status_code == 200, r.text


def test_without_the_env_var_a_laptop_run_needs_only_the_bearer(monkeypatch,
                                                                wired):
    """The other direction. `main.py` skips the check entirely when
    ORCHID_API_KEY is unset, so a developer run behaves exactly as the bare
    router tests assume - which is why they never noticed the coupling."""
    client = wired
    r = client.post("/api/v2/accounts/tenants", headers=API_KEY_HEADER,
                    json=_tenant_body("a@example.com"))
    tenant, admin = r.json()["tenantId"], r.json()["adminUid"]

    monkeypatch.setattr(main, "ORCHID_API_KEY", "")
    r = client.post("/api/v2/accounts/users", headers=_bearer(admin, tenant),
                    json={"email": "op@example.com",
                          "password": "sup3rsecret", "role": ROLE_OPERATOR})
    assert r.status_code == 200, r.text


def test_the_accounts_router_is_mounted_where_the_middleware_can_see_it(wired):
    """If the prefix ever moves out from under /api/v2/, the table above stops
    describing reality and every assertion in it still passes."""
    paths = {r.path for r in main.app.routes if hasattr(r, "path")}
    assert "/api/v2/accounts/users" in paths
    assert "/api/v2/accounts/tenants" in paths
    assert main._GUARDED_PREFIX == "/api/v2/"
    assert {"POST", "PUT", "DELETE"} <= main._GUARDED_METHODS
