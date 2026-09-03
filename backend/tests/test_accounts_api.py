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

    def _get(path):
        if path in db:
            return db[path]
        # Firebase returns the SUBTREE when a GET lands on a parent path whose
        # children were written beneath it - list_users() reads
        # /tenants/{id}/users.json while put_user() writes each member to
        # /tenants/{id}/users/{uid}.json, and that merge is exactly how real
        # Firebase (and test_tenant_store.py's fake) behaves. A flat
        # exact-path lookup cannot model this and under-reports every list.
        prefix = path[:-len(".json")] + "/" if path.endswith(".json") else path + "/"
        kids = {}
        for key, value in db.items():
            if key.startswith(prefix) and key.endswith(".json"):
                child = key[len(prefix):-len(".json")]
                if "/" not in child:          # direct children only
                    kids[child] = value
        return kids or None

    def _delete(path):
        # Mirror of _get's subtree behaviour: deleting a parent path in real
        # Firebase removes everything written beneath it, which is exactly
        # what delete_tenant() relies on to roll a half-made tenant back in
        # one call (/tenants/{id}.json) rather than needing to know every
        # child path (meta, each user) that create_tenant/put_user wrote.
        existed = db.pop(path, None) is not None
        stem = path[:-len(".json")] if path.endswith(".json") else path
        prefix = stem + "/"
        descendants = [k for k in db if k.startswith(prefix)]
        for k in descendants:
            db.pop(k, None)
        return existed or bool(descendants)

    store.set_backend(
        _get,
        lambda p, v: db.__setitem__(p, v) or v,
        _delete,
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


def test_a_store_failure_after_the_tenant_is_written_leaves_nothing_behind(env):
    """The gap the identity-provider test does not reach. If put_user fails
    AFTER create_tenant has written meta.json, that meta record must not
    survive - a tenant with no admin can never be logged into, and there is
    no screen in the app that could repair it."""
    client, db, users = env
    before = dict(db)

    original = store.put_user
    def _explode(*a, **k):
        raise RuntimeError("firebase write failed")
    store.put_user = _explode
    try:
        r = client.post("/api/v2/accounts/tenants",
                        headers={"X-API-Key": VENDOR_KEY},
                        json={"name": "Doomed", "adminEmail": "x@example.com",
                              "adminPassword": "sup3rsecret"})
    finally:
        store.put_user = original

    assert r.status_code == 500
    assert db == before, "a tenant with no admin survived a failed provisioning"
    assert users == {}, "the orphaned Firebase Auth user was not rolled back"
