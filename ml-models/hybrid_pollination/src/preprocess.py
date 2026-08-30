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

# Group column: images sharing this value are the SAME physical plant and must
# never be split across train and test.
GROUP_COLUMN = "sample_id"


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
    random_state: int = 42,
    save_features: bool = True
):
    """
    Full preprocessing pipeline.

    EVALUATION DESIGN - read this before changing anything here
    -----------------------------------------------------------
    This function used to shuffle all 357 images and split them randomly. That
    was data leakage: the images come from only 28 distinct plants, so photo #7
    of a plant trained the model while photo #8 of the SAME plant tested it.
    The model memorised individual plants and reported 100% test accuracy.

    It no longer produces a train/val/test split at all, for a concrete reason:

        plants per class -   Suitable 17,  Not Suitable 9,  Moderate 2

    With only TWO plants labelled Moderate, no grouped three-way split can put
    that class in train, validation and test simultaneously. Any such split
    would either leak or silently drop a class.

    So the honest design is grouped CROSS-VALIDATION over all data, with the
    plant (`sample_id`) as the group. This function therefore returns the full
    unscaled X, y and groups, and `train.py` performs StratifiedGroupKFold.

    Scaling is deliberately NOT applied here. Fitting a scaler on all data
    before cross-validation leaks test-fold statistics into training. The
    scaler belongs inside a Pipeline, fitted per fold. The scaler saved to
    preprocessors.pkl is fitted on all data for INFERENCE ONLY.

    Returns:
        dict with X, y, groups, feature_names, trait_encoders, scaler,
        label_encoder, class_plant_counts
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

    # Groups: which plant each image came from. This is what makes the
    # evaluation honest - all images of one plant stay together.
    if GROUP_COLUMN not in df.columns:
        raise ValueError(
            f"'{GROUP_COLUMN}' column is required for grouped evaluation but is "
            "missing. Without it every metric would be inflated by leakage."
        )
    groups = df[GROUP_COLUMN].values

    # Encode target labels
    label_encoder = LabelEncoder()
    y_encoded = label_encoder.fit_transform(y)
    print(f"  Label mapping: {dict(zip(label_encoder.classes_, label_encoder.transform(label_encoder.classes_)))}")

    # ── Group diagnostics ─────────────────────
    plant_labels = df.groupby(GROUP_COLUMN)[TARGET_COLUMN].first()
    class_plant_counts = plant_labels.value_counts().to_dict()

    print(f"\n[STEP] Grouped evaluation setup:")
    print(f"  Images : {len(X)}")
    print(f"  Plants : {len(plant_labels)}   <- the TRUE sample size")
    print(f"  Plants per class:")
    for cls, n in sorted(class_plant_counts.items()):
        warn = "  <- too few to validate" if n < 5 else ""
        print(f"    {cls:15s}: {n:2d} plants{warn}")

    thin = [c for c, n in class_plant_counts.items() if n < 5]
    if thin:
        print(f"\n  [WARN] {', '.join(thin)} cannot be reliably validated at plant level.")
        print(f"         Per-class results for these classes are indicative only.")

    # Scaler fitted on all data for INFERENCE ONLY. Cross-validation must not
    # use it - train.py scales inside each fold via a Pipeline.
    scaler = StandardScaler()
    scaler.fit(X)

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
        "X": X, "y": y_encoded, "groups": groups,
        "feature_names": feature_names,
        "trait_encoders": trait_encoders,
        "scaler": scaler,
        "label_encoder": label_encoder,
        "class_plant_counts": class_plant_counts,
        "n_plants": len(plant_labels),
        "random_state": random_state,
    }


if __name__ == "__main__":
    result = prepare_dataset()
    print("\n[DONE] Preprocessing complete")
    print(f"   X shape : {result['X'].shape}")
    print(f"   Plants  : {result['n_plants']}")
    print(f"   Classes : {list(result['label_encoder'].classes_)}")
    print("   Evaluation is grouped by plant; run train.py for cross-validated results.")
