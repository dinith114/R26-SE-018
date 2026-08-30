#!/bin/bash

# Training script for the orchid object detector (YOLOv8 fine-tune)

echo "====================================="
echo "Orchid Object Detector Training (YOLOv8)"
echo "====================================="
echo "Data: ./data/yolo/data.yaml"
echo "Output: ./models/best.pt"
echo "Epochs: 100"
echo "====================================="

python prepare_dataset.py
python train.py --epochs 100 --imgsz 640 --batch 8

echo "Training completed!"
