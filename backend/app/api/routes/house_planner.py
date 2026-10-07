"""Where to put the sensors in a house that has none yet.

Phase 1 of the placement work. Phase 2 (spatial_service.py) estimates the
sections that have no node FROM the ones that do; this decides where those
nodes should go in the first place, before any hardware exists.

The honest position on what this can and cannot know
----------------------------------------------------
A house with no sensors has no measurements, so nothing here is measured. The
field this module places against is GENERATED from the house's geometry - depth
from the open edge, distance from the walls, sun angle through the day. That is
a physics PRIOR, not data, and the quality of a placement is bounded by how well
that prior matches the real house.

What the validation does and does not prove:

  * It DOES prove that, on a field with known ground truth, choosing points by
    SSPOR reconstructs that field better than a regular grid or random points.
    That is a statement about the METHOD, and it is the statement the report
    makes.
  * It does NOT prove the generated field resembles this particular shade house.
    Nothing available before the sensors are installed could prove that.

Once real nodes are reporting, their readings can replace the generated
snapshots and the same code re-runs on measured data. The interface does not
change.

Why kriging is the scorer
-------------------------
Every method is scored by reconstructing held-out snapshots with ORDINARY
KRIGING - imported from spatial_service, not reimplemented - because kriging is
what actually runs in production. Scoring placement with the estimator that will
consume it means a placement cannot look good here and disappoint at runtime.
SSPOR has its own POD-based reconstruction; using it to score itself would
flatter it against the baselines.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.routes.spatial_service import _krige_field
from app.api.deps import require_auth, require_role
from app.services.firebase_auth import ROLE_ADMIN, AuthContext

router = APIRouter()

# ── The candidate grid ──────────────────────────────────────────────────────
# Sensors are placed on a discrete set of candidate points, not anywhere in a
# continuous plane. Half a metre is finer than anyone can position a pole in a
# real shade house, and it keeps the snapshot matrix small enough to decompose
# quickly: a 10 x 14 m house becomes 20 x 28 = 560 candidates.
GRID_SPACING_M = 0.5

# Points are kept this far off the wall. A sensor pressed against the plastic
# reads the wall, not the air the plants are in.
WALL_MARGIN_M = 0.6

# How many synthetic conditions the field is sampled under. Split into fit and
# held-out halves; see _snapshots_simulated().
N_SNAPSHOTS = 120
TEST_FRACTION = 0.4

# Sensor counts the curve is computed over.
#
# The floor is IMPORTED from the spatial service rather than guessed here, and
# the two used to disagree: this file said 3 with a comment claiming "below 3
# kriging has nothing to work with", while spatial_service.MIN_ANCHORS is 4 and
# returns "insufficient-anchors" below it. So a farmer could be shown a 3-sensor
# row, choose it, and end up with a house where every unmonitored zone stayed
# permanently blank - while the result screen promised those sections would
# "keep working, estimated from the ones that kept theirs". Measured on a
# 6-section test house: keep 3, and kriging wrote 0 estimates for all 3 targets.
#
# One number, owned by the module that enforces it.
from app.api.routes.spatial_service import MIN_ANCHORS as _MIN_ANCHORS
MIN_SENSORS = _MIN_ANCHORS
# Above 10 a house this size is saturated and the farmer is buying hardware that
# changes nothing.
MAX_SENSORS_CAP = 10

# One node: NodeMCU ESP32 + DHT22 + BH1750 + capacitive probe, from the
# project's own receipts.
NODE_COST_LKR = 2350

# Everything random in here is seeded, so a farmer who plans the same house
# twice gets the same answer and a reviewer can reproduce the table.
SEED = 17


def _candidate_grid(width: float, length: float) -> np.ndarray:
    """Every point a sensor may be placed at, as an (n_points, 2) array."""
    xs = np.arange(WALL_MARGIN_M, max(WALL_MARGIN_M + 0.01, width - WALL_MARGIN_M)
                   + 1e-9, GRID_SPACING_M)
    ys = np.arange(WALL_MARGIN_M, max(WALL_MARGIN_M + 0.01, length - WALL_MARGIN_M)
                   + 1e-9, GRID_SPACING_M)
    if len(xs) == 0:
        xs = np.array([width / 2.0])
    if len(ys) == 0:
        ys = np.array([length / 2.0])
    gx, gy = np.meshgrid(xs, ys)
    return np.column_stack([gx.ravel(), gy.ravel()])


def _field(coords: np.ndarray, width: float, length: float,
           hour: float, cloud: float, ambient: float,
           rng: random.Random) -> np.ndarray:
    """Temperature over every candidate point, under one set of conditions.

    The same two gradients the spatial simulator uses, because they are the two
    a shade house actually has:

      * depth from the open, sun-facing edge - light falls off into the house
        and temperature follows it
      * distance from the side walls - the middle of a span runs warmer than
        the edges

    `cloud` scales the whole solar term, which is what makes the snapshots
    differ from one another in SHAPE and not merely in offset. A set of
    snapshots that differed only by a constant would have rank 1, and every
    placement method would score identically because one sensor would be enough
    to reconstruct all of them.
    """
    x, y = coords[:, 0], coords[:, 1]
    depth = y / max(length, 1e-6)
    shade = np.exp(-2.2 * depth)
    edge = 1.0 - 0.35 * np.abs((x / max(width, 1e-6)) - 0.5) * 2.0

    sun = max(0.0, math.sin(math.pi * (hour - 6.0) / 12.0)) if 6 <= hour <= 18 else 0.0
    sun *= (1.0 - cloud)

    noise = np.array([rng.gauss(0, 0.18) for _ in range(coords.shape[0])])
    return 24.0 + ambient + 9.0 * shade * edge * sun + noise


def _snapshots_simulated(coords: np.ndarray, width: float, length: float
               ) -> Tuple[np.ndarray, np.ndarray]:
    """(fit, test) snapshot matrices, each (n_snapshots, n_points).

    SPLIT, and the split is the point. Choosing sensors from the same snapshots
    the error is then measured on lets every method reconstruct conditions it
    was tuned against, which flatters all of them and flatters the most flexible
    one most. The fit half chooses the sensors; the held-out half is only ever
    used to score them.

    The split is by CONDITION, not by point - a placement is being asked to
    generalise to weather it has not seen, not to corners of the house it has
    not seen.
    """
    rng = random.Random(SEED)
    rows = []
    for _ in range(N_SNAPSHOTS):
        hour = rng.uniform(6.0, 18.0)
        cloud = rng.betavariate(2.0, 5.0)          # mostly clear, sometimes not
        ambient = rng.gauss(0.0, 1.4)              # day-to-day warmth
        rows.append(_field(coords, width, length, hour, cloud, ambient, rng))
    all_snap = np.vstack(rows)

    idx = list(range(N_SNAPSHOTS))
    rng.shuffle(idx)
    n_test = max(2, int(N_SNAPSHOTS * TEST_FRACTION))
    return all_snap[idx[n_test:]], all_snap[idx[:n_test]]


# ── Measured snapshots: the real calibration data ───────────────────────────
# How wide a slice of time counts as "the same moment" across sections. Nodes do
# not report in step - this one pushes every ~40 s, and they drift - so readings
# have to be grouped into buckets before they form a matrix. Ten minutes is
# comfortably longer than any report interval and far shorter than the time a
# shade house takes to change temperature.
BUCKET_MINUTES = 10

# A bucket is only usable if EVERY section contributed to it. A matrix with
# holes cannot be decomposed, and filling those holes by interpolation would
# mean choosing sensor positions from numbers kriging invented - the exact
# circularity this whole phase exists to avoid.
MIN_BUCKETS = 24


def _snapshots_measured(house_id: str, section_ids: List[str], field: str = "temperature"
                        ) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """(fit, test) matrices built from what the nodes actually recorded.

    Shape is (buckets, sections): each row is one moment across the house, each
    column one section. That is the orientation SSPOR wants - it selects
    COLUMNS, and a column here is a physical section, so the answer comes back
    as "these sections" rather than as an index into something abstract.

    Returns None when there is not enough overlapping data, and the caller says
    so rather than quietly falling back to generated numbers. Falling back
    silently would be the worst outcome available: the farmer would be shown a
    placement derived from assumptions, labelled as derived from their farm.

    THE SPLIT IS CHRONOLOGICAL, not random. Sensors are chosen on the earlier
    part of the window and scored on the later part, which is the question
    actually being asked - will this placement still describe the house
    tomorrow? A random split lets a method be scored on the hour either side of
    an hour it was fitted on, which is much easier and much less useful.
    """
    from app.api.routes.smart_care_v2 import _fb_get
    from app.services.readings import value as _measured_value

    bucket_ms = BUCKET_MINUTES * 60000.0
    per_section: dict = {}

    for sid in section_ids:
        hist = _fb_get(f"/farm/history/{house_id}/{sid}.json") or {}
        buckets: dict = {}
        for rec in hist.values():
            if not isinstance(rec, dict):
                continue
            ts = rec.get("timestamp")
            if not ts:
                continue
            # readings.value(), NOT _clean(). This comment used to say _clean()
            # excludes a failed sensor's -999; it does not - it substitutes 28 C,
            # so a DHT22 glitch entered the matrix as a real temperature at that
            # section and moment. value() returns None and the reading is skipped.
            v = _measured_value(rec, field)
            if v is None:
                continue
            b = int(float(ts) // bucket_ms)
            buckets.setdefault(b, []).append(float(v))
        if buckets:
            per_section[sid] = {b: sum(v) / len(v) for b, v in buckets.items()}

    if len(per_section) < len(section_ids):
        return None

    # Only the moments every section saw.
    common = set.intersection(*(set(d) for d in per_section.values()))
    if len(common) < MIN_BUCKETS:
        return None

    order = sorted(common)
    matrix = np.array([[per_section[sid][b] for sid in section_ids] for b in order],
                      dtype=float)

    n_test = max(2, int(len(order) * TEST_FRACTION))
    return matrix[:-n_test], matrix[-n_test:]


# ── Placement methods ───────────────────────────────────────────────────────
# Each returns INDICES into `coords`, so they are interchangeable and the
# evaluator does not care which produced them.

def _place_pysensors(fit: np.ndarray, n: int) -> Optional[List[int]]:
    """SSPOR with QR pivoting. None when the library is unavailable.

    Returning None rather than raising is deliberate: PySensors is documented
    for Linux and macOS only ("Windows testing not completed"), so a developer
    machine can legitimately be without it while the Ubuntu server has it. The
    endpoint degrades to the kriging-greedy placement and says so in the
    response, instead of failing a request the farmer cannot act on.
    """
    try:
        from pysensors.reconstruction import SSPOR
        from pysensors.basis import SVD
    except Exception:
        return None

    # Capped by BOTH dimensions of the matrix, and it has to be both.
    #
    # TruncatedSVD limits n_components by the number of FEATURES (columns), not
    # samples. This function now serves two very different shapes: the Phase 1
    # matrix is (snapshots x ~468 candidate points), where 20 modes is nothing,
    # and the Phase 2 matrix is (buckets x 9 instrumented sections), where 20 is
    # more than exist. Capping on rows alone was fine until the second caller
    # arrived and it raised
    #     ValueError: n_components(20) must be <= n_features(9)
    modes = int(min(20, max(2, fit.shape[0] - 1), max(2, fit.shape[1] - 1)))
    # A pointless ask: selecting every column needs no basis at all.
    if n >= fit.shape[1]:
        return list(range(fit.shape[1]))
    model = SSPOR(n_sensors=int(n), basis=SVD(n_basis_modes=modes))
    model.fit(fit)
    return [int(i) for i in np.asarray(model.selected_sensors).ravel()[:n]]


def _place_grid(coords: np.ndarray, n: int, width: float, length: float) -> List[int]:
    """A regular grid, snapped to the nearest candidate point.

    The baseline a grower would reach for unaided, and the one worth beating -
    "spread them out evenly" is the intuitive answer to this problem.
    """
    cols = max(1, int(round(math.sqrt(n * width / max(length, 1e-6)))))
    rows = int(math.ceil(n / cols))
    want = []
    for r in range(rows):
        for c in range(cols):
            if len(want) >= n:
                break
            want.append(((c + 0.5) * width / cols, (r + 0.5) * length / rows))
    out = []
    for wx, wy in want:
        d = (coords[:, 0] - wx) ** 2 + (coords[:, 1] - wy) ** 2
        for cand in np.argsort(d):
            if int(cand) not in out:
                out.append(int(cand))
                break
    return out


def _place_random(coords: np.ndarray, n: int, seed: int) -> List[int]:
    """Uniformly random candidates. The floor any method must clear."""
    rng = random.Random(seed)
    return rng.sample(range(coords.shape[0]), min(n, coords.shape[0]))


def _place_kriging_greedy(coords: np.ndarray, n: int) -> List[int]:
    """Greedily add the point where kriging is currently least certain.

    Worth having as more than a baseline. Kriging VARIANCE depends only on the
    variogram and on where the points are - not on any measured value - so this
    method needs no field at all, generated or real. It is the one placement in
    this module that does not inherit the physics prior's assumptions, which
    makes it the honest fallback when PySensors is unavailable and a useful
    check on whether the prior is doing any work.

    Starts from the point nearest the centroid, which is where a single sensor
    minimises worst-case distance.
    """
    n = min(n, coords.shape[0])
    centre = coords.mean(axis=0)
    first = int(np.argmin(((coords - centre) ** 2).sum(axis=1)))
    chosen = [first]

    while len(chosen) < n:
        placed = coords[chosen]
        # A dummy field of zeros: only the VARIANCE is read, and it does not
        # depend on the values. Kriging refuses fewer than a handful of points,
        # so below that fall back to max-min distance, which is what the
        # variance criterion reduces to when there is no variogram to fit.
        if len(chosen) >= 4:
            got = _krige_field(placed[:, 0], placed[:, 1], np.zeros(len(chosen)),
                               coords[:, 0], coords[:, 1])
            if got is not None:
                _, var, _ = got
                var = np.asarray(var, dtype=float)
                var[chosen] = -np.inf          # never pick an occupied point
                chosen.append(int(np.argmax(var)))
                continue
        d = np.full(coords.shape[0], np.inf)
        for c in chosen:
            d = np.minimum(d, ((coords - coords[c]) ** 2).sum(axis=1))
        d[chosen] = -np.inf
        chosen.append(int(np.argmax(d)))
    return chosen


def _has_xy(section: dict) -> bool:
    meta = (section or {}).get("meta") or {}
    try:
        float(meta["x"]), float(meta["y"])
        return True
    except (KeyError, TypeError, ValueError):
        return False


def _round(v):
    return None if v is None else round(v, 3)


def _place_grid_idx(coords: np.ndarray, n: int) -> List[int]:
    """Grid baseline over an arbitrary set of points.

    _place_grid() snaps to a dense candidate lattice, which does not exist here:
    the only positions available are the sections that were instrumented. This
    picks n of them spread as evenly as possible, by farthest-point sampling
    from the centroid - the same intent, over the points that actually exist.
    """
    n = min(n, coords.shape[0])
    centre = coords.mean(axis=0)
    chosen = [int(np.argmin(((coords - centre) ** 2).sum(axis=1)))]
    while len(chosen) < n:
        d = np.full(coords.shape[0], np.inf)
        for c in chosen:
            d = np.minimum(d, ((coords - coords[c]) ** 2).sum(axis=1))
        d[chosen] = -np.inf
        chosen.append(int(np.argmax(d)))
    return chosen


def _elbow(table: List[dict]) -> int:
    """The knee of the error curve: most accuracy bought, before it flattens.

    Maximum perpendicular distance from the straight line joining the first and
    last points. Deterministic, standard, and defensible in the report - unlike
    a "within 5% of the best" rule, which needs a threshold nobody can justify
    and which broke on a curve that was not monotonic.
    """
    pts = [(r["sensors"], r["error"]) for r in table if r["error"] is not None]
    if len(pts) < 3:
        return pts[0][0] if pts else MIN_SENSORS

    # MONOTONISE FIRST. The knee construction assumes a curve that falls, and
    # this one does not always: measured data gave 0.375 at three sensors and
    # 0.464 at four. Left alone, the maximum-distance rule picks the point
    # furthest from the chord - and a point that is WORSE than the chord is
    # furthest of all, so it recommended four sensors for more money and more
    # error than three.
    #
    # The running minimum is not a smoothing trick, it is the quantity actually
    # being asked for: "the best I can do with at most n sensors". Adding a
    # sensor can never genuinely make an estimate worse - you could ignore it -
    # so a rise is noise in the estimate, not a property of the farm.
    best = float("inf")
    mono = []
    for x, y in pts:
        best = min(best, y)
        mono.append((x, best))
    pts = mono
    (x1, y1), (x2, y2) = pts[0], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    norm = math.hypot(dx, dy) or 1.0
    best, best_d = pts[0][0], -1.0
    for x, y in pts:
        d = abs(dy * x - dx * y + x2 * y1 - y2 * x1) / norm
        if d > best_d:
            best, best_d = x, d
    return best


# ── Scoring ─────────────────────────────────────────────────────────────────

def _score(coords: np.ndarray, sensors: List[int], test: np.ndarray) -> Optional[float]:
    """Mean absolute reconstruction error over the held-out snapshots, in °C.

    For each snapshot: take the values the chosen sensors would have read, krige
    them onto every candidate point, and compare against what the field actually
    was there. This is exactly the runtime path - measured sections in, estimates
    for unmonitored ones out - with the answer known.
    """
    if len(sensors) < 2:
        return None
    sx, sy = coords[sensors, 0], coords[sensors, 1]
    errs = []
    for snap in test:
        got = _krige_field(sx, sy, snap[sensors], coords[:, 0], coords[:, 1])
        if got is None:
            continue
        pred, _, _ = got
        errs.append(float(np.mean(np.abs(np.asarray(pred) - snap))))
    return float(np.mean(errs)) if errs else None


def _methods_for(coords, fit, test, n, width, length) -> Dict[str, dict]:
    """Every method at one sensor count, scored the same way."""
    out: Dict[str, dict] = {}

    ps = _place_pysensors(fit, n)
    if ps is not None:
        out["pysensors"] = {"label": "PySensors (QR-pivot)", "sensors": ps}
    out["kriging_greedy"] = {"label": "Kriging-variance greedy",
                             "sensors": _place_kriging_greedy(coords, n)}
    out["grid"] = {"label": "Regular grid",
                   "sensors": _place_grid(coords, n, width, length)}
    # Averaged over several draws. A single random layout is luck, and reporting
    # one lucky draw as "random" would understate how much the other methods win.
    rnd_errs, rnd_last = [], None
    for k in range(5):
        pick = _place_random(coords, n, SEED + 100 * k)
        e = _score(coords, pick, test)
        if e is not None:
            rnd_errs.append(e)
            rnd_last = pick
    out["random"] = {"label": "Random", "sensors": rnd_last or [],
                     "_preset_error": (float(np.mean(rnd_errs)) if rnd_errs else None)}

    for key, m in out.items():
        m["error"] = m.pop("_preset_error", None) if "_preset_error" in m \
            else _score(coords, m["sensors"], test)
    return out


# ── API ─────────────────────────────────────────────────────────────────────

# ── Calibration: co-location, the analysis, and the placement decision ───────
# After co-location ends the nodes are carried to their positions, and readings
# taken while a node is in someone's hand describe neither place. They are
# skipped for this long before the spread-out period counts.
SETTLE_MINUTES = 15
# 40 minutes gives the analysis at least three WHOLE ten-minute buckets with
# every node side by side, which is what colocation_offsets() needs.
MIN_COLOCATION_MINUTES = 40


class ColocationIn(BaseModel):
    """'start' when every node sits together, 'end' when they are spread out,
    'clear' to forget a co-location that went wrong."""
    action: str


@router.post("/{house_id}/colocation")
async def colocation(house_id: str, body: ColocationIn,
                     ctx: AuthContext = Depends(require_role(ROLE_ADMIN))) -> dict:
    """Mark the period when every node read the same air.

    Two sensors of the same model disagree by a few tenths of a degree out of the
    box. Spread across a house, that disagreement looks exactly like a warm
    corner. Running them side by side first measures it, and the analysis then
    removes it - so a difference between two sections is the house, not the
    sensors. Times are the SERVER's clock, never the phone's.
    """
    from app.api.routes.smart_care_v2 import _fb_get, _fb_put, _server_now_ms

    meta = _fb_get(f"/farm/houses/{house_id}/meta.json")
    if not meta:
        raise HTTPException(404, "House not found")
    cal = meta.get("calibration") or {}
    co = dict(cal.get("colocation") or {})
    now = float(_server_now_ms())
    action = (body.action or "").strip().lower()

    if action == "start":
        co = {"startMs": now}
    elif action == "end":
        if not co.get("startMs"):
            raise HTTPException(400, "Co-location was never started.")
        minutes = (now - float(co["startMs"])) / 60000.0
        if minutes < MIN_COLOCATION_MINUTES:
            raise HTTPException(
                400, f"The nodes have been together {minutes:.0f} minutes; leave them at least "
                     f"{MIN_COLOCATION_MINUTES} so every sensor's offset can be measured.")
        co["endMs"] = now
    elif action == "clear":
        co = {}
    else:
        raise HTTPException(400, "action must be start, end or clear")

    cal["colocation"] = co or None
    meta["calibration"] = cal
    _fb_put(f"/farm/houses/{house_id}/meta.json", meta)
    return {"status": "success", "houseId": house_id, "colocation": co or None,
            "serverNowMs": now}


def _load_for_analysis(house_id: str):
    """Everything the analysis reads, fetched in the request (tenant) context."""
    from app.api.routes.smart_care_v2 import _fb_get, _natural_key

    meta = _fb_get(f"/farm/houses/{house_id}/meta.json")
    if not meta:
        raise HTTPException(404, "House not found")
    sections = _fb_get(f"/farm/houses/{house_id}/sections.json") or {}
    placed = {sid: sec for sid, sec in sections.items() if isinstance(sec, dict) and _has_xy(sec)}
    ids = sorted(placed, key=_natural_key)
    coords = {sid: (float(placed[sid]["meta"]["x"]), float(placed[sid]["meta"]["y"])) for sid in ids}

    cal = meta.get("calibration") or {}
    since = float(cal.get("startedAt") or 0)
    histories = {}
    for sid in ids:
        hist = _fb_get(f"/farm/history/{house_id}/{sid}.json") or {}
        # Only what was recorded during THIS calibration. A board used in another
        # house before would otherwise bring that house's readings with it.
        histories[sid] = {k: r for k, r in hist.items()
                          if isinstance(r, dict) and float(r.get("timestamp") or 0) >= since}
    co = cal.get("colocation") or None
    return meta, ids, coords, histories, co


def _run_analysis(histories, coords, co):
    """Pure CPU work - no Firebase - so it can run off the event loop."""
    from app.services import placement_analysis as pa
    colocation = None
    if co and co.get("startMs") and co.get("endMs"):
        colocation = {"startMs": float(co["startMs"]), "endMs": float(co["endMs"]),
                      "spreadFromMs": float(co["endMs"]) + SETTLE_MINUTES * 60000.0}
    return pa.analyse(histories, coords, colocation=colocation)


@router.post("/{house_id}/placement-analysis")
async def run_placement_analysis(house_id: str,
                                 ctx: AuthContext = Depends(require_role(ROLE_ADMIN))) -> dict:
    """Run the full analysis on this house's calibration readings and keep it.

    Kept in /farm/placementAnalysis/{h} so the app can show it again
    without recomputing - a run takes ten to twenty seconds of kriging.
    """
    import asyncio
    from app.api.routes.smart_care_v2 import _fb_put, _server_now_ms

    meta, ids, coords, histories, co = _load_for_analysis(house_id)
    if co and co.get("startMs") and not co.get("endMs"):
        # Run now, the side-by-side readings would be scored as if each node
        # were already at its own position.
        raise HTTPException(409, "Co-location is still running. Press Done once the "
                                 "nodes have been together 40 minutes, then spread "
                                 "them out before analysing.")
    if len(ids) < 3:
        raise HTTPException(400, f"{len(ids)} sections have a position; at least 3 are needed.")
    try:
        out = await asyncio.to_thread(_run_analysis, histories, coords, co)
    except ValueError as e:
        raise HTTPException(409, str(e))
    out["computedAtMs"] = _server_now_ms()
    out["houseId"] = house_id
    out["colocation"] = co
    out["nodeCostLkr"] = NODE_COST_LKR
    # NOT under /farm/houses/{h}: the engine downloads that whole document every
    # 60 s, and a 20-35 KB analysis sitting in it cost 30-50 MB of Firebase
    # egress a day for nothing - the same mistake history and events were
    # moved out of.
    _fb_put(f"/farm/placementAnalysis/{house_id}.json", out)
    return {"status": "success", **out}


@router.get("/{house_id}/placement-analysis")
async def get_placement_analysis(house_id: str,
                                 ctx: AuthContext = Depends(require_auth)) -> dict:
    """The last analysis run for this house, or 404 if there has been none."""
    from app.api.routes.smart_care_v2 import _fb_get
    out = _fb_get(f"/farm/placementAnalysis/{house_id}.json")
    if not out:
        raise HTTPException(404, "No placement analysis has been run for this house yet.")
    return {"status": "success", **out}


# ── Shade-house check: is the house what the model was trained on? ──────────
# The watering model's labels came from real ERA5 weather moved INDOORS by three
# constants nobody had measured. This puts what the sensors recorded beside the
# real outdoor weather for the same hours. The reasoning, and every rule about
# what counts as a reading, lives in app/services/shadehouse_check.py.

@router.get("/{house_id}/shadehouse-check")
async def shadehouse_check(house_id: str, section: Optional[str] = None,
                           sinceMs: Optional[float] = None,
                           ctx: AuthContext = Depends(require_auth)) -> dict:
    """Measured indoor conditions against the assumed indoor conversion.

    `section` restricts the check to one section; by default every section of
    the house with history is pooled and each is also reported on its own.
    `sinceMs` drops readings before that moment - a node that sat on a bench
    before it went into the house recorded a ROOM, and a room compared with the
    outdoor weather says nothing about shade cloth.

    409, in words, when there is not enough to judge. Never a number computed
    from nothing, and never a substitute: there is no fallback to generated
    readings or to a default outdoor table.
    """
    import asyncio
    from app.api.routes.forecast import DEFAULT_LAT, DEFAULT_LON
    from app.api.routes.smart_care_v2 import (
        _fb_get, _natural_key, _server_now_ms, farm_tz,
    )
    from app.services import shadehouse_check as shc

    meta = _fb_get(f"/farm/houses/{house_id}/meta.json")
    if not meta:
        raise HTTPException(404, "House not found")
    # The node bench writes INVENTED weather into a house marked simulated.
    # Compared with the real outdoor weather it would yield a confident, entirely
    # fabricated "measurement" of the shade cloth - so it is refused, not run.
    if meta.get("simulated") is True:
        raise HTTPException(
            409, "This house is marked simulated: its readings come from the node "
                 "bench, not from sensors in a shade house, so they cannot check "
                 "the indoor conversion.")

    sections = _fb_get(f"/farm/houses/{house_id}/sections.json") or {}
    ids = sorted((sid for sid, s in sections.items() if isinstance(s, dict)), key=_natural_key)
    if section is not None:
        if section not in ids:
            raise HTTPException(404, f"Section {section} not found in this house")
        ids = [section]

    histories = {}
    for sid in ids:
        hist = _fb_get(f"/farm/history/{house_id}/{sid}.json") or {}
        if hist:
            histories[sid] = hist
    if not histories:
        raise HTTPException(
            409, "Not enough data: no section of this house has recorded any readings yet."
            if section is None else
            f"Not enough data: section {section} has not recorded any readings yet.")

    # The days the outdoor weather is needed for, from the readings that will
    # actually be compared. A walk over every record, so off the event loop.
    now_ms = float(_server_now_ms())
    window = await asyncio.to_thread(shc.reading_window, histories, sinceMs, now_ms)
    if window is None:
        raise HTTPException(
            409, "Not enough data: every stored reading was seeded, unsynced, or "
                 "before the requested start, so nothing measured is left to compare.")
    start, end = window

    farm = _fb_get("/farm/meta.json") or {}
    try:
        lat, lon = float(farm["latitude"]), float(farm["longitude"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError
        located = "farm settings"
    except (KeyError, TypeError, ValueError):
        # Same default as forecast.farm_location(), but SAID: the weather for
        # Peradeniya compared with a house somewhere else would look like a
        # wrong constant when it is a wrong place.
        lat, lon = DEFAULT_LAT, DEFAULT_LON
        located = "default (Peradeniya) - the farm location has not been set"

    try:
        outdoor = await asyncio.to_thread(shc.fetch_outdoor, lat, lon, start, end)
    except Exception as e:
        raise HTTPException(
            503, f"Could not fetch the outdoor weather to compare against "
                 f"({type(e).__name__}). Nothing was computed; try again later.")

    try:
        offset = int(farm_tz().utcoffset(datetime.now(timezone.utc)).total_seconds() // 60)
    except Exception:
        offset = 330          # Sri Lanka, no DST - farm_tz's own default

    out = await asyncio.to_thread(shc.compare, histories, outdoor,
                                  since_ms=sinceMs, now_ms=now_ms, local_offset_min=offset)
    if not out.get("enough"):
        raise HTTPException(409, out.get("reason") or "Not enough data.")
    return {"status": "success", "houseId": house_id,
            "location": {"latitude": lat, "longitude": lon, "source": located},
            "sinceMs": sinceMs, **out}


@router.get("/{house_id}/health")
async def house_health(house_id: str, ctx: AuthContext = Depends(require_auth)) -> dict:
    """What is wrong with this house's hardware right now, per section.

    From the engine's in-memory checks (app/services/device_health.py), so it
    costs nothing to ask. `checkedAtMs` is null until the engine has run once
    since the server started; the slow checks (frozen, silent) need their whole
    window again after a restart, which the app says rather than showing an
    all-clear it has not earned.
    """
    from app.services import device_health as dh
    from app.services.tenant_context import current_tenant
    snap = dh.snapshot(current_tenant(), house_id)
    return {"status": "success", "houseId": house_id, **snap}


class AnalyseIn(BaseModel):
    """Kept for the app's existing call. maxSensors no longer limits anything:
    the analysis covers every count the house allows."""
    maxSensors: int = Field(MAX_SENSORS_CAP, ge=2, le=MAX_SENSORS_CAP)


@router.post("/{house_id}/analyze-placement")
async def analyze_placement(house_id: str, body: AnalyseIn,
                            ctx: AuthContext = Depends(require_role(ROLE_ADMIN))) -> dict:
    """Which sections should keep a sensor, decided from the calibration data.

    Now a view onto the full analysis (placement_analysis.py): temperature,
    humidity and VPD instead of temperature alone, sensor bias removed when the
    nodes were co-located, three placement methods compared on a validation
    period and the winner scored on later readings nobody fitted on.

    The response keeps the shape PlacementResultScreen reads - table, positions
    keyed by sensor count, recommendedSensors - with `analysis` carrying every
    step for the screen that explains the flow.
    """
    res = await run_placement_analysis(house_id, ctx)
    p = res["placement"]
    table, positions, baselines = [], {}, {}
    for row in p["rows"]:
        if not row["runtimeUsable"] or not row.get("selected"):
            continue                     # a layout production cannot run is not offered
        sel = row["methods"][row["selected"]]
        k = row["sensors"]
        table.append({
            "sensors": k,
            "error": sel["temperature"]["mae"],
            "errors": {f: sel[f]["mae"] for f in ("temperature", "humidity", "vpd")},
            "costLkr": k * NODE_COST_LKR,
            "method": row["selected"],
            "recommended": k == p.get("recommended"),
        })
        positions[str(k)] = [{"sectionId": sid, "x": res["positions"][sid]["x"],
                              "y": res["positions"][sid]["y"]} for sid in sel["sections"]]
        baselines[str(k)] = {name: (m.get("temperature") or {}).get("mae")
                             for name, m in row["methods"].items() if "temperature" in m}
    return {
        "status": "success",
        "houseId": house_id,
        "source": "measured",
        "sectionsInstrumented": len(res["sections"]),
        "buckets": {"fit": res["buckets"]["fit"], "test": res["buckets"]["test"],
                    "minutes": res["buckets"]["minutes"]},
        "recommendedSensors": p.get("recommended"),
        "table": table,
        "positions": positions,
        "baselines": baselines,
        "note": p.get("note") or (
            "Chosen from temperature, humidity and VPD recorded during calibration. "
            "Three placement methods were compared on a validation period; the "
            "error shown is on later readings none of them was fitted on."),
        "analysis": res,
    }


class PlanIn(BaseModel):
    width: float = Field(..., gt=1.0, le=200.0, description="House width, metres")
    length: float = Field(..., gt=1.0, le=200.0, description="House length, metres")
    maxSensors: int = Field(8, ge=MIN_SENSORS, le=MAX_SENSORS_CAP)


# NOT PART OF THE APP FLOW ANY MORE.
#
# This placed sensors from a field GENERATED out of house geometry, and the app
# called it the moment a farmer typed in the dimensions - producing a confident
# table and an "optimal placement" before a single sensor existed. That number
# was an assumption about where the sun falls, dressed as a result, and a farmer
# could install to it and never learn it was a guess. Phase 1 now lays sections
# on an even grid and says so, and the placement worth acting on comes from
# analyze-placement once real readings exist.
#
# It is kept because it is the VALIDATION the report rests on: a field whose
# ground truth is known is the only place PySensors can be measured against a
# regular grid and against random placement, and that comparison is what makes
# the accuracy figure defensible. Called by the thesis, not by the app.
@router.post("/plan")
async def plan_house(body: PlanIn, ctx: AuthContext = Depends(require_role(ROLE_ADMIN))) -> dict:
    """Best sensor positions for a house, with the evidence for the choice.

    Returns a curve rather than a single number because the farmer is the one
    spending the money. Every extra node costs LKR 2,350 and buys less accuracy
    than the one before it; where that stops being worth it is their call, and
    they can only make it if they can see it.
    """
    width, length = float(body.width), float(body.length)
    coords = _candidate_grid(width, length)
    if coords.shape[0] < MIN_SENSORS:
        raise HTTPException(400, "House is too small to place sensors in.")

    fit, test = _snapshots_simulated(coords, width, length)

    top = int(min(body.maxSensors, MAX_SENSORS_CAP, coords.shape[0]))
    curve, used_fallback = [], False

    for n in range(MIN_SENSORS, top + 1):
        methods = _methods_for(coords, fit, test, n, width, length)
        if "pysensors" not in methods:
            used_fallback = True

        row = {"sensors": n, "costLkr": n * NODE_COST_LKR}
        for key, m in methods.items():
            row[key] = None if m["error"] is None else round(m["error"], 3)

        # PYSENSORS PLACES. The baselines validate, they do not compete for the
        # job - one method is one thing to explain and to defend, and SSPOR is
        # the published, peer-reviewed one.
        #
        # This is deliberate even though PySensors does not always score best
        # here, and the reason it does not is worth stating rather than hiding.
        # The generated field is essentially RANK 2 - its first two singular
        # values hold 98.8% of the energy, and the first alone holds 93% - so it
        # is one strong gradient. SSPOR optimises POD reconstruction and pivots
        # to extremal points of the modes, which on a smooth monotone gradient
        # means the hot edge. This module scores by KRIGING reconstruction,
        # because kriging is what production runs. Those are different
        # objectives, and at three to five sensors evenly spreading along the
        # gradient - what a grid does - happens to serve the kriging objective
        # better.
        #
        # Not a defect in SSPOR and not a misuse of it: it is being marked on a
        # task it was not optimising for. Checked before accepting it - varying
        # n_basis_modes across 3, n, n+2 and 20 moves the numbers around and
        # never removes the low-count gap, so it is structural, not a tuning
        # mistake.
        #
        # `bestScoring` records which method actually scored lowest so the app
        # can say so. The table has to stay honest even when it disagrees with
        # the placement.
        scored = [(k, m) for k, m in methods.items() if m["error"] is not None]
        best_key = min(scored, key=lambda kv: kv[1]["error"])[0] if scored else None
        row["bestScoring"] = best_key

        win = methods.get("pysensors") or methods["kriging_greedy"]
        row["placedBy"] = "pysensors" if "pysensors" in methods else "kriging_greedy"
        # Positions PER ROW, not sliced from the largest layout. Greedy and
        # pivoted methods do have that prefix property, but a regular grid does
        # not: the 5-point grid is a different arrangement from the first five
        # points of the 8-point grid, so slicing produced a layout no method
        # ever chose or scored.
        row["positions"] = [
            {"x": round(float(coords[i, 0]), 2), "y": round(float(coords[i, 1]), 2)}
            for i in win["sensors"]
        ]
        curve.append(row)

    # The cheapest count that gets within 5% of the BEST error the curve reaches.
    #
    # Not "the first count the next one fails to improve on", which is what this
    # was and which assumed the curve falls monotonically. SSPOR's does not: on a
    # live run it went 0.356 at three sensors, 0.433 at four, then back down. The
    # old rule saw the rise at four, concluded three was a plateau, and told the
    # farmer three sensors was enough BECAUSE the estimate got worse - exactly
    # backwards, and it would have sold them the weakest layout on the table.
    #
    # Comparing against the best achieved is immune to that. A bounce cannot end
    # the search early, and the answer is still the cheapest count that buys
    # essentially all the accuracy available.
    errs = [(r["sensors"], r.get(r["placedBy"])) for r in curve]
    errs = [(n, e) for n, e in errs if e is not None]
    rec = top
    if errs:
        floor = min(e for _, e in errs)
        for n, e in errs:                      # ascending sensor count
            if e <= floor * 1.05:
                rec = n
                break

    rec_row = next(r for r in curve if r["sensors"] == rec)
    best_positions = rec_row["positions"]
    key = rec_row["placedBy"]

    return {
        "status": "success",
        "house": {"width": width, "length": length,
                  "candidatePoints": int(coords.shape[0]),
                  "gridSpacingM": GRID_SPACING_M},
        "method": key,
        "pysensorsAvailable": not used_fallback,
        "message": (
            "PySensors is not installed on this server, so placement used the "
            "kriging-variance method instead and the table has no PySensors row."
            if used_fallback else
            "Placed by PySensors (SSPOR, QR-pivot). The other rows are baselines "
            "it is measured against, not alternatives it was chosen over."),
        "recommendedSensors": rec,
        "positions": best_positions,
        "curve": curve,
        "costPerNodeLkr": NODE_COST_LKR,
        "validation": {
            "fitSnapshots": int(fit.shape[0]),
            "testSnapshots": int(test.shape[0]),
            "scorer": "ordinary-kriging",
            "metric": "mean absolute reconstruction error, deg C, held-out snapshots",
            "note": ("Sensors are chosen on the fit snapshots and scored on held-out "
                     "ones, so no method is measured on conditions it was tuned "
                     "against. The field is generated from house geometry, not "
                     "measured: this compares METHODS, and does not claim the "
                     "field matches this house."),
        },
    }
