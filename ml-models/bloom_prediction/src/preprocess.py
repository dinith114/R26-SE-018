"""
Data loading and preprocessing for bloom date prediction.

Each dated subfolder under data/raw/ (e.g. data/raw/20260712/) has a matching
.xlsx log (data/raw/20260712.xlsx) with one row per photo: which plant it is,
sensor readings at capture time, and how many days later that plant actually
bloomed. This module merges every .xlsx into one dataset, resolves each row
to its image file, and serves batches of (image, tabular features) -> days
until bloom for training.
"""
import glob
import os
from pathlib import Path
from typing import Tuple

import numpy as np
import pandas as pd
from PIL import Image, ImageEnhance
from sklearn.model_selection import ShuffleSplit
from sklearn.preprocessing import StandardScaler

from .config import (
    ALLOWED_EXTENSIONS, MODEL_CONFIG, ORIGINAL_IMAGE_TYPE, TABULAR_FEATURES,
    TARGET_COLUMN,
)
from .utils import preprocess_pil_image

# tf is only needed by BloomDataGenerator/DataPreprocessor.load_data() below -
# kept as a deferred import so load_bloom_dataset/split_dataset/
# save_split_manifest stay usable (e.g. to inspect a split) without
# TensorFlow installed.
try:
    import tensorflow as tf
    _SequenceBase = tf.keras.utils.Sequence
except ImportError:
    tf = None
    _SequenceBase = object


def load_bloom_dataset(data_dir: Path) -> pd.DataFrame:
    """
    Merge every dated .xlsx log under `data_dir` into one DataFrame, with an
    `image_path` column resolved to the matching dated subfolder.
    """
    data_dir = Path(data_dir)
    xlsx_files = sorted(glob.glob(str(data_dir / '*.xlsx')))
    if not xlsx_files:
        raise FileNotFoundError(f"No .xlsx logs found in {data_dir}")

    frames = []
    for xlsx_path in xlsx_files:
        file_stem = Path(xlsx_path).stem
        # A day can have several logs for the same photos, each with sensor
        # readings from a different time (20260712.xlsx, 20260712_10.xlsx,
        # 20260712_12.xlsx, ...). They all share the 20260712/ image folder.
        date_stem = file_stem.split('_')[0]
        df = pd.read_excel(xlsx_path, sheet_name=0)
        df['image_path'] = df['Image'].apply(lambda name: str(data_dir / date_stem / str(name)))
        df['capture_date'] = date_stem
        df['source_log'] = file_stem
        if 'ID' not in df.columns:
            df.insert(0, 'ID', [f'{file_stem}_{i}' for i in range(len(df))])
        frames.append(df)

    dataset = pd.concat(frames, ignore_index=True)

    # Drop rows with no usable target or a missing/unreadable image file
    dataset = dataset.dropna(subset=[TARGET_COLUMN] + TABULAR_FEATURES)
    dataset = dataset[dataset['image_path'].apply(
        lambda p: Path(p).exists() and Path(p).suffix.lower() in ALLOWED_EXTENSIONS
    )]

    return dataset.reset_index(drop=True)


def split_dataset(dataset: pd.DataFrame, val_split: float = 0.15, test_split: float = 0.15,
                   seed: int = 42) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Split into train/validation/test by row, treating every image
    (original or augmented variant) as an independent sample - not grouped
    by Plant ID. Requested despite the leakage this causes: augmented
    siblings of a training image, and other photos of the same plant, can
    land in validation/test, so val/test metrics no longer estimate
    performance on genuinely unseen plants.
    """
    splitter1 = ShuffleSplit(n_splits=1, test_size=test_split, random_state=seed)
    trainval_idx, test_idx = next(splitter1.split(dataset))
    trainval_df = dataset.iloc[trainval_idx].reset_index(drop=True)
    test_df = dataset.iloc[test_idx].reset_index(drop=True)

    # val_split is a fraction of the whole dataset; re-express it as a
    # fraction of what's left after carving out test.
    relative_val = val_split / (1 - test_split)
    splitter2 = ShuffleSplit(n_splits=1, test_size=relative_val, random_state=seed)
    train_idx, val_idx = next(splitter2.split(trainval_df))
    train_df = trainval_df.iloc[train_idx].reset_index(drop=True)
    val_df = trainval_df.iloc[val_idx].reset_index(drop=True)

    return train_df, val_df, test_df


def save_split_manifest(train_df: pd.DataFrame, val_df: pd.DataFrame,
                         test_df: pd.DataFrame, output_dir: Path) -> None:
    """Write exactly which rows/images went to which split, so it's inspectable after training."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cols = ['ID', 'Plant ID', 'image_path', 'capture_date', 'source_log', TARGET_COLUMN]
    train_df[cols].to_csv(output_dir / 'train_split.csv', index=False)
    val_df[cols].to_csv(output_dir / 'val_split.csv', index=False)
    test_df[cols].to_csv(output_dir / 'test_split.csv', index=False)


class BloomDataGenerator(_SequenceBase):
    """
    Keras Sequence that yields ([images, tabular_features], days_until_bloom)
    batches from a merged bloom dataset DataFrame.
    """

    def __init__(self, dataframe: pd.DataFrame, scaler: StandardScaler,
                 batch_size: int = None, target_size: Tuple[int, int] = None,
                 shuffle: bool = True, augment: bool = False):
        if tf is None:
            raise ImportError("TensorFlow is required to build BloomDataGenerator/DataPreprocessor.load_data()")
        self.df = dataframe.reset_index(drop=True)
        self.scaler = scaler
        self.batch_size = batch_size or MODEL_CONFIG['batch_size']
        self.target_size = target_size or MODEL_CONFIG['target_size']
        self.shuffle = shuffle
        self.augment = augment
        self.indices = np.arange(len(self.df))
        self.on_epoch_end()

    def __len__(self) -> int:
        return max(1, int(np.ceil(len(self.df) / self.batch_size)))

    def on_epoch_end(self):
        if self.shuffle:
            np.random.shuffle(self.indices)

    def __getitem__(self, batch_idx: int):
        batch_indices = self.indices[batch_idx * self.batch_size:(batch_idx + 1) * self.batch_size]
        batch = self.df.iloc[batch_indices]

        images = np.zeros((len(batch), *self.target_size, 3), dtype='float32')
        for i, image_path in enumerate(batch['image_path']):
            img = Image.open(image_path).convert('RGB')
            if self.augment:
                img = self._augment_image(img)
            images[i] = preprocess_pil_image(img, self.target_size)[0]

        tabular = self.scaler.transform(batch[TABULAR_FEATURES].to_numpy(dtype='float32'))
        targets = batch[TARGET_COLUMN].to_numpy(dtype='float32')

        return (images, tabular), targets

    @staticmethod
    def _augment_image(img: Image.Image) -> Image.Image:
        """
        Random flip/rotation/brightness/contrast jitter, applied on top of
        whatever offline augmentation already produced this file. The offline
        variants (rotated/brightness-shifted copies) are a fixed, finite set
        shared identically across every epoch, so the model can still
        memorize them; this adds a fresh, continuous perturbation each epoch
        instead, matching growth_stage's richer augmentation
        (see growth_stage/src/preprocess.py's ImageDataGenerator args).
        """
        if np.random.random() > 0.5:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        if np.random.random() > 0.5:
            angle = np.random.uniform(-15, 15)
            img = img.rotate(angle, resample=Image.BILINEAR, fillcolor=(255, 255, 255))
        if np.random.random() > 0.5:
            img = ImageEnhance.Brightness(img).enhance(np.random.uniform(0.8, 1.2))
        if np.random.random() > 0.5:
            img = ImageEnhance.Contrast(img).enhance(np.random.uniform(0.8, 1.2))
        return img


class DataPreprocessor:
    """
    Loads the merged bloom dataset, splits it by plant into train/
    validation/test, fits the tabular feature scaler on the training split
    only, and builds a generator for each.
    """

    def __init__(self, data_dir: Path, target_size: Tuple[int, int] = None,
                 batch_size: int = None, val_split: float = None,
                 test_split: float = None):
        self.data_dir = Path(data_dir)
        self.target_size = target_size or MODEL_CONFIG['target_size']
        self.batch_size = batch_size or MODEL_CONFIG['batch_size']
        self.val_split = val_split if val_split is not None else MODEL_CONFIG['validation_split']
        self.test_split = test_split if test_split is not None else MODEL_CONFIG['test_split']
        self.scaler = StandardScaler()

        if not self.data_dir.exists():
            raise FileNotFoundError(f"Data directory not found: {self.data_dir}")

    def load_data(self):
        """
        Returns (train_generator, validation_generator, test_generator,
        (train_df, val_df, test_df)). The dataframes are what
        save_split_manifest() writes out - callers that don't need the
        manifest can ignore the last element.
        """
        dataset = load_bloom_dataset(self.data_dir)
        train_df, val_df, test_df = split_dataset(dataset, self.val_split, self.test_split)

        self.scaler.fit(train_df[TABULAR_FEATURES].to_numpy(dtype='float32'))

        train_generator = BloomDataGenerator(
            train_df, self.scaler, batch_size=self.batch_size,
            target_size=self.target_size, shuffle=True, augment=True,
        )
        validation_generator = BloomDataGenerator(
            val_df, self.scaler, batch_size=self.batch_size,
            target_size=self.target_size, shuffle=False, augment=False,
        )
        test_generator = BloomDataGenerator(
            test_df, self.scaler, batch_size=self.batch_size,
            target_size=self.target_size, shuffle=False, augment=False,
        )

        return train_generator, validation_generator, test_generator, (train_df, val_df, test_df)

    def get_dataset_stats(self) -> dict:
        dataset = load_bloom_dataset(self.data_dir)
        original_only = dataset[dataset['Image Type'] == ORIGINAL_IMAGE_TYPE]
        return {
            'total_rows': len(dataset),
            'original_photos': len(original_only),
            'unique_plants': dataset['Plant ID'].nunique(),
            'days_until_bloom_min': float(dataset[TARGET_COLUMN].min()),
            'days_until_bloom_max': float(dataset[TARGET_COLUMN].max()),
        }
