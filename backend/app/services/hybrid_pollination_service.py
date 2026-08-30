"""
Hybrid Pollination — Service Layer
Business logic for pollination suitability assessment.
Loads the trained ML model and provides prediction functions.
"""

import os
import sys
import numpy as np
import joblib
import tempfile

# Add ML model source to path for imports
ML_SRC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "ml-models", "hybrid_pollination", "src"
)
sys.path.insert(0, ML_SRC_DIR)

ML_MODELS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "ml-models", "hybrid_pollination", "models"
)


class HybridPollinationService:
    """
    Singleton service that loads the trained model once
    and provides prediction capabilities.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.model = None
        self.scaler = None
        self.trait_encoders = None
        self.label_encoder = None
        self.feature_names = None
        self.model_name = ""
        self._load_model()

    def _load_model(self):
        """Load the trained model and preprocessors."""
        model_path = os.path.join(ML_MODELS_DIR, "best_model.pkl")
        preprocessor_path = os.path.join(ML_MODELS_DIR, "preprocessors.pkl")

        if not os.path.exists(model_path):
            print(f"[WARN] Model not found at {model_path}")
            return

        if not os.path.exists(preprocessor_path):
            print(f"[WARN] Preprocessors not found at {preprocessor_path}")
            return

        try:
            self.model = joblib.load(model_path)
            preprocessors = joblib.load(preprocessor_path)
            self.scaler = preprocessors["scaler"]
            self.trait_encoders = preprocessors["trait_encoders"]
            self.label_encoder = preprocessors["label_encoder"]
            self.feature_names = preprocessors["feature_names"]
            self.model_name = type(self.model).__name__
            print(f"[INFO] Loaded model: {self.model_name}")
            print(f"[INFO] Classes: {list(self.label_encoder.classes_)}")
        except Exception as e:
            print(f"[ERROR] Failed to load model: {e}")

    @property
    def is_loaded(self) -> bool:
        return self.model is not None

    def predict_suitability(self, image_path: str, traits: dict = None) -> dict:
        """
        Predict pollination suitability for a plant image.

        Args:
            image_path: Path to the saved image file
            traits: dict with leaf_condition, plant_strength, disease_visible, flower_condition

        Returns:
            dict with suitability, confidence, probabilities, recommendation
        """
        if not self.is_loaded:
            return {
                "suitability": "Unknown",
                "confidence": 0.0,
                "probabilities": {},
                "recommendation": "Model not loaded. Please train the model first.",
                "features_extracted": 0,
            }

        # Import here to avoid circular imports
        from feature_extraction import extract_all_features

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
                    trait_features[f"{col}_encoded"] = 0
        else:
            for col in self.trait_encoders:
                trait_features[f"{col}_encoded"] = 0

        # Build feature vector
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
        X_scaled = self.scaler.transform(X)

        # Predict
        prediction = self.model.predict(X_scaled)[0]
        label = self.label_encoder.inverse_transform([prediction])[0]

        # Probabilities
        probabilities = {}
        confidence = 0.0
        if hasattr(self.model, "predict_proba"):
            proba = self.model.predict_proba(X_scaled)[0]
            for cls, prob in zip(self.label_encoder.classes_, proba):
                probabilities[cls] = round(float(prob), 4)
            confidence = round(float(max(proba)), 4)

        # Recommendation
        recommendation = self._get_recommendation(label, confidence, traits)

        return {
            "suitability": label,
            "confidence": confidence,
            "probabilities": probabilities,
            "recommendation": recommendation,
            "features_extracted": len(image_features),
        }

    def _get_recommendation(self, label: str, confidence: float, traits: dict = None) -> str:
        """Generate human-readable recommendation."""
        if label == "Suitable":
            msg = "This plant is suitable for pollination. "
            msg += "It shows healthy characteristics and is in good condition for breeding."
            if traits and traits.get("disease_visible") == "no":
                msg += " No visible disease detected."
        elif label == "Moderate":
            msg = "This plant has moderate suitability. "
            msg += "It may be used for pollination but results could be less reliable. "
            msg += "Consider improving plant health before pollination."
        else:
            msg = "This plant is NOT suitable for pollination. "
            msg += "It shows signs of weakness or disease that would likely result in failed pollination."
            if traits and traits.get("disease_visible") == "yes":
                msg += " Disease is visible - treat the plant first."

        if confidence < 0.5:
            msg += f" (Low confidence: {confidence:.0%} - consider additional evaluation)"

        return msg

    def get_model_info(self) -> dict:
        """Get model metadata."""
        return {
            "model_loaded": self.is_loaded,
            "model_name": self.model_name,
            "classes": list(self.label_encoder.classes_) if self.label_encoder else [],
            "num_features": len(self.feature_names) if self.feature_names else 0,
        }


# Singleton instance
pollination_service = HybridPollinationService()
