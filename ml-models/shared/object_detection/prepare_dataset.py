"""
Turn data/{flowers,seeds,plants} into a YOLO-format detection dataset.

The flowers/ and seeds/ photos were annotated by hand by drawing a solid red
rectangle directly into the image (no separate label file), so this script:
  1. finds that red rectangle's pixel bounds -> becomes the box label
  2. inpaints over the rectangle's stroke so the trained model learns the
     actual flower/seed-pod appearance instead of "there's a red line here"
  3. resizes the (now clean) image down and writes a YOLO .txt label next to
     it under data/yolo/

plants/ photos have no drawn box - the whole frame is the plant, so those
just get a full-frame box with a small inset margin.

Usage:
    python prepare_dataset.py
"""
import random
import shutil
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
from PIL import Image

DATA_DIR = Path(__file__).parent / 'data'
OUT_DIR = DATA_DIR / 'yolo'

# Class id order must match CUSTOM_CLASSES in config.py
CLASS_NAMES = ['orchid_plant', 'flower_bunch', 'seed_pod']

# (source subfolder, class name, whether a red box is drawn in these photos)
SOURCES = [
    ('plants', 'orchid_plant', False),
    ('flowers', 'flower_bunch', True),
    ('seeds', 'seed_pod', True),
]

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png'}
MAX_SIDE = 960          # resize cap; detection needs more detail than the 224px classifiers
VAL_FRACTION = 0.2
RANDOM_SEED = 42
PLANT_MARGIN_RATIO = 0.02  # inset for the full-frame "plant" box, in case a photo has a thin border


def find_red_box(img_bgr: np.ndarray) -> Optional[Tuple[int, int, int, int, np.ndarray]]:
    """
    Return the pixel bounds (xmin, ymin, xmax, ymax) plus a mask of just the
    hand-drawn red rectangle's stroke in `img_bgr`, or None if no rectangle
    was found. Red wraps around hue 0 in HSV, so two ranges are ORed together.

    Thresholds are tuned for a near-pure, saturated red pen stroke (not the
    muted reddish-brown of rust/soil/petals also present in these photos):
    a loose color range alone picks those up too and returns a bogus box, so
    candidates are additionally required to look like a thin outline (low
    filled-pixel-to-bounding-box ratio) rather than a solid colored region -
    that's what actually distinguishes a drawn rectangle from a red flower.
    """
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    lower1, upper1 = np.array([0, 180, 130]), np.array([8, 255, 255])
    lower2, upper2 = np.array([172, 180, 130]), np.array([180, 255, 255])
    mask = cv2.inRange(hsv, lower1, upper1) | cv2.inRange(hsv, lower2, upper2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))

    h, w = img_bgr.shape[:2]
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)

    best = None
    for i in range(1, n_labels):  # label 0 is the background
        x, y, bw, bh, area = stats[i]
        bbox_area = bw * bh
        if bbox_area == 0:
            continue
        fill_ratio = area / bbox_area
        area_ratio = bbox_area / (w * h)
        if not (0.005 <= area_ratio <= 0.9):
            continue
        if fill_ratio > 0.45 or area < 150:  # a filled blob (flower/pot), not an outline
            continue
        if best is None or bbox_area > best[0]:
            best = (bbox_area, x, y, x + bw, y + bh, (labels == i).astype(np.uint8) * 255)

    if best is None:
        return None
    _, xmin, ymin, xmax, ymax, component_mask = best
    return xmin, ymin, xmax, ymax, component_mask


def inpaint_box_stroke(img_bgr: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Remove the drawn rectangle's stroke so it isn't a shortcut cue for the model."""
    dilated = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=1)
    return cv2.inpaint(img_bgr, dilated, 3, cv2.INPAINT_TELEA)


def to_yolo_line(class_id: int, xmin: int, ymin: int, xmax: int, ymax: int, w: int, h: int) -> str:
    cx = (xmin + xmax) / 2 / w
    cy = (ymin + ymax) / 2 / h
    bw = (xmax - xmin) / w
    bh = (ymax - ymin) / h
    return f'{class_id} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}'


def process_image(src_path: Path, class_name: str, has_drawn_box: bool, out_img_path: Path, out_label_path: Path) -> bool:
    """Returns True if the box came from auto-detection, False if it fell back to full-frame."""
    img_bgr = cv2.imread(str(src_path))
    if img_bgr is None:
        raise ValueError(f'Could not read {src_path}')
    h, w = img_bgr.shape[:2]

    used_detection = False
    if has_drawn_box:
        found = find_red_box(img_bgr)
        if found is not None:
            xmin, ymin, xmax, ymax, mask = found
            img_bgr = inpaint_box_stroke(img_bgr, mask)
            used_detection = True
        else:
            xmin, ymin, xmax, ymax = 0, 0, w, h
    else:
        mx, my = int(w * PLANT_MARGIN_RATIO), int(h * PLANT_MARGIN_RATIO)
        xmin, ymin, xmax, ymax = mx, my, w - mx, h - my

    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    pil_img = Image.fromarray(img_rgb)
    scale = min(1.0, MAX_SIDE / max(w, h))
    if scale < 1.0:
        pil_img = pil_img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
    pil_img.save(out_img_path, format='JPEG', quality=90)

    class_id = CLASS_NAMES.index(class_name)
    out_label_path.write_text(to_yolo_line(class_id, xmin, ymin, xmax, ymax, w, h) + '\n')
    return used_detection


def main():
    random.seed(RANDOM_SEED)
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    for split in ('train', 'val'):
        (OUT_DIR / 'images' / split).mkdir(parents=True, exist_ok=True)
        (OUT_DIR / 'labels' / split).mkdir(parents=True, exist_ok=True)

    fallback_files = []
    counts = {name: {'train': 0, 'val': 0} for name in CLASS_NAMES}

    for folder, class_name, has_drawn_box in SOURCES:
        src_dir = DATA_DIR / folder
        files = sorted(p for p in src_dir.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS)
        random.shuffle(files)
        n_val = max(1, round(len(files) * VAL_FRACTION))
        split_for = {p: ('val' if i < n_val else 'train') for i, p in enumerate(files)}

        for src_path, split in split_for.items():
            stem = f'{folder}_{src_path.stem}'
            out_img_path = OUT_DIR / 'images' / split / f'{stem}.jpg'
            out_label_path = OUT_DIR / 'labels' / split / f'{stem}.txt'
            used_detection = process_image(src_path, class_name, has_drawn_box, out_img_path, out_label_path)
            counts[class_name][split] += 1
            if has_drawn_box and not used_detection:
                fallback_files.append(src_path)

    yaml_path = OUT_DIR / 'data.yaml'
    yaml_path.write_text(
        'path: ' + str(OUT_DIR.resolve()).replace('\\', '/') + '\n'
        'train: images/train\n'
        'val: images/val\n'
        f'nc: {len(CLASS_NAMES)}\n'
        f'names: {CLASS_NAMES}\n'
    )

    print('Dataset written to', OUT_DIR)
    for name, c in counts.items():
        print(f'  {name}: {c["train"]} train, {c["val"]} val')
    if fallback_files:
        print(f'\n{len(fallback_files)} image(s) had no red box detected - used full-frame box instead.')
        print('Review these (the annotation may need to be re-drawn in a more saturated red):')
        for f in fallback_files:
            print(f'  - {f}')
    print(f'\nWrote {yaml_path}')


if __name__ == '__main__':
    main()
