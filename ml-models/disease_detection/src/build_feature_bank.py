"""
build_feature_bank.py -- prepare the data the input validator needs.

WHY THIS EXISTS
---------------
The disease classifier ends in a 3-way softmax, which always answers "which of
my three classes fits best?" and never "have I seen anything like this before?".
Given a photograph of food it picks the closest of three orchid classes and
reports high confidence, because softmax confidence measures fit between
classes, not familiarity with the input.

Measured on this project: a photograph of a meal was classified healthy at
99.9% confidence. Grass scored healthy at 99.3%, a tree phyllosticta at 99.6%.
A confidence threshold cannot catch these, because the confidence is high.

THE FIX
-------
Take the 1280-dimensional vector from the pooling layer immediately BEFORE the
classifier -- the model's description of what the image looks like, before it is
forced into one of three buckets. Real orchid photographs land close to other
orchid photographs in that space; food, hands, tables and screenshots land far
away. This script stores those training vectors so inference can measure the
distance.

Nothing is retrained. This is a filter in FRONT of the model, so every reported
metric (macro-F1 0.778, the confusion matrix, the threshold sweep) stays valid.

MEASURED SEPARATION, 31 August 2026
-----------------------------------
    this project'''s orchids  validation  median 0.296  max 0.414
                            test        median 0.300  max 0.454
    web orchid photographs  (11 images) min 0.312  max 0.546
    non-orchids             (17 images) min 0.468  max 0.724

The web photographs matter: they are genuine orchids with real lesions, and
their range OVERLAPS the non-orchid range. No threshold separates both groups
perfectly. See DEFAULT_THRESHOLD below for the trade-off that was chosen and
why. At 0.55: 145/145 orchid images accepted, 15/17 non-orchids rejected.

Usage:
    python build_feature_bank.py
    python build_feature_bank.py --calibrate ../../../ood_test
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

COMPONENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SPLIT = COMPONENT_ROOT / "data" / "split"
DEFAULT_MODELS = COMPONENT_ROOT / "models"

IMG_SIZE = (224, 224)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

# Distance to the mean of the K nearest training images. K > 1 so one unusual
# training photograph cannot single-handedly admit an unrelated image.
K_NEIGHBOURS = 5

# The operating threshold, set from a measured trade-off rather than a formula.
#
# Calibrating on this project's own validation set alone gave 0.42, which
# rejected 5 of 11 genuine orchid disease photographs taken from the web. Those
# are real orchids with real lesions; they sit far from the training set only
# because they were shot by other people, on other equipment, in other places.
# The validator could not tell "unfamiliar because not an orchid" from
# "unfamiliar because it is someone else's photograph of one".
#
# Measured distances (30 Aug 2026):
#
#     this project's orchids   0.16  ..  0.454
#     web orchid photographs   0.313 ..  0.547
#     non-orchids              0.469 ..  0.725
#                                     ^^^^^^^^ the ranges genuinely overlap
#
# Because they overlap, NO threshold both accepts every orchid and rejects
# every non-orchid. Two options were measured:
#
#     0.465  143/145 orchids accepted, 17/17 non-orchids rejected
#     0.550  145/145 orchids accepted, 15/17 non-orchids rejected
#
# 0.55 is used. Three reasons:
#
#   1. Refusing to examine a genuinely diseased plant is the more harmful error
#      for a grower than giving a nonsense answer about grass. Nobody
#      photographs grass and asks an orchid app about it.
#   2. The two images that leak at 0.55 are both green plants -- the hardest
#      boundary, and the one no threshold draws confidently.
#   3. 0.465's perfect score is fragile, not robust: it sits 0.004 below the
#      closest non-orchid image. That is luck, not a margin, and the next
#      unrelated photograph would very likely fall under it. Paying a certain
#      cost (rejected real orchids) for an uncertain benefit is a bad trade.
#
# Re-derive it by rerunning this script with --calibrate pointing at folders of
# known non-orchid images, and check the accept/reject counts it prints.
DEFAULT_THRESHOLD = 0.55


def load_image(path):
    import tensorflow as tf
    raw = tf.io.read_file(str(path))
    img = tf.io.decode_image(raw, channels=3, expand_animations=False)
    return tf.cast(tf.image.resize(img, IMG_SIZE, method="bilinear"), tf.float32)


def build_extractor(model_path):
    """The trained model, truncated at the pooling layer before the classifier."""
    import tensorflow as tf
    model = tf.keras.models.load_model(model_path, compile=False)
    try:
        pool = model.get_layer("pool")
    except ValueError:
        sys.exit("ERROR: no layer named 'pool' in {}.\nThe feature bank needs the "
                 "GlobalAveragePooling2D layer that train.py names 'pool'."
                 .format(model_path))
    return tf.keras.Model(model.input, pool.output)


def extract(extractor, paths, batch=16, label=""):
    """L2-normalised feature vectors, so distance is cosine distance."""
    import numpy as np
    import tensorflow as tf
    chunks = []
    for i in range(0, len(paths), batch):
        images = tf.stack([load_image(p) for p in paths[i:i + batch]])
        chunks.append(extractor.predict(images, verbose=0))
        if label and (i // batch) % 10 == 0:
            print("      {} {}/{}".format(label, min(i + batch, len(paths)), len(paths)))
    vectors = np.concatenate(chunks)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / (norms + 1e-9)


def knn_distance(features, bank, k=K_NEIGHBOURS):
    """
    1 - mean cosine similarity to the k most similar training images.

    Small means "looks like things I trained on". Large means "unfamiliar".
    """
    import numpy as np
    similarity = features @ bank.T
    k = min(k, bank.shape[0])
    nearest = np.sort(similarity, axis=1)[:, -k:]
    return 1.0 - nearest.mean(axis=1)


def list_images(folder):
    folder = Path(folder)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.rglob("*")
                  if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--split", default=str(DEFAULT_SPLIT))
    ap.add_argument("--models", default=str(DEFAULT_MODELS))
    ap.add_argument("--calibrate", default=None,
                    help="folder of NON-orchid images, to verify the threshold")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                    help="operating threshold; see DEFAULT_THRESHOLD above")
    ap.add_argument("--from-validation", action="store_true",
                    help="derive the threshold from validation instead of using "
                         "DEFAULT_THRESHOLD. Tighter, but rejects genuine orchid "
                         "photographs taken outside this dataset.")
    ap.add_argument("--margin", type=float, default=0.01,
                    help="with --from-validation: added to the highest distance")
    args = ap.parse_args()

    try:
        import numpy as np
        import tensorflow as tf                                   # noqa: F401
    except ImportError as exc:
        sys.exit("ERROR: missing dependency ({}).".format(exc))

    models_dir = Path(args.models).resolve()
    model_path = models_dir / "disease_model.keras"
    if not model_path.exists():
        sys.exit("ERROR: {} not found. Train the model first.".format(model_path))

    split = Path(args.split)
    train_paths = list_images(split / "train")
    val_paths = list_images(split / "validation")
    test_paths = list_images(split / "test")

    if not train_paths:
        sys.exit("ERROR: no training images under {}".format(split / "train"))

    print("\n" + "=" * 68)
    print("  INPUT VALIDATOR -- building the feature bank")
    print("=" * 68)
    print("  reference (train) : {}".format(len(train_paths)))
    print("  validation        : {}".format(len(val_paths)))
    print("  test              : {}".format(len(test_paths)))

    extractor = build_extractor(model_path)
    print("\n  extracting features ...")
    bank = extract(extractor, train_paths, label="train")
    print("      feature bank: {} x {}".format(*bank.shape))

    # ---- calibrate on VALIDATION, never test ----
    d_val = knn_distance(extract(extractor, val_paths), bank) if val_paths else None
    d_test = knn_distance(extract(extractor, test_paths), bank) if test_paths else None

    if d_val is None or len(d_val) == 0:
        sys.exit("ERROR: no validation images; the threshold cannot be calibrated.")

    if args.from_validation:
        threshold = float(d_val.max() + args.margin)
        source = "validation max {:.3f} + margin {:.3f}".format(
            float(d_val.max()), args.margin)
    else:
        threshold = float(args.threshold)
        source = ("chosen from the measured orchid/non-orchid trade-off; "
                  "see DEFAULT_THRESHOLD in this file")

    print("\n  real orchid photographs")
    print("    validation : median {:.3f}  95th {:.3f}  max {:.3f}".format(
        float(np.median(d_val)), float(np.percentile(d_val, 95)), float(d_val.max())))
    if d_test is not None and len(d_test):
        print("    test       : median {:.3f}  95th {:.3f}  max {:.3f}".format(
            float(np.median(d_test)), float(np.percentile(d_test, 95)), float(d_test.max())))

    print("\n  THRESHOLD {:.3f}".format(threshold))
    print("    {}".format(source))
    print("    rejects {}/{} validation".format(int((d_val > threshold).sum()), len(d_val)))
    if d_test is not None and len(d_test):
        n_bad = int((d_test > threshold).sum())
        print("    rejects {}/{} test  ({:.1f}% of real photos refused)".format(
            n_bad, len(d_test), 100.0 * n_bad / len(d_test)))

    # ---- optional: verify against real non-orchid images ----
    ood_report = None
    if args.calibrate:
        ood_paths = list_images(args.calibrate)
        if not ood_paths:
            print("\n  ! no images found in {}".format(args.calibrate))
        else:
            d_ood = knn_distance(extract(extractor, ood_paths), bank)
            caught = int((d_ood > threshold).sum())
            print("\n  NON-ORCHID IMAGES from {}".format(args.calibrate))
            for p, d in sorted(zip(ood_paths, d_ood), key=lambda x: x[1]):
                mark = "reject" if d > threshold else "ACCEPTED (missed)"
                print("    {:<32} {:.3f}  {}".format(p.name[:32], float(d), mark))
            print("    caught {}/{}".format(caught, len(ood_paths)))
            ood_report = {
                "folder": str(args.calibrate),
                "count": len(ood_paths),
                "caught": caught,
                "min_distance": float(d_ood.min()),
                "max_distance": float(d_ood.max()),
            }

    # ---- save ----
    out = models_dir / "feature_bank.npz"
    np.savez_compressed(out, bank=bank.astype("float32"),
                        threshold=np.float32(threshold), k=np.int32(K_NEIGHBOURS))

    meta = {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "model": str(model_path),
        "reference_images": len(train_paths),
        "feature_dim": int(bank.shape[1]),
        "k_neighbours": K_NEIGHBOURS,
        "threshold": threshold,
        "threshold_chosen_on": ("validation" if args.from_validation
                                else "measured orchid vs non-orchid trade-off"),
        "threshold_rationale": (
            "Set so no genuine orchid photograph is rejected, including images "
            "from outside this dataset. The ranges overlap, so no threshold "
            "separates both perfectly: at 0.55, 145/145 orchid images are "
            "accepted and 15/17 non-orchid images rejected (the two that pass "
            "are green plants). Refusing a genuinely diseased plant is the more "
            "harmful error for a grower."),
        "validation": {
            "n": len(d_val), "median": float(np.median(d_val)),
            "max": float(d_val.max()), "rejected": int((d_val > threshold).sum()),
        },
        "test": ({"n": len(d_test), "median": float(np.median(d_test)),
                  "max": float(d_test.max()),
                  "rejected": int((d_test > threshold).sum())}
                 if d_test is not None and len(d_test) else None),
        "ood_check": ood_report,
        "note": ("Distance filter in front of the classifier. No retraining, so "
                 "all reported disease metrics remain valid."),
    }
    with open(models_dir / "feature_bank_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print("\n" + "=" * 68)
    print("  saved: {}  ({:.1f} MB)".format(out, out.stat().st_size / 1e6))
    print("  saved: {}".format(models_dir / "feature_bank_metadata.json"))
    print("=" * 68)


if __name__ == "__main__":
    main()
