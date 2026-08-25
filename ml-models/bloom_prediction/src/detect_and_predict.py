"""
Detect individual orchid plants / flower bunches / buds / seed pods in a
single photo, then predict a bloom date for each detected object separately
- instead of one bloom-date guess blended across everything in the frame.

The temperature/humidity/light readings are entered once per photo (they
describe the growing environment, not any single object), and are reused for
every detected object's prediction.
"""
import sys
from pathlib import Path
from typing import Optional, Union

from PIL import Image

# Add ml-models/ to path so the shared object_detection package is importable
sys.path.append(str(Path(__file__).parent.parent.parent))

from shared.object_detection import OrchidObjectDetector
from shared.object_detection.utils import crop_detection

from src.predict import BloomPredictor


class BloomDetectionPipeline:
    """
    Combines the zero-shot orchid object detector with the bloom-date
    predictor: detect objects first, then predict a bloom date for each
    detected crop.
    """

    def __init__(self, model_dir: Path):
        self.detector = OrchidObjectDetector()
        self.bloom_predictor = BloomPredictor(model_dir)

    def analyze(self, image_path: Union[str, Path], temperature: float,
                humidity: float, light_intensity: float,
                capture_date: Optional[str] = None) -> dict:
        """
        Args:
            image_path: Path to the uploaded photo
            temperature: Degrees C at capture time
            humidity: Relative humidity % at capture time
            light_intensity: Light level (lux) at capture time
            capture_date: 'YYYY-MM-DD' the photo was taken; defaults to today

        Returns:
            Dict with the total object count and a per-object bloom-date
            prediction (object_class, detection_confidence, box, plus the
            usual predict_image() fields: days_until_bloom,
            predicted_bloom_date, input_conditions).
        """
        image = Image.open(image_path).convert('RGB')
        detections = self.detector.detect(image)

        results = []
        for det in detections:
            crop = crop_detection(image, det['box'])
            bloom_result = self.bloom_predictor.predict_image(
                crop, temperature, humidity, light_intensity, capture_date
            )
            results.append({
                'object_class': det['object_class'],
                'detection_confidence': det['confidence'],
                'box': det['box'],
                **bloom_result,
            })

        return {
            'objects_detected': len(results),
            'detections': results,
        }
