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
    _fb_get, _fb_put, _server_now_ms, vpd_kpa,
)
from app.services.readings import measured
# The estimators moved to app.services.kriging so they can be tested and reused
# without importing the server. Re-exported under their old names: house_planner
# and the placement analysis import _krige_field from here.
from app.services.kriging import IDW_POWER, idw_field as _idw_field, krige_field as _krige_field  # noqa: F401

# Fields worth estimating: the air, which varies smoothly across a house.
FIELDS = ("temperature", "humidity", "light")

# Below this spread across ALL anchors, a field has no structure a variogram can
# describe - the differences are inside what the instrument can resolve.
#
# DHT22 is specified at +/-0.5 C and +/-2 % RH, so two sensor errors is the point
# at which a difference stops being a measurement of the house and starts being a
# measurement of the sensors.
#
# LIGHT IS HERE TOO, and leaving it out was a mistake worth explaining. The first
# version reasoned "a flat light field means night" and stopped there - but that
# is the argument FOR a fallback, not against one. At 20:15 the anchors read
# 388.9, 0, 0 and 111.7 lux; the variogram could not fit, light got no estimate,
# and the app showed "--" for it while four sensors sat there agreeing that it
# was dark. "--" means no data. Dark is data.
#
# 500 lux, because that is the scale the decisions work at: a watering plan
# reasons about thousands of lux, and no grower acts on a 500 lux difference
# between two ends of a house. Below that spread the house is uniformly dark or
# uniformly shaded, and the anchor mean is the honest answer.
FLAT_FIELD_SPAN = {"temperature": 1.0, "humidity": 4.0, "light": 500.0}

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

    readings.measured() and NOT _clean(). This docstring used to promise that
    _clean() makes "a failed sensor read as None and be excluded" - it never
    did: _clean() substitutes 28 C / 70 % / 0 lux, so a node whose DHT22 had
    failed became an anchor reporting 28 C, and a node with no light sensor
    became an anchor reporting darkness. measured() drops the field instead.
    """
    latest = measured((section or {}).get("latest") or {})
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


# ── The estimators ──────────────────────────────────────────────────────────
# _idw_field and _krige_field now live in app/services/kriging.py (imported at
# the top under these names). Their history stays here, next to the code that
# depends on it:
#
# IDW EXISTS because ordinary kriging fits a variogram from the VALUES as well as
# the positions, and with four anchors it often cannot. On house H2 a real 2.5 C
# gradient made PyKrige refuse, and every unmonitored zone got NOTHING. IDW needs
# no variogram; it is weaker, has no kriging variance, and is labelled "idw".
#
# LINEAR IS TRIED FIRST, ALWAYS. Spherical on few points fits a range shorter
# than the sensor spacing and returns the plain anchor mean for every target -
# measured on five anchors spanning 25.0-28.5 C:
#     spherical -> [26.8, 26.8, 26.8, 26.8]  (the mean, with confidence intervals)
#     linear    -> [28.43, 26.86, 27.08, 25.34]
# and held-out error on a simulated 10 x 14 m house, same points:
#     anchors   6      7      8      10
#     linear    0.246  0.241  0.237  0.194
#     spherical 0.497  0.460  0.486  0.438
# A collapse to the anchor mean is rejected even when the fit "succeeds".


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

    tx = [t["x"] for t in targets]
    ty = [t["y"] for t in targets]

    def _field_anchors(f):
        """(xs, ys, zs) from the anchors that MEASURED this field, or None.

        Per field, not all-or-nothing. A node built with a DHT22 and no BH1750
        is a perfectly good temperature anchor; skipping light for the whole
        house because that one node has no light sensor - which is what the
        old any(None) check did - threw away every other node's light reading.
        Below MIN_ANCHORS measured values the field is not estimated at all.
        """
        have = [a for a in anchors if a["r"].get(f) is not None]
        if len(have) < MIN_ANCHORS:
            return None
        return ([a["x"] for a in have], [a["y"] for a in have],
                [a["r"][f] for a in have])

    fields, models = {}, {}
    for f in FIELDS:
        got = _field_anchors(f)
        if got is None:
            continue
        fxs, fys, zs = got
        out = _krige_field(fxs, fys, zs, tx, ty)
        if out is None:
            continue
        vals, var, model = out
        fields[f] = (vals, var)
        models[f] = model

    # ── WHEN THERE IS NOTHING TO INTERPOLATE ─────────────────────────────────
    #
    # A variogram cannot be fitted to a field that is FLAT, and that is not a
    # failure - it is the honest shape of the data. Measured on house H2,
    # 30 Aug 2026, four anchors reporting fresh:
    #
    #     temperature  [24.4, 25.3, 25.3, 24.4]   spread 0.9 C   fit failed
    #     humidity     [90.5, 88.8, 89.8, 91.0]   spread 2.2 %   fit failed
    #     light        [4149, 646, 1390, 1739]    wide           fit fine
    #
    # PyKrige had no semivariance structure to work with, so the whole house was
    # reported "kriging-failed" and the two unmonitored zones got NO estimate at
    # all - they showed as if no data existed, while four sensors sat there
    # agreeing with each other.
    #
    # With a spread inside two sensor errors the best available estimate for an
    # unmonitored zone genuinely IS the anchor mean, and saying so is correct
    # rather than lazy.
    #
    # THIS IS NOT THE OLD BUG RETURNING. The variogram bug returned the mean
    # while a real gradient existed, invisibly, with confidence intervals. This
    # returns the mean ONLY when the measured spread is below what the
    # instruments can resolve, says `method: "uniform-field"`, and reports the
    # span it saw so the claim can be checked.
    flat = {}
    for f in FIELDS:
        if f in fields or f not in FLAT_FIELD_SPAN:
            continue
        got = _field_anchors(f)
        if got is None:
            continue
        zs = got[2]
        span = max(zs) - min(zs)
        if span <= FLAT_FIELD_SPAN[f]:
            mean = sum(zs) / len(zs)
            # Spread across the house, as a standard deviation, rather than a
            # kriging variance - there is no kriging here and pretending there
            # was would overstate what this is.
            sd = (sum((z - mean) ** 2 for z in zs) / len(zs)) ** 0.5
            flat[f] = (mean, sd, span)

    # ── STRUCTURE, BUT NO VARIOGRAM ──────────────────────────────────────────
    # Anything kriging could not fit AND the flat path did not claim gets the
    # distance-weighted estimate. The order is deliberate: kriging is the best
    # of the three and carries a real variance; the flat mean is exactly right
    # when the anchors agree; this is for the case both of those decline - real
    # structure that four points cannot pin a variogram to.
    idw = {}
    for f in FIELDS:
        if f in fields or f in flat:
            continue
        got = _field_anchors(f)
        if got is None:
            continue
        fxs, fys, zs = got
        idw[f] = _idw_field(fxs, fys, zs, tx, ty)

    if "temperature" not in fields or "humidity" not in fields:
        missing = [f for f in ("temperature", "humidity") if f not in fields]
        if all(f in flat or f in idw for f in missing):
            if idw:
                result["status"] = "distance-weighted"
                result["message"] = (
                    "No variogram could be fitted, but the anchors do disagree, so "
                    + ", ".join(sorted(idw)) + " are estimated by inverse-distance "
                    "weighting instead. Weaker than kriging, and the figure beside "
                    "each value is how much the nearby anchors disagree rather than "
                    "a kriging variance.")
            else:
                result["status"] = "uniform-field"
                result["message"] = ("No variogram could be fitted because the field is "
                                     "flat: " + ", ".join(
                                         f"{f} varies {flat[f][2]:.1f} across the house"
                                         for f in sorted(flat)) +
                                     ". Estimates are the anchor mean, which is the "
                                     "honest answer when every sensor agrees.")
        else:
            result["status"] = "kriging-failed"
            result["message"] = ("Could not fit a variogram to the anchor layout - "
                                 "they may be collinear.")
            return result

    stamp = now.strftime("%Y-%m-%d %H:%M:%S UTC")
    written = 0
    for i, t in enumerate(targets):
        est = {}
        for f, (vals, spreads) in idw.items():
            v = float(vals[i])
            if f == "humidity":
                v = max(0.0, min(100.0, v))
            elif f == "light":
                v = max(0.0, v)
            est[f] = round(v, 2)
            est[f + "Sd"] = round(float(spreads[i]), 3)
        for f, (mean, sd, _span) in flat.items():
            v = float(mean)
            if f == "humidity":
                v = max(0.0, min(100.0, v))
            elif f == "light":
                v = max(0.0, v)
            est[f] = round(v, 2)
            est[f + "Sd"] = round(float(sd), 3)
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
            # The method that actually produced TEMPERATURE, named exactly.
            # Three estimators live here now and a screen must never present the
            # weakest of them as the strongest.
            "method": ("ordinary-kriging" if "temperature" in fields
                       else "uniform-field" if "temperature" in flat
                       else "idw" if "temperature" in idw
                       else "none"),
            # Which fields came from where, so the report can say which is which.
            "uniformFields": sorted(flat) or None,
            "idwFields": sorted(idw) or None,
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
