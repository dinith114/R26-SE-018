"""
Hybrid Pollination & Compatibility Analysis - API Routes
Component 4: IT22065230 – Wickramasinghe D.P

Level 1: Pollination Readiness / Suitability Assessment
"""

import os
import tempfile
import shutil
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from typing import Optional

from app.models.schemas import (
    PlantTraitsInput, SuitabilityResponse, HealthResponse, ErrorResponse
)
from app.services.hybrid_pollination_service import pollination_service

router = APIRouter()

# Allowed image extensions
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff"}


def validate_image(file: UploadFile):
    """Validate uploaded file is a supported image."""
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Allowed: {ALLOWED_EXTENSIONS}"
        )


@router.post("/assess", response_model=SuitabilityResponse)
async def assess_suitability(
    image: UploadFile = File(..., description="Plant image to assess"),
    leaf_condition: Optional[str] = Form("unknown"),
    plant_strength: Optional[str] = Form("unknown"),
    disease_visible: Optional[str] = Form("unknown"),
    flower_condition: Optional[str] = Form("unknown"),
):
    """
    Assess pollination suitability of a single orchid plant.

    Upload a plant image and optionally provide trait data.
    Returns a suitability prediction (Suitable / Moderate / Not Suitable)
    with confidence score and recommendation.
    """
    validate_image(image)

    if not pollination_service.is_loaded:
        raise HTTPException(
            status_code=503,
            detail="Model not loaded. Please train the model first."
        )

    # Save uploaded file temporarily
    temp_dir = tempfile.mkdtemp()
    temp_path = os.path.join(temp_dir, image.filename or "upload.jpg")

    try:
        with open(temp_path, "wb") as f:
            content = await image.read()
            f.write(content)

        # Build traits dict
        traits = {
            "leaf_condition": leaf_condition,
            "plant_strength": plant_strength,
            "disease_visible": disease_visible,
            "flower_condition": flower_condition,
        }

        # Predict
        result = pollination_service.predict_suitability(temp_path, traits)

        return SuitabilityResponse(**result)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")

    finally:
        # Cleanup temp file
        shutil.rmtree(temp_dir, ignore_errors=True)


@router.get("/health", response_model=HealthResponse)
async def pollination_health():
    """Check if the pollination model is loaded and ready."""
    info = pollination_service.get_model_info()
    return HealthResponse(
        status="ready" if info["model_loaded"] else "model_not_loaded",
        model_loaded=info["model_loaded"],
        model_name=info["model_name"],
        classes=info["classes"],
    )


@router.get("/guidance")
async def get_pollination_guidance(
    suitability: str = "Suitable"
):
    """
    Get pollination guidance based on plant suitability.
    """
    guidance = {
        "Suitable": {
            "status": "Ready for Pollination",
            "steps": [
                "1. Select a healthy pollen donor plant (also assessed as 'Suitable')",
                "2. Identify the column and pollinia on the donor flower",
                "3. Carefully remove pollinia using a sterile toothpick or needle",
                "4. Transfer pollinia to the stigmatic surface of the receiver flower",
                "5. Label the pollinated flower with date and parent information",
                "6. Monitor for seed pod development over 2-4 weeks",
                "7. Maintain optimal conditions: 70-80% humidity, 20-28°C",
            ],
            "tips": [
                "Both plants should be in full bloom for best results",
                "Pollinate in the morning when flowers are fresh",
                "Avoid pollinating if either plant shows signs of stress",
            ]
        },
        "Moderate": {
            "status": "Conditional — Improve Before Pollination",
            "steps": [
                "1. Address any visible health issues first",
                "2. Improve watering and fertilization schedule",
                "3. Ensure adequate light (bright indirect, no direct sun)",
                "4. Wait 2-4 weeks for plant to recover",
                "5. Re-assess suitability before attempting pollination",
            ],
            "tips": [
                "Moderate plants CAN be pollinated but success rate is lower",
                "Consider using this plant as pollen donor rather than receiver",
                "Monitor leaf color — dark green indicates improving health",
            ]
        },
        "Not Suitable": {
            "status": "Not Ready — Treatment Required",
            "steps": [
                "1. Isolate the plant to prevent disease spread",
                "2. Treat any visible diseases with appropriate fungicide/pesticide",
                "3. Adjust watering — check for root rot or dehydration",
                "4. Provide optimal growing conditions",
                "5. Allow 4-8 weeks for recovery",
                "6. Re-assess suitability after treatment",
            ],
            "tips": [
                "Do NOT use this plant for pollination in its current state",
                "Diseased plants produce weak offspring with poor viability",
                "Focus on rehabilitation before considering breeding",
            ]
        }
    }

    if suitability not in guidance:
        raise HTTPException(status_code=400, detail=f"Invalid suitability: {suitability}")

    return {"status": "success", "suitability": suitability, "guidance": guidance[suitability]}


@router.get("/history")
async def get_pollination_history():
    """
    Retrieve historical assessment records.
    """
    # TODO: Fetch from Firebase in future
    return {
        "status": "success",
        "message": "Assessment history — coming soon (Firebase integration)",
        "records": []
    }
