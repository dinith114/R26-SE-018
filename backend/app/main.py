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
from app.api.routes import smart_watering
from app.api.routes import hybrid_pollination

# app.include_router(disease_detection.router, prefix="/api/v1/disease",     tags=["Disease Detection"])
# app.include_router(growth_stage.router,      prefix="/api/v1/growth",      tags=["Growth Stage"])
app.include_router(smart_watering.router,     prefix="/api/v1/watering",    tags=["Smart Watering"])
app.include_router(hybrid_pollination.router, prefix="/api/v1/pollination", tags=["Hybrid Pollination"])
