"""The property this entire stage exists for.

Two tenants, one fake database, real routing. Tenant A must not be able to see
or change anything of tenant B's, and the only thing separating them is the
token - there is no parameter either of them could change to reach the other.

This also proves the role table: a Viewer can read but never act, an Operator
can act on the farm (including STOP, which must never be harder to reach than
START) but cannot reconfigure it, and only an Admin can reconfigure or destroy.

THE DEVICE REGISTRY IS IN THE FIXTURE ON PURPOSE. /devices is deliberately
outside /farm/, so the path chokepoint does not rewrite it and cannot protect
it. Every cross-tenant assertion below therefore has to name devices explicitly:
the first version of this file allowed anything under /devices/ and asserted on
response TEXT, and it passed the whole time /overview was handing tenant A
tenant B's MAC and IP, and the whole time deleting A's house unassigned B's
boards.
"""
import pytest
from fastapi.testclient import TestClient

from app.services.firebase_auth import (
    ROLE_ADMIN, ROLE_OPERATOR, ROLE_VIEWER, set_decoder,
)

# Tenant A's board, and two of tenant B's. B's sit on H1/S1 and H1/S5 - the
# SAME ids as A's own sections, which is the whole point: house and section ids
# are generated per tenant, so every farm has an H1 and its first section is S1.
A_NODE = "AA02AA02AA02"
B_NODE_S1 = "BB01BB01BB01"
B_NODE_S5 = "BB05BB05BB05"
B_IP = "10.9.9.9"

SECTIONS = ("S1", "S2", "S3", "S4", "S5")


# Ten minutes old. Against the 15 s default that is stale and untrusted; against
# the hour-long interval of tenant B's board it is comfortably live. The gap
# between those two answers is the whole assertion in the freshness test.
STALE_MINUTES = 10


def _sections(prefix, stale_ts=None):
    out = {sid: {"meta": {"name": f"{prefix}-{sid}"}} for sid in SECTIONS}
    if stale_ts is not None:
        out["S1"]["latest"] = {"temperature": 27.0, "humidity": 75.0,
                               "light": 900.0, "timestamp": stale_ts}
    return out


@pytest.fixture
def farm(monkeypatch):
    """A fake Firebase holding two tenants' farms, and a client over the real app."""
    import time
    stale = (time.time() - STALE_MINUTES * 60) * 1000.0
    db = {
        # /overview reads the whole houses tree in one shot.
        "/tenants/t_a/farm/houses.json": {
            "H1": {"meta": {"name": "Farm A"}, "sections": _sections("A", stale)}},
        "/tenants/t_b/farm/houses.json": {
            "H1": {"meta": {"name": "Farm B"}, "sections": _sections("B", stale)}},
        # water/stop read one key at a time rather than the merged tree above,
        # so those exact paths need their own entries. masterMac is set so
        # `stop` takes its normal "nothing is pouring" 200 path instead of
        # falling through to the direct-node path, which 500s with no relay
        # channel wired - a channel this test has no reason to configure.
        "/tenants/t_a/farm/houses/H1/meta.json": {"name": "Farm A", "masterMac": "AA:A1"},
        "/tenants/t_b/farm/houses/H1/meta.json": {"name": "Farm B", "masterMac": "BB:B1"},
        # apply-placement reads the sections collection on its own.
        "/tenants/t_a/farm/houses/H1/sections.json": _sections("A"),
        "/tenants/t_b/farm/houses/H1/sections.json": _sections("B"),
        # GET /houses/{h} reads the whole house document in one shot.
        "/tenants/t_a/farm/houses/H1.json": {"meta": {"name": "Farm A"},
                                             "sections": _sections("A", stale)},
        "/tenants/t_b/farm/houses/H1.json": {"meta": {"name": "Farm B"},
                                             "sections": _sections("B", stale)},
        # THE REGISTRY IS GLOBAL. Not under /tenants/ - that is the design, and
        # it is why every reader has to narrow it by hand.
        "/devices.json": {
            A_NODE: {"tenantId": "t_a", "assignedTo": "H1/S2", "ip": "10.0.0.1",
                     "fw": "validation-1.9", "lastSeen": 9e12},
            # An HOUR between readings, deliberately. /alerts never prints a
            # MAC, so the only way this leak shows is behavioural: read across
            # tenants and tenant A's section is judged against tenant B's
            # reporting interval - see the freshness test below.
            B_NODE_S1: {"tenantId": "t_b", "assignedTo": "H1/S1", "ip": B_IP,
                        "fw": "validation-1.9", "lastSeen": 9e12,
                        "readIntervalMs": 3_600_000},
            B_NODE_S5: {"tenantId": "t_b", "assignedTo": "H1/S5", "ip": B_IP,
                        "fw": "validation-1.9", "lastSeen": 9e12},
        },
    }
    for tid in ("t_a", "t_b"):
        for sid in SECTIONS:
            name = ("A" if tid == "t_a" else "B") + "-" + sid
            db[f"/tenants/{tid}/farm/houses/H1/sections/{sid}.json"] = {
                "meta": {"name": name}}
            # `stop` checks the section exists via its meta specifically, an
            # exact key distinct from the whole-section document above.
            db[f"/tenants/{tid}/farm/houses/H1/sections/{sid}/meta.json"] = {
                "name": name}

    # DELIBERATELY the same objects, not copies: real Firebase is a tree, so a
    # write to /devices/{mac}/x IS visible from /devices.json. The aliasing is
    # what models that.
    for mac, rec in db["/devices.json"].items():
        db[f"/devices/{mac}.json"] = rec

    writes = []

    class _Resp:
        def __init__(self, body):
            self.body = body
            self.status_code = 200 if body is not None else 404

        def json(self):
            return self.body

    class _Req:
        @staticmethod
        def _path(url):
            return url.split("firebaseio.com", 1)[-1]

        def get(self, url, **kw):
            return _Resp(db.get(self._path(url)))

        def put(self, url, **kw):
            p = self._path(url)
            writes.append(p)
            db[p] = kw.get("json")
            if p.startswith("/devices/") and p.endswith("/assignedTo.json"):
                db["/devices.json"][p.split("/")[2]]["assignedTo"] = kw.get("json")
            return _Resp({})

        def delete(self, url, **kw):
            p = self._path(url)
            writes.append(p)
            db.pop(p, None)
            if p.startswith("/devices/") and p.endswith("/assignedTo.json"):
                db["/devices.json"].get(p.split("/")[2], {}).pop("assignedTo", None)
            return _Resp({})

        patch = post = put

    from app.api.routes import devices, smart_care_v2, smart_watering
    for mod in (smart_watering, smart_care_v2, devices):
        monkeypatch.setattr(mod, "_req", _Req(), raising=False)
    smart_care_v2._DEVICE_CACHE["devices"] = None

    def _decode(token):
        uid, tenant, role = token.split("@")
        return {"uid": uid, "tenantId": tenant, "role": role}

    set_decoder(_decode)

    # No `with`: the lifespan would start the automation engine, a 60-second
    # clock that issues real watering commands against whatever Firebase it
    # finds - see test_main_wiring.py for the same reasoning.
    from app.main import app
    yield TestClient(app), db, writes
    set_decoder(None)


def _tok(uid, tenant, role):
    return {"Authorization": f"Bearer {uid}@{tenant}@{role}"}


def test_a_farm_route_with_no_token_is_401(farm):
    client, _, _ = farm
    assert client.get("/api/v2/care/overview").status_code == 401


def test_each_tenant_sees_only_its_own_farm(farm):
    """The test this whole stage exists for. Same endpoint, same shape of
    request, and the only difference is whose token it is.

    THE NEGATIVE HALF IS THE POINT. Asserting "Farm A is in A's response" was
    all this said for a while, and it passed the entire time /overview was
    handing tenant A tenant B's MAC and IP - because a leak adds to a payload,
    it does not remove anything. So sweep the whole payload for anything that
    belongs to the other tenant, devices included.
    """
    client, _, _ = farm
    a = client.get("/api/v2/care/overview", headers=_tok("ua", "t_a", ROLE_ADMIN))
    b = client.get("/api/v2/care/overview", headers=_tok("ub", "t_b", ROLE_ADMIN))
    assert a.status_code == 200 and b.status_code == 200
    assert "Farm A" in a.text and "Farm A" not in b.text
    assert "Farm B" in b.text and "Farm B" not in a.text

    for leaked in (B_NODE_S1, B_NODE_S5, B_IP, "Farm B", "B-S1"):
        assert leaked not in a.text, f"{leaked} leaked into tenant A's overview"
    for leaked in (A_NODE, "10.0.0.1", "Farm A", "A-S1"):
        assert leaked not in b.text, f"{leaked} leaked into tenant B's overview"


@pytest.mark.parametrize("path", ["/api/v2/care/overview",
                                  "/api/v2/care/houses/H1",
                                  "/api/v2/care/alerts"])
def test_no_read_route_shows_another_farms_board(farm, path):
    """A LOOP over every read that joins sections to nodes.

    Each of these matches `assignedTo == "H1/S1"` against the registry, and
    "H1/S1" exists on every farm on the platform. The failure is not a rare
    collision - it is deterministic.
    """
    client, _, _ = farm
    r = client.get(path, headers=_tok("ua", "t_a", ROLE_ADMIN))
    assert r.status_code == 200, r.text
    assert B_NODE_S1 not in r.text, f"{path} leaked another farm's MAC"
    assert B_NODE_S5 not in r.text, f"{path} leaked another farm's MAC"
    assert B_IP not in r.text, f"{path} leaked another farm's IP"


def test_alerts_judge_a_section_by_its_own_nodes_interval(farm):
    """The half of the /alerts leak that no text assertion can see.

    /alerts never prints a MAC, so reading the registry across tenants leaves
    the payload looking perfectly innocent. What crosses over is the reporting
    INTERVAL: tenant A's S1 has a ten-minute-old reading and no node of its own,
    which against the 15 s default is stale and untrusted. Matched against
    tenant B's board on ITS "H1/S1" - an hour between readings - ten minutes is
    live, and A is told nothing at all while their section has gone quiet.
    """
    client, _, _ = farm
    r = client.get("/api/v2/care/alerts", headers=_tok("ua", "t_a", ROLE_ADMIN))
    assert r.status_code == 200, r.text
    ids = {i["id"] for i in r.json()["alerts"]}
    assert "H1-S1-stale" in ids, (
        "A's quiet section was judged against another farm's reporting interval")


def test_a_viewer_cannot_water(farm):
    client, _, _ = farm
    r = client.post("/api/v2/care/houses/H1/sections/S1/water",
                    headers=_tok("v", "t_a", ROLE_VIEWER), json={"durationSec": 30})
    assert r.status_code == 403


def test_a_viewer_cannot_fill_the_tray(farm):
    client, _, _ = farm
    r = client.post("/api/v2/care/houses/H1/sections/S1/tray-fill",
                    headers=_tok("v", "t_a", ROLE_VIEWER), json={"fillSeconds": 10})
    assert r.status_code == 403


def test_an_operator_cannot_change_the_mode(farm):
    client, _, _ = farm
    r = client.put("/api/v2/care/houses/H1/sections/S1/mode",
                   headers=_tok("o", "t_a", ROLE_OPERATOR),
                   json={"mode": "manual"})
    assert r.status_code == 403


def test_an_operator_cannot_delete_a_house(farm):
    """Configuration and destruction are Admin-only, even for whoever is
    trusted to run the pumps day to day."""
    client, _, _ = farm
    r = client.delete("/api/v2/care/houses/H1",
                      headers=_tok("o", "t_a", ROLE_OPERATOR))
    assert r.status_code == 403


def test_an_operator_can_water_and_can_stop(farm):
    """`stop` is deliberately at the same level as `water`: whoever can start a
    pump must be able to stop one, or the guard becomes a safety inversion."""
    client, _, _ = farm
    w = client.post("/api/v2/care/houses/H1/sections/S1/water",
                    headers=_tok("o", "t_a", ROLE_OPERATOR),
                    json={"durationSec": 30})
    assert w.status_code == 200, w.text

    s = client.post("/api/v2/care/houses/H1/sections/S1/stop",
                    headers=_tok("o", "t_a", ROLE_OPERATOR))
    assert s.status_code == 200, s.text


# ── writes ───────────────────────────────────────────────────────────────────

# Every route that changes something, not just `water`. The allow-list version
# of this test ran only the watering path, and watering writes nothing under
# /devices - so the one hole it left open (anything under /devices/) was never
# exercised by the one route it ran. The DESTRUCTIVE routes are the ones that
# went through that hole.
WRITING_ROUTES = [
    ("post", "/api/v2/care/houses/H1/sections/S1/water", {"durationSec": 30}),
    ("delete", "/api/v2/care/houses/H1/sections/S1", None),
    ("post", "/api/v2/care/houses/H1/apply-placement",
     {"keep": ["S1", "S2", "S3", "S4"]}),
    ("delete", "/api/v2/care/houses/H1", None),
]


def _owner(db, path):
    """Whose board is this /devices/... path about, from the pre-request state."""
    return (db["/devices.json"].get(path.split("/")[2]) or {}).get("tenantId")


@pytest.mark.parametrize("method,url,body", WRITING_ROUTES)
def test_no_write_ever_lands_outside_the_callers_tenant(farm, method, url, body):
    """Not "the response looked right" - the actual paths written.

    THE ALLOW-LIST USED TO SAY `startswith("/devices/")`, unconditionally, and
    that escape hatch is exactly the hole the cross-tenant unassign went
    through: deleting tenant A's house wrote
    DELETE /devices/<tenant B's MAC>/assignedTo.json and the test called it
    fine. A /devices path is allowed only for a board this caller actually owns.
    """
    client, db, writes = farm
    kw = {"headers": _tok("a", "t_a", ROLE_ADMIN)}
    if body is not None:
        kw["json"] = body
    r = getattr(client, method)(url, **kw)
    assert r.status_code == 200, r.text
    assert writes, "the request wrote nothing; the test proves nothing"

    for path in writes:
        if path.startswith("/tenants/t_a/"):
            continue
        assert path.startswith("/devices/"), path
        assert _owner(db, path) in (None, "t_a"), (
            f"{method.upper()} {url} wrote {path}, which is another tenant's board")


@pytest.mark.parametrize("method,url,body", WRITING_ROUTES)
def test_another_farms_boards_keep_their_assignment(farm, method, url, body):
    """The harm, stated as the harm rather than as a path.

    B's node keeps reporting to its compiled-in section either way, so readings
    still arrive - which is what made this silent. What breaks is the LINK:
    "No sensor node", freshness `nonode`, offline alarms, and the section
    offered for reassignment, all from a routine action in another account.
    """
    client, db, _ = farm
    kw = {"headers": _tok("a", "t_a", ROLE_ADMIN)}
    if body is not None:
        kw["json"] = body
    assert getattr(client, method)(url, **kw).status_code == 200

    assert db["/devices.json"][B_NODE_S1].get("assignedTo") == "H1/S1"
    assert db["/devices.json"][B_NODE_S5].get("assignedTo") == "H1/S5"
    assert db["/devices/" + B_NODE_S1 + ".json"] is not None


def test_deleting_a_house_frees_the_callers_own_nodes(farm):
    """The mirror, and it has to exist.

    A filter that refuses everything passes every test above and quietly stops
    the farmer's own hardware ever being released - which shows up much later,
    as a section that can never be given a new board.
    """
    client, db, _ = farm
    r = client.delete("/api/v2/care/houses/H1", headers=_tok("a", "t_a", ROLE_ADMIN))
    assert r.status_code == 200, r.text
    assert r.json()["nodesFreed"] == [A_NODE], r.json()
    assert "assignedTo" not in db["/devices.json"][A_NODE]
