"""
Hybrid Pollination - Masked Trait Features

Feature extraction for leaf condition and plant strength, measured ONLY on
segmented plant pixels.

Why this exists alongside feature_extraction.py
------------------------------------------------
The original extractor averages colour and texture over the entire frame. In
this dataset the frame is mostly nursery background - other plants, shade
netting, laterite gravel, concrete - so those averages largely describe the
background, not the plant. That is why image-only suitability scored 0.314,
below the 0.639 majority baseline.

Everything here is computed inside the plant mask, and every colour measure is
expressed RELATIVE to the plant's own tone where possible, so that a naturally
yellow-green Vanda under bright light is not confused with a chlorotic one.

Feature groups:
    health    - greenness, yellowing, dead tissue, colour uniformity
    structure - leaf count, leaf elongation, fan spread, plant extent
    texture   - surface detail, which separates firm leaves from shrivelled ones
"""

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from segmentation import segment_plant


# ──────────────────────────────────────────────
# Health features
# ──────────────────────────────────────────────
def health_features(img: np.ndarray, mask: np.ndarray) -> dict:
    """
    Colour-based condition of the leaf tissue.

    A healthy Vanda leaf is uniformly green with high chroma. A weak one is
    yellowed, patchy, or carries dead brown tissue. Both absolute and relative
    measures are kept: absolute catches genuinely pale plants, relative catches
    plants that are uneven regardless of overall exposure.
    """
    m = mask > 0
    area = int(m.sum())
    if area < 200:
        return {k: 0.0 for k in _health_names()}

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)

    H = hsv[:, :, 0][m].astype(np.float32)
    S = hsv[:, :, 1][m].astype(np.float32)
    V = hsv[:, :, 2][m].astype(np.float32)
    A = lab[:, :, 1][m].astype(np.float32)   # green(-) to red(+)
    B = lab[:, :, 2][m].astype(np.float32)   # blue(-) to yellow(+)

    f = {}

    # Absolute colour position
    f["hue_mean"] = float(H.mean())
    f["hue_std"] = float(H.std())
    f["sat_mean"] = float(S.mean())
    f["sat_std"] = float(S.std())
    f["val_mean"] = float(V.mean())
    f["val_std"] = float(V.std())
    f["lab_a_mean"] = float(A.mean())    # lower = greener
    f["lab_b_mean"] = float(B.mean())    # higher = yellower

    # Tissue fractions within the plant
    f["frac_green"] = float(((H >= 35) & (H <= 85)).mean())
    f["frac_yellow"] = float(((H >= 20) & (H < 35)).mean())
    f["frac_dark"] = float((V < 60).mean())
    f["frac_pale"] = float((S < 50).mean())

    # Relative spread - uneven colour signals patchy, declining tissue
    f["hue_iqr"] = float(np.percentile(H, 75) - np.percentile(H, 25))
    f["val_iqr"] = float(np.percentile(V, 75) - np.percentile(V, 25))
    f["sat_iqr"] = float(np.percentile(S, 75) - np.percentile(S, 25))

    # Deviation from the plant's own median: how much tissue is off-tone
    f["frac_below_med_val"] = float((V < np.median(V) - 40).mean())
    f["frac_off_hue"] = float((np.abs(H - np.median(H)) > 12).mean())

    # Greenness index over plant pixels only
    img_f = img.astype(np.float32) / 255.0
    b, g, r = cv2.split(img_f)
    total = r + g + b + 1e-6
    exg = ((2 * g - r - b) / total)[m]
    f["exg_mean"] = float(exg.mean())
    f["exg_std"] = float(exg.std())

    return f


def _health_names():
    return ["hue_mean", "hue_std", "sat_mean", "sat_std", "val_mean", "val_std",
            "lab_a_mean", "lab_b_mean", "frac_green", "frac_yellow", "frac_dark",
            "frac_pale", "hue_iqr", "val_iqr", "sat_iqr", "frac_below_med_val",
            "frac_off_hue", "exg_mean", "exg_std"]


# ──────────────────────────────────────────────
# Structure features
# ──────────────────────────────────────────────
def structure_features(img: np.ndarray, mask: np.ndarray) -> dict:
    """
    Physical build of the plant: how many leaves, how long, how spread out.

    This is what the nursery owner meant by a "strong" plant - more leaves,
    longer leaves, an upright well-filled fan. The annotated `leaf_count`
    column is useless (it reads "many" on 100% of rows), so leaf count is
    measured here instead.

    All measures are scale-invariant ratios rather than pixel sizes, because
    absolute size from an uncalibrated phone photograph is meaningless - the
    same plant photographed a step closer would look twice as strong.
    """
    f = {}
    m = mask > 0
    frame_area = img.shape[0] * img.shape[1]
    area = int(m.sum())

    f["plant_coverage"] = float(area / frame_area)
    if area < 200:
        return {**f, **{k: 0.0 for k in _structure_names() if k != "plant_coverage"}}

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return {**f, **{k: 0.0 for k in _structure_names() if k != "plant_coverage"}}

    big = max(contours, key=cv2.contourArea)
    c_area = cv2.contourArea(big)
    perim = cv2.arcLength(big, True)
    hull = cv2.convexHull(big)
    hull_area = cv2.contourArea(hull)

    # Solidity: a full leafy fan fills its hull; a sparse plant does not
    f["solidity"] = float(c_area / hull_area) if hull_area > 0 else 0.0
    # A spiky many-leaved outline has a long perimeter for its area
    f["perimeter_ratio"] = float(perim / np.sqrt(c_area)) if c_area > 0 else 0.0

    x, y, w, h = cv2.boundingRect(big)
    f["aspect_ratio"] = float(w / h) if h > 0 else 0.0
    f["extent"] = float(c_area / (w * h)) if w * h > 0 else 0.0

    # Leaf counting by skeleton branch density.
    # Vanda leaves are long straight straps radiating from a central stem, so
    # the number of protrusions from the plant's core approximates leaf count.
    f.update(_leaf_estimate(mask))

    # Convexity defects count the notches between adjacent leaves
    try:
        hull_idx = cv2.convexHull(big, returnPoints=False)
        if len(hull_idx) > 3 and len(big) > 3:
            defects = cv2.convexityDefects(big, np.sort(hull_idx[:, 0])[::-1][:, None])
            if defects is not None:
                deep = [d for d in defects[:, 0, 3] if d > 1000]
                f["notch_count"] = float(len(deep))
                f["notch_depth_mean"] = float(np.mean(deep) / 256.0) if deep else 0.0
            else:
                f["notch_count"], f["notch_depth_mean"] = 0.0, 0.0
        else:
            f["notch_count"], f["notch_depth_mean"] = 0.0, 0.0
    except cv2.error:
        f["notch_count"], f["notch_depth_mean"] = 0.0, 0.0

    return f


def _leaf_estimate(mask: np.ndarray) -> dict:
    """
    Estimate leaf count and elongation from the plant mask.

    Erosion separates the leaves: the narrow strap of each leaf disappears
    before the thick central crown does, so counting components part-way
    through erosion approximates counting leaves.
    """
    out = {}
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    counts, elongations = [], []
    eroded = mask.copy()
    for step in range(1, 5):
        eroded = cv2.erode(eroded, kernel, iterations=1)
        n, _, stats, _ = cv2.connectedComponentsWithStats((eroded > 0).astype(np.uint8), 8)

        blobs = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] > 80]
        counts.append(len(blobs))

        for i in blobs:
            w, h = stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]
            if w > 0 and h > 0:
                elongations.append(max(w, h) / min(w, h))

    out["leaf_count_est"] = float(max(counts) if counts else 0)
    out["leaf_count_mean"] = float(np.mean(counts)) if counts else 0.0
    out["leaf_elongation"] = float(np.mean(elongations)) if elongations else 0.0
    out["leaf_elongation_max"] = float(np.max(elongations)) if elongations else 0.0
    return out


def _structure_names():
    return ["plant_coverage", "solidity", "perimeter_ratio", "aspect_ratio",
            "extent", "leaf_count_est", "leaf_count_mean", "leaf_elongation",
            "leaf_elongation_max", "notch_count", "notch_depth_mean"]


# ──────────────────────────────────────────────
# Texture features
# ──────────────────────────────────────────────
def texture_features(img: np.ndarray, mask: np.ndarray) -> dict:
    """
    Surface detail inside the plant.

    A firm healthy leaf is smooth; a shrivelled or damaged one carries wrinkles,
    creases and edge damage that raise local contrast.
    """
    m = mask > 0
    if m.sum() < 200:
        return {k: 0.0 for k in _texture_names()}

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    blur = cv2.GaussianBlur(gray, (9, 9), 0)
    detail = cv2.absdiff(gray, blur).astype(np.float32)

    edges = cv2.Canny(gray, 60, 160)
    edge_in = cv2.bitwise_and(edges, mask)

    return {
        "lap_var": float(lap[m].var()),
        "lap_abs_mean": float(np.abs(lap[m]).mean()),
        "detail_mean": float(detail[m].mean()),
        "detail_std": float(detail[m].std()),
        "edge_density": float(cv2.countNonZero(edge_in) / max(int(m.sum()), 1)),
    }


def _texture_names():
    return ["lap_var", "lap_abs_mean", "detail_mean", "detail_std", "edge_density"]


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────
def extract_trait_features(image_path: str = None, img: np.ndarray = None) -> dict:
    """
    All masked trait features for one image.

    Returns ~40 features plus segmentation quality indicators. The quality
    indicators matter downstream: a low `isolation` means the frame was crowded
    with other plants, so the measurements describe the neighbourhood as much
    as the subject.
    """
    seg = segment_plant(image_path=image_path, img=img)
    image, mask = seg["image"], seg["plant_mask"]

    features = {}
    features.update(health_features(image, mask))
    features.update(structure_features(image, mask))
    features.update(texture_features(image, mask))

    features["seg_isolation"] = float(seg["isolation"])
    features["seg_coverage"] = float(seg["coverage"])

    return features


def get_trait_feature_names() -> list:
    """Feature names in a stable order."""
    return (_health_names() + _structure_names() + _texture_names()
            + ["seg_isolation", "seg_coverage"])


if __name__ == "__main__":
    names = get_trait_feature_names()
    print(f"Trait features: {len(names)}")

    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    test = os.path.join(BASE, "data", "images", "plants", "20260328_100120_HDR.jpg")
    if os.path.exists(test):
        f = extract_trait_features(test)
        print(f"\nExtracted {len(f)} features from a test image:")
        for k in names:
            print(f"  {k:24s} {f.get(k, 0.0):.4f}")
