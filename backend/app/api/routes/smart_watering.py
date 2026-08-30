"""
Smart Watering & Automated Fertilization — API Routes
Component 3 — R26-SE-018

Endpoints:
  GET  /sensor-data     Current sensor snapshot from Firebase /latest
  POST /predict         Run both ML models, write result to Firebase /prediction
  GET  /prediction      Latest prediction result from Firebase /prediction
  GET  /history         Recent sensor history from Firebase /history
  POST /image-predict   Visual hydration class from ESP32-CAM JPEG (CNN model)
"""

import io
import json
import os
import pickle
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd
import requests as _req
from fastapi import APIRouter, HTTPException, Query, UploadFile, File

router = APIRouter()

# ======================== CONSTANTS ========================

FIREBASE_BASE_URL = "https://orchid-smart-care-default-rtdb.firebaseio.com"
GROWTH_STAGE_MAP  = {"Active": 0, "Flowering": 1, "Dormant": 2}

# Trend window: 24 readings × 5 min = 2-hour look-back
LOOKBACK_READINGS  = 24
HISTORY_FETCH_SIZE = 30   # fetch extra to ensure we have 24 after sorting

# ======================== MODEL LOADING ========================

# Resolve path: routes/ → api/ → app/ → backend/ → R26-SE-018/ → orchid_project/ → ml_pipeline/results/
_MODEL_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "ml_pipeline", "results")
)

_water_pkg:  Optional[dict] = None
_fert_pkg:   Optional[dict] = None
_vision_model = None          # TF/Keras CNN for visual hydration
_vision_classes: list[str] = []


def _load_models() -> None:
    global _water_pkg, _fert_pkg
    with open(os.path.join(_MODEL_DIR, "best_model.pkl"), "rb") as f:
        _water_pkg = pickle.load(f)
    with open(os.path.join(_MODEL_DIR, "best_fertilization_model.pkl"), "rb") as f:
        _fert_pkg = pickle.load(f)
    print(f"[ML] Watering model:      {_water_pkg['model_name']} — F1={_water_pkg['metrics']['f1']:.4f}")
    print(f"[ML] Fertilization model: {_fert_pkg['model_name']}  — F1={_fert_pkg['metrics']['f1']:.4f}")


def _load_vision_model() -> None:
    """Load CNN visual hydration model if the artefacts exist."""
    global _vision_model, _vision_classes
    import tensorflow as tf
    model_path   = os.path.join(_MODEL_DIR, "visual_hydration_model.keras")
    classes_path = os.path.join(_MODEL_DIR, "visual_hydration_classes.json")
    if not os.path.exists(model_path):
        print(f"[WARN] Visual model not found at {model_path} — train it first with visual_hydration_training.py")
        return
    _vision_model = tf.keras.models.load_model(model_path)
    with open(classes_path) as f:
        class_map = json.load(f)
    _vision_classes = [class_map[str(i)] for i in range(len(class_map))]
    print(f"[ML] Visual hydration CNN loaded — classes: {_vision_classes}")


try:
    _load_models()
except Exception as _e:
    print(f"[WARN] ML models not loaded from {_MODEL_DIR}: {_e}")
    print("[WARN] /predict will return 503 until models are available.")

try:
    _load_vision_model()
except Exception as _e:
    print(f"[WARN] Visual hydration model not loaded: {_e}")


def _models_ready() -> bool:
    return _water_pkg is not None and _fert_pkg is not None


# ======================== FIREBASE HELPERS ========================

def _fb_get(path: str) -> Optional[dict]:
    try:
        resp = _req.get(f"{FIREBASE_BASE_URL}{path}", timeout=8)
        return resp.json() if resp.status_code == 200 else None
    except Exception:
        return None


def _fb_put(path: str, data: dict) -> bool:
    try:
        resp = _req.put(f"{FIREBASE_BASE_URL}{path}", json=data, timeout=8)
        return resp.status_code == 200
    except Exception:
        return False


# ======================== FEATURE COMPUTATION ========================

def _compute_trend_features(latest: dict) -> tuple[float, float]:
    """
    Pull last HISTORY_FETCH_SIZE records from Firebase /history,
    compute MoistureTrend and DryingRate over a 2-hour window.

    MoistureTrend = current_moisture − moisture_2h_ago  (negative = drying)
    DryingRate    = max(0, moisture_lost) / 2.0 hours   (%/hr)

    Returns (0.0, 0.0) on any failure so prediction can still proceed.
    """
    try:
        raw = _fb_get(f'/history.json?orderBy="$key"&limitToLast={HISTORY_FETCH_SIZE}')
        if not raw:
            return 0.0, 0.0

        records = sorted(raw.values(), key=lambda r: r.get("timestamp", 0))
        current_moisture = float(latest.get("rootMoisturePct", 50.0))

        if len(records) >= LOOKBACK_READINGS:
            past_moisture = float(records[-LOOKBACK_READINGS].get("rootMoisturePct", current_moisture))
        else:
            past_moisture = current_moisture

        hours_window   = (LOOKBACK_READINGS * 5) / 60.0   # 2.0 h
        moisture_trend = round(current_moisture - past_moisture, 2)
        drying_rate    = round(max(0.0, (past_moisture - current_moisture) / hours_window), 2)
        return moisture_trend, drying_rate
    except Exception:
        return 0.0, 0.0


# ======================== PREDICTION LOGIC ========================

def _predict_watering(latest: dict, moisture_trend: float, drying_rate: float) -> tuple[str, float]:
    """
    Watering model — 8 features, Random Forest.
    Returns (label "Yes"/"No", confidence 0.0–1.0).
    """
    cols = _water_pkg["feature_columns"]
    df = pd.DataFrame([[
        float(latest.get("temperature",        28.0)),
        float(latest.get("humidity",           70.0)),
        float(latest.get("light",               0.0)),
        float(latest.get("rootMoisturePct",    50.0)),
        float(latest.get("hoursSinceWater",    12.0)),
        moisture_trend,
        drying_rate,
        float(datetime.now(timezone.utc).hour),
    ]], columns=cols)
    scaled = _water_pkg["scaler"].transform(df)
    pred   = _water_pkg["model"].predict(scaled)[0]
    proba  = float(_water_pkg["model"].predict_proba(scaled)[0].max())
    label  = _water_pkg["label_encoder"].inverse_transform([pred])[0]
    return label, proba


def _estimate_growth_stage(month: int) -> str:
    """Calendar-based fallback when Component 2 (camera ML) is unavailable."""
    if month in [12, 1, 2]:  return "Dormant"
    if month in [10, 11]:    return "Flowering"
    return "Active"


def _predict_fertilization(latest: dict) -> tuple[str, str]:
    """
    Fertilization model — 6 features, Decision Tree.
    Returns (fertilize_needed "Yes"/"No", fertilizer_type string).
    Growth stage: reads from /latest (set by Component 2), falls back to calendar estimate.
    """
    month        = int(latest.get("seasonMonth", datetime.now().month))
    growth_stage = latest.get("growthStage") or _estimate_growth_stage(month)
    gs_enc       = float(GROWTH_STAGE_MAP.get(growth_stage, 0))

    cols = _fert_pkg["feature_columns"]
    df = pd.DataFrame([[
        float(latest.get("daysSinceLastFertilize", 7.0)),
        gs_enc,
        float(month),
        float(latest.get("rootMoisturePct", 50.0)),
        float(latest.get("temperature",    28.0)),
        float(latest.get("humidity",       70.0)),
    ]], columns=cols)
    scaled = _fert_pkg["scaler"].transform(df)
    pred   = _fert_pkg["model"].predict(scaled)[0]
    label  = _fert_pkg["label_encoder"].inverse_transform([pred])[0]

    if label == "Yes":
        fert_type = "High-N (30-10-10)" if growth_stage == "Active" else "High-P (10-30-20)"
    else:
        fert_type = "None"
    return label, fert_type


def _decide_action(water_needed: str, fertilize_needed: str) -> str:
    if water_needed == "No":
        return "IDLE"
    if fertilize_needed == "Yes":
        return "WATER_AND_FERTILIZE"
    return "WATER_ONLY"


# ======================== ROUTES ========================

@router.get("/sensor-data")
async def get_sensor_data():
    """
    Return the current sensor snapshot from Firebase /latest.
    Written by the ESP32 every 5 minutes.
    """
    data = _fb_get("/latest.json")
    if not data:
        raise HTTPException(status_code=503, detail="No sensor data in Firebase /latest")
    return {"status": "success", "data": data}


@router.post("/predict")
async def predict():
    """
    Run both ML models on the current sensor reading and write the
    combined prediction to Firebase /prediction.

    Flow:
      1. Fetch /latest  (current sensor snapshot)
      2. Fetch last 30 /history records → compute MoistureTrend, DryingRate
      3. Watering model  (Random Forest, 8 features) → WaterNeeded + confidence
      4. Fertilization model (Decision Tree, 6 features) → FertilizeNeeded + type
      5. Write prediction to Firebase /prediction (mobile app reads this)
      6. Return prediction payload
    """
    if not _models_ready():
        raise HTTPException(
            status_code=503,
            detail=f"ML models not loaded. Expected path: {_MODEL_DIR}"
        )

    latest = _fb_get("/latest.json")
    if not latest:
        raise HTTPException(status_code=503, detail="No sensor data in Firebase /latest")

    moisture_trend, drying_rate     = _compute_trend_features(latest)
    water_needed, confidence         = _predict_watering(latest, moisture_trend, drying_rate)
    fertilize_needed, fert_type      = _predict_fertilization(latest)
    action                           = _decide_action(water_needed, fertilize_needed)

    prediction = {
        "waterNeeded":      water_needed,
        "fertilizerNeeded": fertilize_needed,   # mobile app reads this key
        "fertilizerType":   fert_type,
        "confidence":       round(confidence * 100, 1),
        "action":           action,
        "features": {
            "moistureTrend": moisture_trend,
            "dryingRate":    drying_rate,
        },
        "sensorSnapshot": {
            "temperature":       latest.get("temperature"),
            "humidity":          latest.get("humidity"),
            "light":             latest.get("light"),
            "rootMoisturePct":   latest.get("rootMoisturePct"),
            "hoursSinceWater":   latest.get("hoursSinceWater"),
        },
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }

    _fb_put("/prediction.json", prediction)
    return {"status": "success", "prediction": prediction}


@router.get("/prediction")
async def get_prediction():
    """
    Return the latest ML prediction from Firebase /prediction.
    The mobile app also reads /prediction directly via Firebase SDK.
    """
    data = _fb_get("/prediction.json")
    if not data:
        raise HTTPException(
            status_code=404,
            detail="No prediction available yet. POST /api/v1/watering/predict to generate one."
        )
    return {"status": "success", "prediction": data}


@router.get("/history")
async def get_history(limit: int = Query(default=50, ge=1, le=288)):
    """
    Return recent sensor readings from Firebase /history.
    limit: number of records (1–288, default 50; 288 = one full day at 5-min intervals).
    Records are returned sorted oldest-first.
    """
    raw = _fb_get(f'/history.json?orderBy="$key"&limitToLast={limit}')
    if not raw:
        return {"status": "success", "count": 0, "data": []}
    records = sorted(raw.values(), key=lambda r: r.get("timestamp", 0))
    return {"status": "success", "count": len(records), "data": records}


# ── Visual hydration → action recommendation mapping ─────────────────────────

_VISUAL_ACTION = {
    "underhydrated": "WATER_NOW",
    "control":       "MONITOR",
    "overhydrated":  "REDUCE_WATERING",
}

_VISUAL_LABEL = {
    "underhydrated": "Plant appears dry — leaves may be wrinkled or lighter in colour",
    "control":       "Plant hydration looks healthy",
    "overhydrated":  "Plant appears over-watered — check for root rot",
}


def _fuse_predictions(sensor_water: Optional[str], visual_class: str) -> dict:
    """
    Combine sensor-based watering prediction with visual hydration class.

    Agreement table:
      sensor=Yes + visual=underhydrated → HIGH confidence WATER
      sensor=Yes + visual=control       → MODERATE confidence WATER (sensor leads)
      sensor=Yes + visual=overhydrated  → CONFLICT — defer to user
      sensor=No  + visual=underhydrated → CONFLICT — visual warns, sensor says ok
      sensor=No  + visual=control       → HIGH confidence IDLE
      sensor=No  + visual=overhydrated  → HIGH confidence IDLE / reduce schedule
    """
    if sensor_water is None:
        return {"agreement": "sensor_unavailable", "fused_action": _VISUAL_ACTION[visual_class]}

    if sensor_water == "Yes" and visual_class == "underhydrated":
        return {"agreement": "high",     "fused_action": "WATER_NOW",
                "note": "Both sensor and camera confirm plant needs water."}
    if sensor_water == "Yes" and visual_class == "control":
        return {"agreement": "moderate", "fused_action": "WATER_NOW",
                "note": "Sensor signals watering needed; plant looks healthy visually."}
    if sensor_water == "Yes" and visual_class == "overhydrated":
        return {"agreement": "conflict", "fused_action": "REVIEW",
                "note": "Sensor says water; camera detects over-watering. Manual check recommended."}
    if sensor_water == "No" and visual_class == "underhydrated":
        return {"agreement": "conflict", "fused_action": "REVIEW",
                "note": "Sensor says ok; camera detects dryness. Check moisture sensor calibration."}
    if sensor_water == "No" and visual_class == "control":
        return {"agreement": "high",     "fused_action": "IDLE",
                "note": "Both sensor and camera confirm plant is well-hydrated."}
    # sensor=No + visual=overhydrated
    return {"agreement": "high", "fused_action": "IDLE",
            "note": "Sensor and camera both indicate no watering needed; plant may be over-watered."}


@router.post("/image-predict")
async def image_predict(file: UploadFile = File(...)):
    """
    Visual Hydration Classification via CNN (MobileNetV2).

    Accepts a JPEG image from the ESP32-CAM and returns:
      - visual_class     : control | underhydrated | overhydrated
      - confidence       : 0–100 %
      - recommendation   : human-readable label
      - action           : WATER_NOW | MONITOR | REDUCE_WATERING
      - fusion           : agreement level with the latest sensor-based prediction

    The CNN was trained on the orchid hydration dataset (2 160 leaf images,
    70/20/10 train/val/test split, MobileNetV2 backbone, ImageNet weights).

    Multi-modal fusion:
      This endpoint also fetches the latest sensor-based prediction from
      Firebase /prediction and compares it with the visual result, returning
      a fused confidence level and recommended action.
    """
    if _vision_model is None:
        raise HTTPException(
            status_code=503,
            detail="Visual hydration model not loaded. Run ml_pipeline/visual_hydration_training.py first."
        )

    # ── Read and preprocess the uploaded image ────────────────────────────────
    contents = await file.read()
    try:
        import tensorflow as tf
        img = tf.image.decode_jpeg(contents, channels=3)
        img = tf.image.resize(img, (224, 224))
        img = tf.keras.applications.mobilenet_v2.preprocess_input(
            tf.cast(img, tf.float32)
        )
        img = tf.expand_dims(img, 0)   # shape: (1, 224, 224, 3)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image: {e}")

    # ── CNN inference ─────────────────────────────────────────────────────────
    probs       = _vision_model.predict(img, verbose=0)[0]   # shape: (3,)
    class_idx   = int(np.argmax(probs))
    visual_class = _vision_classes[class_idx]
    confidence  = round(float(probs[class_idx]) * 100, 1)

    # ── Fetch latest sensor prediction for fusion ─────────────────────────────
    sensor_pred = _fb_get("/prediction.json")
    sensor_water = sensor_pred.get("waterNeeded") if sensor_pred else None

    fusion = _fuse_predictions(sensor_water, visual_class)

    # All class probabilities for transparency
    all_probs = {_vision_classes[i]: round(float(probs[i]) * 100, 1) for i in range(len(_vision_classes))}

    return {
        "status":          "success",
        "visual_class":    visual_class,
        "confidence":      confidence,
        "recommendation":  _VISUAL_LABEL[visual_class],
        "action":          _VISUAL_ACTION[visual_class],
        "all_probabilities": all_probs,
        "fusion":          fusion,
        "sensor_watering": sensor_water,
        "timestamp":       datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
