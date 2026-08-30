"""
update_manifest_severity.py -- backfill the severity column in augmentation
manifests, without regenerating a single image.

Why this exists
---------------
Hand-labelling 427 images takes hours. Augmentation takes hours too. Making
one wait for the other wastes a day that is not available.

So augmentation may be run first with severity left blank. The disease
classifier does not need severity at all -- it only needs the class folders.
Once severity_labels.csv has been filled in, this script rewrites the
'severity' column of every manifest_<class>.csv in place, matching each
augmented row back to its source image.

That match is safe for exactly the reason stated in PROJECT_CONTEXT.md
section 5: no augmentation transform changes the proportion of diseased
tissue, so a rotated or brightened copy of a 'moderate' leaf is still
'moderate'. This stops being true the moment anyone adds cropping or zoom to
augment_dataset.py.

Usage:
    python update_manifest_severity.py
    python update_manifest_severity.py --check      # report only, write nothing
"""

import argparse
import csv
import shutil
import sys
from pathlib import Path

VALID_SEVERITIES = {"mild", "moderate", "severe", "none"}

COMPONENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LABELS = COMPONENT_ROOT / "data" / "severity_labels.csv"
DEFAULT_ROOT = COMPONENT_ROOT / "data" / "split_augmented"


def load_labels(path):
    if not path.exists():
        sys.exit("ERROR: labels file not found: {}".format(path))
    mapping = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (row.get("image_id") or "").strip()
            sev = (row.get("severity") or "").strip()
            if key and sev:
                mapping[key] = sev
    return mapping


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", default=str(DEFAULT_LABELS))
    ap.add_argument("--root", default=str(DEFAULT_ROOT),
                    help="folder to search for manifest_*.csv")
    ap.add_argument("--check", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    labels = load_labels(Path(args.labels).resolve())
    print("\nseverity labels available: {}".format(len(labels)))

    bad = {k: v for k, v in labels.items() if v not in VALID_SEVERITIES}
    if bad:
        print("  ! unrecognised severity values found, these will be skipped:")
        for k, v in list(bad.items())[:10]:
            print("      {} -> '{}'".format(k, v))

    root = Path(args.root).resolve()
    manifests = sorted(root.rglob("manifest_*.csv"))
    if not manifests:
        sys.exit("ERROR: no manifest_*.csv found under {}".format(root))

    grand_filled = grand_missing = 0

    for manifest in manifests:
        with open(manifest, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames
            rows = list(reader)

        filled = 0
        missing = set()
        for row in rows:
            source_stem = Path(row["source_image"]).stem
            sev = labels.get(source_stem)
            if sev in VALID_SEVERITIES:
                if row.get("severity", "") != sev:
                    row["severity"] = sev
                    filled += 1
            elif not (row.get("severity") or "").strip():
                missing.add(source_stem)

        rel = manifest.relative_to(root)
        print("\n  {}".format(rel))
        print("      rows              : {}".format(len(rows)))
        print("      severity updated  : {}".format(filled))
        print("      sources unlabelled: {}".format(len(missing)))
        if missing:
            for s in sorted(missing)[:5]:
                print("          {}".format(s))
            if len(missing) > 5:
                print("          ... and {} more".format(len(missing) - 5))

        grand_filled += filled
        grand_missing += len(missing)

        if not args.check and filled:
            backup = manifest.with_suffix(".csv.bak")
            shutil.copy2(manifest, backup)
            with open(manifest, "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                w.writeheader()
                w.writerows(rows)

    print("\n{:-^58}".format(" SUMMARY "))
    print("  manifest rows updated       : {}".format(grand_filled))
    print("  source images still unlabelled: {}".format(grand_missing))
    if args.check:
        print("  (check mode -- nothing written)")
    elif grand_filled:
        print("  originals saved alongside as .csv.bak")
    print("-" * 58)


if __name__ == "__main__":
    main()
