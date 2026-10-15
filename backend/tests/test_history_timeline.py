"""The History tab's full timeline, its CSV export, events kept forever, and the
chart's time window (15 Oct 2026).

The Firebase REST queries are emulated (orderBy="$key", startAt, endAt,
limitToLast), so these tests exercise the same key ranges production sends.
"""
import asyncio
import random
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

import pytest

TZ = timezone(timedelta(minutes=330))
END = datetime(2026, 10, 14, 18, 0, tzinfo=TZ)
END_MS = int(END.timestamp() * 1000)


class FakeFirebase:
    """Just enough of the RTDB REST query language for these paths."""

    def __init__(self):
        self.data = {}          # "/farm/history/H1/S1" -> {key: value}
        self.deleted = []

    def get(self, path):
        base, _, q = path.partition("?")
        base = base[:-5] if base.endswith(".json") else base
        node = self.data.get(base)
        if node is None or not q:
            return node
        params = dict(urllib.parse.parse_qsl(q))
        keys = sorted(node)
        if "startAt" in params:
            lo = params["startAt"].strip('"')
            keys = [k for k in keys if k >= lo]
        if "endAt" in params:
            hi = params["endAt"].strip('"')
            keys = [k for k in keys if k <= hi]
        if "limitToLast" in params:
            keys = keys[-int(params["limitToLast"]):]
        return {k: node[k] for k in keys}

    def put(self, path, value):
        base = path[:-5] if path.endswith(".json") else path
        parts = base.split("/")
        parent, key = "/".join(parts[:-1]), parts[-1]
        self.data.setdefault(parent, {})[key] = value
        return True

    def delete(self, path):
        self.deleted.append(path)
        return True


@pytest.fixture
def fb(monkeypatch):
    from app.api.routes import smart_care_v2 as sc
    f = FakeFirebase()
    monkeypatch.setattr(sc, "_fb_get", f.get)
    monkeypatch.setattr(sc, "_fb_put", f.put)
    monkeypatch.setattr(sc, "_fb_delete", f.delete)
    monkeypatch.setattr(sc, "farm_tz", lambda: TZ)
    monkeypatch.setattr(sc, "_server_now_ms", lambda: float(END_MS))
    return sc, f


def push_key(sc, ms, rnd):
    return sc._push_key_prefix(ms) + "".join(rnd.choice(sc._PUSH_CHARS) for _ in range(12))


def seed_readings(sc, f, start_ms, end_ms, every_s=72, delay_ms=10_000, seed=1):
    """Readings every `every_s`, keyed like the firmware's POST (server time, ~10 s later)."""
    rnd = random.Random(seed)
    node = f.data.setdefault("/farm/history/H1/S1", {})
    t, n = start_ms, 0
    while t <= end_ms:
        node[push_key(sc, t + delay_ms, rnd)] = {"temperature": 30.0 + (n % 7) / 10, "humidity": 75.0,
                                                 "light": 1200, "vpd": 1.0, "timestamp": t,
                                                 "sensorFault": False, "node": "validation"}
        t += every_s * 1000
        n += 1
    return n


def seed_event(f, ms, **fields):
    ms = int(ms)                              # real event keys are whole epoch ms
    f.data.setdefault("/farm/events/H1/S1", {})[str(ms)] = {"at": ms, **fields}


def test_timeline_merges_readings_and_events_newest_first(fb):
    sc, f = fb
    start = END_MS - 3_600_000
    seed_readings(sc, f, start, END_MS)
    seed_event(f, END_MS - 1_800_000, action="water", durationSec=73, withFertilizer=True,
               npkType="30-10-10", by="auto", confirmed=True)
    seed_event(f, END_MS - 900_000, action="tray", durationSec=15, by="auto", confirmed=False)
    out = sc.section_timeline("H1", "S1", start=start, end=END_MS, limit=300, ctx=None)
    ts = [x["t"] for x in out["items"]]
    assert ts == sorted(ts, reverse=True)
    kinds = [x["kind"] for x in out["items"]]
    assert kinds.count("water") == 1 and kinds.count("tray") == 1 and kinds.count("reading") == 51
    w = next(x for x in out["items"] if x["kind"] == "water")
    assert w["withFertilizer"] and w["npkType"] == "30-10-10" and w["local"] == "2026-10-14 17:30:00"
    assert out["counts"] == {"waterings": 1, "feeds": 1, "trays": 1, "lastFed": "2026-10-14 17:30"}
    assert out["nextBefore"] is None


def test_paging_covers_everything_once(fb):
    sc, f = fb
    start = END_MS - 6 * 3_600_000
    n = seed_readings(sc, f, start, END_MS)
    for k in range(5):
        seed_event(f, start + 3_600_000 * (k + 0.5), action="water", durationSec=90, by="auto")
    seen, before, pages = [], None, 0
    while True:
        out = sc.section_timeline("H1", "S1", start=start, end=END_MS, before=before, limit=37, ctx=None)
        seen += [(x["t"], x["kind"]) for x in out["items"]]
        pages += 1
        before = out["nextBefore"]
        if before is None:
            break
        assert pages < 100
    assert len(seen) == len(set(seen)) == n + 5
    assert [t for t, _ in seen] == sorted((t for t, _ in seen), reverse=True)


def test_type_filter_feed_shows_only_waterings_with_food(fb):
    sc, f = fb
    start = END_MS - 3_600_000
    seed_readings(sc, f, start, END_MS)
    seed_event(f, END_MS - 3_000_000, action="water", durationSec=90, withFertilizer=False)
    seed_event(f, END_MS - 2_000_000, action="water", durationSec=88, withFertilizer=True, npkType="10-30-20")
    seed_event(f, END_MS - 1_000_000, action="tray", durationSec=15)
    out = sc.section_timeline("H1", "S1", start=start, end=END_MS, types="feed", ctx=None)
    assert [(x["kind"], x["durationSec"]) for x in out["items"]] == [("water", 88)]
    out = sc.section_timeline("H1", "S1", start=start, end=END_MS, types="water,tray", ctx=None)
    assert sorted(x["kind"] for x in out["items"]) == ["tray", "water", "water"]


def test_a_failed_sensor_is_shown_as_missing_not_as_a_number(fb):
    sc, f = fb
    f.data["/farm/history/H1/S1"] = {push_key(sc, END_MS - 60_000, random.Random(3)): {
        "temperature": -999, "humidity": -999, "light": 840, "timestamp": END_MS - 60_000, "sensorFault": True}}
    out = sc.section_timeline("H1", "S1", start=END_MS - 3_600_000, end=END_MS, ctx=None)
    r = out["items"][0]
    assert r["temperature"] is None and r["humidity"] is None and r["vpd"] is None
    assert r["light"] == 840 and r["fault"] is True


def test_the_24_hour_chart_covers_24_hours_in_farm_time(fb):
    """15 Oct, on the phone: 'Last 24 hours' drew about 7 hours (02:-10:), labelled in UTC.
    Nodes report every ~72 s, not every 5 minutes as the old fetch assumed."""
    sc, f = fb
    seed_readings(sc, f, END_MS - 26 * 3_600_000, END_MS)
    out = asyncio.run(sc.section_history("H1", "S1", points=48, hours=24, ctx=None))
    first, last = out["series"][0], out["series"][-1]
    assert last["t"] == END_MS and (last["t"] - first["t"]) > 23.9 * 3_600_000
    assert first["label"] == "18:00" and out["count"] == 48
    custom = asyncio.run(sc.section_history("H1", "S1", points=48, start=END_MS - 32 * 3_600_000,
                                            end=END_MS - 2 * 3_600_000, ctx=None))
    assert custom["series"][-1]["t"] <= END_MS - 2 * 3_600_000
    assert re.match(r"\d\d [A-Z][a-z]{2} \d\d:\d\d", custom["series"][0]["label"])


def test_events_are_no_longer_deleted(fb):
    sc, f = fb
    section = {"latest": {"timestamp": END_MS}}
    for k in range(sc.EVENT_KEEP + 15):
        section["latest"]["timestamp"] = END_MS + k * 1000
        sc._log_event("H1", "S1", section, action="water", durationSec=60, by="auto")
    assert len(f.data["/farm/events/H1/S1"]) == sc.EVENT_KEEP + 15
    assert not [p for p in f.deleted if "/events/" in p]


def test_the_export_link_downloads_a_csv_and_expires(fb, monkeypatch):
    sc, f = fb
    from app.services.tenant_context import tenant_scope
    start = END_MS - 3_600_000
    seed_readings(sc, f, start, END_MS)
    seed_event(f, END_MS - 1_800_000, action="water", durationSec=73, withFertilizer=True, npkType="30-10-10",
               by="auto", confirmed=True)
    with tenant_scope("t_test"):
        link = sc.timeline_export("H1", "S1", sc.TimelineExportIn(start=start, end=END_MS), ctx=None)
    token, name = link["path"].split("/")[-2:]
    assert name == "H1-S1_20261014-20261014.csv"
    resp = sc.timeline_export_file(token, name)
    lines = resp.body.decode().strip().splitlines()
    assert lines[0].startswith("local_time,epoch_ms,type,temperature_c")
    assert len(lines) == 1 + 51 + 1
    assert any(",water," in ln and "30-10-10" in ln and "automatic,confirmed" in ln for ln in lines)
    assert resp.headers["content-disposition"] == f'attachment; filename="{name}"'
    with pytest.raises(sc.HTTPException):
        with tenant_scope("t_test"):
            sc.timeline_export("H1", "S1", sc.TimelineExportIn(start=start, end=start + 9 * 86_400_000), ctx=None)
    sc._exports[token]["exp"] = 0
    with pytest.raises(sc.HTTPException):
        sc.timeline_export_file(token, name)
