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

    A singular matrix - from collinear or near-duplicate anchors - raises, and
    is reported rather than silently producing nonsense.

    LINEAR IS TRIED FIRST WHEN ANCHORS ARE FEW, and the reason is a bug this
    code shipped with. Spherical was tried first, with linear kept only as a
    fallback for when spherical RAISED. Spherical does not raise on few points:
    it fits a variogram whose range is shorter than the spacing between the
    sensors, decides no anchor is close enough to any target to be informative,
    and returns the plain mean of the anchors for every target - which is
    exactly what ordinary kriging should do with that variogram, so nothing
    anywhere reports a problem.

    Measured on five anchors spanning 25.0-28.5 C with a clear gradient:

        spherical   -> [26.8, 26.8, 26.8, 26.8]   range 3.03 m, anchors 5-10 m apart
        linear      -> [28.43, 26.86, 27.08, 25.34]

    26.8 is the mean of the five. The left-hand column is four estimates that
    look measured, carry a confidence interval, and contain no information.
    """
    from pykrige.ok import OrdinaryKriging

    zs_arr = np.asarray(zs, dtype=float)
    z_mean = float(np.mean(zs_arr))
    z_spread = float(np.ptp(zs_arr))

    # LINEAR FIRST, ALWAYS. This used to switch to spherical at eight anchors or
    # more, on the assumption that a fitted range becomes trustworthy once the
    # points are dense. That assumption was never measured, and it is wrong.
    # Held-out reconstruction error on a simulated 10 x 14 m house, same points,
    # only the variogram differing:
    #
    #     anchors      linear     spherical
    #           6       0.246         0.497
    #           7       0.241         0.460
    #           8       0.237         0.486
    #          10       0.194         0.438
    #
    # Linear wins at every count and keeps improving as anchors are added, while
    # spherical stalls near 0.45. The threshold did not trade accuracy for
    # robustness - it simply made the estimate worse above eight anchors, and
    # showed up as reconstruction error going UP when a house gained a sensor.
    #
    # Spherical stays as a fallback for the case where linear fails outright.
    models = ("linear", "spherical")

    for model in models:
        try:
            ok = OrdinaryKriging(
                np.asarray(xs, dtype=float),
                np.asarray(ys, dtype=float),
                zs_arr,
                variogram_model=model,
                enable_plotting=False,
                coordinates_type="euclidean",
            )
            z, ss = ok.execute("points",
                               np.asarray(tx, dtype=float),
                               np.asarray(ty, dtype=float))
            vals = np.asarray(z, dtype=float).ravel()
            var = np.asarray(ss, dtype=float).ravel()
            if not np.all(np.isfinite(vals)):
                continue
            # Reject a collapse to the mean. The anchors disagree by z_spread,
            # so an estimate that equals their average at every target has
            # thrown away the only thing kriging was asked to use - where the
            # sensors are. Checked against the mean rather than against the
            # spread of the outputs, so it also catches a single target.
            if z_spread > 0.5 and np.all(np.abs(vals - z_mean) < 0.02 * z_spread):
                continue
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
