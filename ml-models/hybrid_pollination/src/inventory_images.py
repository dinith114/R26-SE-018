"""
Hybrid Pollination - Tagged Image Inventory

Scans a folder of tagged plant photographs and reports what the collection can
actually support, so that scope is decided from the data rather than hoped for.

Expected layout - ONE FOLDER PER PHYSICAL PLANT, named exactly as the tag reads:

    tagged_plants/
        V. Gordon Dillon x Dr Anek Blitz/
            IMG_6034.jpg
            IMG_6035.jpg          <- more angles of the SAME plant
        V. Kulwadee Maron/
            IMG_6041.jpg
        UNKNOWN_1/                <- unreadable tag; do not guess

Folder names are the labels. There is no spreadsheet to fill in.

Usage:
    python src/inventory_images.py --dir path/to/tagged_plants
    python src/inventory_images.py --dir path/to/tagged_plants --write-csv
"""

import os
import sys
import argparse
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cross_notation import parse_cross


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIR = os.path.join(BASE_DIR, "data", "images", "tagged_plants")
OUT_CSV = os.path.join(BASE_DIR, "data", "tagged_plants.csv")

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".heic", ".webp"}
# OpenCV cannot read these, so they are counted but flagged as unusable
UNREADABLE_EXT = {".dng", ".heic", ".raw", ".cr2", ".nef", ".arw"}


def scan(root: str) -> list:
    """Walk the plant folders and collect one record per plant."""
    if not os.path.isdir(root):
        raise SystemExit(
            f"[ERROR] Folder not found: {root}\n"
            "        Create it and put one sub-folder per plant inside, "
            "named exactly as the tag reads."
        )

    plants = []
    for name in sorted(os.listdir(root)):
        folder = os.path.join(root, name)
        if not os.path.isdir(folder):
            continue

        images, unusable = [], []
        for f in sorted(os.listdir(folder)):
            ext = os.path.splitext(f)[1].lower()
            if ext in UNREADABLE_EXT:
                unusable.append(f)
            elif ext in IMAGE_EXT:
                images.append(f)

        if not images and not unusable:
            continue

        parsed = parse_cross(name)
        plants.append({
            "folder": name,
            "n_images": len(images),
            "n_unusable": len(unusable),
            "images": images,
            "parsed": parsed,
        })

    return plants


def report(plants: list) -> dict:
    """Print what the collection supports and return the summary."""
    if not plants:
        raise SystemExit("[ERROR] No plant folders with images were found.")

    n_plants = len(plants)
    n_images = sum(p["n_images"] for p in plants)
    n_unusable = sum(p["n_unusable"] for p in plants)

    named = [p for p in plants if not p["parsed"]["unreadable"]]
    # A half-readable tag such as "UNKNOWN_1 X Dr Anek" still contributes a
    # parent, so parentage is counted separately from readability
    with_parents = [p for p in plants if p["parsed"]["parents"]]

    # Distinct crosses = distinct normalised grex/cross strings
    distinct = {p["parsed"]["normalised"] for p in named}

    # Parents are counted by CANONICAL identity, not by spelling. "V. Dr Anek",
    # "Dr Anek" and "dr anek" are one plant; counting the strings makes a
    # collection look far thinner than it is.
    parent_counter = Counter()
    parent_spellings = {}
    for p in with_parents:
        parsed = p["parsed"]
        for name, key in zip(parsed["parents"], parsed["parent_keys"]):
            if not key:
                continue    # UNKNOWN half of a partly-readable tag
            parent_counter[key] += 1
            parent_spellings.setdefault(key, set()).add(name.strip())

    ploidy_counter = Counter(
        p["parsed"]["ploidy"] for p in plants if p["parsed"].get("ploidy")
    )

    print("\n" + "=" * 66)
    print("TAGGED IMAGE INVENTORY")
    print("=" * 66)
    print(f"\n  Plants (folders)      : {n_plants}")
    print(f"  Usable images         : {n_images}")
    if n_unusable:
        print(f"  UNUSABLE (RAW/HEIC)   : {n_unusable}  <- convert these to JPG")
    print(f"  Unreadable tags       : {n_plants - len(named)}")
    print(f"  Distinct crosses      : {len(distinct)}")
    print(f"  Crosses with parsable parentage: {len(with_parents)}")
    print(f"  Distinct parent names : {len(parent_counter)}")

    print(f"\n  Images per plant      : "
          f"min {min(p['n_images'] for p in plants)}, "
          f"max {max(p['n_images'] for p in plants)}, "
          f"mean {n_images / n_plants:.1f}")

    # ── What this supports ────────────────────
    print("\n" + "-" * 66)
    print("WHAT THIS COLLECTION SUPPORTS")
    print("-" * 66)

    def verdict(ok, label, detail):
        print(f"  [{'YES' if ok else 'NO ':3s}] {label}")
        print(f"        {detail}")

    verdict(len(distinct) >= 8,
            "Demo of pair compatibility",
            f"{len(distinct)} distinct crosses. Needs ~8+ to demo convincingly.")

    verdict(len(with_parents) >= 30,
            "Trainable trait inheritance (parents -> offspring)",
            f"{len(with_parents)} crosses with known parentage. "
            "Needs ~30+ to train; below that it is a worked example, not a model.")

    verdict(len(parent_counter) >= 15,
            "Parent-level trait vocabulary",
            f"{len(parent_counter)} distinct parent names.")

    repeated = sum(1 for c in parent_counter.values() if c >= 2)
    verdict(repeated >= 5,
            "Shared parents across crosses (needed to learn inheritance)",
            f"{repeated} parents appear in 2+ crosses. Without repeats, "
            "there is nothing to generalise from.")

    if parent_counter:
        print("\n  Most frequent parents (by canonical identity):")
        for key, n in parent_counter.most_common(12):
            spellings = sorted(parent_spellings[key])
            shown = spellings[0]
            extra = (f"   [also written: {', '.join(spellings[1:])}]"
                     if len(spellings) > 1 else "")
            print(f"    {n:2d}x  {shown}{extra}")

    if ploidy_counter:
        print("\n  Ploidy markers found on tags:")
        for pl, n in sorted(ploidy_counter.items()):
            meaning = {"2n": "diploid", "3n": "triploid - usually STERILE",
                       "4n": "tetraploid"}.get(pl, "")
            print(f"    {n:2d}x  {pl}  ({meaning})")

    # ── Problems to fix ───────────────────────
    problems = []
    if n_unusable:
        problems.append(f"{n_unusable} RAW/HEIC files cannot be read by OpenCV - convert to JPG")
    thin = [p["folder"] for p in plants if p["n_images"] < 2]
    if thin:
        problems.append(f"{len(thin)} plants have only 1 image (fine, but no angle variety)")
    unparsed = [p["folder"] for p in named if not p["parsed"]["parents"]]
    if unparsed:
        problems.append(
            f"{len(unparsed)} folder names have no parsable ' x ' parentage - "
            "these are grex names only, which is normal"
        )

    if problems:
        print("\n" + "-" * 66)
        print("NOTES")
        print("-" * 66)
        for p in problems:
            print(f"  - {p}")

    print("=" * 66)

    return {
        "n_plants": n_plants, "n_images": n_images, "n_unusable": n_unusable,
        "n_distinct_crosses": len(distinct), "n_with_parents": len(with_parents),
        "n_parents": len(parent_counter),
    }


def write_csv(plants: list, path: str):
    """Write one row per image, with parentage columns filled in."""
    import csv

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["plant_id", "tag_name", "image_name", "image_path",
                    "seed_parent", "pollen_parent", "genus", "is_cross"])

        for i, p in enumerate(plants, 1):
            parsed = p["parsed"]
            parents = parsed["parents"]
            seed = parents[0] if len(parents) >= 1 else ""
            pollen = parents[1] if len(parents) >= 2 else ""

            for img in p["images"]:
                w.writerow([
                    f"plant{i:03d}", p["folder"], img,
                    os.path.join(p["folder"], img),
                    seed, pollen, parsed["genus"], bool(parents),
                ])

    print(f"\n[SAVED] {path}")
    print("        One row per image. Parentage columns are filled from the "
          "folder name - correct any that parsed wrongly.")


def main():
    parser = argparse.ArgumentParser(description="Inventory tagged plant photographs")
    parser.add_argument("--dir", default=DEFAULT_DIR, help="Folder of per-plant folders")
    parser.add_argument("--write-csv", action="store_true",
                        help="Also write data/tagged_plants.csv")
    args = parser.parse_args()

    plants = scan(args.dir)
    report(plants)

    if args.write_csv:
        write_csv(plants, OUT_CSV)


if __name__ == "__main__":
    main()
