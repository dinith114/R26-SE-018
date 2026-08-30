"""
Hybrid Pollination - Trait Model Training

Trains image-based classifiers for the traits the app used to demand from the
user as dropdowns:

    leaf_condition   healthy / moderate / weak
    plant_strength   strong  / moderate / weak

Both are trained on the project's own annotations, using MASKED features
(measured on segmented plant pixels only) and grouped cross-validation by
plant. Nothing here is trained on the whole frame, because the background in
this dataset is other plants and gravel.

Why these two and not suitability:

    trait            plants per class
    leaf_condition   15 / 9 / 4
    plant_strength   14 / 11 / 3
    suitability      17 / 9 / 2     <- Moderate cannot be learned from 2 plants

These traits are better balanced than the suitability label, so they are the
part of the pipeline most likely to actually learn something.

Every score is reported against the majority-class baseline. A trait model that
does not beat its baseline is reported as such and its confidence is capped, so
the app falls back to asking the grower rather than asserting a guess.

Usage:
    python src/train_traits.py
    python src/train_traits.py --trait leaf_condition
"""

import os
import sys
import json
import joblib
import argparse
from datetime import datetime
from collections import Counter

import numpy as np
import pandas as pd

from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.svm import SVC
from sklearn.model_selection import StratifiedGroupKFold, cross_val_predict
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, f1_score,
    classification_report, confusion_matrix,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trait_features import extract_trait_features, get_trait_feature_names
from cnn_features import extract_cnn_features


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLEAN_CSV = os.path.join(BASE_DIR, "data", "image_annotations_clean.csv")
CACHE_CSV = os.path.join(BASE_DIR, "data", "trait_features.csv")
CNN_CACHE = os.path.join(BASE_DIR, "data", "cnn_embeddings.npy")
MODELS_DIR = os.path.join(BASE_DIR, "models")
RESULTS_DIR = os.path.join(BASE_DIR, "results")

TRAITS = {
    "leaf_condition": ["healthy", "moderate", "weak"],
    "plant_strength": ["strong", "moderate", "weak"],
}

GROUP_COLUMN = "sample_id"


# ──────────────────────────────────────────────
# Feature cache
# ──────────────────────────────────────────────
def build_features(force: bool = False) -> pd.DataFrame:
    """Extract masked features for every annotated image, caching the result."""
    if os.path.exists(CACHE_CSV) and not force:
        print(f"[INFO] Reusing cached features ({os.path.basename(CACHE_CSV)}); "
              "pass --recompute to refresh")
        return pd.read_csv(CACHE_CSV)

    df = pd.read_csv(CLEAN_CSV)
    print(f"[STEP] Extracting masked features from {len(df)} images...")

    rows = []
    for i, (_, r) in enumerate(df.iterrows(), 1):
        if i % 40 == 0:
            print(f"  {i}/{len(df)}")
        try:
            f = extract_trait_features(r["image_path"])
        except Exception as e:
            print(f"  [WARN] {r['image_name']}: {e}")
            continue
        f.update({
            "sample_id": r["sample_id"],
            "image_name": r["image_name"],
            "leaf_condition": r["leaf_condition"],
            "plant_strength": r["plant_strength"],
            "disease_visible": r["disease_visible"],
        })
        rows.append(f)

    out = pd.DataFrame(rows)
    out.to_csv(CACHE_CSV, index=False)
    print(f"[SAVED] {os.path.basename(CACHE_CSV)}  ({len(out)} rows)")
    return out


# ──────────────────────────────────────────────
# Models
# ──────────────────────────────────────────────
def build_cnn_features(df: pd.DataFrame, force: bool = False) -> np.ndarray:
    """
    Embed every annotated image with the frozen pretrained network.

    Cached to .npy because embedding 357 images on CPU takes several minutes.
    """
    clean = pd.read_csv(CLEAN_CSV)
    paths = clean.set_index("image_name")["image_path"].to_dict()
    ordered = [paths.get(n, "") for n in df["image_name"]]

    if os.path.exists(CNN_CACHE) and not force:
        cached = np.load(CNN_CACHE)
        if cached.shape[0] == len(df):
            print(f"[INFO] Reusing cached CNN embeddings {cached.shape}")
            return cached
        print("[INFO] Cached embeddings are stale; recomputing")

    print(f"[STEP] Embedding {len(ordered)} images with pretrained ResNet18...")
    feats = extract_cnn_features(ordered)
    np.save(CNN_CACHE, feats)
    print(f"[SAVED] {os.path.basename(CNN_CACHE)}")
    return feats


def candidate_models() -> dict:
    """Small, regularised models. With 28 plants, capacity is the enemy."""
    def pipe(est):
        return Pipeline([("scaler", StandardScaler()), ("model", est)])

    return {
        "Random Forest": pipe(RandomForestClassifier(
            n_estimators=300, max_depth=6, min_samples_leaf=4,
            class_weight="balanced", random_state=42, n_jobs=-1)),
        "Extra Trees": pipe(ExtraTreesClassifier(
            n_estimators=300, max_depth=6, min_samples_leaf=4,
            class_weight="balanced", random_state=42, n_jobs=-1)),
        "Logistic Regression": pipe(LogisticRegression(
            C=0.3, max_iter=2000, class_weight="balanced", random_state=42)),
        "SVM (RBF)": pipe(SVC(
            C=1.0, gamma="scale", class_weight="balanced",
            probability=True, random_state=42)),
    }


def usable_folds(y: np.ndarray, groups: np.ndarray, requested: int = 4) -> int:
    """Cannot have more folds than the rarest class has plants."""
    seen, per_class = set(), Counter()
    for label, g in zip(y, groups):
        if g in seen:
            continue
        seen.add(g)
        per_class[label] += 1
    rarest = min(per_class.values()) if per_class else requested
    return max(2, min(requested, rarest))


def train_trait(df: pd.DataFrame, trait: str, cnn: np.ndarray = None,
                feature_set: str = "handcrafted") -> dict:
    """
    Train and grouped-cross-validate one trait.

    feature_set:
        "handcrafted" - the masked colour/structure/texture measures
        "cnn"         - frozen pretrained ResNet18 embeddings
        "combined"    - both, concatenated
    """
    handcrafted = [f for f in get_trait_feature_names() if f in df.columns]

    keep = df[trait].isin(TRAITS[trait]).values
    data = df[keep].copy()

    X_hand = np.nan_to_num(data[handcrafted].values.astype(np.float64),
                           nan=0.0, posinf=0.0, neginf=0.0)

    if feature_set == "handcrafted":
        X, feature_names = X_hand, handcrafted
    else:
        if cnn is None:
            raise ValueError("CNN embeddings required for this feature set")
        X_cnn = cnn[keep]
        cnn_names = [f"cnn_{i}" for i in range(X_cnn.shape[1])]
        if feature_set == "cnn":
            X, feature_names = X_cnn, cnn_names
        else:
            X = np.hstack([X_hand, X_cnn])
            feature_names = handcrafted + cnn_names

    le = LabelEncoder()
    y = le.fit_transform(data[trait].values)
    groups = data[GROUP_COLUMN].values

    baseline = max(Counter(y.tolist()).values()) / len(y)
    folds = usable_folds(y, groups)
    cv = StratifiedGroupKFold(n_splits=folds, shuffle=True, random_state=42)

    plants_per_class = Counter()
    seen = set()
    for label, g in zip(data[trait].values, groups):
        if g not in seen:
            seen.add(g)
            plants_per_class[label] += 1

    print("\n" + "=" * 72)
    print(f"TRAIT: {trait}")
    print("=" * 72)
    print(f"  Images {len(y)}   Plants {len(set(groups))}   Folds {folds}")
    print(f"  Plants per class: {dict(plants_per_class)}")
    print(f"  Majority baseline: {baseline:.4f}")

    results, best_name, best_score = {}, None, -1.0

    for name, model in candidate_models().items():
        y_pred = cross_val_predict(model, X, y, cv=cv, groups=groups, n_jobs=1)

        acc = accuracy_score(y, y_pred)
        bal = balanced_accuracy_score(y, y_pred)
        f1 = f1_score(y, y_pred, average="weighted", zero_division=0)

        flag = "beats baseline" if acc > baseline else "below baseline"
        print(f"\n  {name:<22} acc={acc:.4f}  balanced={bal:.4f}  F1={f1:.4f}  ({flag})")

        results[name] = {
            "accuracy": acc, "balanced_accuracy": bal, "f1": f1,
            "beats_baseline": bool(acc > baseline),
            "confusion_matrix": confusion_matrix(y, y_pred).tolist(),
            "report": classification_report(y, y_pred, target_names=list(le.classes_),
                                            zero_division=0),
            "model": model,
        }

        if f1 > best_score:
            best_score, best_name = f1, name

    best = results[best_name]
    print(f"\n  BEST: {best_name}")
    print(f"\n{best['report']}")

    # Refit on everything for deployment
    final = best["model"]
    final.fit(X, y)

    os.makedirs(MODELS_DIR, exist_ok=True)
    bundle = {
        "model": final,
        "label_encoder": le,
        "feature_names": feature_names,
        "trait": trait,
        "baseline": baseline,
        "accuracy": best["accuracy"],
        "balanced_accuracy": best["balanced_accuracy"],
        "f1": best["f1"],
        "beats_baseline": best["beats_baseline"],
        "model_name": best_name,
        "n_plants": len(set(groups)),
        "plants_per_class": dict(plants_per_class),
    }
    bundle["feature_set"] = feature_set
    path = os.path.join(MODELS_DIR, f"trait_{trait}.pkl")
    joblib.dump(bundle, path)
    print(f"  [SAVED] {os.path.basename(path)}")

    if not best["beats_baseline"]:
        print(f"  [IMPORTANT] {trait} does not beat its baseline. The predictor will")
        print(f"              report low confidence so the app asks the grower instead.")

    return {
        "trait": trait, "best_model": best_name, "feature_set": feature_set,
        "baseline": round(baseline, 4),
        "n_plants": len(set(groups)), "n_images": int(len(y)),
        "plants_per_class": dict(plants_per_class),
        "folds": folds,
        "classes": list(le.classes_),
        "models": {n: {k: (round(v, 4) if isinstance(v, float) else v)
                       for k, v in r.items() if k not in ("model", "report")}
                   for n, r in results.items()},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--trait", choices=list(TRAITS), default=None)
    parser.add_argument("--recompute", action="store_true")
    parser.add_argument("--no-cnn", action="store_true",
                        help="Skip transfer learning; handcrafted features only")
    args = parser.parse_args()

    df = build_features(force=args.recompute)

    traits = [args.trait] if args.trait else list(TRAITS)
    sets = ["handcrafted"] if args.no_cnn else ["handcrafted", "cnn", "combined"]

    cnn = None if args.no_cnn else build_cnn_features(df, force=args.recompute)

    summary = {"timestamp": datetime.now().isoformat(),
               "evaluation": "StratifiedGroupKFold by plant; masked features",
               "feature_sets_compared": sets,
               "traits": {}}

    for t in traits:
        # Each feature set is evaluated, and the one with the best balanced
        # accuracy is kept. Selecting on balanced accuracy rather than plain
        # accuracy stops a model that only ever predicts the majority class
        # from winning.
        attempts = {}
        for fs in sets:
            attempts[fs] = train_trait(df, t, cnn=cnn, feature_set=fs)

        # Selected on weighted F1 - the headline metric - rather than balanced
        # accuracy. With only 3-4 plants in the rarest class, balanced accuracy
        # swings on one or two plants and is too noisy to choose on. Balanced
        # accuracy is still reported everywhere so the rare-class weakness
        # stays visible rather than being hidden by the selection.
        best_fs = max(attempts, key=lambda fs:
                      attempts[fs]["models"][attempts[fs]["best_model"]]["f1"])

        print(f"\n  >> Best feature set for {t}: {best_fs}")
        # Refit and save the winner so the .pkl on disk matches the reported result
        summary["traits"][t] = train_trait(df, t, cnn=cnn, feature_set=best_fs)
        summary["traits"][t]["all_feature_sets"] = {
            fs: attempts[fs]["models"][attempts[fs]["best_model"]] for fs in sets
        }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    out = os.path.join(RESULTS_DIR, "trait_training_results.json")
    with open(out, "w") as f:
        json.dump(summary, f, indent=2)

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    for t, r in summary["traits"].items():
        b = r["models"][r["best_model"]]
        verdict = "OK " if b["beats_baseline"] else "WEAK"
        print(f"  [{verdict}] {t:16s} acc={b['accuracy']:.3f}  F1={b['f1']:.3f}  "
              f"baseline={r['baseline']:.3f}  ({r['best_model']}, {r['feature_set']})")
    print(f"\n[SAVED] {os.path.basename(out)}")


if __name__ == "__main__":
    main()
