"""
Hybrid Pollination - Model Training Script

Trains and evaluates suitability models with GROUPED cross-validation.

WHY THIS LOOKS DIFFERENT FROM A NORMAL TRAINING SCRIPT
-------------------------------------------------------
The previous version reported 100% test accuracy. That figure was produced by
data leakage, not by a good model: 357 images came from 28 plants, and a random
split put photographs of the SAME plant on both sides of the divide.

Three changes make the numbers real:

  1. Splits are grouped by `sample_id`, so every image of a plant stays on one
     side. The unit of evaluation is the PLANT, not the photograph.

  2. There is no single train/val/test split. With 28 plants - and only 2 of
     them labelled Moderate - a three-way grouped split cannot represent every
     class. StratifiedGroupKFold cross-validation is used instead, so every
     plant is held out exactly once across the folds.

  3. Scaling happens INSIDE each fold, through a Pipeline. Fitting a scaler on
     all data before splitting leaks test-fold statistics into training.

Every score is reported next to the majority-class baseline. A model that
cannot beat "always predict Suitable" (0.639) has learned nothing, and saying
so plainly is worth more than an impressive number that will not survive a
question.

Usage:
    python src/train.py
    python src/train.py --folds 5
"""

import numpy as np
import os
import sys
import joblib
import json
import argparse
from datetime import datetime
from collections import Counter

from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import SVC
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import StratifiedGroupKFold, cross_val_predict
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    classification_report, confusion_matrix, balanced_accuracy_score,
)

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from xgboost import XGBClassifier
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False
    print("[WARN] XGBoost not installed - skipping XGBoost model")


# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, "models")
RESULTS_DIR = os.path.join(BASE_DIR, "results")

DEFAULT_FOLDS = 5


def get_models() -> dict:
    """
    The models to compare, each wrapped in a Pipeline so that scaling is fitted
    per fold rather than on the whole dataset.
    """
    def pipe(estimator):
        return Pipeline([("scaler", StandardScaler()), ("model", estimator)])

    models = {
        "Random Forest": pipe(RandomForestClassifier(
            n_estimators=200, max_depth=15, min_samples_split=5,
            min_samples_leaf=2, class_weight="balanced",
            random_state=42, n_jobs=-1,
        )),
        "SVM (RBF)": pipe(SVC(
            kernel="rbf", C=1.0, gamma="scale", class_weight="balanced",
            probability=True, random_state=42,
        )),
        "Logistic Regression": pipe(LogisticRegression(
            max_iter=1000, class_weight="balanced", random_state=42,
        )),
    }

    if HAS_XGBOOST:
        models["XGBoost"] = pipe(XGBClassifier(
            n_estimators=200, max_depth=8, learning_rate=0.1,
            subsample=0.8, colsample_bytree=0.8, random_state=42,
            eval_metric="mlogloss",
        ))

    return models


def majority_baseline(y: np.ndarray) -> float:
    """Accuracy of always predicting the commonest class."""
    counts = Counter(y.tolist())
    return max(counts.values()) / len(y)


def n_usable_folds(y: np.ndarray, groups: np.ndarray, requested: int) -> int:
    """
    Largest workable fold count.

    StratifiedGroupKFold cannot create more folds than the rarest class has
    plants. With 2 Moderate plants, asking for 5 folds silently produces folds
    containing no Moderate example at all.
    """
    plants_per_class = Counter()
    seen = set()
    for label, group in zip(y, groups):
        if group in seen:
            continue
        seen.add(group)
        plants_per_class[label] += 1

    rarest = min(plants_per_class.values()) if plants_per_class else requested
    folds = max(2, min(requested, rarest))

    if folds < requested:
        print(f"[WARN] Reduced folds {requested} -> {folds}: the rarest class has "
              f"only {rarest} plants.")

    return folds


def train_and_evaluate(data: dict, n_folds: int = DEFAULT_FOLDS) -> tuple:
    """
    Cross-validate every model with grouping by plant.

    Returns:
        (results dict, best model name)
    """
    X, y, groups = data["X"], data["y"], data["groups"]
    label_encoder = data["label_encoder"]
    class_names = list(label_encoder.classes_)

    n_folds = n_usable_folds(y, groups, n_folds)
    cv = StratifiedGroupKFold(n_splits=n_folds, shuffle=True,
                              random_state=data.get("random_state", 42))

    baseline = majority_baseline(y)

    print("\n" + "=" * 72)
    print(f"GROUPED CROSS-VALIDATION  ({n_folds}-fold, grouped by plant)")
    print("=" * 72)
    print(f"  Images: {len(y)}   Plants: {len(set(groups))}")
    print(f"  Majority-class baseline: {baseline:.4f}  <- the number to beat")

    results = {}
    best_name, best_score = None, -1.0

    for name, model in get_models().items():
        print(f"\n{'-' * 56}\n{name}\n{'-' * 56}")

        # One out-of-fold prediction per image, each made by a model that never
        # saw that image's plant during training.
        y_pred = cross_val_predict(model, X, y, cv=cv, groups=groups, n_jobs=1)

        acc = accuracy_score(y, y_pred)
        bal_acc = balanced_accuracy_score(y, y_pred)
        precision = precision_score(y, y_pred, average="weighted", zero_division=0)
        recall = recall_score(y, y_pred, average="weighted", zero_division=0)
        f1 = f1_score(y, y_pred, average="weighted", zero_division=0)
        cm = confusion_matrix(y, y_pred)
        report = classification_report(y, y_pred, target_names=class_names,
                                       zero_division=0)

        verdict = "beats baseline" if acc > baseline else "DOES NOT beat baseline"
        print(f"  Accuracy (grouped) : {acc:.4f}   ({verdict}, baseline {baseline:.4f})")
        print(f"  Balanced accuracy  : {bal_acc:.4f}   <- fairer with imbalanced classes")
        print(f"  Weighted F1        : {f1:.4f}")
        print(f"\n{report}")

        results[name] = {
            "model": model,
            "accuracy": acc,
            "balanced_accuracy": bal_acc,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "beats_baseline": bool(acc > baseline),
            "confusion_matrix": cm,
            "classification_report": report,
        }

        # Balanced accuracy selects the best model: plain accuracy would reward
        # a model that simply predicts the majority class.
        if bal_acc > best_score:
            best_score, best_name = bal_acc, name

    return results, best_name, baseline


def fit_final_model(results: dict, best_name: str, data: dict):
    """
    Refit the chosen model on ALL data for deployment.

    The cross-validated scores above describe how this model generalises to an
    unseen plant. This fit is what actually ships; its training accuracy is not
    a performance measure and is deliberately not reported.
    """
    model = results[best_name]["model"]
    model.fit(data["X"], data["y"])

    os.makedirs(MODELS_DIR, exist_ok=True)
    path = os.path.join(MODELS_DIR, "best_model.pkl")
    joblib.dump(model, path)
    print(f"\n[SAVED] Best model ({best_name}) -> {os.path.basename(path)}")

    for name, res in results.items():
        safe = name.lower().replace(" ", "_").replace("(", "").replace(")", "")
        m = res["model"]
        m.fit(data["X"], data["y"])
        joblib.dump(m, os.path.join(MODELS_DIR, f"{safe}.pkl"))

    return model


def save_results(results: dict, best_name: str, data: dict, baseline: float,
                 n_folds: int):
    """Write the results summary and the human-readable report."""
    os.makedirs(RESULTS_DIR, exist_ok=True)

    summary = {
        "timestamp": datetime.now().isoformat(),
        "evaluation": {
            "method": "StratifiedGroupKFold cross-validation",
            "grouped_by": "sample_id (physical plant)",
            "n_folds": n_folds,
            "scaling": "fitted inside each fold via Pipeline",
            "note": "Every score is out-of-fold. No image shares a plant with "
                    "its training data.",
        },
        "best_model": best_name,
        "majority_baseline": round(baseline, 4),
        "dataset_info": {
            "n_images": int(data["X"].shape[0]),
            "n_plants": int(data["n_plants"]),
            "num_features": int(data["X"].shape[1]),
            "classes": list(data["label_encoder"].classes_),
            "plants_per_class": data["class_plant_counts"],
        },
        "caveats": [
            "28 plants is the true sample size, not 357 images.",
            "The Moderate class has only 2 plants and cannot be validated; "
            "its per-class scores are indicative only.",
            "A previous version of this pipeline reported 100% accuracy using a "
            "random image-level split. That figure was data leakage.",
        ],
        "models": {},
    }

    for name, res in results.items():
        summary["models"][name] = {
            "accuracy": round(res["accuracy"], 4),
            "balanced_accuracy": round(res["balanced_accuracy"], 4),
            "precision": round(res["precision"], 4),
            "recall": round(res["recall"], 4),
            "f1": round(res["f1"], 4),
            "beats_baseline": res["beats_baseline"],
            "confusion_matrix": res["confusion_matrix"].tolist(),
        }

    path = os.path.join(RESULTS_DIR, "training_results.json")
    with open(path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[SAVED] Results summary -> {os.path.basename(path)}")

    reports = os.path.join(RESULTS_DIR, "classification_reports.txt")
    with open(reports, "w", encoding="utf-8") as f:
        f.write(f"Grouped cross-validation results - "
                f"{datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"{n_folds}-fold StratifiedGroupKFold, grouped by plant\n")
        f.write(f"Majority-class baseline: {baseline:.4f}\n")
        f.write(f"Best model: {best_name}\n")
        f.write("=" * 72 + "\n\n")
        for name, res in results.items():
            marker = "  * BEST" if name == best_name else ""
            f.write(f"{'-' * 56}\n{name}{marker}\n{'-' * 56}\n")
            f.write(f"Accuracy (grouped): {res['accuracy']:.4f}\n")
            f.write(f"Balanced accuracy : {res['balanced_accuracy']:.4f}\n")
            f.write(f"Weighted F1       : {res['f1']:.4f}\n")
            f.write(f"Beats baseline    : {res['beats_baseline']}\n\n")
            f.write(f"{res['classification_report']}\n\n")
    print(f"[SAVED] Classification reports -> {os.path.basename(reports)}")


def print_comparison(results: dict, best_name: str, baseline: float):
    """Model comparison table, with the baseline as a row so it cannot be missed."""
    print("\n" + "=" * 82)
    print("MODEL COMPARISON  (all figures grouped by plant, out-of-fold)")
    print("=" * 82)
    print(f"{'Model':<26}{'Accuracy':>11}{'Balanced':>11}{'F1':>10}{'vs baseline':>16}")
    print("-" * 82)

    for name, res in results.items():
        marker = " *" if name == best_name else ""
        delta = res["accuracy"] - baseline
        print(f"{name + marker:<26}{res['accuracy']:>11.4f}"
              f"{res['balanced_accuracy']:>11.4f}{res['f1']:>10.4f}"
              f"{delta:>+16.4f}")

    print("-" * 82)
    print(f"{'Majority-class baseline':<26}{baseline:>11.4f}{'':>11}{'':>10}{'':>16}")
    print("=" * 82)


def run_training(n_folds: int = DEFAULT_FOLDS):
    """Full training pipeline."""
    from preprocess import prepare_dataset

    print("[STEP] Preprocessing...")
    data = prepare_dataset()

    results, best_name, baseline = train_and_evaluate(data, n_folds)
    folds = n_usable_folds(data["y"], data["groups"], n_folds)

    print_comparison(results, best_name, baseline)
    fit_final_model(results, best_name, data)
    save_results(results, best_name, data, baseline, folds)

    best = results[best_name]
    print(f"\n[DONE] Training complete")
    print(f"   Best model        : {best_name}")
    print(f"   Grouped accuracy  : {best['accuracy']:.4f}")
    print(f"   Balanced accuracy : {best['balanced_accuracy']:.4f}")
    print(f"   Baseline          : {baseline:.4f}")

    if not best["beats_baseline"]:
        print("\n   [IMPORTANT] No model beats the majority-class baseline on unseen")
        print("   plants. Report this honestly - it is the real result, and it is")
        print("   why image-derived traits matter more than another classifier.")

    return results, best_name, data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train suitability models")
    parser.add_argument("--folds", type=int, default=DEFAULT_FOLDS)
    args = parser.parse_args()

    run_training(args.folds)
