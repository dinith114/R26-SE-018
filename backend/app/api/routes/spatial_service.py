"""Virtual sensing: estimate a section's microclimate from its neighbours.

A farm cannot afford a node in every zone. Ordinary Kriging lets the zones that
DO have hardware estimate the ones that do not, using the spatial correlation
between them, and returns a variance for each estimate so the confidence is
explicit rather than assumed.

Two design decisions are worth stating, because both were deliberate.

ESTIMATES ARE NOT WRITTEN TO /latest.
    /latest is where the node writes what it measured. _clean() exists to
    guarantee "nothing is invented here", and this project has already shipped
    and then fixed the exact bug that writing here would recreate: a section
    with no sensor displayed 28.0 C and 70 % humidity as though measured, and
    70 % sits inside the ideal band, so a zone with no hardware showed a green
    "GOOD". A flag on the record does not help, because freshness, _display,
    the tray logic, the app and the engine all read /latest without consulting
    one. Estimates go to /estimated, and a caller has to ask for them.

IT REFUSES RATHER THAN GUESSES.
    Kriging fits a variogram - a model of how quickly similarity decays with
    distance. Below MIN_ANCHORS there is nothing to fit it from, and the result
    is not an interpolation but the nearest anchor's value wearing a confidence
    interval it has not earned. This module returns a reason instead.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from app.api.routes.smart_care_v2 import (
    _fb_get, _fb_put, _clean, _server_now_ms, vpd_kpa,
)

# Fields worth estimating. sampleMoisture is deliberately absent: it measures
# water in THIS section's tray, which is a property of that tray's plumbing and
# last fill, not of the air, and does not vary smoothly across the house.
FIELDS = ("temperature", "humidity", "light")

# Below this there is no variogram worth fitting. Four is already generous for
# kriging - geostatistics texts want dozens - but it is the point at which the
# result stops being "copy the one reading you have".
MIN_ANCHORS = 4

# An anchor must be describing the same weather as the sections it is standing
# in for. Older than this and it is describing a different hour.
MAX_ANCHOR_AGE_MIN = 30.0

# Two nodes at the same coordinates make the kriging matrix singular.
MIN_SEPARATION_M = 0.25


def _coords(section: dict) -> Optional[tuple]:
    """A section's position in the house, or None if it has never been placed."""
    meta = (section or {}).get("meta") or {}
    try:
        return float(meta["x"]), float(meta["y"])
    except (KeyError, TypeError, ValueError):
        return None


def _anchor_reading(section: dict) -> Optional[dict]:
    """This section's own measured reading, if it is recent enough to trust.

    _clean() is used rather than the raw record so a failed sensor reads as None
    and is excluded, instead of contributing -999 to a variogram.
    """
    latest = _clean((section or {}).get("latest") or {})
    if not latest:
        return None
    ts = latest.get("timestamp")
    try:
        age_min = (_server_now_ms() - float(ts)) / 60000.0
    except (TypeError, ValueError):
        return None
    if not (-MAX_ANCHOR_AGE_MIN <= age_min <= MAX_ANCHOR_AGE_MIN):
        return None
    if latest.get("temperature") is None or latest.get("humidity") is None:
        return None
    return latest


def _krige_field(xs, ys, zs, tx, ty):
    """One field, kriged onto the target points. (values, variances) or None.

    Tries an ordinary variogram first and falls back to linear, which is the
    most forgiving model when there are few points. A singular matrix - from
    collinear or near-duplicate anchors - raises, and is reported rather than
    silently producing nonsense.
    """
    from pykrige.ok import OrdinaryKriging

    for model in ("spherical", "linear"):
        try:
            ok = OrdinaryKriging(
                np.asarray(xs, dtype=float),
                np.asarray(ys, dtype=float),
                np.asarray(zs, dtype=float),
                variogram_model=model,
                enable_plotting=False,
                coordinates_type="euclidean",
            )
            z, ss = ok.execute("points",
                               np.asarray(tx, dtype=float),
                               np.asarray(ty, dtype=float))
            vals = np.asarray(z, dtype=float).ravel()
            var = np.asarray(ss, dtype=float).ravel()
            if np.all(np.isfinite(vals)):
                return vals, var, model
        except Exception:
            continue
    return None


def interpolate_house(house_id: str, house: Optional[dict] = None,
                      now: Optional[datetime] = None) -> dict:
    """Estimate the microclimate of every placed section without a live reading.

    `house` is passed in by the engine, which has already fetched the whole farm
    for its tick. Re-fetching here would download the same document a second
    time every cycle, which is how /farm/houses.json previously turned into
    roughly 10 GB of egress a day.

    Deliberately synchronous. The engine pass runs inside asyncio.to_thread, so
    an async function here would need an event loop that does not exist on that
    thread.
    """
    now = now or datetime.now(timezone.utc)
    if house is None:
        house = _fb_get(f"/farm/houses/{house_id}.json") or {}
    sections = (house or {}).get("sections") or {}

    anchors, targets, unplaced = [], [], []
    for sid, sec in sections.items():
        if not isinstance(sec, dict):
            continue
        xy = _coords(sec)
        if xy is None:
            unplaced.append(sid)
            continue
        reading = _anchor_reading(sec)
        if reading is not None:
            anchors.append({"id": sid, "x": xy[0], "y": xy[1], "r": reading})
        else:
            targets.append({"id": sid, "x": xy[0], "y": xy[1]})

    result = {"house": house_id, "anchors": len(anchors), "targets": len(targets),
              "unplaced": unplaced, "written": 0, "status": "ok"}

    if not targets:
        result["status"] = "nothing-to-estimate"
        return result

    if len(anchors) < MIN_ANCHORS:
        # The honest outcome, not a failure to hide. With fewer anchors than
        # this, kriging degenerates to nearest-neighbour with a fabricated
        # confidence interval, and a farmer would be shown a number that looks
        # measured and is not.
        result["status"] = "insufficient-anchors"
        result["message"] = (
            f"{len(anchors)} section(s) reporting, {MIN_ANCHORS} needed before "
            f"neighbouring readings can estimate an unmonitored zone.")
        return result

    # Near-duplicate anchors make the kriging matrix singular. Keep the first of
    # any cluster rather than failing the whole house.
    kept = []
    for a in anchors:
        if all(math.dist((a["x"], a["y"]), (k["x"], k["y"])) >= MIN_SEPARATION_M
               for k in kept):
            kept.append(a)
    if len(kept) < MIN_ANCHORS:
        result["status"] = "anchors-too-close"
        result["message"] = (f"{len(anchors)} anchors collapse to {len(kept)} distinct "
                             f"positions; they need spreading out.")
        return result
    anchors = kept
    result["anchors"] = len(anchors)

    xs = [a["x"] for a in anchors]
    ys = [a["y"] for a in anchors]
    tx = [t["x"] for t in targets]
    ty = [t["y"] for t in targets]

    fields, models = {}, {}
    for f in FIELDS:
        zs = [a["r"].get(f) for a in anchors]
        if any(z is None for z in zs):
            continue                      # that sensor failed somewhere; skip the field
        out = _krige_field(xs, ys, zs, tx, ty)
        if out is None:
            continue
        vals, var, model = out
        fields[f] = (vals, var)
        models[f] = model

    if "temperature" not in fields or "humidity" not in fields:
        result["status"] = "kriging-failed"
        result["message"] = ("Could not fit a variogram to the anchor layout - "
                             "they may be collinear.")
        return result

    stamp = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    written = 0
    for i, t in enumerate(targets):
        est = {}
        for f, (vals, var) in fields.items():
            v = float(vals[i])
            if f == "humidity":
                v = max(0.0, min(100.0, v))
            elif f == "light":
                v = max(0.0, v)
            est[f] = round(v, 2)
            # Kriging variance, as a standard deviation in the field's own
            # units. This is what makes an estimate auditable: a zone far from
            # every anchor carries a visibly wider error than one between two.
            est[f + "Sd"] = round(float(math.sqrt(max(0.0, var[i]))), 3)

        # Recomputed from the estimated pair rather than kriged on its own, so
        # temperature, humidity and VPD stay physically consistent with each
        # other. Interpolating VPD separately can produce a triple that no real
        # air could have.
        est["vpd"] = vpd_kpa(est["temperature"], est["humidity"])

        est.update({
            "estimatedAt": stamp,
            "timestampMs": int(_server_now_ms()),
            "method": "ordinary-kriging",
            "variogram": models.get("temperature"),
            "anchors": [a["id"] for a in anchors],
            "anchorCount": len(anchors),
            "isInterpolated": True,
        })
        _fb_put(f"/farm/houses/{house_id}/sections/{t['id']}/estimated.json", est)
        written += 1

    result["written"] = written
    result["variogram"] = models
    return result


def interpolate_all(houses: dict, now: Optional[datetime] = None) -> dict:
    """Every house in one pass, using the farm document the engine already holds."""
    out = {}
    for hid, h in (houses or {}).items():
        if not isinstance(h, dict):
            continue
        try:
            out[hid] = interpolate_house(hid, h, now)
        except Exception as e:                     # never let this stop the clock
            out[hid] = {"status": "error", "message": str(e)}
            print(f"[SPATIAL] {hid} failed: {e}")
    return out
