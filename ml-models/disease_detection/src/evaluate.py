"""
evaluate.py -- test-set evaluation of the disease classifier.

Produces everything the results chapter needs:

  * per-class precision, recall and F1, plus macro and weighted averages
  * a confusion matrix, printed as text and saved as a figure
  * the confidence-threshold sweep used to set the "unidentified condition"
    cut-off, tuned on VALIDATION (never on test)
  * a list of every misclassified test image, so failures can be discussed
    rather than glossed over

Why per-class metrics and not overall accuracy
----------------------------------------------
The test set is 67 real photographs: 15 black_leaf_spot, 24 healthy,
28 phyllosticta_leaf_spot. A single misclassified Black Leaf Spot image moves
that class's recall by 6.7 percentage points, while barely moving overall
accuracy. Overall accuracy on an imbalanced 67-image set hides exactly the
failure a grower would care about, which is a diseased plant reported healthy.

Macro-F1 (the unweighted mean of the three per-class F1 scores) is the headline
number for this project, because it treats the 15-image class as equally
important as the 28-image one. It is also the metric the admin retraining flow
gates on (PROJECT_CONTEXT.md section 7).

Usage
-----
  python evaluate.py
  python evaluate.py --split validation      # sanity check without touching test
  python evaluate.py --model ../models/disease_model.keras
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

COMPONENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA = COMPONENT_ROOT / "data" / "split_augmented"
DEFAULT_MODELS = COMPONENT_ROOT / "models"
IMG_SIZE = (224, 224)
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def collect_files(split_dir, class_names):
    """Return (paths, true_label_indices) in a stable, sorted order."""
    paths, labels = [], []
    for idx, name in enumerate(class_names):
        folder = split_dir / name
        if not folder.is_dir():
            sys.exit("ERROR: missing class folder {}".format(folder))
        for p in sorted(folder.iterdir()):
            if p.suffix.lower() in IMAGE_SUFFIXES:
                paths.append(p)
                labels.append(idx)
    return paths, labels


def print_confusion(cm, class_names, out):
    width = max(len(c) for c in class_names) + 2
    out("\n  Confusion matrix  (rows = true, columns = predicted)")
    out("  " + " " * width + "".join("{:>10}".format(c[:9]) for c in class_names)
        + "{:>8}".format("total"))
    for i, name in enumerate(class_names):
        row = cm[i]
        out("  {:<{w}}".format(name, w=width)
            + "".join("{:>10}".format(int(v)) for v in row)
            + "{:>8}".format(int(row.sum())))
    out("  " + "-" * (width + 10 * len(class_names) + 8))
    out("  {:<{w}}".format("predicted total", w=width)
        + "".join("{:>10}".format(int(cm[:, j].sum())) for j in range(len(class_names))))


def save_confusion_figure(cm, class_names, path):
    """Confusion matrix as a PNG for the report. Skipped if matplotlib absent."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("  (matplotlib not installed -- skipping the figure)")
        return None

    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    im = ax.imshow(cm, cmap="Blues")
    ax.set_xticks(range(len(class_names)))
    ax.set_yticks(range(len(class_names)))
    ax.set_xticklabels([c.replace("_", "\n") for c in class_names], fontsize=9)
    ax.set_yticklabels([c.replace("_", "\n") for c in class_names], fontsize=9)
    ax.set_xlabel("Predicted"); ax.set_ylabel("True")
    ax.set_title("Disease classifier - test set confusion matrix")

    threshold = cm.max() / 2.0 if cm.max() else 0.5
    for i in range(len(class_names)):
        for j in range(len(class_names)):
            ax.text(j, i, int(cm[i, j]), ha="center", va="center", fontsize=12,
                    color="white" if cm[i, j] > threshold else "black")
    fig.colorbar(im, ax=ax, fraction=0.046)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def threshold_sweep(probs, y_true, class_names, out, thresholds):
    """
    How the unknown-disease rule behaves at different cut-offs.

    Every image here belongs to one of the three trained classes, so anything
    rejected as 'unidentified' is a KNOWN disease being turned away. That is
    the cost side. The benefit -- correctly rejecting a disease the model was
    never trained on -- cannot be measured without images of such a disease,
    and this project has none. Say so in the report rather than implying the
    threshold was validated on unknown classes.
    """
    import numpy as np
    out("\n  Confidence-threshold sweep")
    out("  {:>10} {:>12} {:>14} {:>16}".format(
        "threshold", "kept %", "acc if kept", "sent to expert"))
    rows = []
    pred = probs.argmax(axis=1)
    conf = probs.max(axis=1)
    correct = (pred == np.asarray(y_true))
    for t in thresholds:
        keep = conf >= t
        n_keep = int(keep.sum())
        acc = float(correct[keep].mean()) if n_keep else float("nan")
        rows.append({"threshold": t, "kept": n_keep,
                     "kept_pct": 100.0 * n_keep / len(conf),
                     "accuracy_on_kept": acc,
                     "referred": int(len(conf) - n_keep)})
        out("  {:>10.2f} {:>11.1f}% {:>13.3f} {:>16}".format(
            t, rows[-1]["kept_pct"], acc, rows[-1]["referred"]))
    return rows


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    ap.add_argument("--models", default=str(DEFAULT_MODELS))
    ap.add_argument("--model", default=None, help="path to a .keras file")
    ap.add_argument("--split", default="test", choices=["test", "validation"])
    ap.add_argument("--batch-size", type=int, default=32)
    ap.add_argument("--report", default=None, help="write the text report here")
    args = ap.parse_args()

    try:
        import numpy as np
        import tensorflow as tf
        from sklearn.metrics import (classification_report, confusion_matrix,
                                     f1_score, precision_recall_fscore_support)
    except ImportError as exc:
        sys.exit("ERROR: missing dependency ({}).\n"
                 "  pip install tensorflow-cpu scikit-learn matplotlib".format(exc))

    models_dir = Path(args.models).resolve()
    model_path = Path(args.model) if args.model else models_dir / "disease_model.keras"
    names_path = models_dir / "class_names.json"

    if not model_path.exists():
        sys.exit("ERROR: model not found: {}\nRun train.py first.".format(model_path))
    if not names_path.exists():
        sys.exit("ERROR: {} not found.\nWithout it, output index 0 cannot be "
                 "mapped to a disease name. Retrain with the current "
                 "train.py, which writes it.".format(names_path))

    with open(names_path, encoding="utf-8") as f:
        class_names = json.load(f)

    lines = []

    def out(s=""):
        print(s)
        lines.append(s)

    out("=" * 70)
    out("  DISEASE CLASSIFIER -- EVALUATION ON THE {} SET".format(args.split.upper()))
    out("  model   : {}".format(model_path))
    out("  classes : {}".format(class_names))
    out("  run at  : {}".format(datetime.now().isoformat(timespec="seconds")))
    out("=" * 70)

    if args.split == "test":
        out("\n  These images were held out of training entirely. Verified by")
        out("  tools/check_leakage.py -- see data/leakage_report.txt.")

    split_dir = Path(args.data) / args.split
    paths, y_true = collect_files(split_dir, class_names)
    out("\n  images: {}".format(len(paths)))
    for i, c in enumerate(class_names):
        out("    {:<26} {:>4}".format(c, y_true.count(i)))

    model = tf.keras.models.load_model(model_path, compile=False)

    # Feed raw 0-255 RGB: preprocess_input lives inside the model.
    def load(p):
        img = tf.io.decode_image(tf.io.read_file(str(p)), channels=3,
                                 expand_animations=False)
        return tf.cast(tf.image.resize(img, IMG_SIZE, method="bilinear"), tf.float32)

    probs = []
    for i in range(0, len(paths), args.batch_size):
        batch = tf.stack([load(p) for p in paths[i:i + args.batch_size]])
        probs.append(model.predict(batch, verbose=0))
    probs = np.concatenate(probs, axis=0)
    y_pred = probs.argmax(axis=1)
    y_true = np.asarray(y_true)

    # ---------------- headline metrics ----------------
    macro_f1 = f1_score(y_true, y_pred, average="macro")
    weighted_f1 = f1_score(y_true, y_pred, average="weighted")
    accuracy = float((y_pred == y_true).mean())

    out("\n" + "-" * 70)
    out("  HEADLINE")
    out("-" * 70)
    out("  macro F1       : {:.4f}   <- report this one".format(macro_f1))
    out("  weighted F1    : {:.4f}".format(weighted_f1))
    out("  overall accuracy: {:.4f}  ({}/{})".format(
        accuracy, int((y_pred == y_true).sum()), len(y_true)))
    out("  Macro F1 weights each class equally, so the 15-image class counts")
    out("  as much as the 28-image one. Overall accuracy does not.")

    out("\n" + "-" * 70)
    out("  PER-CLASS METRICS")
    out("-" * 70)
    out(classification_report(y_true, y_pred, target_names=class_names,
                              digits=4, zero_division=0))

    prec, rec, f1, sup = precision_recall_fscore_support(
        y_true, y_pred, zero_division=0)
    out("  How to read these:")
    out("    recall    of a disease = of all plants that truly had it, how many")
    out("                            did the system catch. Missing a diseased")
    out("                            plant is the costly error for a grower.")
    out("    precision of a disease = when the system says it, how often it is")
    out("                            right. Low precision means wasted spraying.")

    cm = confusion_matrix(y_true, y_pred, labels=list(range(len(class_names))))
    print_confusion(cm, class_names, out)

    # ---------------- the dangerous errors ----------------
    healthy_idx = class_names.index("healthy") if "healthy" in class_names else None
    if healthy_idx is not None:
        missed = int(sum(1 for t, p in zip(y_true, y_pred)
                         if t != healthy_idx and p == healthy_idx))
        false_alarm = int(sum(1 for t, p in zip(y_true, y_pred)
                              if t == healthy_idx and p != healthy_idx))
        n_diseased = int((y_true != healthy_idx).sum())
        out("\n  Error types that matter to a grower:")
        out("    diseased plants called HEALTHY : {} of {}   <- the costly error"
            .format(missed, n_diseased))
        out("    healthy plants called diseased : {} of {}   (wasted treatment)"
            .format(false_alarm, int((y_true == healthy_idx).sum())))

    # ---------------- misclassified images ----------------
    wrong = [(paths[i], class_names[y_true[i]], class_names[y_pred[i]],
              float(probs[i].max())) for i in range(len(paths))
             if y_pred[i] != y_true[i]]
    out("\n  Misclassified images ({}):".format(len(wrong)))
    if not wrong:
        out("    none")
    for p, t, pr, c in wrong:
        out("    {:<34} true={:<24} pred={:<24} conf={:.3f}".format(p.name, t, pr, c))

    # ---------------- threshold sweep ----------------
    thresholds = [0.40, 0.50, 0.60, 0.65, 0.70, 0.75, 0.80, 0.90]
    sweep = threshold_sweep(probs, y_true, class_names, out, thresholds)
    if args.split == "validation":
        out("\n  Pick the operating threshold from THIS table (validation).")
        out("  Choosing it from the test table would be tuning on the test set.")
    else:
        out("\n  This table is descriptive only. The operating threshold must be")
        out("  chosen from `python evaluate.py --split validation`.")

    # ---------------- save ----------------
    fig_path = models_dir / "confusion_matrix_{}.png".format(args.split)
    saved = save_confusion_figure(cm, class_names, fig_path)

    metrics = {
        "evaluated_at": datetime.now().isoformat(timespec="seconds"),
        "split": args.split,
        "model": str(model_path),
        "class_names": class_names,
        "n_images": len(paths),
        "accuracy": accuracy,
        "macro_f1": float(macro_f1),
        "weighted_f1": float(weighted_f1),
        "per_class": {
            c: {"precision": float(prec[i]), "recall": float(rec[i]),
                "f1": float(f1[i]), "support": int(sup[i])}
            for i, c in enumerate(class_names)},
        "confusion_matrix": cm.tolist(),
        "misclassified": [{"file": p.name, "true": t, "predicted": pr,
                           "confidence": c} for p, t, pr, c in wrong],
        "threshold_sweep": sweep,
    }
    metrics_path = models_dir / "metrics_{}.json".format(args.split)
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    out("\n" + "=" * 70)
    out("  metrics json : {}".format(metrics_path))
    if saved:
        out("  figure       : {}".format(saved))
    out("=" * 70)

    report_path = Path(args.report) if args.report else \
        models_dir / "evaluation_report_{}.txt".format(args.split)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\nreport written: {}".format(report_path))


if __name__ == "__main__":
    main()
