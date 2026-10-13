"""Validate the kriging service against a microclimate whose truth we know.

The live farm cannot answer "how accurate is this?", because the only zones
worth estimating are the ones with no sensor - so there is nothing to compare
against. A simulated house can: generate a field, hide some sections, estimate
them from the rest, and measure the error against the value that was withheld.

The field is not random. It is built from the two gradients a shade house
actually has:

  * distance from the open sunny edge, which drives light and temperature
  * the coupling between temperature and humidity, so the pair stays physical

plus a little noise, because a perfectly smooth field would flatter any
interpolator.

Run:  python backend/scripts/simulate_spatial.py
"""
from __future__ import annotations

import math
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.routes import spatial_service as sp   # noqa: E402
from app.api.routes.smart_care_v2 import _server_now_ms  # noqa: E402

HOUSE_W, HOUSE_L = 10.0, 14.0        # metres, a plausible shade house
RNG = random.Random(42)   # reseeded per repeat in main()


def true_field(x: float, y: float) -> dict:
    """The microclimate at a point, as physics would roughly have it.

    y = 0 is the open, sun-facing edge. Light falls off with depth into the
    house; temperature follows it; humidity moves the other way because warmer
    air of the same water content is further from saturation.
    """
    depth = y / HOUSE_L                                   # 0 at the edge, 1 at the back
    shade = math.exp(-2.2 * depth)                        # light decays into the house
    edge = 1.0 - 0.35 * abs((x / HOUSE_W) - 0.5) * 2.0    # walls are cooler than the middle

    light = 32000.0 * shade * edge + RNG.gauss(0, 400)
    temp = 27.5 + 6.0 * shade * edge + RNG.gauss(0, 0.25)
    humid = 82.0 - 26.0 * shade * edge + RNG.gauss(0, 1.2)
    return {"temperature": round(temp, 2),
            "humidity": round(max(0.0, min(100.0, humid)), 2),
            "light": round(max(0.0, light), 1)}


def build_house(n: int) -> dict:
    """A house with n placed, reporting sections on a jittered grid."""
    cols = max(1, round(math.sqrt(n * HOUSE_W / HOUSE_L)))
    rows = math.ceil(n / cols)
    now = _server_now_ms()
    sections, k = {}, 0
    for r in range(rows):
        for c in range(cols):
            if k >= n:
                break
            # Jittered so the anchors are never perfectly collinear, which is
            # both more realistic and the case kriging actually handles.
            x = (c + 0.5) * HOUSE_W / cols + RNG.uniform(-0.4, 0.4)
            y = (r + 0.5) * HOUSE_L / rows + RNG.uniform(-0.4, 0.4)
            x, y = round(min(max(x, 0.2), HOUSE_W - 0.2), 2), round(min(max(y, 0.2), HOUSE_L - 0.2), 2)
            t = true_field(x, y)
            k += 1
            sections[f"S{k}"] = {
                "meta": {"x": x, "y": y, "name": f"Section {k}"},
                "latest": {**t, "timestamp": now, "vpd": 1.0},
            }
    return {"sections": sections}


def leave_one_out(house: dict) -> dict:
    """Hide each section in turn, estimate it from the rest, measure the error."""
    captured = {}
    sp._fb_put = lambda p, v: captured.__setitem__(p.split("/")[-2], v) or True

    errs = {f: [] for f in sp.FIELDS}
    sds = {f: [] for f in sp.FIELDS}
    skipped = 0
    ids = list(house["sections"])
    for held in ids:
        trial = {"sections": {}}
        for sid, sec in house["sections"].items():
            if sid == held:
                trial["sections"][sid] = {"meta": sec["meta"]}      # coordinates only
            else:
                trial["sections"][sid] = sec
        captured.clear()
        r = sp.interpolate_house("HSIM", trial)
        if r["status"] != "ok" or held not in captured:
            skipped += 1
            continue
        got, want = captured[held], house["sections"][held]["latest"]
        for f in sp.FIELDS:
            if f in got and f in want:
                errs[f].append(abs(got[f] - want[f]))
                sds[f].append(got.get(f + "Sd", float("nan")))
    return {"errors": errs, "sds": sds, "skipped": skipped, "n": len(ids)}


def main():
    print(f"Simulated shade house {HOUSE_W:.0f} x {HOUSE_L:.0f} m, "
          f"light and temperature falling with depth from the open edge.\n")
    print(f"{'nodes':>6} {'held-out MAE':>34}   {'reported SD':>26}")
    print(f"{'':>6} {'temp C':>10} {'humidity %':>11} {'light':>11}   "
          f"{'temp':>7} {'humid':>8} {'light':>8}")

    # Averaged over many layouts. A single jittered grid is luck: one run had
    # twelve nodes scoring worse than ten, which says more about where that
    # particular grid fell than about how many nodes a farm needs.
    REPEATS = 25
    for n in (4, 5, 6, 8, 10, 12, 16, 20):
        agg = {f: [] for f in sp.FIELDS}
        agg_sd = {f: [] for f in sp.FIELDS}
        skipped = 0
        for rep in range(REPEATS):
            global RNG
            RNG = random.Random(1000 + rep)
            sp.RNG = RNG
            house = build_house(n)
            out = leave_one_out(house)
            skipped += out["skipped"]
            for f in sp.FIELDS:
                agg[f].extend(out["errors"][f])
                agg_sd[f].extend(x for x in out["sds"][f] if x == x)
        def m(d, f):
            return (sum(d[f]) / len(d[f])) if d[f] else float("nan")
        note = "   all refused" if not agg["temperature"] else ""
        print(f"{n:>6} {m(agg,'temperature'):>10.2f} {m(agg,'humidity'):>11.2f} "
              f"{m(agg,'light'):>11.0f}   {m(agg_sd,'temperature'):>7.2f} "
              f"{m(agg_sd,'humidity'):>8.2f} {m(agg_sd,'light'):>8.0f}{note}")

    print("\nRead the two halves against each other: the left is how wrong the")
    print("estimate was, the right is how wrong the model SAID it might be. A")
    print("reported SD far larger than the actual error means the estimate is")
    print("honest but not yet useful - which is the state to look for.")

    # What the real farm would need
    print("\nFor reference, the true field spans:")
    xs = [(x, y) for x in (0.5, HOUSE_W / 2, HOUSE_W - 0.5) for y in (0.5, HOUSE_L - 0.5)]
    t = [true_field(x, y) for x, y in xs]
    for f in sp.FIELDS:
        vals = [q[f] for q in t]
        print(f"  {f:12} {min(vals):8.1f} to {max(vals):8.1f}")


if __name__ == "__main__":
    main()
