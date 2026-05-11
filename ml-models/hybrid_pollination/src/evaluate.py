"""
Hybrid Pollination - Evaluation & Visualization Module
Generates presentation-quality charts: confusion matrix, feature importance, model comparison.

Usage:
    python src/evaluate.py
"""

import numpy as np
import os
import sys
import json
import joblib
import matplotlib
matplotlib.use("Agg")  # Non-interactive backend
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.metrics import confusion_matrix, ConfusionMatrixDisplay

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, "models")
RESULTS_DIR = os.path.join(BASE_DIR, "results")


def setup_plot_style():
    """Set consistent plot styling."""
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams.update({
        "figure.figsize": (10, 7),
        "font.size": 12,
        "axes.titlesize": 14,
        "axes.labelsize": 12,
    })


def plot_confusion_matrix(results: dict, class_names: list, save_dir: str):
    """Generate confusion matrix heatmap for each model."""
    for name, res in results.items():
        cm = np.array(res["confusion_matrix"]) if isinstance(res["confusion_matrix"], list) else res["confusion_matrix"]

        fig, ax = plt.subplots(figsize=(8, 6))
        sns.heatmap(
            cm, annot=True, fmt="d", cmap="Greens",
            xticklabels=class_names, yticklabels=class_names,
            ax=ax, linewidths=0.5, linecolor="white"
        )
        ax.set_xlabel("Predicted Label")
        ax.set_ylabel("True Label")
        ax.set_title(f"Confusion Matrix — {name}")
        plt.tight_layout()

        safe_name = name.lower().replace(" ", "_").replace("(", "").replace(")", "")
        path = os.path.join(save_dir, f"confusion_matrix_{safe_name}.png")
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"  [SAVED] {os.path.basename(path)}")


def plot_model_comparison(results: dict, save_dir: str):
    """Generate model accuracy comparison bar chart."""
    models = list(results.keys())
    train_acc = [results[m]["train_accuracy"] for m in models]
    val_acc = [results[m]["val_accuracy"] for m in models]
    test_acc = [results[m]["test_accuracy"] for m in models]

    x = np.arange(len(models))
    width = 0.25

    fig, ax = plt.subplots(figsize=(12, 7))
    bars1 = ax.bar(x - width, train_acc, width, label="Train", color="#2d6a4f", alpha=0.85)
    bars2 = ax.bar(x, val_acc, width, label="Validation", color="#52b788", alpha=0.85)
    bars3 = ax.bar(x + width, test_acc, width, label="Test", color="#95d5b2", alpha=0.85)

    # Add value labels on bars
    for bars in [bars1, bars2, bars3]:
        for bar in bars:
            height = bar.get_height()
            ax.annotate(f"{height:.2f}",
                        xy=(bar.get_x() + bar.get_width() / 2, height),
                        xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=10)

    ax.set_xlabel("Model")
    ax.set_ylabel("Accuracy")
    ax.set_title("Model Accuracy Comparison")
    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=15, ha="right")
    ax.legend(loc="lower right")
    ax.set_ylim(0, 1.1)

    plt.tight_layout()
    path = os.path.join(save_dir, "model_comparison.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [SAVED] model_comparison.png")


def plot_metrics_comparison(results: dict, save_dir: str):
    """Generate precision/recall/F1 comparison chart."""
    models = list(results.keys())
    precision = [results[m]["test_precision"] for m in models]
    recall = [results[m]["test_recall"] for m in models]
    f1 = [results[m]["test_f1"] for m in models]

    x = np.arange(len(models))
    width = 0.25

    fig, ax = plt.subplots(figsize=(12, 7))
    ax.bar(x - width, precision, width, label="Precision", color="#40916c")
    ax.bar(x, recall, width, label="Recall", color="#74c69d")
    ax.bar(x + width, f1, width, label="F1 Score", color="#b7e4c7")

    ax.set_xlabel("Model")
    ax.set_ylabel("Score")
    ax.set_title("Test Set — Precision / Recall / F1 Comparison")
    ax.set_xticks(x)
    ax.set_xticklabels(models, rotation=15, ha="right")
    ax.legend()
    ax.set_ylim(0, 1.1)

    plt.tight_layout()
    path = os.path.join(save_dir, "metrics_comparison.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [SAVED] metrics_comparison.png")


def plot_feature_importance(model, feature_names: list, save_dir: str, top_n: int = 20):
    """Plot top feature importance from tree-based model."""
    if not hasattr(model, "feature_importances_"):
        print("  [SKIP] Model does not have feature importances")
        return

    importances = model.feature_importances_
    indices = np.argsort(importances)[::-1][:top_n]

    fig, ax = plt.subplots(figsize=(10, 8))
    top_features = [feature_names[i] for i in indices]
    top_importances = importances[indices]

    colors = plt.cm.Greens(np.linspace(0.3, 0.9, len(top_features)))[::-1]
    ax.barh(range(len(top_features)), top_importances[::-1], color=colors)
    ax.set_yticks(range(len(top_features)))
    ax.set_yticklabels(top_features[::-1])
    ax.set_xlabel("Importance")
    ax.set_title(f"Top {top_n} Feature Importances (Best Model)")

    plt.tight_layout()
    path = os.path.join(save_dir, "feature_importance.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [SAVED] feature_importance.png")


def plot_cv_scores(results: dict, save_dir: str):
    """Plot cross-validation scores comparison."""
    models = list(results.keys())
    cv_means = [results[m]["cv_mean"] for m in models]
    cv_stds = [results[m]["cv_std"] for m in models]

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.bar(models, cv_means, yerr=cv_stds, capsize=5,
                  color=["#2d6a4f", "#40916c", "#52b788", "#74c69d"][:len(models)],
                  edgecolor="white", linewidth=1.5)

    for bar, mean in zip(bars, cv_means):
        ax.annotate(f"{mean:.3f}",
                    xy=(bar.get_x() + bar.get_width() / 2, bar.get_height()),
                    xytext=(0, 5), textcoords="offset points",
                    ha="center", fontsize=11, fontweight="bold")

    ax.set_ylabel("Accuracy")
    ax.set_title("5-Fold Cross-Validation Accuracy")
    ax.set_ylim(0, 1.1)

    plt.tight_layout()
    path = os.path.join(save_dir, "cross_validation.png")
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [SAVED] cross_validation.png")


def generate_all_charts(results_json_path: str = None, feature_names: list = None):
    """Generate all evaluation charts from saved results."""
    setup_plot_style()
    os.makedirs(RESULTS_DIR, exist_ok=True)

    # Load results
    if results_json_path is None:
        results_json_path = os.path.join(RESULTS_DIR, "training_results.json")

    with open(results_json_path, "r") as f:
        summary = json.load(f)

    results = summary["models"]
    class_names = summary["dataset_info"]["classes"]
    best_name = summary["best_model"]

    print("\n" + "=" * 50)
    print("GENERATING EVALUATION CHARTS")
    print("=" * 50)

    # 1. Confusion matrices
    print("\n[1/5] Confusion matrices...")
    plot_confusion_matrix(results, class_names, RESULTS_DIR)

    # 2. Model comparison
    print("\n[2/5] Model accuracy comparison...")
    plot_model_comparison(results, RESULTS_DIR)

    # 3. Metrics comparison
    print("\n[3/5] Precision/Recall/F1 comparison...")
    plot_metrics_comparison(results, RESULTS_DIR)

    # 4. Cross-validation
    print("\n[4/5] Cross-validation chart...")
    plot_cv_scores(results, RESULTS_DIR)

    # 5. Feature importance (from best model)
    print("\n[5/5] Feature importance...")
    best_model_path = os.path.join(MODELS_DIR, "best_model.pkl")
    if os.path.exists(best_model_path):
        model = joblib.load(best_model_path)
        if feature_names is None:
            preprocessors = joblib.load(os.path.join(MODELS_DIR, "preprocessors.pkl"))
            feature_names = preprocessors["feature_names"]
        plot_feature_importance(model, feature_names, RESULTS_DIR)
    else:
        print("  [SKIP] Best model file not found")

    print(f"\n✅ All charts saved to: {RESULTS_DIR}")


if __name__ == "__main__":
    generate_all_charts()
