"""
Data preprocessing and augmentation for growth stage classification.
"""
import os
import numpy as np
import pandas as pd
from pathlib import Path
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from tensorflow.keras.preprocessing.image import ImageDataGenerator
from tensorflow.keras.utils import to_categorical
from typing import Tuple, Optional, Dict, Any
import random
from .config import STAGE_LABELS, MODEL_CONFIG


class DataPreprocessor:
    """
    Class for preprocessing image data for growth stage classification.
    """
    
    def __init__(self, data_dir: Path, 
                 target_size: Tuple[int, int] = None,
                 batch_size: int = None):
        """
        Initialize the data preprocessor.
        """
        self.data_dir = Path(data_dir)
        self.target_size = target_size or MODEL_CONFIG['target_size']
        self.batch_size = batch_size or MODEL_CONFIG['batch_size']
        self.stage_labels = STAGE_LABELS
        self.label_encoder = LabelEncoder()
        self.label_encoder.fit(self.stage_labels)
        
        # Check if data directory exists
        if not self.data_dir.exists():
            raise FileNotFoundError(f"Data directory not found: {self.data_dir}")
    
    def load_data(self) -> Tuple[ImageDataGenerator, ImageDataGenerator]:
        """
        Load and split the dataset using flow_from_directory.
        """
        train_datagen = self._get_train_datagen()
        test_datagen = self._get_test_datagen()
        
        # Training generator
        # `classes=self.stage_labels` pins each class to the index matching
        # STAGE_LABELS order. Without it, flow_from_directory assigns indices
        # alphabetically by folder name, which silently desyncs from
        # STAGE_LABELS and corrupts every downstream label lookup
        # (evaluation reports, confusion matrix, and predict.py results).
        train_generator = train_datagen.flow_from_directory(
            self.data_dir,
            target_size=self.target_size,
            batch_size=self.batch_size,
            class_mode='categorical',
            classes=self.stage_labels,
            subset='training',
            shuffle=True,
            seed=42
        )

        # Validation generator
        validation_generator = test_datagen.flow_from_directory(
            self.data_dir,
            target_size=self.target_size,
            batch_size=self.batch_size,
            class_mode='categorical',
            classes=self.stage_labels,
            subset='validation',
            shuffle=False,
            seed=42
        )
        
        return train_generator, validation_generator
    
    def _get_train_datagen(self) -> ImageDataGenerator:
        """
        Create training data generator with augmentation.

        No `rescale` here deliberately: create_cnn_model() (model.py) already
        applies the model-type-specific preprocess_input as the model's first
        layer, which expects raw [0,255] pixels (for efficientnet that's a
        Keras-documented no-op passthrough, since EfficientNet bakes its own
        Rescaling(1./255) layer into the model). Rescaling here too would
        silently rescale pixels twice, crushing them to near-zero and
        starving the frozen backbone of any real signal.
        """
        return ImageDataGenerator(
            rotation_range=20,
            width_shift_range=0.2,
            height_shift_range=0.2,
            shear_range=0.15,
            zoom_range=0.2,
            horizontal_flip=True,
            vertical_flip=True,
            brightness_range=[0.8, 1.2],
            fill_mode='nearest',
            validation_split=0.2
        )

    def _get_test_datagen(self) -> ImageDataGenerator:
        """Create test data generator without augmentation (see _get_train_datagen for why no rescale)."""
        return ImageDataGenerator(
            validation_split=0.2
        )
    
    def get_class_weights(self, train_generator) -> Dict[int, float]:
        """
        Calculate class weights for imbalanced data.
        """
        from sklearn.utils.class_weight import compute_class_weight
        
        # Get class labels from generator
        classes = train_generator.classes
        num_classes = len(train_generator.class_indices)
        
        # Get all unique classes
        unique_classes = np.unique(classes)
        
        # Compute weights for all classes
        weights = compute_class_weight(
            'balanced',
            classes=unique_classes,
            y=classes
        )
        
        # Create dictionary with all class indices (0 to num_classes-1)
        class_weight_dict = {}
        for i, cls in enumerate(unique_classes):
            class_weight_dict[cls] = weights[i]
        
        # Fill in any missing classes with default weight of 1.0
        for i in range(num_classes):
            if i not in class_weight_dict:
                class_weight_dict[i] = 1.0
        
        return class_weight_dict
    
    def get_dataset_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the dataset.
        """
        stats = {
            'total_images': 0,
            'images_per_class': {},
            'classes': self.stage_labels
        }
        
        for stage in self.stage_labels:
            stage_dir = self.data_dir / stage
            if stage_dir.exists():
                count = len(list(stage_dir.glob('*.*')))
                stats['images_per_class'][stage] = count
                stats['total_images'] += count
            else:
                stats['images_per_class'][stage] = 0
        
        return stats


class AugmentationPipeline:
    """
    Custom augmentation pipeline for the growth stage dataset.
    """
    
    @staticmethod
    def augment_image(image: np.ndarray) -> np.ndarray:
        """
        Apply augmentation to a single image.
        """
        import cv2
        
        # Random horizontal flip
        if random.random() > 0.5:
            image = cv2.flip(image, 1)
        
        # Random rotation
        angle = random.uniform(-15, 15)
        h, w = image.shape[:2]
        M = cv2.getRotationMatrix2D((w/2, h/2), angle, 1)
        image = cv2.warpAffine(image, M, (w, h))
        
        # Random brightness adjustment
        brightness = random.uniform(0.8, 1.2)
        image = image * brightness
        
        # Random contrast adjustment
        contrast = random.uniform(0.8, 1.2)
        image = image * contrast
        
        return np.clip(image, 0, 1)
    
    @staticmethod
    def augment_dataset(X: np.ndarray, y: np.ndarray, 
                       augmentation_factor: int = 2) -> Tuple[np.ndarray, np.ndarray]:
        """
        Augment the entire dataset.
        """
        X_augmented = []
        y_augmented = []
        
        for i in range(len(X)):
            # Original image
            X_augmented.append(X[i])
            y_augmented.append(y[i])
            
            # Augmented versions
            for _ in range(augmentation_factor):
                augmented_img = AugmentationPipeline.augment_image(X[i])
                X_augmented.append(augmented_img)
                y_augmented.append(y[i])
        
        return np.array(X_augmented), np.array(y_augmented)