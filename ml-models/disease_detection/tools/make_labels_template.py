"""
make_labels_template.py -- build data/severity_labels.csv for hand-labelling.

One row per ORIGINAL processed image. Augmented copies are not listed: they
inherit severity from their source through the augmentation manifests, which
is only valid because no augmentation transform changes the proportion of
diseased tissue (see PROJECT_CONTEXT.md section 5 -- do not add cropping or
zoom to augment_dataset.py).

Healthy images are pre-filled with severity 'none'. Diseased rows are left
blank for you to fill in.

GRADING PROTOCOL (state this in the report -- grading is by measured area,
not by impression, so that 427 labels stay consistent):

    mild        under 10%  of leaf area affected
    moderate    10% - 40%  of leaf area affected
    severe      over 40%   of leaf area affected

RE-RUNNING IS SAFE. If data/severity_labels.csv already exists, any severity
you have already typed is carried over; only genuinely new images are added
as blank rows. Nothing you have labelled is ever overwritten.

Usage:
    python make_labels_template.py
    python make_labels_template.py --todo        # list unlabelled rows only
    python make_labels_template.py --progress    # just print the counts
"""

import argparse
import csv
import shutil
import sys
from datetime import datetime
from pathlib import Path

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
VALID_SEVERITIES = {"mild", "moderate", "severe", "none"}
HEALTHY_CLASSES = {"healthy"}

COMPONENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROCESSED = COMPONENT_ROOT / "data" / "processed"
DEFAULT_SPLIT_MANIFEST = COMPONENT_ROOT / "data" / "split" / "split_manifest.csv"
DEFAULT_OUT = COMPONENT_ROOT / "data" / "severity_labels.csv"

FIELDS = ["image_id", "filename", "class", "split", "plant_part",
          "severity", "affected_area_percent", "notes"]


def list_images(folder):
    return sorted(p for p in folder.iterdir()
                  if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)


def load_existing(path):
    """Return {image_id: row} of whatever has already been labelled."""
    if not path.exists():
        return {}
    existing = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (row.get("image_id") or "").strip()
            if key:
                existing[key] = row
    return existing


def load_splits(manifest_path):
    """Return {image_id: split} so labelling can be prioritised by split."""
    if not manifest_path.exists():
        return {}
    mapping = {}
    with open(manifest_path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            mapping[row["image_id"]] = row["split"]
    return mapping


def report_progress(rows):
    total = len(rows)
    diseased = [r for r in rows if r["class"] not in HEALTHY_CLASSES]
    done = [r for r in diseased if r["severity"].strip() in VALID_SEVERITIES]
    todo = len(diseased) - len(done)

    print("\n{:-^58}".format(" LABELLING PROGRESS "))
    print("  rows in file            : {}".format(total))
    print("  healthy (auto 'none')   : {}".format(total - len(diseased)))
    print("  diseased needing labels : {}".format(len(diseased)))
    print("  already labelled        : {}".format(len(done)))
    print("  still to do             : {}".format(todo))

    if diseased:
        pct = 100.0 * len(done) / len(diseased)
        filled = int(pct / 2.5)
        print("  [{}{}] {:.0f}%".format("#" * filled, "." * (40 - filled), pct))

    # Per-split breakdown: train labels matter most, they feed the model.
    by_split = {}
    for r in diseased:
        s = r["split"] or "unassigned"
        d = by_split.setdefault(s, [0, 0])
        d[0] += 1
        if r["severity"].strip() in VALID_SEVERITIES:
            d[1] += 1
    if by_split:
        print("\n  by split (label 'train' first -- it is what trains the model):")
        for s in ("train", "validation", "test", "unassigned"):
            if s in by_split:
                tot, dn = by_split[s]
                print("    {:<12} {:>4} / {:<4} done".format(s, dn, tot))

    # Distribution so far, to catch a badly skewed grading habit early.
    counts = {}
    for r in done:
        counts[r["severity"].strip()] = counts.get(r["severity"].strip(), 0) + 1
    if counts:
        print("\n  grades used so far: {}".format(counts))
    print("-" * 58)


def validate(rows):
    """Warn about typos in the severity column. Not fatal."""
    bad = [r for r in rows
           if r["severity"].strip() and r["severity"].strip() not in VALID_SEVERITIES]
    if bad:
        print("\n  ! {} row(s) have an unrecognised severity value:".format(len(bad)))
        for r in bad[:10]:
            print("      {} -> '{}'".format(r["image_id"], r["severity"]))
        print("    allowed values: {}".format(sorted(VALID_SEVERITIES)))

    wrong_healthy = [r for r in rows
                     if r["class"] in HEALTHY_CLASSES
                     and r["severity"].strip() not in ("", "none")]
    if wrong_healthy:
        print("\n  ! {} healthy row(s) have a severity other than 'none'".format(
            len(wrong_healthy)))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--processed", default=str(DEFAULT_PROCESSED))
    ap.add_argument("--split-manifest", default=str(DEFAULT_SPLIT_MANIFEST))
    ap.add_argument("--output", default=str(DEFAULT_OUT))
    ap.add_argument("--plant-part", default="leaf")
    ap.add_argument("--progress", action="store_true",
                    help="print progress for the existing file and exit")
    ap.add_argument("--todo", action="store_true",
                    help="list the image_ids still needing a severity, then exit")
    args = ap.parse_args()

    processed = Path(args.processed).resolve()
    out_path = Path(args.output).resolve()

    if (args.progress or args.todo) and not out_path.exists():
        sys.exit("ERROR: {} does not exist yet -- run without flags first".format(out_path))

    existing = load_existing(out_path)
    splits = load_splits(Path(args.split_manifest).resolve())

    if args.progress or args.todo:
        rows = [dict((k, (r.get(k) or "")) for k in FIELDS) for r in existing.values()]
    else:
        if not processed.is_dir():
            sys.exit("ERROR: processed folder not found: {}".format(processed))
        class_dirs = sorted(d for d in processed.iterdir() if d.is_dir())
        if not class_dirs:
            sys.exit("ERROR: no class subfolders inside {}".format(processed))

        rows = []
        for class_dir in class_dirs:
            is_healthy = class_dir.name in HEALTHY_CLASSES
            for path in list_images(class_dir):
                image_id = path.stem
                prev = existing.get(image_id, {})
                rows.append({
                    "image_id": image_id,
                    "filename": path.name,
                    "class": class_dir.name,
                    "split": splits.get(image_id, prev.get("split", "")),
                    "plant_part": prev.get("plant_part") or args.plant_part,
                    # 'none' for healthy; otherwise keep whatever was typed before.
                    "severity": "none" if is_healthy else (prev.get("severity") or "").strip(),
                    "affected_area_percent": prev.get("affected_area_percent", "") or "",
                    "notes": prev.get("notes", "") or "",
                })

    if args.todo:
        todo = [r for r in rows
                if r["class"] not in HEALTHY_CLASSES
                and r["severity"].strip() not in VALID_SEVERITIES]
        print("\n{} image(s) still need a severity grade:\n".format(len(todo)))
        for r in sorted(todo, key=lambda r: (r["split"] != "train", r["image_id"])):
            print("  {:<12} {:<26} {}".format(r["split"] or "-", r["class"], r["filename"]))
        return

    if args.progress:
        report_progress(rows)
        return

    # Back up before overwriting, so a bad run can never cost hours of typing.
    if out_path.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = out_path.with_name("severity_labels.backup_{}.csv".format(stamp))
        shutil.copy2(out_path, backup)
        print("existing file backed up to: {}".format(backup.name))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    carried = sum(1 for r in rows
                  if r["class"] not in HEALTHY_CLASSES and r["severity"].strip())
    print("\nwritten: {}".format(out_path))
    print("  {} row(s) total".format(len(rows)))
    if existing:
        print("  {} previously typed label(s) carried over".format(carried))

    validate(rows)
    report_progress(rows)

    print("\nHow to fill this in:")
    print("  1. Open the CSV in Excel or LibreOffice.")
    print("  2. Sort by the 'split' column and do the 'train' rows first.")
    print("  3. For each row type mild / moderate / severe in the 'severity'")
    print("     column, judging by percentage of LEAF AREA affected:")
    print("        mild     under 10%")
    print("        moderate 10% - 40%")
    print("        severe   over 40%")
    print("  4. Optionally record your estimate in 'affected_area_percent'.")
    print("     Doing this makes the grading defensible at the viva.")
    print("  5. Save as CSV (not .xlsx) and re-run with --progress to check.")


if __name__ == "__main__":
    main()
