# Hybrid Pollination & Compatibility Analysis – ML Model

**Component 4** | IT22065230 – Wickramasinghe D.P

## Overview

This module trains a machine learning model that predicts hybrid pollination compatibility between two Vanda orchid parent plants.

## Dataset Features

### Plant-Level Features
- Leaf condition (healthy / weak / diseased)
- Number of leaves (few / medium / many)
- Plant strength (strong / weak)
- Leaf color (dark green / pale)

### Flower Morphological Features
- Petal shape
- Flower symmetry
- Color patterns
- Flower size and structure

### Parent Plant Information
- Species name (Vanda type)
- Same species or cross-species
- Flowering stage (ready / not ready)

### Hybridization Outcome
- Parent A + Parent B combination
- Result: Successful / Failed
- Flower quality & lifespan

## Models to Evaluate
- Random Forest
- Support Vector Machine (SVM)
- XGBoost
- Logistic Regression

## Target Metrics
- Accuracy > 80%
- Precision, Recall, F1-Score

## Workflow

```
1. Capture parent orchid images
2. Extract plant-level + flower-level features (OpenCV)
3. Combine image features with trait data
4. Train ML model
5. Output: Compatibility score + Success probability
6. Convert best model to TFLite for mobile deployment
```
