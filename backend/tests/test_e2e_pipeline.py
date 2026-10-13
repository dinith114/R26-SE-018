"""End-to-end scenarios for Component 3.

Walks the whole chain the system actually depends on:

    sensor node -> Firebase -> backend -> ML models -> app payload
                                       -> command -> back to the node

These are INTEGRATION tests, not unit tests. They talk to the real Firebase
instance and a real backend on :8000, because every bug this project has lost
time to lived in the seams between those parts, not inside any one of them:
a PUT that returned 200 and changed nothing, a cooldown comparing two different
clocks, a plan that was computed and never sent anywhere.

    Run:  cd backend
          python -m uvicorn app.main:app --host 0.0.0.0 --port 8000   (other shell)
          python -m pytest tests/test_e2e_pipeline.py -v

SAFETY: everything is written under house `HE2E`, never H1. The demo farm is not
touched, and the house is deleted again in teardown even if a test fails. If a
run is killed hard, delete `/farm/houses/HE2E` and `/devices/E2E*` by hand.

Scenarios that CANNOT be automated (a relay clicking, a pump actually moving
water, a brownout on WiFi join) are written up in
`docs/E2E_HARDWARE_SCENARIOS.md` and must be run against the bench.
"""
import json
import math
import time
import uuid

import pytest
import requests

API = "http://127.0.0.1:8000"
FB = "https://orchid-smart-care-default-rtdb.firebaseio.com"

HOUSE = "HE2E"                    # never H1
SEC = "SE1"
BASE = f"/farm/houses/{HOUSE}/sections/{SEC}"
TEST_MAC = "E2E000000001"

MIN_MS = 60_000
HOUR_MS = 3_600_000


# ───────────────────────── plumbing ─────────────────────────

def fb_put(path, body):
    return requests.put(f"{FB}{path}", json=body, timeout=15)


def fb_get(path):
    r = requests.get(f"{FB}{path}", timeout=15)
    return r.json() if r.ok else None


def fb_delete(path):
    return requests.delete(f"{FB}{path}", timeout=15)


def api(method, path, body=None, expect=200):
    r = requests.request(method, f"{API}{path}", json=body, timeout=90)
    if expect is not None:
        assert r.status_code == expect, (
            f"{method} {path} -> {r.status_code}\n{r.text[:500]}")
    return r.json() if r.content else None


def reading(ts_ms=None, **over):
    """A reading shaped exactly as sensor_node_validate.ino writes it."""
    r = {
        "temperature": 30.2, "humidity": 68.0, "light": 8400.0,
        "vpd": 1.36, "sampleMoisture": 52.0, "sensorFault": False,
        "timestamp": int(ts_ms if ts_ms is not None else time.time() * 1000),
    }
    r.update(over)
    return r


# ───────────────────────── fixtures ─────────────────────────

@pytest.fixture(scope="session", autouse=True)
def require_services():
    try:
        requests.get(f"{API}/health", timeout=10)
    except requests.RequestException as e:
        pytest.skip(f"backend not running on {API}: {e}")
    try:
        requests.get(f"{FB}/.json?shallow=true", timeout=15).raise_for_status()
    except requests.RequestException as e:
        pytest.skip(f"Firebase unreachable: {e}")


@pytest.fixture(scope="session", autouse=True)
def test_house(require_services):
    """An isolated house, torn down whatever happens."""
    fb_put(f"/farm/houses/{HOUSE}/meta.json", {
        "name": "E2E test house", "type": "shade-net",
        "plantCount": 12, "sectionCount": 1})
    fb_put(f"{BASE}/meta.json", {
        "name": "E2E section", "label": "automated test", "plantCount": 12,
        "growthStage": "Active", "lightExposure": 0.8,
        "deviceId": f"{HOUSE}-{SEC}"})
    fb_put(f"{BASE}/control.json", {"mode": "auto", "trayEnabled": True})
    fb_put(f"{BASE}/fertilizer.json", {"daysSince": 3})
    fb_put(f"{BASE}/latest.json", reading())
    _seed_history()
    yield
    fb_delete(f"/farm/houses/{HOUSE}.json")
    fb_delete(f"/farm/history/{HOUSE}.json")
    fb_delete(f"/devices/{TEST_MAC}.json")


def _seed_history():
    """24 h at 30-min spacing. The watering model decides on DAWN conditions, so
    a history without an 04:00-07:00 sample makes the plan fall back to a proxy
    and the test would be measuring the fallback, not the model."""
    now = time.time()
    bulk = {}
    for i in range(48):
        t = now - (47 - i) * 1800
        lt = time.localtime(t)
        h = lt.tm_hour + lt.tm_min / 60.0
        day = max(0.0, -math.cos((h - 6) / 24 * 2 * math.pi))
        bulk[f"e2e{i:03d}"] = reading(
            ts_ms=int(t * 1000),
            temperature=round(26.0 + 6.0 * day, 1),
            humidity=round(80.0 - 18.0 * day, 1),
            light=round(16000 * day))
    fb_put(f"/farm/history/{HOUSE}/{SEC}.json", bulk)


@pytest.fixture
def fresh_reading():
    fb_put(f"{BASE}/latest.json", reading())
    yield


def section_from_overview():
    ov = api("GET", "/api/v2/care/overview")
    for h in ov["houses"]:
        if h["houseId"] != HOUSE:
            continue
        for s in h["sections"]:
            if s["sectionId"] == SEC:
                return s
    raise AssertionError(f"{HOUSE}/{SEC} missing from /overview")


# ══════════════ A. sensor -> Firebase ══════════════

class TestSensorToFirebase:
    """The node is the only writer of `latest`. Nothing may mangle its payload."""

    def test_node_reading_survives_the_round_trip(self):
        r = reading(temperature=31.7, humidity=63.5, light=9100.0)
        assert fb_put(f"{BASE}/latest.json", r).ok
        back = fb_get(f"{BASE}/latest.json")
        assert back["temperature"] == 31.7
        assert back["humidity"] == 63.5
        assert back["timestamp"] == r["timestamp"]

    def test_history_is_stored_outside_the_section_subtree(self):
        """History under the section made /farm/houses.json 1 MB and the
        dashboard take seconds. It must stay at /farm/history/{h}/{s}."""
        sec = fb_get(f"{BASE}.json") or {}
        assert "history" not in sec or not sec["history"], (
            "history is back inside the section subtree — this is the 1 MB "
            "dashboard regression")
        assert fb_get(f"/farm/history/{HOUSE}/{SEC}.json"), "archive missing"

    def test_device_announces_itself_by_mac(self):
        fb_put(f"/devices/{TEST_MAC}.json", {
            "mac": TEST_MAC, "ip": "192.168.1.222", "rssi": -58,
            "fw": "e2e-test", "lastSeen": int(time.time())})
        devs = api("GET", "/api/v2/devices/")["devices"]
        mine = [d for d in devs if d["mac"] == TEST_MAC]
        assert mine, "announced device did not reach the registry"
        d = mine[0]
        assert d["shortId"] == TEST_MAC[-4:]
        assert d["online"] is True
        assert d["lastSeenSec"] < 120


# ══════════════ B. Firebase -> backend ══════════════

class TestFirebaseToBackend:

    def test_overview_carries_what_the_app_renders(self, fresh_reading):
        s = section_from_overview()
        for key in ("latest", "freshness", "meta"):
            assert key in s, f"/overview section is missing {key!r}"
        assert s["latest"]["temperature"] is not None
        assert s["freshness"]["state"] in (
            "live", "delayed", "stale", "never", "future")

    def test_a_current_reading_is_live(self, fresh_reading):
        f = section_from_overview()["freshness"]
        assert f["state"] == "live", f"fresh reading reported {f}"
        assert f["trusted"] is True

    def test_a_node_that_stopped_reporting_is_flagged(self):
        fb_put(f"{BASE}/latest.json", reading(ts_ms=time.time() * 1000 - 6 * HOUR_MS))
        f = section_from_overview()["freshness"]
        assert f["state"] == "stale"
        assert f["trusted"] is False
        assert "hours" in f["label"] or "days" in f["label"]

    def test_a_future_dated_reading_does_not_age_the_rest_of_the_farm(self):
        """Regression for the '163 days ago' bug: a section stamped ahead of
        real time must be flagged on its own, never become the farm's clock."""
        fb_put(f"{BASE}/latest.json", reading(ts_ms=time.time() * 1000 + 160 * 24 * HOUR_MS))
        s = section_from_overview()
        assert s["freshness"]["state"] == "future"
        assert s["freshness"]["trusted"] is False

        ov = api("GET", "/api/v2/care/overview")
        others = [x for h in ov["houses"] for x in h["sections"]
                  if not (h["houseId"] == HOUSE and x["sectionId"] == SEC)]
        poisoned = [x["sectionId"] for x in others
                    if ((x.get("freshness") or {}).get("ageMinutes") or 0) > 200_000]
        assert not poisoned, f"future-dated section aged its neighbours: {poisoned}"

    def test_failed_sensor_is_clamped_not_crashed(self):
        """-999 means the sensor failed. The backend must clamp it to a
        training-range default rather than feed -999 into a model."""
        fb_put(f"{BASE}/latest.json", reading(temperature=-999, humidity=-999))
        s = section_from_overview()
        t = (s.get("latest") or {}).get("temperature")
        assert t is None or t > -100, f"-999 leaked into the app payload: {t}"


# ══════════════ C. backend -> ML ══════════════

class TestBackendToML:

    def test_plan_is_a_morning_watering_time(self, fresh_reading):
        r = api("POST", f"/api/v2/care/houses/{HOUSE}/sections/{SEC}/plan")
        plan = r.get("plan") or r
        hh, mm = (int(x) for x in plan["waterTime"].split(":"))
        assert 5 <= hh <= 9, f"watering planned at {plan['waterTime']} — never a midday soak"
        assert 0 <= mm < 60
        assert 10 <= plan["durationSec"] <= 180
        assert plan.get("reason"), "a plan with no reason cannot be explained to a farmer"

    def test_dormant_plants_are_never_fertilized(self):
        """A hard guard in the backend, not a model output. A model bug was
        caught doing exactly this."""
        meta = fb_get(f"{BASE}/meta.json")
        fb_put(f"{BASE}/meta.json", {**meta, "growthStage": "Dormant"})
        try:
            r = api("POST", f"/api/v2/care/houses/{HOUSE}/sections/{SEC}/plan")
            fert = r.get("fertilizer") or {}
            assert fert.get("due") is not True, f"dormant plant scheduled to feed: {fert}"
        finally:
            fb_put(f"{BASE}/meta.json", meta)

    def test_tray_check_returns_a_decision(self, fresh_reading):
        fb_delete(f"{BASE}/tray.json")
        r = api("POST", f"/api/v2/care/houses/{HOUSE}/sections/{SEC}/tray-check")
        tray = r.get("tray") or r
        assert tray.get("status") in ("ok", "topup", "fill", "cooldown")
        assert "message" in tray

    def test_tray_cooldown_blocks_a_refill_loop(self, fresh_reading):
        """A 3 cm tray cannot dry out in under 6 h, so a second fill inside the
        window means the AIR is dry, not the tray. Refilling would overflow."""
        api("POST", f"/api/v2/care/houses/{HOUSE}/sections/{SEC}/tray-fill",
            {"fillSeconds": 10, "triggeredBy": "e2e"})
        fb_put(f"{BASE}/latest.json", reading(humidity=45.0))
        r = api("POST", f"/api/v2/care/houses/{HOUSE}/sections/{SEC}/tray-check")
        tray = r.get("tray") or r
        assert tray.get("status") == "cooldown", (
            f"tray refilled inside the cooldown window: {tray}")

    def test_model_info_is_reportable(self):
        info = api("GET", "/api/v2/care/model-info")
        assert info, "the About screen and the viva both read this"


# ══════════════ D. command path back to the hardware ══════════════

class TestCommandsReachTheNode:
    """The firmware polls  /farm/houses/{h}/sections/{s}/command  for
    {"id", "action", "durationSec"} and acknowledges at  .../commandAck .
    See sensor_node_validate.ino pollCommand() / seedLastCommandFromAck().
    """

    def test_water_request_is_accepted_and_clamped(self, fresh_reading):
        r = api("POST", f"/api/v2/care/houses/{HOUSE}/sections/{SEC}/water",
                {"durationSec": 9999, "withFertilizer": False, "triggeredBy": "e2e"})
        cmd = r["command"]
        assert cmd["durationSec"] <= 180, (
            f"a {cmd['durationSec']}s pour was accepted — the clamp is a safety net")
        assert cmd["requested"] is True

    def test_issued_command_lands_where_the_firmware_looks(self, fresh_reading):
        """THE integration test for cloud -> node.

        A watering command is only real if it appears at the path the firmware
        polls, in the shape it parses. Anything else is a decision that never
        leaves the server."""
        api("POST", f"/api/v2/care/houses/{HOUSE}/sections/{SEC}/water",
            {"durationSec": 20, "withFertilizer": False, "triggeredBy": "e2e"})

        doc = fb_get(f"{BASE}/command.json")
        assert doc, (
            "nothing at sections/{s}/command — the firmware polls that path and "
            "would never see this command")
        for field in ("id", "action", "durationSec"):
            assert field in doc, (
                f"command is missing {field!r}; pollCommand() rejects a command "
                f"without it. Got: {json.dumps(doc)[:200]}")
        assert doc["action"] == "water"
        assert doc["durationSec"] == 20

    def test_node_acknowledgement_is_durable(self):
        """The ack is the only record of what actually ran: the node reseeds
        lastCmdId from it after a reset so a reboot cannot repeat a pour."""
        cid = f"e2e{uuid.uuid4().hex[:8]}"
        fb_put(f"{BASE}/commandAck.json", {
            "id": cid, "action": "water", "durationSec": 12,
            "done": True, "at": int(time.time())})
        ack = fb_get(f"{BASE}/commandAck.json")
        assert ack["id"] == cid
        assert ack["done"] is True

    def test_tray_fill_command_is_issued(self, fresh_reading):
        r = api("POST", f"/api/v2/care/houses/{HOUSE}/sections/{SEC}/tray-fill",
                {"fillSeconds": 12, "triggeredBy": "e2e"})
        assert r["command"]["fillSeconds"] == 12
        assert r["command"]["requested"] is True


# ══════════════ E. device registry / the app's pairing flow ══════════════

class TestDevicePairing:

    def _announce(self):
        fb_put(f"/devices/{TEST_MAC}.json", {
            "mac": TEST_MAC, "ip": "192.168.1.222", "rssi": -60,
            "fw": "e2e-test", "lastSeen": int(time.time())})

    def test_assign_writes_both_directions(self):
        self._announce()
        api("PUT", f"/api/v2/devices/{TEST_MAC}/assign",
            {"house": HOUSE, "section": SEC, "force": True})
        assert fb_get(f"/devices/{TEST_MAC}/assignedTo.json") == f"{HOUSE}/{SEC}"
        assert fb_get(f"{BASE}/deviceMac.json") == TEST_MAC

    def test_section_lookup_finds_the_device(self):
        self._announce()
        api("PUT", f"/api/v2/devices/{TEST_MAC}/assign",
            {"house": HOUSE, "section": SEC, "force": True})
        r = api("GET", f"/api/v2/devices/section/{HOUSE}/{SEC}")
        assert r["device"]["mac"] == TEST_MAC

    def test_one_section_cannot_hold_two_nodes(self):
        self._announce()
        api("PUT", f"/api/v2/devices/{TEST_MAC}/assign",
            {"house": HOUSE, "section": SEC, "force": True})
        other = "E2E000000002"
        fb_put(f"/devices/{other}.json", {
            "mac": other, "ip": "192.168.1.223", "rssi": -66,
            "fw": "e2e-test", "lastSeen": int(time.time())})
        try:
            r = requests.put(f"{API}/api/v2/devices/{other}/assign",
                             json={"house": HOUSE, "section": SEC}, timeout=30)
            assert r.status_code == 409, (
                f"the 1:1 rule did not fire, got {r.status_code}")
        finally:
            fb_delete(f"/devices/{other}.json")

    def test_unassign_clears_both_sides(self):
        """Backs the Unlink button on the section screen. `_fb_put(path, None)`
        returns 200 and changes nothing, which made unassign silently no-op —
        this fails again the moment someone reintroduces that."""
        self._announce()
        api("PUT", f"/api/v2/devices/{TEST_MAC}/assign",
            {"house": HOUSE, "section": SEC, "force": True})

        api("DELETE", f"/api/v2/devices/{TEST_MAC}/assign")

        assert fb_get(f"/devices/{TEST_MAC}/assignedTo.json") is None, (
            "device still claims a section after unassign")
        assert fb_get(f"{BASE}/deviceMac.json") is None, (
            "section still points at the device after unassign")

    def test_unassigned_device_returns_to_the_picker(self):
        self._announce()
        api("DELETE", f"/api/v2/devices/{TEST_MAC}/assign", expect=None)
        free = api("GET", "/api/v2/devices/?only_unassigned=true")["devices"]
        assert any(d["mac"] == TEST_MAC for d in free), (
            "a released node never reappears in Add Section, so it can never "
            "be linked anywhere again")


# ══════════════ F. app-facing aggregates ══════════════

class TestAppPayloads:

    def test_alerts_endpoint_answers(self):
        r = api("GET", "/api/v2/care/alerts")
        assert "alerts" in r or "status" in r

    def test_history_series_is_chartable(self):
        r = api("GET", f"/api/v2/care/houses/{HOUSE}/sections/{SEC}/history"
                       "?points=24&hours=24")
        assert r["count"] >= 1, "the chart would be empty"
        pt = r["series"][0]
        assert "temperature" in pt and "humidity" in pt
