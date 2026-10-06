"""The shade-house check: does the indoor conversion the watering model was
trained on match what sensors record?

Every reading and every outdoor hour in this file is TEST DATA, BUILT so the
answer is known in advance: indoor = outdoor + warming x sun, and so on, with
constants chosen here. A check that recovers constants it was not told is
measuring them; one that recovers the assumed 3.5 / 7 / 0.45 whatever it is fed
would be reciting them, and the first test is there to tell those apart.

No network anywhere. The outdoor fetch is replaced in the route tests, and
urllib's urlopen is made to fail, so a slip would be an error rather than a
call to Open-Meteo from CI.
"""
import io
import json
import math
import urllib.request
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.services import shadehouse_check as shc
from app.services.firebase_auth import ROLE_VIEWER, set_decoder

HOUR = 3_600_000
MIN = 60_000
T0 = int(datetime(2026, 10, 7, tzinfo=timezone.utc).timestamp() * 1000)   # 00:00 UTC


# ── TEST DATA builders ───────────────────────────────────────────────────────

def _sun(hour_utc: int) -> float:
    """A clear-sky day in Sri Lanka, by UTC hour: sunrise 06:00 local is 00:30
    UTC, so the sun is up from UTC hour 1 to 12. TEST DATA."""
    local = (hour_utc + 5.5) % 24
    return max(0.0, math.sin(math.pi * (local - 6.0) / 12.0)) if 6 <= local <= 18 else 0.0


def outdoor_table(hours: int, start: int = T0, source: str = "era5-archive",
                  night_rh: float = 85.0) -> dict:
    """TEST DATA outdoor weather, one row per UTC hour, shaped like fetch_outdoor()."""
    rows = []
    for i in range(hours):
        ms = start + i * HOUR
        s = _sun((ms // HOUR) % 24)
        rows.append({"hourMs": ms,
                     "temperature": 24.0 + 7.0 * s + 0.1 * (i % 5),
                     "humidity": night_rh - 25.0 * s,
                     "radiation": 950.0 * s})
    return {"source": source, "note": "TEST DATA", "hours": rows}


def indoor_from(outdoor: dict, warming: float, lift: float, trans: float,
                minutes=(5, 25, 45), mutate=None) -> dict:
    """TEST DATA readings for one section: the outdoor hour moved indoors by the
    given constants, in the same form as to_shadehouse(), several readings per
    hour. `mutate(rec, i)` may break individual readings."""
    hist, i = {}, 0
    for o in outdoor["hours"]:
        s = min(1.0, max(0.0, o["radiation"] / 1000.0))
        t = o["temperature"] + warming * s
        rh = o["humidity"] + lift * (1 - 0.45 * s)
        lux = o["radiation"] * trans * 120.0
        for m in minutes:
            ts = o["hourMs"] + m * MIN
            rec = {"timestamp": ts, "temperature": t, "humidity": rh, "light": lux}
            if mutate:
                rec = mutate(rec, i)
            hist[f"-k{ts}"] = rec
            i += 1
    return hist


# ── The estimates ────────────────────────────────────────────────────────────

def test_constants_it_was_not_told_are_recovered():
    """2.0 C, 10 % and 0.30 are NOT the assumed 3.5 / 7 / 0.45, so recovering
    them shows the numbers are measured from the readings."""
    out = outdoor_table(48)
    res = shc.compare({"S1": indoor_from(out, 2.0, 10.0, 0.30)}, out, now_ms=T0 + 3 * 24 * HOUR)

    assert res["enough"] is True
    assert res["hours"] == 48 and res["sections"] == ["S1"]
    assert res["measured"] == {"warming": 2.0, "humidityLift": 10.0, "transmission": 0.3}
    assert res["gap"] == {"warming": -1.5, "humidityLift": 3.0, "transmission": -0.15}
    assert res["verdict"] == {"warming": "out of tolerance",
                              "humidityLift": "within tolerance",
                              "transmission": "out of tolerance"}
    assert res["overall"]["holds"] is False
    assert res["overall"]["suggested"]["MAX_DAY_WARMING"] == 2.0
    assert res["assumed"] == {"warming": 3.5, "humidityLift": 7.0, "transmission": 0.45}
    assert res["tolerance"] == {"warming": 1.0, "humidityLift": 4.0, "transmission": 0.10}


def test_a_house_that_matches_the_assumption_is_judged_to_hold():
    out = outdoor_table(48)
    res = shc.compare({"S1": indoor_from(out, 3.5, 7.0, 0.45)}, out, now_ms=T0 + 3 * 24 * HOUR)
    assert res["measured"] == {"warming": 3.5, "humidityLift": 7.0, "transmission": 0.45}
    assert res["overall"]["holds"] is True and res["overall"]["unchecked"] == []
    # The indoor estimate beats the raw outdoor weather when the conversion is right.
    err = res["estimateError"]["temperature"]
    assert err["outdoorPlusAssumed"] == 0.0 and err["outdoorAsIs"] > 0.5


def test_sections_are_pooled_and_each_is_reported_on_its_own():
    out = outdoor_table(48)
    res = shc.compare({"S1": indoor_from(out, 3.0, 7.0, 0.45),
                       "S2": indoor_from(out, 4.0, 7.0, 0.45)}, out,
                      now_ms=T0 + 3 * 24 * HOUR)
    assert res["perSection"]["S1"]["measured"]["warming"] == 3.0
    assert res["perSection"]["S2"]["measured"]["warming"] == 4.0
    assert res["measured"]["warming"] == 3.5          # median of the pooled pairs
    assert res["sectionHours"] == 96 and res["hours"] == 48


def test_failed_and_absent_readings_are_missing_not_numbers():
    """light -999 on every reading (no BH1750), temperature -999 on every third
    (a DHT22 glitch), and some readings with no light key at all. The old script
    turned the first into a NEGATIVE transmission and dropped the third whole."""
    out = outdoor_table(48)

    def broken(rec, i):
        rec["light"] = -999
        if i % 3 == 0:
            rec["temperature"] = -999
        if i % 7 == 0:
            del rec["light"]
        return rec

    res = shc.compare({"S1": indoor_from(out, 2.0, 10.0, 0.30, mutate=broken)}, out,
                      now_ms=T0 + 3 * 24 * HOUR)
    assert res["measured"]["warming"] == 2.0           # glitches skipped, not averaged in
    assert res["measured"]["humidityLift"] == 10.0     # no-light readings still counted
    assert res["measured"]["transmission"] is None
    assert res["verdict"]["transmission"].startswith("not enough data")
    assert "-999" in res["verdict"]["transmission"]
    assert res["overall"]["unchecked"] == ["transmission"]
    exc = res["excluded"]["S1"]
    assert exc["light"] == 48 * 3 and exc["temperature"] == 48


def test_a_light_reading_pinned_at_the_bh1750_ceiling_is_not_used():
    out = outdoor_table(48)

    def pinned(rec, i):
        if rec["light"] > 30000:
            rec["light"] = 65535 / 1.2
        return rec

    hist = indoor_from(out, 3.5, 7.0, 0.45, mutate=pinned)
    res = shc.compare({"S1": hist}, out, now_ms=T0 + 3 * 24 * HOUR)
    assert res["excluded"]["S1"]["lightAtCeiling"] > 0
    assert res["measured"]["transmission"] == 0.45     # from the readings below the ceiling


def test_seeded_and_unsynced_readings_are_not_the_house():
    """seed_farm_v2.py's synthetic records carry REAL timestamps, so only their
    key gives them away; a node that never synced its clock stamps 1970."""
    out = outdoor_table(48)
    hist = indoor_from(out, 3.5, 7.0, 0.45)
    for i in range(30):
        hist[f"seed{i:03d}"] = {"timestamp": T0 + i * HOUR + 10 * MIN,
                                "temperature": 50.0, "humidity": 20.0, "light": 100.0}
    hist["-k1970"] = {"timestamp": 12_345, "temperature": 26.0, "humidity": 80.0, "light": 0}
    res = shc.compare({"S1": hist}, out, now_ms=T0 + 3 * 24 * HOUR)
    assert res["measured"]["warming"] == 3.5
    assert res["excluded"]["S1"]["seeded"] == 30 and res["excluded"]["S1"]["badClock"] == 1
    assert shc.reading_window({"S1": hist}, now_ms=T0 + 3 * 24 * HOUR) == (
        date(2026, 10, 7), date(2026, 10, 8))


def test_humid_nights_where_no_lift_can_show_are_left_out():
    """Outdoors at 96 % the conversion clips at 99 and a DHT22 cannot read 103,
    so those hours say nothing about the lift. Counted, they would report ~3 %."""
    out = outdoor_table(48, night_rh=96.0)

    def saturate(rec, i):
        rec["humidity"] = min(99.9, rec["humidity"])
        return rec

    res = shc.compare({"S1": indoor_from(out, 3.5, 7.0, 0.45, mutate=saturate)}, out,
                      now_ms=T0 + 3 * 24 * HOUR)
    assert res["measured"]["humidityLift"] == 7.0
    assert res["hoursUsed"]["humidityLift"] < res["hours"]


# ── UTC, not Colombo ─────────────────────────────────────────────────────────

def test_an_indoor_reading_at_0830_utc_pairs_with_the_0800_utc_hour():
    at = T0 + 8 * HOUR + 30 * MIN
    hours, _ = shc.indoor_by_hour({"k": {"timestamp": at, "temperature": 31.0,
                                         "humidity": 70.0, "light": 20000}})
    assert list(hours) == [T0 + 8 * HOUR]

    # Every hour's outdoor value is different, and ONE reading per hour sits at
    # :30. Only a pairing with the same UTC hour recovers the constant exactly:
    # the Colombo hour (14:00 for 08:30 UTC) or rounding to 09:00 would not.
    out = outdoor_table(24)
    res = shc.compare({"S1": indoor_from(out, 2.5, 7.0, 0.45, minutes=(30,))}, out,
                      now_ms=T0 + 2 * 24 * HOUR)
    assert res["measured"]["warming"] == 2.5
    row = next(r for r in res["byHour"] if r["hourUtc"] == 8)
    eight = next(o for o in out["hours"] if o["hourMs"] == T0 + 8 * HOUR)
    assert row["outdoorTemp"] == round(eight["temperature"], 1)
    assert row["localTime"] == "13:30"
    # byHour reads midnight to midnight in FARM time, and keeps empty hours.
    assert len(res["byHour"]) == 24 and res["byHour"][0]["localTime"] == "00:30"


def test_open_meteo_times_are_read_as_gmt():
    payload = {"hourly": {"time": ["2026-10-07T07:00", "2026-10-07T08:00"],
                          "temperature_2m": [27.0, 28.0],
                          "relative_humidity_2m": [80, 78],
                          "shortwave_radiation": [400.0, None]}}
    rows = shc.parse_hourly(payload, date(2026, 10, 7), date(2026, 10, 7))
    assert rows == [{"hourMs": T0 + 7 * HOUR, "temperature": 27.0,
                     "humidity": 80.0, "radiation": 400.0}]   # an hour with a gap is dropped whole


# ── Not enough data, in words ────────────────────────────────────────────────

def test_fewer_than_twelve_hours_is_refused_in_words():
    out = outdoor_table(11)
    res = shc.compare({"S1": indoor_from(out, 3.5, 7.0, 0.45)}, out, now_ms=T0 + 24 * HOUR)
    assert res["enough"] is False
    assert res["reason"].startswith("Not enough data")
    assert "11 hours" in res["reason"] and "12" in res["reason"]
    assert "measured" not in res


def test_twelve_hours_of_night_is_refused_in_words():
    out = outdoor_table(12, start=T0 + 13 * HOUR)      # 18:30 to 06:30 farm time
    assert all(h["radiation"] == 0 for h in out["hours"])
    res = shc.compare({"S1": indoor_from(out, 3.5, 7.0, 0.45)}, out, now_ms=T0 + 2 * 24 * HOUR)
    assert res["enough"] is False and "sun" in res["reason"]


def test_a_section_with_too_few_hours_says_so_beside_the_others():
    out = outdoor_table(48)
    short = {"hours": out["hours"][:5]}
    res = shc.compare({"S1": indoor_from(out, 3.5, 7.0, 0.45),
                       "S2": indoor_from(short, 3.5, 7.0, 0.45)}, out,
                      now_ms=T0 + 3 * 24 * HOUR)
    assert res["perSection"]["S2"]["verdict"]["warming"].startswith("not enough data: 5")
    assert res["perSection"]["S2"]["measured"]["warming"] is None


# ── Which weather: archive or recent ─────────────────────────────────────────

def test_old_days_come_from_the_archive_and_the_last_week_from_the_forecast():
    today = date(2026, 10, 11)
    plan = shc.outdoor_plan(date(2026, 9, 20), date(2026, 10, 10), today)
    assert plan == [
        {"api": "archive", "start": date(2026, 9, 20), "end": date(2026, 10, 3)},
        {"api": "forecast", "start": date(2026, 10, 4), "end": date(2026, 10, 10), "pastDays": 7},
    ]
    # 7-10 Oct, checked on the 11th: none of it is in the archive yet.
    assert [p["api"] for p in shc.outdoor_plan(date(2026, 10, 7), date(2026, 10, 10), today)] \
        == ["forecast"]
    # A simulator clock running ahead does not ask for the future.
    assert shc.outdoor_plan(date(2026, 12, 1), date(2026, 12, 2), today) == []


def test_fetch_asks_in_gmt_and_says_which_source_it_used():
    urls = []

    def fake_open(url, timeout):
        urls.append(url)
        day = "2026-09-25" if "archive" in url else "2026-10-09"
        body = {"hourly": {"time": [f"{day}T06:00"], "temperature_2m": [30.0],
                           "relative_humidity_2m": [70], "shortwave_radiation": [800.0]}}
        return io.BytesIO(json.dumps(body).encode())

    got = shc.fetch_outdoor(6.9, 79.9, date(2026, 9, 25), date(2026, 10, 9),
                            today=date(2026, 10, 11), urlopen=fake_open)
    assert all("timezone=GMT" in u for u in urls)
    assert "archive-api.open-meteo.com" in urls[0] and "start_date=2026-09-25" in urls[0]
    assert "api.open-meteo.com/v1/forecast" in urls[1] and "past_days=7" in urls[1]
    assert got["source"] == "mixed" and "NOT ERA5" in got["note"]
    assert len(got["hours"]) == 2


# ── The routes ───────────────────────────────────────────────────────────────

TENANT = "t_a"
BASE = f"/tenants/{TENANT}/farm"
NOW = T0 + 3 * 24 * HOUR


@pytest.fixture
def farm(monkeypatch):
    """The fake-Firebase seam from test_placement_routes: `_req` is replaced, so
    every read lands in a dict keyed by the tenant-scoped path. TEST DATA."""
    out = outdoor_table(48)
    s1 = indoor_from(out, 2.0, 10.0, 0.30)
    s1["seed000"] = {"timestamp": T0 - 40 * 24 * HOUR, "temperature": 50.0,
                     "humidity": 20.0, "light": 1.0}
    db = {
        f"{BASE}/meta.json": {"latitude": 6.914174, "longitude": 79.972934},
        f"{BASE}/houses/H1/meta.json": {"name": "Test house"},
        f"{BASE}/houses/H1/sections.json": {"S1": {"meta": {"name": "S1"}},
                                            "S2": {"meta": {"name": "S2"}},
                                            "S3": {"meta": {"name": "S3"}}},
        f"{BASE}/history/H1/S1.json": s1,
        f"{BASE}/history/H1/S2.json": indoor_from(out, 3.0, 10.0, 0.30),
        # S3 exists but has never reported: it is left out, not counted as zero.
        f"{BASE}/houses/H2/meta.json": {"name": "Bench", "simulated": True},
        f"{BASE}/houses/H2/sections.json": {"S1": {"meta": {"name": "S1"}}},
        f"{BASE}/history/H2/S1.json": indoor_from(out, 3.5, 7.0, 0.45),
    }

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
    monkeypatch.setattr(smart_care_v2, "_server_now_ms", lambda: float(NOW))

    def _no_network(*a, **k):
        raise AssertionError("a test tried to reach the network")

    monkeypatch.setattr(urllib.request, "urlopen", _no_network)

    calls = []

    def fake_fetch(lat, lon, start, end, **kw):
        calls.append((lat, lon, start, end))
        return {**out, "source": "forecast-model", "note": shc.SOURCE_NOTES["forecast-model"]}

    monkeypatch.setattr(shc, "fetch_outdoor", fake_fetch)

    def _decode(token):
        uid, tenant, role = token.split("@")
        return {"uid": uid, "tenantId": tenant, "role": role}

    set_decoder(_decode)
    from app.main import app
    yield TestClient(app), db, calls
    set_decoder(None)


def _tok(role=ROLE_VIEWER):
    return {"Authorization": f"Bearer u1@{TENANT}@{role}"}


def test_route_pools_the_sections_that_have_history(farm):
    client, _db, calls = farm
    r = client.get("/api/v2/care/houses/H1/shadehouse-check", headers=_tok())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sections"] == ["S1", "S2"]
    assert body["perSection"]["S1"]["measured"]["warming"] == 2.0
    assert body["perSection"]["S2"]["measured"]["warming"] == 3.0
    assert body["measured"]["humidityLift"] == 10.0
    assert body["outdoorSource"]["source"] == "forecast-model"
    assert "NOT ERA5" in body["overall"]["text"] or "not ERA5" in body["overall"]["text"]
    assert len(body["byHour"]) == 24
    # The farm's own coordinates, and only the days the real readings span -
    # the seeded record 40 days earlier did not stretch the request.
    assert calls == [(6.914174, 79.972934, date(2026, 10, 7), date(2026, 10, 8))]
    assert body["location"]["source"] == "farm settings"


def test_route_can_be_restricted_to_one_section(farm):
    client, _db, _calls = farm
    r = client.get("/api/v2/care/houses/H1/shadehouse-check?section=S2", headers=_tok())
    assert r.status_code == 200, r.text
    assert r.json()["sections"] == ["S2"] and r.json()["measured"]["warming"] == 3.0
    assert client.get("/api/v2/care/houses/H1/shadehouse-check?section=S9",
                      headers=_tok()).status_code == 404


def test_route_says_not_enough_data_with_a_409(farm):
    client, db, _calls = farm
    for sid in ("S1", "S2"):
        recs = db[f"{BASE}/history/H1/{sid}.json"]
        db[f"{BASE}/history/H1/{sid}.json"] = dict(sorted(recs.items())[:3 * 5])   # 5 hours
    r = client.get("/api/v2/care/houses/H1/shadehouse-check", headers=_tok())
    assert r.status_code == 409 and r.json()["detail"].startswith("Not enough data")


def test_route_since_drops_readings_from_before_the_house(farm):
    client, _db, _calls = farm
    r = client.get(f"/api/v2/care/houses/H1/shadehouse-check?sinceMs={T0 + 40 * HOUR}",
                   headers=_tok())
    assert r.status_code == 409 and "8 hours" in r.json()["detail"]


def test_route_refuses_a_simulated_house(farm):
    """The node bench writes invented weather into a house marked simulated; a
    'measurement' of shade cloth from it would be fabricated."""
    client, _db, calls = farm
    r = client.get("/api/v2/care/houses/H2/shadehouse-check", headers=_tok())
    assert r.status_code == 409 and "simulated" in r.json()["detail"]
    assert calls == []


def test_route_needs_a_signed_in_member(farm):
    client, _db, _calls = farm
    assert client.get("/api/v2/care/houses/H1/shadehouse-check").status_code == 401


def test_validation_route_returns_the_file_as_written(farm, monkeypatch, tmp_path):
    from app.api.routes import smart_care_v2
    doc = {"generatedAt": "2026-10-07T00:00:00Z", "script": "TEST DATA",
           "splits": [{"name": "OUT-OF-TIME", "hourMaeMin": 1.0}]}
    f = tmp_path / "watering_validation.json"
    f.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(smart_care_v2, "WATERING_VALIDATION_PATH", str(f))
    client, _db, _calls = farm
    r = client.get("/api/v2/care/watering-validation", headers=_tok())
    assert r.status_code == 200 and r.json() == {"status": "success", **doc}

    monkeypatch.setattr(smart_care_v2, "WATERING_VALIDATION_PATH", str(tmp_path / "absent.json"))
    r = client.get("/api/v2/care/watering-validation", headers=_tok())
    assert r.status_code == 404 and "validate_out_of_time.py" in r.json()["detail"]


def test_the_shipped_validation_file_came_from_the_script():
    """The file the server serves has the shape validate_out_of_time.py writes.
    It is generated, never typed: this pins that every split carries its sizes
    and all four scores, so a hand-trimmed file shows up here."""
    from app.api.routes.smart_care_v2 import WATERING_VALIDATION_PATH
    with open(WATERING_VALIDATION_PATH, encoding="utf-8") as fh:
        doc = json.load(fh)
    assert doc["script"] == "ml_pipeline/validate_out_of_time.py"
    assert {"rows", "sites", "excluded", "years"} <= set(doc["dataset"])
    assert "ERA5" in doc["labelSource"]
    assert [s["name"] for s in doc["splits"]] == ["RANDOM", "OUT-OF-TIME", "UNSEEN"]
    for s in doc["splits"]:
        assert {"trainYears", "testYears", "trainRows", "testRows",
                "hourMaeMin", "hourR2", "durMaeSec", "durR2"} <= set(s)
