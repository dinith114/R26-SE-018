"""
Hybrid Pollination - Feature Extraction Module
Extracts plant-level and flower-level features from orchid images using OpenCV.
"""

import cv2
import numpy as np


def extract_color_features(image_path: str) -> dict:
    """
    Extract color-based features from an orchid flower image.

    Returns:
        dict with mean RGB, HSV values and dominant color info
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not load image: {image_path}")

    # Convert to RGB
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    features = {
        "mean_r": np.mean(img_rgb[:, :, 0]),
        "mean_g": np.mean(img_rgb[:, :, 1]),
        "mean_b": np.mean(img_rgb[:, :, 2]),
        "mean_h": np.mean(img_hsv[:, :, 0]),
        "mean_s": np.mean(img_hsv[:, :, 1]),
        "mean_v": np.mean(img_hsv[:, :, 2]),
    }

    return features


def extract_shape_features(image_path: str) -> dict:
    """
    Extract shape/morphological features from an orchid flower image.

    Returns:
        dict with contour area, perimeter, aspect ratio, symmetry score
    """
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError(f"Could not load image: {image_path}")

    # Preprocessing
    blurred = cv2.GaussianBlur(img, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return {"area": 0, "perimeter": 0, "aspect_ratio": 0, "circularity": 0}

    # Use the largest contour (likely the flower)
    largest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest)
    perimeter = cv2.arcLength(largest, True)
    x, y, w, h = cv2.boundingRect(largest)

    features = {
        "area": area,
        "perimeter": perimeter,
        "aspect_ratio": w / h if h > 0 else 0,
        "circularity": (4 * np.pi * area) / (perimeter**2) if perimeter > 0 else 0,
    }

    return features


def extract_leaf_features(image_path: str) -> dict:
    """
    Extract leaf health indicators from a plant image.
    Analyzes green channel dominance and color distribution.

    Returns:
        dict with leaf health indicators
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not load image: {image_path}")

    img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # Green color range for healthy leaves
    lower_green = np.array([35, 40, 40])
    upper_green = np.array([85, 255, 255])
    green_mask = cv2.inRange(img_hsv, lower_green, upper_green)

    total_pixels = img.shape[0] * img.shape[1]
    green_pixels = cv2.countNonZero(green_mask)

    features = {
        "green_ratio": green_pixels / total_pixels if total_pixels > 0 else 0,
        "green_pixel_count": green_pixels,
    }

    return features
