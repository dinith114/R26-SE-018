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
# held-out halves; see _snapshots().
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


def _snapshots(coords: np.ndarray, width: float, length: float
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

    # n_basis_modes caps at the number of snapshots available; asking for more
    # modes than samples is what raises inside the SVD rather than here.
    modes = int(min(20, max(2, fit.shape[0] - 1)))
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

    fit, test = _snapshots(coords, width, length)

    top = int(min(body.maxSensors, MAX_SENSORS_CAP, coords.shape[0]))
    curve, used_fallback = [], False

    for n in range(MIN_SENSORS, top + 1):
        methods = _methods_for(coords, fit, test, n, width, length)
        if "pysensors" not in methods:
            used_fallback = True

        row = {"sensors": n, "costLkr": n * NODE_COST_LKR}
        for key, m in methods.items():
            row[key] = None if m["error"] is None else round(m["error"], 3)

        # THE BEST METHOD AT THIS COUNT WINS, and it is not always the same one.
        # Measured on this field, PySensors is beaten by a plain grid from three
        # to seven sensors and only pulls ahead at eight. Running the comparison
        # and then using PySensors regardless would make the table decorative -
        # it would show the farmer that a grid was better and then place their
        # sensors the worse way.
        scored = [(k, m) for k, m in methods.items() if m["error"] is not None]
        win_key, win = min(scored, key=lambda kv: kv[1]["error"]) if scored             else ("kriging_greedy", methods["kriging_greedy"])
        row["best"] = win_key
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

    # Where the curve flattens: the first count after which one more node buys
    # less than 5% of the error still remaining. This is a recommendation, not a
    # limit - the farmer picks from the table.
    rec = top
    for a, b in zip(curve, curve[1:]):
        ea, eb = a.get(a["best"]), b.get(b["best"])
        if ea and eb and (ea - eb) / ea < 0.05:
            rec = a["sensors"]
            break

    rec_row = next(r for r in curve if r["sensors"] == rec)
    best_positions = rec_row["positions"]
    key = rec_row["best"]

    return {
        "status": "success",
        "house": {"width": width, "length": length,
                  "candidatePoints": int(coords.shape[0]),
                  "gridSpacingM": GRID_SPACING_M},
        "method": key,
        "pysensorsAvailable": not used_fallback,
        "message": (
            "PySensors is not installed on this server, so it has no row in the "
            "table. Placement used the best of the remaining methods."
            if used_fallback else
            f"Best method at {rec} sensors on this house: {key}."),
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
