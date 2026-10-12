"""What the 8 Oct 2026 end-to-end run found, each pinned so it cannot come back.

The run drove the real app over adb against the deployed backend, with virtual
nodes and a virtual master writing Firebase as firmware 2.5 does. Every case
below failed on the code of that evening. The houses, boards and readings here
are TEST DATA built for one situation each.
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.services.firebase_auth import ROLE_ADMIN, set_decoder

TENANT = "t_e2e"
BASE = f"/tenants/{TENANT}/farm"
NOW = datetime(2026, 10, 8, 6, 30, tzinfo=timezone(timedelta(minutes=330)))
NOW_MS = NOW.timestamp() * 1000


# ── a fake Firebase behind the real routes ──────────────────────────────────

@pytest.fixture
def api(monkeypatch):
    db = {
        f"{BASE}/houses/H1/meta.json": {"name": "Test house"},          # no master set
        f"{BASE}/houses/H1/sections/S1.json": {
            "meta": {"name": "S1"},
            "fertilizer": {"due": True, "npkType": "30-10-10", "npkForStage": "30-10-10",
                           "strength": 0.5, "intervalDays": 7}},
        f"{BASE}/houses/H1/sections/S1/meta.json": {"name": "S1"},
        "/devices.json": {
            "AABBCCDDEE01": {"mac": "AABBCCDDEE01", "quiet": True, "tenantId": TENANT},
            "AABBCCDDEE02": {"mac": "AABBCCDDEE02", "quiet": False, "tenantId": TENANT},
        },
    }

    class _Resp:
        def __init__(self, body):
            self.body = body
            self.status_code = 200

        def json(self):
            return self.body

    class _Req:
        @staticmethod
        def _path(url):
            return url.split("firebaseio.com", 1)[-1].split("?", 1)[0]

        def get(self, url, **kw):
            import copy
            return _Resp(copy.deepcopy(db.get(self._path(url))))

        def put(self, url, **kw):
            db[self._path(url)] = kw.get("json")
            return _Resp({})

        def delete(self, url, **kw):
            db.pop(self._path(url), None)
            return _Resp({})

        patch = post = put

    from app.api.routes import devices, smart_care_v2, smart_watering
    for mod in (smart_watering, smart_care_v2, devices):
        monkeypatch.setattr(mod, "_req", _Req(), raising=False)
    smart_care_v2._DEVICE_CACHE["devices"] = None
    set_decoder(lambda tok: dict(zip(("uid", "tenantId", "role"), tok.split("@"))))
    from app.main import app
    yield TestClient(app), db
    set_decoder(None)


TOK = {"Authorization": f"Bearer u1@{TENANT}@{ROLE_ADMIN}"}


# ── F4: Water Now with nothing to pour through ──────────────────────────────

def test_water_now_with_no_master_is_refused_and_records_nothing(api):
    """It answered "Watering for 45s", logged a watering and recorded a feed."""
    client, db = api
    r = client.post("/api/v2/care/houses/H1/sections/S1/water",
                    json={"durationSec": 45, "withFertilizer": True}, headers=TOK)
    assert r.status_code == 409
    assert "no master controller" in r.json()["detail"]
    written = [k for k in db if "/events/" in k or "/fertilizer/" in k or "waterCommand" in k]
    assert written == [], written


# ── F2: a recording-only board cannot be the master ─────────────────────────

def test_a_quiet_board_cannot_be_made_the_master(api):
    client, db = api
    r = client.put("/api/v2/care/houses/H1/master", json={"masterMac": "AABBCCDDEE01"}, headers=TOK)
    assert r.status_code == 409 and "QUIET" in r.json()["detail"]
    assert "masterMac" not in db[f"{BASE}/houses/H1/meta.json"]
    ok = client.put("/api/v2/care/houses/H1/master", json={"masterMac": "AABBCCDDEE02"}, headers=TOK)
    assert ok.status_code == 200
    assert db[f"{BASE}/houses/H1/meta.json"]["masterMac"] == "AABBCCDDEE02"


# ── F4b: the engine's automatic pours ───────────────────────────────────────

def _auto_farm():
    latest = {"timestamp": NOW_MS - 60_000, "temperature": 30.0, "humidity": 60.0}
    return {"H1": {"meta": {"name": "Test house"}, "sections": {"S1": {
        "meta": {"name": "S1"}, "latest": latest,
        "plan": {"date": "2026-10-08", "waterTime": "06:30", "durationSec": 40},
        "fertilizer": {"due": True, "npkType": "30-10-10"}}}}}


def test_an_automatic_watering_that_cannot_be_sent_is_not_marked_done(monkeypatch):
    """It marked the day watered, recorded a feed and said "Plants watered"."""
    from app.api.routes import automation as a
    seen = {"alarms": [], "done": [], "fed": [], "events": []}
    monkeypatch.setattr(a, "get_auto_mode", lambda: True)
    monkeypatch.setattr(a, "section_is_auto", lambda s, m=None: True)
    monkeypatch.setattr(a, "_already_done", lambda s, d, t: False)
    monkeypatch.setattr(a, "_issue_node_command", lambda *x, **k: None)
    monkeypatch.setattr(a, "_command_refusal", lambda *x: "no master controller is set for this house")
    monkeypatch.setattr(a, "_raise_alarm", lambda kind, key, title, msg, *x, **k:
                        seen["alarms"].append((kind, key, k.get("action"), msg)))
    monkeypatch.setattr(a, "_mark_done", lambda *x: seen["done"].append(x))
    monkeypatch.setattr(a, "_record_fertilized", lambda *x: seen["fed"].append(x))
    monkeypatch.setattr(a, "_log_event", lambda *x, **k: seen["events"].append(k))
    monkeypatch.setattr(a, "_fb_put", lambda *x: True)
    out = a.run_watering_link(NOW, _auto_farm())
    assert seen["done"] == [] and seen["fed"] == [] and seen["events"] == []
    assert out["watered"] == []
    (kind, key, action, msg), = seen["alarms"]
    assert kind == "action" and action == "check-device"
    assert key.startswith("H1-S1-cannot-water-") and "Nothing was poured" in msg


def test_an_automatic_tray_fill_that_cannot_be_sent_is_said(monkeypatch):
    """It started the cooldown and said nothing, so an empty tray stayed empty."""
    from app.api.routes import automation as a
    raised = []
    refused = {"status": "fill", "fillSeconds": 12, "humidity": 45.0,
               "autoCommanded": False, "autoRefused": "no tray pump channel is set for this house"}
    monkeypatch.setattr(a, "_run_per_section", lambda houses, fn, **k: {"H1-S1": refused})
    monkeypatch.setattr(a, "_fb_get", lambda p: {"meta": {"name": "S1"}})
    monkeypatch.setattr(a, "get_auto_mode", lambda: True)
    monkeypatch.setattr(a, "section_is_auto", lambda s, m=None: True)
    monkeypatch.setattr(a, "_raise_alarm", lambda kind, key, *x, **k: raised.append((key, k.get("action"))))
    a.run_tray_cycle(NOW, {"H1": {"meta": {}, "sections": {"S1": {}}}})
    assert len(raised) == 1
    assert raised[0][0].startswith("H1-S1-cannot-fill-") and raised[0][1] == "check-device"


def test_a_tray_alarm_names_the_house(monkeypatch):
    """'Section 4: humidity is 44.5%' did not say which house (8 Oct E2E run)."""
    from app.api.routes import automation as a
    raised = []
    fill = {"status": "fill", "fillSeconds": 15, "humidity": 44.5, "autoCommanded": False}
    monkeypatch.setattr(a, "_run_per_section", lambda houses, fn, **k: {"H2-S4": fill})
    monkeypatch.setattr(a, "_fb_get", lambda p: {"meta": {"name": "Section 4"}})
    monkeypatch.setattr(a, "get_auto_mode", lambda: False)
    monkeypatch.setattr(a, "section_is_auto", lambda s, m=None: False)
    monkeypatch.setattr(a, "_raise_alarm", lambda kind, key, title, msg, *x, **k: raised.append(msg))
    a.run_tray_cycle(NOW, {"H2": {"meta": {"name": "Back House"}, "sections": {"S4": {}}}})
    assert raised and raised[0].startswith("Back House · Section 4: humidity is 44.5%")


# ── F13: a feed that has happened is no longer due ──────────────────────────

def test_a_recorded_feed_is_no_longer_due(monkeypatch):
    """due stayed true until the next 05:00 plan: the afternoon watering fed again."""
    from app.api.routes import smart_care_v2 as sc
    from app.services.tenant_context import tenant_scope
    writes = {}
    monkeypatch.setattr(sc, "_fb_put", lambda p, v: writes.__setitem__(p, v) or True)
    monkeypatch.setattr(sc, "_fb_get", lambda p: {})       # farm meta: default timezone
    sc._tz_cache.clear()
    section = {"latest": {"timestamp": NOW_MS}, "fertilizer": {"due": True, "intervalDays": 7}}
    with tenant_scope(TENANT):
        sc._record_fertilized("H1", "S1", section)
    base = "/farm/houses/H1/sections/S1/fertilizer"
    assert writes[f"{base}/due.json"] is False
    assert writes[f"{base}/npkType.json"] == "None"
    assert f"{base}/lastFertilizedTs.json" in writes


# ── F5: a pretend run-now leaves the real schedule alone ────────────────────

def test_a_pretend_pass_does_not_move_the_real_schedule_or_run_health(monkeypatch):
    from app.api.routes import automation as a
    from app.api.routes import spatial_service
    from app.services import device_health
    a._state_by_tenant.pop("t_x", None)
    real = a._state_for("t_x")
    real_tray = datetime(2026, 10, 8, 22, 0, tzinfo=NOW.tzinfo)
    real.update(lastPlanDay="2026-10-08", lastTray=real_tray)
    health = []
    monkeypatch.setattr(a, "farm_tz", lambda: NOW.tzinfo)
    monkeypatch.setattr(a, "_fb_get", lambda p: {})
    monkeypatch.setattr(a, "run_plan_cycle", lambda now, houses: {"planned": 0})
    monkeypatch.setattr(a, "run_tray_cycle", lambda now, houses: {})
    monkeypatch.setattr(a, "run_watering_link", lambda now, houses: {})
    monkeypatch.setattr(a, "_flush_pending_pushes", lambda: None)
    monkeypatch.setattr(a, "get_auto_mode", lambda: False)
    monkeypatch.setattr(spatial_service, "interpolate_all", lambda houses, now: {})
    monkeypatch.setattr(device_health, "check_farm", lambda *x, **k: health.append(x) or [])
    a.run_one_tenant("t_x", at="2026-10-09 06:30")
    assert real["lastPlanDay"] == "2026-10-08"         # tomorrow's 05:00 plan still runs
    assert real["lastTray"] == real_tray
    assert health == []                                # a pretend clock calls every node silent


# ── F3: a sensor counts as fitted only on fresh, repeated evidence ──────────

def _rec(minute, light):
    return {"timestamp": NOW_MS + minute * 60_000, "temperature": 27.0 + 0.1 * (minute % 3),
            "humidity": 75.0 + 0.1 * (minute % 4), "light": light}


def _farm1(latest):
    return {"H1": {"meta": {"name": "H"}, "sections": {"S1": {
        "meta": {"name": "S1"}, "latest": latest, "deviceMac": "AABBCCDDEE09"}}}}


def _feed(readings, first_now=None):
    from app.services import device_health as dh
    out = []
    for i, r in enumerate(readings):
        now = first_now if (i == 0 and first_now) else r["timestamp"] + 30_000
        out += dh.check_farm("t_h", _farm1(r), now, ["H1"])
    return [x["kind"] for x in out]


@pytest.fixture
def _dh_reset():
    from app.services import device_health as dh
    dh.reset()
    yield
    dh.reset()


def test_a_weeks_old_reading_does_not_make_a_sensor_fitted(_dh_reset):
    """Node 1 on 8 Oct: H1/S8's 38-day-old latest carried a sensor value the
    rebuilt board no longer had, and its fresh -999s were pushed as a fault.
    (Found on the tray probe, since removed; the rule guards the light sensor.)"""
    old = _rec(-38 * 24 * 60, 600.0)
    fresh = [_rec(m, -999) for m in range(0, 20)]
    assert _feed([old] + fresh, first_now=NOW_MS) == []


def test_one_stray_value_is_not_a_fitted_sensor(_dh_reset):
    seq = [_rec(m, -999) for m in range(0, 3)] + [_rec(3, 550.0)] + [_rec(m, -999) for m in range(4, 25)]
    assert _feed(seq) == []


def test_a_real_sensor_that_stops_is_still_caught(_dh_reset):
    seq = [_rec(m, 600.0) for m in range(0, 5)] + [_rec(m, -999) for m in range(5, 25)]
    assert _feed(seq) == ["light"]


# ── F2/F9: the app is told which boards only record, and their real interval ─

def test_a_quiet_board_is_marked_and_shows_its_real_interval():
    """The app offered QUIET boards as masters and said 'Reads every 15s' for one."""
    from app.api.routes import devices as d
    quiet = d._decorate("AABBCCDDEE01", {"quiet": True, "lastSeen": 0})
    assert quiet["quiet"] is True and quiet["readIntervalMs"] == 60_000
    normal = d._decorate("AABBCCDDEE02", {"lastSeen": 0})
    assert normal["quiet"] is False and normal["readIntervalMs"] == 15_000


# ── F15: a section whose sensor was taken out is still planned and watered ──

def _kriged_farm():
    fresh = {"timestamp": NOW_MS - 60_000, "temperature": 30.0, "humidity": 60.0}
    plan = {"date": "2026-10-08", "waterTime": "06:30", "durationSec": 40}
    return {"H1": {"meta": {"name": "Test house"}, "sections": {
        "S1": {"meta": {"name": "S1"}, "latest": fresh, "plan": dict(plan)},
        # sensor taken out by apply-placement: no latest, a fresh estimate
        "S2": {"meta": {"name": "S2"}, "plan": dict(plan),
               "estimated": {"timestampMs": NOW_MS - 5 * 60_000, "temperature": 30.4,
                             "humidity": 59.0}},
        # its anchors stopped: the estimate is two hours old
        "S3": {"meta": {"name": "S3"}, "plan": dict(plan),
               "estimated": {"timestampMs": NOW_MS - 2 * 3600_000, "temperature": 30.0,
                             "humidity": 60.0}},
        # a sensor of its own that died: a neighbour's estimate does not rescue it
        "S4": {"meta": {"name": "S4"}, "plan": dict(plan),
               "latest": {"timestamp": NOW_MS - 3 * 3600_000, "temperature": 30.0},
               "estimated": {"timestampMs": NOW_MS - 60_000, "temperature": 30.0}}}}}


def test_kriged_sections_are_planned_but_not_given_tray_decisions(monkeypatch):
    """Only sections with their own reading were ever planned, so the zones the
    placement decision handed to kriging got no plan and no water at all."""
    from app.api.routes import smart_care_v2 as sc
    monkeypatch.setattr(sc, "_server_now_ms", lambda: NOW_MS)
    seen = []
    sc._run_per_section(_kriged_farm(), lambda h, s, sec: seen.append(s) or {})
    assert sorted(seen) == ["S1", "S2"]
    seen.clear()
    sc._run_per_section(_kriged_farm(), lambda h, s, sec: seen.append(s) or {}, estimates=False)
    assert seen == ["S1"]                      # the tray needs the section's own probe


def test_a_kriged_section_that_is_due_is_alarmed(monkeypatch):
    from app.api.routes import automation as a
    raised = []
    monkeypatch.setattr(a, "get_auto_mode", lambda: False)
    monkeypatch.setattr(a, "section_is_auto", lambda s, m=None: False)
    monkeypatch.setattr(a, "_already_done", lambda s, d, t: False)
    monkeypatch.setattr(a, "_raise_alarm", lambda kind, key, *x, **k: raised.append(key))
    out = a.run_watering_link(NOW, _kriged_farm())
    assert sorted(out["alarmed"]) == ["H1-S1-first", "H1-S2-first"]


# ── F16: no tray fill in the dark ───────────────────────────────────────────

def test_no_tray_fill_is_sent_at_night_but_the_same_air_fills_by_day(monkeypatch):
    """02:02 on 9 Oct: the model, trained on daylight hours, asked for a fill at
    night and one was sent - against the rule TRAY_DAY_START/END states."""
    from app.api.routes import smart_care_v2 as sc
    from app.services.tenant_context import tenant_scope

    class _Scaler:
        @staticmethod
        def transform(x):
            return x

    class _Model:
        @staticmethod
        def predict(x):
            return [40.0]

    monkeypatch.setattr(sc, "_tray", {"scaler": _Scaler(), "model": _Model(),
                                      "rh_target_low": 60.0, "rh_target_high": 80.0,
                                      "drop_threshold": 0.7})
    monkeypatch.setattr(sc, "_fb_put", lambda p, v: True)
    monkeypatch.setattr(sc, "_fb_get", lambda p: {})
    sent = []
    monkeypatch.setattr(sc, "_issue_node_command", lambda *x, **k: sent.append(x) or {"id": "c1"})
    tz = timezone(timedelta(minutes=330))

    def decide(when):
        latest = {"timestamp": when.timestamp() * 1000, "temperature": 27.0,
                  "humidity": 45.0, "light": 0}
        section = {"latest": latest, "control": {"override": "auto"}}
        with tenant_scope(TENANT):
            return sc._tray_decision("H1", "S1", section, now=when)

    night = decide(datetime(2026, 10, 9, 2, 2, tzinfo=tz))
    assert night["fillSeconds"] == 0 and not night["autoCommanded"] and sent == []
    assert "night" in night["message"]
    day = decide(datetime(2026, 10, 9, 10, 0, tzinfo=tz))
    assert day["fillSeconds"] > 0 and day["autoCommanded"] and len(sent) == 1


# ── F17: a house setting that was never saved answered "success" ────────────

def _fail_writes(monkeypatch):
    from app.api.routes import smart_watering
    monkeypatch.setattr(smart_watering, "FB_RETRY_DELAY_S", 0)

    def refuse(url, **kw):
        raise ConnectionError("firebase unreachable")
    monkeypatch.setattr(smart_watering._req, "put", refuse)


@pytest.mark.parametrize("url,body", [
    ("/api/v2/care/houses/H1/master", {"masterMac": "AABBCCDDEE02"}),
    ("/api/v2/care/houses/H1/pumps", {"waterChannel": 1, "trayChannel": 2}),
    ("/api/v2/care/houses/H1/dimensions", {"width": 10, "length": 20}),
    ("/api/v2/care/houses/H1", {"name": "Renamed"}),
])
def test_a_house_setting_that_was_not_saved_says_so(api, monkeypatch, url, body):
    """The master and pump routes ignored _fb_put's False. The farmer was told
    the master was set, and found out otherwise when Water Now was refused."""
    client, db = api
    before = dict(db[f"{BASE}/houses/H1/meta.json"])
    _fail_writes(monkeypatch)
    r = client.put(url, json=body, headers=TOK)
    assert r.status_code == 502, r.text
    assert "not saved" in r.json()["detail"]
    assert db[f"{BASE}/houses/H1/meta.json"] == before


def test_pump_channels_are_stored_when_the_write_lands(api):
    client, db = api
    r = client.put("/api/v2/care/houses/H1/pumps",
                   json={"waterChannel": 1, "trayChannel": 2}, headers=TOK)
    assert r.status_code == 200, r.text
    meta = db[f"{BASE}/houses/H1/meta.json"]
    assert (meta["waterChannel"], meta["trayChannel"]) == (1, 2)


# ── F8: a house activated after 05:00 had no plan until the next dawn ───────

def test_catch_up_plans_only_the_sections_without_todays_plan(monkeypatch):
    from app.api.routes import automation as a
    today = NOW.strftime("%Y-%m-%d")
    houses = {
        "H1": {"meta": {"lifecycle": "active"}, "sections": {
            "S1": {"plan": {"date": today, "waterTime": "06:40"}},     # planned at 05:00
            "S2": {"plan": {"date": "2026-10-07", "waterTime": "06:10"}},  # yesterday's
            "S3": {"meta": {"name": "no plan ever"}}}},
        "H2": {"meta": {"lifecycle": "calibrating"}, "sections": {"S1": {}}},
    }
    seen = {}

    def fake_run(hs, fn, **k):
        seen.update({f"{hid}-{sid}": True for hid, h in hs.items()
                     for sid in (h.get("sections") or {})})
        return {key: {} for key in seen}

    monkeypatch.setattr(a, "_run_per_section", fake_run)
    out = a.run_plan_catch_up(NOW, houses)
    assert sorted(seen) == ["H1-S2", "H1-S3"]           # never the calibrating house
    assert out["planned"] == 2


def test_the_engine_catches_up_every_few_minutes_after_the_dawn_plan(monkeypatch):
    from app.api.routes import automation as a
    from app.api.routes import spatial_service
    from app.services import device_health
    st = {"lastPlanDay": NOW.strftime("%Y-%m-%d"), "lastPlanCatchUp": None,
          "lastTray": NOW, "lastSpatial": NOW, "lastTick": None}
    calls = []
    monkeypatch.setattr(a, "_fb_get", lambda p: {})
    monkeypatch.setattr(a, "run_plan_cycle", lambda now, houses: calls.append(("dawn", now)))
    monkeypatch.setattr(a, "run_plan_catch_up", lambda now, houses: calls.append(("catch", now)) or {})
    monkeypatch.setattr(a, "run_tray_cycle", lambda now, houses: {})
    monkeypatch.setattr(a, "run_watering_link", lambda now, houses: {})
    monkeypatch.setattr(a, "_flush_pending_pushes", lambda: None)
    monkeypatch.setattr(spatial_service, "interpolate_all", lambda houses, now: {})
    monkeypatch.setattr(device_health, "check_farm", lambda *x, **k: [])
    monkeypatch.setattr(a, "get_auto_mode", lambda: False)
    from app.services.tenant_context import tenant_scope
    with tenant_scope(TENANT):
        for minute in (0, 1, 9, 10):
            a._engine_pass(NOW + timedelta(minutes=minute), st=st, pretend=True)
    assert [c[0] for c in calls] == ["catch", "catch"]
    assert calls[1][1] - calls[0][1] == timedelta(minutes=a.PLAN_CATCHUP_MINUTES)


def test_a_late_plan_for_a_morning_hour_is_shown_but_never_poured():
    """Planned at 14:00 for 07:10 (hours are clamped to 06:00-09:00): the
    watering window has long closed, so nothing is started."""
    from app.api.routes import automation as a
    afternoon = NOW.replace(hour=14, minute=0)
    plan = {"date": afternoon.strftime("%Y-%m-%d"), "waterTime": "07:10", "durationSec": 60}
    assert a._due_sessions(plan, afternoon) == []
    assert a._due_sessions(plan, afternoon.replace(hour=7, minute=15))[0]["tag"] == "first"


# ── F18: the plan's "yesterday" was the last 2.6 hours, or fake seed data ───

TZ = timezone(timedelta(minutes=330))
PLAN_NOW = datetime(2026, 10, 9, 5, 0, tzinfo=TZ)


def _rd(when, temp, rh):
    return {"timestamp": when.timestamp() * 1000, "temperature": temp, "humidity": rh, "light": 0}


@pytest.fixture
def farm_clock(monkeypatch):
    from app.api.routes import smart_care_v2 as sc
    monkeypatch.setattr(sc, "farm_tz", lambda: TZ)
    return sc


def test_push_key_prefix_matches_a_real_firebase_key(farm_clock):
    """-P3TMumvi8eqF-Vwd0aO is a real Node 1 history key; its reading was taken
    at 07:25 on 9 Oct 2026 (farm time). The prefix must decode to that minute
    and encode back to itself, or the time range would miss real readings."""
    sc = farm_clock
    ms = 0
    for ch in "-P3TMumv":
        ms = ms * 64 + sc._PUSH_CHARS.index(ch)
    assert datetime.fromtimestamp(ms / 1000, TZ).strftime("%Y-%m-%d %H:%M") == "2026-10-09 07:25"
    assert sc._push_key_prefix(ms) == "-P3TMumv"
    assert sc._push_key_prefix(ms - 1) < "-P3TMumv" < sc._push_key_prefix(ms + 60_000)


def test_history_is_asked_for_from_yesterday_midnight_and_never_returns_seed_keys(farm_clock, monkeypatch):
    sc = farm_clock
    asked = []
    monkeypatch.setattr(sc, "_fb_get", lambda p: asked.append(p) or {})
    sc._recent_history("H1", "S8", PLAN_NOW)
    q = asked[0]
    lo = q.split('startAt="', 1)[1].split('"', 1)[0]
    hi = q.split('endAt="', 1)[1].split('"', 1)[0]
    midnight = datetime(2026, 10, 8, 0, 0, tzinfo=TZ).timestamp() * 1000
    assert lo == sc._push_key_prefix(midnight)
    key_at = lambda when: sc._push_key_prefix(when.timestamp() * 1000) + "abcdefghijkl"
    assert lo <= key_at(datetime(2026, 10, 8, 13, 0, tzinfo=TZ)) <= hi    # yesterday's afternoon
    assert lo <= key_at(datetime(2026, 10, 9, 4, 59, tzinfo=TZ)) <= hi    # this morning
    assert not (lo <= "seed093" <= hi)                                     # the 20 Aug demo data
    assert "limitToLast" not in q


def test_yesterday_means_the_whole_previous_day_not_the_night(farm_clock):
    """Node 1 on 9 Oct: the old window saw only the night, so 'yesterday's peak'
    was 28.5 C beside a 28.2 C dawn. The day itself peaked in the afternoon."""
    sc = farm_clock
    day = datetime(2026, 10, 8, tzinfo=TZ)
    raw = {}
    for h in range(24):                                     # yesterday, every hour
        temp = 33.0 if h == 14 else 26.0
        raw[f"y{h:02d}"] = _rd(day + timedelta(hours=h), temp, 80.0)
    raw["fault"] = _rd(day + timedelta(hours=12, minutes=30), -999, -999)   # a failed read
    for m in range(0, 300, 10):                             # tonight, 00:00-05:00
        raw[f"t{m:03d}"] = _rd(PLAN_NOW - timedelta(minutes=m), 25.0, 92.0)
    y = sc._yesterday_stats(raw, {"temperature": 28.0, "humidity": 70.0}, PLAN_NOW)
    assert y["peak_temp"] == 33.0                           # the afternoon, not the night
    assert y["mean_humidity"] == 80.0                       # tonight's 92 % is not "yesterday"
    assert (y["hours"], y["source"]) == (24, "yesterday")   # and -999 did not count


def test_a_partly_recorded_yesterday_is_used_and_labelled(farm_clock):
    sc = farm_clock
    raw = {f"k{m}": _rd(datetime(2026, 10, 8, 21, tzinfo=TZ) + timedelta(minutes=m), 28.0, 85.0)
           for m in range(0, 180, 5)}                       # 21:00-24:00 only, like Node 1
    y = sc._yesterday_stats(raw, {"temperature": 28.0, "humidity": 70.0}, PLAN_NOW)
    assert (y["hours"], y["source"]) == (3, "yesterday")
    assert sc._yesterday_stats({}, {"temperature": 28.0, "humidity": 70.0}, PLAN_NOW)["source"] == "none"


def test_dawn_is_this_mornings_not_yesterdays(farm_clock):
    sc = farm_clock
    raw = {"yday": _rd(datetime(2026, 10, 8, 5, 0, tzinfo=TZ), 21.0, 95.0),
           "today": _rd(datetime(2026, 10, 9, 5, 2, tzinfo=TZ), 27.0, 85.0)}
    assert sc._dawn_reading(raw, {}, PLAN_NOW)["temperature"] == 27.0


def test_a_plan_from_a_partial_yesterday_says_so(farm_clock, monkeypatch):
    sc = farm_clock

    class _Id:
        @staticmethod
        def transform(x):
            return x

    class _Const:
        def __init__(self, v):
            self.v = v

        def predict(self, x):
            return [self.v]

    monkeypatch.setattr(sc, "_water", {"scaler": _Id(), "model_hour": _Const(7.0),
                                       "model_duration": _Const(60.0), "growth_stage_map": {}})
    raw = {f"k{m}": _rd(datetime(2026, 10, 8, 21, tzinfo=TZ) + timedelta(minutes=m), 28.0, 85.0)
           for m in range(0, 180, 5)}
    monkeypatch.setattr(sc, "_recent_history", lambda h, s, now=None: raw)
    monkeypatch.setattr(sc, "_fb_put", lambda p, v: True)
    monkeypatch.setattr(sc, "_fert_decision", lambda s: {})
    section = {"latest": _rd(PLAN_NOW, 28.0, 85.0), "meta": {"name": "S8"}}
    plan = sc._plan_section("H1", "S8", section, now=PLAN_NOW)
    assert plan["inputs"]["yesterdayHours"] == 3
    assert "recorded for 3 of 24 hours" in plan["reason"]


# ── F19: a zone with no sensor was planned from 28 C / 70 % defaults ────────

def _fake_water(sc, monkeypatch, seen):
    class _Id:
        @staticmethod
        def transform(x):
            seen.append([float(v) for v in x[0]])
            return x

    class _Const:
        def __init__(self, v):
            self.v = v

        def predict(self, x):
            return [self.v]

    monkeypatch.setattr(sc, "_water", {"scaler": _Id(), "model_hour": _Const(7.0),
                                       "model_duration": _Const(60.0), "growth_stage_map": {}})


def test_an_unmonitored_zone_is_planned_from_its_estimate_and_its_neighbours(farm_clock, monkeypatch):
    """9 Oct, live: H2 S5 (no sensor) was planned with dawn 28.0 C / 70.0 % and
    yesterday 33.0 C - _clean({}) and "latest + 5" - while kriging said 72.5 %.
    _reading_for_planning existed for this and nothing called it."""
    sc = farm_clock
    seen = []
    _fake_water(sc, monkeypatch, seen)
    sc._NEIGHBOURS.clear()
    monkeypatch.setattr(sc, "_server_now_ms", lambda: PLAN_NOW.timestamp() * 1000)
    monkeypatch.setattr(sc, "_fb_put", lambda p, v: True)
    monkeypatch.setattr(sc, "_fert_decision", lambda s: {})
    monkeypatch.setattr(sc, "_fb_get", lambda p: {"S1": True, "S2": True, "S5": True}
                        if p.endswith("sections.json?shallow=true") else {})
    day = datetime(2026, 10, 8, tzinfo=TZ)

    def hist(peak, rh):
        h = {f"h{i:02d}": _rd(day + timedelta(hours=i), peak if i == 14 else 26.0, rh) for i in range(24)}
        h["dawn"] = _rd(datetime(2026, 10, 9, 5, 0, tzinfo=TZ), 24.0, 90.0)
        return h

    histories = {"S1": hist(32.0, 80.0), "S2": hist(30.0, 70.0), "S5": {}}
    monkeypatch.setattr(sc, "_recent_history", lambda h, s, now=None: histories[s])
    estimate = {"temperature": 24.4, "humidity": 88.0, "light": 0.0, "anchorCount": 4,
                "method": "ordinary-kriging",
                "timestampMs": datetime(2026, 10, 9, 4, 55, tzinfo=TZ).timestamp() * 1000}
    plan = sc._plan_section("H2", "S5", {"estimated": estimate, "meta": {"name": "S5"}}, now=PLAN_NOW)
    dawn_t, dawn_rh, _light, _vpd, y_peak, y_rh = seen[0][:6]
    assert (dawn_t, dawn_rh) == (24.4, 88.0)            # the 04:55 estimate, not 28 / 70
    assert y_peak == 31.0 and y_rh == 75.0              # mean of S1 and S2, not 24.4 + 5
    assert plan["inputs"]["source"] == "interpolated"
    assert plan["inputs"]["yesterdaySource"] == "neighbours (2)"
    assert "estimated from the sensors around it" in plan["reason"]


def test_a_late_plan_for_an_unmonitored_zone_does_not_use_midday_air_as_dawn(farm_clock, monkeypatch):
    """The catch-up plans at any hour. At 10:15 the estimate is midday air
    (16,743 lux, live on 9 Oct) - the model was trained on dawn light 0-4."""
    sc = farm_clock
    seen = []
    _fake_water(sc, monkeypatch, seen)
    sc._NEIGHBOURS.clear()
    late = datetime(2026, 10, 9, 10, 15, tzinfo=TZ)
    monkeypatch.setattr(sc, "_server_now_ms", lambda: late.timestamp() * 1000)
    monkeypatch.setattr(sc, "_fb_put", lambda p, v: True)
    monkeypatch.setattr(sc, "_fert_decision", lambda s: {})
    monkeypatch.setattr(sc, "_fb_get", lambda p: {"S1": True, "S5": True}
                        if p.endswith("sections.json?shallow=true") else {})
    s1 = {"d": _rd(datetime(2026, 10, 9, 5, 1, tzinfo=TZ), 23.0, 91.0),
          "m": _rd(datetime(2026, 10, 9, 10, 0, tzinfo=TZ), 29.0, 70.0)}
    monkeypatch.setattr(sc, "_recent_history", lambda h, s, now=None: s1 if s == "S1" else {})
    estimate = {"temperature": 29.1, "humidity": 69.0, "light": 16743.0, "anchorCount": 4,
                "timestampMs": late.timestamp() * 1000}
    sc._plan_section("H2", "S5", {"estimated": estimate}, now=late)
    dawn_t, dawn_rh, dawn_light = seen[0][:3]
    assert (dawn_t, dawn_rh, dawn_light) == (23.0, 91.0, 0.0)   # S1's 05:01 reading


# ── F20: a fed watering the master refused still counted as a feed ──────────

def _fake_fb(monkeypatch, db):
    from app.api.routes import smart_care_v2 as sc
    monkeypatch.setattr(sc, "_fb_get", lambda p: db.get(p.split("?")[0]))
    monkeypatch.setattr(sc, "_fb_put", lambda p, v: db.__setitem__(p, v) or True)
    monkeypatch.setattr(sc, "_fb_delete", lambda p: db.pop(p, None) is not None or True)
    return sc


def test_a_feed_the_master_refused_as_stale_is_undone(farm_clock, monkeypatch):
    """9 Oct, live: Water Now with plant food into an offline master; 23 min
    later it acked 'stale', ranSec 0 - and the section still said 'Fed at
    09:58 - next feed in about 7 days'."""
    db = {}
    sc = _fake_fb(monkeypatch, db)
    monkeypatch.setattr(sc, "_server_now_ms", lambda: PLAN_NOW.timestamp() * 1000)
    base = "/farm/houses/H2/sections/S2/fertilizer"
    section = {"latest": _rd(PLAN_NOW, 28.0, 70.0),
               "fertilizer": {"due": True, "npkType": "30-10-10", "intervalDays": 7,
                              "message": "Feed 30-10-10 at 50%"}}
    cmd = {"id": "c0ffee000001", "routedTo": "5E5E5E5E00FF"}
    sc._record_fertilized("H2", "S2", section, cmd)
    assert db[f"{base}/due.json"] is False                      # recorded at issue, as designed
    db["/farm/pendingFeeds.json"] = {"c0ffee000001": db.pop("/farm/pendingFeeds/c0ffee000001.json")}
    db["/farm/masters/5E5E5E5E00FF/acks/c0ffee000001.json"] = {
        "id": "c0ffee000001", "outcome": "stale", "ranSec": 0}
    deleted = []
    monkeypatch.setattr(sc, "_fb_delete", lambda p: deleted.append(p) or True)
    undone = sc.settle_pending_feeds()
    assert [u["outcome"] for u in undone] == ["stale"]
    assert db[f"{base}/due.json"] is True and db[f"{base}/npkType.json"] == "30-10-10"
    assert "did not happen" in db[f"{base}/message.json"]
    assert f"{base}/lastFertilizedAt.json" in deleted              # no feed before this one
    assert "/farm/pendingFeeds/c0ffee000001.json" in deleted


def test_a_feed_that_ran_stands_and_a_lost_ack_is_never_undone(farm_clock, monkeypatch):
    db = {}
    sc = _fake_fb(monkeypatch, db)
    now = {"ms": PLAN_NOW.timestamp() * 1000}
    monkeypatch.setattr(sc, "_server_now_ms", lambda: now["ms"])
    base = "/farm/houses/H2/sections/S2/fertilizer"
    p = {"houseId": "H2", "sectionId": "S2", "master": "M1", "issuedAtMs": now["ms"],
         "fedAt": "2026-10-09 05:00", "prev": {"due": True, "npkType": "30-10-10"}}
    db["/farm/pendingFeeds.json"] = {"ran": dict(p), "lost": dict(p)}
    db["/farm/masters/M1/acks/ran.json"] = {"id": "ran", "outcome": "done", "ranSec": 88}
    db[f"{base}/lastFertilizedAt.json"] = "2026-10-09 05:00"
    db[f"{base}/due.json"] = False
    assert sc.settle_pending_feeds() == []
    assert db[f"{base}/due.json"] is False                       # it poured: the feed stands
    now["ms"] += 25 * 3600_000                                   # a day on, still no ack
    db["/farm/pendingFeeds.json"] = {"lost": dict(p)}
    assert sc.settle_pending_feeds() == []
    assert db[f"{base}/due.json"] is False                       # never feed twice on a lost ack


def test_a_refused_command_is_not_a_confirmed_watering_in_the_history(farm_clock, monkeypatch):
    db = {"/farm/events/H2/S2.json": {"1": {"commandId": "c1", "confirmed": False}}}
    sc = _fake_fb(monkeypatch, db)
    sc._stamp_event_outcome("H2", "S2", "c1", {"outcome": "stale", "ranSec": 0})
    assert db["/farm/events/H2/S2/1/confirmed.json"] is False
    assert db["/farm/events/H2/S2/1/outcome.json"] == "stale"
