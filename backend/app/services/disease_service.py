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

import csv
import re
import sys
import threading
from datetime import datetime, timezone
from io import BytesIO
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

PENDING = COMPONENT / "data" / "pending"
CONTRIBUTIONS_CSV = PENDING / "contributions.csv"

# A new class may not be trained until it has this many VERIFIED originals.
#
# This is a GATE, not a progress bar. Augmenting 8 contributed images into 432
# files yields 8 images of information, and a class learned from 8 examples has
# a decision boundary drawn from almost no evidence -- it bleeds into its
# neighbours and steals their predictions. Black Leaf Spot is already the
# weakest class at F1 0.60; adding an undertrained class would drag it lower.
# So the retraining tooling refuses below this number rather than merely
# reporting progress. See PROJECT_CONTEXT.md section 7.
MIN_IMAGES_PER_CLASS = 30

# Contributed photos are stored at the same resolution as data/processed/, which
# is what the training pipeline expects. It also makes storage a non-issue:
# measured on this dataset, 2.0 MB phone photos become about 180 KB.
CONTRIBUTION_MAX_SIDE = 1024

CSV_FIELDS = [
    "image_id", "disease", "plant_part", "severity",
    "verified", "verification_source", "verified_by",
    "submitted_at", "notes", "original_filename",
]

VALID_PARTS = {"leaf", "stem", "flower"}
VALID_SEVERITIES = {"mild", "moderate", "severe"}

# One writer at a time. Two contributions arriving together must not interleave
# rows in the CSV or race for the same sequence number.
_write_lock = threading.Lock()

MAX_UPLOAD_BYTES = 12 * 1024 * 1024          # 12 MB; phone photos are ~2-5 MB
ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic",
}


class ModelUnavailable(RuntimeError):
    """Raised when the trained models are not present on disk."""


class InvalidImage(ValueError):
    """Raised when an upload is not a usable image."""


class InvalidContribution(ValueError):
    """Raised when a contribution form is incomplete or inconsistent."""


def _slug(name):
    """Turn a typed disease name into a safe folder name."""
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return s[:60]


def _read_contributions():
    """Every recorded contribution. A missing file is not an error."""
    if not CONTRIBUTIONS_CSV.exists():
        return []
    with open(CONTRIBUTIONS_CSV, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def pending_counts():
    """
    Per-disease progress toward the retraining threshold.

    Counts VERIFIED rows only, because unverified labels must never be trained
    on -- the same rule the retraining tooling applies.
    """
    rows = _read_contributions()
    by_disease = {}
    for r in rows:
        d = r.get("disease") or "unknown"
        entry = by_disease.setdefault(d, {
            "disease": d,
            "display_name": d.replace("_", " ").title(),
            "total": 0,
            "verified": 0,
        })
        entry["total"] += 1
        if (r.get("verified") or "").strip().lower() == "true":
            entry["verified"] += 1

    for e in by_disease.values():
        e["needed"] = max(0, MIN_IMAGES_PER_CLASS - e["verified"])
        e["ready_for_training"] = e["verified"] >= MIN_IMAGES_PER_CLASS

    return {
        "minimum_required": MIN_IMAGES_PER_CLASS,
        "diseases": sorted(by_disease.values(), key=lambda e: -e["verified"]),
        "total_contributions": len(rows),
        "note": (
            "Only verified images count toward the threshold. Reaching it makes "
            "retraining POSSIBLE, not automatic: a human runs the retrain and the "
            "new model replaces the live one only if macro-F1 does not get worse."
        ),
    }


def save_contribution(image_bytes, disease, plant_part, severity,
                      verified=False, verified_by="", notes="",
                      original_filename=""):
    """
    Store one contributed photograph and record it.

    The image is saved as an ORIGINAL. It is deliberately NOT augmented here:
    augmenting before the train/test split would put variants of the same leaf
    on both sides of that split, which is the data leakage the whole pipeline is
    designed to prevent. Augmentation happens at retrain time, after splitting.
    """
    disease_slug = _slug(disease)
    if not disease_slug:
        raise InvalidContribution("A disease name is required.")
    if plant_part not in VALID_PARTS:
        raise InvalidContribution(
            "Plant part must be one of {}.".format(", ".join(sorted(VALID_PARTS))))
    if severity not in VALID_SEVERITIES:
        raise InvalidContribution(
            "Severity must be one of {}.".format(", ".join(sorted(VALID_SEVERITIES))))
    if verified and not (verified_by or "").strip():
        raise InvalidContribution(
            "Name the institute or expert who confirmed this diagnosis.")

    try:
        from PIL import Image, ImageOps
    except ImportError as exc:                                    # pragma: no cover
        raise ModelUnavailable("Pillow is required to store images: {}".format(exc))

    try:
        img = Image.open(BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as exc:                                      # noqa: BLE001
        raise InvalidImage("Could not read that image: {}".format(exc))

    if max(img.width, img.height) > CONTRIBUTION_MAX_SIDE:
        scale = CONTRIBUTION_MAX_SIDE / max(img.width, img.height)
        img = img.resize((max(1, round(img.width * scale)),
                          max(1, round(img.height * scale))), Image.LANCZOS)

    folder = PENDING / disease_slug
    with _write_lock:
        folder.mkdir(parents=True, exist_ok=True)
        existing = len(list(folder.glob("*.jpg")))
        image_id = "{}_{:04d}".format(disease_slug, existing + 1)
        img.save(folder / (image_id + ".jpg"), "JPEG", quality=92, optimize=True)

        row = {
            "image_id": image_id,
            "disease": disease_slug,
            "plant_part": plant_part,
            "severity": severity,
            "verified": "true" if verified else "false",
            # Records HOW it was verified, not merely whether. When a user role
            # is added later, admin_reviewed rows can outrank self-attested ones.
            "verification_source": "user_attested" if verified else "unverified",
            "verified_by": (verified_by or "").strip(),
            "submitted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "notes": (notes or "").strip(),
            "original_filename": (original_filename or "").strip(),
        }
        write_header = not CONTRIBUTIONS_CSV.exists()
        CONTRIBUTIONS_CSV.parent.mkdir(parents=True, exist_ok=True)
        with open(CONTRIBUTIONS_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
            if write_header:
                w.writeheader()
            w.writerow(row)

    counts = pending_counts()
    this_disease = next(
        (d for d in counts["diseases"] if d["disease"] == disease_slug),
        {"verified": 0, "needed": MIN_IMAGES_PER_CLASS, "ready_for_training": False})

    return {
        "saved": True,
        "image_id": image_id,
        "disease": disease_slug,
        "verified": bool(verified),
        "count_verified": this_disease["verified"],
        "minimum_required": MIN_IMAGES_PER_CLASS,
        "needed": this_disease["needed"],
        "ready_for_training": this_disease["ready_for_training"],
    }



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
        # Deliberately NOT named `predict`. Four components in this repository
        # ship a src/predict.py -- bloom_prediction, disease_detection,
        # growth_stage and hybrid_pollination -- and the backend puts several of
        # their src directories on sys.path at once. A bare `import predict`
        # therefore resolved to whichever component's folder happened to come
        # first, which depended on the order main.py imports routers in. It
        # picked hybrid_pollination's, which needs cv2, and every /detect call
        # failed with a 503. A unique module name removes the ambiguity.
        import disease_predict as _predict
    except ImportError as exc:                                   # pragma: no cover
        raise ModelUnavailable(
            "Could not import disease_predict from {}: {}".format(SRC, exc))
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
