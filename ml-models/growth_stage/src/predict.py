"""
Prediction script for growth stage classification.
"""
import os
import sys
import argparse
import json
from pathlib import Path
import numpy as np
from PIL import Image
import tensorflow as tf

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from src.config import STAGE_LABELS, STAGE_NAMES, MODEL_CONFIG
from src.utils import load_image, preprocess_pil_image, format_prediction, get_stage_info


class GrowthStagePredictor:
    """
    Class for making predictions on orchid growth stages.
    """
    
    def __init__(self, model_path: Path):
        """
        Initialize the predictor.
        
        Args:
            model_path: Path to the trained model file
        """
        self.model_path = Path(model_path)
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model not found: {self.model_path}")
        
        self.model = tf.keras.models.load_model(self.model_path)
        self.input_shape = self.model.input_shape[1:3]
        
    def predict(self, image_path: Path, top_k: int = 3) -> dict:
        """
        Predict the growth stage of an orchid image.
        
        Args:
            image_path: Path to the image file
            top_k: Number of top predictions to return
        
        Returns:
            Dictionary with prediction results
        """
        # Load and preprocess image
        img_array = load_image(image_path, target_size=self.input_shape)
        
        # Make prediction
        predictions = self.model.predict(img_array, verbose=0)
        
        # Format results
        result = format_prediction(predictions[0], top_k=top_k)

        return result

    def predict_image(self, image: Image.Image, top_k: int = 3) -> dict:
        """
        Predict the growth stage of an already-loaded PIL image (e.g. a crop
        produced by the object detector), with no file on disk.

        Args:
            image: PIL image
            top_k: Number of top predictions to return

        Returns:
            Dictionary with prediction results
        """
        img_array = preprocess_pil_image(image, target_size=self.input_shape)
        predictions = self.model.predict(img_array, verbose=0)
        return format_prediction(predictions[0], top_k=top_k)

    def predict_batch(self, image_paths: list, top_k: int = 3) -> list:
        """
        Predict growth stages for multiple images.
        """
        results = []
        for img_path in image_paths:
            result = self.predict(img_path, top_k=top_k)
            results.append(result)
        return results


def main():
    parser = argparse.ArgumentParser(description='Predict growth stage from image')
    parser.add_argument('--model_path', type=str, required=True,
                        help='Path to the trained model')
    parser.add_argument('--image_path', type=str, required=True,
                        help='Path to the image file')
    parser.add_argument('--top_k', type=int, default=3,
                        help='Number of top predictions to show')
    
    args = parser.parse_args()
    
    # Initialize predictor
    predictor = GrowthStagePredictor(Path(args.model_path))
    
    # Make prediction
    result = predictor.predict(Path(args.image_path), top_k=args.top_k)
    
    # Print results
    print("\n" + "=" * 60)
    print("Growth Stage Prediction Results")
    print("=" * 60)
    
    print(f"\nPredicted Stage: {result['stage_name']}")
    print(f"Confidence: {result['confidence']*100:.1f}%")
    print(f"Stage Key: {result['stage_key']}")
    print(f"Description: {result['stage_info']['stage_description']}")
    
    print("\nTop Predictions:")
    for i, pred in enumerate(result['top_predictions'], 1):
        print(f"  {i}. {pred['stage_name']}: {pred['confidence']*100:.1f}%")
    
    print("\nCare Protocol:")
    for key, value in result['stage_info']['care_protocol'].items():
        print(f"  {key.capitalize()}: {value}")
    
    print("=" * 60)


if __name__ == "__main__":
    main()