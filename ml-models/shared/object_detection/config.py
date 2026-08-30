"""
Configuration for the orchid object detector.

Detection is hybrid: a custom YOLOv8 model (fine-tuned on data/{flowers,
plants,seeds}, see prepare_dataset.py + train.py) handles orchid_plant,
flower_bunch and seed_pod, since real photos exist for those. There's no bud
data yet, so bud detection always falls back to the zero-shot OWLv2 model.
If the custom model hasn't been trained yet (models/best.pt missing), all
four classes fall back to zero-shot - this is the original behavior and
requires no code changes to keep working.
"""
import os
from pathlib import Path

# HuggingFace zero-shot object detection model. OWLv2 is an open-vocabulary
# detector: it locates objects from free-text prompts with no orchid-specific
# training data required, unlike a custom YOLO/Faster-RCNN model would.
MODEL_NAME = os.environ.get('ORCHID_DETECTOR_MODEL', 'google/owlv2-base-patch16-ensemble')

# Text prompt -> normalized object class key, used when the custom model is
# unavailable (all four classes are then detected zero-shot, as before).
OBJECT_CLASSES = {
    'orchid plant': 'orchid_plant',
    'orchid flower bunch': 'flower_bunch',
    'orchid flower bud': 'bud',
    'orchid seed pod': 'seed_pod',
}

# Text prompt -> normalized class key for the classes zero-shot detection is
# still responsible for even once the custom model is in use.
ZERO_SHOT_ONLY_CLASSES = {
    'orchid flower bud': 'bud',
}

# Minimum confidence to keep a zero-shot detection
SCORE_THRESHOLD = 0.15

# Path to the fine-tuned YOLOv8 weights produced by train.py / Colab training
# (see notebooks/colab_train.ipynb). Custom detection is skipped entirely if
# no file exists here yet.
CUSTOM_MODEL_PATH = Path(os.environ.get(
    'ORCHID_DETECTOR_CUSTOM_MODEL',
    str(Path(__file__).parent / 'models' / 'best.pt'),
))

# YOLO class index -> normalized object class key. Must match the class order
# written to data/yolo/data.yaml by prepare_dataset.py (CLASS_NAMES).
CUSTOM_CLASSES = {
    0: 'orchid_plant',
    1: 'flower_bunch',
    2: 'seed_pod',
}

# Minimum confidence to keep a custom-model detection
CUSTOM_SCORE_THRESHOLD = 0.25

# Extra pixels added around each detected box before cropping, so the
# downstream classifier sees a bit of context instead of a razor-tight crop
CROP_PADDING_RATIO = 0.08

# -1 = CPU, 0 = first GPU (matches HuggingFace `pipeline(device=...)` convention)
DEVICE = int(os.environ.get('ORCHID_DETECTOR_DEVICE', '-1'))
