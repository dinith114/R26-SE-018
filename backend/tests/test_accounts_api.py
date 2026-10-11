"""The accounts API, with Firebase Auth and the database both faked.

Two seams: `tenant_store.set_backend` for the data (installed by the shared
`fake_firebase` fixture in conftest.py), and `accounts.set_identity_backend`
for the admin-SDK calls that create a user, stamp its claims, delete it and
revoke its sessions. Between them these tests run offline and still exercise
the real routing, the real guards and the real refusals.

EVERY ADMIN TOKEN CARRIES THE REAL ADMIN'S UID. It used to carry a made-up one,
which worked only because nothing checked. The write endpoints now re-read the
caller from the store on every call - a Firebase ID token lives an hour, so
claims alone cannot say whether the caller is STILL an admin - and a token for
a uid the store has never heard of is exactly the token that check exists to
refuse.
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


class UserNotFoundError(Exception):
    """Stands in for firebase_admin.auth.UserNotFoundError.

    Named exactly, because accounts.py matches it by class NAME as well as by
    isinstance: CI installs a trimmed requirements file with no firebase-admin
    in it, so there the real class cannot be imported to compare against at all.
    """


@pytest.fixture
def env(monkeypatch, fake_firebase):
    """Fake database, fake identity provider, fake tokens, one client."""
    db, users, revoked = fake_firebase, {}, []

    def _create_user(email, password):
        if any(u["email"] == email for u in users.values()):
            raise ValueError("email already exists")
        uid = f"uid{len(users) + 1}"
        users[uid] = {"email": email, "claims": {}}
        return uid

    def _set_claims(uid, claims):
        users[uid]["claims"] = claims

    def _delete_user(uid):
        if uid not in users:
            raise UserNotFoundError(uid)
        users.pop(uid)

    def _revoke(uid):
        revoked.append(uid)

    accounts.set_identity_backend(_create_user, _set_claims, _delete_user,
                                  _revoke)
    monkeypatch.setattr(accounts, "VENDOR_KEY", VENDOR_KEY)

    # Tokens are "<uid>@<tenant>@<role>" so a test can mint any identity -
    # including one whose claims disagree with the store, which is the whole
    # point of the stale-claims tests below.
    def _decode(token):
        uid, tenant, role = token.split("@")
        return {"uid": uid, "tenantId": tenant, "role": role,
                "email": users.get(uid, {}).get("email")}
    set_decoder(_decode)

    app = FastAPI()
    app.include_router(accounts.router, prefix="/api/v2/accounts")
    yield TestClient(app), db, users, revoked

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


def _as_admin(tenant):
    """Headers for the tenant's real admin - the uid the store actually holds."""
    return _tok(tenant["adminUid"], tenant["tenantId"], ROLE_ADMIN)


def test_creating_a_tenant_needs_the_vendor_key(env):
    client, _, _, _ = env
    r = client.post("/api/v2/accounts/tenants",
                    json={"name": "X", "adminEmail": "a@b.c",
                          "adminPassword": "sup3rsecret"})
    assert r.status_code == 401


def test_creating_a_tenant_makes_an_admin_with_claims(env):
    client, db, users, _ = env
    body = _make_tenant(client)
    tid, uid = body["tenantId"], body["adminUid"]

    assert tid.startswith("t_")
    assert users[uid]["claims"] == {"tenantId": tid, "role": ROLE_ADMIN}
    assert store.get_tenant(tid)["name"] == "Green Acres"
    assert [u["role"] for u in store.list_users(tid)] == [ROLE_ADMIN]


def test_a_duplicate_admin_email_is_refused_and_leaves_no_tenant(env):
    """The identity provider fails AFTER a tenant id has been minted. Nothing
    half-made may survive that, or the next list shows a tenant with no admin."""
    client, db, _, _ = env
    _make_tenant(client, email="taken@example.com")
    before = dict(db)

    r = client.post("/api/v2/accounts/tenants",
                    headers={"X-API-Key": VENDOR_KEY},
                    json={"name": "Second", "adminEmail": "taken@example.com",
                          "adminPassword": "sup3rsecret"})
    assert r.status_code == 409
    assert db == before


def test_a_refusal_does_not_repeat_the_providers_own_words(env):
    """409 already tells the caller more than it should. Echoing the provider's
    message on top of it turns this into a cross-tenant existence oracle: an
    admin of one farm could enumerate which addresses hold accounts on another."""
    client, _, _, _ = env
    _make_tenant(client, email="taken@example.com")
    r = client.post("/api/v2/accounts/tenants",
                    headers={"X-API-Key": VENDOR_KEY},
                    json={"name": "Second", "adminEmail": "taken@example.com",
                          "adminPassword": "sup3rsecret"})
    assert r.status_code == 409
    assert "email already exists" not in r.text
    assert r.json()["detail"] == "Could not create that account."


def test_a_short_password_is_refused(env):
    client, _, _, _ = env
    r = client.post("/api/v2/accounts/tenants",
                    headers={"X-API-Key": VENDOR_KEY},
                    json={"name": "X", "adminEmail": "a@b.c",
                          "adminPassword": "short"})
    assert r.status_code == 422


def test_listing_users_needs_a_token(env):
    client, _, _, _ = env
    _make_tenant(client)
    assert client.get("/api/v2/accounts/users").status_code == 401


def test_every_role_may_list_its_own_users(env):
    """Reads are answered from the token alone - no store lookup, which is the
    per-request read budget the claims design exists to keep. The uid here is
    deliberately one the store has never seen."""
    client, _, _, _ = env
    tid = _make_tenant(client)["tenantId"]
    for role in (ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER):
        r = client.get("/api/v2/accounts/users", headers=_tok("u9", tid, role))
        assert r.status_code == 200
        assert r.json()["tenantId"] == tid


def test_a_token_for_another_tenant_sees_nothing_of_this_one(env):
    """Tenant isolation at the API. The token is valid; it is simply somebody
    else's, and the response must be shaped by the token, never by a parameter."""
    client, _, _, _ = env
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
    client, db, users, _ = env
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


def test_a_write_that_merely_returns_false_also_rolls_back(env, firebase_parts):
    """The version of the test above that would have caught the real bug.

    Firebase's REST helpers do not raise on a failed write - `_fb_put` catches
    everything and returns False - so the rollback above only ever ran because
    a test monkeypatched an exception in. Against the real database a 401 from
    tightened rules, a 503 or a timeout all arrive here as a plain False, and
    before the store started asserting its writes this endpoint answered
    200 {"status": "success"} over a tenant that had no admin record at all.
    """
    client, db, users, _ = env
    make_get, make_put, make_delete = firebase_parts
    before = dict(db)
    working_put = make_put(db)

    def _put(path, value):
        if "/users/" in path:
            return False              # exactly what _fb_put answers on a 503
        return working_put(path, value)

    store.set_backend(make_get(db), _put, make_delete(db))

    r = client.post("/api/v2/accounts/tenants",
                    headers={"X-API-Key": VENDOR_KEY},
                    json={"name": "Doomed", "adminEmail": "x@example.com",
                          "adminPassword": "sup3rsecret"})

    assert r.status_code == 500, "a failed write was reported as success"
    assert db == before, "the tenant meta survived a failed provisioning"
    assert users == {}, "the orphaned Firebase Auth user was not rolled back"


# ── user management ────────────────────────────────────────────────────────

def _add(client, tenant, email, role):
    return client.post("/api/v2/accounts/users",
                       headers=_as_admin(tenant),
                       json={"email": email, "password": "sup3rsecret",
                             "role": role})


def test_admin_creates_an_operator_with_the_right_claims(env):
    client, _, users, _ = env
    t = _make_tenant(client)
    r = _add(client, t, "op@example.com", ROLE_OPERATOR)
    assert r.status_code == 200, r.text
    uid = r.json()["user"]["uid"]
    assert users[uid]["claims"] == {"tenantId": t["tenantId"],
                                    "role": ROLE_OPERATOR}
    assert store.get_user(t["tenantId"], uid)["role"] == ROLE_OPERATOR


def test_operator_and_viewer_cannot_create_users(env):
    client, _, _, _ = env
    tid = _make_tenant(client)["tenantId"]
    for role in (ROLE_OPERATOR, ROLE_VIEWER):
        r = client.post("/api/v2/accounts/users", headers=_tok("u9", tid, role),
                        json={"email": "x@example.com",
                              "password": "sup3rsecret", "role": ROLE_VIEWER})
        assert r.status_code == 403


def test_operator_and_viewer_cannot_change_a_role(env):
    """The mutant this pins: `Depends(require_role(ROLE_ADMIN))` weakened to
    `Depends(require_auth)` on this route is full self-promotion. A viewer
    calls PUT /users/{their own uid}/role with {"role": "admin"}, is found in
    their own tenant, is not an admin so the last-admin guard stays quiet, and
    walks away with admin claims stamped on them."""
    client, _, _, _ = env
    t = _make_tenant(client)
    tid = t["tenantId"]
    for role in (ROLE_OPERATOR, ROLE_VIEWER):
        uid = _add(client, t, f"{role}@example.com", role).json()["user"]["uid"]
        r = client.put(f"/api/v2/accounts/users/{uid}/role",
                       headers=_tok(uid, tid, role),
                       json={"role": ROLE_ADMIN})
        assert r.status_code == 403, r.text
        assert store.get_user(tid, uid)["role"] == role


def test_operator_and_viewer_cannot_delete_a_user(env):
    client, _, users, _ = env
    t = _make_tenant(client)
    tid = t["tenantId"]
    victim = _add(client, t, "victim@example.com",
                  ROLE_OPERATOR).json()["user"]["uid"]
    for role in (ROLE_OPERATOR, ROLE_VIEWER):
        uid = _add(client, t, f"{role}@example.com", role).json()["user"]["uid"]
        r = client.delete(f"/api/v2/accounts/users/{victim}",
                          headers=_tok(uid, tid, role))
        assert r.status_code == 403, r.text
    assert store.get_user(tid, victim) is not None
    assert victim in users


def test_claims_that_say_admin_do_not_survive_a_store_that_says_otherwise(env):
    """A Firebase ID token is valid for its full hour no matter what the store
    now says, so a demoted or removed admin keeps admin CLAIMS in their pocket
    long enough to call POST /users, mint themselves a fresh admin account, and
    undo their own removal. The store is the authority on who is an admin right
    now, and the three write endpoints ask it."""
    client, _, _, _ = env
    t = _make_tenant(client)
    tid = t["tenantId"]
    demoted = _add(client, t, "was-admin@example.com",
                   ROLE_VIEWER).json()["user"]["uid"]
    victim = _add(client, t, "victim@example.com",
                  ROLE_OPERATOR).json()["user"]["uid"]

    stale = _tok(demoted, tid, ROLE_ADMIN)      # claims lie, store does not
    assert client.post("/api/v2/accounts/users", headers=stale,
                       json={"email": "new@example.com",
                             "password": "sup3rsecret",
                             "role": ROLE_ADMIN}).status_code == 403
    assert client.put(f"/api/v2/accounts/users/{victim}/role", headers=stale,
                      json={"role": ROLE_VIEWER}).status_code == 403
    assert client.delete(f"/api/v2/accounts/users/{victim}",
                         headers=stale).status_code == 403
    assert store.get_user(tid, victim)["role"] == ROLE_OPERATOR


def test_a_deleted_admins_token_cannot_still_act(env):
    """The same window, taken to its end: the store record is gone entirely."""
    client, _, _, _ = env
    t = _make_tenant(client)
    tid = t["tenantId"]
    ghost = _tok("no-such-uid", tid, ROLE_ADMIN)
    assert client.post("/api/v2/accounts/users", headers=ghost,
                       json={"email": "new@example.com",
                             "password": "sup3rsecret",
                             "role": ROLE_ADMIN}).status_code == 403


def test_creating_a_user_with_an_unknown_role_is_refused(env):
    client, _, _, _ = env
    t = _make_tenant(client)
    r = _add(client, t, "x@example.com", "superuser")
    assert r.status_code == 422


def test_admin_changes_a_role_and_the_claims_follow(env):
    client, _, users, _ = env
    t = _make_tenant(client)
    tid = t["tenantId"]
    uid = _add(client, t, "op@example.com", ROLE_OPERATOR).json()["user"]["uid"]

    r = client.put(f"/api/v2/accounts/users/{uid}/role",
                   headers=_as_admin(t), json={"role": ROLE_VIEWER})
    assert r.status_code == 200
    assert store.get_user(tid, uid)["role"] == ROLE_VIEWER
    assert users[uid]["claims"] == {"tenantId": tid, "role": ROLE_VIEWER}


def test_a_role_change_revokes_the_old_sessions(env):
    """Defence in depth. The old ID token still carries the old role for up to
    an hour in either direction; cutting the refresh tokens shortens the reach
    of everything downstream of it."""
    client, _, _, revoked = env
    t = _make_tenant(client)
    uid = _add(client, t, "op@example.com", ROLE_OPERATOR).json()["user"]["uid"]
    client.put(f"/api/v2/accounts/users/{uid}/role",
               headers=_as_admin(t), json={"role": ROLE_VIEWER})
    assert uid in revoked


def test_a_delete_revokes_the_sessions_before_removing_the_account(env):
    client, _, _, revoked = env
    t = _make_tenant(client)
    uid = _add(client, t, "op@example.com", ROLE_OPERATOR).json()["user"]["uid"]
    client.delete(f"/api/v2/accounts/users/{uid}", headers=_as_admin(t))
    assert uid in revoked


def test_a_failed_store_write_does_not_leave_the_claims_ahead_of_it(env):
    """Two authorities written one after the other. If the store write fails
    the claims already say the new role, and the account would hold a power the
    store does not grant it - which is the disagreement the whole role model
    depends on not having."""
    client, _, users, _ = env
    t = _make_tenant(client)
    tid = t["tenantId"]
    uid = _add(client, t, "op@example.com", ROLE_OPERATOR).json()["user"]["uid"]

    def _explode(*a, **k):
        raise RuntimeError("firebase write failed")

    original = store.set_role
    store.set_role = _explode
    try:
        r = client.put(f"/api/v2/accounts/users/{uid}/role",
                       headers=_as_admin(t), json={"role": ROLE_ADMIN})
    finally:
        store.set_role = original

    assert r.status_code == 500
    assert "firebase write failed" not in r.text
    assert store.get_user(tid, uid)["role"] == ROLE_OPERATOR
    assert users[uid]["claims"] == {"tenantId": tid, "role": ROLE_OPERATOR}


def test_admin_deletes_a_user_from_both_places(env):
    client, _, users, _ = env
    t = _make_tenant(client)
    tid = t["tenantId"]
    uid = _add(client, t, "op@example.com", ROLE_OPERATOR).json()["user"]["uid"]

    r = client.delete(f"/api/v2/accounts/users/{uid}", headers=_as_admin(t))
    assert r.status_code == 200
    assert store.get_user(tid, uid) is None
    assert uid not in users


def test_a_record_whose_auth_user_already_vanished_is_still_removable(env):
    """Deleted from the Firebase console, say. If the missing auth user aborts
    the whole delete, the store keeps a record that still reads `role: admin`,
    count_admins keeps counting it, and the last-admin guard then lets the real
    sole admin demote themselves into a tenant with no working admin at all."""
    client, _, users, _ = env
    t = _make_tenant(client)
    tid = t["tenantId"]
    uid = _add(client, t, "op@example.com", ROLE_OPERATOR).json()["user"]["uid"]
    users.pop(uid)                        # gone out of band

    r = client.delete(f"/api/v2/accounts/users/{uid}", headers=_as_admin(t))
    assert r.status_code == 200, r.text
    assert store.get_user(tid, uid) is None


def test_a_delete_that_fails_for_any_other_reason_is_not_reported_as_success(env):
    client, _, _, _ = env
    t = _make_tenant(client)
    tid = t["tenantId"]
    uid = _add(client, t, "op@example.com", ROLE_OPERATOR).json()["user"]["uid"]

    def _boom(_uid):
        raise RuntimeError("firebase is down")

    # Only the delete matters from here on, so the other two are stubs.
    accounts.set_identity_backend(lambda e, p: "unused", lambda u, c: None,
                                  _boom)

    r = client.delete(f"/api/v2/accounts/users/{uid}", headers=_as_admin(t))
    assert r.status_code == 500
    assert "firebase is down" not in r.text
    assert store.get_user(tid, uid) is not None


def test_a_failed_store_delete_is_not_reported_as_success(env):
    """Reachable now that the store raises on a failed delete instead of
    swallowing it. A 200 here would leave behind a record count_admins still
    believes in, attached to an auth user that has already gone."""
    client, _, _, _ = env
    t = _make_tenant(client)
    uid = _add(client, t, "op@example.com", ROLE_OPERATOR).json()["user"]["uid"]

    def _explode(*a, **k):
        raise RuntimeError("firebase delete failed")

    original = store.remove_user
    store.remove_user = _explode
    try:
        r = client.delete(f"/api/v2/accounts/users/{uid}", headers=_as_admin(t))
    finally:
        store.remove_user = original

    assert r.status_code == 500
    assert "firebase delete failed" not in r.text


def test_an_admin_cannot_delete_themselves(env):
    """Not paternalism: the app offers no other way back in, and the only
    remaining route would be a vendor-side repair."""
    client, _, _, _ = env
    t = _make_tenant(client)
    tid, uid = t["tenantId"], t["adminUid"]
    r = client.delete(f"/api/v2/accounts/users/{uid}", headers=_as_admin(t))
    assert r.status_code == 400
    assert store.get_user(tid, uid) is not None


def test_an_admin_cannot_delete_themselves_even_with_another_admin_present(env):
    """The single-admin case is also caught by the last-admin guard, so it
    cannot tell whether the self-delete rule exists at all. With a second
    admin present, only the self-delete rule can refuse this."""
    client, _, users, _ = env
    t = _make_tenant(client)
    tid, first = t["tenantId"], t["adminUid"]
    _add(client, t, "admin2@example.com", ROLE_ADMIN)
    assert store.count_admins(tid) == 2

    r = client.delete(f"/api/v2/accounts/users/{first}", headers=_as_admin(t))
    assert r.status_code == 400
    assert store.get_user(tid, first) is not None
    assert first in users


def test_the_last_admin_cannot_be_demoted(env):
    client, _, _, _ = env
    t = _make_tenant(client)
    tid, uid = t["tenantId"], t["adminUid"]
    r = client.put(f"/api/v2/accounts/users/{uid}/role",
                   headers=_as_admin(t), json={"role": ROLE_VIEWER})
    assert r.status_code == 400
    assert store.get_user(tid, uid)["role"] == ROLE_ADMIN


def test_a_second_admin_makes_demotion_allowed(env):
    client, _, _, _ = env
    t = _make_tenant(client)
    tid, first = t["tenantId"], t["adminUid"]
    _add(client, t, "admin2@example.com", ROLE_ADMIN)

    r = client.put(f"/api/v2/accounts/users/{first}/role",
                   headers=_as_admin(t), json={"role": ROLE_VIEWER})
    assert r.status_code == 200
    assert store.count_admins(tid) == 1


def test_an_admin_cannot_touch_a_user_in_another_tenant(env):
    """The isolation test that matters most: a real admin, a real uid, and the
    only thing wrong is that they belong to different tenants."""
    client, _, _, _ = env
    a = _make_tenant(client, name="Farm A", email="a@example.com")
    b = _make_tenant(client, name="Farm B", email="b@example.com")
    victim = _add(client, b, "worker@example.com",
                  ROLE_OPERATOR).json()["user"]["uid"]

    hdr = _as_admin(a)
    assert client.delete(f"/api/v2/accounts/users/{victim}",
                         headers=hdr).status_code == 404
    assert client.put(f"/api/v2/accounts/users/{victim}/role",
                      headers=hdr, json={"role": ROLE_VIEWER}).status_code == 404
    assert store.get_user(b["tenantId"], victim)["role"] == ROLE_OPERATOR
