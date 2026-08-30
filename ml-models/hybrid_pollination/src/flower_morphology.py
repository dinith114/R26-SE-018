"""
Hybrid Pollination - Flower Morphological Feature Extraction

Extracts the flower traits the methodology specifies:

    petal shape
    flower symmetry
    colour patterns
    lip structure (labellum)
    flower size and structure

These are the characteristics a breeder uses when choosing hybrid parents, and
they are the features the compatibility work was originally designed around.

WHERE THESE CAN AND CANNOT BE MEASURED
---------------------------------------
On background-removed images the flower region separates cleanly from foliage,
and every measurement below is meaningful.

On whole-plant nursery photographs they are NOT reliable, and that is a
measured conclusion rather than a caution: a backlit bloom was found to be less
saturated (hue ~14 / saturation ~33) than the sky visible between the leaves
(hue ~109 / saturation ~44), so the flower region cannot be isolated in the
first place. Every function here therefore reports a `reliable` flag, and it is
false when the flower region is too small or too poorly separated to trust.

Orchid flowers are ZYGOMORPHIC - bilaterally symmetric, with one mirror plane
through the lip. That is a real botanical property and is what makes the
symmetry measurement meaningful rather than decorative: a well-formed bloom has
high bilateral symmetry, and breeders select for it.
"""

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


MIN_FLOWER_AREA = 300      # px, below this nothing is measurable
BG_VALUE, BG_SATURATION = 225, 35
LEAF_HUE_LO, LEAF_HUE_HI = 28, 95


# ──────────────────────────────────────────────
# Region isolation
# ──────────────────────────────────────────────
def isolate_flower(img: np.ndarray) -> tuple:
    """
    Separate the flower from foliage and background on a cutout image.

    Returns:
        (flower_mask, plant_mask)
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

    background = (V >= BG_VALUE) & (S <= BG_SATURATION)
    plant = (~background).astype(np.uint8) * 255

    foliage = ((H >= LEAF_HUE_LO) & (H <= LEAF_HUE_HI)).astype(np.uint8) * 255
    foliage = cv2.bitwise_and(foliage, plant)

    coloured = (S >= 45).astype(np.uint8) * 255
    flower = cv2.bitwise_and(cv2.bitwise_and(plant, cv2.bitwise_not(foliage)), coloured)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    flower = cv2.morphologyEx(flower, cv2.MORPH_OPEN, kernel, iterations=1)
    flower = cv2.morphologyEx(flower, cv2.MORPH_CLOSE, kernel, iterations=2)

    return flower, plant


# ──────────────────────────────────────────────
# Petal shape and structure
# ──────────────────────────────────────────────
def petal_shape_features(flower: np.ndarray) -> dict:
    """
    Shape descriptors of the bloom outline.

    A Vanda flower is a flat rosette of broad rounded segments; a Papilionanthe
    or terete-type bloom is narrower and more star-like. Circularity, solidity
    and the number of outline lobes separate these.
    """
    f = {"petal_circularity": 0.0, "petal_solidity": 0.0, "petal_aspect": 0.0,
         "petal_extent": 0.0, "petal_lobes": 0, "petal_roughness": 0.0}

    contours, _ = cv2.findContours(flower, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = [c for c in contours if cv2.contourArea(c) >= MIN_FLOWER_AREA]
    if not contours:
        return f

    big = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(big)
    perim = cv2.arcLength(big, True)
    hull = cv2.convexHull(big)
    hull_area = cv2.contourArea(hull)
    x, y, w, h = cv2.boundingRect(big)

    f["petal_circularity"] = float(4 * np.pi * area / (perim ** 2)) if perim > 0 else 0.0
    f["petal_solidity"] = float(area / hull_area) if hull_area > 0 else 0.0
    f["petal_aspect"] = float(w / h) if h > 0 else 0.0
    f["petal_extent"] = float(area / (w * h)) if w * h > 0 else 0.0

    # Lobe count: convexity defects deep enough to be the notch between two
    # perianth segments rather than contour noise
    try:
        hull_idx = cv2.convexHull(big, returnPoints=False)
        if len(hull_idx) > 3 and len(big) > 3:
            defects = cv2.convexityDefects(big, np.sort(hull_idx[:, 0])[::-1][:, None])
            if defects is not None:
                threshold = max(600, area * 0.01)
                f["petal_lobes"] = int(sum(1 for d in defects[:, 0, 3] if d > threshold))
    except cv2.error:
        pass

    # Outline roughness: how far the true outline departs from its hull
    hull_perim = cv2.arcLength(hull, True)
    f["petal_roughness"] = float(perim / hull_perim) if hull_perim > 0 else 0.0

    return f


# ──────────────────────────────────────────────
# Symmetry
# ──────────────────────────────────────────────
def symmetry_features(flower: np.ndarray) -> dict:
    """
    Bilateral symmetry of the bloom.

    Orchids are zygomorphic: one mirror plane, running vertically through the
    lip. The mask is centred on its own centroid, aligned to its principal axis,
    then compared with its mirror image. Breeders select for well-formed,
    symmetric flowers, so this is a trait with real selection value.
    """
    f = {"symmetry_vertical": 0.0, "symmetry_horizontal": 0.0,
         "symmetry_axis_angle": 0.0}

    ys, xs = np.nonzero(flower)
    if len(xs) < MIN_FLOWER_AREA:
        return f

    # Principal axis, so a tilted bloom is not scored as asymmetric
    coords = np.stack([xs - xs.mean(), ys - ys.mean()]).astype(np.float32)
    cov = np.cov(coords)
    eigvals, eigvecs = np.linalg.eigh(cov)
    axis = eigvecs[:, np.argmax(eigvals)]
    angle = float(np.degrees(np.arctan2(axis[1], axis[0])))
    f["symmetry_axis_angle"] = round(angle, 2)

    h, w = flower.shape
    centre = (float(xs.mean()), float(ys.mean()))
    rot = cv2.getRotationMatrix2D(centre, angle, 1.0)
    aligned = cv2.warpAffine(flower, rot, (w, h), flags=cv2.INTER_NEAREST)

    ys2, xs2 = np.nonzero(aligned)
    if len(xs2) < MIN_FLOWER_AREA:
        return f

    x0, x1 = xs2.min(), xs2.max()
    y0, y1 = ys2.min(), ys2.max()
    crop = aligned[y0:y1 + 1, x0:x1 + 1]
    if crop.size == 0:
        return f

    def overlap(a, b):
        inter = np.logical_and(a > 0, b > 0).sum()
        union = np.logical_or(a > 0, b > 0).sum()
        return float(inter / union) if union else 0.0

    f["symmetry_vertical"] = round(overlap(crop, cv2.flip(crop, 1)), 4)    # left/right
    f["symmetry_horizontal"] = round(overlap(crop, cv2.flip(crop, 0)), 4)  # top/bottom

    return f


# ──────────────────────────────────────────────
# Colour pattern
# ──────────────────────────────────────────────
def colour_pattern_features(img: np.ndarray, flower: np.ndarray) -> dict:
    """
    Colour distribution across the bloom.

    Distinguishes a plain flower from a spotted or tessellated one by how
    variable the colour is WITHIN the bloom, and how much of it departs from the
    bloom's own dominant tone. Measured relative to the flower itself so that
    exposure does not decide the answer.
    """
    f = {"colour_uniformity": 0.0, "colour_spread": 0.0, "spot_fraction": 0.0,
         "pattern": "unknown", "dominant_hue": 0.0, "secondary_fraction": 0.0}

    m = flower > 0
    if m.sum() < MIN_FLOWER_AREA:
        return f

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H = hsv[:, :, 0][m].astype(np.float32)
    S = hsv[:, :, 1][m].astype(np.float32)
    V = hsv[:, :, 2][m].astype(np.float32)

    f["dominant_hue"] = float(np.median(H))
    f["colour_spread"] = float(np.percentile(H, 75) - np.percentile(H, 25))
    f["colour_uniformity"] = float(1.0 / (1.0 + H.std()))

    # Tissue markedly darker than the bloom's own median = spot or vein
    dark = V < (np.median(V) - 35)
    f["spot_fraction"] = float(dark.mean())

    # Tissue at a clearly different hue = a second colour, e.g. a coloured lip
    off_hue = np.abs(H - np.median(H)) > 15
    f["secondary_fraction"] = float(off_hue.mean())

    if f["spot_fraction"] > 0.22:
        f["pattern"] = "tessellated"
    elif f["spot_fraction"] > 0.08:
        f["pattern"] = "spotted"
    elif f["secondary_fraction"] > 0.25:
        f["pattern"] = "bicolour"
    else:
        f["pattern"] = "plain"

    return f


# ──────────────────────────────────────────────
# Lip (labellum)
# ──────────────────────────────────────────────
def lip_features(img: np.ndarray, flower: np.ndarray) -> dict:
    """
    Approximate the labellum - the modified lower petal.

    The lip matters to this project specifically: it carries the column, and the
    pollinia sit under the anther cap at its base. It is usually a different
    colour from the petals and sits at the bottom of the bloom.

    This is an APPROXIMATION by colour and position, not a trained detector, and
    `lip_confidence` says how distinct the candidate actually was. On a plain
    single-coloured flower the lip cannot be separated at all, and the
    confidence correctly falls to near zero.
    """
    f = {"lip_area_ratio": 0.0, "lip_hue_offset": 0.0, "lip_relative_y": 0.0,
         "lip_confidence": 0.0}

    m = flower > 0
    if m.sum() < MIN_FLOWER_AREA:
        return f

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H = hsv[:, :, 0].astype(np.float32)
    median_hue = float(np.median(H[m]))

    # Candidate lip: flower tissue whose hue departs from the bloom's dominant
    off = (np.abs(H - median_hue) > 15) & m
    off_mask = (off.astype(np.uint8)) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    off_mask = cv2.morphologyEx(off_mask, cv2.MORPH_OPEN, kernel, iterations=1)

    n, labels, stats, centroids = cv2.connectedComponentsWithStats(
        (off_mask > 0).astype(np.uint8), 8)
    if n <= 1:
        return f

    # Largest distinct-coloured region
    idx = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    lip_area = int(stats[idx, cv2.CC_STAT_AREA])
    flower_area = int(m.sum())

    if lip_area < 40:
        return f

    f["lip_area_ratio"] = round(lip_area / flower_area, 4)
    f["lip_hue_offset"] = round(abs(float(np.median(H[labels == idx])) - median_hue), 2)

    # Vertical position within the bloom: 0 = top, 1 = bottom. A real lip sits low.
    ys = np.nonzero(m)[0]
    lip_y = float(centroids[idx][1])
    span = float(ys.max() - ys.min()) or 1.0
    f["lip_relative_y"] = round((lip_y - ys.min()) / span, 3)

    # Confident when the region is a sensible size, clearly off-hue, and low
    size_ok = 0.03 <= f["lip_area_ratio"] <= 0.45
    hue_ok = f["lip_hue_offset"] >= 15
    pos_ok = f["lip_relative_y"] >= 0.35
    f["lip_confidence"] = round(
        (0.4 * size_ok + 0.35 * hue_ok + 0.25 * pos_ok), 2)

    return f


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────
def extract_flower_morphology(image_path: str = None, img: np.ndarray = None) -> dict:
    """
    All flower morphological features for one image.

    Returns a dict including `reliable`, which is False when the flower region
    is too small or too poorly separated for the measurements to mean anything.
    Callers must check it rather than using the numbers blindly.
    """
    if img is None:
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Could not read {image_path}")

    flower, plant = isolate_flower(img)

    flower_area = int(cv2.countNonZero(flower))
    plant_area = int(cv2.countNonZero(plant))
    frame_area = img.shape[0] * img.shape[1]

    features = {
        "flower_area_px": flower_area,
        "flower_frame_ratio": round(flower_area / frame_area, 4),
        "flower_plant_ratio": round(flower_area / plant_area, 4) if plant_area else 0.0,
        "reliable": flower_area >= MIN_FLOWER_AREA,
    }

    features.update(petal_shape_features(flower))
    features.update(symmetry_features(flower))
    features.update(colour_pattern_features(img, flower))
    features.update(lip_features(img, flower))

    if not features["reliable"]:
        features["note"] = ("No flower region large enough to measure. On a "
                            "whole-plant photograph this is expected - flower "
                            "morphology needs a bloom close-up.")

    return features


def get_morphology_feature_names() -> list:
    return [
        "flower_area_px", "flower_frame_ratio", "flower_plant_ratio",
        "petal_circularity", "petal_solidity", "petal_aspect", "petal_extent",
        "petal_lobes", "petal_roughness",
        "symmetry_vertical", "symmetry_horizontal", "symmetry_axis_angle",
        "colour_uniformity", "colour_spread", "spot_fraction",
        "dominant_hue", "secondary_fraction",
        "lip_area_ratio", "lip_hue_offset", "lip_relative_y", "lip_confidence",
    ]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Extract flower morphology")
    parser.add_argument("--image", required=True)
    args = parser.parse_args()

    f = extract_flower_morphology(args.image)

    print("\n" + "=" * 58)
    print("FLOWER MORPHOLOGY")
    print("=" * 58)
    print(f"  reliable: {f['reliable']}")
    if not f["reliable"]:
        print(f"  {f.get('note', '')}")
    print(f"\n  Size      area={f['flower_area_px']}px  "
          f"{f['flower_plant_ratio']:.1%} of plant")
    print(f"  Petal     circularity={f['petal_circularity']:.3f}  "
          f"solidity={f['petal_solidity']:.3f}  lobes={f['petal_lobes']}")
    print(f"  Symmetry  vertical={f['symmetry_vertical']:.3f}  "
          f"horizontal={f['symmetry_horizontal']:.3f}")
    print(f"  Pattern   {f['pattern']}  (spots {f['spot_fraction']:.1%}, "
          f"second colour {f['secondary_fraction']:.1%})")
    print(f"  Lip       area={f['lip_area_ratio']:.1%}  "
          f"hue offset={f['lip_hue_offset']:.0f}  confidence={f['lip_confidence']:.2f}")
    print("=" * 58)
