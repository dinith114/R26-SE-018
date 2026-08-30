"""
train.py -- train the Vanda orchid disease classifier.

Three flat classes: black_leaf_spot, healthy, phyllosticta_leaf_spot.

Architecture: MobileNetV2 transfer learning on ImageNet weights, trained in
two stages.

    STAGE 1  base frozen, only the new head trains, lr 1e-3.
             The head starts as random noise; letting large gradients from a
             random head flow into carefully pretrained convolutional filters
             destroys them. Freezing first lets the head become sensible.

    STAGE 2  top ~30 layers unfrozen, lr 1e-5 (100x smaller).
             The late layers learn orchid-specific texture -- lesion edges,
             chlorotic haloes -- while the early layers keep the generic edge
             and colour detectors that ImageNet already provides and 533
             photographs could never teach from scratch.

This file deliberately fixes every issue listed in PROJECT_CONTEXT.md
section 9:

  1. Normalisation conflict -- preprocess_input is a LAYER INSIDE the model.
     The saved .keras file therefore takes raw 0-255 RGB and does its own
     scaling. There is exactly one place scaling happens, so the backend can
     never double-scale. See src/preprocess.py.
  2. Class weights -- computed from the real folder counts and passed to fit().
  3. Class names -- saved to models/class_names.json at training time.
  4. NUM_CLASSES -- taken from len(class_names), never hardcoded.
  5. Evaluation -- see evaluate.py (test set is never touched here).
  6. Callbacks -- EarlyStopping and ModelCheckpoint on both stages.

Usage
-----
  python train.py                          # full run, both stages
  python train.py --smoke-test             # 1 epoch on a tiny subset
  python train.py --epochs 30 --fine-tune-epochs 15
  python train.py --data ../data/split_augmented --out ../models

On Colab, pass --data /content/split_augmented and --out /content/drive/...
so a dropped session costs one epoch rather than the whole run.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

COMPONENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = COMPONENT_ROOT / "data" / "split_augmented"
DEFAULT_OUT = COMPONENT_ROOT / "models"

IMG_SIZE = (224, 224)


def build_model(num_classes, dropout=0.3, fine_tune_layers=30):
    """
    MobileNetV2 + a small classification head.

    The input pipeline is part of the model:

        raw 0-255 RGB  ->  preprocess_input  ->  MobileNetV2  ->  head

    Putting preprocess_input inside means the exported .keras file is
    self-contained: anything that can resize an image to 224x224 can call it
    correctly, and there is no second place where scaling could disagree.
    """
    import tensorflow as tf
    from tensorflow.keras import layers, Model
    from tensorflow.keras.applications import MobileNetV2

    inputs = layers.Input(shape=IMG_SIZE + (3,), name="image_0_255")

    # Light geometric jitter, active only during training. The 54x on-disk
    # augmentation supplies rotation and colour; this adds small shifts so
    # the model does not rely on the subject being perfectly centred.
    x = layers.RandomFlip("horizontal", name="aug_flip")(inputs)
    x = layers.RandomTranslation(0.05, 0.05, name="aug_shift")(x)

    # This is exactly what mobilenet_v2.preprocess_input does (mode='tf'):
    #     x / 127.5 - 1   ->   maps 0-255 to [-1, 1]
    # Written as a Rescaling layer rather than Lambda(preprocess_input) because
    # a Lambda wrapping an imported function does not reliably round-trip
    # through a saved .keras file in Keras 3, and a model that will not reload
    # is worse than useless. Arithmetic is identical; verified in tests.
    x = layers.Rescaling(scale=1 / 127.5, offset=-1.0, name="mobilenet_scaling")(x)

    base = MobileNetV2(input_shape=IMG_SIZE + (3,),
                       include_top=False, weights="imagenet")
    base.trainable = False
    x = base(x, training=False)

    x = layers.GlobalAveragePooling2D(name="pool")(x)
    x = layers.Dropout(dropout, name="dropout")(x)
    outputs = layers.Dense(num_classes, activation="softmax", name="disease")(x)

    model = Model(inputs, outputs, name="vanda_disease_classifier")
    # Returned separately rather than attached as an attribute: assigning a
    # Layer to a Model attribute makes Keras 3 track it twice.
    return model, base


def compute_class_weights(counts, class_names):
    """
    Balanced class weights: n_samples / (n_classes * count_for_this_class).

    Without this the model can score well by leaning toward the majority
    class. Phyllosticta has 219 training originals against Black Leaf Spot's
    122 -- 1.8x -- so a model that under-predicts Black Leaf Spot still looks
    acceptable on overall accuracy while being useless for the grower whose
    plant actually has it.
    """
    total = sum(counts.values())
    n = len(class_names)
    return {i: total / (n * counts[name]) for i, name in enumerate(class_names)}


def count_images(folder):
    """{class_name: file_count} for one split folder."""
    out = {}
    for d in sorted(p for p in Path(folder).iterdir() if p.is_dir()):
        out[d.name] = sum(1 for p in d.rglob("*")
                          if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    return out


def make_datasets(data_root, batch_size, seed, smoke_test=False):
    import tensorflow as tf

    train_dir = Path(data_root) / "train"
    val_dir = Path(data_root) / "validation"
    for d in (train_dir, val_dir):
        if not d.is_dir():
            sys.exit("ERROR: missing folder {}\nRun the data pipeline first "
                     "(PROJECT_CONTEXT.md section 6).".format(d))

    common = dict(image_size=IMG_SIZE, batch_size=batch_size,
                  label_mode="categorical", seed=seed)

    train_ds = tf.keras.utils.image_dataset_from_directory(
        train_dir, shuffle=True, **common)
    val_ds = tf.keras.utils.image_dataset_from_directory(
        val_dir, shuffle=False, **common)

    class_names = list(train_ds.class_names)
    if class_names != list(val_ds.class_names):
        sys.exit("ERROR: train and validation class order differ:\n"
                 "  train {}\n  val   {}".format(class_names, val_ds.class_names))

    if smoke_test:
        train_ds = train_ds.take(3)
        val_ds = val_ds.take(2)

    autotune = tf.data.AUTOTUNE
    train_ds = train_ds.prefetch(autotune)
    val_ds = val_ds.prefetch(autotune)
    return train_ds, val_ds, class_names


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--epochs", type=int, default=25, help="stage 1 epochs")
    ap.add_argument("--fine-tune-epochs", type=int, default=12, help="stage 2")
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3, help="stage 1")
    ap.add_argument("--fine-tune-lr", type=float, default=1e-5, help="stage 2")
    ap.add_argument("--fine-tune-layers", type=int, default=30)
    ap.add_argument("--dropout", type=float, default=0.3)
    ap.add_argument("--patience", type=int, default=5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--no-fine-tune", action="store_true")
    ap.add_argument("--smoke-test", action="store_true",
                    help="1 epoch on a few batches, to prove the code runs")
    args = ap.parse_args()

    try:
        import tensorflow as tf
    except ImportError:
        sys.exit("ERROR: TensorFlow is not installed in this environment.\n"
                 "  pip install tensorflow-cpu      (local, slow)\n"
                 "  or run this script on Google Colab (recommended, see "
                 "PROJECT_CONTEXT.md section 8)")

    tf.keras.utils.set_random_seed(args.seed)

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 64)
    print("  VANDA ORCHID DISEASE CLASSIFIER -- TRAINING")
    print("  TensorFlow {}   GPU: {}".format(
        tf.__version__,
        [d.name for d in tf.config.list_physical_devices("GPU")] or "none (CPU)"))
    print("=" * 64)

    if args.smoke_test:
        args.epochs, args.fine_tune_epochs = 1, 1
        print("  SMOKE TEST -- 1 epoch on a few batches, metrics meaningless")

    train_ds, val_ds, class_names = make_datasets(
        args.data, args.batch_size, args.seed, args.smoke_test)
    num_classes = len(class_names)            # issue 4: never hardcoded

    # issue 3: save the class order NOW, before anything can go wrong.
    class_names_path = out_dir / "class_names.json"
    with open(class_names_path, "w", encoding="utf-8") as f:
        json.dump(class_names, f, indent=2)
    print("\n  classes ({}): {}".format(num_classes, class_names))
    print("  class order saved -> {}".format(class_names_path))
    print("  (the backend MUST read this file; index order is alphabetical")
    print("   by folder name and would shift if a class is ever added)")

    train_counts = count_images(Path(args.data) / "train")
    val_counts = count_images(Path(args.data) / "validation")
    print("\n  {:<26} {:>10} {:>8}".format("class", "train", "val"))
    for c in class_names:
        print("  {:<26} {:>10} {:>8}".format(c, train_counts[c], val_counts[c]))

    class_weight = compute_class_weights(train_counts, class_names)
    print("\n  class weights (issue 2 -- corrects the 1.8x imbalance):")
    for i, c in enumerate(class_names):
        print("    {:<26} {:.3f}".format(c, class_weight[i]))

    model, base = build_model(num_classes, args.dropout, args.fine_tune_layers)
    print("\n  model: {:,} total params, {:,} trainable (stage 1)".format(
        model.count_params(),
        sum(int(tf.size(w)) for w in model.trainable_weights)))

    model_path = out_dir / "disease_model.keras"
    callbacks = [
        tf.keras.callbacks.EarlyStopping(
            monitor="val_loss", patience=args.patience,
            restore_best_weights=True, verbose=1),
        tf.keras.callbacks.ModelCheckpoint(
            str(model_path), monitor="val_loss",
            save_best_only=True, verbose=1),
        tf.keras.callbacks.ReduceLROnPlateau(
            monitor="val_loss", factor=0.5,
            patience=max(2, args.patience // 2), verbose=1),
    ]

    # Accuracy only. tf.keras Precision/Recall threshold at 0.5 on a one-hot
    # target, which is not the per-class precision/recall the report needs --
    # evaluate.py computes those properly on the test set.
    metrics = ["accuracy"]

    # ---------------- stage 1 ----------------
    print("\n" + "-" * 64)
    print("  STAGE 1 -- frozen base, training the head only, lr {}".format(args.lr))
    print("-" * 64)
    model.compile(optimizer=tf.keras.optimizers.Adam(args.lr),
                  loss="categorical_crossentropy", metrics=metrics)
    hist1 = model.fit(train_ds, validation_data=val_ds, epochs=args.epochs,
                      class_weight=class_weight, callbacks=callbacks, verbose=1)

    history = {k: [float(x) for x in v] for k, v in hist1.history.items()}
    stage1_epochs = len(hist1.history["loss"])

    # ---------------- stage 2 ----------------
    if not args.no_fine_tune:
        print("\n" + "-" * 64)
        print("  STAGE 2 -- unfreezing top {} layers, lr {}".format(
            args.fine_tune_layers, args.fine_tune_lr))
        print("-" * 64)

        base.trainable = True
        for layer in base.layers[:-args.fine_tune_layers]:
            layer.trainable = False
        # BatchNorm layers keep their ImageNet running statistics. Updating
        # them on batches of 32 from 533 photographs makes training unstable.
        for layer in base.layers:
            if isinstance(layer, tf.keras.layers.BatchNormalization):
                layer.trainable = False

        print("  trainable params now: {:,}".format(
            sum(int(tf.size(w)) for w in model.trainable_weights)))

        model.compile(optimizer=tf.keras.optimizers.Adam(args.fine_tune_lr),
                      loss="categorical_crossentropy", metrics=metrics)
        hist2 = model.fit(train_ds, validation_data=val_ds,
                          epochs=args.fine_tune_epochs,
                          class_weight=class_weight, callbacks=callbacks, verbose=1)
        for k, v in hist2.history.items():
            history.setdefault(k, []).extend(float(x) for x in v)

    # ---------------- save ----------------
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
    weights_path = out_dir / "disease_model.weights.h5"
    model.save_weights(weights_path)          # fallback if .keras won't load

    meta = {
        "trained_at": datetime.now().isoformat(timespec="seconds"),
        "tensorflow_version": tf.__version__,
        "class_names": class_names,
        "num_classes": num_classes,
        "image_size": list(IMG_SIZE),
        "input_range": "0-255 raw RGB; preprocess_input is inside the model",
        "train_counts": train_counts,
        "validation_counts": val_counts,
        "class_weight": {class_names[i]: round(w, 4)
                         for i, w in class_weight.items()},
        "stage1_epochs_run": stage1_epochs,
        "total_epochs_run": len(history["loss"]),
        "args": vars(args),
        # NOTE ON THESE TWO NUMBERS -- do not quote them as results.
        # EarlyStopping restores the weights from the lowest-val_loss epoch, so
        # the SAVED model is that epoch's model. peak_val_accuracy below is the
        # highest accuracy seen at ANY epoch, which is usually a different
        # epoch and is therefore higher than the saved model actually scores.
        # The only reportable figures come from evaluate.py.
        "best_val_loss": min(history.get("val_loss", [float("nan")])),
        "peak_val_accuracy_any_epoch": max(history.get("val_accuracy", [float("nan")])),
        "reportable_metrics": "run evaluate.py -- do NOT quote peak_val_accuracy_any_epoch",
    }
    with open(out_dir / "training_metadata.json", "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
    with open(out_dir / "training_history.json", "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

    print("\n" + "=" * 64)
    print("  saved model    : {}".format(model_path))
    print("  saved weights  : {}".format(weights_path))
    print("  saved metadata : {}".format(out_dir / "training_metadata.json"))
    print("  best val_loss             : {:.4f}".format(meta["best_val_loss"]))
    print("  peak val_accuracy (any epoch): {:.4f}".format(
        meta["peak_val_accuracy_any_epoch"]))
    print("  ^ NOT the saved model's score. EarlyStopping keeps the")
    print("    lowest-val_loss epoch. Quote evaluate.py, nothing else.")
    print("\n  NEXT: python evaluate.py   -- test-set metrics + confusion matrix.")
    print("  The test set has not been touched by this script.")
    print("=" * 64)


if __name__ == "__main__":
    main()
