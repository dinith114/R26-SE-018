"""
AI-Powered Smart Orchid Care System - Backend API
FastAPI application entry point
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Smart Orchid Care API",
    description="AI-Powered Smart Orchid Care System Using Multi-Modal Machine Learning",
    version="1.0.0",
)

# CORS middleware for React Native mobile app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update with specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


# -------------------------------------------------------------------
# Route imports (uncomment as components are developed)
# -------------------------------------------------------------------
# from app.api.routes import disease_detection
# from app.api.routes import growth_stage
from app.api.routes import devices
from app.api.routes import smart_watering
from app.api.routes import hybrid_pollination
from app.api.routes import farm_planner
from app.api.routes import farm_scan
from app.api.routes import houses
from app.api.routes import smart_care_v2
from app.api.routes import automation

# app.include_router(disease_detection.router, prefix="/api/v1/disease",     tags=["Disease Detection"])
# app.include_router(growth_stage.router,      prefix="/api/v1/growth",      tags=["Growth Stage"])
app.include_router(smart_watering.router,     prefix="/api/v1/watering",    tags=["Smart Watering"])
app.include_router(hybrid_pollination.router, prefix="/api/v1/pollination", tags=["Hybrid Pollination"])
app.include_router(farm_planner.router,       prefix="/api/v1/farm",        tags=["Farm Planner"])
app.include_router(farm_scan.router,          prefix="/api/v1/farm",        tags=["Farm Survey"])
app.include_router(houses.router,             prefix="/api/v1/houses",      tags=["Houses"])
app.include_router(smart_care_v2.router,      prefix="/api/v2/care",        tags=["Smart Care v2"])
app.include_router(devices.router,            prefix="/api/v2/devices",     tags=["Devices"])
app.include_router(automation.router,         prefix="/api/v2/auto",        tags=["Automation Engine"])


@app.on_event("startup")
async def _start_automation():
    """Start the clock that actually runs the farm.

    Without this the models decide correctly but nothing ever asks them, so
    trays are never filled and the mandatory daily watering never happens.
    """
    automation.start_engine()
