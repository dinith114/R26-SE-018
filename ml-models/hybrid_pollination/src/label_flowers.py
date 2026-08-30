"""
Hybrid Pollination - Automatic Flower Labelling for Cutout Images

Proposes flower / no-flower labels for background-removed orchid images, so
that a supervised flower detector can be trained without hand-labelling 800
pictures from scratch.

WHY THIS IS EASY HERE AND WAS IMPOSSIBLE ON THE NURSERY PHOTOS
---------------------------------------------------------------
Flower detection failed on the project's own whole-plant photographs because
the background defeated it: bright gaps of greenhouse roof between the leaves
are compact, enclosed by foliage, and LESS saturated than a backlit bloom
(measured: bloom hue ~14 / saturation ~33 against sky hue ~109 / saturation
~44). No colour threshold separates them.

These images have the background removed. What remains is plant on white. A
flower is then simply the part of the plant that is neither white background
nor green foliage - a rule that cannot fire on sky, gravel, netting or a hand,
because none of those are present.

The labels this produces are PROPOSALS. They are written with a confidence and
a margin so the uncertain ones can be reviewed first; the clear cases do not
need checking. Nothing here should be treated as ground truth until the
low-confidence rows have been looked at.

Usage:
    python src/label_flowers.py --dir "C:/Users/VICTUS/Pictures/orchid"
    python src/label_flowers.py --dir ... --review 40      # write a review sheet
"""

import os
import sys
import csv
import argparse

import cv2
import numpy as np


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_CSV = os.path.join(BASE_DIR, "data", "knowledge", "cutout_flower_labels.csv")
REVIEW_DIR = os.path.join(BASE_DIR, "results", "flower_label_review")

# Background is near-white in these cutouts
BG_VALUE = 225          # V above this with low saturation is background
BG_SATURATION = 35

# Foliage hue band in OpenCV space
LEAF_HUE_LO, LEAF_HUE_HI = 28, 95

# A flower must be this fraction of the PLANT (not the frame) to count
MIN_FLOWER_FRACTION = 0.020
CONFIDENT_FRACTION = 0.060
MIN_BLOB_AREA = 40      # px at native ~224x224


def analyse_cutout(image_path: str) -> dict:
    """
    Measure the flower fraction of one background-removed plant image.

    Returns:
        dict with plant_fraction, flower_fraction, label, confidence, colour
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not read {image_path}")

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]

    # Background: bright and unsaturated
    background = (V >= BG_VALUE) & (S <= BG_SATURATION)
    plant = (~background).astype(np.uint8) * 255

    # Clean up JPEG fringing around the cutout edge
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    plant = cv2.morphologyEx(plant, cv2.MORPH_OPEN, kernel, iterations=1)

    plant_px = int(cv2.countNonZero(plant))
    frame_px = img.shape[0] * img.shape[1]

    if plant_px < 200:
        return {"plant_fraction": 0.0, "flower_fraction": 0.0, "label": "unknown",
                "confidence": 0.0, "colour": "", "n_blobs": 0,
                "note": "no plant found"}

    # Foliage: green, within the plant
    foliage = ((H >= LEAF_HUE_LO) & (H <= LEAF_HUE_HI)).astype(np.uint8) * 255
    foliage = cv2.bitwise_and(foliage, plant)

    # Flower candidate: plant, not foliage, and actually coloured.
    # The saturation floor keeps brown stems and pale roots out.
    coloured = (S >= 45).astype(np.uint8) * 255
    flower = cv2.bitwise_and(cv2.bitwise_and(plant, cv2.bitwise_not(foliage)), coloured)
    flower = cv2.morphologyEx(flower, cv2.MORPH_OPEN, kernel, iterations=1)
    flower = cv2.morphologyEx(flower, cv2.MORPH_CLOSE, kernel, iterations=2)

    # Keep only blobs big enough to be a bloom, not stem speckle
    n, labels, stats, _ = cv2.connectedComponentsWithStats((flower > 0).astype(np.uint8), 8)
    keep = np.zeros_like(flower)
    n_blobs = 0
    for lab in range(1, n):
        if stats[lab, cv2.CC_STAT_AREA] >= MIN_BLOB_AREA:
            keep[labels == lab] = 255
            n_blobs += 1

    flower_px = int(cv2.countNonZero(keep))
    fraction = flower_px / plant_px

    if fraction >= MIN_FLOWER_FRACTION:
        label = "flower"
        confidence = float(np.clip(fraction / CONFIDENT_FRACTION, 0.0, 1.0))
    else:
        label = "no_flower"
        # Confident it is empty when there is almost nothing there
        confidence = float(np.clip(1.0 - fraction / MIN_FLOWER_FRACTION, 0.0, 1.0))

    colour = ""
    if label == "flower" and flower_px > 0:
        hues = H[keep > 0]
        vals = V[keep > 0]
        colour = _name_colour(float(np.median(hues)), float(np.median(vals)))

    return {
        "plant_fraction": round(plant_px / frame_px, 4),
        "flower_fraction": round(fraction, 4),
        "label": label,
        "confidence": round(confidence, 3),
        "colour": colour,
        "n_blobs": n_blobs,
        "note": "",
    }


def _name_colour(hue: float, value: float) -> str:
    """Rough colour name from median hue."""
    if value < 90:
        return "dark"
    for name, lo, hi in [("red", 0, 8), ("orange", 9, 20), ("yellow", 21, 33),
                         ("cyan", 96, 105), ("blue", 106, 125),
                         ("violet", 126, 145), ("magenta", 146, 168), ("red", 169, 179)]:
        if lo <= hue <= hi:
            return name
    return "other"


def write_review_sheet(rows: list, source_dir: str, n: int):
    """
    Build contact sheets of the least confident labels, for quick eyeballing.

    Reviewing the uncertain ones is enough - the confident cases are the ones
    a person would agree with instantly anyway.
    """
    os.makedirs(REVIEW_DIR, exist_ok=True)
    uncertain = sorted(rows, key=lambda r: r["confidence"])[:n]

    tiles, labels = [], []
    for r in uncertain:
        img = cv2.imread(os.path.join(source_dir, r["image"]))
        if img is None:
            continue
        tile = cv2.resize(img, (140, 140))
        colour = (0, 140, 0) if r["label"] == "flower" else (0, 0, 160)
        cv2.rectangle(tile, (0, 0), (139, 139), colour, 3)
        cv2.putText(tile, r["image"][:8], (4, 16), cv2.FONT_HERSHEY_SIMPLEX,
                    0.38, (0, 0, 0), 1, cv2.LINE_AA)
        cv2.putText(tile, f"{r['label'][:6]} {r['confidence']:.2f}", (4, 133),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.36, colour, 1, cv2.LINE_AA)
        tiles.append(tile)
        labels.append(r["image"])

    if not tiles:
        return

    per_row = 8
    rows_out = []
    for i in range(0, len(tiles), per_row):
        chunk = tiles[i:i + per_row]
        while len(chunk) < per_row:
            chunk.append(np.full((140, 140, 3), 255, np.uint8))
        rows_out.append(np.hstack(chunk))

    sheet = np.vstack(rows_out)
    path = os.path.join(REVIEW_DIR, "least_confident.jpg")
    cv2.imwrite(path, sheet)
    print(f"[SAVED] Review sheet -> {path}")
    print("        Green border = labelled flower, red = labelled no_flower.")
    print("        Check these; the high-confidence ones do not need review.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, help="Folder of cutout images")
    parser.add_argument("--review", type=int, default=40,
                        help="How many least-confident images to put on a review sheet")
    args = parser.parse_args()

    if not os.path.isdir(args.dir):
        raise SystemExit(f"[ERROR] Not a folder: {args.dir}")

    files = sorted(f for f in os.listdir(args.dir)
                   if os.path.splitext(f)[1].lower() in {".jpg", ".jpeg", ".png"})
    print(f"[STEP] Labelling {len(files)} cutout images...")

    rows = []
    for i, name in enumerate(files, 1):
        if i % 100 == 0:
            print(f"  {i}/{len(files)}")
        try:
            r = analyse_cutout(os.path.join(args.dir, name))
        except Exception as e:
            print(f"  [WARN] {name}: {e}")
            continue
        rows.append({"image": name, "source_dir": args.dir, **r})

    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        f.write("# AUTO-PROPOSED flower labels for background-removed orchid images.\n")
        f.write("# These are proposals, not verified ground truth. Review the\n")
        f.write("# low-confidence rows before training on them.\n")
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    n_flower = sum(1 for r in rows if r["label"] == "flower")
    n_none = sum(1 for r in rows if r["label"] == "no_flower")
    low = sum(1 for r in rows if r["confidence"] < 0.5)

    print("\n" + "=" * 62)
    print("AUTO-LABELLING RESULT")
    print("=" * 62)
    print(f"  flower     : {n_flower:4d}  ({n_flower / len(rows) * 100:.0f}%)")
    print(f"  no_flower  : {n_none:4d}  ({n_none / len(rows) * 100:.0f}%)")
    print(f"  low confidence (<0.5), review these: {low}")

    colours = {}
    for r in rows:
        if r["label"] == "flower" and r["colour"]:
            colours[r["colour"]] = colours.get(r["colour"], 0) + 1
    if colours:
        print("\n  flower colours proposed:")
        for c, n in sorted(colours.items(), key=lambda x: -x[1]):
            print(f"    {n:4d}  {c}")

    print("=" * 62)
    print(f"[SAVED] {OUT_CSV}")

    if args.review:
        write_review_sheet(rows, args.dir, args.review)


if __name__ == "__main__":
    main()
