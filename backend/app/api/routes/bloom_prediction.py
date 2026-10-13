"""
Bloom Date Prediction API Routes
Component 2: Orchid Growth Stage Recognition & Bloom Prediction
"""
import sys
import tempfile
import traceback
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image
import io

# Repo root is four levels up from backend/app/api/routes/
ML_PATH = Path(__file__).resolve().parents[4] / "ml-models" / "bloom_prediction"

print(f"[INFO] Looking for ML module at: {ML_PATH}")
print(f"[INFO] ML_PATH exists: {ML_PATH.exists()}")

# Add to Python path
if str(ML_PATH) not in sys.path:
    sys.path.insert(0, str(ML_PATH))
    print(f"[OK] Added {ML_PATH} to sys.path")

try:
    from src.predict import BloomPredictor
    from src.detect_and_predict import BloomDetectionPipeline
    print("[OK] Successfully imported bloom_prediction modules")
except ImportError as e:
    # Do NOT re-raise. This module's ML stack is optional: TensorFlow needs
    # Python 3.13 and the backend also runs on 3.12, where importing it fails.
    # Re-raising took the ENTIRE backend down - every route, for every
    # component - because one component's optional dependency was missing.
    # The component's own endpoints now return 503 and everything else runs.
    ML_IMPORT_ERROR = str(e)
    print(f"[WARN] {__name__}: ML stack unavailable ({e}). "
          "This component's endpoints will return 503; the rest of the API is unaffected.")
finally:
    # growth_stage and bloom_prediction each ship a top-level package
    # literally named `src`. Evicting it (and ML_PATH) here stops the one
    # imported first from being silently reused - and its names missing -
    # when the other route module does its own `from src... import ...`.
    for mod_name in list(sys.modules):
        if mod_name == 'src' or mod_name.startswith('src.'):
            del sys.modules[mod_name]
    if str(ML_PATH) in sys.path:
        sys.path.remove(str(ML_PATH))

router = APIRouter()

_predictor = None
_detection_pipeline = None
_model_dir = ML_PATH / 'models'


def get_predictor():
    """Lazy load the bloom date predictor."""
    global _predictor
    if _predictor is None:
        if (_model_dir / 'vanda_bloom_model.h5').exists():
            _predictor = BloomPredictor(_model_dir)
            print(f"[OK] Bloom Prediction Model loaded from: {_model_dir}")
        else:
            print(f"[ERROR] Model not found in: {_model_dir}")
            raise FileNotFoundError(f"Model not found in {_model_dir}")
    return _predictor


def get_detection_pipeline():
    """Lazy load the object-detection + bloom-prediction pipeline."""
    global _detection_pipeline
    if _detection_pipeline is None:
        if (_model_dir / 'vanda_bloom_model.h5').exists():
            _detection_pipeline = BloomDetectionPipeline(_model_dir)
            print(f"[OK] Bloom Detection Pipeline loaded from: {_model_dir}")
        else:
            raise FileNotFoundError(f"Model not found in {_model_dir}")
    return _detection_pipeline


@router.post("/predict")
async def predict_bloom_date(
    file: UploadFile = File(...),
    temperature: float = Form(...),
    humidity: float = Form(...),
    light_intensity: float = Form(...),
    capture_date: str = Form(None),
):
    """
    Predict the bloom date of an orchid from an uploaded photo plus the
    temperature, humidity, and light readings at capture time.

    Args:
        file: Image file (jpg, png, jpeg, webp, bmp)
        temperature: Degrees C
        humidity: Relative humidity %
        light_intensity: Light level (lux)
        capture_date: 'YYYY-MM-DD' the photo was taken; defaults to today

    Returns:
        JSON with days_until_bloom and predicted_bloom_date
    """
    try:
        allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/bmp', 'image/gif'}
        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"File type not allowed. Allowed types: {', '.join(allowed_types)}"
            )

        contents = await file.read()
        image = Image.open(io.BytesIO(contents))

        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
            image.save(tmp_file.name)
            temp_path = Path(tmp_file.name)

        try:
            predictor = get_predictor()
            result = predictor.predict(temp_path, temperature, humidity, light_intensity, capture_date)

            temp_path.unlink()

            return {
                'status': 'success',
                'data': result,
            }

        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            print(f"Prediction error: {str(e)}")
            traceback.print_exc()
            raise HTTPException(
                status_code=500,
                detail=f"Prediction failed: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Request error: {str(e)}")
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@router.post("/predict-objects")
async def predict_bloom_date_objects(
    file: UploadFile = File(...),
    temperature: float = Form(...),
    humidity: float = Form(...),
    light_intensity: float = Form(...),
    capture_date: str = Form(None),
):
    """
    Detect individual orchid plants, flower bunches, buds, and seed pods in
    an uploaded photo, and predict a bloom date for each one separately -
    for photos that contain more than one of these at once.
    """
    try:
        allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/bmp', 'image/gif'}
        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"File type not allowed. Allowed types: {', '.join(allowed_types)}"
            )

        contents = await file.read()
        image = Image.open(io.BytesIO(contents))

        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
            image.save(tmp_file.name)
            temp_path = Path(tmp_file.name)

        try:
            pipeline = get_detection_pipeline()
            result = pipeline.analyze(temp_path, temperature, humidity, light_intensity, capture_date)

            temp_path.unlink()

            return {
                'status': 'success',
                'data': result,
            }

        except Exception as e:
            if temp_path.exists():
                temp_path.unlink()
            print(f"Detection/prediction error: {str(e)}")
            traceback.print_exc()
            raise HTTPException(
                status_code=500,
                detail=f"Detection/prediction failed: {str(e)}"
            )

    except HTTPException:
        raise
    except Exception as e:
        print(f"Request error: {str(e)}")
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        predictor = get_predictor()
        return {
            'status': 'healthy',
            'model_loaded': True,
            'model_dir': str(_model_dir),
            'component': 'bloom_prediction'
        }
    except Exception as e:
        return {
            'status': 'unhealthy',
            'model_loaded': False,
            'error': str(e),
            'component': 'bloom_prediction'
        }, 500
