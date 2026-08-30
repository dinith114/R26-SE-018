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
        self._resolver = None
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

    def check_input(self, image_path: str) -> dict:
        """
        Is this photograph an orchid plant at all?

        The suitability model has three classes and no way to express "this is
        not a plant" - during testing a photograph of a laptop screen came back
        as Suitable with 98.7% confidence. Every upload is therefore screened
        first. See ml-models/hybrid_pollination/src/orchid_gate.py.

        A missing gate model does not block the app: check_image reports
        gate_available=False and the image is allowed through, which is the
        behaviour that existed before the gate was added.
        """
        try:
            from orchid_gate import check_image
            return check_image(image_path)
        except Exception as e:
            print(f"[WARN] Input gate unavailable: {e}")
            return {"is_orchid": True, "gate_available": False,
                    "message": f"Input validation unavailable: {e}"}

    def resolve_traits(self, image_path: str, leaf_closeup_path: str = None,
                       user_traits: dict = None) -> dict:
        """
        Derive plant traits from the image before any prediction is made.

        This is what removes the requirement for the grower to diagnose their
        own plant: traits are measured, and the user is asked only where the
        measurement is too weak to act on. See ml-models/hybrid_pollination/
        src/trait_resolution.py for the resolution rules and their limits.

        Returns:
            The ResolutionReport as a dict, or None if resolution is unavailable.
        """
        try:
            from trait_resolution import TraitResolver
        except ImportError as e:
            print(f"[WARN] Trait resolution unavailable: {e}")
            return None

        if self._resolver is None:
            self._resolver = TraitResolver()

        return self._resolver.resolve(
            image_path, leaf_closeup_path=leaf_closeup_path, user_traits=user_traits
        ).to_dict()

    def predict_suitability(self, image_path: str, traits: dict = None,
                            leaf_closeup_path: str = None,
                            auto_traits: bool = True,
                            input_check: dict = None) -> dict:
        """
        Predict pollination suitability for a plant image.

        Args:
            image_path: Path to the saved image file
            traits: Any trait values the grower supplied. These are treated as
                    CORRECTIONS to the measured values, not as required input.
            leaf_closeup_path: Optional leaf close-up, used for disease
            auto_traits: Measure traits from the image before predicting
            input_check: Result of check_input, passed in so the gate is not
                    run twice. When it reports the photograph as unusual for
                    the reference collection, the verdict is damped and
                    labelled as extrapolation.

        Returns:
            dict with suitability, confidence, probabilities, recommendation
            and trait_resolution (where each trait value came from)
        """
        if not self.is_loaded:
            return {
                "suitability": "Unknown",
                "confidence": 0.0,
                "probabilities": {},
                "recommendation": "Model not loaded. Please train the model first.",
                "features_extracted": 0,
                "trait_resolution": None,
            }

        # Import here to avoid circular imports
        from feature_extraction import extract_all_features

        # Measure traits from the image first; user-supplied values override
        resolution = None
        effective_traits = dict(traits or {})
        if auto_traits:
            resolution = self.resolve_traits(image_path, leaf_closeup_path, traits)
            if resolution:
                effective_traits = {
                    name: t["value"] for name, t in resolution["traits"].items()
                }

        # Extract image features
        image_features = extract_all_features(image_path)

        # Encode trait features
        trait_features = {}
        if effective_traits:
            for col, encoder in self.trait_encoders.items():
                val = effective_traits.get(col, "unknown")
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
        recommendation = self._get_recommendation(label, confidence, effective_traits)

        # Consistency check between the suitability model and the trait models.
        #
        # These are separate models trained on different feature sets, so they
        # can disagree - and a verdict of "Suitable" sitting next to measured
        # traits of "weak" would rightly destroy a user's trust. When they
        # conflict, the conflict is surfaced and the confidence is cut rather
        # than quietly presenting the more optimistic of the two.
        conflict = self._trait_conflict(label, resolution)
        if conflict:
            recommendation = f"{conflict}\n\n{recommendation}"
            confidence = round(confidence * 0.5, 4)

        # A photograph unlike the reference collection gets its verdict damped
        # and labelled. Measured reason: all 58 internet orchid photographs that
        # passed the gate were called "Suitable" at a median confidence of 0.99,
        # while the same model recalls 99% of Not Suitable images on this
        # nursery's own plants under grouped CV. The model is not broken, it is
        # extrapolating - so the number shown to the grower should say so.
        if (input_check or {}).get("familiarity") == "unusual":
            recommendation = (
                "This photograph is unlike the plants this model was trained on "
                "(different setting, framing or lighting). The verdict below is "
                "an extrapolation and should be treated as indicative only.\n\n"
                + recommendation
            )
            confidence = round(confidence * 0.6, 4)

        return {
            "suitability": label,
            "confidence": confidence,
            "probabilities": probabilities,
            "recommendation": recommendation,
            "features_extracted": len(image_features),
            "trait_resolution": resolution,
        }

    @staticmethod
    def _trait_conflict(label: str, resolution: dict) -> str:
        """
        Detect a suitability verdict that contradicts the measured traits.

        Returns a warning string, or "" when the two agree.
        """
        if not resolution:
            return ""

        traits = resolution.get("traits", {})
        weak = []
        for name in ("leaf_condition", "plant_strength"):
            t = traits.get(name) or {}
            if t.get("source") == "measured" and t.get("value") in ("weak",):
                weak.append(name.replace("_", " "))

        if weak and label == "Suitable":
            joined = " and ".join(weak)
            return (f"NOTE: the suitability model says Suitable, but image analysis "
                    f"measured {joined} as weak. These are separate models and they "
                    f"disagree here, so treat this result with caution and inspect "
                    f"the plant yourself.")

        return ""

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
