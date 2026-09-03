"""The property this entire stage exists for.

Two tenants, one fake database, real routing. Tenant A must not be able to see
or change anything of tenant B's, and the only thing separating them is the
token - there is no parameter either of them could change to reach the other.

This also proves the role table: a Viewer can read but never act, an Operator
can act on the farm (including STOP, which must never be harder to reach than
START) but cannot reconfigure it, and only an Admin can reconfigure or destroy.
"""
import pytest
from fastapi.testclient import TestClient

from app.services.firebase_auth import (
    ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER, set_decoder,
)


@pytest.fixture
def farm(monkeypatch):
    """A fake Firebase holding two tenants' farms, and a client over the real app."""
    db = {
        # /overview reads the whole houses tree in one shot.
        "/tenants/t_a/farm/houses.json": {
            "H1": {"meta": {"name": "Farm A"},
                   "sections": {"S1": {"meta": {"name": "A-S1"}}}}},
        "/tenants/t_b/farm/houses.json": {
            "H1": {"meta": {"name": "Farm B"},
                   "sections": {"S1": {"meta": {"name": "B-S1"}}}}},
        # water/stop read one key at a time rather than the merged tree above,
        # so those exact paths need their own entries. masterMac is set so
        # `stop` takes its normal "nothing is pouring" 200 path instead of
        # falling through to the direct-node path, which 500s with no relay
        # channel wired - a channel this test has no reason to configure.
        "/tenants/t_a/farm/houses/H1/meta.json": {"name": "Farm A", "masterMac": "AA:A1"},
        "/tenants/t_b/farm/houses/H1/meta.json": {"name": "Farm B", "masterMac": "BB:B1"},
        "/tenants/t_a/farm/houses/H1/sections/S1.json": {"meta": {"name": "A-S1"}},
        "/tenants/t_b/farm/houses/H1/sections/S1.json": {"meta": {"name": "B-S1"}},
        # `stop` checks the section exists via its meta specifically, a third
        # exact key distinct from the whole-section document above.
        "/tenants/t_a/farm/houses/H1/sections/S1/meta.json": {"name": "A-S1"},
        "/tenants/t_b/farm/houses/H1/sections/S1/meta.json": {"name": "B-S1"},
    }

    class _Resp:
        def __init__(self, body):
            self.body = body
            self.status_code = 200 if body is not None else 404

        def json(self):
            return self.body

    class _Req:
        def get(self, url, **kw):
            path = url.split("firebaseio.com", 1)[-1]
            return _Resp(db.get(path))

        def put(self, url, **kw):
            db[url.split("firebaseio.com", 1)[-1]] = kw.get("json")
            return _Resp({})

        delete = put

    from app.api.routes import devices, smart_care_v2, smart_watering
    for mod in (smart_watering, smart_care_v2, devices):
        monkeypatch.setattr(mod, "_req", _Req(), raising=False)

    def _decode(token):
        uid, tenant, role = token.split("@")
        return {"uid": uid, "tenantId": tenant, "role": role}

    set_decoder(_decode)

    # No `with`: the lifespan would start the automation engine, a 60-second
    # clock that issues real watering commands against whatever Firebase it
    # finds - see test_main_wiring.py for the same reasoning.
    from app.main import app
    yield TestClient(app), db
    set_decoder(None)


def _tok(uid, tenant, role):
    return {"Authorization": f"Bearer {uid}@{tenant}@{role}"}


def test_a_farm_route_with_no_token_is_401(farm):
    client, _ = farm
    assert client.get("/api/v2/care/overview").status_code == 401


def test_each_tenant_sees_only_its_own_farm(farm):
    """The test this whole stage exists for. Same endpoint, same shape of
    request, and the only difference is whose token it is."""
    client, _ = farm
    a = client.get("/api/v2/care/overview", headers=_tok("ua", "t_a", ROLE_ADMIN))
    b = client.get("/api/v2/care/overview", headers=_tok("ub", "t_b", ROLE_ADMIN))
    assert a.status_code == 200 and b.status_code == 200
    assert "Farm A" in a.text and "Farm A" not in b.text
    assert "Farm B" in b.text and "Farm B" not in a.text


def test_a_viewer_cannot_water(farm):
    client, _ = farm
    r = client.post("/api/v2/care/houses/H1/sections/S1/water",
                    headers=_tok("v", "t_a", ROLE_VIEWER), json={"durationSec": 30})
    assert r.status_code == 403


def test_a_viewer_cannot_fill_the_tray(farm):
    client, _ = farm
    r = client.post("/api/v2/care/houses/H1/sections/S1/tray-fill",
                    headers=_tok("v", "t_a", ROLE_VIEWER), json={"fillSeconds": 10})
    assert r.status_code == 403


def test_an_operator_cannot_change_the_mode(farm):
    client, _ = farm
    r = client.put("/api/v2/care/houses/H1/sections/S1/mode",
                   headers=_tok("o", "t_a", ROLE_OPERATOR),
                   json={"mode": "manual"})
    assert r.status_code == 403


def test_an_operator_cannot_delete_a_house(farm):
    """Configuration and destruction are Admin-only, even for whoever is
    trusted to run the pumps day to day."""
    client, _ = farm
    r = client.delete("/api/v2/care/houses/H1",
                      headers=_tok("o", "t_a", ROLE_OPERATOR))
    assert r.status_code == 403


def test_an_operator_can_water_and_can_stop(farm):
    """`stop` is deliberately at the same level as `water`: whoever can start a
    pump must be able to stop one, or the guard becomes a safety inversion."""
    client, _ = farm
    w = client.post("/api/v2/care/houses/H1/sections/S1/water",
                    headers=_tok("o", "t_a", ROLE_OPERATOR),
                    json={"durationSec": 30})
    assert w.status_code == 200, w.text

    s = client.post("/api/v2/care/houses/H1/sections/S1/stop",
                    headers=_tok("o", "t_a", ROLE_OPERATOR))
    assert s.status_code == 200, s.text


def test_no_farm_write_ever_lands_outside_the_callers_tenant(farm):
    """Not "the response looked right" - the actual paths written. A leak here
    would be a write into another customer's farm."""
    client, db = farm
    before = set(db)
    r = client.post("/api/v2/care/houses/H1/sections/S1/water",
                    headers=_tok("a", "t_a", ROLE_ADMIN), json={"durationSec": 30})
    assert r.status_code == 200, r.text
    written = set(db) - before
    assert written, "the request wrote nothing; the test proves nothing"
    for path in written:
        assert path.startswith("/tenants/t_a/") or path.startswith("/devices/"), path
