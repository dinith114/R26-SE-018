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
import tensorflow as tf
from PIL import Image
from sklearn.model_selection import GroupShuffleSplit
from sklearn.preprocessing import StandardScaler

from .config import (
    ALLOWED_EXTENSIONS, MODEL_CONFIG, ORIGINAL_IMAGE_TYPE, TABULAR_FEATURES,
    TARGET_COLUMN,
)
from .utils import preprocess_pil_image


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
        date_stem = Path(xlsx_path).stem
        df = pd.read_excel(xlsx_path, sheet_name=0)
        df['image_path'] = df['Image'].apply(lambda name: str(data_dir / date_stem / str(name)))
        df['capture_date'] = date_stem
        frames.append(df)

    dataset = pd.concat(frames, ignore_index=True)

    # Drop rows with no usable target or a missing/unreadable image file
    dataset = dataset.dropna(subset=[TARGET_COLUMN] + TABULAR_FEATURES)
    dataset = dataset[dataset['image_path'].apply(
        lambda p: Path(p).exists() and Path(p).suffix.lower() in ALLOWED_EXTENSIONS
    )]

    return dataset.reset_index(drop=True)


def split_by_plant(dataset: pd.DataFrame, validation_split: float = 0.2,
                    seed: int = 42) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Split into train/validation by Plant ID, not by row: every photo of a
    given plant (original + its augmented variants, across every date it was
    photographed) lands entirely in one split, so validation never sees a
    near-duplicate of a training image.
    """
    splitter = GroupShuffleSplit(n_splits=1, test_size=validation_split, random_state=seed)
    train_idx, val_idx = next(splitter.split(dataset, groups=dataset['Plant ID']))
    return dataset.iloc[train_idx].reset_index(drop=True), dataset.iloc[val_idx].reset_index(drop=True)


class BloomDataGenerator(tf.keras.utils.Sequence):
    """
    Keras Sequence that yields ([images, tabular_features], days_until_bloom)
    batches from a merged bloom dataset DataFrame.
    """

    def __init__(self, dataframe: pd.DataFrame, scaler: StandardScaler,
                 batch_size: int = None, target_size: Tuple[int, int] = None,
                 shuffle: bool = True, augment: bool = False):
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
            img = Image.open(image_path)
            if self.augment and np.random.random() > 0.5:
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            images[i] = preprocess_pil_image(img, self.target_size)[0]

        tabular = self.scaler.transform(batch[TABULAR_FEATURES].to_numpy(dtype='float32'))
        targets = batch[TARGET_COLUMN].to_numpy(dtype='float32')

        return (images, tabular), targets


class DataPreprocessor:
    """
    Loads the merged bloom dataset, splits it by plant, fits the tabular
    feature scaler on the training split only, and builds the train/
    validation generators.
    """

    def __init__(self, data_dir: Path, target_size: Tuple[int, int] = None,
                 batch_size: int = None, validation_split: float = None):
        self.data_dir = Path(data_dir)
        self.target_size = target_size or MODEL_CONFIG['target_size']
        self.batch_size = batch_size or MODEL_CONFIG['batch_size']
        self.validation_split = validation_split or MODEL_CONFIG['validation_split']
        self.scaler = StandardScaler()

        if not self.data_dir.exists():
            raise FileNotFoundError(f"Data directory not found: {self.data_dir}")

    def load_data(self) -> Tuple[BloomDataGenerator, BloomDataGenerator]:
        dataset = load_bloom_dataset(self.data_dir)
        train_df, val_df = split_by_plant(dataset, self.validation_split)

        self.scaler.fit(train_df[TABULAR_FEATURES].to_numpy(dtype='float32'))

        train_generator = BloomDataGenerator(
            train_df, self.scaler, batch_size=self.batch_size,
            target_size=self.target_size, shuffle=True, augment=True,
        )
        validation_generator = BloomDataGenerator(
            val_df, self.scaler, batch_size=self.batch_size,
            target_size=self.target_size, shuffle=False, augment=False,
        )

        return train_generator, validation_generator

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
