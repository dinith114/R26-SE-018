"""
Hybrid Pollination - Flower Detection and Trait Measurement

Two jobs:

  1. IS THERE A FLOWER?  This is a gate, not a score. If a plant is not in
     bloom it cannot donate pollen or carry a pod, no matter how healthy it is.
     The correct answer is then "not in bloom - cannot pollinate now", which is
     a different state from "unsuitable plant".

  2. WHAT DOES THE FLOWER LOOK LIKE?  Colour, pattern and shape, measured from
     the flower region only. These feed offspring-trait prediction.

Detection is deliberately conservative about two things that appear constantly
in this dataset and would otherwise be mistaken for blooms:

  - HANDS. Photographs of name tags are taken with the tag held up, so a hand
    is in frame. Note that skin colour alone is NOT a safe exclusion: pink and
    salmon petals share the same YCrCb chroma region as skin. Only large
    skin-coloured regions reaching in from the frame edge are removed.
  - WARM BACKGROUNDS. Orange walls, laterite gravel, terracotta and wooden
    benches are all saturated and non-green. Compactness and saturation
    thresholds filter most of these; the rest are why `confidence` exists.

Nothing here reports a flower it is not reasonably sure of, because a false
"in bloom" would let the app advise a cross that is physically impossible.
"""

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from segmentation import resize_long_side, vegetation_mask


WORK_LONG_SIDE = 512

# A flower must occupy at least this fraction of the frame to be called a bloom.
#
# Raised from 0.004 after a seedling in a pot - carrying no flower at all - was
# reported "flower present, 90% confidence". The frame contained a bright blue
# plastic tool and brown coconut husk, both vivid and both mistaken for petals.
#
# The sweep that set this value also settled a larger question. Measured on 150
# bloom close-ups, 86 whole-plant frames with a bloom the annotator recorded, and
# 150 whole-plant frames with none:
#
#     coverage   close-up recall   whole-plant recall   FALSE blooms
#       0.004          80%                 7%               16%
#       0.010          77%                 7%                9%
#       0.020          71%                 3%                3%
#       0.040          62%                 1%                0%   <- chosen
#       0.080          43%                 0%                0%
#
# Whole-plant recall never exceeds 7% at ANY threshold. Detecting a bloom in a
# whole-plant photograph does not work - the flower is too small and the
# background too colourful - so the only thing the lower thresholds bought was
# false alarms. This value gives up the 7% and takes the 0%.
#
# The consequence is deliberate and is stated to the grower: a whole-plant photo
# will almost always answer "no flower detected in this image", which is honest,
# and a close-up answers properly 62% of the time. A false "in bloom" would let
# the app advise a cross that is physically impossible; a false "no flower" only
# asks for another photograph.
MIN_FLOWER_FRACTION = 0.040
# Below this, presence is reported but flagged low confidence.
CONFIDENT_FLOWER_FRACTION = 0.080

# Set for PRECISION, not recall. A backlit bloom measured saturation ~33, so
# this threshold does miss washed-out flowers. Lowering it to catch them also
# admitted grey roof panels and yellowed leaf tissue as blooms - see the
# measured limitation in the module docstring. A false "in bloom" is the more
# damaging error, so the conservative setting is kept deliberately.
MIN_SATURATION = 70
MIN_BLOB_AREA = 400      # px at working resolution
BLOWN_OUT_VALUE = 238    # Above this a pale pixel is overexposed sky, not petal
BORDER_MARGIN = 3        # Blobs touching the frame edge are background
SATURATED_BLUE = 90      # Blue above this is a flower; below, it is sky

# A blob this saturated is too vivid to be sky, netting, a wall or a bench, so
# it is exempt from the "too large" and "touches the edge" rules that exist to
# reject those. Measured: overexposed sky ~44, greenhouse roof panel ~44, a
# purple Vanda filling the frame ~199. Set well above the background range
# rather than just below the flower, so a pale bloom never qualifies by
# accident - if it is not obviously vivid, the framing rules still apply.
VIVID_SATURATION = 120

# ...and it must also fill at least this much of the frame. A bloom
# photographed close up covers 20-45%; a tool handle or a chip of coconut husk
# beside the plant covers a few percent. Both are vivid, so saturation alone
# cannot separate them - see the comment in flower_mask.
CLOSEUP_FRACTION = 0.20


# ──────────────────────────────────────────────
# Exclusion masks
# ──────────────────────────────────────────────
def skin_mask(img: np.ndarray) -> np.ndarray:
    """
    Raw skin-coloured pixels, by standard YCrCb chroma thresholding.

    Not used directly for exclusion - see hand_mask for why.
    """
    ycrcb = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)
    mask = cv2.inRange(ycrcb, np.array([0, 133, 77]), np.array([255, 173, 127]))

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)


def hand_mask(img: np.ndarray) -> np.ndarray:
    """
    Detect the HAND holding a name tag, rather than skin colour in general.

    The distinction matters and was found the hard way: pink and salmon orchid
    petals sit in the same YCrCb chroma region as human skin, so excluding all
    skin-coloured pixels removed 80% of a real bloom.

    What separates a hand from a flower here is not colour but placement and
    size. A hand holding a tag up to the camera is large and reaches in from
    the edge of the frame; a bloom is smaller and framed within the picture.
    So only large skin-coloured regions that touch the border are excluded.
    """
    skin = skin_mask(img)
    H, W = img.shape[:2]
    frame_area = H * W

    n, labels, stats, _ = cv2.connectedComponentsWithStats((skin > 0).astype(np.uint8), 8)
    hands = np.zeros_like(skin)

    for lab in range(1, n):
        area = stats[lab, cv2.CC_STAT_AREA]
        if area / frame_area < 0.02:
            continue    # Too small to be a hand at arm's length

        x, y = stats[lab, cv2.CC_STAT_LEFT], stats[lab, cv2.CC_STAT_TOP]
        w, h = stats[lab, cv2.CC_STAT_WIDTH], stats[lab, cv2.CC_STAT_HEIGHT]

        touches_border = (x <= BORDER_MARGIN or y <= BORDER_MARGIN
                          or x + w >= W - BORDER_MARGIN
                          or y + h >= H - BORDER_MARGIN)
        if touches_border:
            hands[labels == lab] = 255

    if cv2.countNonZero(hands):
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        hands = cv2.dilate(hands, kernel, iterations=2)   # Cover fingertips

    return hands


def flower_mask(img: np.ndarray) -> np.ndarray:
    """
    Candidate flower pixels: vivid, not green, not skin.

    Orchid blooms in this collection are pink, magenta, purple, white, yellow
    or brown-tessellated. What they share is that they are NOT leaf-green, so
    the mask is built by subtraction rather than by listing hues.
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    S, V = hsv[:, :, 1], hsv[:, :, 2]

    H = hsv[:, :, 0]

    # The discriminator here is HUE, not saturation, and that was established by
    # measurement rather than assumption:
    #
    #     backlit pink bloom      hue ~14, saturation ~33
    #     sky seen between leaves hue ~109, saturation ~44
    #
    # The real flower is LESS saturated than the sky it has to be separated
    # from, so no saturation threshold can split them. Hue separates them
    # cleanly. This matters because whole-plant photographs here look up at a
    # greenhouse roof, and the bright gaps between leaves are compact and fully
    # enclosed by foliage, so neither the border rule nor a compactness test
    # rejects them. Left in, they were reported as white blooms on plants
    # carrying no flower at all.
    candidate = ((S >= MIN_SATURATION) & (V >= 60) & (V <= 250)).astype(np.uint8) * 255

    # Pale blue and cyan is sky or roof panel. Strongly saturated blue is kept,
    # because blue Vandas are real and this collection contains several
    # (Kultana Blue, Pachara Blue, Pak Chong Blue, Twotone Blue).
    sky = ((H >= 86) & (H <= 130) & (S < SATURATED_BLUE)).astype(np.uint8) * 255
    candidate = cv2.bitwise_and(candidate, cv2.bitwise_not(sky))

    # Remove foliage and the hand
    candidate = cv2.bitwise_and(candidate, cv2.bitwise_not(vegetation_mask(img)))
    candidate = cv2.bitwise_and(candidate, cv2.bitwise_not(hand_mask(img)))

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    candidate = cv2.morphologyEx(candidate, cv2.MORPH_OPEN, kernel, iterations=2)
    candidate = cv2.morphologyEx(candidate, cv2.MORPH_CLOSE, kernel, iterations=2)

    # Keep only compact blobs. Flowers are roundish; walls, benches and sky are
    # large sprawling regions or thin slivers.
    n, labels, stats, _ = cv2.connectedComponentsWithStats((candidate > 0).astype(np.uint8), 8)
    keep = np.zeros_like(candidate)
    H_img, W_img = img.shape[:2]
    frame_area = H_img * W_img

    saturation = hsv[:, :, 1]

    for lab in range(1, n):
        area = stats[lab, cv2.CC_STAT_AREA]
        if area < MIN_BLOB_AREA:
            continue
        x, y = stats[lab, cv2.CC_STAT_LEFT], stats[lab, cv2.CC_STAT_TOP]
        w, h = stats[lab, cv2.CC_STAT_WIDTH], stats[lab, cv2.CC_STAT_HEIGHT]
        if w == 0 or h == 0:
            continue

        # Reject slivers (wires, tag edges)
        if max(w, h) / min(w, h) > 4.0:
            continue
        if area / float(w * h) < 0.30:
            continue

        # Is this blob vivid enough to be a bloom rather than background?
        #
        # The two rules below - reject anything covering most of the frame, and
        # reject anything touching the edge - were written for whole-plant
        # photographs, where sky, netting and benches run off the edge and
        # sprawl across the picture. On a CLOSE-UP of a flower both rules fire
        # on the flower itself: a bloom photographed at arm's length covers
        # ~44% of the frame and touches every edge. A purple Vanda filling the
        # picture was being reported as "no flower detected".
        #
        # Saturation is what separates the two cases. The background this had to
        # be protected against is pale by construction - overexposed sky
        # measured saturation ~44, and the sky rule above already removes
        # anything below 90 in the blue band. A bloom that fills the frame is
        # vividly coloured: the purple Vanda measures ~199. So a blob is exempt
        # from the framing rules only when it is far too saturated to be sky.
        blob = labels == lab
        blob_saturation = float(saturation[blob].mean())

        # The exemption applies only to a blob that BOTH is vividly coloured
        # and fills a large part of the frame - that combination means the
        # photograph is a close-up OF the flower.
        #
        # Vividness alone is not enough, and testing found the counter-example:
        # a seedling photographed in its pot had a bright blue plastic tool at
        # the edge of the frame and brown coconut husk in the pot. Both are
        # vividly coloured, both touch the border, and with a saturation-only
        # exemption both were admitted - so a plant carrying no flower at all
        # was reported "flower present, 90% confidence". Requiring the blob to
        # dominate the frame separates a bloom photographed close up (the purple
        # Vanda measures 43% of the frame) from an object lying beside the plant.
        vivid = (blob_saturation >= VIVID_SATURATION
                 and area / frame_area >= CLOSEUP_FRACTION)

        if not vivid and area / frame_area > 0.40:
            continue

        # Reject blobs touching the frame edge. Sky, shade netting, walls and
        # benches all run off the edge of the picture; a bloom on a plant is
        # framed within it. This is what stops overexposed sky at the top of
        # a photograph being counted as a large white flower. A vividly
        # coloured region is exempt - see above.
        if not vivid and (x <= BORDER_MARGIN or y <= BORDER_MARGIN
                          or x + w >= W_img - BORDER_MARGIN
                          or y + h >= H_img - BORDER_MARGIN):
            continue

        keep[blob] = 255

    return keep


# ──────────────────────────────────────────────
# Trait measurement
# ──────────────────────────────────────────────
COLOUR_BINS = [
    # (name, hue_low, hue_high) in OpenCV hue space (0-179)
    ("red",     0,   8),
    ("orange",  9,   20),
    ("yellow",  21,  33),
    ("green",   34,  85),
    ("cyan",    86,  100),
    ("blue",    101, 125),
    ("violet",  126, 145),
    ("magenta", 146, 168),
    ("red",     169, 179),
]


def classify_colour(hsv_pixels: np.ndarray) -> str:
    """Name the dominant colour of a set of HSV pixels."""
    if len(hsv_pixels) == 0:
        return "unknown"

    H, S, V = hsv_pixels[:, 0], hsv_pixels[:, 1], hsv_pixels[:, 2]

    if np.median(S) < 45:
        return "white" if np.median(V) > 170 else "grey"

    counts = {}
    for name, lo, hi in COLOUR_BINS:
        counts[name] = counts.get(name, 0) + int(((H >= lo) & (H <= hi)).sum())

    if not counts:
        return "unknown"

    best = max(counts, key=counts.get)
    # Dark low-value tissue reads brown rather than red or orange
    if best in ("red", "orange") and np.median(V) < 130:
        return "brown"
    return best


def measure_pattern(img: np.ndarray, mask: np.ndarray) -> str:
    """
    Classify the flower's surface pattern.

    Vanda breeders describe blooms as plain, spotted or tessellated (a net-like
    grid, the classic V. coerulea / V. tessellata marking). Local intensity
    variation inside the bloom separates the three: plain petals are smooth,
    spotted ones have isolated dark blobs, tessellated ones have regular
    high-frequency structure across the whole surface.
    """
    if cv2.countNonZero(mask) < MIN_BLOB_AREA:
        return "unknown"

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    m = mask > 0

    # Local contrast within the bloom
    blur = cv2.GaussianBlur(gray, (9, 9), 0)
    detail = cv2.absdiff(gray, blur)
    detail_level = float(detail[m].mean())

    # How much of that detail is isolated blobs vs spread evenly
    _, spots = cv2.threshold(detail, max(12, detail_level * 2), 255, cv2.THRESH_BINARY)
    spots = cv2.bitwise_and(spots, mask)
    spot_fraction = cv2.countNonZero(spots) / max(cv2.countNonZero(mask), 1)

    if detail_level < 4.0:
        return "plain"
    if spot_fraction > 0.18:
        return "tessellated"
    if spot_fraction > 0.05:
        return "spotted"
    return "plain"


def analyse_flower(image_path: str = None, img: np.ndarray = None) -> dict:
    """
    Detect and measure the flower in one image.

    Returns:
        dict with:
            in_bloom       - bool, the gate
            confidence     - 0-1, how sure the detection is
            coverage       - flower area as a fraction of the frame
            dominant_colour, secondary_colour, pattern
            n_blooms       - separate bloom-sized blobs found
            note           - plain-language explanation
    """
    if img is None:
        img = cv2.imread(image_path)
        if img is None:
            raise ValueError(f"Could not load image: {image_path}")

    img = resize_long_side(img, WORK_LONG_SIDE)
    mask = flower_mask(img)

    frame_area = img.shape[0] * img.shape[1]
    area = int(cv2.countNonZero(mask))
    coverage = area / frame_area

    result = {
        "in_bloom": False, "confidence": 0.0, "coverage": round(coverage, 4),
        "dominant_colour": "unknown", "secondary_colour": "unknown",
        "pattern": "unknown", "n_blooms": 0, "note": "",
    }

    if coverage < MIN_FLOWER_FRACTION:
        result["note"] = ("No flower detected. The plant is either not in bloom, or "
                          "the bloom is not visible in this frame.")
        return result

    n, _, stats, _ = cv2.connectedComponentsWithStats((mask > 0).astype(np.uint8), 8)
    result["n_blooms"] = int(sum(1 for i in range(1, n)
                                 if stats[i, cv2.CC_STAT_AREA] >= MIN_BLOB_AREA))

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    pixels = hsv[mask > 0]

    result["in_bloom"] = True
    result["dominant_colour"] = classify_colour(pixels)
    result["pattern"] = measure_pattern(img, mask)

    # Second colour: orchid lips and throats often differ from the petals
    dom = result["dominant_colour"]
    remaining = pixels
    if dom not in ("unknown", "white", "grey"):
        for name, lo, hi in COLOUR_BINS:
            if name == dom:
                remaining = remaining[(remaining[:, 0] < lo) | (remaining[:, 0] > hi)]
    if len(remaining) > len(pixels) * 0.15:
        result["secondary_colour"] = classify_colour(remaining)

    result["confidence"] = round(
        float(np.clip(coverage / CONFIDENT_FLOWER_FRACTION, 0.0, 1.0)) * 0.9, 3
    )
    if result["confidence"] < 0.5:
        result["note"] = ("A small flower-like region was found. Too small to be "
                          "certain - take a closer photograph of the bloom.")
    else:
        result["note"] = (f"Flower detected: {result['dominant_colour']}, "
                          f"{result['pattern']} pattern.")

    return result


def bloom_gate(image_path: str) -> dict:
    """
    The pollination gate for one plant.

    Returns a status the app can act on directly. "not_in_bloom" is explicitly
    NOT a failure of the plant - it is a timing problem, and the right response
    is to say when to come back, not to mark the plant unsuitable.
    """
    flower = analyse_flower(image_path)

    if flower["in_bloom"] and flower["confidence"] >= 0.5:
        status, message = "in_bloom", "Flower present. This plant can take part in a cross now."
    elif flower["in_bloom"]:
        status, message = ("uncertain",
                           "Possible flower detected but not clearly. Photograph the bloom "
                           "closer to confirm.")
    else:
        status, message = ("not_in_bloom",
                           "Not in bloom - cannot pollinate now. This is a timing issue, not "
                           "a fault with the plant. Check the growth-stage bloom prediction "
                           "for when it will be ready.")

    return {"status": status, "can_pollinate": status == "in_bloom",
            "message": message, "flower": flower}


# ──────────────────────────────────────────────
# Test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Detect and measure a flower")
    parser.add_argument("--image", required=True)
    parser.add_argument("--save-mask", action="store_true")
    args = parser.parse_args()

    gate = bloom_gate(args.image)
    f = gate["flower"]

    print(f"\n  Status    : {gate['status']}")
    print(f"  Message   : {gate['message']}")
    print(f"  Coverage  : {f['coverage']:.4f}   Confidence: {f['confidence']:.2f}")
    if f["in_bloom"]:
        print(f"  Colour    : {f['dominant_colour']}"
              + (f" / {f['secondary_colour']}" if f["secondary_colour"] != "unknown" else ""))
        print(f"  Pattern   : {f['pattern']}   Blooms: {f['n_blooms']}")

    if args.save_mask:
        img = resize_long_side(cv2.imread(args.image), WORK_LONG_SIDE)
        mask = flower_mask(img)
        overlay = img.copy()
        overlay[mask > 0] = (0, 0, 255)
        out = "flower_mask_preview.jpg"
        cv2.imwrite(out, np.hstack([img, cv2.addWeighted(overlay, 0.45, img, 0.55, 0)]))
        print(f"  Preview saved -> {out}")
