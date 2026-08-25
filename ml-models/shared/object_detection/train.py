"""
Fine-tune a YOLOv8 detector on data/yolo (see prepare_dataset.py) for the
orchid_plant / flower_bunch / seed_pod classes.

Only ~36 training images exist, so this is a light fine-tune of a pretrained
YOLOv8n, not training from scratch: the backbone is frozen and augmentation
is pushed higher than the ultralytics defaults to get some mileage out of so
few images. Expect this to help on photos from the same greenhouse/setup
more than it generalizes broadly - collecting more annotated photos is the
real fix if accuracy isn't good enough.

Usage:
    python train.py --epochs 100
"""
import argparse
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).parent
DATA_YAML = BASE_DIR / 'data' / 'yolo' / 'data.yaml'
MODELS_DIR = BASE_DIR / 'models'


def main():
    parser = argparse.ArgumentParser(description='Fine-tune YOLOv8 for orchid object detection')
    parser.add_argument('--epochs', type=int, default=100)
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--batch', type=int, default=8)
    parser.add_argument('--freeze', type=int, default=10, help='Number of leading backbone layers to freeze')
    parser.add_argument('--base_model', default='yolov8n.pt', help='Pretrained weights to fine-tune from')
    args = parser.parse_args()

    if not DATA_YAML.exists():
        raise FileNotFoundError(f'{DATA_YAML} not found - run prepare_dataset.py first')

    from ultralytics import YOLO

    model = YOLO(args.base_model)
    results = model.train(
        data=str(DATA_YAML),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        freeze=args.freeze,
        patience=30,
        project=str(BASE_DIR / 'runs'),
        name='train',
        exist_ok=True,
        # Small dataset -> lean harder on augmentation than the YOLO defaults
        degrees=15.0,
        translate=0.15,
        scale=0.6,
        shear=5.0,
        fliplr=0.5,
        flipud=0.1,
        mosaic=1.0,
        mixup=0.1,
        hsv_h=0.02,
        hsv_s=0.6,
        hsv_v=0.5,
    )

    best_weights = Path(results.save_dir) / 'weights' / 'best.pt'
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    dest = MODELS_DIR / 'best.pt'
    shutil.copy2(best_weights, dest)
    print(f'\nBest weights copied to {dest}')
    print('The detector will now use the custom model automatically for orchid_plant/flower_bunch/seed_pod.')


if __name__ == '__main__':
    main()
