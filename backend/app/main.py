"""
AI-Powered Smart Orchid Care System - Backend API
FastAPI application entry point
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
import uvicorn

# Route imports - MUST BE AT THE TOP
from app.api.routes import growth_stage
from app.api.routes import bloom_prediction

app = FastAPI(
    title="Smart Orchid Care API",
    description="AI-Powered Smart Orchid Care System Using Multi-Modal Machine Learning",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc"
)

# CORS middleware for React Native mobile app
# ── Write protection ──────────────────────────────────────────────────────────
#
# The backend is on a public host now, and the endpoints below can start a pump,
# open a valve, or move a node onto a different Wi-Fi network. Scanners find a
# new address within minutes, so anything that CHANGES state needs a key.
#
# Deliberately narrow:
#   * GET is left open. The worst a reader gets is farm telemetry, and keeping
#     reads open means Components 1, 2 and 4 - which use their own fetch code -
#     are not broken by this.
#   * Only /api/v2/* is covered. That is where every water and hardware command
#     lives; the v1 routes are prediction endpoints that touch no hardware.
#
# The key is read from the environment. If ORCHID_API_KEY is unset the check is
# skipped entirely, so a laptop run stays exactly as it was.
import os as _os
from fastapi import Request as _Request
from fastapi.responses import JSONResponse as _JSONResponse

ORCHID_API_KEY = _os.environ.get("ORCHID_API_KEY", "").strip()
_GUARDED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_GUARDED_PREFIX = "/api/v2/"


@app.middleware("http")
async def _require_api_key(request: _Request, call_next):
    if (ORCHID_API_KEY
            and request.method in _GUARDED_METHODS
            and request.url.path.startswith(_GUARDED_PREFIX)):
        if request.headers.get("x-api-key", "") != ORCHID_API_KEY:
            return _JSONResponse(
                status_code=401,
                content={"detail": "This action needs an API key. The app sends one "
                                   "automatically; if you are seeing this in the app, "
                                   "it is out of date and needs rebuilding."})
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:19006",     # Expo web
        "http://localhost:19000",     # Expo
        "exp://localhost:19000",      # Expo
        "http://localhost:8081",      # React Native
        "http://localhost:5000",      # Development
        "*"                           # For development only
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(
    growth_stage.router,
    prefix="/api/v1/growth",
    tags=["Growth Stage Recognition"]
)
app.include_router(
    bloom_prediction.router,
    prefix="/api/v1/bloom",
    tags=["Bloom Date Prediction"]
)

# Additional routers (uncomment as components are developed)
# app.include_router(disease_detection.router, prefix="/api/v1/disease", tags=["Disease Detection"])
# app.include_router(smart_watering.router, prefix="/api/v1/watering", tags=["Smart Watering"])
# app.include_router(hybrid_pollination.router, prefix="/api/v1/pollination", tags=["Hybrid Pollination"])


@app.get("/")
async def root():
    return {
        "project": "AI-Powered Smart Orchid Care System",
        "project_id": "R26-SE-018",
        "version": "1.0.0",
        "status": "running",
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
# -------------------------------------------------------------------
# Route imports (uncomment as components are developed)
# -------------------------------------------------------------------
from app.api.routes import disease_detection

app.include_router(
    disease_detection.router,
    prefix="/api/v1/disease",
    tags=["Disease Detection"],
)

# Still stubs -- leave commented until each component is implemented.
# from app.api.routes import growth_stage
# from app.api.routes import smart_watering
# from app.api.routes import hybrid_pollination
#
# app.include_router(growth_stage.router,      prefix="/api/v1/growth",       tags=["Growth Stage"])
# app.include_router(smart_watering.router,     prefix="/api/v1/watering",     tags=["Smart Watering"])
# app.include_router(hybrid_pollination.router,  prefix="/api/v1/pollination",  tags=["Hybrid Pollination"])
from app.api.routes import devices
from app.api.routes import smart_watering
from app.api.routes import hybrid_pollination
from app.api.routes import house_planner
from app.api.routes import houses
from app.api.routes import smart_care_v2
from app.api.routes import automation

# app.include_router(disease_detection.router, prefix="/api/v1/disease",     tags=["Disease Detection"])
# app.include_router(growth_stage.router,      prefix="/api/v1/growth",      tags=["Growth Stage"])
app.include_router(smart_watering.router,     prefix="/api/v1/watering",    tags=["Smart Watering"])
app.include_router(hybrid_pollination.router, prefix="/api/v1/pollination", tags=["Hybrid Pollination"])
app.include_router(house_planner.router,      prefix="/api/v2/care/houses", tags=["House Planner"])
app.include_router(houses.router,             prefix="/api/v1/houses",      tags=["Houses"])
app.include_router(smart_care_v2.router,      prefix="/api/v2/care",        tags=["Smart Care v2"])
app.include_router(devices.router,            prefix="/api/v2/devices",     tags=["Devices"])
app.include_router(automation.router,         prefix="/api/v2/auto",        tags=["Automation Engine"])

from app.api.routes import accounts
app.include_router(accounts.router, prefix="/api/v2/accounts", tags=["Accounts"])


@app.on_event("startup")
async def _start_automation():
    """Start the clock that actually runs the farm.

    Without this the models decide correctly but nothing ever asks them, so
    trays are never filled and the mandatory daily watering never happens.
    """
    automation.start_engine()
