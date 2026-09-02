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
