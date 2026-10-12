"""
Hybrid Pollination & Compatibility Analysis - API Routes
Component 1: IT22065230 – Wickramasinghe D.P

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
    CrossLogRequest, CrossStageRequest,
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


# ══════════════════════════════════════════════════════════════════
#  GROWER CROSS LOGBOOK
#
#  The compatibility engine answers from the RHS register, which records
#  only crosses that succeeded. These endpoints collect the other half:
#  what a grower actually attempted and what actually happened, failures
#  included. That is the denominator the register structurally cannot have.
#
#  Nothing here predicts. It is a record, and on day one it is an empty one.
# ══════════════════════════════════════════════════════════════════

from fastapi.responses import FileResponse
from app.services.cross_log_service import cross_log_service


@router.get("/log/reference")
async def log_reference():
    """The stage pipeline and exit vocabulary, so the app never hardcodes it."""
    return {"status": "success", **cross_log_service.reference()}


@router.post("/log/photo")
async def log_upload_photo(image: UploadFile = File(...)):
    """
    Store a parent photograph and return the id the record will carry.

    Photos go to disk rather than into the record: a logbook entry is a few
    hundred bytes and should stay that way, and the grower will take two
    photographs for every cross for years.
    """
    validate_image(image)
    try:
        photo_id = cross_log_service.save_photo(image)
        return {"status": "success", "photoId": photo_id,
                "url": f"/api/v1/pollination/log/photo/{photo_id}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not store photo: {e}")


@router.get("/log/photo/{photo_id}")
async def log_get_photo(photo_id: str):
    """Serve a stored photograph back."""
    path = cross_log_service.photo_path(photo_id)
    if not path:
        raise HTTPException(status_code=404, detail="No such photo")
    return FileResponse(path)


@router.get("/log/plants")
async def log_list_plants():
    """Every plant the grower has registered, newest first."""
    return {"status": "success", "plants": cross_log_service.plants()}


@router.post("/log/plants")
async def log_register_plant(
    name: str = Form(""),
    photo: str = Form(""),
    genus: str = Form(""),
    location: str = Form(""),
):
    """
    Register one plant.

    `name` is optional. A plant whose tag is lost or unreadable still gets an
    id it can be labelled with, and the name can be added later - every cross
    that references the id picks it up.
    """
    return {"status": "success",
            "plant": cross_log_service.register_plant(name, photo, genus, location)}


@router.post("/log/crosses")
async def log_create_cross(request: CrossLogRequest):
    """
    Record one attempted cross. Pod parent first, never sorted.

    The two health readings are copied in as snapshots of the day the
    pollinia were moved, not linked to the plants - a plant re-assessed six
    months later must not rewrite what was true at pollination.
    """
    try:
        cross = cross_log_service.log_cross(
            request.pod_plant_id, request.pollen_plant_id,
            pod_health=request.pod_health.model_dump() if request.pod_health else None,
            pollen_health=request.pollen_health.model_dump() if request.pollen_health else None,
            flower_age_days=request.flower_age_days,
            pollen_source=request.pollen_source,
            pollen_stored_days=request.pollen_stored_days,
            logged_by=request.logged_by,
            notes=request.notes,
            conditions=request.conditions,
        )
        return {"status": "success", "cross": cross}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not log the cross: {e}")


@router.get("/log/crosses")
async def log_list_crosses():
    """Every logged cross, newest first, with day count and whether it is due."""
    return {"status": "success", "crosses": cross_log_service.crosses()}


@router.post("/log/crosses/{cross_id}/stage")
async def log_update_stage(cross_id: str, request: CrossStageRequest):
    """
    Advance a cross to the next stage, or close it at the gate it failed.

    Closing records WHICH gate it stopped at, because that is the whole
    signal: no pod set is usually technique, an aborted capsule is usually
    the pod parent's condition, and an empty capsule is where genetic
    incompatibility actually shows.
    """
    try:
        return {"status": "success",
                "cross": cross_log_service.update_stage(
                    cross_id, request.stage, request.outcome, request.note)}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No cross {cross_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/log/stats")
async def log_stats():
    """
    Counts per gate, with denominators. A rate appears only once a gate has
    enough completed attempts behind it to support one.
    """
    return {"status": "success", **cross_log_service.stats()}


@router.delete("/log/crosses/{cross_id}")
async def log_delete_cross(cross_id: str):
    """
    Remove a record.

    Needed for the test entries and duplicates a grower makes while learning
    the app. It is also the one button here that can quietly undo the point of
    the whole logbook: delete every cross that failed and what is left is a
    book of successes, which is exactly the bias the RHS register already has
    and this file exists to correct. The app asks a differently worded
    question before removing a recorded failure.
    """
    try:
        removed = cross_log_service.delete_cross(cross_id)
        return {"status": "success", "removed": removed["crossId"]}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No cross {cross_id}")
