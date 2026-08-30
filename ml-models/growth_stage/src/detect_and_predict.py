"""
Detect individual orchid plants / flower bunches / buds / seed pods in a
single photo, then predict a growth stage for each detected object
separately - instead of one growth-stage guess blended across everything
in the frame.
"""
import sys
from pathlib import Path
from typing import Union

from PIL import Image

# Add ml-models/ to path so the shared object_detection package is importable
sys.path.append(str(Path(__file__).parent.parent.parent))

from shared.object_detection import OrchidObjectDetector
from shared.object_detection.utils import crop_detection

from src.predict import GrowthStagePredictor


class GrowthStageDetectionPipeline:
    """
    Combines the zero-shot orchid object detector with the growth-stage
    classifier: detect objects first, then classify each detected crop.
    """

    def __init__(self, model_path: Path):
        self.detector = OrchidObjectDetector()
        self.stage_predictor = GrowthStagePredictor(model_path)

    def analyze(self, image_path: Union[str, Path], top_k: int = 3) -> dict:
        """
        Args:
            image_path: Path to the uploaded image
            top_k: Number of top stage predictions to return per object

        Returns:
            Dict with the total object count and a per-object growth-stage
            prediction (object_class, detection_confidence, box, plus the
            usual predict_image() fields: stage_key, stage_name, confidence,
            top_predictions, stage_info).
        """
        image = Image.open(image_path).convert('RGB')
        detections = self.detector.detect(image)

        results = []
        for det in detections:
            crop = crop_detection(image, det['box'])
            stage_result = self.stage_predictor.predict_image(crop, top_k=top_k)
            results.append({
                'object_class': det['object_class'],
                'detection_confidence': det['confidence'],
                'box': det['box'],
                **stage_result,
            })

        return {
            'objects_detected': len(results),
            'detections': results,
        }
