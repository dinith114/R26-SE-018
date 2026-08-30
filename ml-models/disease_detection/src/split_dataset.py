"""
split_dataset.py -- divide data/processed/ into train / validation / test.

    data/processed/<class>/        ->    data/split/train/<class>/
                                         data/split/validation/<class>/
                                         data/split/test/<class>/

Three properties this script guarantees, all of which have to be defensible
at the viva:

  STRATIFIED   Each class is split independently at the same ratio, so all
               three classes appear in all three splits in the same
               proportion. A plain random split of the pooled 667 images
               could easily leave, say, only 9 Black Leaf Spot images in the
               test set purely by chance.

  SEEDED       random.Random(42) means the same images land in the same split
               every time this is run. Results are reproducible, and a rerun
               after adding code changes nothing about the evaluation.

  CLEAN        Any previous data/split/ is deleted first, so a stale file from
               an earlier run cannot linger in a split it no longer belongs to
               and quietly leak into evaluation.

After copying, the script asserts that no filename appears in more than one
split, and writes split_manifest.csv recording where every original went.

This runs BEFORE augmentation. See PROJECT_CONTEXT.md section 6.

Usage:
    python split_dataset.py
    python split_dataset.py --ratios 0.8 0.1 0.1 --seed 42
    python split_dataset.py --dry-run          # report counts, copy nothing
"""

import argparse
import csv
import random
import shutil
import sys
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
SPLIT_NAMES = ("train", "validation", "test")

COMPONENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = COMPONENT_ROOT / "data" / "processed"
DEFAULT_DST = COMPONENT_ROOT / "data" / "split"


def list_images(folder):
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)


def split_counts(n, ratios):
    """
    Turn a count and three ratios into three whole numbers that sum to n.

    train is given the remainder rather than validation or test, because with
    small classes (Black Leaf Spot has 152) losing an image from a 15-image
    validation set matters far more than losing one from a 121-image train set.
    """
    n_val = int(round(n * ratios[1]))
    n_test = int(round(n * ratios[2]))
    # Never let a class end up with an empty validation or test set.
    n_val = max(1, n_val) if n >= 3 else n_val
    n_test = max(1, n_test) if n >= 3 else n_test
    n_train = n - n_val - n_test
    if n_train < 1:
        sys.exit("ERROR: class too small to split ({} images)".format(n))
    return n_train, n_val, n_test


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=str(DEFAULT_SRC))
    ap.add_argument("--dest", default=str(DEFAULT_DST))
    ap.add_argument("--ratios", nargs=3, type=float, default=[0.8, 0.1, 0.1],
                    metavar=("TRAIN", "VAL", "TEST"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src, dst = Path(args.source).resolve(), Path(args.dest).resolve()
    if not src.is_dir():
        sys.exit("ERROR: source folder not found: {}".format(src))
    if abs(sum(args.ratios) - 1.0) > 1e-6:
        sys.exit("ERROR: ratios must sum to 1.0, got {}".format(sum(args.ratios)))

    class_dirs = sorted(d for d in src.iterdir() if d.is_dir())
    if not class_dirs:
        sys.exit("ERROR: no class subfolders inside {}".format(src))

    print("\nsource : {}".format(src))
    print("dest   : {}".format(dst))
    print("ratios : train {:.0%} / validation {:.0%} / test {:.0%}   seed {}".format(
        args.ratios[0], args.ratios[1], args.ratios[2], args.seed))
    print("classes: {}".format([d.name for d in class_dirs]))

    # --- wipe any previous split so stale files cannot linger -------------
    if dst.exists() and not args.dry_run:
        print("\nremoving previous split at {}".format(dst))
        shutil.rmtree(dst)

    rows = []
    totals = {s: 0 for s in SPLIT_NAMES}
    print("\n{:<26} {:>6} {:>7} {:>6} {:>6}".format(
        "class", "total", "train", "val", "test"))
    print("-" * 55)

    for class_dir in class_dirs:
        images = list_images(class_dir)
        n = len(images)
        if n == 0:
            print("  skipping empty folder: {}".format(class_dir.name))
            continue

        # Shuffle a COPY with a per-run seeded RNG. Sorting first makes the
        # starting order independent of how the filesystem lists files.
        shuffled = list(images)
        random.Random(args.seed).shuffle(shuffled)

        n_train, n_val, n_test = split_counts(n, args.ratios)
        assigned = (
            [("train", p) for p in shuffled[:n_train]]
            + [("validation", p) for p in shuffled[n_train:n_train + n_val]]
            + [("test", p) for p in shuffled[n_train + n_val:]]
        )

        for split_name, path in assigned:
            target_dir = dst / split_name / class_dir.name
            if not args.dry_run:
                target_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target_dir / path.name)
            rows.append({
                "image_id": path.stem,
                "filename": path.name,
                "class": class_dir.name,
                "split": split_name,
                "source_path": path.as_posix(),
                "dest_path": (target_dir / path.name).as_posix(),
            })
            totals[split_name] += 1

        print("{:<26} {:>6} {:>7} {:>6} {:>6}".format(
            class_dir.name, n, n_train, n_val, n_test))

    print("-" * 55)
    print("{:<26} {:>6} {:>7} {:>6} {:>6}".format(
        "TOTAL", len(rows), totals["train"], totals["validation"], totals["test"]))

    # --- integrity check: no image may appear in two splits ---------------
    seen = {}
    duplicates = []
    for r in rows:
        key = (r["class"], r["filename"])
        if key in seen:
            duplicates.append((key, seen[key], r["split"]))
        seen[key] = r["split"]
    assert not duplicates, "IMAGE IN TWO SPLITS: {}".format(duplicates[:5])
    print("\nintegrity check: no image appears in more than one split  OK")

    if args.dry_run:
        print("\n(dry run -- nothing was copied)")
        return

    manifest = dst / "split_manifest.csv"
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("manifest written: {}".format(manifest))

    # Verify what actually landed on disk, not just what we intended.
    print("\nfiles actually on disk:")
    for split_name in SPLIT_NAMES:
        for class_dir in class_dirs:
            d = dst / split_name / class_dir.name
            count = len(list_images(d)) if d.is_dir() else 0
            print("  {:<12} {:<26} {:>5}".format(split_name, class_dir.name, count))


if __name__ == "__main__":
    main()
