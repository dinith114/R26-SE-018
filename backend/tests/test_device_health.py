"""The hardware health checks: a fault is caught, said once, and nothing that is
working normally is ever reported.

Every reading here is TEST DATA built for one situation at a time - a DHT22 that
stops, a board with no light sensor, a sensor that freezes, a node that goes
quiet - so each check has a known right answer. The false-alarm cases matter as
much as the faults: a checker that cries wolf is switched off by the farmer.
"""
import pytest
from fastapi.testclient import TestClient

from app.services import device_health as dh
from app.services.firebase_auth import ROLE_VIEWER, set_decoder

T0 = 1_791_000_000_000          # ms
MIN = 60_000
TENANT = "t_a"


@pytest.fixture(autouse=True)
def _fresh():
    dh.reset()
    yield
    dh.reset()


def rec(i, t=27.0, h=75.0, light=-999, soil=-999):
    """One reading, i minutes after T0. Defaults: a DHT22-only calibration board."""
    return {"timestamp": T0 + i * MIN, "temperature": t, "humidity": h,
            "light": light, "sampleMoisture": soil}


def farm(latest, lifecycle=None, extra=None):
    meta = {"name": "Shade house"}
    if lifecycle:
        meta["lifecycle"] = lifecycle
    sec = {"meta": {"name": "S1"}, "latest": latest, **(extra or {})}
    return {"H1": {"meta": meta, "sections": {"S1": sec}}}


def run(readings, lifecycle=None, extra=None, now_after_min=0.5, acting=True):
    """Feed one reading per engine tick; return every fault STARTED, in order."""
    started = []
    for i, r in enumerate(readings):
        now = r["timestamp"] + now_after_min * MIN
        f = farm(r, lifecycle, extra)
        started += dh.check_farm(TENANT, f, now, ["H1"] if acting and not lifecycle else [])
    return started


def jitter(i):
    """A healthy DHT22 in a shade house: drifts by tenths, never sits still."""
    return round(27.0 + 0.1 * ((i * 7) % 5), 1), round(75.0 + 0.1 * ((i * 3) % 7), 1)


# ── nothing wrong, nothing said ─────────────────────────────────────────────

def test_a_healthy_dht22_only_board_raises_nothing_in_three_hours():
    """light -999 and no tray probe for ever is how a calibration board is BUILT."""
    readings = [rec(i, *jitter(i)) for i in range(180)]
    assert run(readings) == []
    assert run(readings, lifecycle="calibrating") == []


def test_one_missed_dht22_read_is_not_a_fault():
    readings = [rec(i, *jitter(i)) for i in range(10)]
    readings[5] = rec(5, -999, -999)
    assert run(readings) == []


def test_the_same_reading_seen_on_several_ticks_counts_once():
    st = dh._Section()
    r = rec(0)
    assert dh.observe(st, r, T0) is True
    assert dh.observe(st, r, T0 + MIN) is False
    assert len(st.hist) == 1


def test_a_board_switched_off_for_weeks_is_not_suddenly_silent_at_deploy():
    """The first pass after a deploy sees H1's month-old latest: no alarm."""
    old = rec(0)
    assert dh.check_farm(TENANT, farm(old), T0 + 30 * 24 * 60 * MIN, ["H1"]) == []


def test_a_freed_section_is_forgotten_not_called_silent():
    readings = [rec(i, *jitter(i)) for i in range(5)]
    run(readings)
    # apply-placement deletes latest when the sensor is taken out
    gone = {"H1": {"meta": {}, "sections": {"S1": {"meta": {}}}}}
    assert dh.check_farm(TENANT, gone, T0 + 60 * MIN, ["H1"]) == []
    assert (TENANT, "H1", "S1") not in dh._SECTIONS


def test_saturated_air_holding_still_all_night_is_not_frozen():
    readings = [rec(i, 24.0, 99.9) for i in range(150)]
    assert [x["kind"] for x in run(readings)] == []


# ── faults: caught, once ────────────────────────────────────────────────────

def test_an_unplugged_dht22_is_caught_within_minutes_and_said_once():
    readings = [rec(i, *jitter(i)) for i in range(5)] + [rec(i, -999, -999) for i in range(5, 15)]
    started = run(readings)
    assert [x["kind"] for x in started] == ["dht"]
    issue = started[0]
    assert issue["sectionId"] == "S1" and "DATA to D4" in issue["message"]
    assert issue["key"].startswith("H1-S1-dev-dht-")


def test_a_fault_that_clears_and_returns_alarms_again_under_a_new_key():
    bad = lambda a, b: [rec(i, -999, -999) for i in range(a, b)]
    good = lambda a, b: [rec(i, *jitter(i)) for i in range(a, b)]
    started = run(good(0, 3) + bad(3, 8) + good(8, 12) + bad(12, 17))
    keys = [x["key"] for x in started]
    assert len(keys) == 2 and keys[0] != keys[1] and keys[1].endswith("-2")


def test_a_light_sensor_that_worked_and_stopped_is_caught():
    readings = [rec(i, *jitter(i), light=12000) for i in range(5)]
    readings += [rec(i, *jitter(i), light=-999) for i in range(5, 20)]
    assert [x["kind"] for x in run(readings)] == ["light"]


def test_a_frozen_sensor_is_caught_after_two_hours():
    readings = [rec(i, 27.3, 74.6) for i in range(130)]
    started = run(readings)
    assert [x["kind"] for x in started] == ["frozen"]


def test_jumping_readings_from_a_loose_connector_are_caught():
    readings = []
    for i in range(30):
        t, h = jitter(i)
        if i in (10, 11, 20, 21):
            t += 8.0                                  # in and out of contact
        readings.append(rec(i, t, h))
    assert [x["kind"] for x in run(readings)] == ["erratic"]


def test_a_node_that_was_reporting_and_stopped_is_called_silent():
    readings = [rec(i, *jitter(i)) for i in range(5)]
    run(readings)
    last = readings[-1]
    started = dh.check_farm(TENANT, farm(last), last["timestamp"] + 25 * MIN, ["H1"])
    assert [x["kind"] for x in started] == ["silent"]
    assert "power" in started[0]["message"].lower()


# ── commands and trays: only where the system sends them ────────────────────

def _cmd(issued_min, ack=None):
    extra = {"command": {"id": "c1", "action": "water", "durationSec": 40,
                         "issuedAtSec": (T0 + issued_min * MIN) / 1000}}
    if ack:
        extra["commandAck"] = {"id": ack}
    return extra


def test_a_command_never_carried_out_is_caught_on_a_working_house():
    readings = [rec(i, *jitter(i)) for i in range(6)]
    started = run(readings, extra=_cmd(1))
    assert [x["kind"] for x in started] == ["command"]
    assert "current sensor" in started[0]["message"]      # says what it cannot see


def test_a_confirmed_command_is_fine():
    readings = [rec(i, *jitter(i)) for i in range(6)]
    assert run(readings, extra=_cmd(1, ack="c1")) == []


def test_a_calibrating_house_gets_sensor_checks_but_no_care_checks():
    readings = [rec(i, *jitter(i)) for i in range(4)] + [rec(i, -999, -999) for i in range(4, 10)]
    extra = {**_cmd(1), "tray": {"trayResponds": False}}
    started = run(readings, lifecycle="calibrating", extra=extra)
    assert [x["kind"] for x in started] == ["dht"]


def test_a_tray_that_did_not_fill_is_said():
    readings = [rec(i, *jitter(i)) for i in range(3)]
    started = run(readings, extra={"tray": {"trayResponds": False}})
    assert [x["kind"] for x in started] == ["tray-fill"]


# ── the engine raises them through the existing alarm path ──────────────────

def test_the_engine_raises_each_new_fault_as_one_pushed_alarm(monkeypatch):
    from app.api.routes import automation as auto
    from app.services.tenant_context import tenant_scope
    from datetime import datetime, timezone

    raised = []
    state = {"lastPlanDay": None, "lastTray": None, "lastSpatial": None, "lastTick": None}
    now = datetime.fromtimestamp((T0 + 17 * MIN + 30_000) / 1000, tz=timezone.utc)
    state.update(lastPlanDay=auto._today(now), lastTray=now, lastSpatial=now)
    # Two failed reads seen on earlier ticks; the engine's own tick sees the
    # third, which is the one that makes it a fault.
    readings = [rec(15, -999, -999), rec(16, -999, -999), rec(17, -999, -999)]
    for r in readings[:-1]:
        dh.check_farm("t_x", farm(r), r["timestamp"] + 30_000, ["H1"])
    monkeypatch.setattr(auto, "_state_for", lambda t: state)
    monkeypatch.setattr(auto, "_fb_get", lambda p: farm(readings[-1]) if p == "/farm/houses.json" else None)
    monkeypatch.setattr(auto, "run_watering_link", lambda now, houses: {})
    monkeypatch.setattr(auto, "_flush_pending_pushes", lambda: None)
    monkeypatch.setattr(auto, "get_auto_mode", lambda: False)
    monkeypatch.setattr(auto, "_raise_alarm", lambda *a, **k: raised.append((a, k)))
    with tenant_scope("t_x"):
        auto._engine_pass(now)
        auto._engine_pass(now)                        # a second tick: nothing new
    assert len(raised) == 1
    (kind, key, title, _msg, hid, sid), kw = raised[0]
    assert kind == "action" and kw["action"] == "check-device"
    assert hid == "H1" and sid == "S1" and "-dev-dht-" in key


# ── the route the app reads ─────────────────────────────────────────────────

def test_the_health_route_lists_what_is_wrong_per_section():
    readings = [rec(i, *jitter(i)) for i in range(3)] + [rec(i, -999, -999) for i in range(3, 9)]
    for r in readings:
        dh.check_farm(TENANT, farm(r), r["timestamp"] + 30_000, ["H1"])

    def _decode(token):
        uid, tenant, role = token.split("@")
        return {"uid": uid, "tenantId": tenant, "role": role}

    set_decoder(_decode)
    try:
        from app.main import app
        client = TestClient(app)
        hdr = {"Authorization": f"Bearer u1@{TENANT}@{ROLE_VIEWER}"}
        body = client.get("/api/v2/care/houses/H1/health", headers=hdr).json()
        assert body["checkedAtMs"] is not None
        assert [i["kind"] for i in body["sections"]["S1"]] == ["dht"]
        assert set(body["sections"]["S1"][0]) == {"kind", "title", "message", "sinceMs"}
        other = client.get("/api/v2/care/houses/H9/health", headers=hdr).json()
        assert other["sections"] == {}
    finally:
        set_decoder(None)
