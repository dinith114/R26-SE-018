"""Pour lengths are the grower's (19 Oct 2026).

The watering length model was removed: its seconds were learned from a rule
with no pump in the loop and could not know how many litres a second each
section's pipe delivers. Now every pour is the section's own Pour length, or
the farm default from Settings (10 minutes unless changed). These pin that
down, the Settings endpoint, and the health check that must not call a pour
queued behind a long one "never carried out". Firebase is a dict here.
"""
import asyncio

import pytest
from fastapi import HTTPException

from app.services import device_health as dh
from tests.test_water_once import MASTER, FakeFirebase, install


def run(coro):
    return asyncio.run(coro)


def test_a_sections_own_length_wins_over_the_farm_default(monkeypatch):
    f = FakeFirebase()
    f.put("/farm/meta.json", {"pourDefaults": {"waterSec": 300, "traySec": 40}})
    sc = install(monkeypatch, f)
    assert sc._water_length({}) == (300, "farm")
    assert sc._water_length({"control": {"durations": {"water": 75}}}) == (75, "section")
    assert sc._tray_amount({}) == (40, "farm default")
    assert sc._tray_amount({"control": {"durations": {"tray": 12}}}) == (12, "you")


def test_with_nothing_set_both_default_to_ten_minutes(monkeypatch):
    f = FakeFirebase()
    sc = install(monkeypatch, f)
    assert sc._pour_defaults() == {"waterSec": 600, "traySec": 600}


def test_settings_change_every_section_without_its_own_length(monkeypatch):
    f = FakeFirebase()
    f.put("/farm/houses/H1/sections/S1/plan.json", {"durationSec": 600, "durationSetBy": "farm"})
    f.put("/farm/houses/H1/sections/S2/plan.json", {"durationSec": 90, "durationSetBy": "section"})
    f.put("/farm/houses/H1/sections/S2/control/durations.json", {"water": 90})
    sc = install(monkeypatch, f)
    out = run(sc.set_pour_defaults(sc.PourDefaultsIn(waterSec=240, traySec=20), ctx=None))
    assert out["pourDefaults"] == {"waterSec": 240, "traySec": 20}
    assert f.get("/farm/meta.json")["pourDefaults"] == {"waterSec": 240, "traySec": 20}
    assert f.get("/farm/houses/H1/sections/S1/plan.json")["durationSec"] == 240
    s2 = f.get("/farm/houses/H1/sections/S2/plan.json")
    assert s2["durationSec"] == 90 and s2["durationSetBy"] == "section"


@pytest.mark.parametrize("bad", [0, -5, 3601])
def test_lengths_outside_one_second_to_an_hour_are_refused(monkeypatch, bad):
    f = FakeFirebase()
    sc = install(monkeypatch, f)
    with pytest.raises(HTTPException) as e:
        run(sc.set_pour_defaults(sc.PourDefaultsIn(waterSec=bad, traySec=60), ctx=None))
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        run(sc.set_section_durations("H1", "S1", sc.DurationsIn(waterDurationSec=bad), ctx=None))
    assert e.value.status_code == 400


def test_a_section_length_is_saved_and_shown_at_once(monkeypatch):
    f = FakeFirebase()
    f.put("/farm/houses/H1/sections/S1/plan.json", {"durationSec": 600, "durationSetBy": "farm"})
    sc = install(monkeypatch, f)
    out = run(sc.set_section_durations("H1", "S1", sc.DurationsIn(waterDurationSec=900, trayFillSec=45), ctx=None))
    assert out["durations"] == {"water": 900, "tray": 45}
    plan = f.get("/farm/houses/H1/sections/S1/plan.json")
    assert plan["durationSec"] == 900 and plan["durationSetBy"] == "section"
    # cleared: back to the farm default
    run(sc.set_section_durations("H1", "S1", sc.DurationsIn(), ctx=None))
    assert f.get("/farm/houses/H1/sections/S1/plan.json")["durationSetBy"] == "farm"


def test_the_overview_tells_the_app_the_master_limit(monkeypatch):
    f = FakeFirebase()
    f.put(f"/devices/{MASTER}.json", {"fw": "validation-2.6"})
    sc = install(monkeypatch, f)
    assert sc._pour_cap("H1")[0] == 120
    f.put(f"/devices/{MASTER}.json", {"fw": "validation-2.9"})
    assert sc._pour_cap("H1") == (3600, None)


def test_a_pour_queued_behind_a_long_one_is_not_called_broken():
    issued = 1_000_000.0
    queue = {"a": {"issuedAtSec": issued, "durationSec": 600, "targetSection": "S1", "action": "water"},
             "b": {"issuedAtSec": issued, "durationSec": 600, "targetSection": "S2", "action": "water"}}
    # Past the old rule (issue + 900 + 120 + 90) but the second pour cannot even
    # start until the first has run its 10 minutes.
    at = issued + 900 + 120 + 90 + 60
    assert "S2" not in dh.overdue_commands(queue, at * 1000)
    # Once the first has run, plus the master's idle window, plus its own length
    # and grace, an entry still sitting there was never carried out.
    late = issued + 600 + 900 + 600 + 90 + 1
    out = dh.overdue_commands(queue, late * 1000)
    assert set(out) == {"S1", "S2"}
