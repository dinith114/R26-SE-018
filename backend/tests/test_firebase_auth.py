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


def test_auth_client_raises_when_the_key_file_is_missing(monkeypatch):
    """The caller turns this into an HTTP error. Returning None instead would
    make a missing key look like a working client until the first call."""
    import app.services.firebase_auth as fa
    monkeypatch.setattr(fa, "_auth_app", None)
    monkeypatch.setenv("FIREBASE_ADMIN_KEY", "/definitely/not/a/real/key.json")
    with pytest.raises(Exception):
        fa.auth_client()
