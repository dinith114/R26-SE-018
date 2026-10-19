"""
Evaluation figures for the viva, rebuilt from the saved result files.

WHY THIS SCRIPT EXISTS
----------------------
Every PNG in results/ is dated 11 May and was produced by a pipeline that split
the data at IMAGE level. Photographs of the same plant landed on both sides of
the split, so the model was tested on plants it had memorised and the figures
report accuracies in the high nineties. results/training_results.json says so
itself: "A previous version of this pipeline reported 100% accuracy using a
random image-level split. That figure was data leakage."

The valid results are dated 30 August and come from StratifiedGroupKFold
grouped by sample_id, where every photograph of one plant stays on one side.
Nothing had ever drawn them. Showing a May figure beside an August number is
the single easiest way to be caught contradicting your own report, so this
script draws the August numbers and nothing else.

It reads only saved result files - no model is loaded and nothing is retrained,
so it runs in seconds on any machine with matplotlib, including Colab.

    python src/viva_metrics.py              # print the tables, save the figures
    python src/viva_metrics.py --no-save    # print only
"""
import argparse
import csv
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RESULTS = os.path.join(ROOT, "results")
OUT = os.path.join(RESULTS, "viva")

# One accent, one muted, one warning. Matching the app rather than matplotlib's
# default blue, so the slides and the demo look like one project.
GREEN = "#1C591D"
GREEN_L = "#8FBF90"
GREY = "#9AA39A"
RED = "#BE123C"
AMBER = "#B45309"


def _load(name):
    with open(os.path.join(RESULTS, name), encoding="utf-8") as f:
        return json.load(f)


def _style(ax):
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(colors="#444", labelsize=9)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color("#CCC")


# ──────────────────────────────────────────────
#  1. Model comparison, against the baseline
# ──────────────────────────────────────────────
def model_comparison(save=True):
    d = _load("training_results.json")
    baseline = d["majority_baseline"]
    names, accs, bals = [], [], []
    for name, m in d["models"].items():
        names.append(name.replace(" (RBF)", "\n(RBF)"))
        accs.append(m["accuracy"])
        bals.append(m["balanced_accuracy"])

    order = np.argsort(accs)[::-1]
    names = [names[i] for i in order]
    accs = [accs[i] for i in order]
    bals = [bals[i] for i in order]

    print("\n=== SUITABILITY MODELS (grouped CV by plant, 28 plants) ===")
    print("%-22s %10s %10s %s" % ("model", "accuracy", "balanced", "beats baseline"))
    for n, a, b in zip(names, accs, bals):
        print("%-22s %9.1f%% %9.1f%% %s"
              % (n.replace("\n", " "), a * 100, b * 100, "yes" if a > baseline else "NO"))
    print("%-22s %9.1f%%" % ("majority baseline", baseline * 100))

    if not save:
        return
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    ax.bar(x - 0.19, accs, 0.38, label="Accuracy", color=GREEN)
    ax.bar(x + 0.19, bals, 0.38, label="Balanced accuracy", color=GREEN_L)
    ax.axhline(baseline, color=RED, ls="--", lw=1.4,
               label="Majority baseline (%.1f%%)" % (baseline * 100))
    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.set_ylim(0, 1.0)
    ax.set_ylabel("Score")
    ax.set_title("Suitability models — grouped cross-validation by plant",
                 fontsize=11, color="#222")
    ax.legend(fontsize=8, frameon=False)
    for i, a in enumerate(accs):
        ax.text(i - 0.19, a + 0.015, "%.0f%%" % (a * 100), ha="center", fontsize=8)
    _style(ax)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "01_model_comparison.png"), dpi=200)
    plt.close(fig)


# ──────────────────────────────────────────────
#  2. Confusion matrix + the errors that matter
# ──────────────────────────────────────────────
def confusion(save=True):
    d = _load("training_results.json")
    best = d["best_model"]
    cm = np.array(d["models"][best]["confusion_matrix"])
    classes = d["dataset_info"]["classes"]

    print("\n=== CONFUSION MATRIX — %s ===" % best)
    print("rows = annotated, columns = predicted")
    print("%-14s %s" % ("", "  ".join("%-14s" % c for c in classes)))
    for i, c in enumerate(classes):
        print("%-14s %s   (n=%d)"
              % (c, "  ".join("%-14d" % v for v in cm[i]), cm[i].sum()))

    print("\nPer class:")
    print("%-14s %9s %9s %9s %9s" % ("class", "recall", "precision", "F1", "support"))
    for i, c in enumerate(classes):
        tp = cm[i, i]
        support = cm[i].sum()
        predicted = cm[:, i].sum()
        rec = tp / support if support else 0.0
        pre = tp / predicted if predicted else 0.0
        f1 = 2 * pre * rec / (pre + rec) if (pre + rec) else 0.0
        print("%-14s %8.1f%% %8.1f%% %8.1f%% %9d"
              % (c, rec * 100, pre * 100, f1 * 100, support))

    # The asymmetry the whole component is designed around.
    ns = classes.index("Not Suitable")
    su = classes.index("Suitable")
    fp = cm[ns, su]      # annotated Not Suitable, called Suitable
    fn = cm[su, ns]      # annotated Suitable, called Not Suitable
    print("\nThe two errors, and they do not cost the same:")
    print("  FALSE SUITABLE  (said Suitable, was Not Suitable) : %d" % fp)
    print("     a weak plant is committed to a capsule for nine months")
    print("  FALSE NOT SUITABLE (said Not Suitable, was Suitable): %d" % fn)
    print("     the grower looks at a second plant")

    if not save:
        return
    fig, ax = plt.subplots(figsize=(5.4, 4.6))
    norm = cm / np.maximum(cm.sum(axis=1, keepdims=True), 1)
    ax.imshow(norm, cmap="Greens", vmin=0, vmax=1)
    for i in range(len(classes)):
        for j in range(len(classes)):
            ax.text(j, i, "%d\n%.0f%%" % (cm[i, j], norm[i, j] * 100),
                    ha="center", va="center", fontsize=10,
                    color="white" if norm[i, j] > 0.55 else "#222")
    ax.set_xticks(range(len(classes)))
    ax.set_xticklabels(classes, fontsize=9)
    ax.set_yticks(range(len(classes)))
    ax.set_yticklabels(classes, fontsize=9)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("Annotated")
    ax.set_title("%s — out-of-fold confusion matrix" % best, fontsize=11, color="#222")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "02_confusion_matrix.png"), dpi=200)
    plt.close(fig)


# ──────────────────────────────────────────────
#  3. The traits that are read from the photograph
# ──────────────────────────────────────────────
def traits(save=True):
    d = _load("trait_training_results.json")
    print("\n=== TRAITS READ FROM THE PHOTOGRAPH (grouped CV) ===")
    rows = []
    for trait, t in d["traits"].items():
        m = t["models"][t["best_model"]]
        rows.append((trait.replace("_", " "), m["accuracy"], t["baseline"], t["best_model"]))
        print("%-18s %6.1f%%  (baseline %.1f%%)  %s"
              % (trait.replace("_", " "), m["accuracy"] * 100,
                 t["baseline"] * 100, t["best_model"]))

    if not save:
        return
    fig, ax = plt.subplots(figsize=(6.0, 3.2))
    y = np.arange(len(rows))
    ax.barh(y, [r[1] for r in rows], 0.42, color=GREEN, label="Measured")
    ax.barh(y + 0.44, [r[2] for r in rows], 0.42, color=GREY, label="Baseline")
    ax.set_yticks(y + 0.22)
    ax.set_yticklabels([r[0] for r in rows], fontsize=9)
    ax.set_xlim(0, 1.0)
    ax.set_xlabel("Accuracy")
    ax.set_title("Traits measured from one photograph", fontsize=11, color="#222")
    ax.legend(fontsize=8, frameon=False, loc="lower right")
    for i, r in enumerate(rows):
        ax.text(r[1] + 0.012, i, "%.0f%%" % (r[1] * 100), va="center", fontsize=8)
    _style(ax)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "03_trait_models.png"), dpi=200)
    plt.close(fig)


# ──────────────────────────────────────────────
#  4. The input check, on its held-out set
# ──────────────────────────────────────────────
def gate(save=True):
    path = os.path.join(RESULTS, "orchid_gate_validation.csv")
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    acc = lambda r: str(r["accepted"]).strip().lower() in ("true", "1", "yes")

    NONPLANT = {"cars", "depictions", "documents", "food",
                "laptops", "people", "rooms", "screens"}
    groups = [
        ("Everyday objects", [r for r in rows if r["category"] in NONPLANT], False),
        ("Other plants", [r for r in rows
                          if r["label"] == "not_orchid" and r["category"] not in NONPLANT], False),
        ("Real orchids", [r for r in rows if r["label"] == "orchid"], True),
    ]

    print("\n=== INPUT CHECK — held-out set, never used for fitting ===")
    labels, vals, colours = [], [], []
    for name, g, want_accept in groups:
        a = sum(1 for r in g if acc(r))
        pct = (a if want_accept else len(g) - a) / len(g) * 100
        verb = "accepted" if want_accept else "refused"
        print("  %-18s %3d images   %5.1f%% %s" % (name, len(g), pct, verb))
        labels.append("%s\n(%s)" % (name, verb))
        vals.append(pct)
        colours.append(GREEN if pct >= 90 else AMBER if pct >= 70 else RED)

    no = [r for r in rows if r["label"] == "not_orchid"]
    a = sum(1 for r in no if acc(r))
    print("  %-18s %3d images   %5.1f%% refused   <- the headline"
          % ("ALL non-orchid", len(no), (len(no) - a) / len(no) * 100))

    if not save:
        return
    fig, ax = plt.subplots(figsize=(6.0, 3.6))
    ax.bar(labels, vals, 0.55, color=colours)
    for i, v in enumerate(vals):
        ax.text(i, v + 1.5, "%.0f%%" % v, ha="center", fontsize=9, fontweight="bold")
    ax.set_ylim(0, 108)
    ax.set_ylabel("%")
    ax.set_title("Input check — 543 held-out images", fontsize=11, color="#222")
    _style(ax)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "04_input_check.png"), dpi=200)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--no-save", action="store_true", help="print the tables only")
    args = ap.parse_args()
    save = not args.no_save

    if save:
        os.makedirs(OUT, exist_ok=True)

    d = _load("training_results.json")
    info = d["dataset_info"]
    print("=" * 66)
    print("  R26-SE-018  Component 1 - Hybrid Pollination")
    print("  Evaluation, regenerated from %s" % d["timestamp"][:10])
    print("=" * 66)
    print("  %d photographs of %d plants - 28 is the sample size, not 357"
          % (info["n_images"], info["n_plants"]))
    print("  %s, %d folds, grouped by %s"
          % (d["evaluation"]["method"], d["evaluation"]["n_folds"],
             d["evaluation"]["grouped_by"]))
    print("  plants per class: %s" % info["plants_per_class"])
    for c in d["caveats"]:
        print("  ! %s" % c)

    model_comparison(save)
    confusion(save)
    traits(save)
    gate(save)

    if save:
        print("\nFigures written to %s" % OUT)
        for f in sorted(os.listdir(OUT)):
            print("   %s" % f)


if __name__ == "__main__":
    main()
