"""
Utility functions for growth stage classification.
"""
import os
import json
import joblib
import numpy as np
from PIL import Image
from pathlib import Path
from typing import Union, List, Dict, Any
import tensorflow as tf
from tensorflow.keras.preprocessing import image
from .config import (
    STAGE_LABELS, STAGE_NAMES, STAGE_DESCRIPTIONS, 
    CARE_PROTOCOLS, MODEL_CONFIG
)


def preprocess_pil_image(img: Image.Image, target_size: tuple = None) -> np.ndarray:
    """
    Preprocess an already-loaded PIL image for prediction (e.g. a crop
    produced by the object detector, with no file on disk).

    Args:
        img: PIL image
        target_size: Target size (width, height)

    Returns:
        Preprocessed image array of shape (1, H, W, C)
    """
    if target_size is None:
        target_size = MODEL_CONFIG['target_size']

    # No /255 here deliberately: the model's first layer already applies the
    # model-type-specific preprocess_input, which expects raw [0,255] pixels
    # (see model.py / preprocess.py for why) - training and inference need to
    # match, or the model sees different input distributions in each.
    img = img.convert('RGB').resize(target_size)
    img_array = np.array(img).astype('float32')

    # Convert to model input shape
    if len(img_array.shape) == 3:
        img_array = np.expand_dims(img_array, axis=0)

    return img_array


def load_image(img_path: Union[str, Path], target_size: tuple = None) -> np.ndarray:
    """
    Load and preprocess an image for prediction.

    Args:
        img_path: Path to image file
        target_size: Target size (width, height)

    Returns:
        Preprocessed image array of shape (1, H, W, C)
    """
    img = Image.open(img_path)
    return preprocess_pil_image(img, target_size)


def get_stage_info(stage_key: str) -> Dict[str, Any]:
    """
    Get comprehensive information about a growth stage.
    
    Args:
        stage_key: String key of the stage
    
    Returns:
        Dictionary with stage information
    """
    return {
        'stage_key': stage_key,
        'stage_name': STAGE_NAMES.get(stage_key, stage_key),
        'stage_description': STAGE_DESCRIPTIONS.get(stage_key, ''),
        'care_protocol': CARE_PROTOCOLS.get(stage_key, {})
    }


def format_prediction(predictions: np.ndarray, top_k: int = 3) -> Dict[str, Any]:
    """
    Format prediction results for API response.
    
    Args:
        predictions: Model prediction array
        top_k: Number of top predictions to return
    
    Returns:
        Formatted prediction results
    """
    if isinstance(predictions, np.ndarray):
        pred = predictions[0] if len(predictions.shape) > 1 else predictions
    else:
        pred = predictions
    
    # Get top_k predictions
    indices = np.argsort(pred)[::-1][:top_k]
    top_predictions = []
    
    for idx in indices:
        stage_key = STAGE_LABELS[idx]
        confidence = float(pred[idx])
        top_predictions.append({
            'stage': stage_key,
            'stage_name': STAGE_NAMES.get(stage_key, stage_key),
            'confidence': confidence
        })
    
    # Get best prediction
    best_idx = indices[0]
    best_stage_key = STAGE_LABELS[best_idx]
    best_confidence = float(pred[best_idx])
    
    return {
        'stage_key': best_stage_key,
        'stage_name': STAGE_NAMES.get(best_stage_key, best_stage_key),
        'confidence': best_confidence,
        'top_predictions': top_predictions,
        'stage_info': get_stage_info(best_stage_key)
    }


def save_model_artifacts(model, label_encoder, config: dict, output_dir: Path) -> None:
    """
    Save model and associated artifacts.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save model
    model.save(output_dir / 'vanda_growth_model.h5')
    
    # Save label encoder
    joblib.dump(label_encoder, output_dir / 'label_encoder.pkl')
    
    # Save config
    with open(output_dir / 'model_config.json', 'w') as f:
        json.dump(config, f, indent=2)


def load_model_artifacts(model_dir: Path) -> tuple:
    """
    Load model and associated artifacts.
    """
    model_dir = Path(model_dir)
    
    model = tf.keras.models.load_model(model_dir / 'vanda_growth_model.h5')
    label_encoder = joblib.load(model_dir / 'label_encoder.pkl')
    
    with open(model_dir / 'model_config.json', 'r') as f:
        config = json.load(f)
    
    return model, label_encoder, config


def get_image_files(data_dir: Path, extensions: set = None) -> List[Path]:
    """
    Get all image files from a directory recursively.
    """
    if extensions is None:
        extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'}
    
    image_files = []
    for ext in extensions:
        image_files.extend(Path(data_dir).glob(f'**/*{ext}'))
        image_files.extend(Path(data_dir).glob(f'**/*{ext.upper()}'))
    
    return sorted(set(image_files))


def create_sample_batch(generator, num_samples: int = 5) -> tuple:
    """
    Create a batch of sample images for visualization.
    """
    samples, labels = next(generator)
    return samples[:num_samples], labels[:num_samples]