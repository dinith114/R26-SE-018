"""
Shared zero-shot object detection for locating orchid plants, flower
bunches, buds, and seed pods within a photo, used by both the growth_stage
and bloom_prediction components.
"""
from .config import OBJECT_CLASSES
from .detector import OrchidObjectDetector

__all__ = ['OrchidObjectDetector', 'OBJECT_CLASSES']
