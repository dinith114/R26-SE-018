"""
preprocess.py -- the ONE place training-time and inference-time image
preparation is defined.

Read this before writing any inference code.

--------------------------------------------------------------------------
THE RULE: this module produces raw RGB pixels in the range 0-255.
          It does NOT scale, normalise, or divide by 255.
--------------------------------------------------------------------------

Why. MobileNetV2 ships its own scaling function,
`tf.keras.applications.mobilenet_v2.preprocess_input`, which expects input in
0-255 and maps it to [-1, 1]. In this project that function is built INTO the
model as its first layer (see train.py), so the saved .keras file already
scales whatever it is given.

That means anything that also divides by 255 before calling the model feeds it
values in [0, 1], which preprocess_input then maps to roughly [-1, -0.99].
The model still returns three confident-looking probabilities. They are
meaningless, and nothing crashes, so the bug is invisible until someone
notices the predictions are nonsense.

An earlier version of this file divided by 255. That has been removed on
purpose. If you ever see `/ 255.0` reappear here, it is a bug.

--------------------------------------------------------------------------
The two stages called "processing" in this project -- do not confuse them
--------------------------------------------------------------------------

  data/processed/     FILE-LEVEL cleanup, done once by tools/augment_dataset.py:
                      EXIF rotation baked into pixels, converted to RGB,
                      long side capped at 1024px. Happens before training and
                      never again.

  preprocess.py       TRAINING/INFERENCE-TIME preparation, done on every image
                      every time: resize to 224x224 and hand raw 0-255 pixels
                      to the model.

--------------------------------------------------------------------------
Why there is no background removal or lesion cropping here
--------------------------------------------------------------------------

Two independent reasons, both worth stating in the report.

1. SEVERITY WOULD BREAK. Severity is graded as the percentage of leaf area
   affected. Cropping to the lesion raises that percentage; cropping away a
   lesion lowers it. Because augmented copies inherit the severity of their
   source image, any crop silently corrupts the severity label of 54 files at
   a time. This is why tools/augment_dataset.py contains rotation and colour
   changes but no crop or zoom.

2. TRAIN / DEPLOY MISMATCH. A grower photographs a plant in a shade house.
   The photo has pots, other leaves, netting and sky in it. If the model is
   trained only on clean cut-outs it has never seen that, and accuracy drops
   exactly where it matters. Removing the background at inference too would
   mean shipping and maintaining a second segmentation model, which is more
   work and one more thing that can fail.

MobileNetV2's convolutional layers already learn which regions carry the
signal; that is what the ImageNet pretraining bought. Segmentation-based
background removal is worth listing as future work, not as a change to make
under a 1.5 day deadline.
"""

from pathlib import Path

import numpy as np
import tensorflow as tf

# Input size the model is built for. Changing this means retraining.
IMG_SIZE = (224, 224)

# Where the classifier's class-name file lives. Keras orders classes
# alphabetically by folder name; this file records that order so inference
# never has to guess it.
COMPONENT_ROOT = Path(__file__).resolve().parent.parent
CLASS_NAMES_PATH = COMPONENT_ROOT / "models" / "class_names.json"


def load_class_names(path=None):
    """
    Return the class names in the exact order the model outputs them.

    Never hardcode this list. Keras assigns index 0 to the alphabetically
    first folder name, so adding a class called 'anthracnose' later would
    shift every existing index by one and silently remap every prediction to
    the wrong disease.
    """
    import json
    p = Path(path) if path else CLASS_NAMES_PATH
    if not p.exists():
        raise FileNotFoundError(
            "{} not found. It is written by train.py; without it, predictions "
            "cannot be mapped to disease names.".format(p))
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def decode_and_resize(image_bytes):
    """
    Bytes of a JPEG/PNG -> float32 tensor (224, 224, 3) with values 0-255.

    Used by the backend, which receives an uploaded file rather than a path.
    """
    img = tf.io.decode_image(image_bytes, channels=3, expand_animations=False)
    img = tf.image.resize(img, IMG_SIZE, method="bilinear")
    return tf.cast(img, tf.float32)          # still 0-255, deliberately


def load_image(path):
    """File path -> float32 tensor (224, 224, 3), values 0-255."""
    return decode_and_resize(tf.io.read_file(str(path)))


def prepare_batch(paths):
    """
    List of file paths -> float32 array (N, 224, 224, 3), values 0-255,
    ready to pass straight to model.predict().
    """
    return np.stack([load_image(p).numpy() for p in paths])


def prepare_single(path_or_bytes):
    """
    One image -> float32 array (1, 224, 224, 3), values 0-255.

    Accepts a path or raw bytes, so the same call works for a local file and
    for an upload arriving at the backend.
    """
    if isinstance(path_or_bytes, (bytes, bytearray)):
        img = decode_and_resize(path_or_bytes)
    else:
        img = load_image(path_or_bytes)
    return np.expand_dims(img.numpy(), axis=0)


def predict(model, path_or_bytes, class_names=None, threshold=0.60):
    """
    Run one image through the classifier and apply the unknown-disease rule.

    Returns a dict:
        {'label', 'confidence', 'probabilities', 'is_confident'}

    If the highest probability falls below `threshold`, `label` becomes
    'unidentified'. This is how conditions outside the three trained classes
    are handled: there is no trained 'other' class, because there were not
    enough images of anything else to train one. Tune `threshold` on the
    VALIDATION set, never on the test set.
    """
    names = class_names if class_names is not None else load_class_names()
    probs = model.predict(prepare_single(path_or_bytes), verbose=0)[0]
    idx = int(np.argmax(probs))
    confidence = float(probs[idx])
    confident = confidence >= threshold
    return {
        "label": names[idx] if confident else "unidentified",
        "raw_label": names[idx],
        "confidence": confidence,
        "is_confident": confident,
        "probabilities": {n: float(p) for n, p in zip(names, probs)},
    }
