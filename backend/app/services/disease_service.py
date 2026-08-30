"""
disease_service.py -- bridge between the FastAPI backend and the trained models.

The models, the treatment knowledge base and the cascade rules all live in
`ml-models/disease_detection/`. This module is the only place the backend
reaches into that folder, so the route handlers stay thin and the ML code stays
independently testable and runnable from the command line.

Model loading is LAZY and CACHED. Loading two .keras files takes several
seconds, which no HTTP request can afford, but doing it at import time would
make the whole API fail to start if a model file were missing. So the first
request pays the cost, every later one is fast, and a missing model degrades to
a clear 503 on one endpoint instead of a dead server.
"""

import sys
from pathlib import Path

# backend/app/services/disease_service.py -> repo root is three levels up
REPO_ROOT = Path(__file__).resolve().parents[3]
COMPONENT = REPO_ROOT / "ml-models" / "disease_detection"
SRC = COMPONENT / "src"
MODELS = COMPONENT / "models"

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Operating threshold chosen from the VALIDATION sweep, not test.
# See PROJECT_CONTEXT.md section 4c.
DEFAULT_THRESHOLD = 0.70

MAX_UPLOAD_BYTES = 12 * 1024 * 1024          # 12 MB; phone photos are ~2-5 MB
ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic",
}


class ModelUnavailable(RuntimeError):
    """Raised when the trained models are not present on disk."""


class InvalidImage(ValueError):
    """Raised when an upload is not a usable image."""


def model_status():
    """
    What is on disk, without importing TensorFlow.

    Used by the health endpoint so a monitoring check does not pay the cost of
    loading two models.
    """
    files = {
        "disease_model": MODELS / "disease_model.keras",
        "disease_classes": MODELS / "class_names.json",
        "severity_model": MODELS / "severity_model.keras",
        "severity_classes": MODELS / "severity_class_names.json",
        "treatment_kb": SRC / "treatment_kb.json",
    }
    present = {k: v.exists() for k, v in files.items()}
    return {
        "models_dir": str(MODELS),
        "files": present,
        "disease_ready": present["disease_model"] and present["disease_classes"],
        "severity_ready": present["severity_model"] and present["severity_classes"],
        "treatment_ready": present["treatment_kb"],
        "threshold": DEFAULT_THRESHOLD,
    }


def _cascade():
    """Import the prediction module, converting a missing model into a clear error."""
    try:
        import predict as _predict
    except ImportError as exc:                                   # pragma: no cover
        raise ModelUnavailable(
            "Could not import the prediction module from {}: {}".format(SRC, exc))
    return _predict


def validate_upload(content_type, data):
    """Reject anything that is not a plausible image before touching TensorFlow."""
    if content_type and content_type.lower() not in ALLOWED_CONTENT_TYPES:
        raise InvalidImage(
            "Unsupported file type '{}'. Send a JPEG, PNG or WebP photograph."
            .format(content_type))
    if not data:
        raise InvalidImage("The uploaded file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise InvalidImage(
            "Image is {:.1f} MB. The limit is {:.0f} MB -- most phones can be "
            "asked to send a smaller photo."
            .format(len(data) / 1e6, MAX_UPLOAD_BYTES / 1e6))


def analyse(image_bytes, threshold=DEFAULT_THRESHOLD):
    """
    Run the full cascade on uploaded bytes and return a JSON-ready dict.

    The bytes are passed straight through -- no temp file is written, so a
    failed request leaves nothing behind on disk.
    """
    status = model_status()
    if not status["disease_ready"]:
        raise ModelUnavailable(
            "The disease model is not available. Expected {} and {}. Train the "
            "model or copy it from Google Drive into models/."
            .format(MODELS / "disease_model.keras", MODELS / "class_names.json"))

    predict_mod = _cascade()
    try:
        result = predict_mod.predict(
            image_bytes, models_dir=MODELS, threshold=threshold)
    except FileNotFoundError as exc:
        raise ModelUnavailable(str(exc))
    except Exception as exc:                                     # noqa: BLE001
        # Most commonly a corrupt or non-image upload that got past the
        # content-type check.
        raise InvalidImage(
            "Could not read that image: {}. Try re-taking the photograph."
            .format(exc))

    result["severity_model_used"] = result.get("severity") is not None
    return result


def treatment_for(disease, severity=None):
    """Treatment lookup without running any model. Used by the GET endpoint."""
    try:
        from treatment import TreatmentAdvisor
    except ImportError as exc:                                   # pragma: no cover
        raise ModelUnavailable("Treatment knowledge base unavailable: {}".format(exc))
    return TreatmentAdvisor().recommend(disease, severity)


def known_diseases():
    from treatment import TreatmentAdvisor
    advisor = TreatmentAdvisor()
    return {
        "diseases": [
            {"name": d,
             "display_name": advisor.treatments[d].get("display_name", d),
             "severities": advisor.severities_for(d)}
            for d in advisor.known_diseases()
        ],
        "note": (
            "Only black_leaf_spot, phyllosticta_leaf_spot and healthy are "
            "predicted by the model. 'unidentified' is returned when confidence "
            "falls below the threshold; there is no trained 'other' class."
        ),
    }
