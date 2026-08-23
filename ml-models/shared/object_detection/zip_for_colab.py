"""
Zip the prepared YOLO dataset + training script for upload to Google Colab.

Run prepare_dataset.py first - this only packages what it produces
(data/yolo/), not the raw annotated photos, since those are already small
once resized and boxed by prepare_dataset.py (a few MB total).

Usage:
    python prepare_dataset.py
    python zip_for_colab.py
"""
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).parent
YOLO_DIR = BASE_DIR / 'data' / 'yolo'
STAGING_DIR = BASE_DIR / '_object_detection_colab_staging'
ZIP_BASE = BASE_DIR.parent / 'object_detection_colab'


def main():
    if not YOLO_DIR.exists():
        raise FileNotFoundError(f'{YOLO_DIR} not found - run prepare_dataset.py first')

    if STAGING_DIR.exists():
        shutil.rmtree(STAGING_DIR)
    shutil.copytree(YOLO_DIR, STAGING_DIR / 'data' / 'yolo')
    shutil.copy2(BASE_DIR / 'train.py', STAGING_DIR / 'train.py')

    zip_path = ZIP_BASE.with_suffix('.zip')
    if zip_path.exists():
        zip_path.unlink()

    print(f'Zipping to {zip_path} ...')
    shutil.make_archive(str(ZIP_BASE), 'zip', STAGING_DIR)
    shutil.rmtree(STAGING_DIR)

    print(f'Done: {zip_path} ({zip_path.stat().st_size / 1e6:.1f} MB)')
    print('Upload this file to your Google Drive, then open notebooks/colab_train.ipynb.')


if __name__ == '__main__':
    main()
