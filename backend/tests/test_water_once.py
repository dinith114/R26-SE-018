"""One run of the shared pump for several sections (18 Oct 2026).

The farm has one watering pump for the whole house and no valve per section, so
watering four sections one at a time ran that pump four times back to back.
These pin down the whole-house run: one command, one event per covered section,
one answer from the master confirming all of them, and a refusal when the
sections have valves of their own. Firebase is a dict here; nothing leaves the
process.
"""
import copy

import pytest
from fastapi import HTTPException

MASTER = "AABBCCDDEEFF"


class FakeFirebase:
    def __init__(self, house_meta=None, section_meta=None):
        sections = {sid: {"meta": dict((section_meta or {}).get(sid, {}), name=f"Bed {sid}")}
                    for sid in ("S1", "S2", "S3")}
        meta = {"masterMac": MASTER, "waterChannel": 1, "trayChannel": 2}
        if house_meta is not None:
            meta = house_meta
        self.tree = {"farm": {"houses": {"H1": {"meta": meta, "sections": sections}}}}

    def _walk(self, path, create=False):
        parts = [x for x in path.split("?")[0].removesuffix(".json").split("/") if x]
        node = self.tree
        for k in parts[:-1]:
            if not isinstance(node, dict):
                return None, None
            if k not in node:
                if not create:
                    return None, None
                node[k] = {}
            node = node[k]
        return node, parts[-1]

    def get(self, path):
        # A COPY, as the real REST read is: settle_pending_acks deletes entries
        # while it walks what it read, which a live reference would not survive.
        parent, key = self._walk(path)
        if not isinstance(parent, dict) or key not in parent:
            return None
        return copy.deepcopy(parent[key])

    def put(self, path, value):
        parent, key = self._walk(path, create=True)
        parent[key] = value
        return True

    def delete(self, path):
        parent, key = self._walk(path)
        if isinstance(parent, dict):
            parent.pop(key, None)
        return True


def install(monkeypatch, f):
    from app.api.routes import smart_care_v2 as sc
    monkeypatch.setattr(sc, "_fb_get", f.get)
    monkeypatch.setattr(sc, "_fb_put", f.put)
    monkeypatch.setattr(sc, "_fb_delete", f.delete)
    return sc


def queue(f):
    return ((f.tree["farm"].get("masters") or {}).get(MASTER) or {}).get("queue") or {}


def events(f, sid):
    return list(((f.tree["farm"].get("events") or {}).get("H1") or {}).get(sid, {}).values())


def test_one_command_for_the_longest_run_and_an_event_in_every_section(monkeypatch):
    f = FakeFirebase()
    sc = install(monkeypatch, f)
    out = sc.water_house_once("H1", sc.HouseWaterCmd(sectionIds=["S1", "S2", "S3"], durationSec=90), ctx=None)

    q = list(queue(f).values())
    assert len(q) == 1, "the pump runs once, not once per section"
    assert q[0]["durationSec"] == 90 and q[0]["channel"] == 1 and q[0]["targetSection"] == "S1"
    assert "covers" not in q[0], "the firmware's command stays exactly as before"
    assert out["covers"] == ["S1", "S2", "S3"]

    cid = q[0]["id"]
    for sid in ("S1", "S2", "S3"):
        evs = events(f, sid)
        assert len(evs) == 1
        ev = evs[0]
        assert ev["commandId"] == cid and ev["durationSec"] == 90
        assert ev["withFertilizer"] is False and ev["covers"] == ["S1", "S2", "S3"]
        assert ev["confirmed"] is False


def test_one_answer_from_the_master_confirms_every_covered_section(monkeypatch):
    f = FakeFirebase()
    sc = install(monkeypatch, f)
    sc.water_house_once("H1", sc.HouseWaterCmd(sectionIds=["S1", "S2", "S3"], durationSec=60), ctx=None)
    cid = list(queue(f))[0]
    # The master pours and answers for the command it was given.
    f.put(f"/farm/masters/{MASTER}/acks/{cid}.json",
          {"id": cid, "targetSection": "S1", "ranSec": 60, "outcome": "done"})

    assert sc.settle_pending_acks() == 1
    for sid in ("S1", "S2", "S3"):
        ev = events(f, sid)[0]
        assert ev["confirmed"] is True and ev["outcome"] == "done" and ev["ranSec"] == 60


def test_a_run_stopped_early_is_recorded_as_stopped_everywhere(monkeypatch):
    f = FakeFirebase()
    sc = install(monkeypatch, f)
    sc.water_house_once("H1", sc.HouseWaterCmd(sectionIds=["S2", "S3"], durationSec=60), ctx=None)
    cid = list(queue(f))[0]
    sc._stamp_event_outcome("H1", "S2", cid, {"ranSec": 12, "outcome": "stopped"})
    for sid in ("S2", "S3"):
        ev = events(f, sid)[0]
        assert ev["outcome"] == "stopped" and ev["stoppedEarly"] is True and ev["ranSec"] == 12
    assert events(f, "S1") == [], "a section that was not chosen is not touched"


def test_refused_when_the_sections_have_their_own_valves(monkeypatch):
    f = FakeFirebase(section_meta={"S1": {"relayChannel": 3}, "S2": {"relayChannel": 4}})
    sc = install(monkeypatch, f)
    with pytest.raises(HTTPException) as e:
        sc.water_house_once("H1", sc.HouseWaterCmd(sectionIds=["S1", "S2"], durationSec=60), ctx=None)
    assert e.value.status_code == 409 and "own valves" in e.value.detail
    assert queue(f) == {} and events(f, "S1") == [] and events(f, "S2") == []


def test_refused_with_no_master_and_nothing_logged(monkeypatch):
    f = FakeFirebase(house_meta={"waterChannel": 1})
    sc = install(monkeypatch, f)
    with pytest.raises(HTTPException) as e:
        sc.water_house_once("H1", sc.HouseWaterCmd(sectionIds=["S1", "S2"], durationSec=60), ctx=None)
    assert e.value.status_code == 409 and "master" in e.value.detail
    assert events(f, "S1") == [] and events(f, "S2") == []


def test_unknown_section_and_empty_choice_are_refused(monkeypatch):
    f = FakeFirebase()
    sc = install(monkeypatch, f)
    with pytest.raises(HTTPException) as e:
        sc.water_house_once("H1", sc.HouseWaterCmd(sectionIds=["S1", "S9"], durationSec=60), ctx=None)
    assert e.value.status_code == 404
    with pytest.raises(HTTPException) as e:
        sc.water_house_once("H1", sc.HouseWaterCmd(sectionIds=[], durationSec=60), ctx=None)
    assert e.value.status_code == 400
    assert queue(f) == {}


def test_duration_is_held_to_the_relay_limit(monkeypatch):
    f = FakeFirebase()
    sc = install(monkeypatch, f)
    sc.water_house_once("H1", sc.HouseWaterCmd(sectionIds=["S1", "S2"], durationSec=9999), ctx=None)
    assert list(queue(f).values())[0]["durationSec"] == sc.RELAY_MAX_SEC
