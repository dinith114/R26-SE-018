"""The two spatial estimators, with no Firebase and no app imports.

They lived in routes/spatial_service.py, which imports smart_care_v2 at module
load. That made them untestable without the whole server, and the placement
analysis needs to call them thousands of times on stored readings. Moved here
unchanged; spatial_service re-exports them under their old names so every
existing caller keeps working.

See spatial_service.py for why linear is tried first and why IDW exists.
"""
from __future__ import annotations

import math

import numpy as np

# Inverse-distance weighting exponent. 2 is the standard choice and it IS a
# choice, not a derivation: 1 spreads influence too far across a house this
# size, and 3 makes each target almost equal to its single nearest anchor.
IDW_POWER = 2.0


def idw_field(xs, ys, zs, tx, ty):
    """Distance-weighted estimate, for when a variogram cannot be fitted.

    Returns (values, spreads). The spread is the weighted standard deviation of
    the anchors around each estimate - how much the nearby anchors disagree, NOT
    a kriging variance.
    """
    vals, spreads = [], []
    for x, y in zip(tx, ty):
        d = [math.dist((x, y), (ax, ay)) for ax, ay in zip(xs, ys)]
        if min(d) < 1e-9:
            i = d.index(min(d))
            vals.append(float(zs[i]))
            spreads.append(0.0)
            continue
        w = [1.0 / (dist ** IDW_POWER) for dist in d]
        tot = sum(w)
        v = sum(wi * zi for wi, zi in zip(w, zs)) / tot
        var = sum(wi * (zi - v) ** 2 for wi, zi in zip(w, zs)) / tot
        vals.append(float(v))
        spreads.append(float(math.sqrt(max(0.0, var))))
    return vals, spreads


def krige_field(xs, ys, zs, tx, ty):
    """One field, kriged onto the target points. (values, variances, model) or None.

    Linear first, spherical as the fallback, and a collapse to the anchor mean is
    rejected - the reasons and the measurements are in spatial_service.py.
    """
    from pykrige.ok import OrdinaryKriging

    zs_arr = np.asarray(zs, dtype=float)
    z_mean = float(np.mean(zs_arr))
    z_spread = float(np.ptp(zs_arr))

    for model in ("linear", "spherical"):
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
            if z_spread > 0.5 and np.all(np.abs(vals - z_mean) < 0.02 * z_spread):
                continue
            return vals, var, model
        except Exception:
            continue
    return None
