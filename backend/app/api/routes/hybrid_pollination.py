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
    PlantTraitsInput, SuitabilityResponse, HealthResponse, ErrorResponse,
    CompatibilityRequest, CompatibilityResponse, PartnerRankRequest,
)
from app.services.hybrid_pollination_service import pollination_service
from app.services.compatibility_service import compatibility_service

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
    image: UploadFile = File(..., description="Whole-plant image to assess"),
    leaf_closeup: Optional[UploadFile] = File(
        None, description="Optional close-up of a single leaf. Strongly recommended: "
                          "disease cannot be judged reliably from a whole-plant frame."
    ),
    leaf_condition: Optional[str] = Form(None),
    plant_strength: Optional[str] = Form(None),
    disease_visible: Optional[str] = Form(None),
    flower_condition: Optional[str] = Form(None),
    auto_traits: bool = Form(True),
):
    """
    Assess pollination suitability of a single orchid plant.

    Traits are MEASURED from the image. Any trait value supplied in the form is
    treated as a correction to the measured value, not as required input - the
    endpoint works with the image alone.

    The response carries `trait_resolution`, which states for every trait where
    its value came from (measured / user / unknown), how confident the system
    is, and the evidence behind it. `trait_resolution.asked_for` lists traits
    the system could not determine and would like the grower to confirm.
    """
    validate_image(image)
    if leaf_closeup is not None and leaf_closeup.filename:
        validate_image(leaf_closeup)

    if not pollination_service.is_loaded:
        raise HTTPException(
            status_code=503,
            detail="Model not loaded. Please train the model first."
        )

    # Save uploaded files temporarily
    temp_dir = tempfile.mkdtemp()
    temp_path = os.path.join(temp_dir, image.filename or "upload.jpg")
    closeup_path = None

    try:
        with open(temp_path, "wb") as f:
            f.write(await image.read())

        if leaf_closeup is not None and leaf_closeup.filename:
            closeup_path = os.path.join(temp_dir, f"closeup_{leaf_closeup.filename}")
            with open(closeup_path, "wb") as f:
                f.write(await leaf_closeup.read())

        # Screen the upload BEFORE the model sees it. The suitability model has
        # three classes and forces every input onto one of them, so without this
        # a photograph of a laptop screen returns "Suitable, 98.7%".
        gate = pollination_service.check_input(temp_path)
        if not gate.get("is_orchid", True):
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "not_an_orchid",
                    "message": gate.get("message", "This does not look like an orchid plant."),
                    "input_check": gate,
                },
            )

        # Only pass through traits the grower actually chose. Sending
        # "unknown" for every field would be indistinguishable from an answer.
        traits = {
            k: v for k, v in {
                "leaf_condition": leaf_condition,
                "plant_strength": plant_strength,
                "disease_visible": disease_visible,
                "flower_condition": flower_condition,
            }.items()
            if v is not None and str(v).strip().lower() not in ("", "unknown")
        }

        # Predict
        result = pollination_service.predict_suitability(
            temp_path, traits,
            leaf_closeup_path=closeup_path,
            auto_traits=auto_traits,
            input_check=gate,
        )
        result["input_check"] = gate

        return SuitabilityResponse(**result)

    except HTTPException:
        # A refusal from the input gate is a deliberate answer, not a crash.
        # Without this it would be caught below and reported as a 500.
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction failed: {str(e)}")

    finally:
        # Cleanup temp files
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


# ──────────────────────────────────────────────
# Level 2 — Parent A × Parent B Compatibility
# ──────────────────────────────────────────────
@router.post("/compatibility", response_model=CompatibilityResponse)
async def assess_compatibility(request: CompatibilityRequest):
    """
    Assess crossing two named orchids.

    Order matters. By breeding convention the pod (seed) parent is named first
    and the pollen donor second, so `A × B` and `B × A` are different attempts
    and are assessed separately.

    Optionally accepts `pod_health` / `pollen_health` — a Level 1 assessment
    produced from a photograph of that plant. When supplied, a parent assessed
    Not Suitable blocks the cross, and a Moderate one raises a warning. This is
    how the image half and the name half of the workflow join up: the photograph
    answers what condition a plant is in, the name answers what it can be
    crossed with.

    The response carries an evidence `tier`, a two-class `compatibility_class`
    summary, and the registered `precedents` behind it — never a success
    percentage. The orchid register records only
    crosses that succeeded, so it has no denominator and no success rate can
    honestly be derived from it.
    """
    if not compatibility_service.is_loaded:
        raise HTTPException(
            status_code=503,
            detail=f"Compatibility engine unavailable: {compatibility_service.error}"
        )

    try:
        result = compatibility_service.assess(
            request.pod_parent.strip(),
            request.pollen_parent.strip(),
            pod_health=request.pod_health.model_dump() if request.pod_health else None,
            pollen_health=request.pollen_health.model_dump() if request.pollen_health else None,
        )
        return CompatibilityResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Assessment failed: {str(e)}")


@router.post("/compatibility/rank")
async def rank_partners(request: PartnerRankRequest):
    """
    Rank candidate pollen donors for one pod parent, best evidence first.

    This answers the question a breeder actually asks: "this plant is in
    flower — which of my others should I put on it?"
    """
    if not compatibility_service.is_loaded:
        raise HTTPException(status_code=503, detail="Compatibility engine unavailable")

    if not request.candidates:
        raise HTTPException(status_code=400, detail="Provide at least one candidate")

    try:
        ranked = compatibility_service.rank(
            request.pod_parent.strip(),
            [c.strip() for c in request.candidates if str(c).strip()],
        )
        return {"status": "success", "pod_parent": request.pod_parent, "ranked": ranked}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ranking failed: {str(e)}")


@router.get("/compatibility/parents")
async def list_known_parents():
    """
    Names the knowledge base recognises, for type-ahead in the app.

    A name absent from this list can still be assessed — it simply falls back
    to genus-level evidence rather than an exact registered precedent.
    """
    return {
        "status": "success",
        "parents": compatibility_service.known_parents(),
        "info": compatibility_service.info(),
    }
