"""The calibration routes through the real app: co-location, the analysis, and
the placement table the app already reads.

Same fake-Firebase seam as test_farm_isolation: `_req` is replaced, so every
read and write lands in a dict keyed by the tenant-scoped path. The readings are
TEST DATA with a known gradient and known sensor biases - they exist so the
assertions have a right answer, and nothing here touches the real farm.
"""
import pytest
from fastapi.testclient import TestClient

from app.services.firebase_auth import ROLE_ADMIN, ROLE_VIEWER, set_decoder
from tests.placement_fixtures import STEP, T0, _house

TENANT = "t_a"
COORDS = {"S1": (1, 1), "S2": (9, 1), "S3": (1, 13), "S4": (9, 13), "S5": (5, 7), "S6": (3, 10)}
BASE = f"/tenants/{TENANT}/farm"


@pytest.fixture
def farm(monkeypatch):
    hist = _house(COORDS, 2 * 1440, grad_c_per_m=0.12,
                  biases={"S2": (0.4, -2.0)}, colocate_minutes=60)
    sections = {sid: {"meta": {"name": sid, "x": x, "y": y}} for sid, (x, y) in COORDS.items()}
    db = {
        f"{BASE}/houses/H1/meta.json": {"name": "Test house", "lifecycle": "calibrating",
                                        "calibration": {"startedAt": T0 - 1}},
        f"{BASE}/houses/H1/sections.json": sections,
    }
    for sid in COORDS:
        db[f"{BASE}/history/H1/{sid}.json"] = hist[sid]

    class _Resp:
        def __init__(self, body):
            self.body = body
            self.status_code = 200 if body is not None else 404

        def json(self):
            return self.body

    class _Req:
        @staticmethod
        def _path(url):
            return url.split("firebaseio.com", 1)[-1].split("?", 1)[0]

        def get(self, url, **kw):
            return _Resp(db.get(self._path(url)))

        def put(self, url, **kw):
            db[self._path(url)] = kw.get("json")
            return _Resp({})

        def delete(self, url, **kw):
            db.pop(self._path(url), None)
            return _Resp({})

        patch = post = put

    from app.api.routes import smart_care_v2, smart_watering, devices
    for mod in (smart_watering, smart_care_v2, devices):
        monkeypatch.setattr(mod, "_req", _Req(), raising=False)

    clock = {"now": float(T0)}
    monkeypatch.setattr(smart_care_v2, "_server_now_ms", lambda: clock["now"])

    def _decode(token):
        uid, tenant, role = token.split("@")
        return {"uid": uid, "tenantId": tenant, "role": role}

    set_decoder(_decode)
    from app.main import app
    yield TestClient(app), db, clock
    set_decoder(None)


def _tok(role=ROLE_ADMIN):
    return {"Authorization": f"Bearer u1@{TENANT}@{role}"}


H = "/api/v2/care/houses/H1"


def test_colocation_needs_forty_minutes_and_uses_the_server_clock(farm):
    client, db, clock = farm
    r = client.post(f"{H}/colocation", json={"action": "start"}, headers=_tok())
    assert r.status_code == 200 and r.json()["colocation"]["startMs"] == T0
    clock["now"] = T0 + 20 * STEP
    assert client.post(f"{H}/colocation", json={"action": "end"}, headers=_tok()).status_code == 400
    clock["now"] = T0 + 60 * STEP
    r = client.post(f"{H}/colocation", json={"action": "end"}, headers=_tok())
    assert r.status_code == 200
    stored = db[f"{BASE}/houses/H1/meta.json"]["calibration"]["colocation"]
    assert stored == {"startMs": T0, "endMs": T0 + 60 * STEP}
    # The calibration screen reads it back, with the server's clock beside it.
    c = client.get(f"{H}/calibration", headers=_tok()).json()
    assert c["colocation"] == stored and c["serverNowMs"] == T0 + 60 * STEP


def test_a_viewer_cannot_mark_colocation_or_run_the_analysis(farm):
    client, _db, _clock = farm
    assert client.post(f"{H}/colocation", json={"action": "start"},
                       headers=_tok(ROLE_VIEWER)).status_code == 403
    assert client.post(f"{H}/placement-analysis", headers=_tok(ROLE_VIEWER)).status_code == 403


def test_analysis_is_run_stored_and_read_back(farm):
    client, db, clock = farm
    meta = db[f"{BASE}/houses/H1/meta.json"]
    meta["calibration"]["colocation"] = {"startMs": T0, "endMs": T0 + 60 * STEP}
    clock["now"] = T0 + 2 * 1440 * STEP

    r = client.post(f"{H}/placement-analysis", headers=_tok())
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["fieldsUsed"] == ["temperature", "humidity", "vpd"]
    # The injected +0.4 C / -2 % bias on S2 is found and removed.
    s2 = out["bias"]["offsets"]["S2"]
    assert abs(s2["temperature"] - 0.4) < 0.1 and abs(s2["humidity"] + 2.0) < 0.4
    assert out["coverage"]["node"]["radius"] is not None
    assert f"{BASE}/placementAnalysis/H1.json" in db
    # Never inside the house document the engine downloads every minute.
    assert not any("/houses/H1/placementAnalysis" in k for k in db)

    again = client.get(f"{H}/placement-analysis", headers=_tok(ROLE_VIEWER))
    assert again.status_code == 200
    assert again.json()["coverage"] == out["coverage"]


def test_analyze_placement_keeps_the_shape_the_app_reads(farm):
    client, _db, clock = farm
    clock["now"] = T0 + 2 * 1440 * STEP
    r = client.post(f"{H}/analyze-placement", json={"maxSensors": 8}, headers=_tok())
    assert r.status_code == 200, r.text
    body = r.json()
    ks = [row["sensors"] for row in body["table"]]
    assert ks and min(ks) >= 4                      # only layouts production can run
    for row in body["table"]:
        assert set(row["errors"]) == {"temperature", "humidity", "vpd"}
        assert len(body["positions"][str(row["sensors"])]) == row["sensors"]
    assert body["recommendedSensors"] in ks
    assert "placement" in body["analysis"] and "coverage" in body["analysis"]


def test_too_little_data_is_a_409_in_words(farm):
    client, db, clock = farm
    for sid in COORDS:
        recs = db[f"{BASE}/history/H1/{sid}.json"]
        db[f"{BASE}/history/H1/{sid}.json"] = dict(list(recs.items())[:100])
    r = client.post(f"{H}/placement-analysis", headers=_tok())
    assert r.status_code == 409 and "ten-minute periods" in r.json()["detail"]


def test_analysis_can_run_early_and_says_so(farm):
    client, _db, clock = farm
    clock["now"] = T0 + 0.5 * 1440 * STEP           # half a day: not yet
    c = client.get(f"{H}/calibration", headers=_tok()).json()
    assert c["canAnalyse"] is False and c["ready"] is False
    clock["now"] = T0 + 1.5 * 1440 * STEP           # a day and a half: early
    c = client.get(f"{H}/calibration", headers=_tok()).json()
    assert c["canAnalyse"] is True and c["early"] is True and c["ready"] is False
    clock["now"] = T0 + 3.1 * 1440 * STEP           # past the target: not early
    for sid in COORDS:                              # ...and every node still reporting
        _db[f"{BASE}/history/H1/{sid}.json"]["fresh"] = {
            "timestamp": clock["now"] - STEP, "temperature": 27.0, "humidity": 75.0}
    c = client.get(f"{H}/calibration", headers=_tok()).json()
    assert c["ready"] is True and c["early"] is False



# ── review fixes, 7 Oct 2026 ────────────────────────────────────────────────

def test_a_silent_node_is_not_ready_however_many_readings_it_left(farm):
    client, db, clock = farm
    clock["now"] = T0 + 2 * 1440 * STEP + 3 * 60 * STEP     # data ended 3 h ago
    c = client.get(f"{H}/calibration", headers=_tok()).json()
    assert c["canAnalyse"] is False
    assert all(not r["ok"] for r in c["sections"])
    assert any("stopped reporting" in b for b in c["blockers"])


def test_days_count_from_the_end_of_colocation(farm):
    client, db, clock = farm
    meta = db[f"{BASE}/houses/H1/meta.json"]
    end = T0 + 1440 * STEP                                   # co-location done on day 1
    meta["calibration"]["colocation"] = {"startMs": end - 60 * STEP, "endMs": end}
    clock["now"] = T0 + 2 * 1440 * STEP - STEP
    c = client.get(f"{H}/calibration", headers=_tok()).json()
    assert c["countingFromMs"] == end + 15 * STEP            # plus the settle time
    assert c["daysElapsed"] < 1.0                            # not 2.0 from creation
    assert c["canAnalyse"] is False


def test_nothing_can_be_analysed_while_colocation_is_running(farm):
    client, db, clock = farm
    db[f"{BASE}/houses/H1/meta.json"]["calibration"]["colocation"] = {"startMs": T0}
    clock["now"] = T0 + 1.5 * 1440 * STEP
    c = client.get(f"{H}/calibration", headers=_tok()).json()
    assert c["canAnalyse"] is False and "Co-location is still running" in c["blockers"][0]
    r = client.post(f"{H}/placement-analysis", headers=_tok())
    assert r.status_code == 409 and "still running" in r.json()["detail"]


def test_a_three_section_house_that_keeps_every_sensor_can_be_activated(farm):
    client, db, clock = farm
    secs = db[f"{BASE}/houses/H1/sections.json"]
    for sid in ("S4", "S5", "S6"):
        secs.pop(sid)
    r = client.post(f"{H}/apply-placement", json={"keep": ["S1", "S2", "S3"]}, headers=_tok())
    assert r.status_code == 200, r.text
    assert db[f"{BASE}/houses/H1/meta.json"]["lifecycle"] == "active"
    # Freeing a sensor below the kriging minimum is still refused.
    secs["S4"] = {"meta": {"name": "S4", "x": 9, "y": 13}}
    r = client.post(f"{H}/apply-placement", json={"keep": ["S1", "S2", "S3"]}, headers=_tok())
    assert r.status_code == 400


def test_push_ids_decode_to_their_write_time():
    from app.api.routes.smart_care_v2 import _PUSH_CHARS, _push_id_ms
    ms = 1_791_234_567_890
    head, v = "", ms
    for _ in range(8):
        head = _PUSH_CHARS[v % 64] + head
        v //= 64
    assert _push_id_ms(head + "abcdefghijkl") == ms
    assert _push_id_ms("k000123") is None and _push_id_ms("seed001") is None
