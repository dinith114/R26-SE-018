"""The live status of every pour, for every screen (18 Oct 2026).

A run was visible only on the screen that started it: leave it and the status
was gone, come back and nothing showed, and a pour the engine started by itself
showed nowhere until it was history. These pin down GET /activity: a pour is
seen waiting, running with a countdown from the controller's own clock, and
finished, whoever started it, for a few minutes after. Firebase is a dict here.
"""
import pytest

from tests.test_water_once import MASTER, FakeFirebase, install

T0 = 1_792_330_000_000            # ms


@pytest.fixture
def farm(monkeypatch):
    f = FakeFirebase()
    sc = install(monkeypatch, f)
    clock = {"ms": T0}
    monkeypatch.setattr(sc, "_server_now_ms", lambda: clock["ms"])
    sc._ACTIVITY_NAMES.clear()
    return f, sc, clock


def pour(sc, sid="S1", action="water", secs=60, by="user"):
    """A pour issued and logged the way every caller does it."""
    cmd = sc._issue_node_command("H1", sid, action, secs)
    sc._log_event("H1", sid, {}, action=action, durationSec=secs, by=by,
                  commandId=cmd["id"], confirmed=False)
    return cmd["id"]


def status(sc):
    return sc.farm_activity(ctx=None)


def masters(f):
    return f.tree["farm"]["masters"][MASTER]


def test_a_queued_pour_is_waiting_with_its_names(farm):
    f, sc, clock = farm
    cid = pour(sc, "S2")
    out = status(sc)
    assert out["active"] is True
    [it] = out["items"]
    assert it["id"] == cid and it["state"] == "waiting" and it["action"] == "water"
    assert it["houseId"] == "H1" and it["sectionIds"] == ["S2"] and it["sectionNames"] == ["Bed S2"]
    assert it["by"] == "user"


def test_a_running_pour_counts_down_from_the_controllers_clock(farm):
    f, sc, clock = farm
    cid = pour(sc, secs=90)
    masters(f)["running"] = {"id": cid, "targetSection": "S1", "durationSec": 90,
                             "startedAt": T0 / 1000 + 5}
    clock["ms"] = T0 + 35_000                       # 30 s after the valve opened
    [it] = status(sc)["items"]
    assert it["state"] == "running" and it["remainingSec"] == 60


def test_a_finished_pour_shows_for_three_minutes_then_goes(farm):
    f, sc, clock = farm
    cid = pour(sc, secs=60)
    q = masters(f)["queue"]
    q.pop(cid)
    masters(f)["acks"] = {cid: {"id": cid, "targetSection": "S1", "ranSec": 60,
                                "outcome": "done", "at": T0 / 1000 + 70}}
    clock["ms"] = T0 + 100_000
    [it] = status(sc)["items"]
    assert it["state"] == "done" and it["ranSec"] == 60
    assert status(sc)["active"] is False
    clock["ms"] = T0 + 70_000 + 181_000
    assert status(sc)["items"] == []


def test_a_stopped_and_a_refused_pour_say_so(farm):
    f, sc, clock = farm
    a, b = pour(sc, "S1"), pour(sc, "S2")
    for c in (a, b):
        masters(f)["queue"].pop(c)
    masters(f)["acks"] = {a: {"id": a, "ranSec": 12, "outcome": "stopped", "at": T0 / 1000 + 20},
                          b: {"id": b, "ranSec": 0, "outcome": "stale", "at": T0 / 1000 + 20}}
    clock["ms"] = T0 + 30_000
    got = {i["id"]: i["state"] for i in status(sc)["items"]}
    assert got == {a: "stopped", b: "refused"}


def test_an_automatic_pour_and_a_tray_fill_show_like_any_other(farm):
    f, sc, clock = farm
    w = pour(sc, "S1", by="auto")
    t = pour(sc, "S3", action="tray", secs=15, by="auto")
    got = {i["id"]: (i["by"], i["action"]) for i in status(sc)["items"]}
    assert got == {w: ("auto", "water"), t: ("auto", "tray")}


def test_a_whole_house_run_is_one_item_covering_every_section(farm):
    f, sc, clock = farm
    sc.water_house_once("H1", sc.HouseWaterCmd(sectionIds=["S1", "S2", "S3"], durationSec=90), ctx=None)
    [it] = status(sc)["items"]
    assert it["sectionIds"] == ["S1", "S2", "S3"] and it["lead"] == "S1"
    assert it["sectionNames"] == ["Bed S1", "Bed S2", "Bed S3"]


def test_a_pour_nobody_answered_is_called_unconfirmed(farm):
    f, sc, clock = farm
    cid = pour(sc, secs=60)
    masters(f)["queue"].pop(cid)                       # gone, and no ack ever came
    clock["ms"] = T0 + (60 + 91) * 1000
    [it] = status(sc)["items"]
    assert it["state"] == "unconfirmed"


def test_the_ack_wins_over_a_queue_entry_not_yet_deleted(farm):
    """The controller writes the ack, THEN deletes the queue entry. In between,
    the pour must not read as waiting again after it has run."""
    f, sc, clock = farm
    cid = pour(sc, secs=30)
    masters(f)["acks"] = {cid: {"id": cid, "ranSec": 30, "outcome": "done", "at": T0 / 1000 + 35}}
    clock["ms"] = T0 + 40_000
    [it] = status(sc)["items"]
    assert it["state"] == "done"


def test_old_records_are_pruned_on_the_next_pour(farm):
    f, sc, clock = farm
    old = pour(sc, "S1")
    clock["ms"] = T0 + 31 * 60_000
    new = pour(sc, "S2")
    assert set(f.tree["farm"]["activity"]) == {new}


def test_a_house_without_a_controller_records_nothing(monkeypatch):
    f = FakeFirebase(house_meta={"name": "No master"})
    sc = install(monkeypatch, f)
    sc._note_activity("H1", "S1", "abc123", {"action": "water", "durationSec": 30})
    assert "activity" not in f.tree["farm"]
    assert sc.farm_activity(ctx=None)["items"] == []
