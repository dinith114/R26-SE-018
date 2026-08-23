"""
Model architecture for bloom date prediction.

Combines an image branch (transfer learning, same approach as
growth_stage/src/model.py) with a small tabular branch for the
temperature/humidity/light sensor readings, then regresses the number of
days until the plant blooms.
"""
import tensorflow as tf
from tensorflow.keras import layers, models
from tensorflow.keras.applications import EfficientNetB0, MobileNetV2, ResNet50
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint, ReduceLROnPlateau
from tensorflow.keras.optimizers import Adam
from typing import Tuple

from .config import MODEL_CONFIG


def create_base_model(model_type: str = 'efficientnet',
                      input_shape: Tuple[int, int, int] = (224, 224, 3)):
    """
    Create base image model with transfer learning.
    """
    if model_type == 'efficientnet':
        base_model = EfficientNetB0(
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


def create_bloom_model(input_shape: Tuple[int, int, int] = (224, 224, 3),
                       num_tabular_features: int = 3,
                       model_type: str = 'efficientnet') -> tf.keras.Model:
    """
    Create a two-branch model: image + tabular sensor readings -> days
    until bloom (regression).
    """
    base_model = create_base_model(model_type, input_shape)
    base_model.trainable = False

    # Image branch
    image_input = tf.keras.Input(shape=input_shape, name='image_input')

    if model_type == 'efficientnet':
        x = tf.keras.applications.efficientnet.preprocess_input(image_input)
    elif model_type == 'mobilenet':
        x = tf.keras.applications.mobilenet_v2.preprocess_input(image_input)
    elif model_type == 'resnet':
        x = tf.keras.applications.resnet50.preprocess_input(image_input)
    else:
        x = image_input / 255.0

    x = base_model(x, training=False)
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dense(256, activation='relu', kernel_regularizer='l2')(x)
    x = layers.BatchNormalization()(x)
    x = layers.Dropout(0.3)(x)
    image_embedding = layers.Dense(64, activation='relu')(x)

    # Tabular branch (temperature, humidity, light intensity)
    tabular_input = tf.keras.Input(shape=(num_tabular_features,), name='tabular_input')
    t = layers.Dense(32, activation='relu')(tabular_input)
    t = layers.Dense(16, activation='relu')(t)

    # Combine and regress
    combined = layers.Concatenate()([image_embedding, t])
    combined = layers.Dense(64, activation='relu', kernel_regularizer='l2')(combined)
    combined = layers.Dropout(0.3)(combined)
    output = layers.Dense(1, activation='linear', name='days_until_bloom')(combined)

    model = models.Model(
        inputs=[image_input, tabular_input],
        outputs=output,
        name=f'vanda_bloom_{model_type}'
    )

    model.compile(
        optimizer=Adam(learning_rate=MODEL_CONFIG['learning_rate']),
        loss='mse',
        metrics=['mae']
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
            monitor='val_mae',
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
    base_model.trainable = True

    for layer in base_model.layers:
        layer.trainable = False

    for layer in base_model.layers[-num_layers:]:
        layer.trainable = True

    model.compile(
        optimizer=Adam(learning_rate=learning_rate),
        loss='mse',
        metrics=['mae']
    )

    return model
