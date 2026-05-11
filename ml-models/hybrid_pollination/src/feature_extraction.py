"""
Hybrid Pollination - Feature Extraction Module
Extracts plant-level and flower-level features from orchid images using OpenCV.

Features extracted:
    - Color features (RGB, HSV means + color histogram)
    - Shape features (contour area, perimeter, aspect ratio, circularity)
    - Texture features (Gabor filter responses)
    - Leaf health features (green pixel ratio)
"""

import cv2
import numpy as np
import os


# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
TARGET_SIZE = (256, 256)  # Resize all images to this for consistency


def load_and_resize(image_path: str) -> np.ndarray:
    """
    Load an image and resize it to TARGET_SIZE.
    Returns the BGR image (OpenCV default).
    """
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not load image: {image_path}")
    img = cv2.resize(img, TARGET_SIZE)
    return img


# ──────────────────────────────────────────────
# Color Features
# ──────────────────────────────────────────────
def extract_color_features(img: np.ndarray) -> dict:
    """
    Extract color-based features from an orchid image.

    Returns:
        dict with mean RGB, HSV values and color histogram features
    """
    # Convert color spaces
    img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    features = {
        # Mean channel values
        "mean_r": float(np.mean(img_rgb[:, :, 0])),
        "mean_g": float(np.mean(img_rgb[:, :, 1])),
        "mean_b": float(np.mean(img_rgb[:, :, 2])),
        "mean_h": float(np.mean(img_hsv[:, :, 0])),
        "mean_s": float(np.mean(img_hsv[:, :, 1])),
        "mean_v": float(np.mean(img_hsv[:, :, 2])),
        # Standard deviations (color variation)
        "std_r": float(np.std(img_rgb[:, :, 0])),
        "std_g": float(np.std(img_rgb[:, :, 1])),
        "std_b": float(np.std(img_rgb[:, :, 2])),
        "std_h": float(np.std(img_hsv[:, :, 0])),
        "std_s": float(np.std(img_hsv[:, :, 1])),
        "std_v": float(np.std(img_hsv[:, :, 2])),
    }

    # Color histogram (8 bins per channel, normalized)
    for i, channel_name in enumerate(["h", "s", "v"]):
        hist = cv2.calcHist([img_hsv], [i], None, [8],
                            [0, 180] if i == 0 else [0, 256])
        hist = hist.flatten() / hist.sum()  # Normalize
        for j, val in enumerate(hist):
            features[f"hist_{channel_name}_{j}"] = float(val)

    return features


# ──────────────────────────────────────────────
# Shape Features
# ──────────────────────────────────────────────
def extract_shape_features(img: np.ndarray) -> dict:
    """
    Extract shape/morphological features from an orchid image.

    Returns:
        dict with contour area, perimeter, aspect ratio, circularity
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Preprocessing
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return {
            "contour_area": 0.0,
            "contour_perimeter": 0.0,
            "aspect_ratio": 0.0,
            "circularity": 0.0,
            "solidity": 0.0,
            "contour_count": 0,
        }

    # Use the largest contour (likely the plant/flower)
    largest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest)
    perimeter = cv2.arcLength(largest, True)
    x, y, w, h = cv2.boundingRect(largest)

    # Solidity = contour area / convex hull area
    hull = cv2.convexHull(largest)
    hull_area = cv2.contourArea(hull)

    # Normalize area by image size
    img_area = img.shape[0] * img.shape[1]

    features = {
        "contour_area": float(area / img_area),  # Normalized
        "contour_perimeter": float(perimeter / (2 * (img.shape[0] + img.shape[1]))),  # Normalized
        "aspect_ratio": float(w / h) if h > 0 else 0.0,
        "circularity": float((4 * np.pi * area) / (perimeter ** 2)) if perimeter > 0 else 0.0,
        "solidity": float(area / hull_area) if hull_area > 0 else 0.0,
        "contour_count": len(contours),
    }

    return features


# ──────────────────────────────────────────────
# Texture Features (Gabor Filters)
# ──────────────────────────────────────────────
def extract_texture_features(img: np.ndarray) -> dict:
    """
    Extract texture features using Gabor filters.

    Returns:
        dict with Gabor filter response statistics
    """
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = gray.astype(np.float32) / 255.0

    features = {}
    thetas = [0, np.pi / 4, np.pi / 2, 3 * np.pi / 4]  # 4 orientations
    frequencies = [0.1, 0.3]  # 2 frequencies

    for i, theta in enumerate(thetas):
        for j, freq in enumerate(frequencies):
            kernel = cv2.getGaborKernel(
                ksize=(21, 21),
                sigma=4.0,
                theta=theta,
                lambd=1.0 / freq,
                gamma=0.5,
                psi=0
            )
            filtered = cv2.filter2D(gray, cv2.CV_32F, kernel)
            features[f"gabor_mean_{i}_{j}"] = float(np.mean(filtered))
            features[f"gabor_std_{i}_{j}"] = float(np.std(filtered))

    return features


# ──────────────────────────────────────────────
# Leaf Health Features
# ──────────────────────────────────────────────
def extract_leaf_features(img: np.ndarray) -> dict:
    """
    Extract leaf health indicators from a plant image.
    Analyzes green channel dominance and color distribution.

    Returns:
        dict with leaf health indicators
    """
    img_hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)

    # Green color range for healthy leaves
    lower_green = np.array([35, 40, 40])
    upper_green = np.array([85, 255, 255])
    green_mask = cv2.inRange(img_hsv, lower_green, upper_green)

    # Brown/yellow range for unhealthy/diseased areas
    lower_brown = np.array([10, 50, 50])
    upper_brown = np.array([30, 255, 200])
    brown_mask = cv2.inRange(img_hsv, lower_brown, upper_brown)

    total_pixels = img.shape[0] * img.shape[1]
    green_pixels = cv2.countNonZero(green_mask)
    brown_pixels = cv2.countNonZero(brown_mask)

    features = {
        "green_ratio": float(green_pixels / total_pixels) if total_pixels > 0 else 0.0,
        "brown_ratio": float(brown_pixels / total_pixels) if total_pixels > 0 else 0.0,
        "green_brown_ratio": float(green_pixels / (brown_pixels + 1)),  # +1 to avoid division by zero
        "green_pixel_count": int(green_pixels),
    }

    return features


# ──────────────────────────────────────────────
# Unified Feature Extraction
# ──────────────────────────────────────────────
def extract_all_features(image_path: str) -> dict:
    """
    Extract ALL features from an image in one call.

    Args:
        image_path: Path to the image file

    Returns:
        dict with all features combined (~50 features total)
    """
    img = load_and_resize(image_path)

    features = {}
    features.update(extract_color_features(img))
    features.update(extract_shape_features(img))
    features.update(extract_texture_features(img))
    features.update(extract_leaf_features(img))

    return features


def extract_features_batch(image_paths: list, show_progress: bool = True) -> list:
    """
    Extract features from multiple images.

    Args:
        image_paths: List of image file paths
        show_progress: Whether to print progress

    Returns:
        List of feature dicts (one per image). Failed images return None.
    """
    results = []
    total = len(image_paths)

    for i, path in enumerate(image_paths):
        if show_progress and (i + 1) % 20 == 0:
            print(f"  Extracting features: {i + 1}/{total} ({(i + 1) / total * 100:.0f}%)")

        try:
            features = extract_all_features(path)
            features["image_path"] = path
            results.append(features)
        except Exception as e:
            if show_progress:
                print(f"  [WARN] Failed to process {os.path.basename(path)}: {e}")
            results.append(None)

    success = sum(1 for r in results if r is not None)
    if show_progress:
        print(f"  Done: {success}/{total} images processed successfully")

    return results


def get_feature_names() -> list:
    """Return the list of all feature names in order (for reference)."""
    # Create a dummy image to get feature names
    dummy = np.zeros((256, 256, 3), dtype=np.uint8)
    features = {}
    features.update(extract_color_features(dummy))
    features.update(extract_shape_features(dummy))
    features.update(extract_texture_features(dummy))
    features.update(extract_leaf_features(dummy))
    return list(features.keys())


# ──────────────────────────────────────────────
# Test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    # Print all feature names
    names = get_feature_names()
    print(f"Total features: {len(names)}")
    print("Feature names:")
    for name in names:
        print(f"  - {name}")

    # Test with a real image if available
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    test_dir = os.path.join(BASE_DIR, "data", "images", "plants")
    if os.path.exists(test_dir):
        images = [f for f in os.listdir(test_dir) if f.lower().endswith((".jpg", ".png"))]
        if images:
            test_path = os.path.join(test_dir, images[0])
            print(f"\nTest extraction on: {images[0]}")
            features = extract_all_features(test_path)
            for k, v in features.items():
                print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
