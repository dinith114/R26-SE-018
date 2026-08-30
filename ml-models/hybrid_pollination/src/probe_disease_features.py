"""
Hybrid Pollination - Disease Feature Probe

Diagnostic tool, not part of the runtime pipeline.

Computes a wide set of candidate disease measurements on every annotated plant
image, then ranks each one by how well it separates diseased from healthy
plants. The heuristic provider is then built only from measurements that
actually carry signal, instead of from thresholds chosen by eye.

The first hand-tuned attempt scored a healthy plant as MORE diseased than a
diseased one, because:
  - absolute yellow bands flag healthy Vanda foliage, which is naturally
    yellow-green under high light
  - black-hat lesion detection fires on water droplets and the shadows
    between overlapping leaves

So most candidates here are measured RELATIVE to each plant's own leaf tone,
which removes both the species colour bias and the exposure differences
between photographs.

Usage:
    python src/probe_disease_features.py
    python src/probe_disease_features.py --per-plant 6
"""

import os
import sys
import argparse

import cv2
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from segmentation import segment_plant


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLEAN_CSV = os.path.join(BASE_DIR, "data", "image_annotations_clean.csv")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
PROBE_CSV = os.path.join(RESULTS_DIR, "disease_feature_probe.csv")


# ──────────────────────────────────────────────
# Candidate measurements
# ──────────────────────────────────────────────
def probe_features(image_path: str) -> dict:
    """Compute every candidate disease measurement for one image."""
    seg = segment_plant(image_path)
    img, mask = seg["image"], seg["plant_mask"]

    leaf_area = int(cv2.countNonZero(mask))
    if leaf_area < 500:
        return None

    m = mask > 0
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    H, S, V = (hsv[:, :, i][m].astype(np.float32) for i in range(3))
    L, A, B = (lab[:, :, i][m].astype(np.float32) for i in range(3))

    f = {"leaf_area_px": leaf_area,
         "isolation": seg["isolation"],
         "coverage": seg["coverage"]}

    # ── Absolute colour statistics ────────────
    f["hue_mean"], f["hue_std"] = float(H.mean()), float(H.std())
    f["sat_mean"], f["sat_std"] = float(S.mean()), float(S.std())
    f["val_mean"], f["val_std"] = float(V.mean()), float(V.std())
    f["lab_a_mean"] = float(A.mean())     # higher = shifted toward red
    f["lab_b_mean"] = float(B.mean())     # higher = shifted toward yellow
    f["lab_a_std"], f["lab_b_std"] = float(A.std()), float(B.std())

    # ── Relative colour: deviation from THIS plant's own leaf tone ────
    # Removes both the natural yellow-green of Vanda and per-photo exposure.
    hue_med, val_med, sat_med = np.median(H), np.median(V), np.median(S)
    f["hue_below_med_frac"] = float((H < hue_med - 6).mean())   # yellower than typical
    f["hue_iqr"] = float(np.percentile(H, 75) - np.percentile(H, 25))
    f["val_iqr"] = float(np.percentile(V, 75) - np.percentile(V, 25))
    f["sat_iqr"] = float(np.percentile(S, 75) - np.percentile(S, 25))

    # Tissue markedly darker than the plant's own median = candidate necrosis
    for k in (30, 50, 70):
        f[f"dark_rel_{k}"] = float((V < val_med - k).mean())
    # Tissue markedly less saturated = candidate bleaching
    f["desat_rel_40"] = float((S < sat_med - 40).mean())

    # ── Lesion detection at several scales ────
    for ksize in (9, 15, 25):
        f.update(_lesion_stats(gray, mask, ksize, leaf_area))

    # ── Texture ───────────────────────────────
    lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    f["lap_var"] = float(lap[m].var())

    edges = cv2.Canny(gray, 60, 160)
    f["edge_density"] = float(cv2.countNonZero(cv2.bitwise_and(edges, mask)) / leaf_area)

    # ── Shape: ragged outlines suggest damaged leaves ────
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        big = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(big)
        hull = cv2.contourArea(cv2.convexHull(big))
        perim = cv2.arcLength(big, True)
        f["solidity"] = float(area / hull) if hull > 0 else 0.0
        f["perim_area_ratio"] = float(perim / np.sqrt(area)) if area > 0 else 0.0
    else:
        f["solidity"], f["perim_area_ratio"] = 0.0, 0.0

    return f


def _lesion_stats(gray: np.ndarray, mask: np.ndarray, ksize: int, leaf_area: int) -> dict:
    """
    Dark-spot statistics at one scale.

    Eroding the mask before counting keeps leaf-edge darkness out, and the
    circularity filter rejects the elongated shadows between leaves. Water
    droplets survive both, which is why these must be validated rather than
    trusted.
    """
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksize, ksize))
    blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, kernel)

    inner = cv2.erode(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)))

    out = {}
    for contrast in (25, 40):
        _, spots = cv2.threshold(blackhat, contrast, 255, cv2.THRESH_BINARY)
        spots = cv2.bitwise_and(spots, inner)
        spots = cv2.morphologyEx(
            spots, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        )

        n, labels, stats, _ = cv2.connectedComponentsWithStats((spots > 0).astype(np.uint8), 8)
        count, total = 0, 0
        for lab in range(1, n):
            a = stats[lab, cv2.CC_STAT_AREA]
            w, h = stats[lab, cv2.CC_STAT_WIDTH], stats[lab, cv2.CC_STAT_HEIGHT]
            if a < 8 or a > 1200 or w == 0 or h == 0:
                continue
            if max(w, h) / min(w, h) > 3.5 or a / float(w * h) < 0.35:
                continue
            count += 1
            total += int(a)

        out[f"lesion_n_k{ksize}_c{contrast}"] = count
        out[f"lesion_dens_k{ksize}_c{contrast}"] = total / leaf_area

    return out


# ──────────────────────────────────────────────
# Ranking
# ──────────────────────────────────────────────
def plant_level_auc(plants: pd.DataFrame, col: str) -> float:
    """ROC AUC of one measurement against the disease annotation, per plant."""
    y = (plants.annotated == "yes").astype(int).values
    x = plants[col].values

    if np.all(~np.isfinite(x)) or len(np.unique(y)) < 2:
        return float("nan")

    x = np.nan_to_num(x, nan=float(np.nanmedian(x)))
    ranks = pd.Series(x).rank().values
    n_pos, n_neg = int(y.sum()), int((1 - y).sum())
    if n_pos == 0 or n_neg == 0:
        return float("nan")

    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-plant", type=int, default=6,
                        help="Images to sample per plant (keeps the probe fast)")
    parser.add_argument("--recompute", action="store_true")
    args = parser.parse_args()

    os.makedirs(RESULTS_DIR, exist_ok=True)

    if os.path.exists(PROBE_CSV) and not args.recompute:
        print(f"[INFO] Reusing {os.path.basename(PROBE_CSV)} (--recompute to refresh)")
        probe = pd.read_csv(PROBE_CSV)
    else:
        df = pd.read_csv(CLEAN_CSV)
        df = df[df.disease_visible.isin(["yes", "no"])]
        # Evenly sample within each plant so one heavily photographed plant
        # does not dominate its own average
        picks = []
        for _, g in df.groupby("sample_id", sort=False):
            step = max(1, len(g) // args.per_plant)
            picks.append(g.iloc[::step].head(args.per_plant))
        df = pd.concat(picks, ignore_index=True)

        print(f"[STEP] Probing {len(df)} images across {df.sample_id.nunique()} plants...")
        rows = []
        for i, (_, r) in enumerate(df.iterrows(), 1):
            if i % 20 == 0:
                print(f"  {i}/{len(df)}")
            try:
                f = probe_features(r["image_path"])
            except Exception as e:
                print(f"  [WARN] {r['image_name']}: {e}")
                continue
            if f is None:
                continue
            f.update({"sample_id": r["sample_id"], "image_name": r["image_name"],
                      "annotated": r["disease_visible"]})
            rows.append(f)

        probe = pd.DataFrame(rows)
        probe.to_csv(PROBE_CSV, index=False)
        print(f"[SAVED] {os.path.basename(PROBE_CSV)}")

    # Collapse to plant level
    meta = ["sample_id", "image_name", "annotated"]
    feat_cols = [c for c in probe.columns if c not in meta]
    plants = probe.groupby("sample_id").agg(
        {**{c: "median" for c in feat_cols}, "annotated": lambda s: s.mode().iloc[0]}
    ).reset_index()

    n_pos = int((plants.annotated == "yes").sum())
    print("\n" + "=" * 72)
    print("DISEASE FEATURE RANKING  (plant level, AUC vs annotation)")
    print("=" * 72)
    print(f"Plants: {len(plants)}   diseased={n_pos}   healthy={len(plants) - n_pos}")
    print("\nAUC 0.50 = no signal.  Below 0.50 means the feature is INVERTED")
    print("(higher value predicts HEALTHY), which is still usable information.\n")

    scored = [(c, plant_level_auc(plants, c)) for c in feat_cols]
    scored = [(c, a) for c, a in scored if np.isfinite(a)]
    scored.sort(key=lambda t: abs(t[1] - 0.5), reverse=True)

    print(f"{'feature':34s} {'AUC':>7s}  {'|AUC-.5|':>9s}  direction")
    print("-" * 72)
    for c, a in scored[:26]:
        direction = "higher = diseased" if a > 0.5 else "higher = healthy"
        print(f"{c:34s} {a:7.3f}  {abs(a - 0.5):9.3f}  {direction}")

    print("=" * 72)
    out = os.path.join(RESULTS_DIR, "disease_feature_ranking.csv")
    pd.DataFrame(scored, columns=["feature", "auc"]).to_csv(out, index=False)
    print(f"[SAVED] {os.path.basename(out)}")


if __name__ == "__main__":
    main()
