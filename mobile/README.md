# Mobile App - React Native

## Setup

```bash
cd mobile
npm install
```

## Run

```bash
# Android
npx react-native run-android

# iOS
npx react-native run-ios
```

## Structure

```
mobile/
├── src/
│   ├── components/       # Reusable UI components
│   ├── screens/          # App screens
│   │   ├── HomeScreen
│   │   ├── DiseaseDetectionScreen
│   │   ├── GrowthStageScreen
│   │   ├── WateringScreen
│   │   └── HybridPollinationScreen
│   ├── navigation/       # React Navigation config
│   ├── services/         # API client & Firebase services
│   ├── utils/            # Helper functions
│   └── assets/           # Images, fonts, icons
├── package.json
└── README.md
```

## Key Libraries

- React Navigation (routing)
- React Native Camera (image capture)
- TensorFlow Lite React Native (on-device ML)
- Firebase SDK (auth, database, storage)
- Axios (API calls)
