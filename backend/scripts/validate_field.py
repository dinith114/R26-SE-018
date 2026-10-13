"""Measure the simulated microclimate against published greenhouse behaviour.

The simulator's field is invented. That is unavoidable - the farm has one node,
and a placement algorithm cannot be developed against a house that does not
exist yet. What CAN be done is to check that the invented field behaves like the
structures the literature describes, so a placement method tuned on it is not
tuned on a fiction.

PROVENANCE, stated plainly
--------------------------
The targets below come from a literature survey run through an LLM research
tool on 30 Aug 2026. It returned NO citations - no titles, authors, years or
DOIs - and its correlation-versus-distance table is explicitly DERIVED from
assumed semivariogram parameters ("assuming a representative midday scenario...
a range of 30 m, a sill of 1.5 C^2") rather than measured.

So these are working targets, not validated benchmarks, and this file must not
be cited as though they were. What they are good for is catching a simulator
that is qualitatively wrong - a field with everything correlated at 0.99, or no
thermal lag at all, is wrong under any plausible parameter set. What they cannot
support is a claim of quantitative agreement.

Replace them with sourced figures when there are any. The three worth chasing:
a published correlation matrix or variogram from a real shade house, a measured
edge-to-centre lag, and a sensor-count-versus-RMSE curve.

Run:  python backend/scripts/validate_field.py --house HSIM
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api.routes.smart_care_v2 import _fb_get, _natural_key   # noqa: E402
from app.api.routes.house_planner import _snapshots_measured      # noqa: E402


# ── Targets ─────────────────────────────────────────────────────────────────
# Each is (low, high) and the label says what it is and how firm it is.

TARGETS = {
    # Derived from assumed variogram parameters, NOT measured. Treated as an
    # order-of-magnitude guide only.
    "corr_5m":   (0.55, 0.75, "correlation at ~5 m separation", "derived"),
    "corr_10m":  (0.30, 0.55, "correlation at ~10 m separation", "derived"),

    # Reported as measured maxima in tropical plastic greenhouses. More
    # trustworthy than the correlations, still uncited.
    "grad_max":  (3.0, 3.6, "max instantaneous horizontal spread, C", "reported"),
    "grad_mean": (1.4, 2.0, "24 h mean horizontal spread, C", "reported"),

    # Edge-to-centre propagation in porous shade-net structures, 20-60 min.
    "lag_min":   (20.0, 60.0, "edge-to-interior peak lag, minutes", "reported"),

    # PC1 share. The survey gave a wide spread (41% to 95%) across different
    # studies, so this band is correspondingly loose.
    "pc1":       (0.40, 0.95, "share of variance in the first mode", "reported"),
}


def band(name: str, value: float) -> str:
    lo, hi, label, kind = TARGETS[name]
    ok = lo <= value <= hi
    mark = "ok " if ok else "OUT"
    return "  %s  %-42s %7.3f   target %.2f-%.2f  (%s)" % (
        mark, label, value, lo, hi, kind)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--house", required=True)
    a = ap.parse_args()

    secs = _fb_get(f"/farm/houses/{a.house}/sections.json") or {}
    pos = {}
    for sid in sorted(secs, key=_natural_key):
        m = (secs[sid] or {}).get("meta") or {}
        try:
            pos[sid] = (float(m["x"]), float(m["y"]))
        except (KeyError, TypeError, ValueError):
            continue
    ids = sorted(pos, key=_natural_key)
    if len(ids) < 4:
        raise SystemExit("Need at least 4 placed sections.")

    got = _snapshots_measured(a.house, ids)
    if got is None:
        raise SystemExit("Not enough overlapping history. Run --fast-forward first.")
    fit, test = got
    M = np.vstack([fit, test])
    print(f"{a.house}: {M.shape[0]} periods x {M.shape[1]} sections\n")

    # ── correlation against separation ─────────────────────────────────────
    #
    # ON SPATIAL ANOMALIES, not on the raw series, and the difference is not a
    # detail. A variogram describes how the field varies ACROSS SPACE at an
    # instant. Correlating raw time series instead measures something else
    # entirely: every section in a greenhouse warms by day and cools by night,
    # so that shared diurnal cycle puts a floor under every pair regardless of
    # where they are. Two sensors on opposite sides of a house correlate at 0.9
    # simply because the sun rises for both of them.
    #
    # Removing each moment's spatial mean leaves what actually differs between
    # positions - which is the thing the survey's numbers describe, and the
    # thing a placement algorithm has to exploit. Chasing the raw figure down
    # towards 0.65 would have meant destroying the diurnal cycle, which is the
    # one part of the field that was never wrong.
    A = M - M.mean(axis=1, keepdims=True)
    C = np.corrcoef(A.T)
    C_raw = np.corrcoef(M.T)
    pairs = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            d = float(np.hypot(pos[ids[i]][0] - pos[ids[j]][0],
                               pos[ids[i]][1] - pos[ids[j]][1]))
            pairs.append((d, C[i, j]))

    def near(dist, tol=1.6):
        sel = [c for d, c in pairs if abs(d - dist) <= tol]
        return float(np.mean(sel)) if sel else float("nan")

    raw_pairs = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            d = float(np.hypot(pos[ids[i]][0] - pos[ids[j]][0],
                               pos[ids[i]][1] - pos[ids[j]][1]))
            raw_pairs.append((d, C_raw[i, j]))

    print("correlation against separation")
    print("   %5s  %4s  %-22s %s" % ("dist", "n", "spatial anomaly", "raw series"))
    for d in (2, 4, 6, 8, 10, 12):
        sel = [c for dd, c in pairs if abs(dd - d) <= 1.2]
        rsel = [c for dd, c in raw_pairs if abs(dd - d) <= 1.2]
        if sel:
            print("   %5.1f m  n=%-3d  %.3f  (%.3f to %.3f)     %.3f"
                  % (d, len(sel), np.mean(sel), min(sel), max(sel), np.mean(rsel)))
    print()

    # ── the checks ─────────────────────────────────────────────────────────
    # Spread of the FIELD, not of the raw readings. The reported 3.2-3.5 C
    # maxima come from kriged maps, and kriging smooths instrument scatter away;
    # raw max-minus-min adds roughly two sensor errors on top and is not the
    # same quantity. Comparing them directly made the field look 60% too
    # variable when the difference was entirely in how it was measured.
    from sim_farm import SENSOR_NOISE_C
    raw_spread = M.max(axis=1) - M.min(axis=1)
    spread = np.maximum(0.0, raw_spread - 2 * SENSOR_NOISE_C)
    sv = np.linalg.svd(M - M.mean(axis=0), compute_uv=False)
    energy = (sv ** 2) / (sv ** 2).sum()

    print("checks")
    print(band("corr_5m", near(5.0)))
    print(band("corr_10m", near(10.0)))
    print(band("grad_max", float(np.percentile(spread, 99))))
    print(band("grad_mean", float(spread.mean())))
    print(band("pc1", float(energy[0])))

    # Lag is a property of the generator rather than of the stored readings, so
    # it is read from the constant rather than inferred - inferring it from
    # eight-per-hour samples would be measuring the sampling rate.
    from sim_farm import MAX_LAG_HOURS
    print(band("lag_min", MAX_LAG_HOURS * 60))

    print("\nmode energy: " + "  ".join("%.3f" % e for e in energy[:5]))
    print("modes for 95%%: %d   for 99%%: %d   of %d sections"
          % (int(np.searchsorted(np.cumsum(energy), 0.95) + 1),
             int(np.searchsorted(np.cumsum(energy), 0.99) + 1), len(ids)))

    print("\nA field where everything correlates near 1.0, or which shows no")
    print("lag at all, is wrong under any plausible parameters. Agreement to")
    print("two decimal places with the bands above means nothing - they are")
    print("uncited, and half of them are derived rather than measured.")


if __name__ == "__main__":
    main()
