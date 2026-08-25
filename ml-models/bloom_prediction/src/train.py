"""
Training script for bloom date prediction model.
"""
import sys
import argparse
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from src.config import MODEL_CONFIG, TABULAR_FEATURES, OUTPUT_DIR, MODELS_DIR
from src.model import create_bloom_model, get_callbacks, get_model_summary
from src.preprocess import DataPreprocessor
from src.utils import save_model_artifacts


def find_base_model(model: tf.keras.Model) -> tf.keras.Model:
    """Locate the nested transfer-learning base model inside the full model."""
    for layer in model.layers:
        if isinstance(layer, tf.keras.Model):
            return layer
    raise ValueError("Could not find a nested base model to fine-tune")


def train_model(data_dir: Path,
                output_dir: Path,
                epochs: int = 50,
                batch_size: int = 16,
                model_type: str = 'efficientnet',
                fine_tune_epochs: int = 20) -> tuple:
    """
    Train the bloom date prediction model.
    """
    print("=" * 70)
    print("Vanda Orchid Bloom Date Prediction - Training")
    print("=" * 70)

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    preprocessor = DataPreprocessor(
        data_dir=data_dir,
        target_size=MODEL_CONFIG['target_size'],
        batch_size=batch_size
    )

    stats = preprocessor.get_dataset_stats()
    print("\nDataset Statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")

    print("\nLoading data...")
    train_generator, validation_generator = preprocessor.load_data()

    print(f"\nTraining samples: {len(train_generator.df)}")
    print(f"Validation samples: {len(validation_generator.df)}")

    print(f"\nCreating model (type: {model_type})...")
    model = create_bloom_model(
        input_shape=MODEL_CONFIG['input_shape'],
        num_tabular_features=len(TABULAR_FEATURES),
        model_type=model_type
    )

    print(get_model_summary(model))

    model_save_path = output_dir / 'vanda_bloom_model.h5'
    callbacks = get_callbacks(str(model_save_path), patience=MODEL_CONFIG['patience'])

    print("\nPhase 1: Training with frozen base model...")
    start_time = time.time()

    history = model.fit(
        train_generator,
        validation_data=validation_generator,
        epochs=epochs,
        callbacks=callbacks,
        verbose=1
    )

    training_time = time.time() - start_time
    print(f"\nPhase 1 completed in {training_time:.2f} seconds")

    if fine_tune_epochs > 0:
        print("\nPhase 2: Fine-tuning the model...")

        base_model = find_base_model(model)
        base_model.trainable = True
        for layer in base_model.layers:
            layer.trainable = False
        for layer in base_model.layers[-30:]:
            layer.trainable = True

        model.compile(
            optimizer=tf.keras.optimizers.Adam(learning_rate=MODEL_CONFIG['learning_rate'] / 10),
            loss='mse',
            metrics=['mae']
        )

        fine_tune_callbacks = get_callbacks(
            str(model_save_path),
            patience=MODEL_CONFIG['patience'] // 2
        )

        fine_tune_history = model.fit(
            train_generator,
            validation_data=validation_generator,
            epochs=fine_tune_epochs,
            callbacks=fine_tune_callbacks,
            verbose=1
        )

        for key in history.history:
            if key in fine_tune_history.history:
                history.history[key] = history.history[key] + fine_tune_history.history[key]

    print(f"\nTotal training time: {time.time() - start_time:.2f} seconds")

    print("\nSaving model artifacts...")
    config = {
        'model_type': model_type,
        'input_shape': MODEL_CONFIG['input_shape'],
        'tabular_features': TABULAR_FEATURES,
        'training_time': training_time,
        'epochs': len(history.history['loss']),
        'batch_size': batch_size
    }

    save_model_artifacts(model, preprocessor.scaler, config, output_dir)

    plot_training_history(history, output_dir)

    print("\nEvaluating model...")
    evaluate_model(model, validation_generator, output_dir)

    return model, history, train_generator, validation_generator


def evaluate_model(model, validation_generator, output_dir: Path):
    """
    Generate detailed evaluation metrics: MAE, RMSE, R^2, and a
    predicted-vs-actual scatter plot.
    """
    y_true = []
    y_pred = []
    for i in range(len(validation_generator)):
        (images, tabular), targets = validation_generator[i]
        preds = model.predict((images, tabular), verbose=0).flatten()
        y_true.extend(targets.tolist())
        y_pred.extend(preds.tolist())

    y_true = np.array(y_true)
    y_pred = np.array(y_pred)

    mae = mean_absolute_error(y_true, y_pred)
    rmse = np.sqrt(mean_squared_error(y_true, y_pred))
    r2 = r2_score(y_true, y_pred)

    report = (
        f"Mean Absolute Error: {mae:.2f} days\n"
        f"Root Mean Squared Error: {rmse:.2f} days\n"
        f"R^2 Score: {r2:.4f}\n"
    )
    print("\nEvaluation Results:")
    print(report)

    with open(output_dir / 'evaluation_report.txt', 'w') as f:
        f.write(report)

    plot_predictions(y_true, y_pred, output_dir)

    return y_true, y_pred


def plot_training_history(history, output_dir: Path):
    """
    Plot training history.
    """
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    axes[0].plot(history.history['loss'], label='Training Loss')
    axes[0].plot(history.history['val_loss'], label='Validation Loss')
    axes[0].set_title('Model Loss (MSE)')
    axes[0].set_xlabel('Epoch')
    axes[0].set_ylabel('Loss')
    axes[0].legend()
    axes[0].grid(True)

    axes[1].plot(history.history['mae'], label='Training MAE')
    axes[1].plot(history.history['val_mae'], label='Validation MAE')
    axes[1].set_title('Model MAE (days)')
    axes[1].set_xlabel('Epoch')
    axes[1].set_ylabel('MAE')
    axes[1].legend()
    axes[1].grid(True)

    plt.tight_layout()
    plt.savefig(output_dir / 'training_history.png', dpi=300)
    plt.close()


def plot_predictions(y_true, y_pred, output_dir: Path):
    """
    Plot predicted vs. actual days until bloom.
    """
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.scatter(y_true, y_pred, alpha=0.4, s=15)

    limit = max(y_true.max(), y_pred.max()) + 1
    ax.plot([0, limit], [0, limit], 'r--', label='Perfect prediction')

    ax.set_xlabel('Actual days until bloom')
    ax.set_ylabel('Predicted days until bloom')
    ax.set_title('Predicted vs. Actual')
    ax.legend()
    ax.grid(True)

    plt.tight_layout()
    plt.savefig(output_dir / 'prediction_scatter.png', dpi=300)
    plt.close()


def main():
    parser = argparse.ArgumentParser(description='Train bloom date prediction model')
    parser.add_argument('--data_dir', type=str, required=True,
                        help='Path to the data directory')
    parser.add_argument('--output_dir', type=str, default=str(MODELS_DIR),
                        help='Path to save the model')
    parser.add_argument('--epochs', type=int, default=50,
                        help='Number of training epochs')
    parser.add_argument('--batch_size', type=int, default=16,
                        help='Batch size for training')
    parser.add_argument('--model_type', type=str, default='efficientnet',
                        choices=['efficientnet', 'mobilenet', 'resnet'],
                        help='Type of base model to use')
    parser.add_argument('--fine_tune_epochs', type=int, default=20,
                        help='Number of fine-tuning epochs')

    args = parser.parse_args()

    model, history, train_generator, val_generator = train_model(
        data_dir=Path(args.data_dir),
        output_dir=Path(args.output_dir),
        epochs=args.epochs,
        batch_size=args.batch_size,
        model_type=args.model_type,
        fine_tune_epochs=args.fine_tune_epochs
    )

    print("\n" + "=" * 70)
    print("Training completed successfully!")
    print(f"Model saved to: {args.output_dir}")
    print("=" * 70)


if __name__ == "__main__":
    main()
