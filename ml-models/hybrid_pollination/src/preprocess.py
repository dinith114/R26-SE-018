"""
Hybrid Pollination - Preprocessing Module
Loads cleaned CSV, extracts image features, encodes traits, and prepares X/y for training.

Usage:
    python src/preprocess.py
"""

import pandas as pd
import numpy as np
import os
import sys
import joblib
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.model_selection import train_test_split

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feature_extraction import extract_all_features, get_feature_names


# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLEAN_CSV = os.path.join(BASE_DIR, "data", "image_annotations_clean.csv")
FEATURES_CSV = os.path.join(BASE_DIR, "data", "extracted_features.csv")
MODELS_DIR = os.path.join(BASE_DIR, "models")

# Trait columns to use as features
TRAIT_COLUMNS = ["leaf_condition", "plant_strength", "disease_visible", "flower_condition"]

# Target column
TARGET_COLUMN = "suitability_label"


def extract_image_features_for_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """
    Extract OpenCV features from all images in the dataframe.
    Adds feature columns to the dataframe.
    """
    print("\n[STEP] Extracting image features with OpenCV...")
    print(f"  Processing {len(df)} images...")

    feature_records = []
    failed_indices = []

    for idx, row in df.iterrows():
        img_path = row["image_path"]

        if (len(feature_records) + 1) % 50 == 0:
            print(f"  Progress: {len(feature_records) + 1}/{len(df)}")

        try:
            features = extract_all_features(img_path)
            features["_index"] = idx
            feature_records.append(features)
        except Exception as e:
            failed_indices.append(idx)

    print(f"  Extracted features from {len(feature_records)}/{len(df)} images")
    if failed_indices:
        print(f"  [WARN] Failed: {len(failed_indices)} images")

    # Convert to DataFrame and merge
    features_df = pd.DataFrame(feature_records)
    features_df = features_df.set_index("_index")

    # Merge with original data
    merged = df.join(features_df, how="inner")
    print(f"  Final dataset: {len(merged)} rows with image features")

    return merged


def encode_trait_features(df: pd.DataFrame, encoders: dict = None, fit: bool = True):
    """
    Encode categorical trait columns using LabelEncoder.

    Args:
        df: DataFrame with trait columns
        encoders: Existing encoders to transform with (for inference)
        fit: Whether to fit new encoders (True for training, False for inference)

    Returns:
        encoded_df, encoders dict
    """
    if encoders is None:
        encoders = {}

    encoded_df = df.copy()

    for col in TRAIT_COLUMNS:
        if col not in encoded_df.columns:
            continue

        if fit:
            le = LabelEncoder()
            encoded_df[f"{col}_encoded"] = le.fit_transform(encoded_df[col].astype(str))
            encoders[col] = le
        else:
            le = encoders.get(col)
            if le is None:
                continue
            # Handle unseen labels
            encoded_df[f"{col}_encoded"] = encoded_df[col].astype(str).apply(
                lambda x: le.transform([x])[0] if x in le.classes_ else -1
            )

    return encoded_df, encoders


def prepare_feature_matrix(df: pd.DataFrame) -> tuple:
    """
    Prepare the final feature matrix X and target vector y.

    Returns:
        X (numpy array), y (numpy array), feature_names (list)
    """
    # Image feature columns
    image_feature_names = get_feature_names()

    # Encoded trait columns
    trait_feature_names = [f"{col}_encoded" for col in TRAIT_COLUMNS if f"{col}_encoded" in df.columns]

    # Combine all feature columns
    all_feature_names = image_feature_names + trait_feature_names

    # Filter to columns that exist
    available = [f for f in all_feature_names if f in df.columns]

    X = df[available].values.astype(np.float32)
    y = df[TARGET_COLUMN].values

    # Handle any NaN/inf
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    print(f"\n[INFO] Feature matrix: {X.shape[0]} samples × {X.shape[1]} features")
    print(f"[INFO] Target classes: {np.unique(y)}")
    print(f"[INFO] Class distribution: {dict(zip(*np.unique(y, return_counts=True)))}")

    return X, y, available


def prepare_dataset(
    csv_path: str = None,
    test_size: float = 0.15,
    val_size: float = 0.15,
    random_state: int = 42,
    save_features: bool = True
):
    """
    Full preprocessing pipeline.

    Returns:
        dict with X_train, X_val, X_test, y_train, y_val, y_test,
              feature_names, encoders, scaler, label_encoder
    """
    if csv_path is None:
        csv_path = CLEAN_CSV

    # Load cleaned data
    print("[STEP] Loading cleaned CSV...")
    df = pd.read_csv(csv_path)
    print(f"  Loaded {len(df)} rows")

    # Extract image features
    df = extract_image_features_for_dataset(df)

    # Encode traits
    print("\n[STEP] Encoding trait features...")
    df, trait_encoders = encode_trait_features(df, fit=True)

    # Save features CSV for inspection
    if save_features:
        df.to_csv(FEATURES_CSV, index=False)
        print(f"  Saved features -> {os.path.basename(FEATURES_CSV)}")

    # Prepare X, y
    X, y, feature_names = prepare_feature_matrix(df)

    # Encode target labels
    label_encoder = LabelEncoder()
    y_encoded = label_encoder.fit_transform(y)
    print(f"  Label mapping: {dict(zip(label_encoder.classes_, label_encoder.transform(label_encoder.classes_)))}")

    # Scale features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Split: first into train+val and test, then train+val into train and val
    X_trainval, X_test, y_trainval, y_test = train_test_split(
        X_scaled, y_encoded,
        test_size=test_size,
        random_state=random_state,
        stratify=y_encoded
    )

    val_ratio = val_size / (1 - test_size)  # Adjust ratio for second split
    X_train, X_val, y_train, y_val = train_test_split(
        X_trainval, y_trainval,
        test_size=val_ratio,
        random_state=random_state,
        stratify=y_trainval
    )

    print(f"\n[STEP] Dataset split:")
    print(f"  Train: {X_train.shape[0]} samples ({X_train.shape[0] / len(X) * 100:.0f}%)")
    print(f"  Val:   {X_val.shape[0]} samples ({X_val.shape[0] / len(X) * 100:.0f}%)")
    print(f"  Test:  {X_test.shape[0]} samples ({X_test.shape[0] / len(X) * 100:.0f}%)")

    # Save preprocessors
    os.makedirs(MODELS_DIR, exist_ok=True)
    preprocessors = {
        "scaler": scaler,
        "trait_encoders": trait_encoders,
        "label_encoder": label_encoder,
        "feature_names": feature_names,
    }
    preprocessor_path = os.path.join(MODELS_DIR, "preprocessors.pkl")
    joblib.dump(preprocessors, preprocessor_path)
    print(f"\n[SAVED] Preprocessors -> {os.path.basename(preprocessor_path)}")

    return {
        "X_train": X_train, "X_val": X_val, "X_test": X_test,
        "y_train": y_train, "y_val": y_val, "y_test": y_test,
        "feature_names": feature_names,
        "trait_encoders": trait_encoders,
        "scaler": scaler,
        "label_encoder": label_encoder,
    }


if __name__ == "__main__":
    result = prepare_dataset()
    print("\n✅ Preprocessing complete!")
    print(f"   X_train shape: {result['X_train'].shape}")
    print(f"   Classes: {result['label_encoder'].classes_}")
