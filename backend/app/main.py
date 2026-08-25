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
# from app.api.routes import disease_detection
# from app.api.routes import growth_stage
from app.api.routes import smart_watering
from app.api.routes import hybrid_pollination

# app.include_router(disease_detection.router, prefix="/api/v1/disease",     tags=["Disease Detection"])
# app.include_router(growth_stage.router,      prefix="/api/v1/growth",      tags=["Growth Stage"])
app.include_router(smart_watering.router,     prefix="/api/v1/watering",    tags=["Smart Watering"])
app.include_router(hybrid_pollination.router, prefix="/api/v1/pollination", tags=["Hybrid Pollination"])
