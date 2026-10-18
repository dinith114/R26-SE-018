"""The offline fallback: what a master is given, and what its reports become.

A master waters from its own copy of today's plan when the cloud is gone
(app/services/fallback.py, firmware queue_fallback.ino). These tests pin the
backend's half. The farm below is TEST DATA.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.api.routes import automation
from app.services import fallback

SL = timezone(timedelta(hours=5, minutes=30))          # the farm's clock
TODAY = "2026-10-11"
NOW = datetime(2026, 10, 11, 5, 1, tzinfo=SL)
MAC = "AABBCCDDEEFF"


def _sec(date, hhmm, secs, auto=True, **meta):
    return {"meta": {"name": "Sec", **meta}, "auto": auto,
            "plan": {"date": date, "waterTime": hhmm, "durationSec": secs}}


def _farm():
    return {
        "H1": {"meta": {"name": "House 1", "masterMac": MAC, "waterChannel": 1},
               "sections": {
                   "S1": _sec(TODAY, "07:10", 60),
                   "S2": _sec(TODAY, "06:40", 50, auto=False),       # run by hand
                   "S3": _sec("2026-10-10", "07:00", 55),             # yesterday's plan
                   "S4": _sec(TODAY, "06:30", 150),                   # longer than the relay cap
               }},
        "H2": {"meta": {"name": "No master"},
               "sections": {"S1": _sec(TODAY, "07:00", 40)}},
    }


def _is_auto(s):
    return bool(s.get("auto"))


def _epoch(hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    return int(datetime(2026, 10, 11, h, m, tzinfo=SL).timestamp())


# ── what a master is given ──────────────────────────────────────────────────

def test_a_master_gets_only_its_automatic_sections_planned_for_today():
    plans = fallback.build_plans(_farm(), TODAY, SL, _is_auto, lambda h, s: 1, 1000)
    assert list(plans) == [MAC]                                    # H2 has no master
    doc = plans[MAC]
    assert doc["day"] == TODAY
    assert doc["dayStartSec"] == int(datetime(2026, 10, 11, tzinfo=SL).timestamp())
    assert sorted(doc["entries"]) == ["H1-S1", "H1-S4"]            # not S2 (manual), not S3 (old plan)
    e = doc["entries"]["H1-S1"]
    assert e == {"house": "H1", "section": "S1", "dueSec": _epoch("07:10"),
                 "durationSec": 60, "channel": 1}


def test_a_pour_is_capped_at_the_relay_limit():
    doc = fallback.build_plans(_farm(), TODAY, SL, _is_auto, lambda h, s: 1, 1000)[MAC]
    assert doc["entries"]["H1-S4"]["durationSec"] == fallback.MAX_POUR_SEC == 120


def test_a_section_with_no_watering_channel_is_left_out():
    doc = fallback.build_plans(_farm(), TODAY, SL, _is_auto,
                               lambda h, s: None if s == "S1" else 1, 1000)[MAC]
    assert sorted(doc["entries"]) == ["H1-S4"]


def test_today_with_nothing_automatic_is_an_empty_plan_not_no_plan():
    """Otherwise the master would fall back to yesterday's plan and water a
    house the grower has put on manual."""
    farm = _farm()
    for s in farm["H1"]["sections"].values():
        s["auto"] = False
    doc = fallback.build_plans(farm, TODAY, SL, _is_auto, lambda h, s: 1, 1000)[MAC]
    assert doc["day"] == TODAY and doc["entries"] == {}


def test_before_todays_plan_exists_the_master_keeps_yesterdays():
    farm = _farm()
    for s in farm["H1"]["sections"].values():
        s["plan"]["date"] = "2026-10-10"
    assert fallback.build_plans(farm, TODAY, SL, _is_auto, lambda h, s: 1, 1000) == {}


def test_the_master_never_waters_while_the_engine_still_might():
    """The engine starts a missed watering up to WATER_WINDOW_MIN late. If the
    master did not wait longer than that, both could pour the same morning."""
    assert fallback.FALLBACK_AFTER_MIN > automation.WATER_WINDOW_MIN
    doc = fallback.build_plans(_farm(), TODAY, SL, _is_auto, lambda h, s: 1, 1000)[MAC]
    assert doc["afterMin"] == fallback.FALLBACK_AFTER_MIN
    assert doc["untilMin"] == fallback.FALLBACK_UNTIL_MIN > doc["afterMin"]


def test_the_signature_follows_what_the_plan_depends_on():
    base = fallback.signature(_farm(), TODAY, _is_auto)
    farm = _farm()
    farm["H1"]["sections"]["S1"]["latest"] = {"temperature": 31}    # a new reading: no change
    assert fallback.signature(farm, TODAY, _is_auto) == base
    farm["H1"]["sections"]["S1"]["plan"]["waterTime"] = "07:20"     # a new plan: change
    assert fallback.signature(farm, TODAY, _is_auto) != base
    farm = _farm()
    farm["H1"]["sections"]["S2"]["auto"] = True                     # a mode change: change
    assert fallback.signature(farm, TODAY, _is_auto) != base
    farm = _farm()
    farm["H1"]["meta"]["waterChannel"] = 3                          # a channel change: change
    assert fallback.signature(farm, TODAY, _is_auto) != base


# ── reports from a master ───────────────────────────────────────────────────

def test_a_report_is_read_or_refused():
    good = {"house": "H1", "targetSection": "S1", "ranSec": 60, "at": _epoch("07:36"),
            "outcome": "done", "fromYesterday": False, "channel": 1}
    assert fallback.read_report(good)["section"] == "S1"
    for bad in ({**good, "house": ""}, {**good, "at": "soon"}, {**good, "ranSec": -1}, "x", None):
        assert fallback.read_report(bad) is None


# ── the engine's side ───────────────────────────────────────────────────────

@pytest.fixture
def fb(monkeypatch):
    """A fake database for the engine functions, recording every write."""
    db = {"puts": {}, "deletes": [], "gets": {}, "marked": [], "events": [], "alarms": []}
    monkeypatch.setattr(automation, "_fb_put", lambda p, v: db["puts"].__setitem__(p, v) or True)
    monkeypatch.setattr(automation, "_fb_get", lambda p: db["gets"].get(p))
    monkeypatch.setattr(automation, "_fb_delete", lambda p: db["deletes"].append(p) or True)
    monkeypatch.setattr(automation, "get_auto_mode", lambda: True)
    monkeypatch.setattr(automation, "section_is_auto", lambda s, m=None: bool(s.get("auto")))
    monkeypatch.setattr(automation, "farm_tz", lambda: SL)
    monkeypatch.setattr(automation, "_relay_channel", lambda h, s, a="water": 1)
    monkeypatch.setattr(automation, "_mark_done", lambda *a: db["marked"].append(a))
    monkeypatch.setattr(automation, "_log_event", lambda h, s, sec, **f: db["events"].append((h, s, f)))
    monkeypatch.setattr(automation, "_raise_alarm", lambda kind, key, *a, **k: db["alarms"].append(key))
    return db


def test_the_engine_writes_a_plan_only_when_it_changes(fb):
    st = {}
    out = automation.export_fallback_plans(NOW, _farm(), st)
    assert out["written"] == 1 and f"/farm/masters/{MAC}/fallbackPlan.json" in fb["puts"]
    fb["puts"].clear()
    assert automation.export_fallback_plans(NOW, _farm(), st)["written"] == 0
    assert fb["puts"] == {}


def test_a_calibrating_house_gives_its_master_nothing(fb):
    farm = _farm()
    farm["H1"]["meta"]["lifecycle"] = "calibrating"
    assert automation.export_fallback_plans(NOW, farm, {})["written"] == 0
    assert fb["puts"] == {}


def test_an_offline_watering_is_recorded_then_its_report_deleted(fb):
    at = _epoch("07:36")
    fb["gets"][f"/farm/masters/{MAC}/fallbackDone.json"] = {
        "fb1-S1": {"house": "H1", "targetSection": "S1", "ranSec": 60, "at": at,
                   "outcome": "done", "fromYesterday": False, "channel": 1}}
    out = automation.record_fallback_reports(NOW, _farm())
    assert out["recorded"] == ["H1-S1"]
    assert fb["marked"] == [("H1", "S1", TODAY, "first", "fallback")]   # the morning counts as watered
    assert fb["events"][0][2]["by"] == "fallback" and fb["events"][0][2]["durationSec"] == 60
    assert fb["alarms"] == ["H1-S1-fallback-fb1-S1"]                     # the grower is told
    assert fb["deletes"] == [f"/farm/masters/{MAC}/fallbackDone/fb1-S1.json"]


def test_an_unusable_report_is_deleted_and_marks_nothing(fb):
    fb["gets"][f"/farm/masters/{MAC}/fallbackDone.json"] = {
        "junk": {"targetSection": "S1"},                                # no house, no time
        "other": {"house": "H9", "targetSection": "S1", "ranSec": 5, "at": _epoch("07:00")}}
    out = automation.record_fallback_reports(NOW, _farm())
    assert out["recorded"] == [] and fb["marked"] == [] and fb["alarms"] == []
    assert sorted(fb["deletes"]) == sorted(f"/farm/masters/{MAC}/fallbackDone/{k}.json"
                                           for k in ("junk", "other"))


def test_the_engine_beat_is_the_current_epoch(fb):
    before = int(datetime.now(timezone.utc).timestamp())
    automation._beat()
    assert before <= fb["puts"]["/farm/engineBeat.json"] <= before + 5
