"""
compare_models.py -- train several architectures under identical conditions and
report which performs best.

Why this script exists
----------------------
"Why did you choose this model?" is asked at essentially every viva. There are
two acceptable answers and this project should give both:

  1. A PRINCIPLED answer -- the deployment target is a mobile phone used by a
     grower in a shade house, possibly offline, so model size and inference
     latency are real constraints, not afterthoughts. MobileNetV2 was designed
     for exactly that.

  2. An EMPIRICAL answer -- a table showing the alternatives were actually
     trained and measured on this dataset, not dismissed on reputation.

Answer 1 alone invites "but did you test that?". Answer 2 alone invites "you
picked the biggest number, but can it run on a phone?". Together they are hard
to argue with.

What is held constant
---------------------
Everything except the backbone: same split, same seed, same classification head,
same optimiser, same learning rate, same epochs, same class weights, same data.
Only then is the comparison meaningful. Each architecture gets its own official
`preprocess_input`, because they were pretrained with different input scaling
and using the wrong one would handicap a model for no reason -- that would be a
rigged comparison, which is worse than no comparison.

What is measured
----------------
  macro F1 on validation   the headline metric (all classes weighted equally)
  accuracy                 for reference only
  parameters               model complexity
  size on disk             matters for a mobile app download
  inference latency        milliseconds per single image, CPU

Usage
-----
  python compare_models.py --quick        # small subset, proves it runs
  python compare_models.py                # full run -- do this on Colab
  python compare_models.py --models mobilenetv2 efficientnetb0

IMPORTANT: this compares on the VALIDATION set. The test set stays untouched
until the final chosen model is evaluated once by evaluate.py. Choosing an
architecture by test-set score is tuning on the test set, and it would make the
final number optimistic.
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

COMPONENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = COMPONENT_ROOT / "data" / "split_augmented"
DEFAULT_OUT = COMPONENT_ROOT / "models"
IMG_SIZE = (224, 224)


def get_architectures():
    """
    name -> (builder, preprocess_input, note)

    Each entry uses its own official preprocess_input. MobileNetV2 and
    ResNet50V2 map 0-255 to [-1, 1]; EfficientNet expects raw 0-255 and does its
    scaling internally; the scratch CNN uses plain 0-1.
    """
    import tensorflow as tf
    from tensorflow.keras import layers, Model
    from tensorflow.keras.applications import (
        MobileNetV2, EfficientNetB0, ResNet50V2, DenseNet121)
    from tensorflow.keras.applications import mobilenet_v2, efficientnet, resnet_v2, densenet

    def transfer(ctor):
        def build(num_classes, dropout):
            base = ctor(input_shape=IMG_SIZE + (3,), include_top=False,
                        weights="imagenet")
            base.trainable = False
            inp = layers.Input(shape=IMG_SIZE + (3,))
            x = base(inp, training=False)
            x = layers.GlobalAveragePooling2D()(x)
            x = layers.Dropout(dropout)(x)
            out = layers.Dense(num_classes, activation="softmax")(x)
            return Model(inp, out)
        return build

    def scratch(num_classes, dropout):
        """
        A small CNN trained from scratch. Not a serious contender -- it is the
        control. It shows how much of the performance comes from ImageNet
        pretraining rather than from the architecture, which is the point of
        including it. Expect it to do clearly worse: 533 original photographs
        is nowhere near enough to learn useful filters from nothing.
        """
        inp = layers.Input(shape=IMG_SIZE + (3,))
        x = layers.Rescaling(1.0 / 255)(inp)
        for filters in (32, 64, 128):
            x = layers.Conv2D(filters, 3, padding="same", activation="relu")(x)
            x = layers.BatchNormalization()(x)
            x = layers.MaxPooling2D()(x)
        x = layers.GlobalAveragePooling2D()(x)
        x = layers.Dropout(dropout)(x)
        out = layers.Dense(num_classes, activation="softmax")(x)
        return Model(inp, out)

    return {
        "mobilenetv2": (transfer(MobileNetV2), mobilenet_v2.preprocess_input,
                        "Designed for mobile. Depthwise separable convolutions."),
        "efficientnetb0": (transfer(EfficientNetB0), efficientnet.preprocess_input,
                           "Compound scaling. Strong accuracy per parameter."),
        "resnet50v2": (transfer(ResNet50V2), resnet_v2.preprocess_input,
                       "Deep residual baseline. Much larger."),
        "densenet121": (transfer(DenseNet121), densenet.preprocess_input,
                        "Dense connectivity, good with limited data."),
        "scratch_cnn": (scratch, lambda x: x,
                        "Control: no pretraining. Shows what ImageNet buys."),
    }


def make_datasets(data_root, batch_size, seed, preprocess, max_batches=None):
    import tensorflow as tf

    train_dir, val_dir = Path(data_root) / "train", Path(data_root) / "validation"
    for d in (train_dir, val_dir):
        if not d.is_dir():
            sys.exit("ERROR: missing folder {}".format(d))

    common = dict(image_size=IMG_SIZE, batch_size=batch_size,
                  label_mode="categorical", seed=seed)
    train_ds = tf.keras.utils.image_dataset_from_directory(train_dir, shuffle=True, **common)
    val_ds = tf.keras.utils.image_dataset_from_directory(val_dir, shuffle=False, **common)
    class_names = list(train_ds.class_names)

    if max_batches:
        train_ds = train_ds.take(max_batches)

    at = tf.data.AUTOTUNE
    train_ds = train_ds.map(lambda x, y: (preprocess(x), y), num_parallel_calls=at).prefetch(at)
    val_ds = val_ds.map(lambda x, y: (preprocess(x), y), num_parallel_calls=at).prefetch(at)
    return train_ds, val_ds, class_names


def count_images(folder):
    out = {}
    for d in sorted(p for p in Path(folder).iterdir() if p.is_dir()):
        out[d.name] = sum(1 for p in d.rglob("*")
                          if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    return out


def measure_latency(model, repeats=25):
    """Milliseconds to classify ONE image on this CPU. Mobile-relevant."""
    import numpy as np
    dummy = np.zeros((1,) + IMG_SIZE + (3,), dtype="float32")
    model.predict(dummy, verbose=0)          # warm up, exclude graph tracing
    start = time.perf_counter()
    for _ in range(repeats):
        model.predict(dummy, verbose=0)
    return (time.perf_counter() - start) / repeats * 1000.0


def evaluate_macro_f1(model, val_ds, num_classes):
    import numpy as np
    from sklearn.metrics import f1_score
    y_true, y_pred = [], []
    for xb, yb in val_ds:
        probs = model.predict(xb, verbose=0)
        y_pred.extend(probs.argmax(axis=1))
        y_true.extend(yb.numpy().argmax(axis=1))
    return (float(f1_score(y_true, y_pred, average="macro", labels=list(range(num_classes)))),
            float(np.mean(np.array(y_true) == np.array(y_pred))))


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--models", nargs="+", default=None)
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--dropout", type=float, default=0.3)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--quick", action="store_true",
                    help="2 epochs on 25 batches -- proves the script runs")
    ap.add_argument("--max-train-batches", type=int, default=None)
    args = ap.parse_args()

    try:
        import tensorflow as tf
    except ImportError:
        sys.exit("ERROR: TensorFlow not installed. See requirements.txt.")

    if args.quick:
        args.epochs = 2
        args.max_train_batches = 25

    archs = get_architectures()
    chosen = args.models or list(archs)
    for m in chosen:
        if m not in archs:
            sys.exit("ERROR: unknown model '{}'. Available: {}".format(
                m, ", ".join(archs)))

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 74)
    print("  ARCHITECTURE COMPARISON -- scored on the VALIDATION set")
    print("  TensorFlow {} | epochs {} | batch {} | seed {}".format(
        tf.__version__, args.epochs, args.batch_size, args.seed))
    if args.quick:
        print("  QUICK MODE -- subset only. Numbers are NOT reportable.")
    print("=" * 74)
    print("\n  The test set is deliberately untouched here. Selecting an")
    print("  architecture by test score would be tuning on the test set.")

    train_counts = count_images(Path(args.data) / "train")
    total = sum(train_counts.values())
    n_classes = len(train_counts)
    class_weight = {i: total / (n_classes * c)
                    for i, c in enumerate(train_counts[k] for k in sorted(train_counts))}

    results = []
    for name in chosen:
        builder, preprocess, note = archs[name]
        print("\n" + "-" * 74)
        print("  {}".format(name.upper()))
        print("  {}".format(note))
        print("-" * 74)

        tf.keras.utils.set_random_seed(args.seed)      # identical start each time
        try:
            train_ds, val_ds, class_names = make_datasets(
                args.data, args.batch_size, args.seed, preprocess,
                args.max_train_batches)
            model = builder(len(class_names), args.dropout)
            model.compile(optimizer=tf.keras.optimizers.Adam(args.lr),
                          loss="categorical_crossentropy", metrics=["accuracy"])

            t0 = time.perf_counter()
            model.fit(train_ds, validation_data=val_ds, epochs=args.epochs,
                      class_weight=class_weight, verbose=2)
            train_seconds = time.perf_counter() - t0

            macro_f1, accuracy = evaluate_macro_f1(model, val_ds, len(class_names))

            tmp = out_dir / "_size_probe.keras"
            model.save(tmp)
            size_mb = tmp.stat().st_size / 1e6
            tmp.unlink()

            latency_ms = measure_latency(model)

            results.append({
                "model": name, "note": note,
                "macro_f1": macro_f1, "accuracy": accuracy,
                "parameters": int(model.count_params()),
                "size_mb": round(size_mb, 1),
                "latency_ms": round(latency_ms, 1),
                "train_seconds": round(train_seconds, 1),
            })
            print("\n  macro F1 {:.4f} | acc {:.4f} | {:,} params | {:.1f} MB | {:.0f} ms/image"
                  .format(macro_f1, accuracy, model.count_params(), size_mb, latency_ms))

        except Exception as exc:                       # noqa: BLE001
            print("  FAILED: {}".format(exc))
            results.append({"model": name, "note": note, "error": str(exc)})

        tf.keras.backend.clear_session()

    ok = [r for r in results if "error" not in r]
    ok.sort(key=lambda r: r["macro_f1"], reverse=True)

    print("\n" + "=" * 74)
    print("  RESULTS -- ranked by macro F1 on validation")
    print("=" * 74)
    print("\n  {:<16} {:>9} {:>9} {:>12} {:>9} {:>10}".format(
        "model", "macro F1", "accuracy", "params", "size MB", "ms/image"))
    print("  " + "-" * 70)
    for r in ok:
        print("  {:<16} {:>9.4f} {:>9.4f} {:>12,} {:>9.1f} {:>10.1f}".format(
            r["model"], r["macro_f1"], r["accuracy"], r["parameters"],
            r["size_mb"], r["latency_ms"]))
    for r in results:
        if "error" in r:
            print("  {:<16} FAILED: {}".format(r["model"], r["error"][:44]))

    if ok:
        best = ok[0]
        print("\n  Best macro F1 : {} ({:.4f})".format(best["model"], best["macro_f1"]))
        smallest = min(ok, key=lambda r: r["size_mb"])
        fastest = min(ok, key=lambda r: r["latency_ms"])
        print("  Smallest      : {} ({:.1f} MB)".format(smallest["model"], smallest["size_mb"]))
        print("  Fastest       : {} ({:.1f} ms/image)".format(fastest["model"], fastest["latency_ms"]))
        print("\n  How to read this for the report: if the best-scoring model is")
        print("  also large and slow, say so and justify the trade-off against")
        print("  the mobile deployment target rather than hiding it. A defended")
        print("  trade-off is a stronger answer than a single big number.")

    payload = {
        "compared_at": datetime.now().isoformat(timespec="seconds"),
        "tensorflow_version": tf.__version__,
        "quick_mode": bool(args.quick),
        "reportable": not args.quick,
        "scored_on": "validation",
        "settings": {"epochs": args.epochs, "batch_size": args.batch_size,
                     "lr": args.lr, "dropout": args.dropout, "seed": args.seed,
                     "max_train_batches": args.max_train_batches},
        "train_counts": train_counts,
        "results": results,
    }
    path = out_dir / "model_comparison.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print("\n  saved: {}".format(path))
    if args.quick:
        print("  QUICK MODE -- rerun without --quick (on Colab) for reportable numbers.")
    print("=" * 74)


if __name__ == "__main__":
    main()
