"""
Model architecture for growth stage classification.
"""
import tensorflow as tf
from tensorflow.keras import layers, models
from tensorflow.keras.applications import EfficientNetB3, MobileNetV2, ResNet50
from tensorflow.keras.optimizers import Adam
from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau, ModelCheckpoint
from typing import Tuple, Optional
from .config import MODEL_CONFIG


def create_base_model(model_type: str = 'efficientnet', 
                      input_shape: Tuple[int, int, int] = (224, 224, 3)):
    """
    Create base model with transfer learning.
    """
    if model_type == 'efficientnet':
        base_model = EfficientNetB3(
            weights='imagenet',
            include_top=False,
            input_shape=input_shape
        )
    elif model_type == 'mobilenet':
        base_model = MobileNetV2(
            weights='imagenet',
            include_top=False,
            input_shape=input_shape
        )
    elif model_type == 'resnet':
        base_model = ResNet50(
            weights='imagenet',
            include_top=False,
            input_shape=input_shape
        )
    else:
        raise ValueError(f"Unsupported model type: {model_type}")
    
    return base_model


def create_cnn_model(input_shape: Tuple[int, int, int] = (224, 224, 3),
                     num_classes: int = 7,
                     model_type: str = 'efficientnet') -> tf.keras.Model:
    """
    Create a CNN model for growth stage classification.
    """
    # Create base model
    base_model = create_base_model(model_type, input_shape)
    base_model.trainable = False
    
    # Build the complete model
    inputs = tf.keras.Input(shape=input_shape)
    
    # Preprocess input based on model type
    if model_type == 'efficientnet':
        x = tf.keras.applications.efficientnet.preprocess_input(inputs)
    elif model_type == 'mobilenet':
        x = tf.keras.applications.mobilenet_v2.preprocess_input(inputs)
    elif model_type == 'resnet':
        x = tf.keras.applications.resnet50.preprocess_input(inputs)
    else:
        x = inputs / 255.0
    
    # Base model
    x = base_model(x, training=False)
    
    # Global pooling
    x = layers.GlobalAveragePooling2D()(x)
    
    # Dense layers with dropout
    x = layers.Dense(512, activation='relu', kernel_regularizer='l2')(x)
    x = layers.BatchNormalization()(x)
    x = layers.Dropout(0.3)(x)
    
    x = layers.Dense(256, activation='relu', kernel_regularizer='l2')(x)
    x = layers.BatchNormalization()(x)
    x = layers.Dropout(0.3)(x)
    
    # Output layer
    outputs = layers.Dense(num_classes, activation='softmax')(x)
    
    model = models.Model(inputs, outputs, name=f'vanda_growth_{model_type}')
    
    # Compile model with simple metrics
    model.compile(
        optimizer=Adam(learning_rate=MODEL_CONFIG['learning_rate']),
        loss='categorical_crossentropy',
        metrics=['accuracy']
    )
    
    return model


def get_callbacks(model_save_path: str, patience: int = 10) -> list:
    """
    Get training callbacks.
    """
    callbacks = [
        EarlyStopping(
            monitor='val_loss',
            patience=patience,
            restore_best_weights=True,
            verbose=1
        ),
        ReduceLROnPlateau(
            monitor='val_loss',
            factor=0.2,
            patience=patience // 2,
            min_lr=1e-7,
            verbose=1
        ),
        ModelCheckpoint(
            model_save_path,
            monitor='val_accuracy',
            save_best_only=True,
            verbose=1
        )
    ]
    return callbacks


def get_model_summary(model: tf.keras.Model) -> str:
    """
    Get model summary as string.
    """
    from io import StringIO
    import sys
    
    old_stdout = sys.stdout
    sys.stdout = StringIO()
    model.summary()
    summary_str = sys.stdout.getvalue()
    sys.stdout = old_stdout
    
    return summary_str


def fine_tune_model(model: tf.keras.Model, 
                   base_model: tf.keras.Model,
                   num_layers: int = 30,
                   learning_rate: float = 0.0001) -> tf.keras.Model:
    """
    Fine-tune the last n layers of the base model.
    """
    # Unfreeze the base model
    base_model.trainable = True
    
    # Freeze all layers
    for layer in base_model.layers:
        layer.trainable = False
    
    # Unfreeze the last n layers
    for layer in base_model.layers[-num_layers:]:
        layer.trainable = True
    
    # Recompile with lower learning rate
    model.compile(
        optimizer=Adam(learning_rate=learning_rate),
        loss='categorical_crossentropy',
        metrics=['accuracy']
    )
    
    return model