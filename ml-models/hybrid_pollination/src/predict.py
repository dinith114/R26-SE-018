"""
Hybrid Pollination - Model Inference Script
Loads a trained model and predicts pollination suitability for a given orchid plant.

Usage:
    python src/predict.py --image path/to/image.jpg

Or as a module:
    from predict import PollSuitabilityPredictor
    predictor = PollSuitabilityPredictor()
    result = predictor.predict(image_path, traits)
"""

import numpy as np
import os
import sys
import joblib
import argparse

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feature_extraction import extract_all_features


# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, "models")


class PollSuitabilityPredictor:
    """
    Loads the trained model and preprocessors to predict
    orchid pollination suitability from an image and plant traits.
    """

    def __init__(self, model_path: str = None, preprocessor_path: str = None):
        if model_path is None:
            model_path = os.path.join(MODELS_DIR, "best_model.pkl")
        if preprocessor_path is None:
            preprocessor_path = os.path.join(MODELS_DIR, "preprocessors.pkl")

        # Load model
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")
        self.model = joblib.load(model_path)

        # Load preprocessors
        if not os.path.exists(preprocessor_path):
            raise FileNotFoundError(f"Preprocessors not found: {preprocessor_path}")
        preprocessors = joblib.load(preprocessor_path)
        self.scaler = preprocessors["scaler"]
        self.trait_encoders = preprocessors["trait_encoders"]
        self.label_encoder = preprocessors["label_encoder"]
        self.feature_names = preprocessors["feature_names"]

        print(f"[INFO] Model loaded: {os.path.basename(model_path)}")
        print(f"[INFO] Classes: {list(self.label_encoder.classes_)}")

    def predict(
        self,
        image_path: str,
        traits: dict = None
    ) -> dict:
        """
        Predict pollination suitability for a single plant.

        Args:
            image_path: Path to the plant image
            traits: Optional dict with keys: leaf_condition, plant_strength,
                    disease_visible, flower_condition

        Returns:
            dict with: label, confidence, probabilities, recommendation
        """
        # Extract image features
        image_features = extract_all_features(image_path)

        # Encode trait features
        trait_features = {}
        if traits:
            for col, encoder in self.trait_encoders.items():
                val = traits.get(col, "unknown")
                val = str(val).strip().lower()
                if val in encoder.classes_:
                    trait_features[f"{col}_encoded"] = encoder.transform([val])[0]
                else:
                    # Unknown value — use most common class (0)
                    trait_features[f"{col}_encoded"] = 0
        else:
            # Default: unknown traits
            for col in self.trait_encoders:
                trait_features[f"{col}_encoded"] = 0

        # Build feature vector in correct order
        feature_vector = []
        for fname in self.feature_names:
            if fname in image_features:
                feature_vector.append(float(image_features[fname]))
            elif fname in trait_features:
                feature_vector.append(float(trait_features[fname]))
            else:
                feature_vector.append(0.0)

        X = np.array([feature_vector], dtype=np.float32)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        # Scale
        X_scaled = self.scaler.transform(X)

        # Predict
        prediction = self.model.predict(X_scaled)[0]
        label = self.label_encoder.inverse_transform([prediction])[0]

        # Probabilities (if available)
        probabilities = {}
        confidence = 0.0
        if hasattr(self.model, "predict_proba"):
            proba = self.model.predict_proba(X_scaled)[0]
            for cls, prob in zip(self.label_encoder.classes_, proba):
                probabilities[cls] = round(float(prob), 4)
            confidence = round(float(max(proba)), 4)

        # Generate recommendation
        recommendation = self._get_recommendation(label, confidence, traits)

        return {
            "suitability": label,
            "confidence": confidence,
            "probabilities": probabilities,
            "recommendation": recommendation,
            "features_extracted": len(image_features),
        }

    def _get_recommendation(self, label: str, confidence: float, traits: dict = None) -> str:
        """Generate human-readable recommendation based on prediction."""
        if label == "Suitable":
            msg = "✅ This plant is suitable for pollination. "
            msg += "It shows healthy characteristics and is in good condition for breeding."
            if traits and traits.get("disease_visible") == "no":
                msg += " No visible disease detected."
        elif label == "Moderate":
            msg = "⚠️ This plant has moderate suitability. "
            msg += "It may be used for pollination but results could be less reliable. "
            msg += "Consider improving plant health before pollination."
            if traits and traits.get("leaf_condition") == "moderate":
                msg += " Leaf condition is moderate — monitor closely."
        else:  # Not Suitable
            msg = "❌ This plant is NOT suitable for pollination. "
            msg += "It shows signs of weakness or disease that would likely result in failed pollination."
            if traits and traits.get("disease_visible") == "yes":
                msg += " Disease is visible — treat the plant first before considering pollination."

        if confidence < 0.5:
            msg += f"\n⚠️ Low confidence ({confidence:.0%}) — consider getting additional evaluation."

        return msg


def main():
    """CLI interface for prediction."""
    parser = argparse.ArgumentParser(description="Predict orchid pollination suitability")
    parser.add_argument("--image", type=str, required=True, help="Path to plant image")
    parser.add_argument("--leaf-condition", type=str, default="unknown",
                        choices=["healthy", "moderate", "weak", "unknown"])
    parser.add_argument("--plant-strength", type=str, default="unknown",
                        choices=["strong", "moderate", "weak", "unknown"])
    parser.add_argument("--disease", type=str, default="unknown",
                        choices=["yes", "no", "unknown"])
    parser.add_argument("--flower-condition", type=str, default="unknown",
                        choices=["good", "moderate", "weak", "unknown"])
    args = parser.parse_args()

    # Build traits dict
    traits = {
        "leaf_condition": args.leaf_condition,
        "plant_strength": args.plant_strength,
        "disease_visible": args.disease,
        "flower_condition": args.flower_condition,
    }

    # Predict
    predictor = PollSuitabilityPredictor()
    result = predictor.predict(args.image, traits)

    # Print result
    print("\n" + "=" * 50)
    print("POLLINATION SUITABILITY ASSESSMENT")
    print("=" * 50)
    print(f"\n  Suitability: {result['suitability']}")
    print(f"  Confidence:  {result['confidence']:.1%}")
    print(f"\n  Probabilities:")
    for cls, prob in result["probabilities"].items():
        bar = "█" * int(prob * 20) + "░" * (20 - int(prob * 20))
        print(f"    {cls:15s} [{bar}] {prob:.1%}")
    print(f"\n  {result['recommendation']}")
    print(f"\n  Features extracted: {result['features_extracted']}")


if __name__ == "__main__":
    main()
