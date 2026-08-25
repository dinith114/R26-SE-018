"""
Configuration for bloom date prediction.
"""
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
    'model_type': 'efficientnet',  # 'efficientnet', 'mobilenet', 'resnet'
    'learning_rate': 0.001,
    'batch_size': 16,
    'epochs': 50,
    'patience': 10,
    'target_size': (224, 224),
    'validation_split': 0.2,
}

# Sensor/environment columns read from the .xlsx logs, in the exact order fed
# into the model's tabular input branch
TABULAR_FEATURES = ['Temperature', 'Humidity', 'Light intensity']

# Target column: whole days from the photo's capture time until the plant's
# recorded bloom date
TARGET_COLUMN = 'No of days until bloom'

# Only rows with this Image Type anchor the train/validation split; every
# augmented variant of the same photo inherits its base photo's split so a
# near-duplicate image never leaks across train and validation
ORIGINAL_IMAGE_TYPE = 'Original'

# Free-text growth/bloom status descriptions found in the spreadsheets, kept
# for reference/analysis only - not used as a model input or output
BLOOM_STATUSES = [
    'Developing',
    'Swelling',
    'Opening',
    'Partial Bloom',
    'Full Bloomed',
    'Mixed',
]

# Allowed image extensions
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'}
