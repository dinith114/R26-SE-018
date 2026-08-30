"""
Hybrid Pollination - Pretrained CNN Feature Extraction (Transfer Learning)

Uses a ResNet18 pretrained on ImageNet as a frozen feature extractor, then
trains a small classifier on top.

WHY TRANSFER LEARNING AND NOT A CNN TRAINED FROM SCRATCH
---------------------------------------------------------
The dataset has 357 images but only 28 distinct plants. Training a network from
scratch on 28 effective examples would memorise them, exactly the failure that
produced the original 100% accuracy. Freezing a network trained on 1.2 million
ImageNet images and fitting only a linear classifier on its output keeps the
number of learned parameters small enough for the data to support.

The hand-crafted features in trait_features.py reached:

    leaf_condition   0.538 accuracy   (baseline 0.501)
    plant_strength   0.482 accuracy   (baseline 0.546)  <- below baseline

Colour and contour statistics apparently do not capture what a breeder means by
"weak". Learned visual features may; this module tests that rather than assuming.

The plant mask is applied before the image reaches the network, so the network
sees the plant on a neutral field instead of the nursery behind it.

Everything still runs on CPU. ResNet18 over ~360 images takes a few minutes.
"""

import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from segmentation import segment_plant


# ImageNet normalisation - required, the pretrained weights expect it
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

INPUT_SIZE = 224

_model = None
_torch = None


def _load_model():
    """Load ResNet18 once, with the classification head removed."""
    global _model, _torch
    if _model is not None:
        return _model, _torch

    import torch
    import torchvision

    torch.set_num_threads(max(1, (os.cpu_count() or 2) // 2))

    try:
        weights = torchvision.models.ResNet18_Weights.IMAGENET1K_V1
        net = torchvision.models.resnet18(weights=weights)
    except Exception as e:
        raise RuntimeError(
            "Could not load pretrained ResNet18 weights. The first run needs "
            f"internet access to download them (~45 MB). Original error: {e}"
        )

    # Drop the 1000-class head; keep the 512-d pooled embedding
    net.fc = torch.nn.Identity()
    net.eval()

    _model, _torch = net, torch
    return _model, _torch


def preprocess(image_path: str = None, img: np.ndarray = None,
               use_mask: bool = True) -> np.ndarray:
    """
    Prepare one image for the network.

    With use_mask=True the background is replaced by a neutral grey rather than
    black. Black would create a hard high-contrast edge around the plant, which
    the network reads as a strong feature in its own right; flat grey is closer
    to "nothing here".
    """
    seg = segment_plant(image_path=image_path, img=img)
    image, mask = seg["image"], seg["plant_mask"]

    if use_mask and cv2.countNonZero(mask) > 200:
        neutral = np.full_like(image, 128)
        image = np.where(mask[:, :, None] > 0, image, neutral)

    image = cv2.resize(image, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_AREA)
    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    rgb = (rgb - IMAGENET_MEAN) / IMAGENET_STD

    return np.transpose(rgb, (2, 0, 1))    # HWC -> CHW


def extract_cnn_features(image_paths: list, use_mask: bool = True,
                         batch_size: int = 16, verbose: bool = True) -> np.ndarray:
    """
    Embed a list of images.

    Returns:
        (n_images, 512) float32 array. Rows for unreadable images are zeros.
    """
    net, torch = _load_model()

    out = np.zeros((len(image_paths), 512), dtype=np.float32)

    for start in range(0, len(image_paths), batch_size):
        chunk = image_paths[start:start + batch_size]
        if verbose and start % (batch_size * 4) == 0:
            print(f"  embedding {start}/{len(image_paths)}")

        tensors, rows = [], []
        for i, path in enumerate(chunk):
            try:
                tensors.append(preprocess(path, use_mask=use_mask))
                rows.append(start + i)
            except Exception as e:
                if verbose:
                    print(f"    [WARN] {os.path.basename(str(path))}: {e}")

        if not tensors:
            continue

        batch = torch.from_numpy(np.stack(tensors))
        with torch.no_grad():
            embeddings = net(batch).numpy()

        for row, emb in zip(rows, embeddings):
            out[row] = emb

    if verbose:
        print(f"  embedded {len(image_paths)} images -> {out.shape}")

    return out


if __name__ == "__main__":
    import pandas as pd

    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    df = pd.read_csv(os.path.join(BASE, "data", "image_annotations_clean.csv"))

    print("Testing CNN embedding on 4 images...")
    feats = extract_cnn_features(df["image_path"].head(4).tolist())
    print(f"  shape {feats.shape}")
    print(f"  first row, first 8 values: {feats[0][:8]}")
    print(f"  non-zero rows: {(feats.any(axis=1)).sum()}/4")
