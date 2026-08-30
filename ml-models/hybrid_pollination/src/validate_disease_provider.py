"""
Hybrid Pollination - Disease Provider Validation

Measures how well the image-derived disease signal reproduces the disease
annotations, so that replacing the user's dropdown with a measurement can be
justified with a number instead of an assertion.

Two rules make the result honest:

  1. Grouped by plant. `disease_visible` is annotated per plant and constant
     across every photo of it, so scoring per image would count the same plant
     up to 50 times and inflate everything. All headline numbers are per plant.

  2. The threshold is calibrated by leave-one-plant-out cross-validation.
     Picking a threshold on all the data and then reporting accuracy on that
     same data is the same mistake as the original random train/test split.

Usage:
    python src/validate_disease_provider.py
    python src/validate_disease_provider.py --limit 60      # quick run
"""

import os
import sys
import json
import argparse
from collections import defaultdict

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from disease_provider import HeuristicDiseaseProvider


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLEAN_CSV = os.path.join(BASE_DIR, "data", "image_annotations_clean.csv")
RESULTS_DIR = os.path.join(BASE_DIR, "results")
CACHE_CSV = os.path.join(RESULTS_DIR, "disease_signals.csv")


# ──────────────────────────────────────────────
# Signal extraction
# ──────────────────────────────────────────────
def compute_signals(df: pd.DataFrame, limit: int = None) -> pd.DataFrame:
    """Run the heuristic provider over every annotated plant image."""
    provider = HeuristicDiseaseProvider()

    if limit:
        df = df.groupby("sample_id", group_keys=False).head(max(1, limit // df.sample_id.nunique()))

    rows = []
    total = len(df)
    print(f"[STEP] Scoring {total} images with the heuristic provider...")

    for i, (_, row) in enumerate(df.iterrows(), 1):
        if i % 25 == 0:
            print(f"  {i}/{total}")

        try:
            signal = provider.analyze(row["image_path"])
        except Exception as e:
            print(f"  [WARN] {row['image_name']}: {e}")
            continue

        rows.append({
            "sample_id": row["sample_id"],
            "image_name": row["image_name"],
            "annotated": row["disease_visible"],
            "severity": signal.severity,
            "confidence": signal.confidence,
            **signal.evidence,
        })

    return pd.DataFrame(rows)


# ──────────────────────────────────────────────
# Evaluation
# ──────────────────────────────────────────────
def to_plant_level(sig: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse per-image severities to one row per plant.

    Uses the 75th percentile rather than the mean: disease is often visible in
    only some views of a plant, and averaging would wash out a real detection
    seen in three photos out of twenty.
    """
    grouped = sig.groupby("sample_id").agg(
        severity=("severity", lambda s: float(np.percentile(s, 75))),
        severity_mean=("severity", "mean"),
        severity_max=("severity", "max"),
        confidence=("confidence", "mean"),
        n_images=("severity", "size"),
        annotated=("annotated", lambda s: s.mode().iloc[0]),
    ).reset_index()

    return grouped[grouped.annotated.isin(["yes", "no"])].copy()


def metrics_at(y_true: np.ndarray, y_pred: np.ndarray) -> dict:
    """Accuracy, precision, recall and F1 for the positive (diseased) class."""
    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())
    tn = int(((y_pred == 0) & (y_true == 0)).sum())

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return {
        "accuracy": (tp + tn) / max(len(y_true), 1),
        "precision": precision, "recall": recall, "f1": f1,
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def best_threshold(sev: np.ndarray, y: np.ndarray) -> float:
    """Threshold maximising F1 on the given plants."""
    candidates = np.unique(np.round(np.concatenate([sev, np.arange(0.05, 0.95, 0.01)]), 3))
    best_t, best_f1 = 0.35, -1.0

    for t in candidates:
        f1 = metrics_at(y, (sev >= t).astype(int))["f1"]
        if f1 > best_f1:
            best_f1, best_t = f1, float(t)

    return best_t


def leave_one_plant_out(plants: pd.DataFrame) -> dict:
    """
    Honest evaluation: for each plant, calibrate the threshold on the OTHER
    plants and then classify the held-out one.
    """
    sev = plants.severity.values
    y = (plants.annotated == "yes").astype(int).values

    preds, thresholds = [], []
    for i in range(len(plants)):
        train = np.ones(len(plants), dtype=bool)
        train[i] = False

        t = best_threshold(sev[train], y[train])
        thresholds.append(t)
        preds.append(int(sev[i] >= t))

    result = metrics_at(y, np.array(preds))
    result["mean_threshold"] = float(np.mean(thresholds))
    result["threshold_std"] = float(np.std(thresholds))
    return result


def auc_score(sev: np.ndarray, y: np.ndarray) -> float:
    """
    ROC AUC via rank statistic - threshold-free, so it shows whether the
    severity score separates the classes at all.
    """
    pos, neg = sev[y == 1], sev[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")

    ranks = pd.Series(sev).rank().values
    return float((ranks[y == 1].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


# ──────────────────────────────────────────────
# Report
# ──────────────────────────────────────────────
def report(plants: pd.DataFrame) -> dict:
    sev = plants.severity.values
    y = (plants.annotated == "yes").astype(int).values

    n_pos, n_neg = int(y.sum()), int((1 - y).sum())
    majority = max(n_pos, n_neg) / len(y)

    print("\n" + "=" * 66)
    print("DISEASE PROVIDER VALIDATION  (grouped by plant)")
    print("=" * 66)
    print(f"\nPlants evaluated : {len(plants)}   diseased={n_pos}  healthy={n_neg}")
    print(f"Majority baseline: {majority:.3f}   (always predict the commoner class)")
    print(f"ROC AUC          : {auc_score(sev, y):.3f}   (0.5 = no signal, 1.0 = perfect)")

    loo = leave_one_plant_out(plants)
    print("\n--- Leave-one-plant-out (threshold calibrated without the held-out plant) ---")
    print(f"  Accuracy : {loo['accuracy']:.3f}   vs {majority:.3f} baseline")
    print(f"  Precision: {loo['precision']:.3f}")
    print(f"  Recall   : {loo['recall']:.3f}")
    print(f"  F1       : {loo['f1']:.3f}")
    print(f"  Confusion: TP={loo['tp']}  FP={loo['fp']}  FN={loo['fn']}  TN={loo['tn']}")
    print(f"  Threshold: {loo['mean_threshold']:.3f} +/- {loo['threshold_std']:.3f}")

    fitted = best_threshold(sev, y)
    insample = metrics_at(y, (sev >= fitted).astype(int))
    print(f"\n--- Threshold fitted on ALL plants (optimistic - for reference only) ---")
    print(f"  Threshold {fitted:.3f} -> accuracy {insample['accuracy']:.3f}, F1 {insample['f1']:.3f}")

    print("\n--- Per-plant severity ---")
    for _, r in plants.sort_values("severity", ascending=False).iterrows():
        flag = "OK " if (r.severity >= loo["mean_threshold"]) == (r.annotated == "yes") else "MISS"
        print(f"  {flag}  {r.sample_id:6s}  severity={r.severity:.3f}  "
              f"annotated={r.annotated:3s}  n_images={int(r.n_images):3d}")

    print("=" * 66)

    return {
        "n_plants": len(plants), "n_diseased": n_pos, "n_healthy": n_neg,
        "majority_baseline": round(majority, 4),
        "roc_auc": round(auc_score(sev, y), 4),
        "leave_one_plant_out": {k: (round(v, 4) if isinstance(v, float) else v)
                                for k, v in loo.items()},
        "fitted_threshold": round(fitted, 4),
        "fitted_in_sample": {k: (round(v, 4) if isinstance(v, float) else v)
                             for k, v in insample.items()},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Score only roughly this many images (quick run)")
    parser.add_argument("--recompute", action="store_true",
                        help="Ignore the cached signals CSV")
    args = parser.parse_args()

    os.makedirs(RESULTS_DIR, exist_ok=True)

    if os.path.exists(CACHE_CSV) and not args.recompute and not args.limit:
        print(f"[INFO] Reusing cached signals from {os.path.basename(CACHE_CSV)} "
              f"(--recompute to refresh)")
        sig = pd.read_csv(CACHE_CSV)
    else:
        df = pd.read_csv(CLEAN_CSV)
        df = df[df.disease_visible.isin(["yes", "no"])]
        sig = compute_signals(df, args.limit)
        if not args.limit:
            sig.to_csv(CACHE_CSV, index=False)
            print(f"[SAVED] Per-image signals -> {os.path.basename(CACHE_CSV)}")

    plants = to_plant_level(sig)
    summary = report(plants)

    out = os.path.join(RESULTS_DIR, "disease_validation.json")
    with open(out, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n[SAVED] Summary -> {os.path.basename(out)}")


if __name__ == "__main__":
    main()
