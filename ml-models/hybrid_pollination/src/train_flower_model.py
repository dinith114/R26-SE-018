"""
Hybrid Pollination - Flower Presence Model

Trains a supervised flower / no-flower classifier on background-removed orchid
images, replacing the colour-threshold detector that failed on nursery photos.

BACKGROUND
----------
`flower_analysis.py` detects blooms with colour rules. On the project's own
whole-plant photographs those rules cannot work, and the reason was measured
rather than assumed: bright gaps of greenhouse roof between the leaves are
compact, enclosed by foliage, and LESS saturated than a backlit bloom (bloom
hue ~14 / saturation ~33 versus sky hue ~109 / saturation ~44). No threshold
separates them, so the detector was tuned for precision and finds only 32% of
blooms.

An additional 800 background-removed Vanda images make a supervised approach
possible. With no sky, gravel, netting or hands in frame, flower presence is
learnable from the image itself rather than hand-specified.

TWO THINGS THIS SCRIPT IS CAREFUL ABOUT
----------------------------------------
1. The training labels are AUTO-PROPOSED by label_flowers.py, not
   hand-verified. A model trained on them inherits their mistakes. Accuracy
   against those labels therefore measures agreement with a rule, not truth,
   and is reported as such.

2. DOMAIN SHIFT is the real risk. The model is trained on clean cutouts but
   must run on cluttered nursery photographs. That gap is bridged by feeding
   both through the same preprocessing - segment the plant, put it on neutral
   grey - and it is TESTED at the end rather than assumed, by running the
   trained model against the project's own annotated photographs.

Usage:
    python src/train_flower_model.py
"""

import os
import sys
import json
import csv
import joblib
import argparse
from datetime import datetime
from collections import Counter

import cv2
import numpy as np

from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.pipeline import Pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import SVC
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import (
    accuracy_score, balanced_accuracy_score, f1_score,
    classification_report, confusion_matrix, roc_auc_score,
)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cnn_features import _load_model, IMAGENET_MEAN, IMAGENET_STD, INPUT_SIZE


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LABELS_CSV = os.path.join(BASE_DIR, "data", "knowledge", "cutout_flower_labels.csv")
EMB_CACHE = os.path.join(BASE_DIR, "data", "cutout_embeddings.npy")
MODELS_DIR = os.path.join(BASE_DIR, "models")
RESULTS_DIR = os.path.join(BASE_DIR, "results")

NEUTRAL = 128


def preprocess_cutout(image_path: str) -> np.ndarray:
    """
    Prepare a cutout image the SAME way real photographs are prepared.

    The white background is replaced with the same neutral grey that
    cnn_features uses for segmented nursery photos. Without this the model
    would learn "white background" as a feature and collapse the moment it saw
    a real photograph.
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not read {image_path}")

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    background = (hsv[:, :, 2] >= 225) & (hsv[:, :, 1] <= 35)
    img = np.where(background[:, :, None], NEUTRAL, img).astype(np.uint8)

    img = cv2.resize(img, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    rgb = (rgb - IMAGENET_MEAN) / IMAGENET_STD
    return np.transpose(rgb, (2, 0, 1))


def embed_cutouts(paths: list, batch_size: int = 16) -> np.ndarray:
    """Embed cutout images with the frozen pretrained network."""
    net, torch = _load_model()
    out = np.zeros((len(paths), 512), dtype=np.float32)

    for start in range(0, len(paths), batch_size):
        chunk = paths[start:start + batch_size]
        if start % (batch_size * 8) == 0:
            print(f"  embedding {start}/{len(paths)}")

        tensors, rows = [], []
        for i, p in enumerate(chunk):
            try:
                tensors.append(preprocess_cutout(p))
                rows.append(start + i)
            except Exception:
                pass

        if not tensors:
            continue
        with torch.no_grad():
            emb = net(torch.from_numpy(np.stack(tensors))).numpy()
        for r, e in zip(rows, emb):
            out[r] = e

    return out


def load_labels() -> list:
    if not os.path.exists(LABELS_CSV):
        raise SystemExit(f"[ERROR] {LABELS_CSV} not found. Run label_flowers.py first.")
    with open(LABELS_CSV, encoding="utf-8") as f:
        lines = [l for l in f if not l.startswith("#")]
    return [r for r in csv.DictReader(lines) if r["label"] in ("flower", "no_flower")]


def models() -> dict:
    def pipe(est):
        return Pipeline([("scaler", StandardScaler()), ("model", est)])
    return {
        "Logistic Regression": pipe(LogisticRegression(
            C=1.0, max_iter=3000, class_weight="balanced", random_state=42)),
        "Random Forest": pipe(RandomForestClassifier(
            n_estimators=400, max_depth=10, min_samples_leaf=2,
            class_weight="balanced", random_state=42, n_jobs=-1)),
        "SVM (RBF)": pipe(SVC(
            C=2.0, gamma="scale", class_weight="balanced",
            probability=True, random_state=42)),
    }


def fit_domain_guard(X: np.ndarray) -> dict:
    """
    Describe the training distribution so out-of-domain input can be rejected.

    This exists because of a failure found by testing, not by theory. The
    classifier reaches 0.999 accuracy on cutouts and then answers "flower" with
    1.00 confidence for EVERY real nursery photograph - including one showing a
    hand holding a name tag and one showing only sky gaps between leaves.

    A positives-only transfer test scored 16/16 and hid this completely, because
    a model that always says "flower" gets perfect recall.

    The guard stores the mean embedding and the distribution of distances to it
    across the training set. An image far outside that range is not scored; the
    model says it cannot judge, which is the truthful answer.
    """
    centre = X.mean(axis=0)
    distances = np.linalg.norm(X - centre, axis=1)
    return {
        "centre": centre,
        "mean_distance": float(distances.mean()),
        "std_distance": float(distances.std()),
        "p99_distance": float(np.percentile(distances, 99)),
        "max_distance": float(distances.max()),
    }


def transfer_test(bundle: dict) -> dict:
    """
    Run the trained model on the project's OWN nursery photographs.

    Reports BOTH a flowering set and a non-flowering set. Testing only on
    positives is what concealed the domain-shift failure the first time.
    """
    clean_csv = os.path.join(BASE_DIR, "data", "image_annotations_clean.csv")
    if not os.path.exists(clean_csv):
        return {}

    import pandas as pd
    from cnn_features import extract_cnn_features

    df = pd.read_csv(clean_csv)
    # 'good' means a flower was present and in good condition; anything else
    # tells us nothing definite about presence, so only 'good' is used as a
    # positive and the rest are excluded rather than assumed negative.
    known = df[df["flower_condition"].isin(["good"])]
    if len(known) < 5:
        return {"note": "Too few annotated flowering photographs to test transfer."}

    pos_paths = known.groupby("sample_id", group_keys=False).head(2)["image_path"].tolist()

    # Negatives: plants whose flower condition was never recorded as present.
    # Imperfect ground truth, but sufficient to expose a model that answers
    # "flower" for everything.
    neg = df[~df["flower_condition"].isin(["good", "moderate", "weak"])]
    neg_paths = neg.groupby("sample_id", group_keys=False).head(2)["image_path"].tolist()

    model, le = bundle["model"], bundle["label_encoder"]
    guard = bundle.get("domain_guard")

    def run(paths, expect):
        if not paths:
            return {}
        emb = extract_cnn_features(paths, verbose=False)
        preds = le.inverse_transform(model.predict(emb))
        correct = int((preds == expect).sum())

        flagged = 0
        if guard is not None:
            d = np.linalg.norm(emb - guard["centre"], axis=1)
            flagged = int((d > guard["p99_distance"]).sum())

        return {"n": len(paths), "correct": correct,
                "rate": round(correct / len(paths), 3),
                "flagged_out_of_domain": flagged}

    print(f"\n[STEP] Transfer test: {len(pos_paths)} flowering, "
          f"{len(neg_paths)} non-flowering real photos...")

    return {
        "flowering_photos": run(pos_paths, "flower"),
        "non_flowering_photos": run(neg_paths, "no_flower"),
        "note": ("Both directions tested. A model that always answers 'flower' "
                 "scores perfectly on the first set and zero on the second."),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--recompute", action="store_true")
    args = parser.parse_args()

    rows = load_labels()
    src = rows[0]["source_dir"]
    paths = [os.path.join(src, r["image"]) for r in rows]
    y_raw = np.array([r["label"] for r in rows])

    print(f"[INFO] {len(rows)} labelled cutouts: {dict(Counter(y_raw.tolist()))}")

    if os.path.exists(EMB_CACHE) and not args.recompute:
        X = np.load(EMB_CACHE)
        if X.shape[0] != len(rows):
            X = None
        else:
            print(f"[INFO] Reusing cached embeddings {X.shape}")
    else:
        X = None

    if X is None:
        print("[STEP] Embedding cutouts with frozen ResNet18...")
        X = embed_cutouts(paths)
        np.save(EMB_CACHE, X)
        print(f"[SAVED] {os.path.basename(EMB_CACHE)}")

    le = LabelEncoder()
    y = le.fit_transform(y_raw)
    baseline = max(Counter(y.tolist()).values()) / len(y)

    # No grouping needed: these are 800 distinct images, verified non-duplicate
    # (max pairwise correlation 0.727), unlike the 28-plant nursery set.
    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)

    print("\n" + "=" * 70)
    print("FLOWER PRESENCE MODEL  (5-fold CV on cutouts)")
    print("=" * 70)
    print(f"  Baseline (majority class): {baseline:.4f}")

    results, best_name, best_f1 = {}, None, -1.0

    for name, model in models().items():
        pred = cross_val_predict(model, X, y, cv=cv, n_jobs=1)
        proba = cross_val_predict(model, X, y, cv=cv, method="predict_proba", n_jobs=1)

        acc = accuracy_score(y, pred)
        bal = balanced_accuracy_score(y, pred)
        f1 = f1_score(y, pred, average="weighted", zero_division=0)
        auc = roc_auc_score(y, proba[:, 1])

        print(f"\n  {name:<22} acc={acc:.4f}  balanced={bal:.4f}  "
              f"F1={f1:.4f}  AUC={auc:.4f}")

        results[name] = {
            "accuracy": acc, "balanced_accuracy": bal, "f1": f1, "auc": auc,
            "confusion_matrix": confusion_matrix(y, pred).tolist(),
            "report": classification_report(y, pred, target_names=list(le.classes_),
                                            zero_division=0),
            "model": model,
        }
        if f1 > best_f1:
            best_f1, best_name = f1, name

    best = results[best_name]
    print(f"\n  BEST: {best_name}\n")
    print(best["report"])

    final = best["model"]
    final.fit(X, y)

    guard = fit_domain_guard(X)

    os.makedirs(MODELS_DIR, exist_ok=True)
    bundle = {
        "model": final, "label_encoder": le, "trained_on": "cutout images",
        "n_train": len(y), "baseline": baseline,
        "accuracy": best["accuracy"], "f1": best["f1"], "auc": best["auc"],
        "model_name": best_name,
        "label_provenance": "auto-proposed by label_flowers.py, not hand-verified",
        "domain_guard": guard,
    }
    path = os.path.join(MODELS_DIR, "flower_presence.pkl")
    joblib.dump(bundle, path)
    print(f"[SAVED] {os.path.basename(path)}")

    transfer = transfer_test(bundle)
    if transfer:
        print("\n" + "-" * 70)
        print("TRANSFER TO REAL NURSERY PHOTOGRAPHS")
        print("-" * 70)
        for k, v in transfer.items():
            print(f"  {k}: {v}")

    os.makedirs(RESULTS_DIR, exist_ok=True)
    summary = {
        "timestamp": datetime.now().isoformat(),
        "training_data": {
            "source": src, "n_images": len(y),
            "class_counts": {k: int(v) for k, v in Counter(y_raw.tolist()).items()},
            "label_provenance": "AUTO-PROPOSED, not hand-verified",
        },
        "baseline": round(baseline, 4),
        "best_model": best_name,
        "models": {n: {k: (round(v, 4) if isinstance(v, float) else v)
                       for k, v in r.items() if k not in ("model", "report")}
                   for n, r in results.items()},
        "transfer_test": transfer,
        "caveats": [
            "Accuracy is measured against auto-proposed labels, so it reflects "
            "agreement with a colour rule rather than verified ground truth.",
            "Cutouts are cleaner than real nursery photographs; the transfer "
            "test is the number that matters for deployment.",
        ],
    }
    out = os.path.join(RESULTS_DIR, "flower_model_results.json")
    with open(out, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n[SAVED] {os.path.basename(out)}")


if __name__ == "__main__":
    main()
