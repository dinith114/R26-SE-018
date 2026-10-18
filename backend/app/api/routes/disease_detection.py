"""
Disease Detection, Severity Assessment & Treatment Recommendation — API routes
Component 1 (R26-SE-018)

Endpoints
---------
  POST /api/v1/disease/detect              upload a photo, get the full result
  GET  /api/v1/disease/treatments/{name}   treatment lookup, no model needed
  GET  /api/v1/disease/classes             what the system can recognise
  GET  /api/v1/disease/status              are the models loaded?
  GET  /api/v1/disease/metrics             measured performance, from the result files
  POST /api/v1/disease/contribute          submit a photo of an unknown disease  (signed in)
  GET  /api/v1/disease/pending-counts      progress toward the retrain threshold
  GET  /api/v1/disease/contributions/mine  your own photos and their review status  (signed in)
  GET  /api/v1/disease/review/whoami       is this account an expert?  (signed in)
  GET  /api/v1/disease/review/queue        photos for the expert  (expert)
  GET  /api/v1/disease/review/items/{id}   one photo in full  (expert)
  POST /api/v1/disease/review/items/{id}   approve, correct or reject  (expert)
  GET  /api/v1/disease/review/log          every decision, newest first  (expert)

The route handlers stay thin on purpose: every rule about when the severity
model runs, and every threshold, lives in the ML component
(`ml-models/disease_detection/src/disease_predict.py`) so the same logic is used by the
command line, the tests and the API. See app/services/disease_service.py.
"""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.api.deps import require_auth
from app.services import disease_contributions as contributions
from app.services import disease_service
from app.services.firebase_auth import AuthContext

router = APIRouter()


@router.post("/detect")
async def detect_disease(
    image: UploadFile = File(..., description="Photograph of an orchid leaf"),
    threshold: float = Query(
        disease_service.DEFAULT_THRESHOLD, ge=0.0, le=1.0,
        description="Confidence below this returns 'unidentified'."),
):
    """
    Analyse one orchid photograph.

    Runs the full cascade: disease classification, a confidence check, severity
    grading (only when a disease is actually identified), and a treatment
    recommendation keyed by (disease, severity).

    Returns `disease: "unidentified"` when the top probability is below the
    threshold — the condition is outside the three trained classes, or the photo
    is unclear. In that case severity is not assessed and the response advises
    expert review, because grading a condition that cannot be named is
    meaningless.
    """
    data = await image.read()

    try:
        disease_service.validate_upload(image.content_type, data)
    except disease_service.InvalidImage as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        result = disease_service.analyse(data, threshold=threshold)
    except disease_service.ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except disease_service.InvalidImage as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "status": "success",
        "filename": image.filename,
        "result": result,
    }


@router.get("/treatments/{disease_name}")
async def get_treatment(
    disease_name: str,
    severity: str = Query(
        None, description="mild | moderate | severe. Omit for healthy/unidentified."),
):
    """
    Treatment recommendation for a (disease, severity) pair.

    No model is run, so this is fast and works even if the model files are
    missing. An unknown disease name falls back to the 'unidentified' entry
    rather than erroring, so the app never breaks on an unexpected label.

    Note on doses: any option whose rate has not yet been verified against the
    product label and the Sri Lanka Department of Agriculture registered list is
    returned with `show_dose: false` and a referral message in place of the
    number. Display that message; never invent a rate.
    """
    try:
        advice = disease_service.treatment_for(disease_name, severity)
    except disease_service.ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    if advice.get("error"):
        raise HTTPException(status_code=400, detail=advice["message"])

    return {"status": "success", "treatment": advice}


@router.get("/classes")
async def list_classes():
    """Everything the system can name, and the severity grades for each."""
    try:
        return {"status": "success", **disease_service.known_diseases()}
    except Exception as exc:                                      # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/status")
async def model_status():
    """
    Which model files are present, without loading TensorFlow.

    Cheap enough for a monitoring probe, and the fastest way to diagnose a 503
    from /detect.
    """
    status = disease_service.model_status()
    return {
        "status": "success" if status["disease_ready"] else "degraded",
        "detail": status,
    }


@router.get("/metrics")
async def get_metrics():
    """
    How well the models measured, for presenting the results.

    Not shown in the grower's app: a grower has no use for confusion matrices,
    which is why the watering component's viva-only screen was removed too.

    Read from the result files the evaluation scripts wrote -- test-set scores
    against what guessing would get, the severity grades, the not-an-orchid
    check and the architecture comparison. No model is loaded, and no number is
    typed in by hand. Open to read: these are published results, not farm data.
    """
    return {"status": "success", "metrics": disease_service.metrics_summary()}


@router.post("/contribute")
async def contribute_image(
    image: UploadFile = File(..., description="Photograph of the affected part"),
    disease: str = Form(..., description="Disease name, e.g. Anthracnose"),
    plant_part: str = Form(..., description="leaf | stem | flower"),
    severity: str = Form(..., description="mild | moderate | severe"),
    confirmed_by: str = Form("", description="Optional: who already identified it"),
    notes: str = Form("", description="Optional observations"),
    # Sent by app builds from before expert review. Kept only as information
    # for the expert; it no longer makes a photograph count.
    verified: bool = Form(False),
    verified_by: str = Form(""),
    ctx: AuthContext = Depends(require_auth),
):
    """
    Submit a photograph of a condition the system cannot yet identify.

    Signed in, so every photograph is tied to the account that sent it. It is
    checked (too small, dark or blurred to judge is refused, with the reason),
    stored as an ORIGINAL in `data/pending/<disease>/`, and joins the expert's
    queue as `pending`. It counts toward a new class only once an expert
    approves it; app/services/disease_contributions.py holds the full rule.

    Never augmented here: augmenting before the train / test split would put
    variants of the same leaf on both sides of it.
    """
    data = await image.read()
    try:
        disease_service.validate_upload(image.content_type, data)
    except disease_service.InvalidImage as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        result = contributions.submit(
            data,
            disease=disease,
            plant_part=plant_part,
            severity=severity,
            contributor=ctx,
            notes=notes,
            original_filename=image.filename or "",
            claimed_confirmed_by=confirmed_by or (verified_by if verified else ""),
        )
    except contributions.PhotoRefused as exc:
        raise HTTPException(status_code=422, detail="This photo can't be used. " + str(exc))
    except contributions.DuplicatePhoto as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except contributions.TooManyContributions as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except disease_service.InvalidContribution as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except disease_service.InvalidImage as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except disease_service.ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    return {"status": "success", "result": result}


@router.get("/pending-counts")
async def get_pending_counts():
    """
    How close each contributed disease is to being trainable.

    Open to read: it holds counts, not photographs or accounts. Only
    expert-approved photographs count, they must come from at least three
    accounts, and near-identical photographs count once.
    """
    try:
        return {"status": "success", **contributions.counts()}
    except Exception as exc:                                      # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/contributions/mine")
async def my_contributions(ctx: AuthContext = Depends(require_auth)):
    """The signed-in grower's own photographs and what the expert decided."""
    return {"status": "success", "contributions": contributions.mine(ctx.uid),
            "rules": contributions.RULES}


@router.get("/review/whoami")
async def review_whoami(ctx: AuthContext = Depends(require_auth)):
    """
    Lets the app show the review screen to experts only. This decides what is
    displayed, nothing more: every review request is checked again on its own.
    """
    return {"status": "success", "expert": contributions.is_expert(ctx)}


async def require_expert(ctx: AuthContext = Depends(require_auth)) -> AuthContext:
    """Signed in AND on the server's expert list."""
    if not contributions.is_expert(ctx):
        raise HTTPException(403, "Only an orchid expert can review contributed photos.")
    return ctx


@router.get("/review/queue")
async def review_queue(
    status: Literal["pending", "approved", "rejected", "all"] = Query("pending"),
    ctx: AuthContext = Depends(require_expert),
):
    """Photos for the expert. Waiting ones come oldest first."""
    return {"status": "success", "items": contributions.queue(status),
            "reject_reasons": contributions.REJECT_REASONS}


@router.get("/review/items/{image_id}")
async def review_item(image_id: str, ctx: AuthContext = Depends(require_expert)):
    """One photo in full, with possible copies and its decision history."""
    try:
        return {"status": "success", "item": contributions.item(image_id),
                "reject_reasons": contributions.REJECT_REASONS}
    except contributions.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))


class ReviewDecision(BaseModel):
    decision: Literal["approve", "correct", "reject"]
    reason: Optional[str] = None
    note: Optional[str] = ""
    disease: Optional[str] = None
    plant_part: Optional[str] = None
    severity: Optional[str] = None


@router.post("/review/items/{image_id}")
async def review_decide(image_id: str, body: ReviewDecision,
                        ctx: AuthContext = Depends(require_expert)):
    """Approve, correct or reject one photo. Every decision is logged."""
    try:
        item = contributions.review(
            image_id, body.decision, expert=ctx, reason=body.reason, note=body.note,
            disease=body.disease, plant_part=body.plant_part, severity=body.severity)
    except contributions.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except contributions.SelfReview as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except disease_service.InvalidContribution as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"status": "success", "item": item}


@router.get("/review/log")
async def review_log(limit: int = Query(50, ge=1, le=500),
                     ctx: AuthContext = Depends(require_expert)):
    """Who decided what, and when. The log is only ever appended to."""
    return {"status": "success", "decisions": contributions.decisions(limit)}
