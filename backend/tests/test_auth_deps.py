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
