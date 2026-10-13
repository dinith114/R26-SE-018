"""
One-off/rerunnable data hygiene pass over data/raw/<class>/.

Run after adding new photos to a class folder (from ml-models/growth_stage/):

    python src/clean_dataset.py            # convert formats, quarantine dupes
    python src/clean_dataset.py --dry-run  # report only, touch nothing

Deliberately imports `config` directly (not via `from .config import` /
`src/__init__.py`) so it stays runnable without TensorFlow installed -
`src/__init__.py` eagerly imports model.py, which requires it.

Fixes two problems that silently cap training accuracy:

1. Keras' `ImageDataGenerator.flow_from_directory` only recognizes
   png/jpg/jpeg/bmp/ppm/tif/tiff (a hardcoded whitelist, independent of this
   project's own `ALLOWED_EXTENSIONS`). Photos saved as .jfif or .webp are
   silently skipped during training - they never reach the model at all. This
   script re-saves them as .jpg alongside the original (which is left in
   place, so nothing is lost).

2. Exact byte-identical images filed under two different class folders
   (e.g. the same photo saved as both budding/ and full_bloom/) teach the
   model contradictory labels for the same input. Exact duplicates within a
   single class waste training time and can leak across the train/validation
   split. Both are moved to data/_quarantine/ (never deleted) for review.
"""
import argparse
import hashlib
import shutil
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_DIR, STAGE_LABELS  # noqa: E402

UNSUPPORTED_BY_KERAS = {'.jfif', '.webp'}
QUARANTINE_DIR = DATA_DIR.parent / '_quarantine'


def convert_unsupported_formats(data_dir: Path, dry_run: bool = False) -> int:
    """Re-save .jfif/.webp photos as .jpg so flow_from_directory picks them up."""
    converted = 0
    for stage in STAGE_LABELS:
        stage_dir = data_dir / stage
        if not stage_dir.exists():
            continue
        for f in sorted(stage_dir.iterdir()):
            if f.suffix.lower() not in UNSUPPORTED_BY_KERAS:
                continue
            target = f.with_suffix('.jpg')
            if target.exists():
                continue
            print(f"  convert: {f.relative_to(data_dir)} -> {target.name}")
            if not dry_run:
                with Image.open(f) as im:
                    im.convert('RGB').save(target, 'JPEG', quality=95)
            converted += 1
    return converted


def _hash_file(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


# Cross-class conflicts where a human has visually confirmed which class is
# correct (checked 2026-08-26: both sides of the budding/full_bloom pairs
# below show fully-open flowers with no closed buds, i.e. full_bloom is
# right). (wrong_class, correct_class) - files are quarantined from
# wrong_class, kept in correct_class. Any cross-class conflict NOT listed
# here is left alone and printed as a warning instead of guessed at.
VERIFIED_LABEL_CONFLICTS = {
    frozenset({'budding', 'full_bloom'}): 'full_bloom',
}


def find_duplicates(data_dir: Path):
    """
    Return (cross_class_dupes, same_class_dupes): cross_class_dupes is a list
    of (wrong_class, Path) for files whose class lost to a
    VERIFIED_LABEL_CONFLICTS resolution; same_class_dupes is a list of
    (class, Path) for redundant exact copies within one class (keeping the
    alphabetically-first copy of each).
    """
    by_hash = {}
    for stage in STAGE_LABELS:
        stage_dir = data_dir / stage
        if not stage_dir.exists():
            continue
        for f in sorted(stage_dir.iterdir()):
            if not f.is_file():
                continue
            by_hash.setdefault(_hash_file(f), []).append((stage, f))

    cross_class, same_class = [], []
    for h, entries in by_hash.items():
        if len(entries) < 2:
            continue
        classes = {stage for stage, _ in entries}
        if len(classes) == 1:
            # Same-class exact duplicates: keep the first, quarantine the rest.
            stage = entries[0][0]
            same_class.extend((stage, f) for _, f in entries[1:])
            continue

        resolution = VERIFIED_LABEL_CONFLICTS.get(frozenset(classes))
        if resolution is None:
            names = ', '.join(f"{stage}/{f.name}" for stage, f in entries)
            print(f"  WARNING: unverified cross-class duplicate, leaving in place: {names}")
            continue
        cross_class.extend((stage, f) for stage, f in entries if stage != resolution)

    return cross_class, same_class


def quarantine_duplicates(data_dir: Path, dry_run: bool = False) -> int:
    """
    Move exact-duplicate images (cross-class conflicts resolved via
    VERIFIED_LABEL_CONFLICTS, plus redundant same-class copies) into
    data/_quarantine/<class>/ - never deleted, just taken out of the
    training tree.
    """
    cross_class, same_class = find_duplicates(data_dir)
    moved = 0
    for stage, f in cross_class + same_class:
        dest_dir = QUARANTINE_DIR / stage
        dest = dest_dir / f.name
        print(f"  quarantine: {f.relative_to(data_dir)} -> {dest.relative_to(data_dir.parent)}")
        if not dry_run:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dest))
        moved += 1
    return moved


def main():
    parser = argparse.ArgumentParser(description='Clean up growth_stage training data')
    parser.add_argument('--dry-run', action='store_true', help='Report only, change nothing')
    args = parser.parse_args()

    print("Converting .jfif/.webp photos to .jpg (Keras can't see them otherwise)...")
    n_converted = convert_unsupported_formats(DATA_DIR, args.dry_run)
    print(f"  {n_converted} file(s) converted\n")

    print("Scanning for exact-duplicate images across/within classes...")
    n_quarantined = quarantine_duplicates(DATA_DIR, args.dry_run)
    print(f"  {n_quarantined} file(s) quarantined\n")

    if args.dry_run:
        print("Dry run only - nothing was changed.")


if __name__ == '__main__':
    main()
