"""
Day-ahead forecast — the anticipatory half of humidity control.

Everything else in this system is reactive: wait for humidity to fall, then fill
the tray. But a 3 cm tray needs time for its water to evaporate, so by the time
low humidity is measured the plant has already been under stress for a while.

This module predicts, from the dawn reading, how the rest of today will go in
each section, and lets the tray be topped up BEFORE the heat arrives.

HOW IT IS TRUSTED
-----------------
The model is deliberately used as an ACCELERATOR, never as a gate:

  * If it predicts a hot afternoon, the tray is topped up early.
  * If it predicts nothing, the ordinary reactive logic runs exactly as before.

That matters because recall is 0.78 — it still misses about a fifth of hot days.
Precision is 0.98, so when it does speak it is almost always right. Used this
way a miss costs nothing (the reactive path still catches it) and a hit buys
hours of warning; used as a gate it would skip watering on the days it missed.

The dawn reading alone gave recall 0.62. Adding the outdoor weather forecast
(see _fetch_outdoor) lifted it to 0.78 and halved peak-temperature error.
"""

import json
import os
import joblib
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Optional

import numpy as np

_MODEL_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "..", "..", "..", "..", "ml_pipeline", "results"))

_fc: Optional[dict] = None

try:
    _fc = joblib.load(os.path.join(_MODEL_DIR, "forecast_v2.pkl"))
    m = _fc["metrics"]
    print(f"[ML v2] Forecast      temp MAE={m['temp']['mae']:.2f}C  "
          f"peak MAE={m['peak_temp_mae']:.2f}C  hot-day F1={m['hot_day_f1']:.3f}")
except Exception as e:
    print(f"[WARN] forecast model not loaded: {e}")
    print("[WARN] Run: python ml_pipeline/build_forecast_model.py")


def ready() -> bool:
    return _fc is not None


# ─────────────── Outdoor forecast from the weather service ───────────────────
# The model's biggest blind spot was cloud: at 05:00 there is no light yet, so a
# day that turns cloudy looks like a clear one. A national weather service
# already predicts cloud well, so we fetch it instead of guessing. Adding these
# five outdoor fields cut peak-temperature error from 1.04 C to 0.49 C and lifted
# hot-day recall from 0.62 to 0.78.
#
# No sensor is involved: the BACKEND downloads this. The farm has Wi-Fi and the
# ESP32 never sees it.
# The farm's coordinates are a SETTING, not a constant. Open-Meteo covers the
# whole globe, so a farm in Battaramulla or anywhere else works by writing
# /farm/meta/{latitude,longitude}. Defaults to Peradeniya, where the model was
# trained.
#
# IMPORTANT: moving the farm changes the weather but NOT the model. Peradeniya
# (hill country) averages 24.1 C / 82% RH; Battaramulla (coastal) averages
# 26.4 C / 85%. For a different site, re-run fetch_real_weather.py with those
# coordinates and retrain, or the local-delta the model learned will be wrong.
DEFAULT_LAT, DEFAULT_LON = 7.2683, 80.5960     # Peradeniya
# {(tenant, date): features}, one fetch per farm per day.
#
# KEYED BY TENANT, and it was not until the final review. Keyed by date alone it
# held exactly one farm's weather - the .clear() below guaranteed that - and
# run_all_tenants walks every tenant inside one tick, so the first farm's
# coordinates decided every other farm's forecast for the rest of the day.
# Same shape as the timezone and auto-mode caches, found two rounds later.
from app.services.tenant_context import current_tenant

_outdoor_cache: dict = {}


def farm_location() -> tuple:
    """Where this farm actually is, from farm settings."""
    try:
        from app.api.routes.smart_care_v2 import _fb_get
        meta = _fb_get("/farm/meta.json") or {}
        lat = float(meta.get("latitude", DEFAULT_LAT))
        lon = float(meta.get("longitude", DEFAULT_LON))
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            return lat, lon
    except Exception:
        pass
    return DEFAULT_LAT, DEFAULT_LON


def _fetch_outdoor(today: str) -> Optional[dict]:
    """Today's outdoor forecast, aggregated exactly as in training."""
    key = (current_tenant(), today)
    if key in _outdoor_cache:
        return _outdoor_cache[key]
    try:
        lat, lon = farm_location()
        url = ("https://api.open-meteo.com/v1/forecast"
               f"?latitude={lat}&longitude={lon}"
               "&hourly=temperature_2m,relative_humidity_2m,shortwave_radiation"
               "&forecast_days=1&timezone=" + urllib.parse.quote("Asia/Colombo"))
        with urllib.request.urlopen(url, timeout=12) as r:
            h = json.load(r)["hourly"]
        temps = [v for v in h["temperature_2m"] if v is not None]
        rhs = [v for v in h["relative_humidity_2m"] if v is not None]
        rad = [v for v in h["shortwave_radiation"] if v is not None]
        if not temps or not rhs or not rad:
            return None
        month = int(today[5:7])
        radsum = float(sum(rad))
        # `_fc or {}` because the model may not be loaded at all. This used to be
        # `_fc.get(...)`, which raises AttributeError when the pickle is absent -
        # and the blanket except below then reported it as "outdoor forecast
        # unavailable", which reads as a network problem and sends whoever is
        # debugging it after the wrong fault. In production predict_day guards
        # this behind ready(), so _fc is never None there; CI has no model file
        # and calls this helper directly, which is where it surfaced.
        #
        # A missing model only costs the clearness CALIBRATION. Falling through
        # to radsum makes clearness 1.0, which is the honest answer when there
        # is no reference to compare today against.
        monthly = (_fc or {}).get("monthly_peak_radsum") or {}
        peak_ref = monthly.get(month) or monthly.get(str(month)) or radsum or 1.0
        feats = {
            "out_tmax": float(max(temps)),
            "out_rhmin": float(min(rhs)),
            "out_radsum": radsum,
            "out_radmax": float(max(rad)),
            "out_clearness": round(radsum / float(peak_ref), 3),
        }
        # Drop only THIS farm's stale days, not every farm's entry.
        for k in [k for k in _outdoor_cache if k[0] == key[0]]:
            del _outdoor_cache[k]
        _outdoor_cache[key] = feats
        return feats
    except Exception as e:
        # Usually no internet, or the service is down. The farm must keep running,
        # so we fall back to the dawn-only path rather than failing the whole plan.
        #
        # The exception TYPE is in the message on purpose. This catch is broad by
        # design, which means it also swallows programming errors, and for a
        # while it was doing exactly that - an AttributeError from a missing
        # model was being reported as the forecast service being unavailable.
        # URLError means look at the network; anything else means look at the code.
        print(f"[WARN] outdoor forecast unavailable ({type(e).__name__}: {e}); "
              f"using dawn readings only")
        return None


def predict_day(dawn: dict, month: int, light_exposure: float,
                yesterday_peak: float) -> Optional[dict]:
    """Predict today's hourly temperature and humidity from the dawn reading,
    plus the outdoor forecast when the model was trained to use it."""
    if not ready():
        return None

    from app.api.routes.smart_care_v2 import vpd_kpa

    feats = np.array([[
        float(dawn.get("temperature", 26.0)),
        float(dawn.get("humidity", 80.0)),
        float(dawn.get("light", 0.0)),
        vpd_kpa(float(dawn.get("temperature", 26.0)), float(dawn.get("humidity", 80.0))),
        float(month),
        float(light_exposure),
        float(yesterday_peak),
    ]])
    if _fc.get("uses_weather_service"):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        od = _fetch_outdoor(today)
        if od is None:
            return None            # caller keeps yesterday's forecast rather than a bad one
        feats = np.hstack([feats, np.array([[od["out_tmax"], od["out_rhmin"],
                                             od["out_radsum"], od["out_radmax"],
                                             od["out_clearness"]]])])

    out = _fc["model"].predict(_fc["scaler"].transform(feats))[0]

    hours = _fc["hours"]
    n = len(hours)
    temps = [round(float(v), 1) for v in out[:n]]
    hums = [round(float(v), 1) for v in out[n:]]

    peak_i = int(np.argmax(temps))
    dry_i = int(np.argmin(hums))
    vpds = [vpd_kpa(t, h) for t, h in zip(temps, hums)]

    return {
        "hours": hours,
        "temperature": temps,
        "humidity": hums,
        "vpd": vpds,
        "peakTemp": temps[peak_i],
        "peakHour": hours[peak_i],
        "minHumidity": hums[dry_i],
        "minHumidityHour": hours[dry_i],
        "meanVpd": round(float(np.mean(vpds)), 3),
        "hotDay": bool(temps[peak_i] >= _fc["hot_threshold"]),
        "hotThreshold": _fc["hot_threshold"],
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        # so the app can be honest about how much to trust it
        "confidence": {
            "peakTempMae": _fc["metrics"]["peak_temp_mae"],
            "hotDayPrecision": _fc["metrics"]["hot_day_precision"],
            "hotDayRecall": _fc["metrics"]["hot_day_recall"],
        },
    }


# How far ahead we are willing to act. Below 1 h there is no time for the water
# to evaporate; beyond 4 h the tray would be refilled again anyway.
LEAD_MIN_HOURS = 1.0
LEAD_MAX_HOURS = 4.0
PREFILL_RH = 62.0      # only pre-fill if the air is already drying toward the floor


