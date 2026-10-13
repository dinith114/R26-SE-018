"""
Multi-House Management — per-house / per-zone data, prediction and watering control.

Firebase layout (non-destructive: lives alongside the legacy flat /latest paths):

  /houses/{houseId}/
    meta:             { name, type, plantCount, zoneCount }
    zones/{zoneId}/
      latest:         { temperature, humidity, light, rootMoisturePct, hoursSinceWater, timestamp }
      history/{push}: same fields
      prediction:     { waterNeeded, fertilizerNeeded, confidence, ... }
    housePrediction:  { waterNeeded, worstZone, confidence, timestamp }
    control:          { autoWater, thresholds{...}, waterCommand{...} }

Endpoints:
  GET  /houses                     → all houses summary (meta + housePrediction + zone latests)
  GET  /houses/{id}                → one house in full
  POST /houses/{id}/predict        → run ML per zone, write zone predictions + house rollup
  POST /houses/predict-all         → same, for every house
  POST /houses/{id}/water          → one-click water command (written to control.waterCommand)
  PUT  /houses/{id}/control        → update autoWater / thresholds
"""

from datetime import datetime, timezone
from typing import Optional, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.routes.smart_watering import (
    _fb_get, _fb_put, _models_ready,
    _predict_watering, _predict_fertilization, _decide_action,
    LOOKBACK_READINGS, HISTORY_FETCH_SIZE,
)

router = APIRouter()

# Sensor-failure sentinel written by the firmware on read errors
SENTINEL = -999

# Training-data defaults used when a sensor value is missing or failed
SAFE_DEFAULTS = {
    "temperature":     28.0,
    "humidity":        70.0,
    "light":           0.0,
    "rootMoisturePct": 50.0,
    "hoursSinceWater": 12.0,
}


def _clamp_sentinels(reading: dict) -> dict:
    """Replace -999 sensor-failure values (and missing keys) with training-range defaults.

    The models were trained on light 0-15000 lux, temp 22-36 C etc. — a raw -999
    is far out of distribution and corrupts the prediction.
    """
    clean = dict(reading)
    for key, default in SAFE_DEFAULTS.items():
        val = clean.get(key)
        try:
            val = float(val)
        except (TypeError, ValueError):
            val = None
        if val is None or val <= SENTINEL:
            clean[key] = default
        else:
            clean[key] = val
    return clean


def _zone_trend_features(house_id: str, zone_id: str, latest: dict) -> tuple[float, float]:
    """MoistureTrend / DryingRate over the zone's own history (2-hour window)."""
    try:
        raw = _fb_get(
            f'/houses/{house_id}/zones/{zone_id}/history.json'
            f'?orderBy="$key"&limitToLast={HISTORY_FETCH_SIZE}'
        )
        if not raw:
            return 0.0, 0.0
        records = sorted(raw.values(), key=lambda r: r.get("timestamp", 0))
        current = float(latest.get("rootMoisturePct", 50.0))
        if len(records) >= LOOKBACK_READINGS:
            past = float(records[-LOOKBACK_READINGS].get("rootMoisturePct", current))
        else:
            past = current
        hours = (LOOKBACK_READINGS * 5) / 60.0
        return round(current - past, 2), round(max(0.0, (past - current) / hours), 2)
    except Exception:
        return 0.0, 0.0


def _predict_zone(house_id: str, zone_id: str, latest: dict) -> dict:
    """Run both ML models on one zone's clamped reading."""
    clean = _clamp_sentinels(latest)
    trend, drying = _zone_trend_features(house_id, zone_id, clean)
    water, conf   = _predict_watering(clean, trend, drying)
    fert, ftype   = _predict_fertilization(clean)
    return {
        "waterNeeded":      water,
        "fertilizerNeeded": fert,
        "fertilizerType":   ftype,
        "confidence":       round(conf * 100, 1),
        "action":           _decide_action(water, fert),
        "features":         {"moistureTrend": trend, "dryingRate": drying},
        "timestamp":        datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }


def _predict_house(house_id: str, house: dict) -> dict:
    """Predict every zone of a house, write results, return the house rollup."""
    zones = house.get("zones") or {}
    zone_preds = {}
    for zone_id, zone in zones.items():
        latest = (zone or {}).get("latest")
        if not latest:
            continue
        pred = _predict_zone(house_id, zone_id, latest)
        zone_preds[zone_id] = pred
        _fb_put(f"/houses/{house_id}/zones/{zone_id}/prediction.json", pred)

    if not zone_preds:
        rollup = {"waterNeeded": "Unknown", "worstZone": None, "confidence": 0,
                  "zonesEvaluated": 0,
                  "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}
    else:
        # House needs water if ANY zone needs it; worst zone = needy zone with highest confidence
        needy = {z: p for z, p in zone_preds.items() if p["waterNeeded"] == "Yes"}
        if needy:
            worst = max(needy, key=lambda z: needy[z]["confidence"])
            rollup = {"waterNeeded": "Yes", "worstZone": worst,
                      "confidence": needy[worst]["confidence"],
                      "zonesNeedingWater": len(needy), "zonesEvaluated": len(zone_preds)}
        else:
            best = max(zone_preds, key=lambda z: zone_preds[z]["confidence"])
            rollup = {"waterNeeded": "No", "worstZone": None,
                      "confidence": zone_preds[best]["confidence"],
                      "zonesNeedingWater": 0, "zonesEvaluated": len(zone_preds)}
        rollup["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    _fb_put(f"/houses/{house_id}/housePrediction.json", rollup)
    return {"housePrediction": rollup, "zonePredictions": zone_preds}


# ─────────────────────────────── Endpoints ────────────────────────────────────

@router.get("")
async def list_houses():
    """Summary of every house: meta, rollup prediction and each zone's latest reading."""
    houses = _fb_get("/houses.json")
    if not houses:
        return {"status": "success", "count": 0, "houses": []}

    out = []
    for house_id, house in houses.items():
        if not isinstance(house, dict):
            continue
        zones = house.get("zones") or {}
        zone_summaries = []
        for zone_id, zone in sorted(zones.items()):
            latest = (zone or {}).get("latest") or {}
            zone_summaries.append({
                "zoneId":     zone_id,
                "latest":     latest,
                "prediction": (zone or {}).get("prediction"),
            })
        out.append({
            "houseId":         house_id,
            "meta":            house.get("meta", {}),
            "housePrediction": house.get("housePrediction"),
            "control":         house.get("control", {}),
            "zones":           zone_summaries,
        })
    return {"status": "success", "count": len(out), "houses": out}


@router.get("/{house_id}")
async def get_house(house_id: str):
    house = _fb_get(f"/houses/{house_id}.json")
    if not house:
        raise HTTPException(404, f"House '{house_id}' not found")
    return {"status": "success", "houseId": house_id, "house": house}


@router.post("/{house_id}/predict")
async def predict_house(house_id: str):
    """Run the watering + fertilization models on every zone of this house."""
    if not _models_ready():
        raise HTTPException(503, "ML models not loaded")
    house = _fb_get(f"/houses/{house_id}.json")
    if not house:
        raise HTTPException(404, f"House '{house_id}' not found")
    result = _predict_house(house_id, house)
    return {"status": "success", "houseId": house_id, **result}


@router.post("/predict-all")
async def predict_all_houses():
    """Run prediction for every house (call this on a schedule)."""
    if not _models_ready():
        raise HTTPException(503, "ML models not loaded")
    houses = _fb_get("/houses.json")
    if not houses:
        return {"status": "success", "housesEvaluated": 0}
    results = {}
    for house_id, house in houses.items():
        if isinstance(house, dict):
            results[house_id] = _predict_house(house_id, house)["housePrediction"]
    return {"status": "success", "housesEvaluated": len(results), "results": results}


class WaterRequest(BaseModel):
    duration_sec: int = 30
    triggered_by: str = "user"


def _house_needs_fertilizer(house: dict) -> Optional[str]:
    """
    Check every zone's last prediction for fertilizerNeeded=Yes.
    Fertilizer is only ever delivered together with water (never to dry roots),
    so this is folded into the water command rather than a separate line/command.
    Returns the fertilizer type (High-N / High-P) of the first needy zone, or None.
    """
    zones = (house or {}).get("zones") or {}
    for zone in zones.values():
        pred = (zone or {}).get("prediction") or {}
        if pred.get("fertilizerNeeded") == "Yes":
            return pred.get("fertilizerType")
    return None


@router.post("/{house_id}/water")
async def water_house(house_id: str, req: WaterRequest):
    """
    One-click watering: write a water command for this house's actuator to pick up.

    Also auto-attaches a fertilizer dose if any zone's last prediction says
    fertilizerNeeded=Yes — the firmware fires a second relay (dosing pump) for a
    short window during the same watering run, per NPK type (High-N/High-P).
    """
    house = _fb_get(f"/houses/{house_id}.json")
    if not house:
        raise HTTPException(404, f"House '{house_id}' not found")

    fert_type = _house_needs_fertilizer(house)
    command = {
        "requested":     True,
        "durationSec":   max(5, min(req.duration_sec, 300)),
        "triggeredBy":   req.triggered_by,
        "fertilize":     fert_type is not None,
        "fertilizerType": fert_type,
        "timestamp":     datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    ok = _fb_put(f"/houses/{house_id}/control/waterCommand.json", command)
    if not ok:
        raise HTTPException(502, "Failed to write water command to Firebase")
    return {"status": "success", "houseId": house_id, "waterCommand": command}


class ControlUpdate(BaseModel):
    autoWater:  Optional[bool] = None
    thresholds: Optional[Dict[str, float]] = None


@router.put("/{house_id}/control")
async def update_control(house_id: str, req: ControlUpdate):
    """Update a house's auto-water flag and/or custom thresholds."""
    house = _fb_get(f"/houses/{house_id}.json")
    if not house:
        raise HTTPException(404, f"House '{house_id}' not found")
    updated = {}
    if req.autoWater is not None:
        _fb_put(f"/houses/{house_id}/control/autoWater.json", req.autoWater)
        updated["autoWater"] = req.autoWater
    if req.thresholds:
        _fb_put(f"/houses/{house_id}/control/thresholds.json", req.thresholds)
        updated["thresholds"] = req.thresholds
    return {"status": "success", "houseId": house_id, "updated": updated}
