@echo off
echo =====================================
echo Vanda Orchid Bloom Date Prediction Training
echo =====================================
echo Data directory: ./data/raw
echo Output directory: ./models
echo Epochs: 50
echo Batch size: 16
echo Model type: efficientnet
echo =====================================

python src\train.py --data_dir ./data/raw --output_dir ./models --epochs 5 --batch_size 16 --model_type efficientnet --fine_tune_epochs 3

echo.
echo =====================================
echo Training completed!
echo =====================================
pause
