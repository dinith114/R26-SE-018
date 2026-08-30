"""
Configuration for growth stage classification.
"""
import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / 'data' / 'raw'
MODELS_DIR = BASE_DIR / 'models'
OUTPUT_DIR = BASE_DIR / 'outputs'

# Create directories if they don't exist
MODELS_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Model configuration
MODEL_CONFIG = {
    'input_shape': (224, 224, 3),
    'num_classes': 6,
    'model_type': 'efficientnet',  # 'efficientnet', 'mobilenet', 'resnet'
    'learning_rate': 0.001,
    'batch_size': 32,
    'epochs': 50,
    'patience': 10,
    'target_size': (224, 224)
}

# Stage labels
# NOTE: 'germination' is intentionally excluded — data/raw has no folder for it
# (source images were too few and in an unsupported format). Re-add it here once
# a proper augmented data/raw/germination folder exists.
STAGE_LABELS = [
    'vegetative',
    'budding',
    'pre_bloom',
    'full_bloom',
    'wilting',
    'seed_formation'
]

STAGE_NAMES = {
    'vegetative': 'Vegetative Growth Stage',
    'budding': 'Budding Stage',
    'pre_bloom': 'Pre-Bloom Stage',
    'full_bloom': 'Full Bloom Stage',
    'wilting': 'Wilting Stage',
    'seed_formation': 'Seed Formation Stage'
}

STAGE_DESCRIPTIONS = {
    'vegetative': 'Plant grows bigger but no buds yet',
    'budding': 'Flower buds begin to appear',
    'pre_bloom': 'Buds develop and start opening',
    'full_bloom': 'Flowers are fully open and healthy',
    'wilting': 'Flowers start fading and drying',
    'seed_formation': 'Seeds develop and mature after flowering'
}

CARE_PROTOCOLS = {
    'vegetative': {
        'water': 'Water when nearly dry',
        'light': 'Moderate-bright',
        'temperature': '24-30C',
        'fertilizer': 'Balanced feed'
    },
    'budding': {
        'water': 'Slightly increase watering',
        'light': 'Bright filtered',
        'temperature': '24-29C',
        'fertilizer': 'Bloom booster'
    },
    'pre_bloom': {
        'water': 'Consistent moisture',
        'light': 'Steady bright',
        'temperature': '23-28C',
        'fertilizer': 'Bloom formula'
    },
    'full_bloom': {
        'water': 'Regular, avoid petals',
        'light': 'Bright indirect',
        'temperature': '22-27C',
        'fertilizer': 'Light support'
    },
    'wilting': {
        'water': 'Reduce gradually',
        'light': 'Moderate',
        'temperature': '20-26C',
        'fertilizer': 'Switch to balanced'
    },
    'seed_formation': {
        'water': 'Stable routine',
        'light': 'Bright indirect',
        'temperature': '22-28C',
        'fertilizer': 'Half strength'
    }
}

# Allowed image extensions
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'}