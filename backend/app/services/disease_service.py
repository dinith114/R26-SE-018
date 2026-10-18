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

import json
import re
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

# Contributed photographs. Everything about storing and reviewing them lives in
# app/services/disease_contributions.py.
PENDING = COMPONENT / "data" / "pending"

VALID_PARTS = {"leaf", "stem", "flower"}
VALID_SEVERITIES = {"mild", "moderate", "severe"}

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


# ---------------------------------------------------------------------------
# Measured performance, for presenting the results
# ---------------------------------------------------------------------------

# Every augmented training original became this many files (augment_dataset.py),
# so the training counts in training_metadata.json divide back to photographs.
AUGMENT_FACTOR = 54


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def metrics_summary():
    """
    The measured results of both models, read from the files the evaluation
    scripts wrote. No number is typed in by hand, and no model is
    loaded, so it is fast and works even where TensorFlow is not installed.

    Every section is optional: a missing file drops its section rather than
    failing the request. `sources` lists the files that were actually read, so
    every number can be traced to where it came from.
    """
    results = COMPONENT / "results"
    sources = []

    def load(path):
        data = _read_json(path)
        if data is not None:
            sources.append(Path(path).relative_to(COMPONENT).as_posix())
        return data

    disease = (load(results / "extended_metrics" / "metrics_test.json")
               or load(MODELS / "metrics_test.json"))
    severity = (load(results / "extended_metrics" / "severity_metrics_test.json")
                or load(MODELS / "severity_metrics_test.json"))
    gate = load(MODELS / "feature_bank_metadata.json")
    architectures = load(MODELS / "model_comparison.json")
    training = load(MODELS / "training_metadata.json")
    photo = load(results / "photo_checks" / "photo_check_thresholds.json")
    experiments = load(results / "experiments" / "report" / "experiments_summary.json")
    final_tests = load(results / "experiments" / "test_log.json")

    out = {"sources": sources}

    if disease:
        x = disease.get("beyond_accuracy") or {}
        out["disease"] = {
            "n_images": disease["n_images"],
            "class_names": disease["class_names"],
            "accuracy": disease["accuracy"],
            "macro_f1": disease["macro_f1"],
            "per_class": disease["per_class"],
            "confusion_matrix": disease["confusion_matrix"],
            "baseline": x.get("majority_baseline"),
            "balanced_accuracy": x.get("balanced_accuracy"),
            "kappa": x.get("cohen_kappa"),
            "mcc": x.get("mcc"),
            "roc_auc": x.get("roc_auc_macro"),
            "roc_auc_per_class": x.get("roc_auc_per_class"),
            "calibration_error": x.get("expected_calibration_error"),
            "ci95_accuracy": x.get("ci95_accuracy"),
            "ci95_macro_f1": x.get("ci95_macro_f1"),
        }
        # Two test photographs turned out to be second shots of training
        # photographs (tools/measure_photo_checks.py). Shown with the score
        # recomputed without them, rather than left for someone else to find.
        near = [c for c in (photo or {}).get("near_copies_across_split", [])
                if c.get("part") == "test"]
        if near:
            held = {Path(c["held_out"]).name for c in near}
            wrong = {m["file"] for m in disease.get("misclassified", [])}
            right = disease["n_images"] - len(wrong) - len(held - wrong)
            n = disease["n_images"] - len(held)
            out["disease"]["near_copies"] = {
                "test_photos": sorted(held), "n_without": n, "accuracy_without": right / n,
            }

    if severity:
        x = severity.get("beyond_accuracy") or {}
        out["severity"] = {
            "n_images": severity["n_images"],
            "class_names": severity["class_names"],
            "exact_accuracy": severity["exact_accuracy"],
            "within_one_grade": severity["within_one_grade_accuracy"],
            "macro_f1": severity["macro_f1"],
            "per_class": severity["per_class"],
            "confusion_matrix": severity["confusion_matrix"],
            "severe_called_mild": severity.get("severe_called_mild"),
            "baseline": x.get("majority_baseline"),
            "qwk": x.get("quadratic_weighted_kappa"),
            "mean_grade_error": x.get("mean_grade_error"),
            "ci95_exact_accuracy": x.get("ci95_exact_accuracy"),
            "ci95_within_one_grade": x.get("ci95_within_one_grade"),
        }

    if gate:
        ood = gate.get("ood_check") or {}
        out["input_check"] = {
            "orchid_test_photos": (gate.get("test") or {}).get("n"),
            "orchid_test_refused": (gate.get("test") or {}).get("rejected"),
            "orchid_validation_photos": (gate.get("validation") or {}).get("n"),
            "orchid_validation_refused": (gate.get("validation") or {}).get("rejected"),
            "non_orchid_photos": ood.get("count"),
            "non_orchid_refused": ood.get("caught"),
            "rationale": gate.get("threshold_rationale"),
        }

    if architectures:
        out["architectures"] = {
            "scored_on": architectures.get("scored_on"),
            "epochs": (architectures.get("settings") or {}).get("epochs"),
            "results": [{k: r.get(k) for k in ("model", "macro_f1", "accuracy", "parameters",
                                                "size_mb", "latency_ms", "note")}
                        for r in architectures.get("results", [])],
        }

    if training:
        out["data"] = {
            "train_photos": round(sum(training.get("train_counts", {}).values()) / AUGMENT_FACTOR),
            "validation_photos": sum(training.get("validation_counts", {}).values()),
            "test_photos": (disease or {}).get("n_images"),
            "class_names": training.get("class_names"),
        }
    leakage = COMPONENT / "data" / "leakage_report.txt"
    if leakage.exists():
        text = leakage.read_text(encoding="utf-8")
        out.setdefault("data", {})["leakage_check"] = (
            "PASS" if "RESULT: PASS" in text else "FAIL" if "RESULT: FAIL" in text else None)
        sources.append("data/leakage_report.txt")

    if photo:
        out["photo_checks"] = {k: photo.get(k) for k in (
            "photographs", "real_refused", "bad_copies_caught", "copies_caught",
            "false_alarm_pairs", "distinct_pairs")}

    # Improvement experiments, once the Colab run's results have been brought
    # back. A smoke test proves only that the code runs, so it is never shown.
    if experiments and not experiments.get("smoke_test"):
        out["experiments"] = {
            "built_at": experiments.get("built_at"),
            "rows": [{
                "id": r["row"], "label": r["label"], "task": r["task"], "split": r.get("split"),
                "accuracy": r["metrics"]["accuracy"], "macro_f1": r["metrics"]["macro_f1"],
                "within_one": r["metrics"].get("within_one"),
                "vs": (r.get("delta") or {}).get("vs"),
                "verdict": (r.get("delta") or {}).get("verdict"),
            } for r in experiments.get("rows", [])],
            "final_tests": [t for t in (final_tests or []) if not t.get("smoke_test")],
        }
    return out
