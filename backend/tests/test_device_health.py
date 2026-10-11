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
    sec = {"meta": {"name": "S1"}, "latest": latest, "deviceMac": "A1B2C3D4E5F6",
           **(extra or {})}
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


bad = lambda a, b: [rec(i, -999, -999) for i in range(a, b)]
good = lambda a, b: [rec(i, *jitter(i)) for i in range(a, b)]


def test_a_fault_that_really_clears_and_returns_alarms_again_under_a_new_key():
    # Fixed for 40 minutes - longer than CLEAR_AFTER_MS - then broken again.
    started = run(good(0, 3) + bad(3, 8) + good(8, 48) + bad(48, 53))
    keys = [x["key"] for x in started]
    assert len(keys) == 2 and keys[0] != keys[1]


def test_a_flapping_wire_is_one_alarm_not_one_per_flap():
    """Found in review: a loose DHT22 wire making and breaking contact every few
    minutes started and cleared a fault on each flap - ~150 pushes a night."""
    seq = []
    for start in range(0, 600, 10):                    # ten hours: 6 min bad, 4 min good
        seq += bad(start, start + 6) + good(start + 6, start + 10)
    assert [x["kind"] for x in run(seq)] == ["dht"]


def test_one_fault_alarms_at_most_three_times_a_day():
    seq = good(0, 3)
    t = 3
    for _ in range(6):                                 # six real recurrences, 35 min apart
        seq += bad(t, t + 5) + good(t + 5, t + 40)
        t += 40
    started = run(seq)
    assert len(started) == dh.MAX_ALARMS_PER_DAY == 3
    # ...and the fault is still on the screens after the cap.
    assert ("t_a", "H1", "S1") in dh._SECTIONS


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

MASTER = "AABBCCDDEEFF"


def _queue(issued_min, section="S1"):
    """The master's queue as _issue_node_command writes it - where EVERY pour goes."""
    return {"c1": {"action": "water", "durationSec": 40, "targetSection": section,
                   "issuedAtSec": (T0 + issued_min * MIN) / 1000, "routedTo": MASTER}}


def _run_with_master(readings, queue):
    started = []
    for r in readings:
        f = farm(r)
        f["H1"]["meta"]["masterMac"] = MASTER
        started += dh.check_farm(TENANT, f, r["timestamp"] + 30_000, ["H1"],
                                 master_queues={MASTER: queue})
    return started


def test_a_pour_left_in_the_masters_queue_is_caught():
    """The first version read the SECTION's command document - pours do not go
    there - so it could never have seen one. Found in review."""
    readings = [rec(i, *jitter(i)) for i in range(6)]
    started = _run_with_master(readings, _queue(-25))       # 25 min old, never run
    assert [x["kind"] for x in started] == ["command"]
    assert "master" in started[0]["message"] and "current sensor" in started[0]["message"]


def test_a_pour_the_master_ran_leaves_nothing_to_say():
    readings = [rec(i, *jitter(i)) for i in range(6)]
    assert _run_with_master(readings, {}) == []         # the master deletes it after acking
    # ...nor one still within its run time plus grace.
    dh.reset()
    assert _run_with_master(readings[:2], _queue(1)) == []
    # ...nor two pours queued together: a working master runs them one at a time,
    # so the second legitimately waits for the first. Found in review.
    dh.reset()
    two = {**_queue(-10), "c2": {**_queue(-10)["c1"], "durationSec": 120}}
    assert _run_with_master(readings, two) == []


def test_a_calibrating_house_gets_sensor_checks_but_no_care_checks():
    readings = [rec(i, *jitter(i)) for i in range(4)] + [rec(i, -999, -999) for i in range(4, 10)]
    started = []
    for r in readings:
        f = farm(r, "calibrating", {"tray": {"trayResponds": False}})
        f["H1"]["meta"]["masterMac"] = MASTER
        started += dh.check_farm(TENANT, f, r["timestamp"] + 30_000, [],
                                 master_queues={MASTER: _queue(-25)})
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



# ── 8 Oct review: each finding, as a test that failed before its fix ────────

def test_a_failed_farm_download_does_not_wipe_what_is_known():
    """_fb_get returns None on a timeout and the engine turned it into {}. The
    forget loop then dropped every section: a node already dead was never
    "silent" again, and the app showed a green all-clear."""
    run([rec(i, *jitter(i)) for i in range(5)])
    assert dh.check_farm(TENANT, {}, T0 + 6 * MIN, ["H1"]) == []
    assert (TENANT, "H1", "S1") in dh._SECTIONS
    later = dh.check_farm(TENANT, farm(rec(4, *jitter(4))), T0 + 30 * MIN, ["H1"])
    assert [x["kind"] for x in later] == ["silent"]


def test_a_stuck_pour_is_reported_for_a_section_with_no_node():
    """Every pour goes through the master, so a section whose own node is dead
    or absent is still watered - and a pour stuck for it must still be said."""
    f = {"H1": {"meta": {"name": "H", "masterMac": MASTER},
                "sections": {"S7": {"meta": {"name": "S7"}}}}}     # no node at all
    started = dh.check_farm(TENANT, f, T0 + 30 * MIN, ["H1"],
                            master_queues={MASTER: _queue(-5, section="S7")})
    assert [(x["kind"], x["sectionId"]) for x in started] == [("command", "S7")]


def test_a_battery_dying_after_a_wifi_drop_is_said_again():
    """Silent at 13:20, back at 13:25, dead at 13:30: the second outage used to
    be folded into the first (still in its 30-minute clear-down) and never said."""
    seq = [rec(i, *jitter(i)) for i in range(5)]                    # 00:00-00:04
    run(seq)
    first = dh.check_farm(TENANT, farm(seq[-1]), seq[-1]["timestamp"] + 25 * MIN, ["H1"])
    back = [rec(i, *jitter(i)) for i in range(30, 34)]               # reports again
    run(back)
    second = dh.check_farm(TENANT, farm(back[-1]), back[-1]["timestamp"] + 25 * MIN, ["H1"])
    assert [x["kind"] for x in first] == ["silent"] and [x["kind"] for x in second] == ["silent"]
    assert first[0]["key"] != second[0]["key"]


def test_a_new_fault_after_a_restart_gets_its_own_key():
    """The key used a per-day counter that restarted with the server, so the
    first fault after a deploy reused that morning's acknowledged key and
    _raise_alarm wrote nothing."""
    before = run([rec(i, *jitter(i)) for i in range(3)] + bad(3, 8))
    dh.reset()                                                       # the deploy
    after = run([rec(i, *jitter(i)) for i in range(400, 403)] + bad(403, 408))
    assert before[0]["key"] != after[0]["key"]


def test_a_node_that_died_shortly_before_a_restart_is_still_caught():
    """seen_live needed a reading under 20 min old at first sight, so a node that
    died an hour before a deploy could never be called silent."""
    last = rec(0, *jitter(0))
    started = dh.check_farm(TENANT, farm(last), last["timestamp"] + 60 * MIN, ["H1"])
    assert [x["kind"] for x in started] == ["silent"]


def test_an_unlinked_section_is_not_called_silent():
    """Unlinking deletes deviceMac but leaves latest; twenty minutes later the
    section was reported as a node that stopped."""
    run([rec(i, *jitter(i)) for i in range(5)])
    f = farm(rec(4, *jitter(4)))
    del f["H1"]["sections"]["S1"]["deviceMac"]
    assert dh.check_farm(TENANT, f, T0 + 40 * MIN, ["H1"]) == []
