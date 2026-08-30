"""
check_leakage.py -- prove that no original photograph contributed to both the
training set and the held-out validation / test sets.

Why this matters
----------------
Augmentation turns one photograph into 54 files. If augmentation had run
BEFORE the split, rotated copies of the same leaf would be scattered across
train and test: the model would train on Black_LS_0001_rot90 and be tested on
Black_LS_0001_rot180 -- the same leaf, same lesions, same lighting, merely
rotated. Accuracy would come out near 99% and would predict nothing about a
real grower's photo. That is data leakage, and it would invalidate the entire
results chapter.

This script provides the evidence that it did not happen. Run it after the
pipeline completes and paste the output into the report.

Three independent checks
------------------------
  1. MANIFEST CHECK   Every training file records the original it came from
                      in its manifest's source_image column. None of those
                      originals may appear in validation or test.
  2. FILENAME CHECK   Independently of the manifests, every training filename
                      must begin with the stem of an original that is not in
                      the holdout sets. This catches a stale file left behind
                      by an interrupted run, which a manifest would not list.
  3. SPLIT CHECK      No original may be listed under two splits in
                      split_manifest.csv.

Usage:
    python check_leakage.py
    python check_leakage.py --report ../data/leakage_report.txt
"""

import argparse
import csv
import sys
from pathlib import Path

COMPONENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AUG = COMPONENT_ROOT / "data" / "split_augmented"
DEFAULT_SPLIT_MANIFEST = COMPONENT_ROOT / "data" / "split" / "split_manifest.csv"

HOLDOUT_SPLITS = ("validation", "test")


def collect_train_sources(aug_root):
    """{source_image_stem} listed by every training manifest."""
    sources = set()
    manifests = sorted((aug_root / "train").rglob("manifest_*.csv"))
    for m in manifests:
        with open(m, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                sources.add(Path(row["source_image"]).stem)
    return sources, manifests


def collect_holdout_stems(aug_root):
    stems = set()
    for split in HOLDOUT_SPLITS:
        folder = aug_root / split
        if folder.is_dir():
            for p in folder.rglob("*.jpg"):
                stems.add(p.stem)
    return stems


def collect_train_files(aug_root):
    folder = aug_root / "train"
    return [p for p in folder.rglob("*.jpg")] if folder.is_dir() else []


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--augmented", default=str(DEFAULT_AUG))
    ap.add_argument("--split-manifest", default=str(DEFAULT_SPLIT_MANIFEST))
    ap.add_argument("--report", default=None, help="also write output to this file")
    args = ap.parse_args()

    aug_root = Path(args.augmented).resolve()
    if not aug_root.is_dir():
        sys.exit("ERROR: not found: {}".format(aug_root))

    lines = []

    def out(s=""):
        print(s)
        lines.append(s)

    out("=" * 64)
    out("  DATA LEAKAGE VERIFICATION")
    out("  dataset: {}".format(aug_root))
    out("=" * 64)

    train_sources, manifests = collect_train_sources(aug_root)
    holdout_stems = collect_holdout_stems(aug_root)
    train_files = collect_train_files(aug_root)

    out("\n  manifests read        : {}".format(len(manifests)))
    for m in manifests:
        out("      {}".format(m.relative_to(aug_root)))
    out("  training files on disk: {}".format(len(train_files)))
    out("  distinct originals behind them: {}".format(len(train_sources)))
    out("  held-out images (validation + test): {}".format(len(holdout_stems)))

    failures = 0

    # --- check 1: manifest sources vs holdout -----------------------------
    overlap = train_sources & holdout_stems
    out("\n  CHECK 1 -- training source images that also appear in holdout")
    out("      overlap = {}   (must be 0)".format(len(overlap)))
    if overlap:
        failures += 1
        for s in sorted(overlap)[:20]:
            out("        LEAKED: {}".format(s))
    else:
        out("      PASS")

    # --- check 2: filenames on disk vs holdout ----------------------------
    # An augmented file is named <source_stem>[_rotNN][_code].jpg, so any
    # holdout stem appearing as a filename prefix means a leaked file exists
    # on disk even if no manifest lists it.
    out("\n  CHECK 2 -- training FILENAMES derived from a held-out original")
    bad_files = []
    for p in train_files:
        stem = p.stem
        if stem in holdout_stems:
            bad_files.append(p)
        else:
            # strip augmentation suffixes back to the source stem
            base = stem.split("_rot")[0]
            for code in ("_bh50", "_bl40", "_eh50", "_el40",
                         "_ch50", "_cl40", "_sh50", "_sl40"):
                base = base.replace(code, "")
            if base in holdout_stems:
                bad_files.append(p)
    out("      leaked files = {}   (must be 0)".format(len(bad_files)))
    if bad_files:
        failures += 1
        for p in bad_files[:20]:
            out("        LEAKED: {}".format(p.relative_to(aug_root)))
    else:
        out("      PASS")

    # --- check 3: split manifest internal consistency ---------------------
    out("\n  CHECK 3 -- no original listed under two splits")
    sm = Path(args.split_manifest).resolve()
    if not sm.exists():
        out("      SKIPPED: {} not found".format(sm))
    else:
        seen = {}
        clashes = []
        counts = {}
        with open(sm, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                key = row["image_id"]
                counts[row["split"]] = counts.get(row["split"], 0) + 1
                if key in seen and seen[key] != row["split"]:
                    clashes.append((key, seen[key], row["split"]))
                seen[key] = row["split"]
        out("      originals in split_manifest.csv: {}".format(len(seen)))
        out("      per split: {}".format(counts))
        out("      clashes = {}   (must be 0)".format(len(clashes)))
        if clashes:
            failures += 1
            for c in clashes[:20]:
                out("        CLASH: {}".format(c))
        else:
            out("      PASS")

    out("\n" + "=" * 64)
    if failures == 0:
        out("  RESULT: PASS -- no leakage detected.")
        out("  Every held-out image is an original photograph that contributed")
        out("  nothing to training, so test metrics are honest.")
    else:
        out("  RESULT: FAIL -- {} check(s) failed. Do not train on this".format(failures))
        out("  dataset. Re-run split_dataset.py, then re-run augmentation.")
    out("=" * 64)

    if args.report:
        Path(args.report).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print("\nreport written: {}".format(Path(args.report).resolve()))

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
