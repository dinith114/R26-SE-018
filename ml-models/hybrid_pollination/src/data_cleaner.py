"""
Hybrid Pollination - Data Cleaner
Cleans and standardizes the image_dataset.csv for training.

Usage:
    python src/data_cleaner.py
"""

import pandas as pd
import os
import sys


# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_CSV = os.path.join(BASE_DIR, "data", "image_dataset.csv")
CLEAN_CSV = os.path.join(BASE_DIR, "data", "image_annotations_clean.csv")
PLANT_DIR = os.path.join(BASE_DIR, "data", "images", "plants")
FLOWER_DIR = os.path.join(BASE_DIR, "data", "images", "flowers")

# Supported image formats (OpenCV-compatible)
SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}


def load_raw_csv(path: str) -> pd.DataFrame:
    """Load the raw CSV file."""
    df = pd.read_csv(path)
    print(f"[INFO] Loaded {len(df)} rows from {os.path.basename(path)}")
    print(f"[INFO] Columns: {list(df.columns)}")
    return df


def clean_labels(df: pd.DataFrame) -> pd.DataFrame:
    """Standardize suitability labels to 3 clean classes."""
    # Fix double spaces and whitespace
    df["suitability_label"] = df["suitability_label"].str.strip()
    df["suitability_label"] = df["suitability_label"].str.replace(r"\s+", " ", regex=True)

    # Standardize to 3 classes
    label_map = {
        "Suitable": "Suitable",
        "suitable": "Suitable",
        "moderate": "Moderate",
        "Moderate": "Moderate",
        "Not Suitable": "Not Suitable",
        "not suitable": "Not Suitable",
    }
    df["suitability_label"] = df["suitability_label"].map(label_map)

    # Check for unmapped labels
    unmapped = df["suitability_label"].isna().sum()
    if unmapped > 0:
        print(f"[WARN] {unmapped} rows have unmapped suitability labels — dropping them")
        df = df.dropna(subset=["suitability_label"])

    return df


def clean_trait_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Clean and standardize trait columns."""
    # Strip whitespace from all string columns
    str_cols = ["species", "leaf_condition", "leaf_count", "plant_strength",
                "disease_visible", "flower_condition", "image_type"]
    for col in str_cols:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.lower()

    # Standardize disease_visible
    df["disease_visible"] = df["disease_visible"].map({
        "yes": "yes", "no": "no",
        "nan": "unknown", "": "unknown"
    }).fillna("unknown")

    # Standardize flower_condition
    df["flower_condition"] = df["flower_condition"].replace({
        "nan": "unknown", "": "unknown"
    }).fillna("unknown")

    return df


def filter_usable_images(df: pd.DataFrame) -> pd.DataFrame:
    """Remove rows with DNG/unsupported formats and verify image existence."""
    # Check file extension
    df["extension"] = df["image_name"].apply(
        lambda x: os.path.splitext(str(x))[1].lower()
    )

    # Filter to supported formats only
    supported_mask = df["extension"].isin(SUPPORTED_EXTENSIONS)
    n_unsupported = (~supported_mask).sum()
    if n_unsupported > 0:
        print(f"[INFO] Removing {n_unsupported} rows with unsupported formats (DNG, etc.)")
        df = df[supported_mask].copy()

    # Build full image path and check existence
    def get_image_path(row):
        if row["image_type"] == "plant":
            return os.path.join(PLANT_DIR, str(row["image_name"]))
        elif row["image_type"] == "flower":
            return os.path.join(FLOWER_DIR, str(row["image_name"]))
        return None

    df["image_path"] = df.apply(get_image_path, axis=1)

    # Check which images actually exist
    exists_mask = df["image_path"].apply(lambda p: p is not None and os.path.exists(p))
    n_missing = (~exists_mask).sum()
    if n_missing > 0:
        print(f"[WARN] {n_missing} images not found on disk — removing those rows")
        missing = df[~exists_mask]["image_name"].tolist()[:10]
        print(f"        Examples: {missing}")

    df = df[exists_mask].copy()

    # Drop helper column
    df = df.drop(columns=["extension"])

    return df


def filter_plant_images(df: pd.DataFrame) -> pd.DataFrame:
    """
    For the suitability model, we primarily use plant images.
    Flower images all have 'unknown' traits and are all 'Suitable' — no training signal.
    """
    plants_df = df[df["image_type"] == "plant"].copy()
    flowers_df = df[df["image_type"] == "flower"].copy()

    print(f"\n[INFO] Plant images: {len(plants_df)}  (used for training)")
    print(f"[INFO] Flower images: {len(flowers_df)} (kept for feature extraction demo only)")

    return plants_df, flowers_df


def print_summary(df: pd.DataFrame):
    """Print dataset statistics."""
    print("\n" + "=" * 60)
    print("CLEANED DATASET SUMMARY")
    print("=" * 60)

    print(f"\nTotal usable plant images: {len(df)}")
    print(f"Unique plants (sample_ids): {df['sample_id'].nunique()}")

    print("\n--- Suitability Label Distribution ---")
    label_counts = df["suitability_label"].value_counts()
    for label, count in label_counts.items():
        pct = count / len(df) * 100
        print(f"  {label:15s}: {count:4d}  ({pct:.1f}%)")

    print("\n--- Leaf Condition Distribution ---")
    print(df["leaf_condition"].value_counts().to_string(header=False))

    print("\n--- Plant Strength Distribution ---")
    print(df["plant_strength"].value_counts().to_string(header=False))

    print("\n--- Disease Visible Distribution ---")
    print(df["disease_visible"].value_counts().to_string(header=False))

    print("\n" + "=" * 60)


def run_cleaning():
    """Full cleaning pipeline."""
    # Load
    df = load_raw_csv(RAW_CSV)

    # Clean
    df = clean_labels(df)
    df = clean_trait_columns(df)
    df = filter_usable_images(df)

    # Split plant vs flower
    plants_df, flowers_df = filter_plant_images(df)

    # Save cleaned plant data (for training)
    plants_df.to_csv(CLEAN_CSV, index=False)
    print(f"\n[SAVED] Cleaned plant data -> {CLEAN_CSV}")

    # Save flower data separately (for demo)
    flower_csv = os.path.join(BASE_DIR, "data", "flower_annotations.csv")
    flowers_df.to_csv(flower_csv, index=False)
    print(f"[SAVED] Flower annotations -> {flower_csv}")

    # Summary
    print_summary(plants_df)

    return plants_df


if __name__ == "__main__":
    run_cleaning()
