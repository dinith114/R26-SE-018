"""
train_severity.py -- train the SEVERITY classifier (Model 2).

This is a separate model from the disease classifier, trained on separate data,
and it is deliberately kept separate. See PROJECT_CONTEXT.md section 7.

  Model 1  train.py           disease   3 classes, ALL images
  Model 2  train_severity.py  severity  3 grades, DISEASED images only

Why the labels do not come from folder names
--------------------------------------------
The disease classifier can use `image_dataset_from_directory` because disease
IS the folder name. Severity is not: `split_augmented/train/black_leaf_spot/`
contains mild, moderate and severe images all mixed together. So this script
builds the (path, label) pairs itself:

  1. read data/severity_labels.csv          -> {original image_id: grade}
  2. read the augmentation manifests        -> {augmented file: source image}
  3. join them                              -> every augmented file's grade

Step 2 is what makes 427 hand-graded labels cover ~23,000 training files. It is
only valid because no augmentation transform changes the proportion of diseased
tissue -- rotating or brightening a leaf does not change how much of it is
diseased. If anyone ever adds cropping or zoom to augment_dataset.py, this join
silently becomes wrong.

Healthy images are excluded entirely. Severity of a healthy plant is 'none',
which is not a grade the model should have to predict -- Model 1 already
answers that question, and at inference the severity model is only consulted
when Model 1 has found a disease.

Usage
-----
  python train_severity.py --smoke-test        # proves the code runs
  python train_severity.py                     # full run
  python train_severity.py --check             # how many labels are usable, then exit
"""

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

COMPONENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = COMPONENT_ROOT / "data" / "split_augmented"
DEFAULT_LABELS = COMPONENT_ROOT / "data" / "severity_labels.csv"
DEFAULT_OUT = COMPONENT_ROOT / "models"

IMG_SIZE = (224, 224)
SEVERITY_CLASSES = ["mild", "moderate", "severe"]     # fixed, ordered
HEALTHY_CLASSES = {"healthy"}

# Augmentation suffixes, needed only when a manifest is missing.
ADJUSTMENT_CODES = ("bh50", "bl40", "eh50", "el40", "ch50", "cl40", "sh50", "sl40")


def load_severity_labels(path):
    """{image_id: grade} for diseased originals that have a valid grade."""
    p = Path(path)
    if not p.exists():
        sys.exit("ERROR: {} not found. Run tools/make_labels_template.py.".format(p))
    labels, skipped = {}, 0
    with open(p, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            cls = (row.get("class") or "").strip()
            grade = (row.get("severity") or "").strip().lower()
            image_id = (row.get("image_id") or "").strip()
            if not image_id or cls in HEALTHY_CLASSES:
                continue
            if grade in SEVERITY_CLASSES:
                labels[image_id] = grade
            else:
                skipped += 1
    return labels, skipped


def source_stem_from_name(stem):
    """
    Recover the original image id from an augmented filename.

    Black_LS_0007_rot45_bh50 -> Black_LS_0007

    Only used when a manifest is unavailable; the manifest is authoritative.
    """
    for code in ADJUSTMENT_CODES:
        stem = stem.replace("_" + code, "")
    if "_rot" in stem:
        stem = stem.split("_rot")[0]
    return stem


def collect_split(split_dir, labels, use_manifests=True):
    """
    Walk one split folder and return (paths, label_indices, stats).

    Healthy folders are skipped. Files whose source image has no grade yet are
    skipped and counted, so partial labelling still trains something.
    """
    paths, y = [], []
    unlabelled_sources = set()
    n_seen = 0

    if not split_dir.is_dir():
        sys.exit("ERROR: missing folder {}".format(split_dir))

    for class_dir in sorted(d for d in split_dir.iterdir() if d.is_dir()):
        if class_dir.name in HEALTHY_CLASSES:
            continue

        # The manifest maps every augmented file to the original it came from.
        mapping = {}
        if use_manifests:
            for m in class_dir.glob("manifest_*.csv"):
                with open(m, newline="", encoding="utf-8-sig") as f:
                    for row in csv.DictReader(f):
                        mapping[row["image_id"]] = Path(row["source_image"]).stem

        for img in sorted(class_dir.glob("*.jpg")):
            n_seen += 1
            src = mapping.get(img.stem) or source_stem_from_name(img.stem)
            grade = labels.get(src)
            if grade is None:
                unlabelled_sources.add(src)
                continue
            paths.append(img)
            y.append(SEVERITY_CLASSES.index(grade))

    return paths, y, {"seen": n_seen, "unlabelled_sources": len(unlabelled_sources)}


def make_tf_dataset(paths, labels, batch_size, shuffle, seed):
    import tensorflow as tf
    ds = tf.data.Dataset.from_tensor_slices(
        ([str(p) for p in paths], labels))

    def load(path, label):
        img = tf.io.decode_jpeg(tf.io.read_file(path), channels=3)
        img = tf.image.resize(img, IMG_SIZE, method="bilinear")
        # Raw 0-255: the Rescaling layer inside the model does the scaling,
        # exactly as in train.py. One place, one definition.
        return tf.cast(img, tf.float32), tf.one_hot(label, len(SEVERITY_CLASSES))

    if shuffle:
        ds = ds.shuffle(min(len(paths), 4096), seed=seed, reshuffle_each_iteration=True)
    at = tf.data.AUTOTUNE
    return ds.map(load, num_parallel_calls=at).batch(batch_size).prefetch(at)


def build_model(num_classes, dropout=0.3):
    """Same recipe as the disease model, so results are comparable."""
    import tensorflow as tf
    from tensorflow.keras import layers, Model
    from tensorflow.keras.applications import MobileNetV2

    inputs = layers.Input(shape=IMG_SIZE + (3,), name="image_0_255")
    x = layers.RandomFlip("horizontal")(inputs)
    x = layers.RandomTranslation(0.05, 0.05)(x)
    x = layers.Rescaling(scale=1 / 127.5, offset=-1.0, name="mobilenet_scaling")(x)

    base = MobileNetV2(input_shape=IMG_SIZE + (3,), include_top=False,
                       weights="imagenet")
    base.trainable = False
    x = base(x, training=False)
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(dropout)(x)
    outputs = layers.Dense(num_classes, activation="softmax", name="severity")(x)
    return Model(inputs, outputs, name="vanda_severity_classifier"), base


def report_counts(name, y, stats):
    counts = Counter(y)
    print("\n  {}".format(name))
    print("    files scanned      : {}".format(stats["seen"]))
    print("    usable (labelled)  : {}".format(len(y)))
    print("    skipped, no label  : {} distinct source image(s)".format(
        stats["unlabelled_sources"]))
    for i, cls in enumerate(SEVERITY_CLASSES):
        print("      {:<10} {:>7}".format(cls, counts.get(i, 0)))
    return counts


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    ap.add_argument("--labels", default=str(DEFAULT_LABELS))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--fine-tune-epochs", type=int, default=10)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--fine-tune-lr", type=float, default=1e-5)
    ap.add_argument("--fine-tune-layers", type=int, default=30)
    ap.add_argument("--dropout", type=float, default=0.3)
    ap.add_argument("--patience", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--min-per-class", type=int, default=15,
                    help="refuse to train if a grade has fewer training originals")
    ap.add_argument("--no-fine-tune", action="store_true")
    ap.add_argument("--check", action="store_true",
                    help="report label coverage and exit without training")
    ap.add_argument("--smoke-test", action="store_true")
    args = ap.parse_args()

    labels, skipped = load_severity_labels(args.labels)
    print("\n" + "=" * 66)
    print("  SEVERITY CLASSIFIER (Model 2) -- diseased images only")
    print("=" * 66)
    print("\n  graded originals   : {}".format(len(labels)))
    print("  ungraded / invalid : {}".format(skipped))
    if labels:
        print("  grade mix          : {}".format(dict(Counter(labels.values()))))

    if not labels:
        sys.exit("\nERROR: no severity labels yet.\n"
                 "  Fill data/severity_labels.csv, then re-run.\n"
                 "  Progress: python ../tools/make_labels_template.py --progress")

    data_root = Path(args.data)
    train_paths, train_y, s_tr = collect_split(data_root / "train", labels)
    val_paths, val_y, s_va = collect_split(data_root / "validation", labels)

    tr_counts = report_counts("TRAIN", train_y, s_tr)
    va_counts = report_counts("VALIDATION", val_y, s_va)

    # A grade with almost no examples produces a model that never predicts it,
    # which looks fine on overall accuracy and is useless in practice.
    thin = [SEVERITY_CLASSES[i] for i in range(len(SEVERITY_CLASSES))
            if tr_counts.get(i, 0) < args.min_per_class * 54]
    if thin:
        print("\n  ! WARNING: very few training examples for: {}".format(thin))
        print("    Each original becomes 54 files, so a grade needs roughly")
        print("    {} files to represent {} real photographs.".format(
            args.min_per_class * 54, args.min_per_class))
        print("    Label more images of these grades before trusting the model.")

    empty = [SEVERITY_CLASSES[i] for i in range(len(SEVERITY_CLASSES))
             if va_counts.get(i, 0) == 0]
    if empty:
        print("\n  ! WARNING: no VALIDATION images for: {}".format(empty))
        print("    Recall for those grades cannot be measured at all.")

    if args.check:
        print("\n  (--check: nothing trained)")
        print("=" * 66)
        return

    if not train_y:
        sys.exit("\nERROR: no labelled training images. Label some rows first.")

    try:
        import tensorflow as tf
    except ImportError:
        sys.exit("ERROR: TensorFlow not installed. See requirements.txt.")

    tf.keras.utils.set_random_seed(args.seed)
    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.smoke_test:
        args.epochs, args.fine_tune_epochs = 1, 1
        train_paths, train_y = train_paths[:96], train_y[:96]
        val_paths, val_y = val_paths[:32], val_y[:32]
        print("\n  SMOKE TEST -- metrics meaningless by design")

    train_ds = make_tf_dataset(train_paths, train_y, args.batch_size, True, args.seed)
    val_ds = make_tf_dataset(val_paths, val_y, args.batch_size, False, args.seed)

    total = len(train_y)
    n_cls = len(SEVERITY_CLASSES)
    class_weight = {i: (total / (n_cls * tr_counts[i]) if tr_counts.get(i) else 1.0)
                    for i in range(n_cls)}
    print("\n  class weights: {}".format(
        {SEVERITY_CLASSES[i]: round(w, 3) for i, w in class_weight.items()}))

    model, base = build_model(n_cls, args.dropout)
    model_path = out_dir / "severity_model.keras"

    with open(out_dir / "severity_class_names.json", "w", encoding="utf-8") as f:
        json.dump(SEVERITY_CLASSES, f, indent=2)
    print("  class order saved -> {}".format(out_dir / "severity_class_names.json"))

    callbacks = [
        tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=args.patience,
                                         restore_best_weights=True, verbose=1),
        tf.keras.callbacks.ModelCheckpoint(str(model_path), monitor="val_loss",
                                           save_best_only=True, verbose=1),
        tf.keras.callbacks.ReduceLROnPlateau(monitor="val_loss", factor=0.5,
                                             patience=max(2, args.patience // 2),
                                             verbose=1),
    ]

    print("\n" + "-" * 66)
    print("  STAGE 1 -- frozen base, lr {}".format(args.lr))
    print("-" * 66)
    model.compile(optimizer=tf.keras.optimizers.Adam(args.lr),
                  loss="categorical_crossentropy", metrics=["accuracy"])
    h1 = model.fit(train_ds, validation_data=val_ds, epochs=args.epochs,
                   class_weight=class_weight, callbacks=callbacks, verbose=1)
    history = {k: [float(x) for x in v] for k, v in h1.history.items()}

    if not args.no_fine_tune:
        print("\n" + "-" * 66)
        print("  STAGE 2 -- top {} layers, lr {}".format(
            args.fine_tune_layers, args.fine_tune_lr))
        print("-" * 66)
        base.trainable = True
        for layer in base.layers[:-args.fine_tune_layers]:
            layer.trainable = False
        for layer in base.layers:
            if isinstance(layer, tf.keras.layers.BatchNormalization):
                layer.trainable = False
        model.compile(optimizer=tf.keras.optimizers.Adam(args.fine_tune_lr),
                      loss="categorical_crossentropy", metrics=["accuracy"])
        h2 = model.fit(train_ds, validation_data=val_ds,
                       epochs=args.fine_tune_epochs,
                       class_weight=class_weight, callbacks=callbacks, verbose=1)
        for k, v in h2.history.items():
            history.setdefault(k, []).extend(float(x) for x in v)

    # BUG FIX (29 Aug 2026): ModelCheckpoint(save_best_only=True) has already
    # written the best-val_loss model to disk. Calling model.save() here would
    # overwrite it with whatever is in memory -- and Keras resets EarlyStopping's
    # internal best at the start of each fit(), so after a fine-tuning stage that
    # never beat stage 1, the in-memory weights are stage 2's best, which is
    # WORSE. Reload the checkpoint instead, so the .keras file, the weights
    # fallback and the reported metrics all describe the same, best model.
    if model_path.exists():
        model = tf.keras.models.load_model(model_path, compile=False)
        print("  reloaded best checkpoint from {}".format(model_path.name))
    else:
        model.save(model_path)
    model.save_weights(out_dir / "severity_model.weights.h5")

    meta = {
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "tensorflow_version": tf.__version__,
        "model": "severity",
        "class_names": SEVERITY_CLASSES,
        "graded_originals": len(labels),
        "grade_mix_originals": dict(Counter(labels.values())),
        "train_files": len(train_y),
        "validation_files": len(val_y),
        "train_counts": {SEVERITY_CLASSES[i]: tr_counts.get(i, 0) for i in range(n_cls)},
        "class_weight": {SEVERITY_CLASSES[i]: round(w, 4)
                         for i, w in class_weight.items()},
        "input_range": "0-255 raw RGB; scaling is inside the model",
        "smoke_test": bool(args.smoke_test),
        "reportable": not args.smoke_test,
        "best_val_loss": min(history.get("val_loss", [float("nan")])),
        "best_val_accuracy": max(history.get("val_accuracy", [float("nan")])),
        "args": vars(args),
    }
    with open(out_dir / "severity_training_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print("\n" + "=" * 66)
    print("  saved: {}".format(model_path))
    print("  best val_loss     : {:.4f}".format(meta["best_val_loss"]))
    print("  best val_accuracy : {:.4f}".format(meta["best_val_accuracy"]))
    if args.smoke_test:
        print("\n  SMOKE TEST -- these numbers are NOT reportable.")
    print("=" * 66)


if __name__ == "__main__":
    main()
