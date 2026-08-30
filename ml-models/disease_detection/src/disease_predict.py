"""
disease_predict.py -- the full inference cascade: photograph in, recommendation out.

This is the piece that joins everything the component builds:

    photograph
        |
        v
    preprocess: resize 224x224, raw 0-255 RGB
        |
        v
    Model 1 - disease classifier (3-class softmax)
        |
        +-- max probability < THRESHOLD?  -> "unidentified condition"
        |                                    severity NOT consulted
        |                                    expert review recommended
        |
        +-- predicted "healthy"?          -> no treatment
        |                                    severity NOT consulted
        |
        +-- otherwise (a disease)
                |
                v
            Model 2 - severity classifier (mild / moderate / severe)
                |
                v
            treatment knowledge base, keyed by (disease, severity)
                |
                v
            recommendation

Two rules are enforced here and nowhere else, so the backend cannot get them
wrong:

  1. The severity model is NEVER consulted for a healthy plant or for a
     low-confidence prediction. Grading the severity of a condition you cannot
     name is meaningless, and a healthy plant has no grade.

  2. Scaling happens once, inside the model. This module hands over raw 0-255
     RGB. If anyone adds a division by 255 here, predictions become silently
     meaningless -- see src/preprocess.py.

Both models are loaded once and cached, because loading a .keras file takes
seconds and a web request cannot afford that per call.

NAMING NOTE
-----------
This file is called disease_predict.py, not predict.py, on purpose. Four
components in this repository ship a src/predict.py, and the backend places
several of their src directories on sys.path simultaneously. A bare
`import predict` then resolves to whichever directory comes first, which
depends on router import order in backend/app/main.py. It resolved to
hybrid_pollination's, which imports cv2, and every /detect request returned
503. A unique filename makes the import unambiguous.

Usage
-----
  python disease_predict.py --image ../data/split/test/black_leaf_spot/Black_LS_0002.jpg
  python disease_predict.py --image photo.jpg --json
  python disease_predict.py --demo                 # runs over a few held-out test images
  python disease_predict.py --image photo.jpg --threshold 0.60
"""

import argparse
import json
import sys
from pathlib import Path

COMPONENT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODELS = COMPONENT_ROOT / "models"

IMG_SIZE = (224, 224)

# Chosen from the VALIDATION threshold sweep (PROJECT_CONTEXT.md section 4c).
# At 0.70 the system answers 84% of cases automatically at 91% accuracy.
DEFAULT_THRESHOLD = 0.70

_CACHE = {}


def _load(models_dir):
    """Load both models, both class lists and the treatment KB once."""
    key = str(models_dir)
    if key in _CACHE:
        return _CACHE[key]

    import tensorflow as tf
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from treatment import TreatmentAdvisor

    models_dir = Path(models_dir)
    disease_path = models_dir / "disease_model.keras"
    if not disease_path.exists():
        raise FileNotFoundError(
            "{} not found. Train it, or download it from Drive into models/."
            .format(disease_path))

    names_path = models_dir / "class_names.json"
    if not names_path.exists():
        raise FileNotFoundError(
            "{} not found. Without it, output index 0 cannot be mapped to a "
            "disease name and every prediction could silently be wrong."
            .format(names_path))

    bundle = {
        "disease_model": tf.keras.models.load_model(disease_path, compile=False),
        "disease_classes": json.loads(names_path.read_text(encoding="utf-8")),
        "advisor": TreatmentAdvisor(),
        "severity_model": None,
        "severity_classes": None,
    }

    # The severity model is optional: the system still gives a disease name and
    # the cultural-control advice without it.
    sev_path = models_dir / "severity_model.keras"
    sev_names = models_dir / "severity_class_names.json"
    if sev_path.exists() and sev_names.exists():
        bundle["severity_model"] = tf.keras.models.load_model(sev_path, compile=False)
        bundle["severity_classes"] = json.loads(sev_names.read_text(encoding="utf-8"))

    _CACHE[key] = bundle
    return bundle


def _to_tensor(image):
    """
    Accept a path or raw bytes -> float32 (1, 224, 224, 3), values 0-255.

    Raw 0-255 on purpose. The Rescaling layer inside the model maps it to
    [-1, 1]. Scaling here as well would double-scale and quietly ruin every
    prediction without raising an error.
    """
    import tensorflow as tf
    data = image if isinstance(image, (bytes, bytearray)) else tf.io.read_file(str(image))
    img = tf.io.decode_image(data, channels=3, expand_animations=False)
    img = tf.image.resize(img, IMG_SIZE, method="bilinear")
    return tf.expand_dims(tf.cast(img, tf.float32), axis=0)


def predict(image, models_dir=DEFAULT_MODELS, threshold=DEFAULT_THRESHOLD,
            include_treatment=True):
    """
    Run the full cascade on one image.

    `image` is a file path or raw image bytes (so the backend can pass an
    upload straight through without writing a temp file).

    Returns a JSON-serialisable dict. Never raises for an unrecognised
    prediction -- an unknown label falls through to the 'unidentified' entry,
    because a system that crashes on an unexpected input is worse than one
    that says "I am not sure, ask an expert".
    """
    b = _load(models_dir)
    x = _to_tensor(image)

    # ---- stage 1: disease ----
    probs = b["disease_model"].predict(x, verbose=0)[0]
    idx = int(probs.argmax())
    confidence = float(probs[idx])
    raw_label = b["disease_classes"][idx]
    confident = confidence >= threshold

    result = {
        "disease": raw_label if confident else "unidentified",
        "raw_prediction": raw_label,
        "confidence": round(confidence, 4),
        "confident": confident,
        "threshold": threshold,
        "plant_part": "leaf",       # both trained diseases are leaf diseases
        "probabilities": {c: round(float(p), 4)
                          for c, p in zip(b["disease_classes"], probs)},
        "severity": None,
        "severity_confidence": None,
        "severity_probabilities": None,
    }

    # ---- stage 2: severity, only when a disease was actually identified ----
    if not confident:
        result["explanation"] = (
            "Highest probability {:.1%} is below the {:.0%} threshold. The "
            "condition is outside the three trained classes, or the photograph "
            "is unclear. Severity was not assessed, because grading a condition "
            "that cannot be named is meaningless."
            .format(confidence, threshold))
    elif raw_label == "healthy":
        result["explanation"] = (
            "No disease detected ({:.1%} confidence). Severity was not "
            "assessed -- a healthy plant has no grade.".format(confidence))
    elif b["severity_model"] is None:
        result["explanation"] = (
            "{} identified at {:.1%} confidence. Severity model not available, "
            "so only general advice for this disease is given."
            .format(raw_label, confidence))
    else:
        sev_probs = b["severity_model"].predict(x, verbose=0)[0]
        s_idx = int(sev_probs.argmax())
        result["severity"] = b["severity_classes"][s_idx]
        result["severity_confidence"] = round(float(sev_probs[s_idx]), 4)
        result["severity_probabilities"] = {
            c: round(float(p), 4) for c, p in zip(b["severity_classes"], sev_probs)}
        result["explanation"] = (
            "{} identified at {:.1%} confidence, graded {} ({:.1%})."
            .format(raw_label, confidence, result["severity"],
                    result["severity_confidence"]))

        # Severity is an ordered scale and the model's exact-grade accuracy is
        # modest (0.465 test) while its within-one-grade accuracy is high
        # (0.907). Surfacing that honestly matters: a grower should treat the
        # grade as an indication, not a measurement.
        if result["severity_confidence"] < 0.55:
            result["severity_note"] = (
                "Severity confidence is low. The grade may be one step out; "
                "inspect the plant before choosing between treatments.")

    # ---- stage 3: treatment ----
    if include_treatment:
        result["treatment"] = b["advisor"].recommend(
            result["disease"], result["severity"])

    return result


def print_human(r):
    """Readable output for a terminal demo."""
    print("\n" + "=" * 66)
    t = r.get("treatment") or {}
    print("  {}".format(t.get("display_name", r["disease"]).upper()))
    if r["severity"]:
        print("  severity: {}".format(r["severity"]))
    print("=" * 66)
    print("\n  {}".format(r["explanation"]))

    print("\n  Disease probabilities:")
    for k, v in sorted(r["probabilities"].items(), key=lambda kv: -kv[1]):
        bar = "#" * int(round(v * 34))
        print("    {:<26} {:>6.1%}  {}".format(k, v, bar))

    if r.get("severity_probabilities"):
        print("\n  Severity probabilities:")
        for k, v in r["severity_probabilities"].items():
            bar = "#" * int(round(v * 34))
            print("    {:<26} {:>6.1%}  {}".format(k, v, bar))
    if r.get("severity_note"):
        print("\n  ! {}".format(r["severity_note"]))

    if not t or t.get("error"):
        print()
        return

    print("\n  {}".format(t.get("summary", "")))
    if t.get("immediate_actions"):
        print("\n  DO NOW")
        for s in t["immediate_actions"]:
            print("    - {}".format(s))
    if t.get("cultural_control"):
        print("\n  GROWING CONDITIONS")
        for s in t["cultural_control"]:
            print("    - {}".format(s))

    chem = t.get("chemical_control", {})
    print("\n  CHEMICAL TREATMENT: {}".format(
        "recommended" if chem.get("recommended") else "not recommended"))
    if chem.get("rationale"):
        print("    {}".format(chem["rationale"]))
    for o in chem.get("options", []):
        print("    * {} [FRAC {}] -- {}".format(
            o["active_ingredient"], o["frac_group"], o["dose"]))

    if t.get("escalate_to_expert"):
        print("\n  ** REFER TO AN EXPERT **")
        if t.get("escalation_reason"):
            print("     {}".format(t["escalation_reason"]))
    print()


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--image")
    ap.add_argument("--models", default=str(DEFAULT_MODELS))
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--json", action="store_true", help="print raw JSON")
    ap.add_argument("--demo", action="store_true",
                    help="run over one held-out test image per class")
    args = ap.parse_args()

    if args.demo:
        test_root = COMPONENT_ROOT / "data" / "split" / "test"
        if not test_root.is_dir():
            sys.exit("ERROR: {} not found.".format(test_root))
        for class_dir in sorted(d for d in test_root.iterdir() if d.is_dir()):
            imgs = sorted(class_dir.glob("*.jpg"))[:1]
            for img in imgs:
                print("\n\n>>> {}  (true class: {})".format(img.name, class_dir.name))
                print_human(predict(img, args.models, args.threshold))
        return

    if not args.image:
        ap.error("give --image PATH, or --demo")

    r = predict(args.image, args.models, args.threshold)
    if args.json:
        print(json.dumps(r, indent=2))
    else:
        print_human(r)


if __name__ == "__main__":
    main()
