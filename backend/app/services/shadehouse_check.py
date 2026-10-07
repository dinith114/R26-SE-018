"""Is the shade house what the watering model was told it is?

The PP2 panel asked "how do we know the watering times are correct?". The answer
has two halves, and this module is the second.

  1. The model reproduces the expert rule it was trained on, on whole years it
     never saw (ml_pipeline/validate_out_of_time.py, served as
     /api/v2/care/watering-validation). That shows the MODEL is faithful to its
     labels.
  2. Those labels were computed on REAL weather (ERA5) - but ERA5 is the open
     air, and the plants are inside a shade house. fetch_real_weather.py moves
     the weather indoors with three constants nobody has ever measured:

         temperature  outdoor + 3.5 C x sun             MAX_DAY_WARMING
         humidity     outdoor + 7 % x (1 - 0.45 x sun)  HUMIDITY_LIFT
         light        45 % of outdoor                   SHADE_TRANSMISSION

     If those are wrong, the model is faithfully reproducing a rule applied to
     the wrong house, and half 1 cannot see it. Only a sensor INSIDE the house
     can, so this puts what the sensors recorded beside the real outdoor weather
     for the same hours and reports each constant as measured.

compare() is a pure function of the readings and the outdoor table it is given:
no Firebase, no network, nothing random. fetch_outdoor() is the one part that
touches the network, and it is separate so that the tests never do.

THE RULES THAT EACH COST A WRONG ANSWER
---------------------------------------
These were all live defects in ml_pipeline/validate_shadehouse_assumption.py,
which this replaces on the server. Each one produced a NUMBER, not an error,
which is why they survived:

  * UTC throughout. History timestamps are epoch ms in UTC. The script turned
    them into naive UTC and then asked for the weather in Asia/Colombo, so every
    indoor hour was paired with the outdoor hour 5.5 h away - the midday indoor
    reading against the dawn outdoor one. Here the weather is requested in GMT
    and every hour is an epoch-ms bucket, so there is no clock to get wrong.
  * A failed or absent sensor is MISSING, never a number. A node built without
    a BH1750 writes light -999 on every reading; the script kept it, and the
    median "transmission" came out negative. readings.value() drops -999, NaN,
    missing and implausible values, field by field: a record with no light
    still contributes its temperature.
  * Seeded records are not readings. seed_farm_v2.py and seed_houses.py wrote
    synthetic history under `seedNNN` keys stamped with REAL wall-clock time, so
    they pair with real weather perfectly well and would be counted as the
    house. The live H1 history carries 96 of them per section.
  * A clock that never synced is not a time. One live record is stamped
    1970-01-01; taken at face value it asks the weather archive for 56 years.
  * A light reading at the BH1750's ceiling is a floor, not a value. The
    firmware runs it in CONTINUOUS_HIGH_RES_MODE with the default MTreg, whose
    datasheet range ends at 65535 / 1.2 = 54,612 lux - and 45 % of a full-sun
    120,000 lux is 54,000. A pinned reading would pull the measured
    transmission down for no reason but the sensor's range.
  * The humidity lift is measured the way the model APPLIES it. The constant is
    the night-time lift; by day the conversion uses 7 x (1 - 0.45 x sun). The
    script took the plain median of indoor-minus-outdoor, which is a
    sun-weighted average of the constant, not the constant. And hours where the
    conversion clips at 99 % are left out: outdoors at 95 % RH no lift can show,
    neither in the model (it clips) nor on a DHT22 (it cannot read 102 %).
    Counting those hours would report a lift of ~3 % in a house whose lift is 7.

WHAT A RESULT DOES AND DOES NOT SHOW
------------------------------------
Within tolerance means the conversion the training data went through matches
this house over the hours compared. It does not make the watering rule itself
right - that is agronomy, and it is cited, not measured. And a few days in
October is one season: the report should say which days were compared.
"""
from __future__ import annotations

import json
import math
import statistics
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional

from app.services import readings as rd

# ── The conversion being checked ─────────────────────────────────────────────
# Copied from ml_pipeline/fetch_real_weather.py, which lives outside this
# repository and is not deployed. If those constants are ever corrected, change
# these with them: the check is against what the model was TRAINED on, and that
# is whatever fetch_real_weather.py said at training time.
ASSUMED = {"warming": 3.5, "humidityLift": 7.0, "transmission": 0.45}
RH_SUN_SHRINK = 0.45          # the lift is HUMIDITY_LIFT x (1 - 0.45 x sun)
RH_CLIP = (20.0, 99.0)        # to_shadehouse() clips indoor humidity to this
LUX_PER_WM2 = 120.0           # luminous efficacy of daylight, as in training
SUN_FULL_WM2 = 1000.0         # sun = radiation / 1000, clipped to 0..1

# How far the measured value may sit from the assumed one before the constant
# is called wrong. The same three numbers as the ml_pipeline script, so the
# script and this endpoint give the same verdict on the same data.
TOLERANCE = {"warming": 1.0, "humidityLift": 4.0, "transmission": 0.10}

QUANTITIES = ("warming", "humidityLift", "transmission")
LABELS = {"warming": "Day warming at full sun",
          "humidityLift": "Humidity lift",
          "transmission": "Light transmission"}
UNITS = {"warming": "C", "humidityLift": "%", "transmission": "fraction"}
# The constant's name in fetch_real_weather.py, for the "edit this" line.
CONSTANT_NAMES = {"warming": "MAX_DAY_WARMING", "humidityLift": "HUMIDITY_LIFT",
                  "transmission": "SHADE_TRANSMISSION"}

# Fewer overlapping hours than this is not a day, and a median over it says
# more about the hour of day than about the house.
MIN_HOURS = 12
# Warming is measured as (indoor - outdoor) / sun, so it is only read when the
# sun is strong: at sun 0.05 a 0.2 C sensor wobble becomes 4 C of "warming".
SUNNY = 0.3                   # i.e. outdoor radiation above 300 W/m2
BRIGHT_WM2 = 100.0            # transmission needs real daylight to be a ratio

BH1750_CEILING_LUX = 65535 / 1.2      # 54,612.5 lux; see the module docstring
SEED_PREFIX = "seed"
# Before this the node's clock had not synced. 2020-01-01 UTC.
EARLIEST_PLAUSIBLE_MS = 1_577_836_800_000
HOUR_MS = 3_600_000


def _r(v, nd=2):
    return None if v is None else round(float(v), nd)


def _median(xs: List[float]) -> Optional[float]:
    return float(statistics.median(xs)) if xs else None


def _mean(xs: List[float]) -> Optional[float]:
    return float(sum(xs) / len(xs)) if xs else None


def _iso_hour(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def sun_of(radiation_wm2: float) -> float:
    return min(1.0, max(0.0, float(radiation_wm2) / SUN_FULL_WM2))


def modelled_indoor(t_out: float, rh_out: float, radiation_wm2: float) -> dict:
    """What fetch_real_weather.to_shadehouse() says the inside was, for one hour.

    The same arithmetic, constant for constant, so "outdoor plus assumed" in the
    response is the number the training data actually contained.
    """
    sun = sun_of(radiation_wm2)
    rh = rh_out + ASSUMED["humidityLift"] * (1.0 - RH_SUN_SHRINK * sun)
    return {
        "temperature": t_out + ASSUMED["warming"] * sun,
        "humidity": min(RH_CLIP[1], max(RH_CLIP[0], rh)),
        "light": radiation_wm2 * ASSUMED["transmission"] * LUX_PER_WM2,
    }


# ── Indoor: readings to hourly means ─────────────────────────────────────────

def indoor_by_hour(history: dict, since_ms: Optional[float] = None,
                   now_ms: Optional[float] = None) -> tuple:
    """(hours, excluded) for one section.

    `hours` maps a UTC hour start (epoch ms) to the mean of each field measured
    in that hour, or None for a field with no usable reading. An hour is the
    FLOOR of the timestamp: a reading at 08:30 UTC belongs to [08:00, 09:00).
    compare() then pairs that window with the outdoor values describing the
    same sixty minutes - see out_for_window().

    `excluded` counts what was left out and why, so the app can say "990 light
    readings were -999" instead of quietly computing from fewer.
    """
    excluded = {"seeded": 0, "badClock": 0, "beforeSince": 0,
                "temperature": 0, "humidity": 0, "light": 0, "lightAtCeiling": 0}
    acc: Dict[int, Dict[str, List[float]]] = {}
    # Hours in which the BH1750 hit its ceiling. Dropping only the pinned
    # minutes kept an hour's CLOUDY minutes and divided them by the whole hour's
    # radiation, biasing transmission low - a true 0.60 read 0.516 "within
    # tolerance" and a true 0.70 read 0.247. The light in such an hour is
    # censored, so the whole hour's light is left out. Found in review.
    pinned: set = set()
    for key, rec in (history or {}).items():
        if not isinstance(rec, dict):
            continue
        if str(key).startswith(SEED_PREFIX):
            excluded["seeded"] += 1
            continue
        try:
            ts = float(rec.get("timestamp"))
        except (TypeError, ValueError):
            excluded["badClock"] += 1
            continue
        # A clock behind 2020 never synced; one ahead of now is the farm
        # simulator's sim clock. Neither is a time the weather can be fetched for.
        if (not math.isfinite(ts) or ts < EARLIEST_PLAUSIBLE_MS
                or (now_ms is not None and ts > now_ms + HOUR_MS)):
            excluded["badClock"] += 1
            continue
        if since_ms is not None and ts < since_ms:
            excluded["beforeSince"] += 1
            continue
        hour = int(ts // HOUR_MS) * HOUR_MS
        slot = acc.setdefault(hour, {"temperature": [], "humidity": [], "light": []})
        for field in ("temperature", "humidity", "light"):
            v = rd.value(rec, field)
            if v is None:
                excluded[field] += 1
                continue
            if field == "light" and v >= BH1750_CEILING_LUX - 1.0:
                excluded["lightAtCeiling"] += 1
                pinned.add(hour)
                continue
            slot[field].append(v)
    hours = {h: {f: (None if f == "light" and h in pinned else _mean(vals))
                 for f, vals in slot.items()}
             for h, slot in acc.items()}
    excluded["lightHoursAtCeiling"] = len(pinned)
    return hours, excluded


def reading_window(histories: Dict[str, dict], since_ms: Optional[float] = None,
                   now_ms: Optional[float] = None) -> Optional[tuple]:
    """(first, last) UTC dates the usable readings span, or None if none are.

    Through indoor_by_hour(), the same filter compare() applies, so the outdoor
    request covers exactly the readings that will be compared - and a 1970 clock
    or a seeded record cannot stretch it across decades.
    """
    stamps: List[int] = []
    for hist in (histories or {}).values():
        hours, _exc = indoor_by_hour(hist, since_ms=since_ms, now_ms=now_ms)
        stamps.extend(hours)
    if not stamps:
        return None
    day = lambda ms: datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).date()
    # + HOUR_MS: the last indoor hour is closed by the NEXT outdoor stamp (see
    # out_for_window), which for a 23:00 hour falls on the following day.
    return day(min(stamps)), day(max(stamps) + HOUR_MS)


# ── The estimates ────────────────────────────────────────────────────────────

def _rh_clipped(row: dict) -> bool:
    """True where the conversion itself clips, so no lift can be measured."""
    lifted = row["rhOut"] + ASSUMED["humidityLift"] * (1.0 - RH_SUN_SHRINK * row["sun"])
    return lifted > RH_CLIP[1]


def _estimate(rows: List[dict]) -> dict:
    """Each constant as measured over `rows`, with the hours it rests on."""
    warm = [(r["tIn"] - r["tOut"]) / r["sun"]
            for r in rows if r["tIn"] is not None and r["sun"] > SUNNY]
    lift = [(r["rhIn"] - r["rhOut"]) / (1.0 - RH_SUN_SHRINK * r["sun"])
            for r in rows if r["rhIn"] is not None and not _rh_clipped(r)]
    trans = [r["luxIn"] / (r["rad"] * LUX_PER_WM2)
             for r in rows if r["luxIn"] is not None and r["rad"] > BRIGHT_WM2]
    return {
        "warming": (_median(warm), len(warm)),
        "humidityLift": (_median(lift), len(lift)),
        "transmission": (_median(trans), len(trans)),
    }


def _why_unmeasured(q: str, rows: List[dict]) -> str:
    """'not enough data', in words a farmer and an examiner can both act on."""
    if q == "warming":
        return ("not enough data: no sunny hours (outdoor radiation above 300 W/m2) "
                "among the hours compared")
    if q == "humidityLift":
        return ("not enough data: outdoor humidity was so high in every hour that "
                "the conversion clips at 99 %, so no lift can show")
    if not any(r["luxIn"] is not None for r in rows):
        return ("not enough data: no valid light readings (a node without a "
                "BH1750 reports -999, and a pinned 54,612 lux is not a value)")
    return ("not enough data: no bright hours (outdoor radiation above 100 W/m2) "
            "with a valid light reading")


def _judge(rows: List[dict]) -> dict:
    """measured / gap / verdict / hoursUsed per quantity, plus an overall."""
    est = _estimate(rows)
    measured, gap, verdict, used = {}, {}, {}, {}
    for q in QUANTITIES:
        m, n = est[q]
        used[q] = n
        if m is None:
            measured[q], gap[q] = None, None
            verdict[q] = _why_unmeasured(q, rows)
            continue
        measured[q] = _r(m, 3 if q == "transmission" else 2)
        gap[q] = _r(m - ASSUMED[q], 3 if q == "transmission" else 2)
        verdict[q] = ("within tolerance" if abs(m - ASSUMED[q]) <= TOLERANCE[q]
                      else "out of tolerance")
    return {"measured": measured, "gap": gap, "verdict": verdict, "hoursUsed": used}


def _overall(j: dict, source: str) -> dict:
    """The script's verdict logic, unchanged: every MEASURED constant within
    tolerance means the conversion holds; one outside means it does not. A
    constant that could not be measured is named, never counted as a pass."""
    checked = [q for q in QUANTITIES if j["measured"][q] is not None]
    unchecked = [q for q in QUANTITIES if j["measured"][q] is None]
    bad = [q for q in checked if j["verdict"][q] == "out of tolerance"]
    if not checked:
        return {"holds": None, "checked": [], "unchecked": unchecked, "suggested": {},
                "text": "Not enough data to judge any of the three constants."}
    if bad:
        suggested = {CONSTANT_NAMES[q]: j["measured"][q] for q in checked}
        text = ("At least one constant is out of tolerance: "
                + ", ".join(LABELS[q].lower() for q in bad)
                + ". Correct them in ml_pipeline/fetch_real_weather.py and retrain "
                  "(fetch_real_weather, train_on_real_data, build_forecast_model).")
    else:
        suggested = {}
        text = ("The modelled indoor conversion holds against these readings for "
                + ", ".join(LABELS[q].lower() for q in checked) + ".")
    if unchecked:
        text += " Not checked: " + ", ".join(LABELS[q].lower() for q in unchecked) + "."
    if source != "era5-archive":
        text += (" Part of the outdoor reference is a forecast-model analysis, not "
                 "ERA5; re-run once those days are in the ERA5 archive.")
    return {"holds": not bad, "checked": checked, "unchecked": unchecked,
            "suggested": suggested, "text": text}


def _by_hour(rows: List[dict], local_offset_min: int) -> List[dict]:
    """24 rows, one per UTC hour of day, ordered by FARM time so a chart reads
    midnight to midnight where the plants are. Medians, pooled over sections and
    days. An hour nobody recorded is present with n 0 and nulls - not dropped,
    so a gap in the chart is a gap in the data."""
    out = []
    for h in range(24):
        sel = [r for r in rows if (r["hourMs"] // HOUR_MS) % 24 == h]
        local = (h * 60 + local_offset_min) % 1440

        def med(key):
            return _r(_median([r[key] for r in sel if r[key] is not None]), 1)

        out.append({
            "hourUtc": h,
            "localTime": f"{local // 60:02d}:{local % 60:02d}",
            "n": len(sel),
            "indoorTemp": med("tIn"), "indoorRh": med("rhIn"),
            "outdoorTemp": med("tOut"), "outdoorRh": med("rhOut"),
            "assumedTemp": med("tModel"), "assumedRh": med("rhModel"),
        })
    out.sort(key=lambda row: (row["hourUtc"] * 60 + local_offset_min) % 1440)
    return out


def _estimate_error(rows: List[dict]) -> dict:
    """Mean absolute error of the indoor ESTIMATE, against using the outdoor
    weather as it is. If the conversion is doing its job, the first is smaller."""
    out = {}
    for field, i, m, o in (("temperature", "tIn", "tModel", "tOut"),
                           ("humidity", "rhIn", "rhModel", "rhOut")):
        sel = [r for r in rows if r[i] is not None]
        out[field] = {
            "hours": len(sel),
            "outdoorPlusAssumed": _r(_mean([abs(r[m] - r[i]) for r in sel])),
            "outdoorAsIs": _r(_mean([abs(r[o] - r[i]) for r in sel])),
        }
    return out


def out_for_window(out_by_hour: Dict[int, dict], hour: int) -> Optional[tuple]:
    """(temperature, humidity, radiation) outdoors over [hour, hour + 1 h).

    Open-Meteo's columns do not all describe the same moment:
      shortwave_radiation    the mean of the PRECEDING hour
      temperature_2m, RH     an instant, at the stamp
    So the radiation for [08:00, 09:00) is the row stamped 09:00, and the air
    over that window is best taken as the mean of the 08:00 and 09:00 instants.
    Pairing the indoor 08:00 hour with the 08:00 row - as this did first -
    used the sun from an hour EARLIER and the air from thirty minutes before the
    middle of the window, which on a clear morning and cloudy afternoon moved a
    house that follows the assumption exactly from 3.5 C to 4.19 C of warming.
    Found in review, 7 Oct 2026.

    None when the closing stamp is missing (no radiation for the window). The
    opening instant may be missing at the edge of a fetch; then the closing one
    is used alone.
    """
    close = out_by_hour.get(hour + HOUR_MS)
    if close is None:
        return None
    open_ = out_by_hour.get(hour)
    if open_ is None:
        return float(close["temperature"]), float(close["humidity"]), float(close["radiation"])
    return ((float(open_["temperature"]) + float(close["temperature"])) / 2.0,
            (float(open_["humidity"]) + float(close["humidity"])) / 2.0,
            float(close["radiation"]))


def compare(histories: Dict[str, dict], outdoor: dict, *,
            since_ms: Optional[float] = None, now_ms: Optional[float] = None,
            local_offset_min: int = 330) -> dict:
    """Measured indoor against the assumed conversion, pooled and per section.

    `histories` is {sectionId: {pushKey: record}} exactly as Firebase returns
    /farm/history/{h}/{s}. `outdoor` is what fetch_outdoor() returns:
    {"source", "note", "hours": [{"hourMs", "temperature", "humidity",
    "radiation"}]}, hourMs being a UTC hour start.

    Returns `enough: False` with a `reason` in words when there is not enough
    to judge - fewer than MIN_HOURS overlapping hours, or no sunny hour - and
    never a number computed from nothing.
    """
    out_by_hour = {int(h["hourMs"]): h for h in (outdoor or {}).get("hours") or []}
    source = (outdoor or {}).get("source") or "unknown"

    rows: List[dict] = []
    excluded: Dict[str, dict] = {}
    unmatched: Dict[str, int] = {}
    for sid, hist in (histories or {}).items():
        hours, exc = indoor_by_hour(hist, since_ms=since_ms, now_ms=now_ms)
        excluded[sid] = exc
        unmatched[sid] = 0
        for hour, ind in sorted(hours.items()):
            o = out_for_window(out_by_hour, hour)
            if o is None:
                unmatched[sid] += 1
                continue
            t_out, rh_out, rad = o
            mod = modelled_indoor(t_out, rh_out, rad)
            rows.append({
                "section": sid, "hourMs": hour,
                "tIn": ind["temperature"], "rhIn": ind["humidity"], "luxIn": ind["light"],
                "tOut": t_out, "rhOut": rh_out, "rad": rad, "sun": sun_of(rad),
                "tModel": mod["temperature"], "rhModel": mod["humidity"],
            })

    distinct = sorted({r["hourMs"] for r in rows})
    sections = sorted({r["section"] for r in rows})
    base = {
        "hours": len(distinct),
        "sectionHours": len(rows),
        "sections": sections,
        "from": _iso_hour(distinct[0]) if distinct else None,
        "to": _iso_hour(distinct[-1] + HOUR_MS) if distinct else None,
        "outdoorSource": {k: v for k, v in (outdoor or {}).items() if k != "hours"},
        "assumed": dict(ASSUMED),
        "tolerance": dict(TOLERANCE),
        "labels": dict(LABELS),
        "units": dict(UNITS),
        "excluded": excluded,
        "indoorHoursWithoutOutdoor": unmatched,
    }

    if len(distinct) < MIN_HOURS:
        return {**base, "enough": False,
                "reason": (f"Not enough data: {len(distinct)} hour"
                           f"{'' if len(distinct) == 1 else 's'} of indoor readings "
                           f"overlap the outdoor weather, and at least {MIN_HOURS} are "
                           "needed to judge the conversion. Let the node record for "
                           "longer.")}
    if not any(r["sun"] > SUNNY and r["tIn"] is not None for r in rows):
        return {**base, "enough": False,
                "reason": (f"Not enough data: none of the {len(distinct)} overlapping "
                           "hours had sun (outdoor radiation above 300 W/m2) with a "
                           "temperature reading, so the day warming - the part of the "
                           "conversion that moves the watering time - cannot be "
                           "measured yet.")}

    pooled = _judge(rows)
    per_section = {}
    for sid in sections:
        srows = [r for r in rows if r["section"] == sid]
        n = len({r["hourMs"] for r in srows})
        if n < MIN_HOURS:
            per_section[sid] = {
                "hours": n, "measured": {q: None for q in QUANTITIES},
                "gap": {q: None for q in QUANTITIES},
                "verdict": {q: f"not enough data: {n} overlapping hours, need {MIN_HOURS}"
                            for q in QUANTITIES},
                "hoursUsed": {q: 0 for q in QUANTITIES}}
        else:
            per_section[sid] = {"hours": n, **_judge(srows)}

    return {
        **base,
        "enough": True,
        "measured": pooled["measured"],
        "gap": pooled["gap"],
        "verdict": pooled["verdict"],
        "hoursUsed": pooled["hoursUsed"],
        "overall": _overall(pooled, source),
        "perSection": per_section,
        "estimateError": _estimate_error(rows),
        "byHour": _by_hour(rows, local_offset_min),
    }


# ── Outdoor weather: Open-Meteo ──────────────────────────────────────────────
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARS = "temperature_2m,relative_humidity_2m,shortwave_radiation"
# The ERA5 archive runs about a week behind real time. Days older than this come
# from the archive - the dataset the model was trained on. Anything newer comes
# from the forecast API's past_days, which is the forecast MODEL's own analysis,
# not ERA5: close, but not the same dataset, and the response says which.
ARCHIVE_LAG_DAYS = 7

SOURCE_NOTES = {
    "era5-archive": ("ERA5 reanalysis from the Open-Meteo archive: the same dataset "
                     "the training weather came from."),
    "forecast-model": ("Open-Meteo forecast-model analysis (past_days), NOT ERA5: "
                       "these days are too recent for the archive. It is the best "
                       "reference available for the last week, but it is not the "
                       "dataset the model was trained on."),
    "mixed": ("ERA5 archive for the older days and Open-Meteo forecast-model "
              "analysis (NOT ERA5) for the last week, which the archive does not "
              "cover yet."),
}


def outdoor_plan(start: date, end: date, today: date) -> List[dict]:
    """Which API covers which days. Pure, so the rule is testable without a network.

    "Older than ARCHIVE_LAG_DAYS" goes to the archive; the rest to the forecast
    API with past_days reaching back to the first of them. Nothing after today:
    a simulator's clock can run ahead, and the archive answers a future date
    with a 400.
    """
    end = min(end, today)
    if start > end:
        return []
    cutoff = today - timedelta(days=ARCHIVE_LAG_DAYS)
    parts = []
    if start < cutoff:
        parts.append({"api": "archive", "start": start,
                      "end": min(end, cutoff - timedelta(days=1))})
    if end >= cutoff:
        first = max(start, cutoff)
        parts.append({"api": "forecast", "start": first, "end": end,
                      "pastDays": (today - first).days})
    return parts


def _url(part: dict, lat: float, lon: float) -> str:
    q = {"latitude": f"{lat:.6f}", "longitude": f"{lon:.6f}", "hourly": HOURLY_VARS,
         # GMT, so every time that comes back is already UTC - see the module
         # docstring for what asking in Asia/Colombo did.
         "timezone": "GMT"}
    if part["api"] == "archive":
        q.update(start_date=part["start"].isoformat(), end_date=part["end"].isoformat())
        return f"{ARCHIVE_URL}?{urllib.parse.urlencode(q)}"
    q.update(past_days=str(part["pastDays"]), forecast_days="1")
    return f"{FORECAST_URL}?{urllib.parse.urlencode(q)}"


def parse_hourly(payload: dict, start: date, end: date) -> List[dict]:
    """Open-Meteo's columns as rows keyed by UTC hour start, inside [start, end].

    An hour with any of the three values missing is dropped whole: an hour with
    no radiation has no sun, and guessing one would be inventing the warming.
    """
    h = (payload or {}).get("hourly") or {}
    lo = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    hi = datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1)
    rows = []
    for t, temp, rh, rad in zip(h.get("time") or [], h.get("temperature_2m") or [],
                                h.get("relative_humidity_2m") or [],
                                h.get("shortwave_radiation") or []):
        if temp is None or rh is None or rad is None:
            continue
        when = datetime.strptime(t, "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc)
        if not (lo <= when < hi):
            continue
        rows.append({"hourMs": int(when.timestamp() * 1000), "temperature": float(temp),
                     "humidity": float(rh), "radiation": float(rad)})
    return rows


def fetch_outdoor(lat: float, lon: float, start: date, end: date, *,
                  today: Optional[date] = None, timeout: float = 20.0,
                  urlopen: Optional[Callable] = None) -> dict:
    """Hourly outdoor weather for the farm, archive or recent as outdoor_plan says.

    Raises on a network failure rather than returning an empty table: "the
    weather service could not be reached" and "the conversion could not be
    checked" are different statements, and the route says the first.
    `urlopen` is a seam for tests; the default is urllib's, so this module adds
    no dependency.
    """
    today = today or datetime.now(timezone.utc).date()
    opener = urlopen or urllib.request.urlopen
    plan = outdoor_plan(start, end, today)
    hours: Dict[int, dict] = {}
    parts = []
    for part in plan:
        with opener(_url(part, lat, lon), timeout=timeout) as resp:
            payload = json.load(resp)
        got = parse_hourly(payload, part["start"], part["end"])
        for row in got:
            hours[row["hourMs"]] = row
        parts.append({"api": part["api"], "from": part["start"].isoformat(),
                      "to": part["end"].isoformat(), "hours": len(got)})
    apis = {p["api"] for p in parts}
    source = ("mixed" if apis == {"archive", "forecast"}
              else "forecast-model" if apis == {"forecast"}
              else "era5-archive" if apis == {"archive"} else "none")
    return {"source": source, "note": SOURCE_NOTES.get(source, "No outdoor weather requested."),
            "latitude": lat, "longitude": lon, "parts": parts,
            "hours": [hours[k] for k in sorted(hours)]}
