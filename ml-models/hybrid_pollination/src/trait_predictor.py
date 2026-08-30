"""
Hybrid Pollination - Trait Prediction at Inference Time

Loads the trained leaf_condition and plant_strength models and predicts them
from a single image, so the app no longer has to ask the grower.

Confidence is reported honestly and is capped by how well the model actually
performed in grouped cross-validation. A model that barely beats its baseline
cannot be allowed to assert an answer with 90% confidence just because its
softmax happens to be peaked - the softmax describes the model's internal
certainty, not its accuracy on an unseen plant.

Measured performance (grouped by plant, see results/trait_training_results.json):

    leaf_condition   accuracy 0.633   F1 0.611   baseline 0.501
    plant_strength   accuracy 0.683   F1 0.663   baseline 0.546

Both beat their baselines, but neither is strong. The `weak` class in
particular is barely learnable - there are only 3-4 weak plants in the whole
dataset - so a `weak` prediction is flagged as low confidence regardless of
what the model reports.
"""

import os
import sys

import numpy as np
import joblib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from trait_features import extract_trait_features, get_trait_feature_names


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, "models")

# Classes with too few training plants to be trusted, per trait
UNDER_SUPPORTED = {
    "leaf_condition": {"weak"},      # 4 plants
    "plant_strength": {"weak"},      # 3 plants
}


class TraitPredictor:
    """Predicts leaf condition and plant strength from one plant image."""

    def __init__(self, models_dir: str = MODELS_DIR):
        self.models_dir = models_dir
        self.bundles = {}
        self._load()

    def _load(self):
        for trait in ("leaf_condition", "plant_strength"):
            path = os.path.join(self.models_dir, f"trait_{trait}.pkl")
            if not os.path.exists(path):
                print(f"[WARN] Trait model missing: {os.path.basename(path)} "
                      f"- run train_traits.py")
                continue
            try:
                self.bundles[trait] = joblib.load(path)
            except Exception as e:
                print(f"[ERROR] Could not load {trait} model: {e}")

    def available(self) -> list:
        return sorted(self.bundles)

    def predict(self, image_path: str, trait: str,
                precomputed: dict = None) -> dict:
        """
        Predict one trait from an image.

        Args:
            image_path:  Plant image
            trait:       "leaf_condition" or "plant_strength"
            precomputed: Handcrafted features already extracted for this image,
                         so that predicting both traits does not segment twice

        Returns:
            dict with value, confidence, probabilities, explanation, model_info
        """
        bundle = self.bundles.get(trait)
        if bundle is None:
            return {
                "value": "unknown", "confidence": 0.0, "probabilities": {},
                "explanation": f"No trained model available for {trait}.",
                "model_info": {},
            }

        X = self._build_vector(image_path, bundle, precomputed)
        if X is None:
            return {
                "value": "unknown", "confidence": 0.0, "probabilities": {},
                "explanation": "No plant could be isolated in this image.",
                "model_info": {},
            }

        model = bundle["model"]
        le = bundle["label_encoder"]

        pred = model.predict(X)[0]
        value = le.inverse_transform([pred])[0]

        probabilities, raw_conf = {}, 0.0
        if hasattr(model, "predict_proba"):
            proba = model.predict_proba(X)[0]
            probabilities = {c: round(float(p), 4)
                             for c, p in zip(le.classes_, proba)}
            raw_conf = float(proba.max())

        confidence = self._calibrate(raw_conf, bundle, value, trait)

        return {
            "value": value,
            "confidence": round(confidence, 3),
            "probabilities": probabilities,
            "explanation": self._explain(trait, value, confidence, bundle),
            "model_info": {
                "model": bundle.get("model_name", ""),
                "feature_set": bundle.get("feature_set", ""),
                "cv_accuracy": round(bundle.get("accuracy", 0.0), 3),
                "cv_f1": round(bundle.get("f1", 0.0), 3),
                "baseline": round(bundle.get("baseline", 0.0), 3),
            },
        }

    def _build_vector(self, image_path: str, bundle: dict,
                      precomputed: dict = None):
        """Assemble the feature vector this bundle's model expects."""
        feature_set = bundle.get("feature_set", "handcrafted")

        hand = None
        if feature_set in ("handcrafted", "combined"):
            hand = precomputed or extract_trait_features(image_path)
            names = [f for f in get_trait_feature_names() if f in hand]
            hand_vec = np.array([[float(hand.get(n, 0.0)) for n in names]])
        else:
            hand_vec = None

        cnn_vec = None
        if feature_set in ("cnn", "combined"):
            from cnn_features import extract_cnn_features
            cnn_vec = extract_cnn_features([image_path], verbose=False)
            if not cnn_vec.any():
                return None

        if feature_set == "handcrafted":
            X = hand_vec
        elif feature_set == "cnn":
            X = cnn_vec
        else:
            X = np.hstack([hand_vec, cnn_vec])

        if X is None:
            return None

        expected = len(bundle.get("feature_names", []))
        if expected and X.shape[1] != expected:
            print(f"[WARN] Feature count mismatch for {bundle.get('trait')}: "
                  f"got {X.shape[1]}, model expects {expected}")
            return None

        return np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    @staticmethod
    def _calibrate(raw_confidence: float, bundle: dict, value: str,
                   trait: str) -> float:
        """
        Turn the model's internal certainty into something the app can act on.

        Scaled by how far the model beat its baseline in cross-validation. A
        model that only just beats guessing should never report high
        confidence, however peaked its softmax is.
        """
        accuracy = bundle.get("accuracy", 0.0)
        baseline = bundle.get("baseline", 0.0)

        # Bounded by the model's measured accuracy on unseen plants. A softmax
        # of 0.9 from a model that is right 63% of the time should not be
        # reported as 90% confidence - the softmax describes the model's
        # internal certainty, and cross-validated accuracy describes how often
        # that certainty is justified.
        confidence = raw_confidence * accuracy

        # A model no better than guessing gets no confidence at all
        if accuracy <= baseline:
            confidence *= 0.4

        # Classes with a handful of training plants cannot be trusted even when
        # the model is sure
        if value in UNDER_SUPPORTED.get(trait, set()):
            confidence *= 0.5

        return float(np.clip(confidence, 0.0, 1.0))

    @staticmethod
    def _explain(trait: str, value: str, confidence: float, bundle: dict) -> str:
        label = trait.replace("_", " ")
        acc = bundle.get("accuracy", 0.0)

        msg = f"Predicted {label}: {value}."

        if value in UNDER_SUPPORTED.get(trait, set()):
            n = bundle.get("plants_per_class", {}).get(value, 0)
            msg += (f" Note: only {n} plants in the training data were labelled "
                    f"'{value}', so this class is not reliably learned.")

        msg += (f" Model accuracy on unseen plants was {acc:.0%} "
                f"(baseline {bundle.get('baseline', 0):.0%}).")

        if confidence < 0.4:
            msg += " Confidence is low - please confirm."

        return msg

    def predict_all(self, image_path: str) -> dict:
        """Predict every available trait, segmenting the image only once."""
        precomputed = None
        try:
            precomputed = extract_trait_features(image_path)
        except Exception:
            pass

        return {t: self.predict(image_path, t, precomputed)
                for t in self.available()}


_predictor = None


def get_trait_predictor() -> TraitPredictor:
    """Shared predictor, loaded once."""
    global _predictor
    if _predictor is None:
        _predictor = TraitPredictor()
    return _predictor


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Predict plant traits from an image")
    parser.add_argument("--image", required=True)
    args = parser.parse_args()

    predictor = get_trait_predictor()
    print(f"Loaded models: {predictor.available()}\n")

    for trait, r in predictor.predict_all(args.image).items():
        print(f"  {trait}: {r['value']}  (confidence {r['confidence']:.0%})")
        print(f"     {r['explanation']}")
        if r["probabilities"]:
            probs = "  ".join(f"{k}={v:.2f}" for k, v in r["probabilities"].items())
            print(f"     {probs}")
        print()
