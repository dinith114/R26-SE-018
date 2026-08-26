"""
Smart Orchid Care v2 — redesigned API.

WHAT CHANGED FROM v1
--------------------
v1 asked "should we water? yes/no" using a root-moisture probe per plant.
That is impractical — you cannot probe every plant's roots.

v2 has two control loops per SECTION (= one microclimate zone = one device):

  LOOP 1 · WATERING   Daily watering is mandatory. The model predicts WHAT TIME
                      today and FOR HOW LONG. Normally once per day; a second
                      session is allowed ONLY in extreme heat (Vanda literature
                      permits twice-daily watering in extreme heat). Fertilizer,
                      when due, is injected into that same water.

  LOOP 2 · HUMIDITY   A shallow 3 cm tray per section. When humidity falls the
                      valve tops it up; evaporation lifts RH toward the Vanda
                      band (60-80%) WITHOUT soaking the roots. A hot day makes
                      the tray work harder rather than triggering a second spray.

Hierarchy:  farm -> houses -> sections
Firebase:   /farm/meta
            /farm/houses/{h}/sections/{s}/{latest,plan,tray,fertilizer,control,meta}
            /farm/history/{h}/{s}/{pushId}      <- archive, deliberately separate

The history archive is NOT stored under the section. Firebase REST returns a
whole subtree, so while history lived there every dashboard poll of
/farm/houses.json downloaded the entire archive — 1 MB against 8 KB of real
state, which made the app take seconds to show anything. Keep them apart.
"""

import math
import os
import pickle
# joblib, not pickle, for the v2 bundles: they are stored compressed so the
# backend can be deployed without shipping 1.7 GB. joblib.load reads a plain
# pickle too, so restoring an uncompressed backup still works.
import joblib
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Dict, List, Optional

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import requests as _req

from app.api.routes.smart_watering import _fb_get, _fb_put, FIREBASE_BASE_URL

router = APIRouter()


def _fb_delete(path: str) -> bool:
    try:
        return _req.delete(f"{FIREBASE_BASE_URL}{path}", timeout=8).status_code == 200
    except Exception:
        return False

# ─── Model loading ────────────────────────────────────────────────────────────
_MODEL_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "..", "ml_pipeline", "results"))

_water: Optional[dict] = None
_tray:  Optional[dict] = None
_fert:  Optional[dict] = None


def _load_v2():
    global _water, _tray, _fert
    _water = joblib.load(os.path.join(_MODEL_DIR, "watering_v2.pkl"))
    _tray  = joblib.load(os.path.join(_MODEL_DIR, "tray_v2.pkl"))
    _fert  = joblib.load(os.path.join(_MODEL_DIR, "fertilizer_v2.pkl"))
    m = _water["metrics"]
    print(f"[ML v2] Watering hour  MAE={m['hour']['mae_minutes']:.0f} min | "
          f"duration MAE={m['duration']['mae_seconds']:.0f}s | "
          f"2nd-session F1={m['second_session']['f1']:.3f}")
    print(f"[ML v2] Tray fill      MAE={_tray['metrics']['mae_seconds']:.2f}s")
    # Deliberately NOT printed as an F1 score. It is 1.0 because the label is a
    # deterministic function of the inputs, so the classifier reproduces a rule
    # the code already holds. Printing "F1=1.000" invites a claim we cannot defend.
    print("[ML v2] Fertilizer     rule-based schedule (encoded as a classifier, "
          "not learned from observed feeding)")


try:
    _load_v2()
except Exception as e:
    print(f"[WARN] v2 models not loaded from {_MODEL_DIR}: {e}")
    print("[WARN] Run: python ml_pipeline/train_models_v2.py")


def _ready() -> bool:
    return _water is not None and _tray is not None and _fert is not None


# ─── Sensor helpers ───────────────────────────────────────────────────────────
SENTINEL = -999
SAFE = {"temperature": 28.0, "humidity": 70.0, "light": 0.0}

# A 3 cm tray cannot physically dry out faster than this. Any "low humidity"
# sooner than this after a fill is caused by dry air, not an empty tray — so we
# refuse to refill and avoid a wasteful overflow loop.
COOLDOWN_HOURS = 6.0

# What "days since fertilized" means for a section that has never been fed
# through the system. Deliberately at the Active-stage interval so it reads as
# due once, is acted on, and then runs on real timestamps from that point.
FERT_UNKNOWN_DAYS = 7.0


# Physically possible ranges. A reading outside these means the sensor is
# faulty (stuck, disconnected, garbage on the wire) — not a real measurement.
LIMITS = {"temperature": (-10.0, 60.0), "humidity": (0.0, 100.0), "light": (0.0, 200000.0)}


# Values the models must never see, and the app must never be shown.
DISPLAY_DROP = (None, SENTINEL)


def _display(reading: dict) -> dict:
    """A reading as the FARMER should see it - or nothing at all.

    `_clean` exists to keep a model from being fed rubbish, so it substitutes
    training-range defaults for anything missing or flagged -999. Those defaults
    then leaked straight through /overview into the app, and a section with no
    sensor at all displayed 28.0 C and 70 % humidity as though measured - 70 %
    even landing inside the ideal band, so a zone with no hardware showed a
    green "GOOD".

    Nothing is invented here. A sensor that did not report reads as null, and
    the app shows "--".
    """
    raw = reading or {}
    if not raw.get("timestamp"):
        return {}
    out = {}
    for k, v in raw.items():
        if k in ("temperature", "humidity", "light", "vpd", "sampleMoisture"):
            try:
                fv = float(v)
            except (TypeError, ValueError):
                out[k] = None
                continue
            out[k] = None if fv <= SENTINEL else fv
        else:
            out[k] = v
    return out


def _clean(reading: dict) -> dict:
    """Make a raw device reading safe to feed to the models.

    Handles three kinds of bad data:
      * missing keys            -> training-range default
      * -999 sensor-fault flag  -> training-range default
      * physically impossible   -> clamped to the sensor's real range
        (e.g. 150% RH or -40 C means the sensor has failed, and feeding that
        to a model trained on 30-97% RH produces nonsense)
    """
    out = dict(reading or {})
    for k, dflt in SAFE.items():
        try:
            v = float(out.get(k))
        except (TypeError, ValueError):
            v = None
        if v is None or v <= SENTINEL:
            out[k] = dflt
        else:
            lo, hi = LIMITS[k]
            out[k] = min(max(v, lo), hi)
    return out


def vpd_kpa(temp_c: float, rh_pct: float) -> float:
    """Vapour Pressure Deficit (kPa) — the physical drying power of the air.

    Standard greenhouse metric; combines temperature and humidity into one
    number. This turned out to be the dominant driver of watering time.
    """
    svp = 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))
    return round(svp * (1.0 - rh_pct / 100.0), 3)


def _recent_history(house_id: str, section_id: str) -> dict:
    """The section's last ~24 h of readings, fetched ONCE.

    Both _yesterday_stats and _dawn_reading need this same window. They each
    used to fetch it themselves, so every plan pulled the identical ~50 KB from
    Firebase twice — about a second of pure waste per section, multiplied by
    every section on the farm.
    """
    return _fb_get(f'/farm/history/{house_id}/{section_id}.json'
                   f'?orderBy="$key"&limitToLast=288') or {}


def _yesterday_stats(raw: dict, fallback: dict) -> dict:
    """Summarise the section's own history (previous ~24 h)."""
    if not raw:
        return {"peak_temp": fallback["temperature"] + 5,
                "mean_humidity": fallback["humidity"],
                "mean_vpd": vpd_kpa(fallback["temperature"], fallback["humidity"])}
    recs = [_clean(r) for r in raw.values() if isinstance(r, dict)]
    if not recs:
        return {"peak_temp": fallback["temperature"] + 5,
                "mean_humidity": fallback["humidity"],
                "mean_vpd": vpd_kpa(fallback["temperature"], fallback["humidity"])}
    temps = [r["temperature"] for r in recs]
    hums  = [r["humidity"] for r in recs]
    vpds  = [vpd_kpa(r["temperature"], r["humidity"]) for r in recs]
    return {"peak_temp": round(max(temps), 1),
            "mean_humidity": round(sum(hums) / len(hums), 1),
            "mean_vpd": round(sum(vpds) / len(vpds), 3)}


def _dawn_reading(raw: dict, latest: dict) -> dict:
    """Find this section's DAWN reading (~5-6 AM) from its own history.

    The watering-time model is trained on dawn conditions — that is when the
    decision is actually made each morning. Feeding it an afternoon reading
    would be out-of-distribution and produce unreliable plans, so we search
    history for the reading nearest 05:00. If the history does not span a dawn
    yet, we fall back to the coolest reading available (the best dawn proxy).
    """
    if not raw:
        return latest
    recs = []
    for r in raw.values():
        if not isinstance(r, dict) or r.get("timestamp") is None:
            continue
        try:
            # LOCAL time: "dawn" is 04:00-07:00 where the plants are, and the
            # model was trained on Asia/Colombo hours.
            ts = to_farm_time(r["timestamp"])
        except Exception:
            continue
        recs.append((ts, _clean(r)))
    if not recs:
        return latest

    dawn = [(t, r) for t, r in recs if 4 <= t.hour <= 7]
    if dawn:
        # nearest to 05:00
        best = min(dawn, key=lambda p: abs((p[0].hour + p[0].minute / 60.0) - 5.0))
        return best[1]
    # no dawn in history yet — coolest reading is the closest proxy
    return min(recs, key=lambda p: p[1]["temperature"])[1]


# ═══════════════ GROWTH STAGE — Component 2 integration ══════════════════════
#
# Growth stage decides WHICH fertilizer a section gets (30-10-10 for active
# growth, 10-30-20 for flowering, none when dormant), so getting it wrong feeds
# the plant the wrong thing. It must not be a stale value someone typed once.
#
# ─── INTEGRATION CONTRACT FOR COMPONENT 2 (Growth Stage Recognition) ─────────
# Component 2 writes its prediction to this path, per section:
#
#   /farm/houses/{houseId}/sections/{sectionId}/growthPrediction
#   {
#     "stage":       "Active" | "Flowering" | "Dormant",
#     "confidence":  0.0 - 1.0,
#     "predictedAt": <epoch milliseconds>,
#     "source":      "component2-cnn"
#   }
#
# Nothing else is required — no API call, no import, no shared code. As soon as
# Component 2 starts writing that node, this component picks it up automatically.
# Until then the farmer's manual setting is used, and the app asks them to set it.
# ─────────────────────────────────────────────────────────────────────────────

GROWTH_PREDICTION_MAX_AGE_DAYS = 21   # a stage lasts weeks; older than this is stale
GROWTH_PREDICTION_MIN_CONF     = 0.50 # below this we do not trust it over the farmer
GROWTH_MANUAL_STALE_DAYS       = 60   # farmer's setting this old is probably outdated
VALID_STAGES = ("Active", "Flowering", "Dormant")


# The exact feature order these models were trained on.
#
# The bundles used to carry this as `feature_columns`, and /model-info read it
# straight out of the pickle. The retrain on real ERA5 weather stopped writing
# that key into watering_v2.pkl and tray_v2.pkl (only fertilizer_v2.pkl still
# has it), so /model-info raised KeyError and returned 500 - and the About
# screen and the viva both read that endpoint.
#
# ORDER MATTERS: these must stay in step with the arrays handed to
# scaler.transform() in _plan_section and _tray_decision. They are the labels
# for those columns, not an independent list.
WATER_FEATURES = [
    "dawn_temp", "dawn_humidity", "dawn_light", "dawn_vpd",
    "yest_peak_temp", "yest_mean_humidity", "yest_mean_vpd",
    "season_month", "growth_stage_enc", "light_exposure",
]
TRAY_FEATURES = ["temperature", "humidity", "light", "vpd", "hour"]


# ──────────────────── Commands: cloud → node ─────────────────────────
#
# There are TWO consumers of a command and they read DIFFERENT documents:
#
#   control/waterCommand   {requested, durationSec, withFertilizer, ...}
#       → FARM_SIMULATOR.html, the digital twin.
#
#   command                {id, action, durationSec}
#       → the real firmware. pollCommand() in sensor_node_validate.ino reads
#         this path and acknowledges at commandAck.
#
# The backend was written against the simulator; the firmware was written later
# against its own contract. For a while the app's Water Now button therefore
# wrote a document no physical node has ever read — the plants would not have
# been watered. Every command now goes through _issue_node_command as WELL as
# the control/* write, so both consumers act on it.
#
# The node matches by `id` and never deletes the document: a repeated poll of
# the same id is deliberately ignored, so a genuinely new command MUST carry a
# new id. Never reuse or reset one.
#
# Latency is one firmware read cycle - READ_INTERVAL_MS is 15 s - so a pump
# starts within about 15 seconds of the button, not instantly.

# "stop" ends whatever is running and carries no duration, which is why the
# duration guard below has to make an exception for it.
NODE_ACTIONS = ("water", "tray", "stop", "wifi")

# The firmware's own safety clamp: RELAY_MAX_SEC = 120 in
# sensor_node_validate.ino. The backend used to accept up to 180 s, so a manual
# request between 121 and 180 s made the app promise a pour the hardware would
# silently cut short. Clamp to the same number the relay will actually honour,
# so what the farmer is told is what happens. The model's own plans are already
# bounded to 30-120 s, so this only affects a manual override.
RELAY_MAX_SEC = 120


def _issue_node_command(house_id: str, section_id: str, action: str,
                        duration_sec: int, **extra) -> Optional[dict]:
    """Write the command document the FIRMWARE polls. Returns it, or None.

    The firmware ignores a command whose durationSec is <= 0, so a zero-length
    command is not written at all rather than being written and silently dropped.
    """
    if action not in NODE_ACTIONS:
        raise ValueError(f"unknown node action {action!r}")
    secs = int(duration_sec)
    # Only the two actions that move water need a duration. "stop" ends whatever
    # is running; "wifi" carries credentials instead.
    if secs <= 0 and action not in ("stop", "wifi"):
        return None

    now = datetime.now(timezone.utc)
    cmd = {"id": uuid.uuid4().hex[:12],
           "action": action,
           "durationSec": secs,
           "issuedAt": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
           # Epoch SECONDS, so the node can refuse a command that has gone
           # stale. A command document persists until something overwrites it,
           # so a node that reboots hours later would otherwise find the last
           # one and pour - which is exactly what happened on the bench:
           # a 20-hour-old watering command ran at boot. Seconds rather than
           # milliseconds because `long` is 32-bit on the ESP32 and an epoch in
           # ms overflows it.
           "issuedAtSec": int(now.timestamp())}
    cmd.update(extra)
    _fb_put(f"/farm/houses/{house_id}/sections/{section_id}/command.json", cmd)
    return cmd


def _last_ack(section: dict) -> dict:
    """What the node last reported finishing, for the app to confirm against."""
    ack = (section or {}).get("commandAck") or {}
    return {"id": ack.get("id"), "action": ack.get("action"),
            "durationSec": ack.get("durationSec"), "at": ack.get("at")}


# ─────────────────────────── Reading freshness ───────────────────────────────
# The farm has Wi-Fi but NO MAINS POWER: every node runs off a battery. A flat
# battery or a dropped Wi-Fi link makes a node stop reporting SILENTLY — the
# last reading just sits in Firebase looking perfectly current.
#
# That is dangerous in both directions:
#   * the farmer trusts a humidity number that is hours old, and
#   * the planner would happily irrigate from a stale reading.
#
# So every reading is aged here, server-side, and the app is never allowed to
# show a number without also showing how old it is.
#
# ─────────────────────── The farm's own clock ─────────────────────────
#
# Everything about WATERING is expressed in the plants' local time. The models
# were trained on ERA5 hourly weather fetched with `timezone=Asia/Colombo`
# (ml_pipeline/fetch_real_weather.py), so a predicted waterTime of "06:34" means
# 06:34 where the plants are - not 06:34 UTC.
#
# The server used to have no farm timezone at all. It planned and scheduled on
# UTC, so on this UTC+5:30 farm every watering fired 5.5 h late: on 24 Aug 2026
# the node acknowledged the day's watering at 06:36:58 UTC = 12:06:58 local, a
# MIDDAY SOAK, which is the single thing this component exists to prevent. The
# same gap fed the model bad input, because _dawn_reading searched 04:00-07:00
# UTC - 09:30-12:30 local - and called late-morning air "dawn".
#
# Only "what hour is it for the plants" moves. Absolute instants - reading
# freshness, the tray cooldown - are epoch based and are deliberately untouched.
FARM_TZ_NAME_DEFAULT   = "Asia/Colombo"
FARM_TZ_OFFSET_DEFAULT = 330      # minutes. Sri Lanka is UTC+5:30, and has no DST.
_TZ_CACHE_SEC          = 300      # this is read on every tick; do not hit Firebase each time

_tz_cache: Dict[str, object] = {"tz": None, "at": 0.0}


def farm_tz() -> tzinfo:
    """The farm's timezone, from /farm/meta.

    Prefers an IANA name (`timezone`: "Asia/Colombo") so a site with DST would
    be handled correctly. Falls back to a fixed offset (`tzOffsetMinutes`) when
    the IANA database is missing, which is the normal case on Windows without
    the `tzdata` package - and is exactly right here, Sri Lanka having no DST.
    """
    now = time.time()
    cached = _tz_cache.get("tz")
    if cached is not None and now - float(_tz_cache["at"]) < _TZ_CACHE_SEC:
        return cached                                    # type: ignore[return-value]

    meta = _fb_get("/farm/meta.json") or {}
    tz: Optional[tzinfo] = None
    name = meta.get("timezone") or FARM_TZ_NAME_DEFAULT
    try:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(str(name))
    except Exception:
        try:
            mins = int(meta.get("tzOffsetMinutes", FARM_TZ_OFFSET_DEFAULT))
        except (TypeError, ValueError):
            mins = FARM_TZ_OFFSET_DEFAULT
        tz = timezone(timedelta(minutes=mins))

    _tz_cache["tz"], _tz_cache["at"] = tz, now
    return tz


def farm_now() -> datetime:
    """Now, on the farm's clock. Use this for every watering decision."""
    return datetime.now(farm_tz())


# ────────────────── Who is allowed to act by itself ──────────────────
#
# ONE definition of this question, because there used to be two and they
# disagreed. automation.py asked `section_is_auto()`, which consults the farm
# switch and the per-section override. `_tray_decision` asked its own
# `ctrl.get("mode", "auto") != "manual"` - the LEGACY per-section key that
# /farm/meta/autoMode replaced.
#
# The consequence was that "Check Tray" would open a valve while the app was
# telling the farmer "Automatic care is OFF - the system alerts you and you do
# it yourself". The master switch did not cover the tray path at all. Verified
# on 24 Aug 2026: autoMode was false while S5 still carried control.mode "auto",
# so the tray auto-fill was live.
#
# `section_is_auto` in automation.py now delegates here. Do not reintroduce a
# second answer.
_AUTO_CACHE_SEC = 5.0        # asked once per section in a fan-out; do not re-fetch each time
_auto_cache: Dict[str, object] = {"on": None, "at": 0.0}


def farm_auto_mode() -> bool:
    """The farm-level switch. Defaults to ON for a freshly set-up farm."""
    now = time.time()
    if _auto_cache["on"] is not None and now - float(_auto_cache["at"]) < _AUTO_CACHE_SEC:
        return bool(_auto_cache["on"])
    meta = _fb_get("/farm/meta.json") or {}
    on = bool(meta.get("autoMode", True))
    _auto_cache["on"], _auto_cache["at"] = on, now
    return on


def section_acts_alone(section: dict, master: Optional[bool] = None) -> bool:
    """Does THIS section act without the farmer pressing anything?

    The farm switch decides, unless the farmer has pinned this one section.
    `control.override` is 'auto' | 'manual' | absent, and absent means
    "follow the farm".
    """
    if master is None:
        master = farm_auto_mode()
    ov = ((section or {}).get("control") or {}).get("override")
    if ov == "auto":
        return True
    if ov == "manual":
        return False
    return bool(master)


def to_farm_time(ts_ms) -> datetime:
    """An epoch-ms reading timestamp as the farm's local wall time."""
    return datetime.fromtimestamp(float(ts_ms) / 1000.0, tz=farm_tz())


# Production nodes read every 300 s (5 min) and sync their clock, so device time
# == wall-clock time and the server clock is the correct reference.
#
# "Now" USED to be max(server clock, newest reading anywhere on the farm), so an
# accelerated simulator could drive the whole farm's clock. That coupling is a
# trap: it lets ONE section decide how old EVERY other section looks. A browser
# simulator (FARM_SIMULATOR.html) left running with a fast-forward clock stamped
# H1/S1 with a 2027 date, and every healthy node on the farm was then aged
# against that clock and shown as "163 days ago" while it was reporting fine
# every 30 seconds. One bad row made the entire farm look dead.
#
# A reading may now only contribute to the farm clock if it is not implausibly
# ahead of the server clock. Future-dated readings are reported as a fault on
# their OWN section (see _freshness) instead of silently rebasing time for their
# neighbours. A dead node still ages out normally, because the server clock
# keeps advancing past its frozen reading.
# How late a reading may be before it stops being trustworthy.
#
# These used to be FIXED at 15 and 60 minutes, which is wrong in both directions
# now that the reporting interval is settable from the app. A node on a 15 s
# interval could be silent for sixty consecutive readings and still be called
# "live"; a node on 5 minutes was judged by a threshold that assumed 5 minutes,
# which happened to work and only by coincidence.
#
# A node is late when it has missed readings it OWED, so the thresholds are
# multiples of its own interval. The floor stops a fast interval from flapping
# on one dropped packet; the ceiling stops a very slow interval from hiding a
# dead node for hours.
READING_LIVE_CYCLES    = 2.0   # one missed reading is jitter; two is trouble
READING_DELAYED_CYCLES = 4.0   # beyond this it is stale and not trusted
READING_LIVE_FLOOR_MIN = 1.5   # never call a node late sooner than this
READING_LIVE_CEIL_MIN  = 20.0  # never wait longer than this to call it late

# What a node reports at when nothing has been configured. Matches
# READ_INTERVAL_MS in the firmware.
DEFAULT_READ_INTERVAL_MS = 15000

# Each cycle also does its blocking HTTP work - announce, fetch assignment, poll
# command, upload - which measured at about 11 s on this hardware. A node on a
# 15 s interval genuinely reports every ~27 s, so judging it against 15 s would
# call every healthy node late.
CYCLE_OVERHEAD_SEC = 12


def _freshness_limits(read_interval_ms=None):
    """(live_minutes, delayed_minutes) for a node reporting at this interval."""
    ms = read_interval_ms or DEFAULT_READ_INTERVAL_MS
    cycle_min = (ms / 1000.0 + CYCLE_OVERHEAD_SEC) / 60.0
    live = min(READING_LIVE_CEIL_MIN,
               max(READING_LIVE_FLOOR_MIN, cycle_min * READING_LIVE_CYCLES))
    delayed = max(live * 1.5, cycle_min * READING_DELAYED_CYCLES)
    return live, delayed
# Device clocks drift by seconds, and a reading can land in Firebase moments
# before the server reads it. Past this margin, a future timestamp is not drift:
# it is a wrong clock or fabricated data.
CLOCK_SKEW_TOLERANCE_MIN = 10.0
CLOCK_SKEW_TOLERANCE_MS  = CLOCK_SKEW_TOLERANCE_MIN * 60_000.0


def _server_now_ms() -> float:
    """Real wall-clock time. The only trustworthy reference for ageing data."""
    return datetime.now(timezone.utc).timestamp() * 1000.0


def _minutes_ahead(ts_ms) -> float:
    """How far a timestamp sits in the future, in minutes. 0 if it is in the past."""
    try:
        return max(0.0, (float(ts_ms) - _server_now_ms()) / 60_000.0)
    except (TypeError, ValueError):
        return 0.0


def _farm_now_ms(houses: dict) -> float:
    """'Now' for ageing readings — the server clock, never dragged forward by a
    section whose timestamp is in the future. See the note above."""
    server  = _server_now_ms()
    horizon = server + CLOCK_SKEW_TOLERANCE_MS
    newest  = 0.0
    for h in (houses or {}).values():
        if not isinstance(h, dict):
            continue
        for s in ((h.get("sections") or {})).values():
            if not isinstance(s, dict):
                continue
            try:
                ts = float(((s.get("latest") or {}).get("timestamp")))
            except (TypeError, ValueError):
                continue
            if ts > horizon:
                continue          # wrong clock: never allowed to define "now"
            newest = max(newest, ts)
    return max(server, newest)


def _plain_span(minutes: float) -> str:
    """A length of time: '25 minutes', '3 hours', '2 days'."""
    if minutes < 60:
        m = max(1, int(minutes))
        return "1 minute" if m == 1 else f"{m} minutes"
    hours = minutes / 60.0
    if hours < 24:
        h = int(round(hours))
        return "1 hour" if h == 1 else f"{h} hours"
    d = int(round(hours / 24.0))
    return "1 day" if d == 1 else f"{d} days"


def _plain_age(minutes: float) -> str:
    """A point in the past: 'just now', '25 min ago', '3 hours ago'."""
    if minutes < 2:  return "just now"
    if minutes < 60: return f"{int(minutes)} min ago"
    return f"{_plain_span(minutes)} ago"


def _freshness(section: dict, farm_now_ms: float, read_interval_ms=None) -> dict:
    """Age a section's last reading. Returned on every section in /overview."""
    ts = ((section or {}).get("latest") or {}).get("timestamp")
    if ts is None:
        return {"state": "never", "ageMinutes": None, "label": "No reading yet",
                "trusted": False,
                "message": "This device has never sent a reading. Check that it is "
                           "switched on and connected to Wi-Fi."}

    # A timestamp in the FUTURE is not fresh, it is wrong. _hours_since clamps a
    # negative age to zero, so without this the least trustworthy reading on the
    # farm would render as "just now" — which is exactly how the simulator's 2027
    # data passed itself off as live sensor data.
    ahead = _minutes_ahead(ts)
    if ahead > CLOCK_SKEW_TOLERANCE_MIN:
        return {"state": "future", "ageMinutes": None, "label": "clock wrong",
                "trusted": False,
                "message": f"This section's last reading is stamped {_plain_span(ahead)} "
                           "in the future, so either the device clock is wrong or the "
                           "data is simulated. These numbers cannot be trusted."}

    hrs = _hours_since(ts, farm_now_ms)
    if hrs is None:
        return {"state": "never", "ageMinutes": None, "label": "No reading yet",
                "trusted": False, "message": "This device has never sent a reading."}

    mins  = hrs * 60.0
    label = _plain_age(mins)
    READING_LIVE_MIN, READING_DELAYED_MIN = _freshness_limits(read_interval_ms)

    if mins <= READING_LIVE_MIN:
        return {"state": "live", "ageMinutes": round(mins), "label": label,
                "trusted": True, "message": ""}
    if mins <= READING_DELAYED_MIN:
        # trusted=False from the moment a node misses the readings it owed.
        #
        # This used to be True, on the theory that "late but plausible" was
        # still usable. In practice it meant a node could be silent for twice
        # its own reporting interval while the app showed its last value in
        # full colour, with the action buttons live - so a farmer could press
        # Water Now against a number the hardware had stopped standing behind.
        # "delayed" and "stale" now differ only in how long it has been, which
        # is what the message says; neither is trusted.
        return {"state": "delayed", "ageMinutes": round(mins), "label": label,
                "trusted": False,
                "message": f"Last reading {label}. This node has missed at least two "
                           f"readings in a row, so what it last sent may no longer be "
                           f"true. Check its power and Wi-Fi."}
    return {"state": "stale", "ageMinutes": round(mins), "label": label,
            "trusted": False,
            "message": f"No reading for {_plain_span(mins)}. These numbers are old — "
                       f"check the device's battery and Wi-Fi before trusting them."}


def _seasonal_stage(month: int) -> str:
    """Last-resort estimate from the Sri Lankan season. Never silently trusted —
    it is always reported as source='seasonal' so the app can flag it."""
    if month in (12, 1, 2):
        return "Dormant"
    if month in (10, 11):
        return "Flowering"
    return "Active"


def _resolve_growth_stage(section: dict) -> dict:
    """Decide the growth stage, preferring Component 2's prediction.

    Order: Component 2 prediction -> farmer's manual setting -> seasonal guess.
    Always reports which source was used and whether the farmer should act.
    """
    meta = (section or {}).get("meta") or {}
    now  = datetime.now(timezone.utc)
    # NOTE: growth-stage timestamps use REAL server time, not the device clock.
    # Component 2 and the setup wizard both run off-device, so their timestamps
    # are wall-clock. (The tray cooldown is the opposite case — both of its
    # timestamps come from the device, so that one uses device time.)
    real_now = now.timestamp() * 1000.0
    month    = now.month

    # 1 ── Component 2's prediction
    pred = (section or {}).get("growthPrediction") or {}
    stage = pred.get("stage")
    if stage in VALID_STAGES:
        try:
            conf = float(pred.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0.0
        age_h = _hours_since(pred.get("predictedAt"), real_now)
        age_d = (age_h / 24.0) if age_h is not None else None
        fresh = age_d is None or age_d <= GROWTH_PREDICTION_MAX_AGE_DAYS

        if conf >= GROWTH_PREDICTION_MIN_CONF and fresh:
            return {"stage": stage, "source": "component2",
                    "confidence": round(conf * 100, 1),
                    "ageDays": round(age_d, 1) if age_d is not None else None,
                    "needsAttention": False,
                    "message": (f"Growth stage detected automatically by the camera "
                                f"({stage}, {round(conf*100)}% confidence).")}
        # present but not usable — fall through, but say why
        reason = ("confidence too low" if conf < GROWTH_PREDICTION_MIN_CONF
                  else f"prediction is {round(age_d)} days old")
    else:
        reason = None

    # 2 ── the farmer's manual setting
    manual = meta.get("growthStage")
    if manual in VALID_STAGES:
        set_h = _hours_since(meta.get("growthStageSetAt"), real_now)
        set_d = (set_h / 24.0) if set_h is not None else None
        stale = set_d is not None and set_d > GROWTH_MANUAL_STALE_DAYS
        msg = f"Growth stage set by you: {manual}."
        if reason:
            msg = f"Camera prediction unusable ({reason}) — using your setting: {manual}."
        if stale:
            msg += f" You set it {round(set_d)} days ago — please check it is still correct."
        return {"stage": manual, "source": "manual", "confidence": None,
                "ageDays": round(set_d, 1) if set_d is not None else None,
                "needsAttention": bool(stale),
                "message": msg}

    # 3 ── nothing set anywhere: guess from the season and ASK THE FARMER
    guess = _seasonal_stage(month)
    return {"stage": guess, "source": "seasonal", "confidence": None, "ageDays": None,
            "needsAttention": True,
            "message": ("No growth stage available — the camera has not reported one and "
                        f"you have not set it. Using a seasonal estimate ({guess}), which "
                        "may be wrong. Please set the growth stage for this section.")}


def _hhmm(hour_float: float) -> str:
    h = int(hour_float)
    m = int(round((hour_float - h) * 60))
    if m == 60:
        h, m = h + 1, 0
    return f"{h:02d}:{m:02d}"


# ═══════════════════════ ML: today's watering plan ════════════════════════════

def _plan_section(house_id: str, section_id: str, section: dict,
                  now: Optional[datetime] = None) -> dict:
    """`now` lets the automation engine keep one pass internally consistent.

    Without it the plan was stamped with the real server date while the engine
    pass was evaluating a simulated one, so `_due_sessions` compared two
    different days and the watering never fired. Defaults to real time, so
    production behaviour is unchanged."""
    latest = _clean((section or {}).get("latest") or {})
    meta   = (section or {}).get("meta") or {}

    gs = _resolve_growth_stage(section)
    stage = gs["stage"]
    stage_enc = _water["growth_stage_map"].get(stage, 0)
    exposure = float(meta.get("lightExposure", 0.8))
    # The farm's clock, not the server's: the model's predicted hour, the plan's
    # date and the season month are all in the plants' local time.
    now = now or farm_now()

    # one history fetch feeds both the daily summary and the dawn lookup
    hist = _recent_history(house_id, section_id)
    y = _yesterday_stats(hist, latest)
    # the model decides at dawn — use the dawn reading, not whatever time it is now
    dawn = _dawn_reading(hist, latest)
    dawn_vpd = vpd_kpa(dawn["temperature"], dawn["humidity"])

    feats = np.array([[
        dawn["temperature"], dawn["humidity"], dawn["light"], dawn_vpd,
        y["peak_temp"], y["mean_humidity"], y["mean_vpd"],
        float(now.month), float(stage_enc), exposure,
    ]])
    Xs = _water["scaler"].transform(feats)

    hour   = float(_water["model_hour"].predict(Xs)[0])
    dur    = int(round(float(_water["model_duration"].predict(Xs)[0])))
    second = bool(_water["model_second"].predict(Xs)[0])
    second_conf = float(_water["model_second"].predict_proba(Xs)[0].max())

    hour = max(6.0, min(9.0, hour))
    dur  = max(30, min(120, dur))

    plan = {
        "date": now.strftime("%Y-%m-%d"),
        "waterHour": round(hour, 2),
        "waterTime": _hhmm(hour),
        "durationSec": dur,
        "secondSession": second,
        "secondTime": "17:00" if second else None,
        "secondDurationSec": int(dur * 0.7) if second else 0,
        "secondConfidence": round(second_conf * 100, 1),
        "reason": (
            f"Extreme heat detected (yesterday peaked {y['peak_temp']}°C, "
            f"VPD {y['mean_vpd']}) — a second evening session is allowed."
            if second else
            f"Normal conditions — one watering is enough. The tray handles "
            f"midday humidity (VPD {dawn_vpd})."
        ),
        "inputs": {"dawnTemp": dawn["temperature"], "dawnHumidity": dawn["humidity"],
                   "dawnLight": dawn["light"], "dawnVpd": dawn_vpd,
                   "yesterdayPeakTemp": y["peak_temp"], "yesterdayMeanVpd": y["mean_vpd"]},
        "generatedAt": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
    }

    # Predict how the rest of today will go, so the tray can act BEFORE the heat
    # instead of chasing it. Stored per section: each microclimate has its own
    # curve, which is the whole point of the zone survey.
    try:
        from app.api.routes import forecast as _fx
        fc = _fx.predict_day(dawn, now.month, exposure, y["peak_temp"])
        if fc:
            _fb_put(f"/farm/houses/{house_id}/sections/{section_id}/forecast.json", fc)
            plan["forecast"] = {"peakTemp": fc["peakTemp"], "peakHour": fc["peakHour"],
                                "minHumidity": fc["minHumidity"], "hotDay": fc["hotDay"]}
    except Exception as e:                       # a forecast failure must never
        print(f"[WARN] forecast skipped for {house_id}-{section_id}: {e}")  # block watering

    _fb_put(f"/farm/houses/{house_id}/sections/{section_id}/plan.json", plan)

    # Compute and STORE the fertilizer decision alongside the plan, so every
    # screen can show it. (It used to be returned only from /plan, which meant
    # fertilization was invisible unless the user tapped that one button.)
    fert = _fert_decision(section)
    existing = (section or {}).get("fertilizer") or {}
    # Nulls from the decision must not clobber what is already recorded. The
    # decision is computed from a snapshot taken BEFORE this pass, so a feed
    # recorded moments ago reads back as None here and would erase itself.
    merged = {**existing, **{k: v for k, v in fert.items() if v is not None},
              "updatedAt": plan["generatedAt"]}
    _fb_put(f"/farm/houses/{house_id}/sections/{section_id}/fertilizer.json", merged)
    plan["fertilizer"] = fert
    return plan


# ═══════════════════════ ML: tray humidity control ════════════════════════════

def _device_now_ms(section: dict) -> float:
    """'Now' according to the DEVICE clock (the latest reading's timestamp).

    All time reasoning uses device time, not server time, so that:
      * a device with clock drift stays self-consistent, and
      * the farm simulator (which runs many times faster than real time)
        produces correct cooldown behaviour.
    Falls back to the server clock if the device has never reported.
    """
    ts = ((section or {}).get("latest") or {}).get("timestamp")
    try:
        return float(ts)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc).timestamp() * 1000.0


def _hours_since(ts_ms, now_ms: Optional[float] = None) -> Optional[float]:
    """Hours between an epoch-ms timestamp and 'now' (device clock)."""
    try:
        ref = now_ms if now_ms is not None else datetime.now(timezone.utc).timestamp() * 1000.0
        return max(0.0, (ref - float(ts_ms)) / 3600000.0)
    except (TypeError, ValueError):
        return None


def _run_per_section(houses: dict, fn) -> dict:
    """Apply `fn(house_id, section_id, section)` to every reporting section.

    Runs them concurrently. Each call is dominated by Firebase round-trips
    (~0.7 s each, several per section), so doing four sections in sequence took
    ~19 s for /plan-all — long enough that the app's buttons looked broken. The
    work itself is independent per section, so a small thread pool collapses
    that to roughly the time of one section.
    """
    jobs = [(hid, sid, s)
            for hid, h in (houses or {}).items() if isinstance(h, dict)
            for sid, s in ((h.get("sections") or {}).items())
            if isinstance(s, dict) and s.get("latest")]
    if not jobs:
        return {}

    results: Dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
        futures = {pool.submit(fn, hid, sid, s): f"{hid}-{sid}" for hid, sid, s in jobs}
        for fut in as_completed(futures):
            key = futures[fut]
            try:
                results[key] = fut.result()
            except Exception as e:
                # one bad section must not take the whole farm down
                results[key] = {"error": str(e), "fillSeconds": 0}
    return dict(sorted(results.items()))


def _tray_decision(house_id: str, section_id: str, section: dict,
                   now: Optional[datetime] = None) -> dict:
    latest = _clean((section or {}).get("latest") or {})
    # The tray model takes hour-of-day as a feature and was trained on local
    # hours, so this must be the farm's clock, not the server's.
    now  = now or farm_now()
    hour = now.hour
    v = vpd_kpa(latest["temperature"], latest["humidity"])

    Xs = _tray["scaler"].transform(np.array([[
        latest["temperature"], latest["humidity"], latest["light"], v, float(hour)]]))
    secs = int(round(float(_tray["model"].predict(Xs)[0])))
    secs = max(0, min(60, secs))
    model_secs = secs          # the model's own call, kept for the UI and report

    lo, hi = _tray["rh_target_low"], _tray["rh_target_high"]
    rh = latest["humidity"]

    prev    = (section or {}).get("tray") or {}
    dev_now = _device_now_ms(section)
    since   = _hours_since(prev.get("lastFillTs"), dev_now)

    # ── THE MODEL DECIDES WHETHER TO FILL, NOT A THRESHOLD ───────────────────
    # The regressor was trained on a target that already returns 0 when no fill
    # is needed (above the band, or inside it on a mild day) and a positive dose
    # otherwise. So `secs > 0` IS the model's fill / no-fill decision, made from
    # temperature, humidity, light, VPD and hour together.
    #
    # This used to be overridden by hard humidity thresholds, which threw that
    # decision away and reduced the model to a dose calculator. A fixed 60%
    # cutoff also creates a cliff: 59.9% triggered a full fill and 60.1% did
    # nothing, even though a hot bright morning at 62% needs water more than a
    # cool evening at 58%. The model blends those factors; a threshold cannot.
    #
    # The bands survive only to choose the WORDS shown to the farmer.
    if secs == 0:
        status = "ok"
        if rh >= hi:
            msg = f"Humidity {rh}% is above target, no fill needed."
        elif rh >= lo:
            msg = f"Humidity {rh}% is inside the {lo:.0f}-{hi:.0f}% band, no fill needed."
        else:
            msg = (f"Humidity {rh}% is below {lo:.0f}%, but it is mild enough that the "
                   f"model does not call for a fill yet.")
    elif rh >= lo:
        status = "topup"
        msg = (f"Humidity {rh}% is inside the band, but it is hot and bright, so a "
               f"small {secs}s top-up keeps it there.")
    else:
        status = "fill"
        msg = f"Humidity {rh}% is below {lo:.0f}%, open the valve {secs}s to raise it."

    # ── ANTICIPATORY TOP-UP ──────────────────────────────────────────────────
    # If nothing is needed right now but the forecast says this section is
    # heading for a hot, dry afternoon, top the tray up while there is still
    # time for the water to evaporate. Used only to ACT EARLIER, never to skip
    # a fill: the model's recall is ~0.68, so a miss must cost nothing.
    prefill = None
    if secs == 0:
        try:
            from app.api.routes import forecast as _fx
            fc = (section or {}).get("forecast") or {}
            if fc.get("date") == now.strftime("%Y-%m-%d"):
                advice = _fx.prefill_advice(fc, hour + now.minute / 60.0, rh)
                if advice:
                    prefill = advice
                    secs = max(6, min(15, int(round((hi - rh) * 0.6))))
                    status = "prefill"
                    msg = advice["reason"]
        except Exception as e:
            print(f"[WARN] prefill check skipped: {e}")

    # SAFETY NET, not a decision. The model already returns 0 above the band, so
    # this only catches a bad prediction (retrained model, corrupt pickle).
    # Overfilling a 3 cm tray into already damp air risks mould on the roots,
    # so this one stays hard.
    if secs > 0 and rh >= hi:
        msg = (f"Model asked for {secs}s but humidity is {rh}%, at or above the "
               f"{hi:.0f}% ceiling. Fill blocked to avoid over-humidifying.")
        secs, status = 0, "ok"

    # ── COOLDOWN GUARD ───────────────────────────────────────────────────────
    # A 3 cm tray cannot physically dry out within COOLDOWN_HOURS. So if humidity
    # is still low that soon after a fill, the tray is NOT empty — the dry air is
    # (open-sided shade house, hot afternoon). Refilling would only overflow the
    # 3 cm notch and waste water. Instead we hold off and flag that the tray has
    # reached its limit, which is what justifies an extra watering session.
    cooling = False
    if status in ("fill", "topup") and since is not None and since < COOLDOWN_HOURS:
        cooling  = True
        wait     = round(COOLDOWN_HOURS - since, 1)
        at_limit = status == "fill"
        status, secs = "cooldown", 0
        msg = (f"Tray was filled {since:.1f} h ago, so it still has water. "
               f"Humidity is {rh}% because the air is dry today, not because the tray is empty. "
               f"Next fill allowed in {wait} h.")
        if at_limit:
            msg += " The tray is at its limit — extra watering may be needed."

    # ── AUTO MODE: actually issue the command ────────────────────────────────
    # Deciding is not enough — in auto mode the system must act without the
    # farmer pressing anything. (Found by the farm simulator: trays were being
    # correctly diagnosed as empty but never refilled.)
    ctrl      = (section or {}).get("control") or {}
    # The farm switch and the per-section override, not the legacy `mode` key.
    # trayEnabled is a separate per-section opt-out and still applies on top.
    auto      = section_acts_alone(section) and ctrl.get("trayEnabled", True)
    commanded = False
    # Acts on ANY dose the model asks for, not just a full "fill". Top-ups were
    # previously computed and then silently dropped, so the small maintenance
    # doses the model is best at never actually reached the valve.
    if auto and status in ("fill", "topup", "prefill") and secs > 0:
        cmd = {"requested": True, "fillSeconds": secs, "triggeredBy": "auto",
               "timestamp": now.strftime("%Y-%m-%d %H:%M:%S UTC")}
        _fb_put(f"/farm/houses/{house_id}/sections/{section_id}/control/trayCommand.json", cmd)
        node_cmd = _issue_node_command(house_id, section_id, "tray", secs)
        _log_event(house_id, section_id, section,
                   action="tray", durationSec=secs, withFertilizer=False,
                   by="auto", commandId=(node_cmd or {}).get("id"),
                   confirmed=False)
        commanded = True
        msg += " Auto mode: filling now."

    out = {"fillSeconds": secs, "status": status, "message": msg,
           # what the model asked for before any safety override, so the app and
           # the report can show the model's own decision rather than the result
           "modelSeconds": model_secs,
           "prefill": prefill,
           "decidedBy": "model" if secs == model_secs else "safety-override",
           "autoCommanded": commanded,
           "lastFillTs": (dev_now if commanded else prev.get("lastFillTs")),
           "humidity": rh, "temperature": latest["temperature"],
           "vpd": v, "targetLow": lo, "targetHigh": hi,
           "cooldownHours": COOLDOWN_HOURS,
           "hoursSinceFill": round(since, 1) if since is not None else None,
           "hoursUntilNextFill": round(max(0.0, COOLDOWN_HOURS - since), 1) if cooling else 0,
           "trayAtLimit": bool(cooling and rh < lo),
           "checkedAt": now.strftime("%Y-%m-%d %H:%M:%S UTC")}
    _fb_put(f"/farm/houses/{house_id}/sections/{section_id}/tray.json", out)
    return out


# ═══════════════════════ ML: fertilizer ═══════════════════════════════════════

def _days_since_fertilized(section: dict) -> float:
    """How long since this section was actually fed, in days.

    Derived from a TIMESTAMP, not from a stored number.

    The previous version read a plain `daysSince` integer that nothing ever
    wrote. Three faults compounded:
      * a number cannot advance with time, so it never grew;
      * nothing reset it after a feed, so it never shrank;
      * its default (7) equalled the Active-stage interval (7), so any section
        created through the app was born "due" and stayed due forever.
    The visible result was every single watering claiming to mix in plant food,
    and a "Fertilizer due" alert that could never be cleared.
    """
    fert = (section or {}).get("fertilizer") or {}
    now_ms = _device_now_ms(section)

    ts = fert.get("lastFertilizedTs")
    if ts:
        hrs = _hours_since(ts, now_ms)
        if hrs is not None:
            return round(hrs / 24.0, 2)

    # Never fed through the system. Fall back to whatever was seeded, and treat
    # an absent value as "due now" rather than inventing a history - a section
    # whose feeding is unknown SHOULD be flagged once, and recording the first
    # feed then starts the clock properly.
    try:
        return float(fert.get("daysSince"))
    except (TypeError, ValueError):
        return float(FERT_UNKNOWN_DAYS)


def _record_fertilized(house_id: str, section_id: str, section: dict) -> None:
    """Start the clock. Called when a watering that CARRIES fertilizer is issued.

    Recorded at issue rather than at the node's acknowledgement: an ack can be
    lost, and feeding twice because a confirmation went missing is worse than
    the small risk of counting a feed the pump never delivered. The farmer can
    correct it from the section screen.
    """
    now_ms = _device_now_ms(section)
    _fb_put(f"/farm/houses/{house_id}/sections/{section_id}/fertilizer/lastFertilizedTs.json",
            now_ms)
    # to_farm_time takes epoch MILLISECONDS, not a datetime. Passing a datetime
    # raised inside the request and turned every fertilised watering into a 500,
    # after the timestamp above had already been written.
    _fb_put(f"/farm/houses/{house_id}/sections/{section_id}/fertilizer/lastFertilizedAt.json",
            to_farm_time(now_ms).strftime("%Y-%m-%d %H:%M"))


# How many events are kept per section. Events are written a handful of times a
# day, so this is roughly a month of history - enough to answer "when was this
# last watered and fed" without the document growing without bound.
EVENT_KEEP = 60


def _log_event(house_id: str, section_id: str, section: dict, **fields) -> Optional[str]:
    """Record something that MOVED WATER, so it can be shown as history.

    The only record before this was `watering/log/{day}-{tag}`, holding `{at,
    by}`. It was written by the automatic path only, carried no duration and no
    fertilizer detail, and was keyed by day so at most two entries survived per
    day. There was no way to answer "when was this section last fed", which is
    the question the fertilizer schedule depends on.

    Keyed by epoch milliseconds so the keys sort chronologically.
    """
    now_ms = int(_device_now_ms(section))
    ev = {"at": now_ms,
          "atLocal": to_farm_time(now_ms).strftime("%Y-%m-%d %H:%M"),
          **fields}
    key = str(now_ms)
    # OUTSIDE the section subtree, on its own branch.
    #
    # /farm/houses.json is the engine's hot path - fetched every 60 seconds, so
    # 1,440 times a day. Anything stored inside a section is paid for on every
    # one of those fetches. At 60 events per section this log would have added
    # ~84 KB to a 23 KB document and taken the engine alone from 29 MB/day to
    # about 147 MB. History was moved out of the section subtree for exactly
    # this reason once already.
    base = f"/farm/events/{house_id}/{section_id}"
    if not _fb_put(f"{base}/{key}.json", ev):
        return None

    # Prune oldest beyond EVENT_KEEP. `shallow=true` returns keys only, so this
    # costs a few hundred bytes rather than the whole log.
    try:
        keys = _fb_get(f"{base}.json?shallow=true") or {}
        if len(keys) > EVENT_KEEP:
            for old_key in sorted(keys, key=lambda k: int(k) if k.isdigit() else 0)[:len(keys) - EVENT_KEEP]:
                _fb_delete(f"{base}/{old_key}.json")
    except Exception:
        pass          # a failed prune must never fail the watering
    return key


def _fert_decision(section: dict) -> dict:
    latest = _clean((section or {}).get("latest") or {})
    # Growth stage decides WHICH fertilizer — take it from Component 2 if it has
    # reported, else the farmer's setting, else a seasonal guess (and say so).
    gs     = _resolve_growth_stage(section)
    stage  = gs["stage"]
    days   = _days_since_fertilized(section)
    now    = datetime.now(timezone.utc)

    # The farmer can switch plant food off entirely (e.g. they feed by hand).
    # Checked before the model so nothing is ever dosed behind their back.
    if ((section or {}).get("control") or {}).get("fertEnabled") is False:
        return {"due": False, "npkType": "None", "strength": 0.0,
                "daysSinceFertilize": days, "growthStage": stage,
                "growthSource": gs["source"], "growthMessage": gs["message"],
                "growthNeedsAttention": gs["needsAttention"], "fertEnabled": False,
                "message": "Automatic plant food is switched off for this section.",
                "guidance": "Turn it back on from My Farm when you want the system "
                            "to feed the plants again."}

    # HARD SAFETY RULE (never left to the model): dormant Vanda are not fed.
    # A resting plant cannot use the nutrients; salts accumulate in the velamen
    # and burn the roots.
    if stage == "Dormant":
        return {"due": False, "npkType": "None", "strength": 0.0,
                "daysSinceFertilize": days, "growthStage": stage,
                "growthSource": gs["source"], "growthMessage": gs["message"],
                "growthNeedsAttention": gs["needsAttention"],
                "message": "Plant is dormant — no fertilizer until growth resumes.",
                "guidance": ("Feeding a resting Vanda burns the roots: salts build up "
                             "in the velamen because the plant is not taking them up.")}

    Xs = _fert["scaler"].transform(np.array([[
        days, float(_fert["growth_stage_map"].get(stage, 0)), float(now.month),
        latest["temperature"], latest["humidity"]]]))

    due = bool(_fert["model_due"].predict(Xs)[0])
    npk = _fert["npk_encoder"].inverse_transform(_fert["model_npk"].predict(Xs))[0]
    strength = 0.5 if now.month not in (11, 12, 1, 2) and stage != "Dormant" else 0.25

    # What this stage takes, regardless of whether a feed is due right now. The
    # history needs it: a farmer who feeds early still mixed something, and
    # recording "None" against a feed that happened is simply wrong.
    npk_for_stage = npk
    if not due:
        npk = "None"
        nxt = _fert["schedule_days"].get(stage, 7) - days
        msg = f"Not due — next feed in about {max(0, int(nxt))} day(s)."
    else:
        msg = (f"Due now: {npk} at {int(strength*100)}% strength, "
               f"mixed into the next watering (never on dry roots).")

    fert_rec = (section or {}).get("fertilizer") or {}
    return {"due": due, "npkType": npk, "strength": strength,
            "daysSinceFertilize": days,
            # None until the first recorded feed, which the app shows as
            # "not recorded yet" rather than inventing a date.
            "npkForStage": npk_for_stage,
            "lastFertilizedAt": fert_rec.get("lastFertilizedAt"),
            "everFertilized": bool(fert_rec.get("lastFertilizedTs")),
            "intervalDays": int(_fert["schedule_days"].get(stage, 7)),
            "growthStage": stage,
            "growthSource": gs["source"], "growthMessage": gs["message"],
            "growthNeedsAttention": gs["needsAttention"],
            "growthConfidence": gs["confidence"],
            "message": msg,
            "guidance": ("Vanda are heavy feeders: weekly in the growing season, "
                         "every 2-3 weeks when dormant, always at 1/4-1/2 strength "
                         "and always delivered with water.")}


# ═══════════════════════ Setup / hierarchy ════════════════════════════════════

class SectionIn(BaseModel):
    id: Optional[str] = None
    name: str
    label: Optional[str] = ""                 # "bright edge", "shaded corner"
    plantCount: int = 0
    growthStage: str = "Active"
    lightExposure: float = Field(0.8, ge=0.0, le=1.0)


class HouseIn(BaseModel):
    id: Optional[str] = None
    name: str
    type: str = "shade-net"
    plantCount: int = 0
    sections: List[SectionIn] = []


class FarmSetup(BaseModel):
    # Neither of these is asked for any more. The setup wizard used to demand a
    # farm name and an owner name before a farmer could do anything, and neither
    # earned its keep: ownerName was written here and read by NOTHING, and
    # farmName is only a screen title that already falls back to "My Farm"
    # everywhere it is shown. Renaming the farm is still available on the
    # dashboard for anyone who wants one.
    farmName: str = "My Farm"
    houses: List[HouseIn] = []


@router.post("/setup")
async def setup_farm(cfg: FarmSetup):
    """First-time setup wizard: farm -> houses -> sections."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    _fb_put("/farm/meta.json", {"farmName": (cfg.farmName or "My Farm").strip() or "My Farm",
                                "createdAt": now, "version": 2})
    made = []
    for hi, h in enumerate(cfg.houses, 1):
        hid = h.id or f"H{hi}"
        _fb_put(f"/farm/houses/{hid}/meta.json", {
            "name": h.name, "type": h.type, "plantCount": h.plantCount,
            "sectionCount": len(h.sections), "createdAt": now})
        for si, s in enumerate(h.sections, 1):
            sid = s.id or f"S{si}"
            _fb_put(f"/farm/houses/{hid}/sections/{sid}/meta.json", {
                "name": s.name, "label": s.label, "plantCount": s.plantCount,
                "growthStage": s.growthStage, "lightExposure": s.lightExposure,
                "deviceId": f"{hid}-{sid}", "createdAt": now})
            _fb_put(f"/farm/houses/{hid}/sections/{sid}/control.json",
                    {"mode": "auto", "trayEnabled": True})
        made.append({"houseId": hid, "sections": len(h.sections)})
    return {"status": "success", "farm": cfg.farmName, "houses": made,
            "note": "Flash each device with its deviceId, e.g. H1-S1."}


@router.post("/houses")
async def add_house(h: HouseIn):
    """Add a house later (farmer can extend the farm any time)."""
    existing = _fb_get("/farm/houses.json") or {}
    hid = h.id or f"H{len(existing) + 1}"
    if hid in existing:
        raise HTTPException(409, f"House '{hid}' already exists")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    _fb_put(f"/farm/houses/{hid}/meta.json", {
        "name": h.name, "type": h.type, "plantCount": h.plantCount,
        "sectionCount": len(h.sections), "createdAt": now})
    for si, s in enumerate(h.sections, 1):
        sid = s.id or f"S{si}"
        _fb_put(f"/farm/houses/{hid}/sections/{sid}/meta.json", {
            "name": s.name, "label": s.label, "plantCount": s.plantCount,
            "growthStage": s.growthStage, "lightExposure": s.lightExposure,
            "deviceId": f"{hid}-{sid}", "createdAt": now})
        _fb_put(f"/farm/houses/{hid}/sections/{sid}/control.json",
                {"mode": "auto", "trayEnabled": True})
    return {"status": "success", "houseId": hid}


@router.post("/houses/{house_id}/sections")
async def add_section(house_id: str, s: SectionIn):
    """Add a section to an existing house."""
    house = _fb_get(f"/farm/houses/{house_id}/meta.json")
    if not house:
        raise HTTPException(404, f"House '{house_id}' not found")
    existing = _fb_get(f"/farm/houses/{house_id}/sections.json") or {}
    sid = s.id or f"S{len(existing) + 1}"
    if sid in existing:
        raise HTTPException(409, f"Section '{sid}' already exists in {house_id}")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    _fb_put(f"/farm/houses/{house_id}/sections/{sid}/meta.json", {
        "name": s.name, "label": s.label, "plantCount": s.plantCount,
        "growthStage": s.growthStage, "lightExposure": s.lightExposure,
        "deviceId": f"{house_id}-{sid}", "createdAt": now})
    _fb_put(f"/farm/houses/{house_id}/sections/{sid}/control.json",
            {"mode": "auto", "trayEnabled": True})
    house["sectionCount"] = len(existing) + 1
    _fb_put(f"/farm/houses/{house_id}/meta.json", house)
    return {"status": "success", "houseId": house_id, "sectionId": sid,
            "deviceId": f"{house_id}-{sid}"}


@router.put("/houses/{house_id}/sections/{section_id}")
async def update_section(house_id: str, section_id: str, s: SectionIn):
    meta = _fb_get(f"/farm/houses/{house_id}/sections/{section_id}/meta.json")
    if not meta:
        raise HTTPException(404, "Section not found")
    if s.growthStage != meta.get("growthStage"):
        meta["growthStageSetAt"] = int(datetime.now(timezone.utc).timestamp() * 1000)
    meta.update({"name": s.name, "label": s.label, "plantCount": s.plantCount,
                 "growthStage": s.growthStage, "lightExposure": s.lightExposure})
    _fb_put(f"/farm/houses/{house_id}/sections/{section_id}/meta.json", meta)
    return {"status": "success", "meta": meta}


# ═══════════════════════ Read endpoints ═══════════════════════════════════════

@router.get("/overview")
async def overview():
    """Everything the dashboard needs: every house, every section, current status."""
    farm   = _fb_get("/farm/meta.json") or {}
    houses = _fb_get("/farm/houses.json") or {}
    out, alerts = [], 0

    # Which node reports for which section, and how often it is meant to. A
    # section is only "late" relative to its OWN node's interval, and a section
    # with no node at all must say so rather than showing an empty reading as if
    # the hardware were merely quiet. 0.2 KB, fetched once for the whole farm.
    devices = _fb_get("/devices.json") or {}
    by_section = {}
    for mac, rec in (devices or {}).items():
        assigned = (rec or {}).get("assignedTo")
        if assigned:
            by_section[assigned] = {"mac": mac,
                                    "shortId": mac[-4:],
                                    "readIntervalMs": (rec or {}).get("readIntervalMs")}

    # One clock for the whole farm, so sections are aged consistently.
    farm_now = _farm_now_ms(houses)
    stale_sections = 0

    for hid, h in sorted(houses.items()):
        if not isinstance(h, dict):
            continue
        secs = []
        for sid, s in sorted((h.get("sections") or {}).items()):
            if not isinstance(s, dict):
                continue
            node   = by_section.get(f"{hid}/{sid}")
            latest = _display(s.get("latest") or {})
            plan   = s.get("plan") or {}
            tray   = s.get("tray") or {}
            fresh  = _freshness(s, farm_now, (node or {}).get("readIntervalMs"))

            # A section with no node is not a section whose node is quiet. The
            # app used to show both identically, so a zone with no hardware
            # displayed 28 C and 70 % - the model's fallback defaults - and 70 %
            # sits in the ideal band, so it even showed a green "GOOD".
            if node is None and fresh["state"] == "never":
                fresh = {"state": "nonode", "ageMinutes": None,
                         "label": "No sensor node", "trusted": False,
                         "message": "No sensor node is linked to this section, so "
                                    "there are no readings. Link one from Add Section."}

            # "online" used to mean "has ever reported", so a node that died days
            # ago still read as online. It now means "reported recently enough".
            online = fresh["state"] in ("live", "delayed")
            if not fresh["trusted"]:
                stale_sections += 1
                alerts += 1
            needs  = tray.get("status") == "fill"
            if needs:
                alerts += 1
            fert = s.get("fertilizer") or {}
            if fert.get("due"):
                alerts += 1
            secs.append({
                "sectionId": sid,
                "meta": s.get("meta", {}),
                "online": online,
                "freshness": fresh,
                # vpd only when both inputs are real. Computing it from the
                # model's fallback defaults produced a confident 0.611 kPa for a
                # section that had never reported anything.
                "latest": {**latest,
                           "vpd": (vpd_kpa(latest["temperature"], latest["humidity"])
                                   if latest.get("temperature") is not None
                                   and latest.get("humidity") is not None else None)},
                "node": node,
                "plan": plan,
                "tray": tray,
                "fertilizer": fert,
                "control": s.get("control", {}),
            })
        out.append({"houseId": hid, "meta": h.get("meta", {}), "sections": secs})

    return {"status": "success", "farm": farm, "houses": out,
            "houseCount": len(out),
            "sectionCount": sum(len(x["sections"]) for x in out),
            "staleSections": stale_sections,
            "alerts": alerts}


@router.get("/houses/{house_id}")
async def get_house(house_id: str):
    """One house, with each section aged the same way /overview ages it.

    This used to return the raw Firebase document, so the section screen had no
    idea how old a reading was and displayed a number from a dead node exactly
    like a number from a live one. It also let -999 - the firmware's "this
    sensor failed" marker - through to the screen as though it were a
    measurement.
    """
    h = _fb_get(f"/farm/houses/{house_id}.json")
    if not h:
        raise HTTPException(404, f"House '{house_id}' not found")

    devices = _fb_get("/devices.json") or {}
    by_section = {}
    for mac, rec in (devices or {}).items():
        assigned = (rec or {}).get("assignedTo")
        if assigned:
            by_section[assigned] = {"mac": mac,
                                    "shortId": mac[-4:],
                                    "readIntervalMs": (rec or {}).get("readIntervalMs")}

    farm_now = _farm_now_ms({house_id: h})
    for sid, sec in ((h.get("sections") or {})).items():
        if not isinstance(sec, dict):
            continue
        node = by_section.get(f"{house_id}/{sid}")
        fresh = _freshness(sec, farm_now, (node or {}).get("readIntervalMs"))
        if node is None and fresh["state"] == "never":
            fresh = {"state": "nonode", "ageMinutes": None,
                     "label": "No sensor node", "trusted": False,
                     "message": "No sensor node is linked to this section, so there "
                                "are no readings. Link one from Add Section."}
        sec["freshness"] = fresh
        sec["node"] = node
        sec["latest"] = _display(sec.get("latest") or {})

    return {"status": "success", "houseId": house_id, "house": h}


# ═══════════════════════ ML endpoints ═════════════════════════════════════════

@router.post("/houses/{house_id}/sections/{section_id}/plan")
async def plan_section(house_id: str, section_id: str):
    """Today's watering plan for one section: time + duration + 2nd session."""
    if not _ready():
        raise HTTPException(503, "v2 models not loaded — run train_models_v2.py")
    s = _fb_get(f"/farm/houses/{house_id}/sections/{section_id}.json")
    if not s:
        raise HTTPException(404, "Section not found")
    plan = _plan_section(house_id, section_id, s)
    fert = _fert_decision(s)
    return {"status": "success", "houseId": house_id, "sectionId": section_id,
            "plan": plan, "fertilizer": fert}


@router.post("/plan-all")
async def plan_all():
    """Generate today's plan for every section (run once each morning)."""
    if not _ready():
        raise HTTPException(503, "v2 models not loaded")
    houses = _fb_get("/farm/houses.json") or {}
    results = _run_per_section(houses, _plan_section)
    return {"status": "success", "sectionsPlanned": len(results), "plans": results}


@router.post("/houses/{house_id}/sections/{section_id}/tray-check")
async def tray_check(house_id: str, section_id: str):
    """Should this section's humidity tray be topped up right now?"""
    if not _ready():
        raise HTTPException(503, "v2 models not loaded")
    s = _fb_get(f"/farm/houses/{house_id}/sections/{section_id}.json")
    if not s:
        raise HTTPException(404, "Section not found")
    return {"status": "success", "houseId": house_id, "sectionId": section_id,
            "tray": _tray_decision(house_id, section_id, s)}


@router.post("/tray-check-all")
async def tray_check_all():
    """Humidity check for every section (run every few minutes)."""
    if not _ready():
        raise HTTPException(503, "v2 models not loaded")
    houses = _fb_get("/farm/houses.json") or {}
    results = _run_per_section(houses, _tray_decision)
    filling = sum(1 for r in results.values() if r["fillSeconds"] > 0)
    return {"status": "success", "sectionsChecked": len(results),
            "sectionsFilling": filling, "results": results}


# ═══════════════════════ Control endpoints ════════════════════════════════════

class WaterCmd(BaseModel):
    durationSec: int = 45
    withFertilizer: bool = False
    triggeredBy: str = "user"


@router.post("/houses/{house_id}/sections/{section_id}/water")
async def water_section(house_id: str, section_id: str, cmd: WaterCmd):
    """Manual watering. Fertilizer, if requested, rides along in the same water."""
    s = _fb_get(f"/farm/houses/{house_id}/sections/{section_id}.json")
    if not s:
        raise HTTPException(404, "Section not found")
    command = {"requested": True,
               "durationSec": max(10, min(cmd.durationSec, RELAY_MAX_SEC)),
               "withFertilizer": cmd.withFertilizer,
               "triggeredBy": cmd.triggeredBy,
               "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}
    _fb_put(f"/farm/houses/{house_id}/sections/{section_id}/control/waterCommand.json", command)
    # ...and the document the real firmware actually polls. Without this the
    # button only ever moved data inside the server.
    node_cmd = _issue_node_command(house_id, section_id, "water",
                                   command["durationSec"],
                                   withFertilizer=command["withFertilizer"])
    # Start the fertilizer clock. Without this the counter never moves, so every
    # subsequent watering claims to mix in plant food and the "due" alert can
    # never be cleared.
    fert_now = _fert_decision(s) if command["withFertilizer"] else None
    if command["withFertilizer"]:
        _record_fertilized(house_id, section_id, s)
    _log_event(house_id, section_id, s,
               action="water",
               durationSec=command["durationSec"],
               withFertilizer=bool(command["withFertilizer"]),
               npkType=((fert_now or {}).get("npkForStage")
                        if command["withFertilizer"] else None),
               strength=(fert_now or {}).get("strength") if command["withFertilizer"] else None,
               by=cmd.triggeredBy or "user",
               commandId=(node_cmd or {}).get("id"),
               confirmed=False)
    return {"status": "success", "command": command,
            "nodeCommand": node_cmd,
            "lastAck": _last_ack(s),
            "message": (f"Watering for {command['durationSec']}s. The node picks "
                        "this up within about 15 seconds.")}


@router.get("/houses/{house_id}/sections/{section_id}/events")
def section_events(house_id: str, section_id: str, limit: int = 40) -> dict:
    """Everything that moved water in this section, newest first.

    Includes whether the node confirmed it. A command the server accepted and a
    pour the hardware actually ran are different claims, and the history has to
    show which one it is holding.
    """
    raw = _fb_get(f"/farm/events/{house_id}/{section_id}.json") or {}
    items = []
    for k, v in raw.items():
        if isinstance(v, dict):
            items.append({"id": k, **v})
    items.sort(key=lambda x: x.get("at") or 0, reverse=True)

    waters = [x for x in items if x.get("action") == "water"]
    feeds  = [x for x in waters if x.get("withFertilizer")]
    return {"status": "success",
            "events": items[:max(1, min(limit, 200))],
            "counts": {"total": len(items),
                       "waterings": len(waters),
                       "feeds": len(feeds)},
            "lastWatered": waters[0]["atLocal"] if waters else None,
            "lastFed": feeds[0]["atLocal"] if feeds else None}


@router.get("/houses/{house_id}/sections/{section_id}/command-status")
def command_status(house_id: str, section_id: str,
                   id: Optional[str] = None) -> dict:
    """Has the node actually carried out the last command sent to this section?

    The run screen polls this so it can say "node confirmed" instead of only
    "sent". Those are genuinely different claims: the server writing a command
    proves nothing about a pump, and for months this project had a command path
    that reached no hardware at all while every screen reported success.

    Confirmation requires the ack's id to MATCH the pending command. The node
    matches by id and never deletes the document, so a stale ack left over from
    a previous command would otherwise read as this one having succeeded.
    """
    base = f"/farm/houses/{house_id}/sections/{section_id}"
    cmd = _fb_get(f"{base}/command.json") or {}
    ack = _fb_get(f"{base}/commandAck.json") or {}

    cid = cmd.get("id")

    # Which command is the caller asking about?
    #
    # `id` matters because Stop REPLACES the command document. Keying off
    # whatever happens to be in there now means that the moment a farmer presses
    # Stop, the run they were watching becomes unfindable: the app polled
    # forever, the countdown kept ticking and the Stop button stayed spinning
    # even though the relay had already opened. The caller passes the id it
    # started, and that is answered from the ack, which keeps its own id.
    want = id or cid
    matches = bool(want) and ack.get("id") == want
    confirmed = matches and bool(ack.get("done"))

    # The node posts an ack twice: once with started=true/done=false the moment
    # it begins pouring, and again when it finishes. "running" is the gap
    # between them, and it is the only honest basis for a countdown or a Stop
    # button - a timer the phone starts on its own is a guess about hardware.
    running = matches and bool(ack.get("started")) and not bool(ack.get("done"))

    started_at = ack.get("at") if matches and ack.get("started") else None
    # From the ACK when it is the run we were asked about - the command document
    # may since have been replaced by the stop that ended it.
    secs = (ack.get("durationSec") if matches else cmd.get("durationSec")) or 0
    remaining = None
    if running and started_at:
        remaining = max(0, int(started_at) + int(secs) - int(time.time()))

    # Stamp the outcome onto the event that started it. The app polls this
    # throughout every manual run, so the history learns whether the node
    # actually did the work without any extra request.
    if matches and bool(ack.get("done")) and want:
        try:
            evs = _fb_get(f"/farm/events/{house_id}/{section_id}.json") or {}
            for k, v in evs.items():
                if isinstance(v, dict) and v.get("commandId") == want and not v.get("confirmed"):
                    ev = f"/farm/events/{house_id}/{section_id}/{k}"
                    _fb_put(f"{ev}/confirmed.json", True)
                    _fb_put(f"{ev}/stoppedEarly.json", bool(ack.get("stopped")))
                    break
        except Exception:
            pass

    return {
        "status": "success",
        "house": house_id,
        "section": section_id,
        "askedAbout": want,
        "command": {"id": cid,
                    "action": cmd.get("action"),
                    "durationSec": cmd.get("durationSec"),
                    "issuedAt": cmd.get("issuedAt")},
        "ack": {"id": ack.get("id"),
                "action": ack.get("action"),
                "durationSec": ack.get("durationSec"),
                "started": bool(ack.get("started")),
                "done": bool(ack.get("done")),
                # True only when the farmer cut it short. "watered for 90 s" and
                # "stopped after 12 s" are different outcomes and the app must
                # not report one as the other.
                "stopped": bool(ack.get("stopped")),
                "idle": bool(ack.get("idle")),
                "at": ack.get("at")},
        "running": running,
        "remainingSec": remaining,
        "confirmed": confirmed,
    }


@router.post("/houses/{house_id}/sections/{section_id}/stop")
def stop_section(house_id: str, section_id: str) -> dict:
    """Cut a running pour short.

    Until the firmware loop was made cooperative this was impossible: the node
    waited out a pour inside one delay(), so nothing could reach it while water
    was moving. It now watches for this command in 250 ms slices.

    A stop carries no duration - it ends whatever is running. If nothing is
    running the node acknowledges it as idle, so the app never waits forever.
    """
    if not _fb_get(f"/farm/houses/{house_id}/sections/{section_id}/meta.json"):
        raise HTTPException(404, f"Section '{house_id}/{section_id}' not found")

    cmd = _issue_node_command(house_id, section_id, "stop", 0)
    if not cmd:
        raise HTTPException(500, "Could not write the stop command")

    return {"status": "success", "command": cmd,
            "message": "Stop sent. The node picks this up within a few seconds."}


class WifiCmd(BaseModel):
    ssid: str = Field(..., min_length=1, max_length=32)
    password: str = Field("", max_length=63)


@router.post("/houses/{house_id}/sections/{section_id}/wifi")
def set_node_wifi(house_id: str, section_id: str, body: WifiCmd) -> dict:
    """Move this section's node onto a different Wi-Fi network.

    The node treats the change as PROVISIONAL: `saveCredsProvisional` keeps the
    working network as a backup, and if the new one does not come up at boot
    `rollbackCreds` puts it back and restarts. So a typo costs a reboot, not a
    node - and holding BOOT for 3 s still forces the setup portal as a last
    resort.

    The password is written to the Realtime Database in plain text, and the
    database rules are currently open. That is a deliberate, temporary choice
    while the app is unpublished; it must be closed before this ships. Tightening
    the rules needs auth tokens in BOTH the firmware and the backend first, or
    both stop working at once.
    """
    dev = _fb_get("/devices.json") or {}
    node = next((m for m, r in dev.items()
                 if (r or {}).get("assignedTo") == f"{house_id}/{section_id}"), None)
    if not node:
        raise HTTPException(400,
                            f"No node is linked to {house_id}/{section_id}, so there is "
                            "nothing to move onto a different network.")

    cmd = _issue_node_command(house_id, section_id, "wifi", 0,
                              ssid=body.ssid, **{"pass": body.password})
    if not cmd:
        raise HTTPException(500, "Could not write the Wi-Fi command")

    # Never echo the password back.
    safe = {k: v for k, v in cmd.items() if k != "pass"}
    return {"status": "success", "command": safe, "node": node,
            "message": (f"Sent to node {node[-4:]}. It will restart onto '{body.ssid}'. "
                        "If that network does not work it returns to the current one "
                        "by itself, which takes about a minute.")}


class TrayCmd(BaseModel):
    fillSeconds: int = 15
    triggeredBy: str = "user"


@router.post("/houses/{house_id}/sections/{section_id}/tray-fill")
async def tray_fill(house_id: str, section_id: str, cmd: TrayCmd):
    """Manually top up this section's humidity tray."""
    s = _fb_get(f"/farm/houses/{house_id}/sections/{section_id}.json")
    if not s:
        raise HTTPException(404, "Section not found")
    now = datetime.now(timezone.utc)
    command = {"requested": True,
               "fillSeconds": max(1, min(cmd.fillSeconds, 60)),
               "triggeredBy": cmd.triggeredBy,
               "timestamp": now.strftime("%Y-%m-%d %H:%M:%S UTC")}
    _fb_put(f"/farm/houses/{house_id}/sections/{section_id}/control/trayCommand.json", command)

    # Stamp the fill so the cooldown guard knows the tray now has water.
    # This MUST use the device clock, because _tray_decision measures the
    # cooldown against the device clock too. Stamping it with server time made
    # the two ends of the same subtraction come from different clocks, so under
    # the simulator a manual fill read as weeks old and the cooldown never
    # applied to it. On real hardware the clocks agree (NTP) and this is a no-op.
    tray = (s or {}).get("tray") or {}
    tray.update({"lastFillTs": int(_device_now_ms(s)),
                 "lastFillSeconds": command["fillSeconds"],
                 "status": "cooldown", "fillSeconds": 0,
                 "hoursSinceFill": 0.0,
                 "hoursUntilNextFill": COOLDOWN_HOURS,
                 "message": (f"Tray filled for {command['fillSeconds']}s just now. "
                             f"Next fill allowed in {COOLDOWN_HOURS:.0f} h.")})
    _fb_put(f"/farm/houses/{house_id}/sections/{section_id}/tray.json", tray)

    node_cmd = _issue_node_command(house_id, section_id, "tray",
                                   command["fillSeconds"])
    # Tray fills belong in the history too. Watering was logged and this was
    # not, so the record answered "when was it watered" but never "when was the
    # tray last topped up" - which is the other half of humidity control.
    _log_event(house_id, section_id, s,
               action="tray",
               durationSec=command["fillSeconds"],
               withFertilizer=False,
               by=cmd.triggeredBy or "user",
               commandId=(node_cmd or {}).get("id"),
               confirmed=False)
    return {"status": "success", "command": command,
            "nodeCommand": node_cmd,
            "lastAck": _last_ack(s),
            "cooldownHours": COOLDOWN_HOURS}


class ModeCmd(BaseModel):
    # All three are optional so a screen can flip ONE switch without having to
    # resend the others (and accidentally reset them).
    mode: Optional[str] = Field(None, pattern="^(auto|manual)$")
    trayEnabled: Optional[bool] = None
    fertEnabled: Optional[bool] = None


def _apply_mode(house_id: str, section_id: str, cmd: ModeCmd) -> dict:
    path = f"/farm/houses/{house_id}/sections/{section_id}/control.json"
    ctrl = _fb_get(path) or {}
    if cmd.mode is not None:
        ctrl["mode"] = cmd.mode
    if cmd.trayEnabled is not None:
        ctrl["trayEnabled"] = cmd.trayEnabled
    if cmd.fertEnabled is not None:
        ctrl["fertEnabled"] = cmd.fertEnabled
    _fb_put(path, ctrl)
    return ctrl


@router.put("/houses/{house_id}/sections/{section_id}/mode")
async def set_mode(house_id: str, section_id: str, cmd: ModeCmd):
    """Switch a section between automatic and manual control."""
    return {"status": "success", "control": _apply_mode(house_id, section_id, cmd)}


@router.put("/mode-all")
async def set_mode_all(cmd: ModeCmd):
    """Set watering / plant-food automation for the WHOLE farm at once.

    The farmer thinks in terms of "is the system looking after my plants?", not
    per-section control nodes, so the dashboard needs one switch that reaches
    every section.
    """
    houses = _fb_get("/farm/houses.json") or {}
    jobs = [(hid, sid)
            for hid, h in houses.items() if isinstance(h, dict)
            for sid in (h.get("sections") or {})]
    if not jobs:
        return {"status": "success", "sectionsUpdated": 0}

    with ThreadPoolExecutor(max_workers=min(8, len(jobs))) as pool:
        list(pool.map(lambda j: _apply_mode(j[0], j[1], cmd), jobs))
    return {"status": "success", "sectionsUpdated": len(jobs)}


class HouseEdit(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    plantCount: Optional[int] = None


class RenameIn(BaseModel):
    """Just a new label. Deliberately separate from the full edit models: a
    farmer fixing a typo in a name must never risk resetting plantCount,
    growthStage or lightExposure because the app forgot to resend a field."""
    name: str


def _clean_name(raw: str, limit: int = 40) -> str:
    name = " ".join((raw or "").split())        # collapse stray whitespace
    if not name:
        raise HTTPException(400, "Name cannot be empty")
    if len(name) > limit:
        raise HTTPException(400, f"Name must be {limit} characters or fewer")
    return name


@router.put("/farm")
async def rename_farm(body: RenameIn):
    """Rename the farm. The wizard used to be the only way to set this, so a
    typo during setup was permanent unless the whole farm was rebuilt."""
    meta = _fb_get("/farm/meta.json") or {}
    meta["farmName"] = _clean_name(body.name)
    _fb_put("/farm/meta.json", meta)
    return {"status": "success", "farm": meta}


@router.put("/houses/{house_id}/sections/{section_id}/name")
async def rename_section(house_id: str, section_id: str, body: RenameIn):
    """Rename one section, touching nothing else about it."""
    path = f"/farm/houses/{house_id}/sections/{section_id}/meta.json"
    meta = _fb_get(path)
    if not meta:
        raise HTTPException(404, "Section not found")
    meta["name"] = _clean_name(body.name)
    _fb_put(path, meta)
    return {"status": "success", "meta": meta}


@router.put("/houses/{house_id}")
async def edit_house(house_id: str, body: HouseEdit):
    """Rename a house or change its type / plant count."""
    meta = _fb_get(f"/farm/houses/{house_id}/meta.json")
    if not meta:
        raise HTTPException(404, f"House '{house_id}' not found")
    for k in ("name", "type", "plantCount"):
        v = getattr(body, k)
        if v is not None:
            meta[k] = v
    _fb_put(f"/farm/houses/{house_id}/meta.json", meta)
    return {"status": "success", "meta": meta}


@router.delete("/houses/{house_id}")
async def delete_house(house_id: str):
    """Remove a house and everything under it."""
    if not _fb_get(f"/farm/houses/{house_id}/meta.json"):
        raise HTTPException(404, f"House '{house_id}' not found")
    _fb_delete(f"/farm/houses/{house_id}.json")
    return {"status": "success", "deleted": house_id}


@router.delete("/houses/{house_id}/sections/{section_id}")
async def delete_section(house_id: str, section_id: str):
    """Deleting a section must also release its node.

    Otherwise the device keeps `assignedTo` pointing at a section that no longer
    exists: it never reappears in the Add Section picker, and the one-to-one
    check still counts it as taken. The node itself then falls back to its
    compiled-in section, so it stays alive rather than going silent.
    """
    try:
        devs = _fb_get("/devices.json") or {}
        target = f"{house_id}/{section_id}"
        for mac, rec in devs.items():
            if (rec or {}).get("assignedTo") == target:
                _fb_delete(f"/devices/{mac}/assignedTo.json")
                break
    except Exception:
        # Never block the delete on registry cleanup; a stale link is
        # recoverable, a section that refuses to delete is not.
        pass

    """Remove one section (and its readings) from a house."""
    if not _fb_get(f"/farm/houses/{house_id}/sections/{section_id}/meta.json"):
        raise HTTPException(404, "Section not found")
    _fb_delete(f"/farm/houses/{house_id}/sections/{section_id}.json")
    remaining = _fb_get(f"/farm/houses/{house_id}/sections.json") or {}
    meta = _fb_get(f"/farm/houses/{house_id}/meta.json") or {}
    meta["sectionCount"] = len(remaining)
    _fb_put(f"/farm/houses/{house_id}/meta.json", meta)
    return {"status": "success", "deleted": f"{house_id}-{section_id}",
            "sectionsRemaining": len(remaining)}


@router.get("/houses/{house_id}/sections/{section_id}/history")
async def section_history(house_id: str, section_id: str, points: int = 48,
                          hours: int = 24):
    """Down-sampled history for the section's charts (oldest first).

    `hours` is the window the farmer picked in the chart's range menu. Nodes
    report every 5 minutes, so 12 samples an hour; we pull a little extra to
    survive a device that reported late, then trim by real timestamp.
    """
    hours = max(1, min(int(hours), 24 * 30))
    want  = min(int(hours * 12 * 1.2) + 12, 5000)

    raw = _fb_get(f'/farm/history/{house_id}/{section_id}.json'
                  f'?orderBy="$key"&limitToLast={want}')
    if not raw:
        return {"status": "success", "count": 0, "series": [], "hours": hours}

    recs = []
    for r in raw.values():
        if not isinstance(r, dict) or r.get("timestamp") is None:
            continue
        c = _clean(r)
        recs.append({"t": int(r["timestamp"]),
                     "temperature": c["temperature"], "humidity": c["humidity"],
                     "light": c["light"], "vpd": vpd_kpa(c["temperature"], c["humidity"])})
    recs.sort(key=lambda x: x["t"])

    # Trim to the requested window using the DEVICE clock (the newest reading),
    # not the server's — the same reasoning as the tray cooldown, and it keeps
    # the chart correct under the accelerated simulator.
    if recs:
        cutoff = recs[-1]["t"] - hours * 3600 * 1000
        trimmed = [r for r in recs if r["t"] >= cutoff]
        if len(trimmed) >= 2:
            recs = trimmed

    if len(recs) > points:                       # even down-sample
        step = len(recs) / float(points)
        recs = [recs[int(i * step)] for i in range(points)]

    # A multi-day window needs the day, not just the clock time.
    fmt = "%H:%M" if hours <= 24 else "%d %b %H:%M"
    for r in recs:
        r["label"] = datetime.fromtimestamp(r["t"] / 1000, tz=timezone.utc).strftime(fmt)

    temps = [r["temperature"] for r in recs] or [0]
    hums  = [r["humidity"] for r in recs] or [0]
    return {"status": "success", "count": len(recs), "series": recs, "hours": hours,
            "tempMin": min(temps), "tempMax": max(temps),
            "humidityMin": min(hums), "humidityMax": max(hums)}


@router.get("/alerts")
async def alerts():
    """Everything the farmer should be told about right now."""
    houses = _fb_get("/farm/houses.json") or {}
    items = []
    now = datetime.now(timezone.utc)
    farm_now = _farm_now_ms(houses)

    # Each section is judged against ITS OWN node's reporting interval. Without
    # this every node was measured by the 15 s default, so a healthy node on the
    # 5 min production setting raised "Device stopped reporting" on every poll.
    alert_nodes = {}
    for mac, rec in (_fb_get("/devices.json") or {}).items():
        assigned = (rec or {}).get("assignedTo")
        if assigned:
            alert_nodes[assigned] = {"mac": mac,
                                     "readIntervalMs": (rec or {}).get("readIntervalMs")}

    for hid, h in sorted(houses.items()):
        if not isinstance(h, dict):
            continue
        hname = (h.get("meta") or {}).get("name", hid)
        for sid, s in sorted((h.get("sections") or {}).items()):
            if not isinstance(s, dict):
                continue
            sname = (s.get("meta") or {}).get("name", sid)
            where = f"{hname} · {sname}"
            latest, tray, plan = s.get("latest"), s.get("tray") or {}, s.get("plan") or {}

            if not latest:
                items.append({"id": f"{hid}-{sid}-offline", "level": "warning",
                              "icon": "cloud-offline-outline", "title": "Device offline",
                              "message": f"{where} has never reported. Check power and Wi-Fi.",
                              "houseId": hid, "sectionId": sid})
                continue

            # A node that stopped reporting is the most important thing to say:
            # every other number below it is computed from a stale reading.
            fresh = _freshness(s, farm_now,
                               (alert_nodes.get(f"{hid}/{sid}") or {}).get("readIntervalMs"))
            if not fresh["trusted"]:
                items.append({"id": f"{hid}-{sid}-stale", "level": "warning",
                              "icon": "battery-dead-outline",
                              "title": "Device stopped reporting",
                              "message": f"{where}: {fresh['message']}",
                              "houseId": hid, "sectionId": sid})
                continue

            c = _clean(latest)
            if tray.get("status") == "fill":
                items.append({"id": f"{hid}-{sid}-tray", "level": "action",
                              "icon": "water-outline", "title": "Humidity low",
                              "message": f"{where}: {c['humidity']}% RH — tray needs "
                                         f"{tray.get('fillSeconds', 0)}s of water.",
                              "houseId": hid, "sectionId": sid})
            elif tray.get("trayAtLimit"):
                # tray still has water but the air is too dry for it to cope
                items.append({"id": f"{hid}-{sid}-limit", "level": "info",
                              "icon": "information-circle-outline",
                              "title": "Tray at its limit",
                              "message": f"{where}: {c['humidity']}% RH but the tray was "
                                         f"filled {tray.get('hoursSinceFill')}h ago — the air "
                                         f"is very dry today, not the tray.",
                              "houseId": hid, "sectionId": sid})
            if c["temperature"] >= 36:
                items.append({"id": f"{hid}-{sid}-heat", "level": "urgent",
                              "icon": "flame-outline", "title": "Extreme heat",
                              "message": f"{where} is at {c['temperature']}°C.",
                              "houseId": hid, "sectionId": sid})
            fert = s.get("fertilizer") or {}
            if fert.get("growthNeedsAttention"):
                items.append({"id": f"{hid}-{sid}-growth", "level": "action",
                              "icon": "leaf-outline", "title": "Set the growth stage",
                              "message": f"{where}: {fert.get('growthMessage')}",
                              "houseId": hid, "sectionId": sid})
            if fert.get("due"):
                items.append({"id": f"{hid}-{sid}-fert", "level": "action",
                              "icon": "flask-outline", "title": "Fertilizer due",
                              "message": f"{where}: give {fert.get('npkType')} at "
                                         f"{int(float(fert.get('strength', 0.5)) * 100)}% strength — "
                                         f"it will be mixed into the next watering.",
                              "houseId": hid, "sectionId": sid})
            if plan.get("secondSession"):
                items.append({"id": f"{hid}-{sid}-2nd", "level": "info",
                              "icon": "time-outline", "title": "Second watering planned",
                              "message": f"{where}: extra session at {plan.get('secondTime')} "
                                         f"({plan.get('secondDurationSec')}s) because of heat.",
                              "houseId": hid, "sectionId": sid})
            elif plan.get("waterTime"):
                items.append({"id": f"{hid}-{sid}-plan", "level": "info",
                              "icon": "calendar-outline", "title": "Today's watering",
                              "message": f"{where}: {plan['waterTime']} for {plan['durationSec']}s.",
                              "houseId": hid, "sectionId": sid})

    order = {"urgent": 0, "action": 1, "warning": 2, "info": 3}
    items.sort(key=lambda a: order.get(a["level"], 9))
    return {"status": "success", "count": len(items),
            "urgent": sum(1 for a in items if a["level"] in ("urgent", "action")),
            "alerts": items,
            "generatedAt": now.strftime("%Y-%m-%d %H:%M:%S UTC")}


@router.get("/model-info")
async def model_info():
    """Model metrics — used by the app's About screen and for the viva."""
    if not _ready():
        raise HTTPException(503, "v2 models not loaded")
    return {
        "status": "success",
        "version": 2,
        "watering": {
            "type": "RandomForestRegressor x2 + RandomForestClassifier",
            "features": _water.get("feature_columns") or WATER_FEATURES,
            "metrics": _water["metrics"],
            "rule": "Once per day. Second session only in extreme heat.",
        },
        "tray": {
            "type": "RandomForestRegressor",
            "features": _tray.get("feature_columns") or TRAY_FEATURES,
            "metrics": _tray["metrics"],
            "target": f"{_tray['rh_target_low']}-{_tray['rh_target_high']}% RH (Vanda ideal)",
        },
        "growthStage": {
            "sources": ["component2", "manual", "seasonal"],
            "component2Path": "/farm/houses/{houseId}/sections/{sectionId}/growthPrediction",
            "component2Schema": {"stage": "Active|Flowering|Dormant",
                                 "confidence": "0.0-1.0",
                                 "predictedAt": "epoch ms",
                                 "source": "component2-cnn"},
            "maxAgeDays": GROWTH_PREDICTION_MAX_AGE_DAYS,
            "minConfidence": GROWTH_PREDICTION_MIN_CONF,
            "note": ("Component 2 is not connected yet. When it writes to the path "
                     "above this component picks it up automatically — no code change."),
        },
        "fertilizer": {
            "type": "DecisionTreeClassifier",
            "metrics": _fert["metrics"],
            "note": _fert["note"],
        },
    }
