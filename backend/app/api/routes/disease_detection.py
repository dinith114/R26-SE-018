"""
Disease Detection, Severity Assessment & Treatment Recommendation — API routes
Component 1 (R26-SE-018)

Endpoints
---------
  POST /api/v1/disease/detect              upload a photo, get the full result
  GET  /api/v1/disease/treatments/{name}   treatment lookup, no model needed
  GET  /api/v1/disease/classes             what the system can recognise
  GET  /api/v1/disease/status              are the models loaded?
  POST /api/v1/disease/contribute          submit a photo of an unknown disease
  GET  /api/v1/disease/pending-counts      progress toward the retrain threshold

The route handlers stay thin on purpose: every rule about when the severity
model runs, and every threshold, lives in the ML component
(`ml-models/disease_detection/src/disease_predict.py`) so the same logic is used by the
command line, the tests and the API. See app/services/disease_service.py.
"""

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from app.services import disease_service

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


@router.post("/contribute")
async def contribute_image(
    image: UploadFile = File(..., description="Photograph of the affected part"),
    disease: str = Form(..., description="Disease name, e.g. Anthracnose"),
    plant_part: str = Form(..., description="leaf | stem | flower"),
    severity: str = Form(..., description="mild | moderate | severe"),
    verified: bool = Form(False, description="Confirmed by an orchid research institute"),
    verified_by: str = Form("", description="Which institute or expert confirmed it"),
    notes: str = Form("", description="Optional observations"),
):
    """
    Submit a photograph of a condition the system cannot yet identify.

    The image is stored as an ORIGINAL in `data/pending/<disease>/` and recorded
    in `contributions.csv`. It is deliberately NOT augmented on upload:
    augmenting before the train/test split would place variants of the same leaf
    on both sides of that split, which is exactly the data leakage the pipeline
    is built to prevent. Augmentation happens at retrain time, after splitting.

    Nothing about the live model changes. Two gates stand between a contribution
    and the model:

      1. VERIFIED   unverified labels are stored but never trained on
      2. COUNT      a class needs 30 verified originals before it may be trained

    Reaching the threshold makes retraining POSSIBLE, not automatic. A human runs
    it, and the new model replaces the live one only if macro-F1 does not get
    worse. Training on a handful of images would give a class whose decision
    boundary is drawn from almost no evidence, and it would steal predictions
    from the classes that already work.

    `plant_part` is supplied by the contributor rather than predicted, because
    there is no stem or flower training data -- a model cannot classify what it
    has never seen.
    """
    data = await image.read()

    try:
        disease_service.validate_upload(image.content_type, data)
    except disease_service.InvalidImage as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        result = disease_service.save_contribution(
            image_bytes=data,
            disease=disease,
            plant_part=(plant_part or "").strip().lower(),
            severity=(severity or "").strip().lower(),
            verified=verified,
            verified_by=verified_by,
            notes=notes,
            original_filename=image.filename or "",
        )
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

    Counts VERIFIED contributions only, matching the rule the retraining tooling
    applies -- an unverified label is stored but never trained on. Lets the app
    show "Anthracnose: 8 / 30" without anyone needing shell access to the server.
    """
    try:
        return {"status": "success", **disease_service.pending_counts()}
    except Exception as exc:                                      # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc))
