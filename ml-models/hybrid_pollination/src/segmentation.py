"""
Hybrid Pollination - Plant Segmentation Module

Isolates the subject orchid plant from the nursery background before any
trait is measured.

Why this exists:
    Feature extraction previously averaged colour and texture over the WHOLE
    frame. In this dataset the background is other green plants, teal shade
    netting, reddish laterite gravel and concrete, so those averages mostly
    described the background. Measuring "how brown is this plant" without a
    mask measures the gravel.

Two stages:
    1. Vegetation mask   - which pixels are plant material at all
    2. Subject selection - which of those pixels belong to the plant the
                           photo is ABOUT (frames often contain several)

Subject selection uses sharpness (the subject is the in-focus object) and a
mild centre prior, which together approximate "what the photographer aimed at".
"""

import cv2
import numpy as np


# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
WORK_LONG_SIDE = 512        # Long edge after resize. Aspect ratio is preserved -
                            # squashing to a square distorts leaf aspect ratios,
                            # which later become vigour features.
EXG_THRESHOLD = 0.05        # Excess-green cutoff for vegetation
FOCUS_TILE = 32             # Tile size for the sharpness map
MIN_SUBJECT_AREA = 0.02     # Reject subject blobs smaller than 2% of the frame
GRABCUT_ITERS = 3           # GrabCut refinement iterations


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def resize_long_side(img: np.ndarray, long_side: int = WORK_LONG_SIDE) -> np.ndarray:
    """
    Resize so the longer edge equals long_side, preserving aspect ratio.

    Aspect ratio matters downstream: leaf elongation and fan shape become
    vigour features, and a forced square resize would corrupt both.
    """
    h, w = img.shape[:2]
    scale = long_side / max(h, w)
    if scale >= 1.0:
        return img.copy()
    return cv2.resize(img, (int(round(w * scale)), int(round(h * scale))),
                      interpolation=cv2.INTER_AREA)


# ──────────────────────────────────────────────
# Stage 1 - Vegetation mask
# ──────────────────────────────────────────────
def vegetation_mask(img: np.ndarray) -> np.ndarray:
    """
    Mark every pixel that looks like plant material (leaf, stem or flower).

    Combines two cues so that stressed tissue is not lost:
      - Excess Green (2G - R - B), robust to illumination changes
      - A broad HSV band that also keeps yellowed (chlorotic) leaf tissue,
        which pure ExG would drop precisely when it matters most

    Args:
        img: BGR image

    Returns:
        uint8 mask, 255 = plant material
    """
    img_f = img.astype(np.float32) / 255.0
    b, g, r = cv2.split(img_f)

    # Excess Green index, normalised so lighting has less influence
    total = r + g + b + 1e-6
    exg = (2 * g - r - b) / total

    exg_mask = (exg > EXG_THRESHOLD).astype(np.uint8) * 255

    # Vegetation hue band: 25-95 covers yellow-green through green.
    # Chlorotic (yellowing) leaves sit near hue 25-40 and must be kept, since
    # losing them would hide exactly the plants we care about detecting.
    # Saturation and value floors are deliberately high: these photos are hazy
    # and backlit, and a permissive band marks sky, netting and gravel as plant.
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    hue_mask = cv2.inRange(hsv, np.array([25, 60, 40]), np.array([95, 255, 245]))

    # AND, not OR: a pixel must look green by both measures. OR was letting the
    # whole frame through on washed-out images.
    mask = cv2.bitwise_and(exg_mask, hue_mask)

    # Remove speckle, then close gaps inside leaves
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    return mask


# ──────────────────────────────────────────────
# Stage 2 - Subject selection
# ──────────────────────────────────────────────
def sharpness_map(img: np.ndarray, tile: int = FOCUS_TILE) -> np.ndarray:
    """
    Per-tile focus measure, upsampled to full resolution.

    The in-focus subject has high local Laplacian variance; blurred background
    foliage has low variance. This is a depth-from-focus proxy and is what lets
    us pick the intended plant out of a bench full of them.

    Returns:
        float32 map in [0, 1], same HxW as img
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    lap = cv2.Laplacian(gray, cv2.CV_32F, ksize=3)
    lap_sq = lap ** 2

    # Mean of squared Laplacian per tile == local variance proxy
    small = cv2.resize(lap_sq, (max(1, w // tile), max(1, h // tile)),
                       interpolation=cv2.INTER_AREA)
    small = cv2.GaussianBlur(small, (3, 3), 0)

    focus = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)

    # Normalise to [0, 1] using a high percentile so one specular highlight
    # does not flatten the whole map
    hi = np.percentile(focus, 99)
    if hi > 1e-6:
        focus = np.clip(focus / hi, 0.0, 1.0)
    else:
        focus = np.zeros_like(focus)

    return focus


def centre_prior(shape: tuple) -> np.ndarray:
    """
    Gaussian weight favouring the middle of the frame.

    Deliberately wide (sigma = 40% of the frame) so it only breaks ties between
    equally sharp regions rather than forcing a centre crop.
    """
    h, w = shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cy, cx = h / 2.0, w / 2.0
    sy, sx = h * 0.4, w * 0.4
    return np.exp(-(((yy - cy) ** 2) / (2 * sy ** 2) + ((xx - cx) ** 2) / (2 * sx ** 2)))


def subject_score(img: np.ndarray, veg: np.ndarray) -> np.ndarray:
    """
    Per-pixel "is this the subject" score, before any hard decision.

    Connected-component scoring does not work on this dataset: the subject
    touches background foliage, so the whole frame merges into one component
    and every candidate scores identically. Scoring per pixel first, and only
    then taking components, avoids that failure.

    Returns:
        float32 map in [0, 1]
    """
    focus = sharpness_map(img)
    prior = centre_prior(img.shape)

    # Sharpness is the real discriminator here - the background in these photos
    # is other plants, so no colour rule can separate them, but it is blurred.
    score = (focus ** 1.5) * (0.4 + 0.6 * prior)

    # Non-vegetation cannot be the subject plant
    score = score * (veg > 0).astype(np.float32)

    return cv2.GaussianBlur(score, (31, 31), 0)


def subject_mask(img: np.ndarray, veg: np.ndarray) -> np.ndarray:
    """
    Narrow a vegetation mask down to the single plant the photo is about.

    Seeds GrabCut from the sharpness/centre score map, then intersects the
    result back with the vegetation mask so that pots, wires and benches the
    colour model may have kept are dropped.

    Args:
        img: BGR image
        veg: vegetation mask from vegetation_mask()

    Returns:
        uint8 mask, 255 = subject plant
    """
    score = subject_score(img, veg)

    if score.max() < 1e-6:
        return veg  # No focus signal at all - fall back to all vegetation

    # Seed GrabCut: confident foreground / background from the score extremes,
    # everything between left for GrabCut's colour model to resolve.
    hi = np.percentile(score[score > 0], 75) if np.any(score > 0) else 1.0
    lo = np.percentile(score, 40)

    gc_mask = np.full(img.shape[:2], cv2.GC_PR_BGD, dtype=np.uint8)
    gc_mask[score >= lo] = cv2.GC_PR_FGD
    gc_mask[score >= hi] = cv2.GC_FGD
    gc_mask[(veg == 0) & (score < lo)] = cv2.GC_BGD

    # GrabCut needs both a foreground and a background seed to run
    if not np.any(gc_mask == cv2.GC_FGD) or not np.any(gc_mask == cv2.GC_BGD):
        mask = ((score >= hi).astype(np.uint8)) * 255
    else:
        try:
            bgd_model = np.zeros((1, 65), np.float64)
            fgd_model = np.zeros((1, 65), np.float64)
            cv2.grabCut(img, gc_mask, None, bgd_model, fgd_model,
                        GRABCUT_ITERS, cv2.GC_INIT_WITH_MASK)
            mask = np.where((gc_mask == cv2.GC_FGD) | (gc_mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
        except cv2.error:
            mask = ((score >= hi).astype(np.uint8)) * 255

    # Drop anything GrabCut kept that is not plant material
    mask = cv2.bitwise_and(mask, veg)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    # Keep the dominant blob and anything comparable to it, so a plant split by
    # an occluding wire survives as one plant
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        (mask > 0).astype(np.uint8), connectivity=8
    )
    if n_labels > 1:
        areas = stats[1:, cv2.CC_STAT_AREA]
        biggest = areas.max()
        keep = [i + 1 for i, a in enumerate(areas) if a >= biggest * 0.15]
        mask = np.isin(labels, keep).astype(np.uint8) * 255

    return mask


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────
def segment_plant(image_path: str = None, img: np.ndarray = None) -> dict:
    """
    Full segmentation pipeline.

    Args:
        image_path: Path to an image file, or
        img:        An already-loaded BGR image

    Returns:
        dict with:
            image        - resized BGR image used for all measurements
            veg_mask     - all vegetation in frame
            plant_mask   - the subject plant only
            coverage     - subject area as a fraction of the frame
            veg_coverage - all vegetation as a fraction of the frame
            isolation    - subject area / vegetation area. Low values mean the
                           frame is crowded with other plants, so downstream
                           whole-plant traits should be trusted less.
    """
    if img is None:
        if image_path is None:
            raise ValueError("Provide either image_path or img")
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Could not load image: {image_path}")

    img = resize_long_side(img, WORK_LONG_SIDE)

    veg = vegetation_mask(img)
    plant = subject_mask(img, veg)

    frame_area = img.shape[0] * img.shape[1]
    veg_area = int(cv2.countNonZero(veg))
    plant_area = int(cv2.countNonZero(plant))

    return {
        "image": img,
        "veg_mask": veg,
        "plant_mask": plant,
        "coverage": plant_area / frame_area,
        "veg_coverage": veg_area / frame_area,
        "isolation": (plant_area / veg_area) if veg_area > 0 else 0.0,
    }


def apply_mask(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Black out everything outside the mask (for visualisation and debugging)."""
    return cv2.bitwise_and(img, img, mask=mask)


def overlay_mask(img: np.ndarray, mask: np.ndarray, colour=(0, 255, 0), alpha=0.4) -> np.ndarray:
    """Tint the masked region so a human can check the segmentation by eye."""
    layer = img.copy()
    layer[mask > 0] = colour
    return cv2.addWeighted(layer, alpha, img, 1 - alpha, 0)


# ──────────────────────────────────────────────
# Test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import os

    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    plant_dir = os.path.join(BASE_DIR, "data", "images", "plants")
    out_dir = os.path.join(BASE_DIR, "results", "segmentation_check")
    os.makedirs(out_dir, exist_ok=True)

    images = sorted(f for f in os.listdir(plant_dir) if f.lower().endswith((".jpg", ".png")))[:12]

    print(f"[INFO] Writing segmentation previews for {len(images)} images")
    for name in images:
        path = os.path.join(plant_dir, name)
        try:
            seg = segment_plant(path)
        except ValueError as e:
            print(f"  [WARN] {name}: {e}")
            continue

        preview = np.hstack([
            seg["image"],
            overlay_mask(seg["image"], seg["veg_mask"], (255, 0, 0)),
            overlay_mask(seg["image"], seg["plant_mask"], (0, 255, 0)),
        ])
        cv2.imwrite(os.path.join(out_dir, f"seg_{name}"), preview)
        print(f"  {name}: coverage={seg['coverage']:.2f}  isolation={seg['isolation']:.2f}")

    print(f"[INFO] Previews saved to {out_dir}")
    print("       Left = original | Middle = all vegetation | Right = selected subject")
