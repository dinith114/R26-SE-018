"""
Training script for growth stage classification model.
"""
import os
import sys
import argparse
import json
import time
from pathlib import Path
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.metrics import classification_report, confusion_matrix
import seaborn as sns
import tensorflow as tf

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from src.config import MODEL_CONFIG, STAGE_LABELS, OUTPUT_DIR, MODELS_DIR
from src.model import create_cnn_model, get_callbacks, get_model_summary, fine_tune_model
from src.preprocess import DataPreprocessor
from src.utils import save_model_artifacts, get_stage_info


def train_model(data_dir: Path, 
                output_dir: Path, 
                epochs: int = 50,
                batch_size: int = 32,
                model_type: str = 'efficientnet',
                fine_tune_epochs: int = 20) -> tuple:
    """
    Train the growth stage classification model.
    """
    print("=" * 70)
    print("Vanda Orchid Growth Stage Classification - Training")
    print("=" * 70)
    
    # Create output directory
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize data preprocessor
    preprocessor = DataPreprocessor(
        data_dir=data_dir,
        target_size=MODEL_CONFIG['target_size'],
        batch_size=batch_size
    )
    
    # Get dataset stats
    stats = preprocessor.get_dataset_stats()
    print("\nDataset Statistics:")
    print(f"Total images: {stats['total_images']}")
    print("Images per class:")
    for stage, count in stats['images_per_class'].items():
        print(f"  {stage}: {count}")
    
    # Load data using generators
    print("\nLoading data...")
    train_generator, validation_generator = preprocessor.load_data()
    
    print(f"\nTraining samples: {train_generator.samples}")
    print(f"Validation samples: {validation_generator.samples}")
    print(f"Classes: {train_generator.class_indices}")
    
    # Calculate class weights for imbalance
    class_weights = preprocessor.get_class_weights(train_generator)
    print(f"\nClass weights: {class_weights}")
    
    # Create model
    print(f"\nCreating model (type: {model_type})...")
    model = create_cnn_model(
        input_shape=MODEL_CONFIG['input_shape'],
        num_classes=len(STAGE_LABELS),
        model_type=model_type
    )
    
    print(get_model_summary(model))
    
    # Training parameters
    model_save_path = output_dir / 'vanda_growth_model.h5'
    callbacks = get_callbacks(str(model_save_path), patience=MODEL_CONFIG['patience'])
    
    # Phase 1: Train with frozen base
    print("\nPhase 1: Training with frozen base model...")
    start_time = time.time()
    
    history = model.fit(
        train_generator,
        validation_data=validation_generator,
        epochs=epochs,
        callbacks=callbacks,
        class_weight=class_weights,
        verbose=1
    )
    
    training_time = time.time() - start_time
    print(f"\nPhase 1 completed in {training_time:.2f} seconds")
    
    # Phase 2: Fine-tuning (if specified)
    if fine_tune_epochs > 0:
        print("\nPhase 2: Fine-tuning the model...")
        
        # Unfreeze the base model layers
        base_model = model.layers[1]  # The base model is the second layer
        base_model.trainable = True
        
        # Freeze all layers initially
        for layer in base_model.layers:
            layer.trainable = False
        
        # Unfreeze the last 30 layers
        for layer in base_model.layers[-30:]:
            layer.trainable = True
        
        # Recompile with lower learning rate
        model.compile(
            optimizer=tf.keras.optimizers.Adam(learning_rate=MODEL_CONFIG['learning_rate'] / 10),
            loss='categorical_crossentropy',
            metrics=['accuracy']
        )
        
        # Continue training
        fine_tune_callbacks = get_callbacks(
            str(model_save_path), 
            patience=MODEL_CONFIG['patience'] // 2
        )
        
        fine_tune_history = model.fit(
            train_generator,
            validation_data=validation_generator,
            epochs=fine_tune_epochs,
            callbacks=fine_tune_callbacks,
            class_weight=class_weights,
            verbose=1
        )
        
        # Combine histories
        for key in history.history:
            if key in fine_tune_history.history:
                history.history[key] = history.history[key] + fine_tune_history.history[key]
    
    print(f"\nTotal training time: {time.time() - start_time:.2f} seconds")
    
    # Save model artifacts
    print("\nSaving model artifacts...")
    config = {
        'model_type': model_type,
        'input_shape': MODEL_CONFIG['input_shape'],
        'num_classes': len(STAGE_LABELS),
        'class_names': STAGE_LABELS,
        'training_time': training_time,
        'epochs': len(history.history['loss']),
        'batch_size': batch_size
    }
    
    save_model_artifacts(
        model,
        preprocessor.label_encoder,
        config,
        output_dir
    )
    
    # Plot training history
    plot_training_history(history, output_dir)
    
    # Evaluate on validation set
    print("\nEvaluating model...")
    eval_results = model.evaluate(validation_generator, verbose=0)
    metrics_names = model.metrics_names
    
    print("\nValidation Results:")
    for name, value in zip(metrics_names, eval_results):
        print(f"  {name}: {value:.4f}")
    
    # Generate detailed evaluation
    evaluate_model(model, validation_generator, output_dir)
    
    return model, history, train_generator, validation_generator


def evaluate_model(model, validation_generator, output_dir: Path):
    """
    Generate detailed evaluation metrics.
    """
    # Get predictions
    y_true = validation_generator.classes
    y_pred_probs = model.predict(validation_generator, verbose=0)
    y_pred = np.argmax(y_pred_probs, axis=1)
    
    # Get unique classes present in validation
    unique_classes = np.unique(y_true)
    class_names = [STAGE_LABELS[i] for i in unique_classes]
    
    # Classification report with only classes present
    report = classification_report(y_true, y_pred, target_names=class_names)
    print("\nClassification Report:")
    print(report)
    
    # Save report
    with open(output_dir / 'classification_report.txt', 'w') as f:
        f.write(report)
    
    # Confusion matrix
    cm = confusion_matrix(y_true, y_pred)
    plot_confusion_matrix(cm, class_names, output_dir)
    
    return y_true, y_pred


def plot_training_history(history, output_dir: Path):
    """
    Plot training history.
    """
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    
    # Loss plot
    axes[0].plot(history.history['loss'], label='Training Loss')
    axes[0].plot(history.history['val_loss'], label='Validation Loss')
    axes[0].set_title('Model Loss')
    axes[0].set_xlabel('Epoch')
    axes[0].set_ylabel('Loss')
    axes[0].legend()
    axes[0].grid(True)
    
    # Accuracy plot
    axes[1].plot(history.history['accuracy'], label='Training Accuracy')
    axes[1].plot(history.history['val_accuracy'], label='Validation Accuracy')
    axes[1].set_title('Model Accuracy')
    axes[1].set_xlabel('Epoch')
    axes[1].set_ylabel('Accuracy')
    axes[1].legend()
    axes[1].grid(True)
    
    plt.tight_layout()
    plt.savefig(output_dir / 'training_history.png', dpi=300)
    plt.close()


def plot_confusion_matrix(cm, class_names, output_dir: Path):
    """
    Plot confusion matrix.
    """
    # Normalize confusion matrix
    cm_normalized = cm.astype('float') / cm.sum(axis=1)[:, np.newaxis]
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(18, 7))
    
    # Raw counts
    sns.heatmap(cm, annot=True, fmt='d', cmap='Blues',
                xticklabels=class_names, yticklabels=class_names, ax=ax1)
    ax1.set_title('Confusion Matrix (Counts)')
    ax1.set_xlabel('Predicted')
    ax1.set_ylabel('Actual')
    
    # Normalized
    sns.heatmap(cm_normalized, annot=True, fmt='.2f', cmap='Blues',
                xticklabels=class_names, yticklabels=class_names, ax=ax2)
    ax2.set_title('Confusion Matrix (Normalized)')
    ax2.set_xlabel('Predicted')
    ax2.set_ylabel('Actual')
    
    plt.tight_layout()
    plt.savefig(output_dir / 'confusion_matrix.png', dpi=300)
    plt.close()


def main():
    parser = argparse.ArgumentParser(description='Train growth stage classification model')
    parser.add_argument('--data_dir', type=str, required=True,
                        help='Path to the data directory')
    parser.add_argument('--output_dir', type=str, default=str(MODELS_DIR),
                        help='Path to save the model')
    parser.add_argument('--epochs', type=int, default=50,
                        help='Number of training epochs')
    parser.add_argument('--batch_size', type=int, default=32,
                        help='Batch size for training')
    parser.add_argument('--model_type', type=str, default='efficientnet',
                        choices=['efficientnet', 'mobilenet', 'resnet'],
                        help='Type of base model to use')
    parser.add_argument('--fine_tune_epochs', type=int, default=20,
                        help='Number of fine-tuning epochs')
    
    args = parser.parse_args()
    
    # Train model
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