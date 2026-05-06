# ML Models - Training & Inference

This directory contains the machine learning models for all four components of the Smart Orchid Care System.

## Structure

```
ml-models/
├── disease_detection/      # Component 1 – Orchid disease detection
│   ├── data/               # Dataset (gitignored – store in cloud)
│   ├── models/             # Trained model files
│   ├── src/                # Training & inference scripts
│   └── README.md
│
├── growth_stage/           # Component 2 – Growth stage recognition
│   ├── data/
│   ├── models/
│   ├── src/
│   └── README.md
│
├── smart_watering/         # Component 3 – Smart watering prediction
│   ├── data/
│   ├── models/
│   ├── src/
│   └── README.md
│
├── hybrid_pollination/     # Component 4 – Hybrid compatibility (IT22065230)
│   ├── data/
│   ├── models/
│   ├── src/
│   └── README.md
│
├── notebooks/              # Shared Jupyter notebooks
├── shared/                 # Shared utilities & helpers
└── requirements.txt        # ML-specific Python dependencies
```

## Setup

```bash
cd ml-models
pip install -r requirements.txt
```

## Notes

- Raw datasets should NOT be committed to Git (they are gitignored)
- Store datasets in Google Drive / Firebase Storage and document the download links
- Trained `.tflite` models for mobile deployment go in each component's `models/` folder
