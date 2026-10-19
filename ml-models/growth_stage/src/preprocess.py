"""
Data loading, splitting, and augmentation for growth stage classification.

Each data/raw/<class>/ folder holds original photos plus ~10 offline-
augmented variants of each (rot30/45/60, bup/bdown, cup/cdown, sup/sdown
suffixes - see clean_dataset.py). Splitting by individual file would let
near-duplicate variants of the same original photo leak across train/
validation/test, so the split groups by original photo first (the same
principle bloom_prediction/src/preprocess.py uses for Plant ID) and only
then divides each class into three sets.
"""
import re
from pathlib import Path
from typing import Any, Dict, Tuple

import numpy as np
import pandas as pd
from PIL import Image, ImageEnhance
from sklearn.model_selection import GroupShuffleSplit
from sklearn.preprocessing import LabelEncoder

from .config import MODEL_CONFIG, STAGE_LABELS

# tf is only needed by GrowthStageDataGenerator/DataPreprocessor below - kept
# as a deferred import so list_class_images/split_dataset/save_split_manifest
# stay usable (e.g. to inspect a split) without TensorFlow installed, same as
# clean_dataset.py.
try:
    import tensorflow as tf
    _SequenceBase = tf.keras.utils.Sequence
except ImportError:
    tf = None
    _SequenceBase = object

# `+` because variants stack (a class-balancing pass adds `_bal_<op><amount>`,
# e.g. `_10_bal_bdown0.85`, `_10_bal_rot-12`), and any rotation angle counts:
# missing either lets copies of one photo land in both train and test.
VARIANT_SUFFIX = re.compile(r'(?:_bal_[a-z]+-?[0-9.]*|_bdown|_bup|_cdown|_cup|_rot-?\d+|_sdown|_sup)+$')


def _base_id(filename: str) -> str:
    """Strip the offline-augmentation suffix to recover the original photo's identity."""
    return VARIANT_SUFFIX.sub('', Path(filename).stem)


def list_class_images(data_dir: Path) -> pd.DataFrame:
    """List every image under data_dir/<class>/ with its class and original-photo group id."""
    data_dir = Path(data_dir)
    rows = []
    for stage in STAGE_LABELS:
        stage_dir = data_dir / stage
        if not stage_dir.exists():
            continue
        for f in sorted(stage_dir.iterdir()):
            if not f.is_file():
                continue
            rows.append({
                'class': stage,
                'filename': f.name,
                'image_path': str(f),
                'group_id': f"{stage}/{_base_id(f.name)}",
            })
    if not rows:
        raise FileNotFoundError(f"No images found under {data_dir}/<class>/")
    return pd.DataFrame(rows)


def split_dataset(df: pd.DataFrame, val_split: float = 0.15, test_split: float = 0.15,
                   seed: int = 42) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Group-aware, per-class train/validation/test split. Splitting each class
    independently (rather than the whole dataset at once) keeps every split
    proportionally balanced across classes instead of, say, one class landing
    disproportionately in test purely by chance of group assignment.
    """
    train_parts, val_parts, test_parts = [], [], []

    for _, class_df in df.groupby('class', sort=False):
        splitter1 = GroupShuffleSplit(n_splits=1, test_size=test_split, random_state=seed)
        trainval_idx, test_idx = next(splitter1.split(class_df, groups=class_df['group_id']))
        trainval_df = class_df.iloc[trainval_idx]
        test_parts.append(class_df.iloc[test_idx])

        # val_split is a fraction of the whole class; re-express it as a
        # fraction of what's left after carving out test.
        relative_val = val_split / (1 - test_split)
        splitter2 = GroupShuffleSplit(n_splits=1, test_size=relative_val, random_state=seed)
        train_idx, val_idx = next(splitter2.split(trainval_df, groups=trainval_df['group_id']))
        train_parts.append(trainval_df.iloc[train_idx])
        val_parts.append(trainval_df.iloc[val_idx])

    def _combine(parts):
        return pd.concat(parts, ignore_index=True).sample(frac=1, random_state=seed).reset_index(drop=True)

    return _combine(train_parts), _combine(val_parts), _combine(test_parts)


def save_split_manifest(train_df: pd.DataFrame, val_df: pd.DataFrame,
                         test_df: pd.DataFrame, output_dir: Path) -> None:
    """Write exactly which files went to which split, so it's inspectable after training."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cols = ['class', 'filename', 'image_path']
    train_df[cols].to_csv(output_dir / 'train_split.csv', index=False)
    val_df[cols].to_csv(output_dir / 'val_split.csv', index=False)
    test_df[cols].to_csv(output_dir / 'test_split.csv', index=False)


class GrowthStageDataGenerator(_SequenceBase):
    """Keras Sequence yielding (image_batch, one_hot_label_batch) from a split DataFrame."""

    def __init__(self, dataframe: pd.DataFrame, batch_size: int = None,
                 target_size: Tuple[int, int] = None, shuffle: bool = True,
                 augment: bool = False):
        if tf is None:
            raise ImportError("TensorFlow is required to build GrowthStageDataGenerator/DataPreprocessor.load_data()")
        self.df = dataframe.reset_index(drop=True)
        self.batch_size = batch_size or MODEL_CONFIG['batch_size']
        self.target_size = target_size or MODEL_CONFIG['target_size']
        self.shuffle = shuffle
        self.augment = augment
        self.class_to_index = {c: i for i, c in enumerate(STAGE_LABELS)}
        # Exposed for get_class_weights() / evaluation, mirroring the
        # `.classes` attribute Keras' flow_from_directory used to provide.
        self.classes = self.df['class'].map(self.class_to_index).to_numpy()
        self.samples = len(self.df)
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
        labels = np.zeros((len(batch), len(STAGE_LABELS)), dtype='float32')
        for i, (_, row) in enumerate(batch.iterrows()):
            img = Image.open(row['image_path']).convert('RGB')
            if self.augment:
                img = self._augment_image(img)
            images[i] = np.array(img.resize(self.target_size), dtype='float32')
            labels[i, self.class_to_index[row['class']]] = 1.0

        return images, labels

    @staticmethod
    def _augment_image(img: Image.Image) -> Image.Image:
        """
        Random flip/rotation/brightness/contrast, applied fresh every epoch on
        top of whatever offline augmentation already produced this file. The
        offline variants are a fixed, finite set shared identically across
        every epoch, so the model can still memorize them; this adds a
        continuous per-epoch perturbation instead.
        """
        if np.random.random() > 0.5:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
        if np.random.random() > 0.5:
            img = img.transpose(Image.FLIP_TOP_BOTTOM)
        if np.random.random() > 0.5:
            angle = np.random.uniform(-20, 20)
            img = img.rotate(angle, resample=Image.BILINEAR, fillcolor=(255, 255, 255))
        if np.random.random() > 0.5:
            img = ImageEnhance.Brightness(img).enhance(np.random.uniform(0.8, 1.2))
        if np.random.random() > 0.5:
            img = ImageEnhance.Contrast(img).enhance(np.random.uniform(0.8, 1.2))
        return img


class DataPreprocessor:
    """
    Loads data/raw/<class>/, splits it train/validation/test, and builds a
    generator for each.
    """

    def __init__(self, data_dir: Path,
                 target_size: Tuple[int, int] = None,
                 batch_size: int = None,
                 val_split: float = None,
                 test_split: float = None):
        self.data_dir = Path(data_dir)
        self.target_size = target_size or MODEL_CONFIG['target_size']
        self.batch_size = batch_size or MODEL_CONFIG['batch_size']
        self.val_split = val_split if val_split is not None else MODEL_CONFIG['validation_split']
        self.test_split = test_split if test_split is not None else MODEL_CONFIG['test_split']
        self.stage_labels = STAGE_LABELS
        # Kept for save_model_artifacts()/load_model_artifacts() compatibility
        # (label_encoder.pkl); the generators use class_to_index directly.
        self.label_encoder = LabelEncoder().fit(self.stage_labels)

        if not self.data_dir.exists():
            raise FileNotFoundError(f"Data directory not found: {self.data_dir}")

    def load_data(self):
        """
        Returns (train_generator, validation_generator, test_generator,
        (train_df, val_df, test_df)). The dataframes are what
        save_split_manifest() writes out - callers that don't need the
        manifest can ignore the last element.
        """
        df = list_class_images(self.data_dir)
        train_df, val_df, test_df = split_dataset(df, self.val_split, self.test_split)

        train_generator = GrowthStageDataGenerator(
            train_df, self.batch_size, self.target_size, shuffle=True, augment=True)
        validation_generator = GrowthStageDataGenerator(
            val_df, self.batch_size, self.target_size, shuffle=False, augment=False)
        test_generator = GrowthStageDataGenerator(
            test_df, self.batch_size, self.target_size, shuffle=False, augment=False)

        return train_generator, validation_generator, test_generator, (train_df, val_df, test_df)

    def get_class_weights(self, train_generator: GrowthStageDataGenerator) -> Dict[int, float]:
        """
        Calculate class weights for imbalanced data.
        """
        from sklearn.utils.class_weight import compute_class_weight

        classes = train_generator.classes
        num_classes = len(self.stage_labels)
        unique_classes = np.unique(classes)

        weights = compute_class_weight('balanced', classes=unique_classes, y=classes)

        class_weight_dict = {int(cls): float(w) for cls, w in zip(unique_classes, weights)}
        for i in range(num_classes):
            class_weight_dict.setdefault(i, 1.0)

        return class_weight_dict

    def get_dataset_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the dataset.
        """
        df = list_class_images(self.data_dir)
        counts = df['class'].value_counts().to_dict()
        return {
            'total_images': len(df),
            'images_per_class': {stage: counts.get(stage, 0) for stage in self.stage_labels},
            'classes': self.stage_labels,
        }
