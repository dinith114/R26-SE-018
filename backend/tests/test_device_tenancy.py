"""Devices belong to a tenant, and the chokepoint cannot help here.

`/devices/{mac}` is deliberately NOT under `/farm/`, because a board belongs to
nobody until it is flashed with a tenant. That is the right design and it has a
consequence: the path-scoping chokepoint that protects every farm read does not
protect these routes at all. Tenancy has to be enforced in this module or not at
all.

What that was worth before this file existed, measured: `list_devices` returned
every tenant's boards to any signed-in caller - MAC, IP, and which house and
section they were installed in - and `assign_device` had no ownership check, so
one farm's admin could take another farm's LIVE board into their own house. The
existing code deletes the previous holder's link when it does that, so the
victim's section would have gone dark mid-operation.

404, NEVER 403, for another tenant's device. A 403 confirms the MAC exists on
the platform, which is the leak wearing a different hat.
"""
import pytest
from fastapi.testclient import TestClient

from app.services.firebase_auth import ROLE_ADMIN, set_decoder

MINE, THEIRS, LOOSE = "AA11AA11AA11", "BB22BB22BB22", "CC33CC33CC33"


@pytest.fixture
def farm(monkeypatch):
    """Two tenants' boards plus one nobody has claimed, over the real app."""
    db = {
        "/devices.json": {
            MINE:   {"tenantId": "t_a", "assignedTo": "H1/S1", "ip": "10.0.0.1",
                     "fw": "validation-1.9", "lastSeen": 9e12},
            THEIRS: {"tenantId": "t_b", "assignedTo": "H9/S9", "ip": "10.0.0.2",
                     "fw": "validation-1.9", "lastSeen": 9e12},
            LOOSE:  {"ip": "10.0.0.3", "fw": "validation-1.9", "lastSeen": 9e12},
        },
    }
    for mac, rec in db["/devices.json"].items():
        db[f"/devices/{mac}.json"] = rec

    class _Resp:
        def __init__(self, body):
            self.body = body
            self.status_code = 200

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
            db[p] = kw.get("json")
            # keep the collection view consistent with the per-device writes
            if p.startswith("/devices/") and p.endswith("/tenantId.json"):
                mac = p.split("/")[2]
                db["/devices.json"][mac]["tenantId"] = kw.get("json")
            if p.startswith("/devices/") and p.endswith("/assignedTo.json"):
                mac = p.split("/")[2]
                db["/devices.json"][mac]["assignedTo"] = kw.get("json")
            return _Resp({})

        def delete(self, url, **kw):
            p = self._path(url)
            db.pop(p, None)
            if p.startswith("/devices/") and p.endswith("/assignedTo.json"):
                db["/devices.json"].get(p.split("/")[2], {}).pop("assignedTo", None)
            return _Resp({})

        patch = post = put

    from app.api.routes import devices, smart_care_v2, smart_watering
    for mod in (smart_watering, smart_care_v2, devices):
        monkeypatch.setattr(mod, "_req", _Req(), raising=False)

    set_decoder(lambda t: dict(zip(("uid", "tenantId", "role"), t.split("@"))))
    from app.main import app
    yield TestClient(app), db
    set_decoder(None)


def _a(role=ROLE_ADMIN):
    return {"Authorization": f"Bearer ua@t_a@{role}"}


# ── listings ───────────────────────────────────────────────────────────────

def test_a_listing_shows_my_boards_and_unclaimed_ones_but_not_another_farms(farm):
    client, _ = farm
    r = client.get("/api/v2/devices/", headers=_a())
    assert r.status_code == 200
    macs = {d["mac"] for d in r.json()["devices"]}
    assert MINE in macs
    assert LOOSE in macs, "an unclaimed board must be claimable by anyone"
    assert THEIRS not in macs, "another farm's board was listed"
    assert "10.0.0.2" not in r.text, "another farm's board leaked in the payload"


def test_only_unassigned_still_works_and_still_hides_another_farms_board(farm):
    client, db = farm
    db["/devices.json"][THEIRS].pop("assignedTo")
    r = client.get("/api/v2/devices/?only_unassigned=true", headers=_a())
    macs = {d["mac"] for d in r.json()["devices"]}
    assert macs == {LOOSE}


# ── every single-device route ──────────────────────────────────────────────

def test_every_single_device_route_is_404_for_another_farms_board(farm):
    """A LOOP, not one test each, so a tenth route added without a check is
    more likely to be noticed. 404 rather than 403 throughout: a 403 confirms
    the MAC exists on the platform, which is the leak wearing a different hat.
    """
    client, _ = farm
    calls = [
        ("put",    f"/api/v2/devices/{THEIRS}/assign",   {"house": "H1", "section": "S1"}),
        ("delete", f"/api/v2/devices/{THEIRS}/assign",   None),
        ("put",    f"/api/v2/devices/{THEIRS}/interval", {"readIntervalMs": 15000}),
        ("post",   f"/api/v2/devices/{THEIRS}/identify", None),
        ("post",   f"/api/v2/devices/{THEIRS}/ping",     None),
        # ?token is a required query param; without it the 422 from body
        # validation would hide whether the ownership check ran at all.
        ("get",    f"/api/v2/devices/{THEIRS}/ping?token=1", None),
        ("post",   f"/api/v2/devices/{THEIRS}/scan",     None),
        ("get",    f"/api/v2/devices/{THEIRS}/scan",     None),
    ]
    for method, url, body in calls:
        kw = {"headers": _a()}
        if body is not None:
            kw["json"] = body
        r = getattr(client, method)(url, **kw)
        assert r.status_code == 404, f"{method.upper()} {url} -> {r.status_code}"
        assert "403" not in r.text


def test_my_own_board_is_reachable_on_those_same_routes(farm):
    """The mirror of the test above. A filter that refused everything would
    pass that one and be useless."""
    client, _ = farm
    assert client.post(f"/api/v2/devices/{MINE}/identify",
                       headers=_a()).status_code == 200


# ── claiming ───────────────────────────────────────────────────────────────

def test_assigning_an_unclaimed_board_claims_it_for_my_farm(farm):
    """Without this, two tenants could each claim the same board and the second
    would silently take it from the first."""
    client, db = farm
    r = client.put(f"/api/v2/devices/{LOOSE}/assign", headers=_a(),
                   json={"house": "H1", "section": "S2"})
    assert r.status_code == 200, r.text
    assert db["/devices.json"][LOOSE]["tenantId"] == "t_a"


def test_assigning_another_farms_board_is_refused_and_changes_nothing(farm):
    """The damage this prevents is a live board taken mid-operation, so assert
    on the STORED record, not on the status code alone."""
    client, db = farm
    before = dict(db["/devices.json"][THEIRS])
    r = client.put(f"/api/v2/devices/{THEIRS}/assign", headers=_a(),
                   json={"house": "H1", "section": "S3"})
    assert r.status_code == 404
    assert db["/devices.json"][THEIRS] == before
    assert db["/devices.json"][THEIRS]["assignedTo"] == "H9/S9"


def test_unassigning_my_board_does_not_release_it_to_other_farms(farm):
    """Detaching a board from a section is what a farmer does when moving
    hardware around their OWN farm. Clearing the tenant would drop it back into
    the global pool where anybody could take it."""
    client, db = farm
    r = client.delete(f"/api/v2/devices/{MINE}/assign", headers=_a())
    assert r.status_code == 200, r.text
    assert db["/devices.json"][MINE].get("tenantId") == "t_a"
