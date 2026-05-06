# 🌺 AI-Powered Smart Orchid Care System

### Using Multi-Modal Machine Learning

> **Project ID:** R26-SE-018  
> **Institution:** Sri Lanka Institute of Information Technology (SLIIT)  
> **Degree:** B.Sc. (Hons) in Information Technology – Software Engineering  
> **Date:** March 2026

---

## 📖 Overview

An integrated AI-powered platform designed to support the complete orchid cultivation lifecycle. The system combines **IoT sensors**, **computer vision**, and **multi-modal machine learning** to assist orchid growers with plant health monitoring, environmental management, and hybrid breeding decision-making.

The system focuses primarily on **Vanda orchids**, which are widely cultivated in tropical regions but remain underrepresented in computational breeding research.

---

## 🧩 System Components

| #  | Component | Description | Member |
|----|-----------|-------------|--------|
| 1  | **Orchid Disease Detection & Treatment Recommendation** | Analyzes leaf/plant images to detect diseases and recommend treatments | TBD |
| 2  | **Orchid Growth Stage Recognition & Bloom Prediction** | Identifies growth stages and predicts flowering periods using images + environmental data | TBD |
| 3  | **Smart Watering & Automated Fertilization** | IoT sensor-driven ML models for automated irrigation and fertilization | TBD |
| 4  | **Hybrid Pollination & Compatibility Analysis** | Predicts hybrid compatibility between parent orchids using image analysis + ML | IT22065230 – Wickramasinghe D.P |

---

## 🏗️ Tech Stack

| Layer | Technology | Reason |
|-------|------------|--------|
| **Mobile App** | React Native | Cross-platform, single codebase, large community |
| **Backend API** | FastAPI (Python) | Fast, async support, auto-generated API docs |
| **ML on Device** | TensorFlow Lite | Offline predictions (greenhouses have poor connectivity) |
| **Database** | Firebase (free tier) | Real-time database, zero cost for pilot, easy auth |
| **ML Training** | Python, Scikit-learn, TensorFlow/PyTorch | Industry-standard ML libraries |
| **Image Processing** | OpenCV | Feature extraction from orchid images |
| **IoT Hardware** | Raspberry Pi, ESP32, DHT22 | Image capture, sensor data, edge processing |

---

## 📁 Project Structure

```
R26-SE-018/
│
├── mobile/                          # React Native mobile application
│   ├── src/
│   │   ├── components/              # Reusable UI components
│   │   ├── screens/                 # App screens
│   │   ├── navigation/             # Navigation configuration
│   │   ├── services/               # API calls & Firebase services
│   │   ├── utils/                  # Helper functions
│   │   └── assets/                 # Images, fonts, icons
│   ├── package.json
│   └── README.md
│
├── backend/                         # FastAPI backend server
│   ├── app/
│   │   ├── api/
│   │   │   └── routes/             # API route handlers
│   │   ├── models/                 # Pydantic models & DB schemas
│   │   ├── services/              # Business logic
│   │   ├── core/                  # Config, security, dependencies
│   │   └── main.py                # FastAPI app entry point
│   ├── tests/                     # Backend unit tests
│   ├── requirements.txt
│   └── README.md
│
├── ml-models/                       # Machine learning models & training
│   ├── disease_detection/          # Component 1 – Disease detection model
│   ├── growth_stage/               # Component 2 – Growth stage recognition
│   ├── smart_watering/             # Component 3 – Watering/fertilization model
│   ├── hybrid_pollination/         # Component 4 – Hybrid compatibility model
│   ├── notebooks/                  # Jupyter notebooks for experimentation
│   ├── shared/                    # Shared utilities across ML models
│   └── README.md
│
├── iot/                             # IoT device firmware & scripts
│   ├── raspberry_pi/              # Raspberry Pi camera & processing scripts
│   ├── esp32/                     # ESP32 sensor firmware
│   └── README.md
│
├── docs/                            # Project documentation
│   ├── architecture/              # System architecture diagrams
│   ├── api/                       # API documentation
│   ├── research/                  # Research papers & references
│   └── user-guides/              # User manuals
│
├── .gitignore
├── LICENSE
└── README.md                        # This file
```

---

## 🚀 Getting Started

### Prerequisites

- **Node.js** >= 18.x
- **Python** >= 3.10
- **npm** or **yarn**
- **Android Studio** / **Xcode** (for mobile emulation)
- Firebase account (free tier)

### 1. Clone the Repository

```bash
git clone https://github.com/dinith114/R26-SE-018.git
cd R26-SE-018
```

### 2. Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### 3. Mobile App Setup

```bash
cd mobile
npm install
npx react-native run-android    # or run-ios
```

### 4. ML Model Training

```bash
cd ml-models
pip install -r requirements.txt
# Run individual model training scripts
```

---

## 🤝 Contributing

1. Create a feature branch from `main`
2. Follow the naming convention: `feature/<component-name>/<feature>`
3. Write meaningful commit messages
4. Submit a Pull Request for review

### Branch Naming Convention

```
feature/disease-detection/<feature-name>
feature/growth-stage/<feature-name>
feature/smart-watering/<feature-name>
feature/hybrid-pollination/<feature-name>
```

---

## 📄 License

This project is developed as part of the BSc (Hons) IT degree program at SLIIT.

---

## 📬 Contact

For questions or collaboration, please reach out to the project team through the SLIIT Department of Information Technology.
