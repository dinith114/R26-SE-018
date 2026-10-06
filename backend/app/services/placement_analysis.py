"""Where the sensors should stay, and how far one sensor reaches - from real readings.

The panel at PP2 asked for three things this module exists to answer:

  1. WHAT DATA decides the placement, shown as a flow - not "the algorithm
     picked these". Every step below returns its own numbers so the app can
     show the flow with this house's data in it.
  2. THE VARIATION in the readings - sensor noise, failed reads, sensor bias,
     and how much the sections genuinely differ. A placement chosen from
     differences smaller than the sensors' own error is choosing noise.
  3. EVALUATION METRICS - error on readings the placement never saw, against
     the obvious alternatives (a regular grid, random sensors, and - when the
     house is small enough to try every option - the best possible choice).

And the question asked out loud: what is ONE NODE's maximum coverage?

THE FLOW
--------
  raw readings      every record the nodes wrote during calibration
  cleaning          failed (-999), missing and impossible values are DROPPED,
                    never replaced (see readings.py for why that distinction
                    cost a real bug)
  sensor bias       if the nodes were run side by side first (co-location),
                    each node's offset from the group is measured and removed,
                    so a difference between two places is the place and not the
                    sensor
  10-minute means   nodes do not report in step; a bucket is one moment
  fields            temperature and humidity as measured, VPD computed from the
                    pair - VPD is what drives the watering model
  variation         per node: mean, spread, noise; across nodes: how far apart
                    the sections really are, against two sensor errors
  coverage          every PAIR of nodes: how different are they, against how
                    far apart. One node can stand for a spot only while that
                    difference stays inside the sensor's own accuracy - the
                    distance where it crosses is the coverage radius
  leave-one-out     hide each node, estimate it from the others, as production
                    would - the cross-check on the coverage figure
  placement         PySensors (SSPOR) chooses k sections from the EARLIER
                    readings, kriging rebuilds the rest, error is measured on
                    the LATER readings; grid / random / greedy / best-possible
                    are scored the same way

Everything here is a pure function of the readings passed in. No Firebase, no
generated data, nothing random that is not seeded.
"""
from __future__ import annotations

import itertools
import math
import random
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from app.services import readings as rd
from app.services.kriging import idw_field, krige_field

BUCKET_MIN = 10
FIELDS = ("temperature", "humidity", "vpd")
BASE_FIELDS = ("temperature", "humidity")
UNITS = {"temperature": "°C", "humidity": "%", "vpd": "kPa"}

# What "close enough" means, per field: the DHT22's own accuracy. A difference
# smaller than this cannot be told apart from two sensors disagreeing.
#   temperature  +/-0.5 C       datasheet
#   humidity     +/-2 % RH      datasheet
#   vpd          0.10 kPa       those two propagated through the VPD formula at
#                               a typical 30 C / 70 % shade-house afternoon:
#                               dVPD/dRH x 2 % = 0.085, dVPD/dT x 0.5 C = 0.037,
#                               combined sqrt(0.085^2 + 0.037^2) = 0.093 -> 0.10
TOLERANCE = {"temperature": 0.5, "humidity": 2.0, "vpd": 0.10}

# Same thresholds the runtime estimator uses (spatial_service.FLAT_FIELD_SPAN):
# below this spread the anchor mean is the honest estimate.
FLAT_SPAN = {"temperature": 1.0, "humidity": 4.0}

MIN_ANCHORS = 4                 # spatial_service.MIN_ANCHORS - kriging below this refuses
MIN_COMMON_BUCKETS = 24         # four hours of overlap, at least
TEST_FRACTION = 0.4
MAX_SCORE_SNAPSHOTS = 48        # scoring cost is kriging calls; evenly spaced subset
RANDOM_DRAWS = 6
EXHAUSTIVE_MAX = 35             # try every subset when there are no more than this
MAX_K = 8
SEED = 17
MIN_COLOCATION_BUCKETS = 3      # 30 minutes side by side


# ── 1-3. raw readings, cleaning, buckets ────────────────────────────────────

def _bucket_of(ts_ms: float) -> int:
    return int(float(ts_ms) // (BUCKET_MIN * 60000.0))


def collect(histories: Dict[str, dict]) -> Tuple[dict, dict]:
    """(per-section stats, per-section buckets) from the raw history records.

    buckets[sid][b] = {"temperature": [..], "humidity": [..]} - every MEASURED
    value that fell in that 10-minute bucket. Means are taken later, so the
    within-bucket spread (a noise estimate) survives.
    """
    stats, buckets = {}, {}
    for sid, hist in histories.items():
        s = {"records": 0, "first": None, "last": None,
             "rejected": {f: {"missing": 0, "failed": 0, "implausible": 0}
                          for f in BASE_FIELDS + ("light",)},
             "valid": {f: 0 for f in BASE_FIELDS + ("light",)}}
        b_out: Dict[int, dict] = {}
        for rec in (hist or {}).values():
            if not isinstance(rec, dict):
                continue
            ts = rec.get("timestamp")
            try:
                ts = float(ts)
            except (TypeError, ValueError):
                continue
            s["records"] += 1
            s["first"] = ts if s["first"] is None else min(s["first"], ts)
            s["last"] = ts if s["last"] is None else max(s["last"], ts)
            for f in BASE_FIELDS + ("light",):
                why = rd.why_rejected(rec, f)
                if why:
                    s["rejected"][f][why] += 1
                else:
                    s["valid"][f] += 1
            t = rd.value(rec, "temperature")
            h = rd.value(rec, "humidity")
            # A DHT22 reports both or neither; one without the other is a
            # half-failed read, and VPD from it would be wrong.
            if t is None or h is None:
                continue
            slot = b_out.setdefault(_bucket_of(ts), {"temperature": [], "humidity": []})
            slot["temperature"].append(t)
            slot["humidity"].append(h)
        stats[sid] = s
        buckets[sid] = b_out
    return stats, buckets


def _means(buckets: Dict[str, dict]) -> Dict[str, Dict[int, dict]]:
    out = {}
    for sid, bs in buckets.items():
        out[sid] = {b: {f: float(np.mean(v[f])) for f in BASE_FIELDS} for b, v in bs.items()}
    return out


# ── 4. sensor bias from co-location ─────────────────────────────────────────

def colocation_offsets(means: Dict[str, Dict[int, dict]], start_ms: float, end_ms: float
                       ) -> Optional[dict]:
    """Each node's offset from the group while every node sat in one spot.

    Offset = the median, over the co-location buckets, of (this node minus the
    median of all nodes in that bucket). The median rather than the mean, so one
    node warming in a sunbeam for ten minutes does not set everyone's offset.

    None if the window holds too little: fewer than three nodes reporting
    together, or fewer than MIN_COLOCATION_BUCKETS buckets.
    """
    b0, b1 = _bucket_of(start_ms) + 1, _bucket_of(end_ms) - 1     # whole buckets inside
    window = range(b0, b1 + 1)
    diffs: Dict[str, Dict[str, list]] = {sid: {f: [] for f in BASE_FIELDS} for sid in means}
    used = 0
    for b in window:
        present = [sid for sid in means if b in means[sid]]
        if len(present) < 3:
            continue
        used += 1
        for f in BASE_FIELDS:
            med = float(np.median([means[sid][b][f] for sid in present]))
            for sid in present:
                diffs[sid][f].append(means[sid][b][f] - med)
    if used < MIN_COLOCATION_BUCKETS:
        return None
    offsets = {}
    for sid, d in diffs.items():
        if len(d["temperature"]) < MIN_COLOCATION_BUCKETS:
            offsets[sid] = None                 # this node was not there for it
            continue
        offsets[sid] = {f: round(float(np.median(d[f])), 3) for f in BASE_FIELDS}
    return {"buckets": used, "startMs": start_ms, "endMs": end_ms, "offsets": offsets}


# ── 5. the aligned matrices ─────────────────────────────────────────────────

def aligned(means: Dict[str, Dict[int, dict]], ids: Sequence[str],
            offsets: Optional[dict], after_ms: Optional[float]) -> Tuple[List[int], Dict[str, np.ndarray]]:
    """Buckets every section reported in, as (B, S) matrices per field.

    Bias-corrected when offsets exist; VPD is computed from each corrected
    (temperature, humidity) pair, exactly as the runtime estimator recomputes it
    from its two kriged fields rather than interpolating VPD on its own.
    """
    first = _bucket_of(after_ms) + 1 if after_ms else None
    common = None
    for sid in ids:
        keys = {b for b in means.get(sid, {}) if first is None or b >= first}
        common = keys if common is None else common & keys
    order = sorted(common or [])
    mats = {f: np.zeros((len(order), len(ids))) for f in FIELDS}
    for j, sid in enumerate(ids):
        off = ((offsets or {}).get(sid) or {}) if offsets else {}
        for i, b in enumerate(order):
            t = means[sid][b]["temperature"] - (off.get("temperature") or 0.0)
            h = means[sid][b]["humidity"] - (off.get("humidity") or 0.0)
            h = min(100.0, max(0.0, h))
            mats["temperature"][i, j] = t
            mats["humidity"][i, j] = h
            mats["vpd"][i, j] = rd.vpd_kpa(t, h)
    return order, mats


# ── 6. variation ────────────────────────────────────────────────────────────

def variation(order: List[int], mats: Dict[str, np.ndarray], ids: Sequence[str],
              raw_buckets: Dict[str, dict], tz_offset_min: int) -> dict:
    per_node = {}
    for j, sid in enumerate(ids):
        node = {}
        for f in FIELDS:
            col = mats[f][:, j]
            node[f] = {"mean": round(float(col.mean()), 3), "sd": round(float(col.std()), 3),
                       "min": round(float(col.min()), 3), "max": round(float(col.max()), 3)}
        # Short-term noise: the spread of raw readings inside one 10-minute
        # bucket, typically. Includes real flicker as well as instrument noise,
        # so it is an upper bound on the noise, not a measurement of it alone.
        for f in BASE_FIELDS:
            sds = [float(np.std(v[f])) for v in raw_buckets.get(sid, {}).values() if len(v[f]) >= 3]
            node[f]["noise"] = round(float(np.median(sds)), 3) if sds else None
        per_node[sid] = node

    between = {}
    hours = [((b * BUCKET_MIN + tz_offset_min) / 60.0) % 24 for b in order]
    day = np.array([6 <= h < 18 for h in hours])
    for f in FIELDS:
        spread = mats[f].max(axis=1) - mats[f].min(axis=1) if mats[f].size else np.array([])
        tol2 = 2 * TOLERANCE[f]
        between[f] = {
            "meanSpread": round(float(spread.mean()), 3) if spread.size else None,
            "p95Spread": round(float(np.percentile(spread, 95)), 3) if spread.size else None,
            "maxSpread": round(float(spread.max()), 3) if spread.size else None,
            "daySpread": round(float(spread[day].mean()), 3) if spread.size and day.any() else None,
            "nightSpread": round(float(spread[~day].mean()), 3) if spread.size and (~day).any() else None,
            "twoSensorErrors": tol2,
            # The fraction of moments when the sections differed by more than
            # two sensors could disagree on their own - i.e. when the house was
            # measurably NOT uniform.
            "fractionBeyondSensorError": round(float((spread > tol2).mean()), 3) if spread.size else None,
            "unit": UNITS[f],
        }
    return {"perNode": per_node, "between": between}


# ── 7. coverage: difference against distance ────────────────────────────────

def coverage(mats: Dict[str, np.ndarray], ids: Sequence[str], coords: Dict[str, Tuple[float, float]]) -> dict:
    """How far one node can stand for another, from every pair of nodes.

    For a pair at distance d, the mean absolute difference between their
    readings is exactly the error you would make by putting ONE sensor at the
    first spot and using it for the second. Fit that against distance; the
    distance where the fitted line reaches the sensor's own accuracy is how far
    one node reaches. Reported per field, and the smallest is the answer,
    because a node only covers a spot if it covers every quantity there.
    """
    pairs = []
    for i, j in itertools.combinations(range(len(ids)), 2):
        a, b = ids[i], ids[j]
        d = math.dist(coords[a], coords[b])
        row = {"a": a, "b": b, "distance": round(d, 2)}
        for f in FIELDS:
            row[f] = round(float(np.mean(np.abs(mats[f][:, i] - mats[f][:, j]))), 4)
        pairs.append(row)

    fields = {}
    for f in FIELDS:
        tol = TOLERANCE[f]
        ds = np.array([p["distance"] for p in pairs], dtype=float)
        es = np.array([p[f] for p in pairs], dtype=float)
        out = {"tolerance": tol, "unit": UNITS[f], "pairs": len(pairs)}
        if len(pairs) < 3 or np.ptp(ds) < 1e-6:
            out.update(status="too-few-pairs", radius=None)
            fields[f] = out
            continue
        slope, intercept = np.polyfit(ds, es, 1)
        resid = es - (intercept + slope * ds)
        ss_tot = float(((es - es.mean()) ** 2).sum())
        r2 = 1.0 - float((resid ** 2).sum()) / ss_tot if ss_tot > 0 else 0.0
        dmin, dmax = float(ds.min()), float(ds.max())
        out.update(slope=round(float(slope), 5), intercept=round(float(intercept), 4),
                   r2=round(r2, 3), minDistance=round(dmin, 2), maxDistance=round(dmax, 2))
        if intercept >= tol:
            # Even two nodes side by side (distance -> 0) differ by more than the
            # tolerance: either the bias was not removed or the house changes
            # within less than the closest spacing.
            out.update(status="below-spacing", radius=None,
                       note=f"Nodes differ by more than ±{tol} {UNITS[f]} even at the closest spacing.")
        elif slope <= 1e-9:
            out.update(status="no-growth", radius=None, atLeast=round(dmax, 2),
                       note="The difference does not grow with distance across this house.")
        else:
            r = (tol - intercept) / slope
            out.update(radius=round(float(r), 2),
                       status="measured" if r <= dmax else "extrapolated")
        fields[f] = out

    radii = [(f, v["radius"]) for f, v in fields.items() if v.get("radius") is not None]
    limiting = min(radii, key=lambda kv: kv[1]) if radii else None
    lower_bounds = [v["atLeast"] for v in fields.values() if v.get("atLeast") is not None]
    combined = None
    if limiting:
        combined = {"radius": limiting[1], "limitedBy": limiting[0],
                    "areaM2": round(math.pi * limiting[1] ** 2, 1),
                    "status": fields[limiting[0]]["status"]}
    elif lower_bounds and all(v["status"] == "no-growth" for v in fields.values()):
        combined = {"radius": None, "atLeast": min(lower_bounds), "status": "no-growth",
                    "limitedBy": None}
    return {"pairs": pairs, "fields": fields, "node": combined}


# ── estimation, the way production does it ──────────────────────────────────

def _estimate(xs, ys, zs, tx, ty, field: str, k: int) -> Tuple[List[float], str]:
    """Estimate one field at the targets. Mirrors spatial_service's order:
    kriging, then the anchor mean for a flat field, then IDW. Below
    MIN_ANCHORS production refuses outright; scoring uses IDW there and the
    row is marked not usable at runtime."""
    if k >= MIN_ANCHORS:
        got = krige_field(xs, ys, zs, tx, ty)
        if got is not None:
            return list(np.asarray(got[0], dtype=float)), "kriging"
        if np.ptp(zs) <= FLAT_SPAN.get(field, 0.0):
            m = float(np.mean(zs))
            return [m] * len(tx), "uniform"
    vals, _ = idw_field(xs, ys, zs, tx, ty)
    return vals, "idw"


def _snapshots(n: int, cap: int) -> List[int]:
    if n <= cap:
        return list(range(n))
    return sorted({int(round(i * (n - 1) / (cap - 1))) for i in range(cap)})


def score(sel: Sequence[int], mats: Dict[str, np.ndarray], rows: Sequence[int],
          xy: np.ndarray) -> Optional[dict]:
    """Error at the sections NOT selected, over the given rows (snapshots).

    Temperature and humidity are estimated; VPD is computed from the two
    estimates and compared with the measured VPD - the same consistency rule
    the runtime estimator follows.
    """
    S = xy.shape[0]
    rest = [i for i in range(S) if i not in set(sel)]
    if not rest or len(sel) < 2:
        return None
    errs = {f: [] for f in FIELDS}
    methods = set()
    sx, sy = xy[list(sel), 0], xy[list(sel), 1]
    tx, ty = xy[rest, 0], xy[rest, 1]
    for r in rows:
        est = {}
        for f in BASE_FIELDS:
            v, m = _estimate(sx, sy, mats[f][r, list(sel)], tx, ty, f, len(sel))
            est[f] = np.asarray(v, dtype=float)
            methods.add(m)
        est_h = np.clip(est["humidity"], 0.0, 100.0)
        est["vpd"] = np.array([rd.vpd_kpa(t, h) for t, h in zip(est["temperature"], est_h)])
        for f in FIELDS:
            errs[f].extend(np.abs(est[f] - mats[f][r, rest]).tolist())
    out = {}
    for f in FIELDS:
        e = np.asarray(errs[f])
        out[f] = {"mae": round(float(e.mean()), 4),
                  "rmse": round(float(np.sqrt((e ** 2).mean())), 4),
                  "max": round(float(e.max()), 4)}
    # One number to compare layouts by: error in units of sensor accuracy,
    # averaged over the three fields. 1.0 = as wrong as the sensor itself.
    out["normalized"] = round(float(np.mean([out[f]["mae"] / TOLERANCE[f] for f in FIELDS])), 4)
    out["estimators"] = sorted(methods)
    return out


# ── 8. leave-one-out ────────────────────────────────────────────────────────

def leave_one_out(mats, ids, xy, rows) -> List[dict]:
    out = []
    S = len(ids)
    for j in range(S):
        others = [i for i in range(S) if i != j]
        sc = score(others, mats, rows, xy)
        nearest = min(math.dist(xy[j], xy[i]) for i in others)
        out.append({"section": ids[j], "nearest": round(nearest, 2),
                    **({f: sc[f] for f in FIELDS} if sc else {}),
                    "estimators": sc["estimators"] if sc else []})
    return out


# ── 9. placement ────────────────────────────────────────────────────────────

def _sspor(fit_stack: np.ndarray, k: int) -> Optional[List[int]]:
    try:
        from pysensors.reconstruction import SSPOR
        from pysensors.basis import SVD
    except Exception:
        return None
    if k >= fit_stack.shape[1]:
        return list(range(fit_stack.shape[1]))
    modes = int(min(20, max(2, fit_stack.shape[0] - 1), max(2, fit_stack.shape[1] - 1)))
    model = SSPOR(n_sensors=int(k), basis=SVD(n_basis_modes=modes))
    model.fit(fit_stack)
    return [int(i) for i in np.asarray(model.selected_sensors).ravel()[:k]]


def _farthest(xy: np.ndarray, k: int) -> List[int]:
    """Spread out as evenly as the existing positions allow - the 'grid' a
    grower would choose by eye, over the sections that actually exist."""
    centre = xy.mean(axis=0)
    chosen = [int(np.argmin(((xy - centre) ** 2).sum(axis=1)))]
    while len(chosen) < k:
        d = np.full(xy.shape[0], np.inf)
        for c in chosen:
            d = np.minimum(d, ((xy - xy[c]) ** 2).sum(axis=1))
        d[chosen] = -np.inf
        chosen.append(int(np.argmax(d)))
    return chosen


def _kriging_greedy(xy: np.ndarray, k: int) -> List[int]:
    """Add the point kriging is least certain about. Needs no readings at all -
    kriging variance depends only on positions - so it is the placement that
    uses the least information, which makes it a useful lower reference."""
    chosen = _farthest(xy, min(k, 3))
    while len(chosen) < k:
        got = krige_field(xy[chosen, 0], xy[chosen, 1], np.arange(len(chosen), dtype=float),
                          xy[:, 0], xy[:, 1]) if len(chosen) >= MIN_ANCHORS else None
        if got is not None:
            var = np.asarray(got[1], dtype=float)
            var[chosen] = -np.inf
            chosen.append(int(np.argmax(var)))
            continue
        d = np.full(xy.shape[0], np.inf)
        for c in chosen:
            d = np.minimum(d, ((xy - xy[c]) ** 2).sum(axis=1))
        d[chosen] = -np.inf
        chosen.append(int(np.argmax(d)))
    return chosen


def elbow(points: List[Tuple[int, float]]) -> Optional[int]:
    """Knee of a falling error curve; same construction as house_planner._elbow.
    The curve is made monotone first - 'the best possible with at most n' - so a
    noisy rise cannot recommend paying more for a worse layout."""
    pts = [(x, y) for x, y in points if y is not None]
    if not pts:
        return None
    if len(pts) < 3:
        return pts[-1][0]
    best, mono = float("inf"), []
    for x, y in pts:
        best = min(best, y)
        mono.append((x, best))
    (x1, y1), (x2, y2) = mono[0], mono[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy) or 1.0
    pick, far = mono[0][0], -1.0
    for x, y in mono:
        d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / norm
        if d > far:
            pick, far = x, d
    return pick


CANDIDATES = ("pysensors", "grid", "kriging_greedy")


def _anomaly_stack(mats, rows) -> np.ndarray:
    """What SSPOR is fitted on: each field's DEPARTURE from the house mean at
    each moment, standardised, the three fields stacked as extra snapshots.

    Removing the house mean first is the point. The whole shade house warms and
    cools together every day; left in, that shared swing is the biggest mode in
    the data, and SSPOR spends its sensors explaining something any one sensor
    already captures. Placement is about where the house DIFFERS. Measured on
    test data: at four sensors the un-centred fit scored 0.84 against a regular
    grid's 0.36 (normalised error); centred, 0.15.
    """
    blocks = []
    for f in FIELDS:
        m = mats[f][rows]
        m = m - m.mean(axis=1, keepdims=True)
        sd = float(m.std()) or 1.0
        blocks.append(m / sd)
    return np.vstack(blocks)


def placement(mats, ids, xy, fit_rows, test_rows) -> dict:
    """Which k sections to keep, for every k, chosen and scored honestly.

    THREE PERIODS, IN TIME ORDER, and the order is the method:

      choose     the first 75 % of the fit period. Each candidate method picks
                 its sensors here (SSPOR learns from it; grid and the kriging-
                 variance greedy only need positions).
      validate   the rest of the fit period. The methods are compared here, and
                 the best one for each k is SELECTED.
      test       the later 40 % of the whole window, which no method and no
                 selection has seen. Every error reported is measured here.

    Why the selection step exists: SSPOR does not always win. On a smooth one-
    directional gradient an evenly spread grid can reconstruct better, and
    which is better depends on the house. Picking the winner on the TEST data
    and then quoting its test error would be grading your own exam; picking on
    validate and quoting test is not.

    'best'/'worst' come from trying every subset ON THE TEST PERIOD. They are
    the limits of what any layout could have achieved - a yardstick for the
    selected layout, not a method anyone could have used in advance.
    """
    S = len(ids)
    kmax = min(S - 1, MAX_K)
    if S < 3:
        return {"rows": [], "recommended": None,
                "note": "At least three positioned sections are needed to compare layouts."}

    n_val = max(2, len(fit_rows) // 4)
    choose_rows, val_all = fit_rows[:-n_val], fit_rows[-n_val:]
    val_rows = [val_all[i] for i in _snapshots(len(val_all), MAX_SCORE_SNAPSHOTS // 2)]
    stack = _anomaly_stack(mats, choose_rows)

    rng = random.Random(SEED)
    rows = []
    for k in range(2, kmax + 1):
        row = {"sensors": k, "runtimeUsable": k >= MIN_ANCHORS,
               "estimator": "kriging" if k >= MIN_ANCHORS else "idw", "methods": {}}
        sp = _sspor(stack, k)
        candidates = {"kriging_greedy": _kriging_greedy(xy, k), "grid": _farthest(xy, k)}
        if sp is not None:
            candidates = {"pysensors": sp, **candidates}
        validation = {}
        for name, sel in candidates.items():
            v = score(sel, mats, val_rows, xy)
            validation[name] = v["normalized"] if v else None
            row["methods"][name] = {"sections": [ids[i] for i in sel],
                                    "validation": validation[name],
                                    **(score(sel, mats, test_rows, xy) or {})}
        ok = {n: v for n, v in validation.items() if v is not None}
        row["selected"] = min(ok, key=ok.get) if ok else None
        draws = [score(rng.sample(range(S), k), mats, test_rows, xy) for _ in range(RANDOM_DRAWS)]
        draws = [d for d in draws if d]
        if draws:
            row["methods"]["random"] = {
                f: {m: round(float(np.mean([d[f][m] for d in draws])), 4) for m in ("mae", "rmse", "max")}
                for f in FIELDS}
            row["methods"]["random"]["normalized"] = round(float(np.mean([d["normalized"] for d in draws])), 4)
            row["methods"]["random"]["draws"] = len(draws)
        if math.comb(S, k) <= EXHAUSTIVE_MAX:
            scored = []
            for sel in itertools.combinations(range(S), k):
                sc = score(sel, mats, test_rows, xy)
                if sc:
                    scored.append((sc["normalized"], sel, sc))
            if scored:
                scored.sort(key=lambda t: t[0])
                for label, (_, sel, sc) in (("best", scored[0]), ("worst", scored[-1])):
                    row["methods"][label] = {"sections": [ids[i] for i in sel], **sc}
                row["subsetsTried"] = len(scored)
        rows.append(row)

    # The elbow is found on VALIDATION errors of the selected method, so the
    # test period stays untouched by every decision, including how many.
    curve = [(r["sensors"], r["methods"][r["selected"]]["validation"] if r["selected"] else None)
             for r in rows]
    knee = elbow(curve)
    rec = None
    if knee is not None:
        rec = max(knee, MIN_ANCHORS)
        if rec > kmax:
            rec = None
    note = None
    if rec is None:
        note = (f"With {S} sections every one must stay: kriging needs {MIN_ANCHORS} sensors "
                f"to estimate the rest, so there is nothing to take out.")
    elif knee is not None and knee < MIN_ANCHORS:
        note = (f"The error stops improving much after {knee} sensors, but the runtime "
                f"estimator needs {MIN_ANCHORS}, so {rec} is recommended.")
    chosen = next((r for r in rows if r["sensors"] == rec), None)
    return {"rows": rows, "elbow": knee, "recommended": rec, "note": note,
            "selectedMethod": chosen["selected"] if chosen else None,
            "keep": chosen["methods"][chosen["selected"]]["sections"] if chosen and chosen["selected"] else None,
            "periods": {"choose": len(choose_rows), "validate": len(val_all), "test": len(test_rows)}}


# ── the whole flow ──────────────────────────────────────────────────────────

def analyse(histories: Dict[str, dict], coords: Dict[str, Tuple[float, float]],
            colocation: Optional[dict] = None, tz_offset_min: int = 330) -> dict:
    """Run every step and return each step's numbers. Raises ValueError with a
    plain reason when the data cannot support the analysis."""
    ids = [sid for sid in histories if sid in coords]
    if len(ids) < 3:
        raise ValueError(f"{len(ids)} positioned sections have readings; at least 3 are needed.")

    stats, raw_buckets = collect({sid: histories[sid] for sid in ids})
    means = _means(raw_buckets)

    bias = None
    after = None
    if colocation and colocation.get("startMs") and colocation.get("endMs"):
        bias = colocation_offsets(means, float(colocation["startMs"]), float(colocation["endMs"]))
        # The spread-out period starts once the nodes have been carried to their
        # places and settled - the caller says when (house_planner adds 15 min).
        after = float(colocation.get("spreadFromMs") or colocation["endMs"])

    silent = [sid for sid in ids if not means.get(sid)]
    if silent:
        raise ValueError("No usable readings yet from " + ", ".join(silent) + ".")

    order, mats = aligned(means, ids, (bias or {}).get("offsets"), after)
    if len(order) < MIN_COMMON_BUCKETS:
        raise ValueError(
            f"Only {len(order)} ten-minute periods where every section reported; "
            f"{MIN_COMMON_BUCKETS} are needed. A node that keeps dropping out holds the house back.")

    xy = np.array([coords[sid] for sid in ids], dtype=float)
    n_test = max(2, int(len(order) * TEST_FRACTION))
    fit_rows = list(range(len(order) - n_test))
    test_all = list(range(len(order) - n_test, len(order)))
    test_rows = [test_all[i] for i in _snapshots(len(test_all), MAX_SCORE_SNAPSHOTS)]
    all_rows = _snapshots(len(order), MAX_SCORE_SNAPSHOTS)

    bucket_ms = BUCKET_MIN * 60000
    return {
        "sections": ids,
        "positions": {sid: {"x": coords[sid][0], "y": coords[sid][1]} for sid in ids},
        "fieldsUsed": list(FIELDS),
        "tolerance": TOLERANCE,
        "units": UNITS,
        "raw": stats,
        "bias": bias,
        "buckets": {
            "minutes": BUCKET_MIN, "common": len(order),
            "fit": len(fit_rows), "test": n_test, "scoredOn": len(test_rows),
            "fromMs": order[0] * bucket_ms if order else None,
            "toMs": (order[-1] + 1) * bucket_ms if order else None,
            "splitAtMs": order[fit_rows[-1] + 1] * bucket_ms if fit_rows else None,
        },
        "variation": variation(order, mats, ids, raw_buckets, tz_offset_min),
        "coverage": coverage(mats, ids, coords),
        "leaveOneOut": leave_one_out(mats, ids, xy, all_rows),
        "placement": placement(mats, ids, xy, fit_rows, test_rows),
    }
