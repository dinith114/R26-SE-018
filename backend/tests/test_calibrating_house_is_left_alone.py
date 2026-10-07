"""A house that is calibrating gets no watering, no tray fills and no alarms.

Its nodes are bare DHT22 boards spread out to record where the house differs,
wired to no pump and no tray. Before this, the engine treated it like any other
house: with Auto off, every tray decision became a pushed "Fill the humidity
tray now" alarm repeating every five minutes, per section, for the whole
three-day window. Found by walking the calibration procedure through
automation.py on 7 Oct 2026, before the first real calibration house.

The houses below are TEST DATA: two houses that differ only in lifecycle, so
anything that reaches one and not the other is the lifecycle doing it.
"""
from datetime import datetime, timezone

from app.api.routes import automation

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
LATEST = {"timestamp": 1_791_000_000_000, "temperature": 31.0, "humidity": 55.0, "light": -999}


def _farm():
    sec = lambda: {"meta": {"name": "S"}, "latest": dict(LATEST),
                   "plan": {"date": "2026-10-08", "waterTime": "12:00", "durationSec": 40}}
    return {
        "H1": {"meta": {"name": "Working house"}, "sections": {"S1": sec()}},
        "HC": {"meta": {"name": "Calibrating", "lifecycle": "calibrating"},
               "sections": {"S1": sec(), "S2": sec()}},
    }


def test_only_working_houses_reach_the_tray_and_plan_cycles(monkeypatch):
    seen = []

    def _fake_per_section(houses, fn):
        seen.append(sorted(houses))
        return {}

    monkeypatch.setattr(automation, "_run_per_section", _fake_per_section)
    monkeypatch.setattr(automation, "get_auto_mode", lambda: False)
    automation.run_tray_cycle(NOW, _farm())
    automation.run_plan_cycle(NOW, _farm())
    assert seen == [["H1"], ["H1"]]


def test_a_calibrating_house_raises_no_watering_alarm(monkeypatch):
    raised = []
    monkeypatch.setattr(automation, "get_auto_mode", lambda: False)
    monkeypatch.setattr(automation, "section_is_auto", lambda s, m=None: False)
    monkeypatch.setattr(automation, "_already_done", lambda s, d, t: False)
    monkeypatch.setattr(automation, "_due_sessions",
                        lambda plan, now, s=None: [{"tag": "am", "time": "12:00", "durationSec": 40}])
    monkeypatch.setattr(automation, "_raise_alarm",
                        lambda kind, key, *a, **k: raised.append(key))
    out = automation.run_watering_link(NOW, _farm())
    assert out["alarmed"] == ["H1-S1-am"]
    assert all(not k.startswith("HC-") for k in raised)


def test_activating_the_house_brings_it_back():
    farm = _farm()
    farm["HC"]["meta"]["lifecycle"] = "active"
    assert sorted(automation._acting_houses(farm)) == ["H1", "HC"]
    farm["HC"]["meta"].pop("lifecycle")                 # old houses: absent = active
    assert sorted(automation._acting_houses(farm)) == ["H1", "HC"]


# ── the review found the manual Check now path and /alerts still let it in ──

def test_check_now_skips_a_calibrating_house_too():
    """/plan-all and /tray-check-all go through _run_per_section, like the engine."""
    from app.api.routes import smart_care_v2 as sc
    seen = []
    sc._run_per_section(_farm(), lambda hid, sid, s: seen.append(hid) or {})
    assert seen == ["H1"]


def test_alerts_keep_a_silent_node_but_no_care_items(monkeypatch):
    import asyncio
    from app.api.routes import smart_care_v2 as sc
    farm = _farm()
    for h in farm.values():
        for s in h["sections"].values():
            s["tray"] = {"status": "fill", "fillSeconds": 12}
    monkeypatch.setattr(sc, "_fb_get", lambda path: farm if path == "/farm/houses.json" else None)
    monkeypatch.setattr(sc, "_devices_for_caller", lambda: {})
    monkeypatch.setattr(sc, "second_session_due", lambda s, now: None)
    # HC/S2 has gone quiet; everything else is fresh.
    monkeypatch.setattr(sc, "_freshness", lambda s, now, iv=None: {
        "trusted": s is not farm["HC"]["sections"]["S2"], "message": "silent 3 h"})
    out = asyncio.run(sc.alerts(ctx=None))
    ids = {i["id"] for i in out["alerts"]}
    assert "H1-S1-tray" in ids                      # the working house is still cared for
    assert "HC-S2-stale" in ids                     # a silent calibration node is still said
    assert not any(i.startswith("HC-") and not i.endswith("-stale") for i in ids)
