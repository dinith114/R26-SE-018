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
from typing import Dict, List, Optional, Tuple

import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.routes.spatial_service import _krige_field

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

# Sensor counts the curve is computed over. Below 3 kriging has nothing to work
# with; above 10 a house this size is saturated and the farmer is buying
# hardware that changes nothing.
MIN_SENSORS = 3
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
    from app.api.routes.smart_care_v2 import _fb_get, _clean

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
            # _clean() rather than the raw record, so a failed sensor's -999 is
            # excluded instead of being decomposed as if it were a temperature.
            v = _clean(rec).get(field)
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

class AnalyseIn(BaseModel):
    """Nothing to configure: the data decides. maxSensors caps the table only."""
    maxSensors: int = Field(MAX_SENSORS_CAP, ge=MIN_SENSORS, le=MAX_SENSORS_CAP)


@router.post("/{house_id}/analyze-placement")
async def analyze_placement(house_id: str, body: AnalyseIn) -> dict:
    """Which sections should keep a sensor, decided from the calibration data.

    This is the phase the whole design exists for. Phase 1 places sensors from a
    field GENERATED out of house geometry, because a house with no hardware has
    nothing else to go on. This runs once those sensors have been in the ground
    for the calibration window, and it uses what they actually recorded.

    What it can and cannot answer, stated plainly:

      * It CAN say which k of the instrumented sections carry the information -
        the classic over-instrument-then-prune workflow, and what the flow asks
        for.
      * It CANNOT propose a position with no sensor in it. There is no data
        there. Kriging could invent some, but then SSPOR would be selecting
        sensors to reconstruct kriging's own guess, which is circular.

    Scored by ordinary kriging on held-out LATER buckets, so a placement is
    asked to describe the house tomorrow rather than to re-describe the hours it
    was fitted on.
    """
    from app.api.routes.smart_care_v2 import _fb_get, _natural_key, _ml_per_sec

    meta = _fb_get(f"/farm/houses/{house_id}/meta.json")
    if not meta:
        raise HTTPException(404, "House not found")

    sections = _fb_get(f"/farm/houses/{house_id}/sections.json") or {}
    placed = {sid: sec for sid, sec in sections.items()
              if isinstance(sec, dict) and _has_xy(sec)}
    if len(placed) < MIN_SENSORS:
        raise HTTPException(
            400, f"{len(placed)} sections have a position. At least {MIN_SENSORS} "
                 f"are needed - set them in each section's Setup tab.")

    ids = sorted(placed, key=_natural_key)
    coords = np.array([[float(placed[s]["meta"]["x"]), float(placed[s]["meta"]["y"])]
                       for s in ids], dtype=float)

    got = _snapshots_measured(house_id, ids)
    if got is None:
        raise HTTPException(
            409, "Not enough overlapping readings yet. Every section needs data "
                 f"covering at least {MIN_BUCKETS} common {BUCKET_MINUTES}-minute "
                 "periods. Check the calibration screen for which section is behind.")
    fit, test = got

    top = int(min(body.maxSensors, len(ids) - 1))
    if top < MIN_SENSORS:
        raise HTTPException(
            400, f"With {len(ids)} sections there is nothing to choose - "
                 f"pruning needs more sections than sensors.")

    table, positions, baselines = [], {}, {}
    for n in range(MIN_SENSORS, top + 1):
        chosen = _place_pysensors(fit, n)
        used = "pysensors"
        if chosen is None:
            chosen = _place_kriging_greedy(coords, n)
            used = "kriging_greedy"

        err = _score(coords, chosen, test)
        table.append({
            "sensors": n,
            "error": None if err is None else round(err, 3),
            "costLkr": n * NODE_COST_LKR,
            "method": used,
        })
        positions[str(n)] = [
            {"sectionId": ids[i],
             "x": round(float(coords[i, 0]), 2),
             "y": round(float(coords[i, 1]), 2)}
            for i in chosen
        ]
        # Kept for the report, not for the screen. The flow asks for a simple
        # table; these are what make the simple number defensible.
        baselines[str(n)] = {
            "grid": _round(_score(coords, _place_grid_idx(coords, n), test)),
            "random": _round(_score(coords, _place_random(coords, n, SEED + n), test)),
            "krigingGreedy": _round(_score(coords, _place_kriging_greedy(coords, n), test)),
        }

    rec = _elbow(table)
    for row in table:
        row["recommended"] = (row["sensors"] == rec)

    return {
        "status": "success",
        "houseId": house_id,
        "source": "measured",
        "sectionsInstrumented": len(ids),
        "buckets": {"fit": int(fit.shape[0]), "test": int(test.shape[0]),
                    "minutes": BUCKET_MINUTES},
        "recommendedSensors": rec,
        "table": table,
        "positions": positions,
        "baselines": baselines,
        "note": ("Chosen from the readings these sections recorded during "
                 "calibration, and scored on later readings none of them was "
                 "fitted on. Only sections that already hold a sensor can be "
                 "chosen - there is no data anywhere else."),
    }


class PlanIn(BaseModel):
    width: float = Field(..., gt=1.0, le=200.0, description="House width, metres")
    length: float = Field(..., gt=1.0, le=200.0, description="House length, metres")
    maxSensors: int = Field(8, ge=MIN_SENSORS, le=MAX_SENSORS_CAP)


@router.post("/plan")
async def plan_house(body: PlanIn) -> dict:
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
