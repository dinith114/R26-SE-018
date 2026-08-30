"""
Growth Stage Recognition API Routes
Component 2: Orchid Growth Stage Recognition & Bloom Prediction
"""
import sys
import os
import tempfile
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import traceback
import numpy as np
from PIL import Image
import io

# Repo root is four levels up from backend/app/api/routes/
ML_PATH = Path(__file__).resolve().parents[4] / "ml-models" / "growth_stage"

print(f"[INFO] Looking for ML module at: {ML_PATH}")
print(f"[INFO] ML_PATH exists: {ML_PATH.exists()}")

# Add to Python path
if str(ML_PATH) not in sys.path:
    sys.path.insert(0, str(ML_PATH))
    print(f"[OK] Added {ML_PATH} to sys.path")

# Now try importing
try:
    from src.predict import GrowthStagePredictor
    from src.detect_and_predict import GrowthStageDetectionPipeline
    from src.utils import get_stage_info
    from src.config import STAGE_NAMES, STAGE_LABELS
    print("[OK] Successfully imported growth_stage modules")
except ImportError as e:
    print(f"[ERROR] Import error: {e}")
    # List what's in the directory
    if ML_PATH.exists():
        print(f"Contents of {ML_PATH}:")
        for item in ML_PATH.iterdir():
            print(f"  - {item.name}")
    raise
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
_model_path = ML_PATH / 'models' / 'vanda_growth_model.h5'


def get_predictor():
    """Lazy load the predictor."""
    global _predictor
    if _predictor is None:
        if _model_path.exists():
            _predictor = GrowthStagePredictor(_model_path)
            print(f"[OK] Growth Stage Model loaded from: {_model_path}")
        else:
            print(f"[ERROR] Model not found at: {_model_path}")
            # List what's in the models directory
            if ML_PATH.exists():
                models_dir = ML_PATH / 'models'
                if models_dir.exists():
                    print(f"Files in {models_dir}:")
                    for f in models_dir.iterdir():
                        print(f"  - {f.name}")
            raise FileNotFoundError(f"Model not found at {_model_path}")
    return _predictor


def get_detection_pipeline():
    """Lazy load the object-detection + growth-stage pipeline."""
    global _detection_pipeline
    if _detection_pipeline is None:
        if _model_path.exists():
            _detection_pipeline = GrowthStageDetectionPipeline(_model_path)
            print(f"[OK] Growth Stage Detection Pipeline loaded from: {_model_path}")
        else:
            raise FileNotFoundError(f"Model not found at {_model_path}")
    return _detection_pipeline


@router.post("/identify")
async def identify_growth_stage(
    file: UploadFile = File(...)
):
    """
    Identify the growth stage of an orchid from an uploaded image.
    
    Args:
        file: Image file (jpg, png, jpeg, webp, bmp)
    
    Returns:
        JSON with prediction results
    """
    try:
        # Validate file type
        allowed_types = {'image/jpeg', 'image/png', 'image/webp', 'image/bmp', 'image/gif'}
        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=f"File type not allowed. Allowed types: {', '.join(allowed_types)}"
            )
        
        # Read image file
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        
        # Save temporarily
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
            image.save(tmp_file.name)
            temp_path = Path(tmp_file.name)
        
        try:
            # Get predictor and make prediction
            predictor = get_predictor()
            result = predictor.predict(temp_path, top_k=3)
            
            # Clean up temp file
            temp_path.unlink()
            
            # Return result
            return {
                'status': 'success',
                'data': {
                    'stage_key': result['stage_key'],
                    'stage_label': result['stage_name'],
                    'confidence': result['confidence'],
                    'stage_description': result['stage_info']['stage_description'],
                    'top_3_predictions': result['top_predictions'],
                    'care_protocol': result['stage_info']['care_protocol'],
                    'inference_source': 'trained_model',
                    'image_analysis': {
                        'image_processed': True,
                        'image_format': file.content_type
                    }
                }
            }
            
        except Exception as e:
            # Clean up temp file
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


@router.post("/identify-objects")
async def identify_growth_stage_objects(
    file: UploadFile = File(...)
):
    """
    Detect individual orchid plants, flower bunches, buds, and seed pods in
    an uploaded image, and predict a growth stage for each one separately -
    for photos that contain more than one of these at once.

    Args:
        file: Image file (jpg, png, jpeg, webp, bmp)

    Returns:
        JSON with one growth-stage prediction per detected object
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
            result = pipeline.analyze(temp_path, top_k=3)

            temp_path.unlink()

            return {
                'status': 'success',
                'data': {
                    'objects_detected': result['objects_detected'],
                    'detections': [
                        {
                            'object_class': det['object_class'],
                            'detection_confidence': det['detection_confidence'],
                            'box': det['box'],
                            'stage_key': det['stage_key'],
                            'stage_label': det['stage_name'],
                            'confidence': det['confidence'],
                            'stage_description': det['stage_info']['stage_description'],
                            'top_3_predictions': det['top_predictions'],
                            'care_protocol': det['stage_info']['care_protocol'],
                        }
                        for det in result['detections']
                    ],
                    'inference_source': 'trained_model+zero_shot_detector',
                }
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


@router.get("/stages")
async def get_stages():
    """Get all available growth stages with their information."""
    stages = []
    for stage_key in STAGE_LABELS:
        stages.append(get_stage_info(stage_key))
    
    return {
        'status': 'success',
        'data': {
            'stages': stages,
            'total_stages': len(stages)
        }
    }


@router.get("/stage/{stage_key}")
async def get_stage_info_by_key(stage_key: str):
    """Get information about a specific growth stage."""
    if stage_key not in STAGE_NAMES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stage key: {stage_key}"
        )
    
    return {
        'status': 'success',
        'data': get_stage_info(stage_key)
    }


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        predictor = get_predictor()
        return {
            'status': 'healthy',
            'model_loaded': True,
            'model_path': str(_model_path),
            'stages': len(STAGE_LABELS),
            'component': 'growth_stage_recognition'
        }
    except Exception as e:
        return {
            'status': 'unhealthy',
            'model_loaded': False,
            'error': str(e),
            'component': 'growth_stage_recognition'
        }, 500