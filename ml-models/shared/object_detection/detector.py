"""
Object detector for locating individual orchid plants, flower bunches, buds,
and seed pods within a single image.

Detection is hybrid: a custom YOLOv8 model, fine-tuned on real photos (see
prepare_dataset.py + train.py), handles orchid_plant / flower_bunch /
seed_pod. There's no bud training data yet, so bud detection always falls
back to a pretrained open-vocabulary model (OWLv2) queried with a text
prompt. If the custom model hasn't been trained yet, ALL four classes fall
back to zero-shot - so this still works with zero setup, same as before.
"""
from pathlib import Path
from typing import Any, Dict, List, Union

from PIL import Image

from .config import (
    CUSTOM_CLASSES,
    CUSTOM_MODEL_PATH,
    CUSTOM_SCORE_THRESHOLD,
    DEVICE,
    MODEL_NAME,
    OBJECT_CLASSES,
    SCORE_THRESHOLD,
    ZERO_SHOT_ONLY_CLASSES,
)


class OrchidObjectDetector:
    """
    Finds orchid plants, flower bunches, buds, and seed pods in an image,
    using the custom YOLO model where it's trained and zero-shot elsewhere.
    """

    _pipeline = None      # shared HF zero-shot pipeline, loads once
    _custom_model = None  # shared YOLO model, loads once

    def __init__(self, model_name: str = MODEL_NAME, score_threshold: float = SCORE_THRESHOLD,
                 custom_model_path: Union[str, Path] = CUSTOM_MODEL_PATH,
                 custom_score_threshold: float = CUSTOM_SCORE_THRESHOLD):
        self.model_name = model_name
        self.score_threshold = score_threshold
        self.custom_model_path = Path(custom_model_path)
        self.custom_score_threshold = custom_score_threshold
        self.use_custom_model = self.custom_model_path.exists()

    def _get_pipeline(self):
        if OrchidObjectDetector._pipeline is None:
            from transformers import pipeline
            OrchidObjectDetector._pipeline = pipeline(
                task='zero-shot-object-detection',
                model=self.model_name,
                device=DEVICE,
            )
        return OrchidObjectDetector._pipeline

    def _get_custom_model(self):
        if OrchidObjectDetector._custom_model is None:
            from ultralytics import YOLO
            OrchidObjectDetector._custom_model = YOLO(str(self.custom_model_path))
        return OrchidObjectDetector._custom_model

    def _detect_custom(self, img: Image.Image) -> List[Dict[str, Any]]:
        model = self._get_custom_model()
        result = model.predict(img, conf=self.custom_score_threshold, verbose=False)[0]

        detections = []
        for box in result.boxes:
            class_id = int(box.cls[0])
            label = CUSTOM_CLASSES.get(class_id)
            if label is None:
                continue
            xmin, ymin, xmax, ymax = box.xyxy[0].tolist()
            detections.append({
                'object_class': label,
                'label': label,
                'confidence': float(box.conf[0]),
                'box': {
                    'xmin': int(xmin),
                    'ymin': int(ymin),
                    'xmax': int(xmax),
                    'ymax': int(ymax),
                },
            })
        return detections

    def _detect_zero_shot(self, img: Image.Image, candidate_labels: List[str],
                           class_map: Dict[str, str]) -> List[Dict[str, Any]]:
        detector = self._get_pipeline()
        raw_results = detector(img, candidate_labels=candidate_labels)

        detections = []
        for result in raw_results:
            if result['score'] < self.score_threshold:
                continue
            box = result['box']
            detections.append({
                'object_class': class_map.get(result['label'], result['label']),
                'label': result['label'],
                'confidence': float(result['score']),
                'box': {
                    'xmin': int(box['xmin']),
                    'ymin': int(box['ymin']),
                    'xmax': int(box['xmax']),
                    'ymax': int(box['ymax']),
                },
            })
        return detections

    def detect(self, image: Union[str, Path, Image.Image]) -> List[Dict[str, Any]]:
        """
        Detect orchid plants/flower bunches/buds/seed pods in an image.

        Args:
            image: A file path or an already-loaded PIL image.

        Returns:
            List of detections, each with object_class, label, confidence,
            and a pixel box ({'xmin','ymin','xmax','ymax'}).
        """
        if isinstance(image, Image.Image):
            img = image.convert('RGB')
        else:
            img = Image.open(image).convert('RGB')

        if self.use_custom_model:
            detections = self._detect_custom(img)
            detections += self._detect_zero_shot(img, list(ZERO_SHOT_ONLY_CLASSES.keys()), ZERO_SHOT_ONLY_CLASSES)
        else:
            detections = self._detect_zero_shot(img, list(OBJECT_CLASSES.keys()), OBJECT_CLASSES)

        return detections
