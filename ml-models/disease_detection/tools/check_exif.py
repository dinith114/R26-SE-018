"""
check_exif.py -- read-only survey of data/raw/.

Answers three questions before any processing happens:

  1. How many photos carry an EXIF orientation tag other than 1?
     A tag other than 1 means the stored pixels are NOT upright; viewers
     rotate on the fly, but a CNN reads the stored pixels and would see a
     sideways leaf. Every such image must be physically rotated in step 2.

  2. What are the pixel dimensions, and how much would a 1024px cap save?

  3. Are there non-JPEG files, corrupt files, or duplicate byte-identical
     images hiding in the class folders?

This script NEVER writes to data/raw/. It only prints a report.

Usage:
    python check_exif.py                # surveys ../data/raw
    python check_exif.py --input PATH   # survey some other folder
"""

import argparse
import hashlib
import sys
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image, ExifTags, UnidentifiedImageError

# Pillow exposes EXIF tags as numbers; 274 is the Orientation tag.
ORIENTATION_TAG = next(k for k, v in ExifTags.TAGS.items() if v == "Orientation")

# Human-readable meaning of each orientation value, for the printed report.
ORIENTATION_MEANING = {
    1: "normal (already upright)",
    2: "mirrored horizontally",
    3: "rotated 180",
    4: "mirrored vertically",
    5: "mirrored + rotated 270 CW",
    6: "rotated 90 CW  <- very common on phones",
    7: "mirrored + rotated 90 CW",
    8: "rotated 270 CW <- very common on phones",
}

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def survey_folder(folder: Path, max_side: int):
    """Walk one class folder and collect statistics. Returns a dict."""
    stats = {
        "folder": folder.name,
        "orientations": Counter(),
        "suffixes": Counter(),
        "modes": Counter(),
        "widths": [],
        "heights": [],
        "needs_resize": 0,
        "unreadable": [],
        "hashes": defaultdict(list),
        "total": 0,
    }

    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        stats["total"] += 1
        stats["suffixes"][path.suffix.lower()] += 1

        # Byte-level hash catches exact duplicate files (the same photo
        # accidentally saved twice under two names).
        digest = hashlib.md5(path.read_bytes()).hexdigest()
        stats["hashes"][digest].append(path.name)

        try:
            with Image.open(path) as im:
                im.verify()                 # cheap corruption check
            with Image.open(path) as im:    # verify() leaves the file unusable
                stats["modes"][im.mode] += 1
                stats["widths"].append(im.width)
                stats["heights"].append(im.height)
                if max(im.width, im.height) > max_side:
                    stats["needs_resize"] += 1

                exif = im.getexif()
                orientation = exif.get(ORIENTATION_TAG) if exif else None
                stats["orientations"][orientation if orientation else "no EXIF"] += 1
        except (UnidentifiedImageError, OSError) as exc:
            stats["unreadable"].append(f"{path.name}: {exc}")

    return stats


def print_report(all_stats, max_side):
    grand_total = 0
    grand_rotated = 0
    grand_resize = 0
    grand_unreadable = 0

    for s in all_stats:
        print(f"\n{'=' * 62}")
        print(f"  {s['folder']}   ({s['total']} files)")
        print("=" * 62)

        # --- orientation ---
        print("  EXIF orientation:")
        rotated_here = 0
        for value, count in sorted(s["orientations"].items(), key=lambda kv: str(kv[0])):
            if value in (1, "no EXIF", None):
                meaning = ORIENTATION_MEANING.get(1, "") if value == 1 else "tag absent"
                flag = " "
            else:
                meaning = ORIENTATION_MEANING.get(value, "unknown value")
                flag = "!"
                rotated_here += count
            print(f"   {flag}  {str(value):>8} : {count:>4}   {meaning}")
        if rotated_here:
            print(f"      -> {rotated_here} image(s) are NOT upright in their pixels.")

        # --- size ---
        if s["widths"]:
            print("  Pixel size:")
            print(f"      width  min/max : {min(s['widths'])} / {max(s['widths'])}")
            print(f"      height min/max : {min(s['heights'])} / {max(s['heights'])}")
            print(f"      larger than {max_side}px on the long side : {s['needs_resize']}")

        # --- format / colour mode ---
        print(f"  File types : {dict(s['suffixes'])}")
        print(f"  Colour modes: {dict(s['modes'])}   (want RGB; L=greyscale, P=palette)")

        # --- duplicates ---
        dupes = {h: names for h, names in s["hashes"].items() if len(names) > 1}
        if dupes:
            print(f"  ! DUPLICATE files (byte-identical): {len(dupes)} group(s)")
            for names in list(dupes.values())[:5]:
                print(f"      {names}")
        else:
            print("  Duplicates : none")

        # --- unreadable ---
        if s["unreadable"]:
            print(f"  ! UNREADABLE / CORRUPT: {len(s['unreadable'])}")
            for line in s["unreadable"][:5]:
                print(f"      {line}")

        grand_total += s["total"]
        grand_rotated += rotated_here
        grand_resize += s["needs_resize"]
        grand_unreadable += len(s["unreadable"])

    print(f"\n{'=' * 62}")
    print("  SUMMARY")
    print("=" * 62)
    print(f"  images scanned               : {grand_total}")
    print(f"  not upright in pixels (EXIF) : {grand_rotated}")
    print(f"  larger than {max_side}px          : {grand_resize}")
    print(f"  unreadable / corrupt         : {grand_unreadable}")
    print()
    if grand_rotated or grand_resize:
        print("  VERDICT: run the 'rename' step. It fixes rotation and size.")
    else:
        print("  VERDICT: pixels already upright and within size cap,")
        print("           but still run 'rename' to normalise format and names.")
    print()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default=None,
                    help="folder containing class subfolders (default: ../data/raw)")
    ap.add_argument("--max-side", type=int, default=1024,
                    help="long-side cap used by the rename step (default 1024)")
    args = ap.parse_args()

    root = Path(args.input) if args.input else Path(__file__).resolve().parent.parent / "data" / "raw"
    root = root.resolve()

    if not root.is_dir():
        sys.exit(f"ERROR: not a folder: {root}")

    class_dirs = sorted(d for d in root.iterdir() if d.is_dir())
    if not class_dirs:
        sys.exit(f"ERROR: no class subfolders inside {root}")

    print(f"\nSurveying: {root}")
    print(f"Class folders found: {[d.name for d in class_dirs]}")

    all_stats = [survey_folder(d, args.max_side) for d in class_dirs]
    print_report(all_stats, args.max_side)


if __name__ == "__main__":
    main()
