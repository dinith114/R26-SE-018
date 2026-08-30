#!/bin/bash

# Training script for growth stage classification

# Set environment
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# Training parameters
DATA_DIR="./data/raw"
OUTPUT_DIR="./models"
EPOCHS=50
BATCH_SIZE=32
MODEL_TYPE="efficientnet"
FINE_TUNE_EPOCHS=20

echo "====================================="
echo "Vanda Orchid Growth Stage Training"
echo "====================================="
echo "Data directory: $DATA_DIR"
echo "Output directory: $OUTPUT_DIR"
echo "Epochs: $EPOCHS"
echo "Batch size: $BATCH_SIZE"
echo "Model type: $MODEL_TYPE"
echo "Fine-tune epochs: $FINE_TUNE_EPOCHS"
echo "====================================="

# Run training
python src/train.py \
    --data_dir "$DATA_DIR" \
    --output_dir "$OUTPUT_DIR" \
    --epochs $EPOCHS \
    --batch_size $BATCH_SIZE \
    --model_type $MODEL_TYPE \
    --fine_tune_epochs $FINE_TUNE_EPOCHS

echo "Training completed!"