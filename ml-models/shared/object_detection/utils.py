"""
Cropping helpers for turning detector boxes into classifier-ready images.
"""
from typing import Any, Dict, List

from PIL import Image

from .config import CROP_PADDING_RATIO


def crop_detection(image: Image.Image, box: Dict[str, int], padding_ratio: float = CROP_PADDING_RATIO) -> Image.Image:
    """Crop `box` out of `image`, expanded by `padding_ratio` on each side."""
    width, height = image.size
    box_w = box['xmax'] - box['xmin']
    box_h = box['ymax'] - box['ymin']
    pad_x = int(box_w * padding_ratio)
    pad_y = int(box_h * padding_ratio)

    left = max(0, box['xmin'] - pad_x)
    top = max(0, box['ymin'] - pad_y)
    right = min(width, box['xmax'] + pad_x)
    bottom = min(height, box['ymax'] + pad_y)

    return image.crop((left, top, right, bottom))


def crop_all_detections(image: Image.Image, detections: List[Dict[str, Any]]) -> List[Image.Image]:
    """Crop every detection's box out of `image`, in the same order as `detections`."""
    return [crop_detection(image, det['box']) for det in detections]
