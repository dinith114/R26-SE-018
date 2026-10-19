"""
Prepare a component (growth_stage or bloom_prediction) for training on
Google Colab: resize data/raw images down to just above the model's input
size, then zip the resized data + src code into a single upload-ready file.

Source photos are full-resolution camera images (e.g. 4000x3000, ~5MB each),
but every training pipeline in this repo resizes to 224x224 on load anyway -
shipping full resolution to Colab wastes ~99% of the upload as bytes the
model immediately throws away. This cuts growth_stage from ~17GB to ~150MB
and bloom_prediction from ~53GB to ~220MB, small enough for Google Drive's
free tier and a fast upload.

Usage:
    python prepare_for_colab.py growth_stage
    python prepare_for_colab.py bloom_prediction
"""
import argparse
import shutil
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from PIL import Image

TARGET_SIZE = (240, 240)  # a little above the 224x224 the models actually train at
JPEG_QUALITY = 88
IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff', '.jfif'}


def _collect_files(src_dir: Path):
    """
    Yield only the files the training pipelines actually read: files sitting
    directly in `src_dir` (e.g. bloom_prediction's .xlsx logs), and files one
    level down inside each immediate subdirectory (class folders for
    growth_stage, dated folders for bloom_prediction). Anything nested deeper
    is ignored - neither pipeline's data loader ever looks there, and in
    practice these turned out to be stray manually-created folders (e.g.
    "New folder", "original") left over in a couple of bloom_prediction's
    dated folders, not part of the dataset.
    """
    skipped_dirs = []
    for entry in sorted(src_dir.iterdir()):
        if entry.is_file():
            yield entry
        elif entry.is_dir():
            for sub_entry in sorted(entry.iterdir()):
                if sub_entry.is_file():
                    yield sub_entry
                elif sub_entry.is_dir():
                    skipped_dirs.append(sub_entry)

    if skipped_dirs:
        print(f'  Skipping {len(skipped_dirs)} unexpected nested folder(s) not used by training:')
        for d in skipped_dirs:
            print(f'    - {d}')


def _process_one(job):
    src_path, dst_path = job
    try:
        if src_path.suffix.lower() in IMAGE_EXTENSIONS:
            with Image.open(src_path) as img:
                # Let libjpeg decode at 1/2-1/8 scale directly - far faster than
                # decoding 4000x3000 and then throwing almost all of it away.
                img.draft('RGB', (TARGET_SIZE[0] * 2, TARGET_SIZE[1] * 2))
                img.convert('RGB').resize(TARGET_SIZE).save(
                    dst_path.with_suffix('.jpg'), format='JPEG', quality=JPEG_QUALITY)
        else:
            shutil.copy2(src_path, dst_path)
    except (OSError, FileNotFoundError) as e:
        return src_path, e
    return src_path, None


def resize_tree(src_dir: Path, dst_dir: Path) -> int:
    dst_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    errors = []

    jobs = []
    for src_path in _collect_files(src_dir):
        dst_path = dst_dir / src_path.relative_to(src_dir)
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        jobs.append((src_path, dst_path))

    # Full-res decoding is CPU-bound (~4 images/s on one core), so a 60k-photo
    # dataset took hours serially; fan it out across every core.
    with ProcessPoolExecutor() as pool:
        for src_path, err in pool.map(_process_one, jobs, chunksize=64):
            if err is not None:
                errors.append((src_path, err))
                continue
            count += 1
            if count % 2000 == 0:
                print(f'  ...{count} files processed', flush=True)

    if errors:
        print(f'  Skipped {len(errors)} file(s) that could not be read:')
        for path, e in errors:
            print(f'    - {path}: {e}')

    return count


def main():
    parser = argparse.ArgumentParser(description='Prepare a component for Colab training (resize + zip)')
    parser.add_argument('component', choices=['growth_stage', 'bloom_prediction'])
    args = parser.parse_args()

    base_dir = Path(__file__).parent / args.component
    staging_dir = Path(__file__).parent / f'_{args.component}_colab_staging'
    if staging_dir.exists():
        shutil.rmtree(staging_dir)

    print(f'Resizing images in {base_dir / "data" / "raw"} ...')
    count = resize_tree(base_dir / 'data' / 'raw', staging_dir / 'data' / 'raw')
    print(f'Resized {count} files')

    print('Copying source code...')
    shutil.copytree(base_dir / 'src', staging_dir / 'src')

    zip_base = Path(__file__).parent / f'{args.component}_colab'
    zip_path = zip_base.with_suffix('.zip')
    if zip_path.exists():
        zip_path.unlink()

    print(f'Zipping to {zip_path} ...')
    shutil.make_archive(str(zip_base), 'zip', staging_dir)

    shutil.rmtree(staging_dir)
    print(f'Done: {zip_path} ({zip_path.stat().st_size / 1e6:.1f} MB)')
    print('Upload this file to your Google Drive, then open the matching Colab notebook.')


if __name__ == '__main__':
    main()
