"""
Hybrid Pollination - Flower Trait Measurement over the tagged collection

Runs flower detection across every tagged plant folder and builds a trait table
keyed by cross name. This is what makes offspring-trait prediction possible for
named hybrids rather than only for documented species.

It also answers a prior question honestly: HOW MANY of the tagged photographs
actually show a flower? Many were taken to record the name tag, with a hand
holding the label and no bloom in frame. Traits cannot be measured from those,
and pretending otherwise would put invented colours into the knowledge base.

Per plant the measurement is taken from the BEST-EVIDENCED frame - the one with
the largest confidently detected bloom - rather than averaged over every angle,
because most angles do not show the flower at all.

Usage:
    python src/measure_flower_traits.py
    python src/measure_flower_traits.py --per-plant 6
"""

import os
import sys
import csv
import argparse
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cross_notation import parse_cross
from flower_analysis import analyse_flower


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAGGED_DIR = os.path.join(BASE_DIR, "data", "images", "tagged_plants")
OUT_CSV = os.path.join(BASE_DIR, "data", "knowledge", "measured_flower_traits.csv")

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}

# Only frames at least this confident contribute a trait measurement
MIN_CONFIDENCE = 0.5


def measure_plant(folder: str, images: list, per_plant: int) -> dict:
    """
    Measure one plant from its best-evidenced frame.

    Returns the measurement plus how many frames were checked and how many
    showed a bloom, so the caller can report coverage honestly.
    """
    # Spread the sample across the folder rather than taking the first N,
    # since consecutive frames are near-duplicates of the same angle
    step = max(1, len(images) // per_plant)
    sample = images[::step][:per_plant]

    best, n_bloom = None, 0

    for name in sample:
        try:
            f = analyse_flower(os.path.join(folder, name))
        except Exception:
            continue

        if not f["in_bloom"]:
            continue
        n_bloom += 1

        if f["confidence"] >= MIN_CONFIDENCE:
            if best is None or f["coverage"] > best["coverage"]:
                best = {**f, "image_name": name}

    return {"best": best, "n_checked": len(sample), "n_with_bloom": n_bloom}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=TAGGED_DIR)
    parser.add_argument("--per-plant", type=int, default=6,
                        help="Frames to check per plant")
    args = parser.parse_args()

    if not os.path.isdir(args.dir):
        raise SystemExit(f"[ERROR] Folder not found: {args.dir}")

    folders = sorted(f for f in os.listdir(args.dir)
                     if os.path.isdir(os.path.join(args.dir, f)))

    rows = []
    n_plants = n_with_flower = n_measured = 0
    colours, patterns = Counter(), Counter()

    print(f"[STEP] Checking {len(folders)} plants for flowers "
          f"({args.per_plant} frames each)...")

    for i, folder_name in enumerate(folders, 1):
        folder = os.path.join(args.dir, folder_name)
        images = sorted(f for f in os.listdir(folder)
                        if os.path.splitext(f)[1].lower() in IMAGE_EXT)
        if not images:
            continue

        n_plants += 1
        if i % 10 == 0:
            print(f"  {i}/{len(folders)}")

        result = measure_plant(folder, images, args.per_plant)
        parsed = parse_cross(folder_name)
        best = result["best"]

        if result["n_with_bloom"]:
            n_with_flower += 1

        if best:
            n_measured += 1
            colours[best["dominant_colour"]] += 1
            patterns[best["pattern"]] += 1

        rows.append({
            "tag_name": folder_name,
            "seed_parent": parsed["parents"][0] if len(parsed["parents"]) >= 1 else "",
            "pollen_parent": parsed["parents"][1] if len(parsed["parents"]) >= 2 else "",
            "grex": parsed.get("grex", ""),
            "ploidy": parsed.get("ploidy", ""),
            "n_frames_checked": result["n_checked"],
            "n_frames_with_bloom": result["n_with_bloom"],
            "measured": bool(best),
            "source_image": best["image_name"] if best else "",
            "dominant_colour": best["dominant_colour"] if best else "",
            "secondary_colour": best["secondary_colour"] if best else "",
            "pattern": best["pattern"] if best else "",
            "n_blooms": best["n_blooms"] if best else 0,
            "coverage": round(best["coverage"], 4) if best else 0.0,
            "confidence": best["confidence"] if best else 0.0,
        })

    # ── Write ─────────────────────────────────
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        f.write("# Flower traits MEASURED from the project's own tagged photographs.\n")
        f.write("# measured=False means no bloom was found in the sampled frames -\n")
        f.write("# usually because the photograph was taken to record the name tag.\n")
        f.write("# Colours are measured under nursery daylight and are indicative,\n")
        f.write("# not colorimetric.\n")
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # ── Report ────────────────────────────────
    print("\n" + "=" * 66)
    print("FLOWER TRAIT MEASUREMENT")
    print("=" * 66)
    print(f"\n  Plants checked            : {n_plants}")
    print(f"  Plants with a bloom found : {n_with_flower}")
    print(f"  Plants measured (conf>={MIN_CONFIDENCE}) : {n_measured}")

    if n_plants:
        pct = n_measured / n_plants * 100
        print(f"  Coverage                  : {pct:.0f}% of plants")

    if colours:
        print("\n  Dominant colours measured:")
        for c, n in colours.most_common():
            print(f"    {n:3d}  {c}")
    if patterns:
        print("\n  Patterns measured:")
        for p, n in patterns.most_common():
            print(f"    {n:3d}  {p}")

    print("\n" + "-" * 66)
    print("WHAT THIS SUPPORTS")
    print("-" * 66)
    if n_measured >= 20:
        print("  [YES] Offspring trait prediction for named hybrids.")
        print(f"        {n_measured} measured parents is enough to blend traits.")
    else:
        print("  [NO ] Offspring trait prediction for named hybrids.")
        print(f"        Only {n_measured} plants gave a usable flower measurement.")
        print("        Most tagged photographs record the NAME TAG, not the bloom.")
        print("        Prediction stays limited to documented species until more")
        print("        flower close-ups are photographed.")

    print("=" * 66)
    print(f"[SAVED] {OUT_CSV}")


if __name__ == "__main__":
    main()
