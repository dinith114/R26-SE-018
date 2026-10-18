"""
split_severity.py -- a severity-balanced split, used ONLY by the severity
experiments in run_experiments.py.

Why a second split
------------------
split_dataset.py ran before any photograph had a severity grade, so it could
balance by disease only. The grades turned out unevenly spread:

                    mild  moderate  severe
    train            22%       33%     45%
    validation       42%       37%     21%
    test             40%       28%     33%

and none of the 30 held-out Black Leaf Spot photographs is graded severe,
against 41 of the 122 used for training. A random split would do that about
once in 44,000 tries (hypergeometric, 2.3e-5). The likely cause is the
labelling order:
label_severity.py shows train photographs first, so every held-out photograph
was graded at the end of one session, straight after 219 Phyllosticta
photographs whose lesions are larger.

This split stratifies by disease AND grade, so train, validation and test get
the same mix, and photographs from every part of the labelling session.

What it does not touch
----------------------
The disease classifier keeps the original split, and so does every number in
the thesis. Only the severity experiments read data/split_severity/.

Leakage note
------------
Some photographs in THIS split's train part sit in the ORIGINAL test part. A
severity model trained here must never be scored on the original test set,
and the disease-then-severity cascade check must not use it. This split's own
validation and test parts are clean, and that is asserted below.

Usage
-----
    python split_severity.py
    python split_severity.py --dry-run
"""

import argparse
import csv
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

from split_dataset import split_counts

COMPONENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = COMPONENT_ROOT / "data" / "split"
DEFAULT_DST = COMPONENT_ROOT / "data" / "split_severity"
DEFAULT_LABELS = COMPONENT_ROOT / "data" / "severity_labels.csv"

GRADES = ("mild", "moderate", "severe")
SPLITS = ("train", "validation", "test")
HEALTHY = {"healthy"}


def load_grades(path):
    """{image_id: (class, grade)} for every diseased photograph with a grade."""
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            cls = (row.get("class") or "").strip()
            grade = (row.get("severity") or "").strip().lower()
            if cls and cls not in HEALTHY and grade in GRADES:
                out[(row.get("image_id") or "").strip()] = (cls, grade)
    return out


def find_originals(src, grades):
    """
    {image_id: (path, original_split)}. The originals are spread across the
    three folders of the original split; each must be found exactly once.
    """
    found = {}
    for split in SPLITS:
        for cls in sorted({c for c, _ in grades.values()}):
            folder = src / split / cls
            if folder.is_dir():
                for p in folder.glob("*.jpg"):
                    if p.stem in grades:
                        if p.stem in found:
                            sys.exit("ERROR: {} found in two original splits".format(p.stem))
                        found[p.stem] = (p, split)
    missing = sorted(set(grades) - set(found))
    if missing:
        sys.exit("ERROR: {} graded photograph(s) not found under {}, e.g. {}\n"
                 "Run split_dataset.py first.".format(len(missing), src, missing[:5]))
    return found


def mix_line(name, counter):
    total = sum(counter.values()) or 1
    return "  {:<12}{:>8.0f}%{:>9.0f}%{:>9.0f}%{:>8}".format(
        name, *[100 * counter[g] / total for g in GRADES], sum(counter.values()))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", default=str(DEFAULT_SRC),
                    help="the original split, whose three parts hold the originals")
    ap.add_argument("--dest", default=str(DEFAULT_DST))
    ap.add_argument("--labels", default=str(DEFAULT_LABELS))
    ap.add_argument("--ratios", nargs=3, type=float, default=[0.8, 0.1, 0.1],
                    metavar=("TRAIN", "VAL", "TEST"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src, dst = Path(args.source).resolve(), Path(args.dest).resolve()
    grades = load_grades(args.labels)
    if not grades:
        sys.exit("ERROR: no graded diseased photographs in {}".format(args.labels))
    originals = find_originals(src, grades)

    print("\nsource : {}".format(src))
    print("dest   : {}".format(dst))
    print("graded diseased photographs: {}".format(len(grades)))

    # One stratum per (disease, grade). Each is shuffled with its own seeded
    # RNG after sorting, exactly as split_dataset.py does per class, so the
    # result does not depend on how the filesystem lists files.
    strata = {}
    for image_id, (cls, grade) in grades.items():
        strata.setdefault((cls, grade), []).append(image_id)

    assigned = {}
    print("\n  {:<24}{:<10}{:>6}{:>7}{:>6}{:>6}".format(
        "disease", "grade", "total", "train", "val", "test"))
    for (cls, grade) in sorted(strata):
        ids = sorted(strata[(cls, grade)])
        random.Random(args.seed).shuffle(ids)
        n_train, n_val, n_test = split_counts(len(ids), args.ratios)
        for i, image_id in enumerate(ids):
            assigned[image_id] = ("train" if i < n_train else
                                  "validation" if i < n_train + n_val else "test")
        print("  {:<24}{:<10}{:>6}{:>7}{:>6}{:>6}".format(
            cls, grade, len(ids), n_train, n_val, n_test))

    assert set(assigned) == set(grades), "a graded photograph was not placed"

    print("\n  grade mix       mild  moderate   severe   total")
    print("  -- original split (disease-stratified) --")
    for s in SPLITS:
        print(mix_line(s, Counter(grades[k][1] for k, (_, o) in originals.items() if o == s)))
    print("  -- this split (disease x grade) --")
    for s in SPLITS:
        print(mix_line(s, Counter(grades[k][1] for k, a in assigned.items() if a == s)))

    moved = Counter((originals[k][1], assigned[k]) for k in grades)
    print("\n  where photographs moved (rows = original split, columns = this split)")
    print("  {:<12}{:>8}{:>12}{:>8}".format("", *SPLITS))
    for o in SPLITS:
        print("  {:<12}{:>8}{:>12}{:>8}".format(o, *[moved[(o, s)] for s in SPLITS]))
    print("  Photographs moved from the original test part into this train part")
    print("  are why a model trained here must never be scored on the original test set.")

    if args.dry_run:
        print("\n(dry run -- nothing copied)")
        return

    if dst.exists():
        shutil.rmtree(dst)
    rows = []
    for image_id in sorted(assigned):
        path, original_split = originals[image_id]
        cls, grade = grades[image_id]
        target = dst / assigned[image_id] / cls
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target / path.name)
        rows.append({"image_id": image_id, "filename": path.name, "class": cls,
                     "severity": grade, "split": assigned[image_id],
                     "original_split": original_split,
                     "dest_path": (target / path.name).as_posix()})

    manifest = dst / "split_manifest.csv"
    with open(manifest, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print("\nmanifest written: {}".format(manifest))

    # Verify what actually landed on disk, not just what was intended.
    on_disk = Counter()
    print("files on disk:")
    for s in SPLITS:
        for cls in sorted({c for c, _ in grades.values()}):
            files = list((dst / s / cls).glob("*.jpg"))
            on_disk.update(p.stem for p in files)
            print("  {:<12}{:<26}{:>5}".format(s, cls, len(files)))
    twice = [k for k, n in on_disk.items() if n > 1]
    assert not twice, "PHOTOGRAPH IN TWO PARTS: {}".format(twice[:5])
    assert len(on_disk) == len(grades), "expected {} files, found {}".format(
        len(grades), len(on_disk))
    print("integrity check: {} photographs, each in exactly one part  OK".format(len(on_disk)))


if __name__ == "__main__":
    main()
