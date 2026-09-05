"""The store's own rules, against a dict standing in for Firebase.

The point of these is the two guards that protect a tenant from locking itself
out - the last admin, and a uid that belongs to somebody else's tenant. Both
are the kind of thing that reads as obviously handled and turns out not to be.
"""
import pytest

from app.services import tenant_store as store
from app.services.firebase_auth import ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER


@pytest.fixture(autouse=True)
def db(fake_firebase):
    """The shared fake from conftest.py.

    This used to be a private copy, and it had drifted from the one in
    test_accounts_api.py - the two disagreed about whether a delete cascades -
    so a store change could pass in one file and fail in the other.
    """
    return fake_firebase


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


# ── a write that fails must say so ─────────────────────────────────────────
#
# The REST helpers report failure by RETURNING FALSE: `_fb_put` catches every
# exception and answers False, so a 401 from tightened database rules, a 503
# and an eight-second timeout are indistinguishable from success at this layer.
# accounts.py rolls a half-made tenant back only on an exception, so a store
# that swallows a failed write leaves that rollback dead against the real
# database and the endpoint answers 200 over a tenant that was never stored.

def _writes_all_fail(db):
    """A backend that fails the way Firebase's helpers actually fail."""
    store.set_backend(lambda p: db.get(p),
                      lambda p, v: False,
                      lambda p: False)


def test_create_tenant_raises_when_the_write_fails(db):
    _writes_all_fail(db)
    with pytest.raises(RuntimeError):
        store.create_tenant("t_x", "Green Acres", "ua", "starter")


def test_put_user_raises_when_the_write_fails(db):
    _writes_all_fail(db)
    with pytest.raises(RuntimeError):
        store.put_user("t_x", "ua", "admin@example.com", ROLE_ADMIN)


def test_remove_user_raises_when_the_delete_fails(db):
    tid = _tenant_with_admin()
    _writes_all_fail(db)
    with pytest.raises(RuntimeError):
        store.remove_user(tid, "ua")


def test_set_role_raises_when_the_write_fails(db):
    tid = _tenant_with_admin()
    store.put_user(tid, "ob", "op@example.com", ROLE_OPERATOR)
    _writes_all_fail(db)
    with pytest.raises(RuntimeError):
        store.set_role(tid, "ob", ROLE_VIEWER)


def test_set_role_refuses_a_failed_read_rather_than_wiping_the_record(db):
    """`get(...) or {}` would write back {"role": ...} alone, silently dropping
    email and addedAt. A read that did not come back is not an empty record."""
    tid = _tenant_with_admin()
    store.put_user(tid, "ob", "op@example.com", ROLE_OPERATOR)
    kept = dict(db)

    store.set_backend(lambda p: None, lambda p, v: db.__setitem__(p, v) or True,
                      lambda p: True)
    with pytest.raises(RuntimeError):
        store.set_role(tid, "ob", ROLE_VIEWER)

    assert db == kept, "a failed read was written back as a partial record"


def test_set_role_keeps_the_fields_it_is_not_changing():
    tid = _tenant_with_admin()
    store.put_user(tid, "ob", "op@example.com", ROLE_OPERATOR)
    before = store.get_user(tid, "ob")
    store.set_role(tid, "ob", ROLE_VIEWER)
    after = store.get_user(tid, "ob")
    assert after["role"] == ROLE_VIEWER
    assert after["email"] == "op@example.com"
    assert after["addedAt"] == before["addedAt"]


# ── the rollback removes what provisioning wrote, and nothing else ─────────

def test_rollback_removes_the_meta_and_the_admin_record():
    tid = _tenant_with_admin()
    store.rollback_new_tenant(tid, "ua")
    assert store.get_tenant(tid) is None
    assert store.get_user(tid, "ua") is None


def test_rollback_leaves_the_rest_of_the_tenant_subtree_alone(db):
    """Deleting /tenants/{id}.json cascades, and Stage 2 moves every house,
    section, plan, tray and pump config under that node - at which point a
    broad delete inside an exception handler erases a customer's farm. Naming
    the two records provisioning wrote cannot grow that reach by accident."""
    tid = _tenant_with_admin()
    db[f"/tenants/{tid}/farm/houses/H1/meta.json"] = {"name": "House 1"}
    db[f"/tenants/{tid}/farm/meta.json"] = {"autoMode": True}

    store.rollback_new_tenant(tid, "ua")

    assert store.get_tenant(tid) is None
    assert store.get_user(tid, "ua") is None
    assert db[f"/tenants/{tid}/farm/houses/H1/meta.json"] == {"name": "House 1"}
    assert db[f"/tenants/{tid}/farm/meta.json"] == {"autoMode": True}


def test_rollback_attempts_both_deletes_even_when_the_first_fails(db):
    """One failed undo must not abandon the other: a tenant left holding meta
    and no admin cannot be logged into and cannot be repaired from the app."""
    tid = _tenant_with_admin()
    tried = []

    def _delete(path):
        tried.append(path)
        return not path.endswith("/users/ua.json")

    store.set_backend(lambda p: db.get(p), lambda p, v: True, _delete)
    with pytest.raises(RuntimeError):
        store.rollback_new_tenant(tid, "ua")
    assert tried == [f"/tenants/{tid}/users/ua.json",
                     f"/tenants/{tid}/meta.json"]


def test_there_is_no_delete_tenant():
    """A helper named "delete the tenant" is a customer-deletion tool waiting
    to be reused by the next person who needs to remove something. Once the
    farm subtree lives under that node in Stage 2, its absence is the guard."""
    assert not hasattr(store, "delete_tenant")
