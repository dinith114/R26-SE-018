"""
evaluate_severity.py -- test-set evaluation of the SEVERITY classifier (Model 2).

Same job as evaluate.py, but for grades instead of diseases, and with two extra
measurements that matter specifically for an ordered scale.

ADJACENT-ERROR ACCURACY
    mild / moderate / severe is an ORDERED scale, so not all errors are equal.
    Calling a severe leaf 'moderate' is a small error; calling it 'mild' is a
    serious one, because the grower under-treats a plant that is badly infected.
    A plain confusion matrix hides that distinction, so this script reports
    "within one grade" accuracy alongside exact accuracy.

GRADE DISTRIBUTION PER SPLIT
    The splits were stratified by DISEASE, because severity was not yet known
    when the split was made. So the grade mix in validation and test does not
    match training, and that mismatch limits how well the model can score. The
    script prints all three distributions so the effect is visible rather than
    mysterious. Report this as a known limitation.

Usage
-----
    python evaluate_severity.py
    python evaluate_severity.py --split validation
"""

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

COMPONENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = COMPONENT_ROOT / "data" / "split_augmented"
DEFAULT_MODELS = COMPONENT_ROOT / "models"
DEFAULT_LABELS = COMPONENT_ROOT / "data" / "severity_labels.csv"

IMG_SIZE = (224, 224)
SEVERITY_CLASSES = ["mild", "moderate", "severe"]
HEALTHY = {"healthy"}


def load_labels(path):
    labels = {}
    with open(Path(path), newline="", encoding="utf-8-sig") as f:
        for row in __import__("csv").DictReader(f):
            if (row.get("class") or "").strip() in HEALTHY:
                continue
            g = (row.get("severity") or "").strip().lower()
            if g in SEVERITY_CLASSES:
                labels[(row.get("image_id") or "").strip()] = g
    return labels


def collect(split_dir, labels):
    """Held-out splits contain originals only, so the stem IS the image_id."""
    paths, y = [], []
    for class_dir in sorted(d for d in split_dir.iterdir() if d.is_dir()):
        if class_dir.name in HEALTHY:
            continue
        for p in sorted(class_dir.glob("*.jpg")):
            g = labels.get(p.stem)
            if g:
                paths.append(p)
                y.append(SEVERITY_CLASSES.index(g))
    return paths, y


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    ap.add_argument("--models", default=str(DEFAULT_MODELS))
    ap.add_argument("--labels", default=str(DEFAULT_LABELS))
    ap.add_argument("--split", default="test", choices=["test", "validation"])
    ap.add_argument("--batch-size", type=int, default=32)
    args = ap.parse_args()

    try:
        import numpy as np
        import tensorflow as tf
        from sklearn.metrics import (classification_report, confusion_matrix,
                                     f1_score, precision_recall_fscore_support)
    except ImportError as exc:
        sys.exit("ERROR: missing dependency ({}).".format(exc))

    models_dir = Path(args.models).resolve()
    model_path = models_dir / "severity_model.keras"
    if not model_path.exists():
        sys.exit("ERROR: {} not found.\nTrain it first, or download it from "
                 "Drive into models/.".format(model_path))

    labels = load_labels(args.labels)
    paths, y_true = collect(Path(args.data) / args.split, labels)
    if not paths:
        sys.exit("ERROR: no labelled {} images found.".format(args.split))

    lines = []

    def out(s=""):
        print(s)
        lines.append(s)

    out("=" * 70)
    out("  SEVERITY CLASSIFIER (Model 2) -- {} SET".format(args.split.upper()))
    out("  model : {}".format(model_path))
    out("  run at: {}".format(datetime.now().isoformat(timespec="seconds")))
    out("=" * 70)

    # --- distribution comparison, which explains a lot of the score ---
    out("\n  Grade distribution by split (stratified by DISEASE, not grade):")
    out("  {:<12} {:>8} {:>10} {:>10}".format("split", "mild", "moderate", "severe"))
    for sp in ("train", "validation", "test"):
        d = Path(args.data) / sp
        if not d.is_dir():
            continue
        _, yy = collect(d, labels) if sp != "train" else (None, None)
        if sp == "train":
            counts = Counter()
            for cd in sorted(x for x in d.iterdir() if x.is_dir()):
                if cd.name in HEALTHY:
                    continue
                import csv as _csv
                for m in cd.glob("manifest_*.csv"):
                    for row in _csv.DictReader(open(m, encoding="utf-8-sig")):
                        g = labels.get(Path(row["source_image"]).stem)
                        if g:
                            counts[g] += 1
            total = sum(counts.values()) or 1
            out("  {:<12} {:>7.0f}% {:>9.0f}% {:>9.0f}%".format(
                sp, *[100 * counts[c] / total for c in SEVERITY_CLASSES]))
        else:
            cc = Counter(yy)
            total = len(yy) or 1
            out("  {:<12} {:>7.0f}% {:>9.0f}% {:>9.0f}%".format(
                sp, *[100 * cc.get(i, 0) / total for i in range(3)]))
    out("\n  A mismatch here caps achievable accuracy and is a real limitation,")
    out("  not a bug. Severity was unknown when the split was made.")

    out("\n  {} images: {}".format(
        args.split, {SEVERITY_CLASSES[i]: Counter(y_true).get(i, 0) for i in range(3)}))

    model = tf.keras.models.load_model(model_path, compile=False)

    def load(p):
        img = tf.io.decode_jpeg(tf.io.read_file(str(p)), channels=3)
        return tf.cast(tf.image.resize(img, IMG_SIZE, method="bilinear"), tf.float32)

    probs = []
    for i in range(0, len(paths), args.batch_size):
        probs.append(model.predict(
            tf.stack([load(p) for p in paths[i:i + args.batch_size]]), verbose=0))
    probs = np.concatenate(probs, axis=0)
    y_pred = probs.argmax(axis=1)
    y_true = np.asarray(y_true)

    macro_f1 = f1_score(y_true, y_pred, average="macro",
                        labels=[0, 1, 2], zero_division=0)
    exact = float((y_pred == y_true).mean())
    within_one = float((np.abs(y_pred - y_true) <= 1).mean())

    out("\n" + "-" * 70)
    out("  HEADLINE")
    out("-" * 70)
    out("  macro F1               : {:.4f}".format(macro_f1))
    out("  exact-grade accuracy   : {:.4f}  ({}/{})".format(
        exact, int((y_pred == y_true).sum()), len(y_true)))
    out("  within-one-grade       : {:.4f}  <- ordered scale, so this matters".format(
        within_one))
    out("  random baseline        : 0.3333 (three grades)")
    out("\n  'Within one grade' counts moderate-called-severe as near-correct.")
    out("  The serious error is a SEVERE leaf called MILD -- the grower then")
    out("  under-treats a badly infected plant. That count is below.")

    out("\n" + "-" * 70)
    out("  PER-GRADE METRICS")
    out("-" * 70)
    out(classification_report(y_true, y_pred, labels=[0, 1, 2],
                              target_names=SEVERITY_CLASSES, digits=4,
                              zero_division=0))

    cm = confusion_matrix(y_true, y_pred, labels=[0, 1, 2])
    out("  Confusion matrix (rows = true, columns = predicted)")
    out("  {:<12}{:>10}{:>10}{:>10}{:>8}".format("", *SEVERITY_CLASSES, "total"))
    for i, name in enumerate(SEVERITY_CLASSES):
        out("  {:<12}{:>10}{:>10}{:>10}{:>8}".format(
            name, *[int(v) for v in cm[i]], int(cm[i].sum())))

    severe_as_mild = int(cm[2][0])
    mild_as_severe = int(cm[0][2])
    out("\n  Dangerous errors:")
    out("    SEVERE called MILD   : {} of {}   <- grower under-treats".format(
        severe_as_mild, int(cm[2].sum())))
    out("    MILD called SEVERE   : {} of {}   (over-treats, wasteful not harmful)"
        .format(mild_as_severe, int(cm[0].sum())))

    prec, rec, f1, sup = precision_recall_fscore_support(
        y_true, y_pred, labels=[0, 1, 2], zero_division=0)

    metrics = {
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
        "model": "severity", "split": args.split,
        "class_names": SEVERITY_CLASSES,
        "n_images": len(paths),
        "macro_f1": float(macro_f1),
        "exact_accuracy": exact,
        "within_one_grade_accuracy": within_one,
        "random_baseline": 1 / 3,
        "per_class": {c: {"precision": float(prec[i]), "recall": float(rec[i]),
                          "f1": float(f1[i]), "support": int(sup[i])}
                      for i, c in enumerate(SEVERITY_CLASSES)},
        "confusion_matrix": cm.tolist(),
        "severe_called_mild": severe_as_mild,
        "misclassified": [
            {"file": paths[i].name, "true": SEVERITY_CLASSES[y_true[i]],
             "predicted": SEVERITY_CLASSES[y_pred[i]],
             "confidence": float(probs[i].max())}
            for i in range(len(paths)) if y_pred[i] != y_true[i]],
    }
    mp = models_dir / "severity_metrics_{}.json".format(args.split)
    json.dump(metrics, open(mp, "w", encoding="utf-8"), indent=2)

    rp = models_dir / "severity_evaluation_{}.txt".format(args.split)
    rp.write_text("\n".join(lines) + "\n", encoding="utf-8")

    out("\n" + "=" * 70)
    out("  metrics : {}".format(mp))
    out("  report  : {}".format(rp))
    out("=" * 70)


if __name__ == "__main__":
    main()
