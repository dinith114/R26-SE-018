"""
Hybrid Pollination - Model Training Script
Trains and evaluates ML models for pollination suitability prediction.

Usage:
    python src/train.py
"""

import numpy as np
import os
import sys
import joblib
import json
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import SVC
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    classification_report, confusion_matrix
)
from sklearn.model_selection import cross_val_score

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from xgboost import XGBClassifier
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False
    print("[WARN] XGBoost not installed — skipping XGBoost model")


# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, "models")
RESULTS_DIR = os.path.join(BASE_DIR, "results")


def get_models() -> dict:
    """
    Define the ML models to train and compare.
    Uses class_weight='balanced' to handle the imbalanced dataset.
    """
    models = {
        "Random Forest": RandomForestClassifier(
            n_estimators=200,
            max_depth=15,
            min_samples_split=5,
            min_samples_leaf=2,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1
        ),
        "SVM (RBF)": SVC(
            kernel="rbf",
            C=1.0,
            gamma="scale",
            class_weight="balanced",
            probability=True,
            random_state=42
        ),
        "Logistic Regression": LogisticRegression(
            max_iter=1000,
            class_weight="balanced",
            random_state=42,
        ),
    }

    if HAS_XGBOOST:
        models["XGBoost"] = XGBClassifier(
            n_estimators=200,
            max_depth=8,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            use_label_encoder=False,
            eval_metric="mlogloss"
        )

    return models


def train_and_evaluate(data: dict) -> dict:
    """
    Train all models and evaluate them.

    Args:
        data: dict from preprocess.prepare_dataset()

    Returns:
        dict with model results
    """
    X_train = data["X_train"]
    X_val = data["X_val"]
    X_test = data["X_test"]
    y_train = data["y_train"]
    y_val = data["y_val"]
    y_test = data["y_test"]
    label_encoder = data["label_encoder"]
    class_names = list(label_encoder.classes_)

    models = get_models()
    results = {}
    best_model_name = None
    best_val_accuracy = 0.0

    print("\n" + "=" * 70)
    print("MODEL TRAINING & EVALUATION")
    print("=" * 70)

    for name, model in models.items():
        print(f"\n{'─' * 50}")
        print(f"Training: {name}")
        print(f"{'─' * 50}")

        # Train
        model.fit(X_train, y_train)

        # Predict
        y_train_pred = model.predict(X_train)
        y_val_pred = model.predict(X_val)
        y_test_pred = model.predict(X_test)

        # Metrics
        train_acc = accuracy_score(y_train, y_train_pred)
        val_acc = accuracy_score(y_val, y_val_pred)
        test_acc = accuracy_score(y_test, y_test_pred)

        val_precision = precision_score(y_val, y_val_pred, average="weighted", zero_division=0)
        val_recall = recall_score(y_val, y_val_pred, average="weighted", zero_division=0)
        val_f1 = f1_score(y_val, y_val_pred, average="weighted", zero_division=0)

        test_precision = precision_score(y_test, y_test_pred, average="weighted", zero_division=0)
        test_recall = recall_score(y_test, y_test_pred, average="weighted", zero_division=0)
        test_f1 = f1_score(y_test, y_test_pred, average="weighted", zero_division=0)

        # Cross-validation on training data
        cv_scores = cross_val_score(model, X_train, y_train, cv=5, scoring="accuracy")

        # Confusion matrix
        cm = confusion_matrix(y_test, y_test_pred)

        # Classification report
        report = classification_report(y_test, y_test_pred, target_names=class_names, zero_division=0)

        print(f"  Train Accuracy:  {train_acc:.4f}")
        print(f"  Val Accuracy:    {val_acc:.4f}")
        print(f"  Test Accuracy:   {test_acc:.4f}")
        print(f"  Val F1 (weighted): {val_f1:.4f}")
        print(f"  Test F1 (weighted): {test_f1:.4f}")
        print(f"  Cross-Val (5-fold): {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")
        print(f"\n  Classification Report (Test):")
        print(f"  {report}")

        # Store results
        results[name] = {
            "model": model,
            "train_accuracy": train_acc,
            "val_accuracy": val_acc,
            "test_accuracy": test_acc,
            "val_precision": val_precision,
            "val_recall": val_recall,
            "val_f1": val_f1,
            "test_precision": test_precision,
            "test_recall": test_recall,
            "test_f1": test_f1,
            "cv_mean": cv_scores.mean(),
            "cv_std": cv_scores.std(),
            "confusion_matrix": cm,
            "classification_report": report,
            "y_test_pred": y_test_pred,
        }

        # Track best model (by validation accuracy)
        if val_acc > best_val_accuracy:
            best_val_accuracy = val_acc
            best_model_name = name

    return results, best_model_name


def save_best_model(results: dict, best_name: str, data: dict):
    """Save the best model and results summary."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    best = results[best_name]
    model = best["model"]

    # Save model
    model_path = os.path.join(MODELS_DIR, "best_model.pkl")
    joblib.dump(model, model_path)
    print(f"\n[SAVED] Best model ({best_name}) -> {model_path}")

    # Save all models
    for name, res in results.items():
        safe_name = name.lower().replace(" ", "_").replace("(", "").replace(")", "")
        model_file = os.path.join(MODELS_DIR, f"{safe_name}.pkl")
        joblib.dump(res["model"], model_file)

    # Save results summary as JSON
    summary = {
        "timestamp": datetime.now().isoformat(),
        "best_model": best_name,
        "dataset_info": {
            "train_samples": int(data["X_train"].shape[0]),
            "val_samples": int(data["X_val"].shape[0]),
            "test_samples": int(data["X_test"].shape[0]),
            "num_features": int(data["X_train"].shape[1]),
            "classes": list(data["label_encoder"].classes_),
        },
        "models": {}
    }

    for name, res in results.items():
        summary["models"][name] = {
            "train_accuracy": round(res["train_accuracy"], 4),
            "val_accuracy": round(res["val_accuracy"], 4),
            "test_accuracy": round(res["test_accuracy"], 4),
            "val_f1": round(res["val_f1"], 4),
            "test_f1": round(res["test_f1"], 4),
            "test_precision": round(res["test_precision"], 4),
            "test_recall": round(res["test_recall"], 4),
            "cv_mean": round(res["cv_mean"], 4),
            "cv_std": round(res["cv_std"], 4),
            "confusion_matrix": res["confusion_matrix"].tolist(),
        }

    results_path = os.path.join(RESULTS_DIR, "training_results.json")
    with open(results_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"[SAVED] Results summary -> {results_path}")

    # Save classification reports
    reports_path = os.path.join(RESULTS_DIR, "classification_reports.txt")
    with open(reports_path, "w", encoding="utf-8") as f:
        f.write(f"Training Results - {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"Best Model: {best_name}\n")
        f.write("=" * 70 + "\n\n")
        for name, res in results.items():
            marker = " * BEST" if name == best_name else ""
            f.write(f"{'-' * 50}\n")
            f.write(f"{name}{marker}\n")
            f.write(f"{'-' * 50}\n")
            f.write(f"Train Accuracy: {res['train_accuracy']:.4f}\n")
            f.write(f"Val Accuracy:   {res['val_accuracy']:.4f}\n")
            f.write(f"Test Accuracy:  {res['test_accuracy']:.4f}\n")
            f.write(f"Test F1:        {res['test_f1']:.4f}\n")
            f.write(f"CV (5-fold):    {res['cv_mean']:.4f} +/- {res['cv_std']:.4f}\n\n")
            f.write(f"Classification Report:\n{res['classification_report']}\n\n")
    print(f"[SAVED] Classification reports -> {reports_path}")


def print_comparison_table(results: dict, best_name: str):
    """Print a formatted model comparison table."""
    print("\n" + "=" * 90)
    print("MODEL COMPARISON")
    print("=" * 90)
    print(f"{'Model':<25} {'Train Acc':>10} {'Val Acc':>10} {'Test Acc':>10} {'Test F1':>10} {'CV Mean':>10}")
    print("─" * 90)

    for name, res in results.items():
        marker = " *" if name == best_name else ""
        print(
            f"{name + marker:<25} "
            f"{res['train_accuracy']:>10.4f} "
            f"{res['val_accuracy']:>10.4f} "
            f"{res['test_accuracy']:>10.4f} "
            f"{res['test_f1']:>10.4f} "
            f"{res['cv_mean']:>10.4f}"
        )
    print("=" * 90)


def run_training():
    """Full training pipeline."""
    from preprocess import prepare_dataset

    # Preprocess
    print("🔄 Starting preprocessing...")
    data = prepare_dataset()

    # Train & evaluate
    print("\n🔄 Starting model training...")
    results, best_name = train_and_evaluate(data)

    # Print comparison
    print_comparison_table(results, best_name)

    # Save
    save_best_model(results, best_name, data)

    print(f"\n✅ Training complete!")
    print(f"   Best model: {best_name}")
    print(f"   Val accuracy: {results[best_name]['val_accuracy']:.4f}")
    print(f"   Test accuracy: {results[best_name]['test_accuracy']:.4f}")

    return results, best_name, data


if __name__ == "__main__":
    results, best_name, data = run_training()
