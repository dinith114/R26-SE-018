"""What a node actually MEASURED - and nothing substituted for what it did not.

smart_care_v2._clean() is for feeding the MODELS: it replaces a failed or
impossible value with a safe default (28 C, 70 %, 0 lux) so a model never sees
-999. That is right for a model and wrong for anything that treats a reading as
evidence about the house. Two such places used it anyway:

  * the placement matrix (house_planner._snapshots_measured), where a DHT22
    glitch became a real-looking 28.0 C at that section and that moment;
  * the kriging anchors (spatial_service._anchor_reading), whose docstring
    promised "a failed sensor reads as None and is excluded" - it never did,
    because _clean() never returns None.

And a node built without a BH1750 reports light -999 on every reading, which
_clean() turns into 0.0 lux: a section that has no light sensor at all would
have been placed and kriged as permanently dark.

Here a value is either measured and plausible, or absent. Nothing in between.
"""
from __future__ import annotations

import math
from typing import Optional

SENTINEL = -999.0

# Same bounds as smart_care_v2.PLAUSIBLE - what a WORKING sensor in a Sri
# Lankan shade house can report. Kept here rather than imported so this module
# stays importable without the server; test_readings pins the two equal.
PLAUSIBLE = {"temperature": (5.0, 55.0), "humidity": (5.0, 100.0),
             "light": (0.0, 200000.0)}

MEASURED_FIELDS = ("temperature", "humidity", "light")


def value(rec: dict, field: str) -> Optional[float]:
    """One field as measured, or None if it was missing, failed or impossible."""
    try:
        v = float((rec or {}).get(field))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= SENTINEL:
        return None
    lo, hi = PLAUSIBLE[field]
    if v < lo or v > hi:
        return None
    return v


def why_rejected(rec: dict, field: str) -> Optional[str]:
    """'missing', 'failed' (-999 / not a number) or 'implausible'; None if fine."""
    raw = (rec or {}).get(field)
    if raw is None:
        return "missing"
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return "failed"
    if not math.isfinite(v) or v <= SENTINEL:
        return "failed"
    lo, hi = PLAUSIBLE[field]
    if v < lo or v > hi:
        return "implausible"
    return None


def measured(rec: dict) -> dict:
    """The reading with every unusable field REMOVED, timestamp kept."""
    out = {}
    for f in MEASURED_FIELDS:
        v = value(rec, f)
        if v is not None:
            out[f] = v
    if (rec or {}).get("timestamp") is not None:
        out["timestamp"] = rec["timestamp"]
    return out


def vpd_kpa(temp_c: float, rh_pct: float) -> float:
    """Vapour pressure deficit, kPa. Same formula as smart_care_v2.vpd_kpa."""
    svp = 0.6108 * math.exp(17.27 * temp_c / (temp_c + 237.3))
    return svp * (1.0 - rh_pct / 100.0)
