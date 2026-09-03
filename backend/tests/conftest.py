"""Shared test fixtures. Two jobs, both learned from a real defect.

ONE FAKE FIREBASE, NOT TWO. `test_accounts_api.py` and `test_tenant_store.py`
each grew their own dict-backed stand-in for the Realtime Database, and by the
time anyone looked they had already diverged: one cascaded on delete, the other
removed the exact key. A store change could pass in one file and fail in the
other, and the two files disagreed about what Firebase does. There is one fake
here now, and it models what the REST helpers actually do:

  * a GET on a parent path returns the merged SUBTREE, because that is how
    /farm/houses.json behaves everywhere else in this codebase and it is how
    `list_users` reads a tenant that `put_user` wrote one uid at a time;
  * a DELETE removes everything beneath the path as well, because Firebase
    deletes subtrees;
  * a DELETE answers True whether or not anything was there, because Firebase
    answers 200 to a delete of an absent node and `_fb_delete` returns
    `status_code == 200`. Modelling that as False would make the store's write
    assertions fire where production is silent, which is a fake inventing a
    failure rather than reproducing one.

NOTHING MAY REACH THE REAL FARM. `tenant_store.set_backend(None, None, None)`
does not neutralise the store - it RESTORES production Firebase, and this
project's Realtime Database rules are open. A test file that forgot to install
its seam would read and write the live farm from a CI runner. The autouse
fixture below installs a backend that refuses instead, so that mistake fails
loudly, locally, on the first call.
"""
import pytest

from app.services import tenant_store as store


def _subtree_get(db):
    def _get(path):
        if path in db:
            return db[path]
        prefix = path[:-len(".json")] + "/" if path.endswith(".json") else path + "/"
        kids = {}
        for key, value in db.items():
            if key.startswith(prefix) and key.endswith(".json"):
                child = key[len(prefix):-len(".json")]
                if "/" not in child:          # direct children only
                    kids[child] = value
        return kids or None
    return _get


def _subtree_put(db):
    def _put(path, value):
        db[path] = value
        return True                            # `_fb_put` returns a bool
    return _put


def _subtree_delete(db):
    def _delete(path):
        db.pop(path, None)
        stem = path[:-len(".json")] if path.endswith(".json") else path
        prefix = stem + "/"
        for key in [k for k in db if k.startswith(prefix)]:
            db.pop(key, None)
        return True                            # Firebase answers 200 either way
    return _delete


def install_fake_firebase(db: dict) -> None:
    """Point `tenant_store` at `db` for the rest of the test."""
    store.set_backend(_subtree_get(db), _subtree_put(db), _subtree_delete(db))


def _refuse(*_a, **_k):
    raise AssertionError(
        "This test used tenant_store without installing a fake backend. "
        "The unfaked store talks to the real farm database. Depend on the "
        "`fake_firebase` fixture.")


@pytest.fixture(autouse=True)
def _no_live_firebase():
    """Default every test to a store that refuses rather than one that dials out.

    Autouse fixtures are set up before the fixtures a test asks for, so
    `fake_firebase` still gets the last word for the tests that want one.
    """
    store.set_backend(_refuse, _refuse, _refuse)
    yield
    store.set_backend(_refuse, _refuse, _refuse)


@pytest.fixture
def firebase_parts():
    """The three fake helpers as builders, so a test can swap ONE of them for a
    failing version without reimplementing the other two."""
    return _subtree_get, _subtree_put, _subtree_delete


@pytest.fixture
def fake_firebase():
    """A dict shaped like the Realtime Database paths the store uses."""
    db: dict = {}
    install_fake_firebase(db)
    yield db
    store.set_backend(_refuse, _refuse, _refuse)
