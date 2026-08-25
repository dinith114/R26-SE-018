"""
Utility functions for bloom date prediction.
"""
import json
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Union

import joblib
import numpy as np
import tensorflow as tf
from PIL import Image

from .config import MODEL_CONFIG


def preprocess_pil_image(img: Image.Image, target_size: tuple = None) -> np.ndarray:
    """
    Preprocess an already-loaded PIL image for prediction.

    Args:
        img: PIL image
        target_size: Target size (width, height)

    Returns:
        Preprocessed image array of shape (1, H, W, C)
    """
    if target_size is None:
        target_size = MODEL_CONFIG['target_size']

    # No /255 here deliberately: the model's image branch already applies
    # the model-type-specific preprocess_input as its first layer (see
    # model.py), which expects raw [0,255] pixels - for efficientnet that's
    # a Keras-documented no-op passthrough, since EfficientNet bakes its own
    # Rescaling(1./255) layer into the model. Rescaling here too would
    # silently rescale pixels twice, crushing them to near-zero and
    # starving the frozen backbone of any real signal.
    img = img.convert('RGB').resize(target_size)
    img_array = np.array(img).astype('float32')

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


def compute_bloom_date(days_until_bloom: float, capture_date: Union[str, date, None] = None) -> date:
    """
    Turn a predicted days-until-bloom count into a calendar bloom date.

    Args:
        days_until_bloom: Model output (can be fractional; rounded to a whole day)
        capture_date: The date the photo was taken. Defaults to today.

    Returns:
        The predicted bloom date
    """
    if capture_date is None:
        capture_date = date.today()
    elif isinstance(capture_date, str):
        capture_date = datetime.strptime(capture_date, '%Y-%m-%d').date()

    days = max(0, round(float(days_until_bloom)))
    return capture_date + timedelta(days=days)


def save_model_artifacts(model, scaler, config: dict, output_dir: Path) -> None:
    """
    Save the trained model, tabular feature scaler, and training config.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    model.save(output_dir / 'vanda_bloom_model.h5')
    joblib.dump(scaler, output_dir / 'tabular_scaler.pkl')

    with open(output_dir / 'model_config.json', 'w') as f:
        json.dump(config, f, indent=2, default=str)


def load_model_artifacts(model_dir: Path) -> tuple:
    """
    Load the trained model, tabular feature scaler, and training config.
    """
    model_dir = Path(model_dir)

    # compile=False: inference only needs the architecture + weights, not the
    # training config - and Keras 3.15 fails to deserialize the saved 'mse'
    # loss ("not a KerasSaveable subclass") when compile=True is left on.
    model = tf.keras.models.load_model(model_dir / 'vanda_bloom_model.h5', compile=False)
    scaler = joblib.load(model_dir / 'tabular_scaler.pkl')

    with open(model_dir / 'model_config.json', 'r') as f:
        config = json.load(f)

    return model, scaler, config
