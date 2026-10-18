"""
extra_metrics.py -- measures beyond accuracy and F1, shared by both evaluators.

The panel at the second progress review asked for evaluation with "different
metrics". Each one below answers a question accuracy cannot:

  majority baseline   what you would score by always guessing the commonest
                      class. A model has learned something only above this.
  balanced accuracy   the mean of per-class recall, so the 15-image class
                      counts as much as the 28-image one.
  Cohen's kappa       agreement with the truth after removing what lucky
                      guessing alone would achieve. 0 = chance, 1 = perfect.
  MCC                 Matthews correlation, -1 to 1. Stays honest when the
                      classes are unequal in size.
  ROC-AUC             how well the probabilities RANK each class above the
                      others, independent of any threshold. 0.5 = guessing.
  calibration (ECE)   whether "90% sure" is right about 90% of the time. 0 is
                      perfect; it matters because the app shows a percentage.
  95% range           the spread of each score over 2,000 resamples of the test
                      photographs. With 67 photographs one image moves accuracy
                      1.5 points, so a single number overstates certainty.

For the ORDERED severity scale, two more:

  quadratic weighted kappa   kappa where a two-grade error costs four times a
                             one-grade error, the standard score for graded scales.
  mean grade error           how many grades out a prediction is, on average.
"""

import numpy as np

N_BOOT = 2000
SEED = 42


def majority_baseline(y_true, n_classes):
    """Accuracy and macro F1 of always predicting the most common class."""
    y_true = np.asarray(y_true)
    counts = np.bincount(y_true, minlength=n_classes)
    share = counts.max() / len(y_true)
    # Always predicting class k: precision = share, recall = 1 for k; 0 elsewhere.
    f1_k = 2 * share / (1 + share)
    return {"accuracy": float(share), "macro_f1": float(f1_k / n_classes),
            "class_index": int(counts.argmax())}


def expected_calibration_error(probs, y_true, bins=10):
    """Gap between confidence and accuracy, averaged over confidence bins."""
    conf = probs.max(axis=1)
    correct = (probs.argmax(axis=1) == np.asarray(y_true)).astype(float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi)
        if m.any():
            ece += m.mean() * abs(correct[m].mean() - conf[m].mean())
    return float(ece)


def _bootstrap(fn, y_true, y_pred, n_boot=N_BOOT, seed=SEED):
    """2.5th and 97.5th percentiles of fn over resamples of the photographs."""
    rng = np.random.default_rng(seed)
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    n = len(y_true)
    scores = [fn(y_true[idx], y_pred[idx]) for idx in
              (rng.integers(0, n, n) for _ in range(n_boot))]
    return [float(np.percentile(scores, 2.5)), float(np.percentile(scores, 97.5))]


def classification_extras(y_true, y_pred, probs, class_names):
    from sklearn.metrics import (balanced_accuracy_score, cohen_kappa_score,
                                 f1_score, matthews_corrcoef, roc_auc_score)
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    labels = list(range(len(class_names)))
    auc = {}
    for k, name in enumerate(class_names):
        positive = (y_true == k).astype(int)
        if 0 < positive.sum() < len(positive):
            auc[name] = float(roc_auc_score(positive, probs[:, k]))
    return {
        "majority_baseline": majority_baseline(y_true, len(class_names)),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "cohen_kappa": float(cohen_kappa_score(y_true, y_pred)),
        "mcc": float(matthews_corrcoef(y_true, y_pred)),
        "roc_auc_per_class": auc,
        "roc_auc_macro": float(np.mean(list(auc.values()))) if auc else None,
        "expected_calibration_error": expected_calibration_error(probs, y_true),
        "ci95_accuracy": _bootstrap(lambda t, p: float((t == p).mean()), y_true, y_pred),
        "ci95_macro_f1": _bootstrap(
            lambda t, p: float(f1_score(t, p, average="macro", labels=labels, zero_division=0)),
            y_true, y_pred),
        "bootstrap": {"resamples": N_BOOT, "seed": SEED},
    }


def ordinal_extras(y_true, y_pred, probs):
    from sklearn.metrics import (balanced_accuracy_score, cohen_kappa_score,
                                 matthews_corrcoef)
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)

    def qwk(t, p):
        return float(cohen_kappa_score(t, p, weights="quadratic", labels=[0, 1, 2]))

    return {
        "majority_baseline": majority_baseline(y_true, 3),
        "balanced_accuracy": float(balanced_accuracy_score(y_true, y_pred)),
        "cohen_kappa": float(cohen_kappa_score(y_true, y_pred, labels=[0, 1, 2])),
        "quadratic_weighted_kappa": qwk(y_true, y_pred),
        "mcc": float(matthews_corrcoef(y_true, y_pred)),
        "mean_grade_error": float(np.abs(y_true - y_pred).mean()),
        "expected_calibration_error": expected_calibration_error(probs, y_true),
        "ci95_exact_accuracy": _bootstrap(lambda t, p: float((t == p).mean()), y_true, y_pred),
        "ci95_within_one_grade": _bootstrap(
            lambda t, p: float((np.abs(t - p) <= 1).mean()), y_true, y_pred),
        "ci95_quadratic_weighted_kappa": _bootstrap(qwk, y_true, y_pred),
        "bootstrap": {"resamples": N_BOOT, "seed": SEED},
    }


def save_roc_figure(y_true, probs, class_names, path, title):
    """One-vs-rest ROC curve per class. Skipped if matplotlib is absent."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from sklearn.metrics import roc_auc_score, roc_curve
    except ImportError:
        return None
    y_true = np.asarray(y_true)
    fig, ax = plt.subplots(figsize=(5.6, 5.0))
    for k, name in enumerate(class_names):
        positive = (y_true == k).astype(int)
        if 0 < positive.sum() < len(positive):
            fpr, tpr, _ = roc_curve(positive, probs[:, k])
            ax.plot(fpr, tpr, linewidth=2,
                    label="{} (AUC {:.3f})".format(name.replace("_", " "),
                                                   roc_auc_score(positive, probs[:, k])))
    ax.plot([0, 1], [0, 1], "--", color="grey", linewidth=1, label="guessing (AUC 0.5)")
    ax.set_xlabel("false positive rate")
    ax.set_ylabel("true positive rate")
    ax.set_title(title, fontsize=11)
    ax.legend(loc="lower right", fontsize=8.5)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def describe_classification(x, out):
    """Print the extra measures with a one-line reading of each."""
    b = x["majority_baseline"]
    out("\n" + "-" * 70)
    out("  BEYOND ACCURACY")
    out("-" * 70)
    out("  majority-class baseline : accuracy {:.4f}, macro F1 {:.4f}".format(
        b["accuracy"], b["macro_f1"]))
    out("      what always guessing the commonest class would score")
    out("  balanced accuracy       : {:.4f}   mean recall; small classes count equally".format(
        x["balanced_accuracy"]))
    out("  Cohen's kappa           : {:.4f}   agreement beyond chance (0 chance, 1 perfect)".format(
        x["cohen_kappa"]))
    out("  MCC                     : {:.4f}   -1 to 1, honest under unequal classes".format(x["mcc"]))
    out("  ROC-AUC (macro)         : {:.4f}   ranking quality; 0.5 = guessing".format(
        x["roc_auc_macro"]))
    for name, v in x["roc_auc_per_class"].items():
        out("      {:<26} {:.4f}".format(name, v))
    out("  calibration error (ECE) : {:.4f}   0 = '90% sure' is right 90% of the time".format(
        x["expected_calibration_error"]))
    out("  95% range, accuracy     : {:.3f} to {:.3f}".format(*x["ci95_accuracy"]))
    out("  95% range, macro F1     : {:.3f} to {:.3f}".format(*x["ci95_macro_f1"]))
    out("      from {} resamples of these photographs (seed {})".format(
        x["bootstrap"]["resamples"], x["bootstrap"]["seed"]))


def describe_ordinal(x, out):
    b = x["majority_baseline"]
    out("\n" + "-" * 70)
    out("  BEYOND ACCURACY (ordered grades)")
    out("-" * 70)
    out("  majority-class baseline : exact accuracy {:.4f}, macro F1 {:.4f}".format(
        b["accuracy"], b["macro_f1"]))
    out("  quadratic weighted kappa: {:.4f}   the standard score for graded scales".format(
        x["quadratic_weighted_kappa"]))
    out("  mean grade error        : {:.4f}   grades out, on average".format(x["mean_grade_error"]))
    out("  Cohen's kappa           : {:.4f}   unweighted, every error equal".format(x["cohen_kappa"]))
    out("  MCC                     : {:.4f}".format(x["mcc"]))
    out("  balanced accuracy       : {:.4f}".format(x["balanced_accuracy"]))
    out("  calibration error (ECE) : {:.4f}".format(x["expected_calibration_error"]))
    out("  95% range, exact        : {:.3f} to {:.3f}".format(*x["ci95_exact_accuracy"]))
    out("  95% range, within one   : {:.3f} to {:.3f}".format(*x["ci95_within_one_grade"]))
    out("  95% range, QWK          : {:.3f} to {:.3f}".format(*x["ci95_quadratic_weighted_kappa"]))
