"""
Prediction script for bloom date prediction.
"""
import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Optional, Union

import numpy as np
import tensorflow as tf
from PIL import Image

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from src.config import TABULAR_FEATURES
from src.utils import compute_bloom_date, load_model_artifacts, preprocess_pil_image


class BloomPredictor:
    """
    Predicts days until bloom (and the resulting bloom date) from a plant
    photo plus its temperature/humidity/light readings.
    """

    def __init__(self, model_dir: Path):
        """
        Args:
            model_dir: Directory containing vanda_bloom_model.h5,
                tabular_scaler.pkl, and model_config.json
                (see src/utils.py:save_model_artifacts)
        """
        self.model_dir = Path(model_dir)
        self.model, self.scaler, self.config = load_model_artifacts(self.model_dir)
        self.input_shape = self.model.input_shape[0][1:3]

    def predict(self, image_path: Union[str, Path], temperature: float,
                humidity: float, light_intensity: float,
                capture_date: Optional[str] = None) -> dict:
        """
        Args:
            image_path: Path to the plant/flower photo
            temperature: Degrees C at capture time
            humidity: Relative humidity % at capture time
            light_intensity: Light level (lux) at capture time
            capture_date: 'YYYY-MM-DD' the photo was taken; defaults to today

        Returns:
            Dict with days_until_bloom and predicted_bloom_date
        """
        image = Image.open(image_path).convert('RGB')
        return self.predict_image(image, temperature, humidity, light_intensity, capture_date)

    def predict_image(self, image: Image.Image, temperature: float,
                      humidity: float, light_intensity: float,
                      capture_date: Optional[str] = None) -> dict:
        """
        Same as predict(), but for an already-loaded PIL image (e.g. a crop
        produced by the object detector), with no file on disk.
        """
        img_array = preprocess_pil_image(image, target_size=self.input_shape)

        tabular_values = {'Temperature': temperature, 'Humidity': humidity, 'Light intensity': light_intensity}
        tabular_row = np.array([[tabular_values[col] for col in TABULAR_FEATURES]], dtype='float32')
        tabular_scaled = self.scaler.transform(tabular_row)

        days_until_bloom = float(self.model.predict((img_array, tabular_scaled), verbose=0)[0][0])
        days_until_bloom = max(0.0, days_until_bloom)
        bloom_date = compute_bloom_date(days_until_bloom, capture_date)

        return {
            'days_until_bloom': round(days_until_bloom),
            'predicted_bloom_date': bloom_date.isoformat(),
            'input_conditions': {
                'temperature': temperature,
                'humidity': humidity,
                'light_intensity': light_intensity,
                'capture_date': capture_date or date.today().isoformat(),
            },
        }


def main():
    parser = argparse.ArgumentParser(description='Predict bloom date from an image and sensor readings')
    parser.add_argument('--model_dir', type=str, required=True,
                        help='Directory containing the trained model artifacts')
    parser.add_argument('--image_path', type=str, required=True,
                        help='Path to the image file')
    parser.add_argument('--temperature', type=float, required=True, help='Temperature (C)')
    parser.add_argument('--humidity', type=float, required=True, help='Relative humidity (%)')
    parser.add_argument('--light_intensity', type=float, required=True, help='Light intensity (lux)')
    parser.add_argument('--capture_date', type=str, default=None,
                        help='Date the photo was taken, YYYY-MM-DD (defaults to today)')

    args = parser.parse_args()

    predictor = BloomPredictor(Path(args.model_dir))
    result = predictor.predict(
        Path(args.image_path), args.temperature, args.humidity,
        args.light_intensity, args.capture_date
    )

    print("\n" + "=" * 60)
    print("Bloom Date Prediction Results")
    print("=" * 60)
    print(f"\nDays until bloom: {result['days_until_bloom']}")
    print(f"Predicted bloom date: {result['predicted_bloom_date']}")
    print("\nInput conditions:")
    for key, value in result['input_conditions'].items():
        print(f"  {key}: {value}")
    print("=" * 60)


if __name__ == "__main__":
    main()
