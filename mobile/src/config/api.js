/**
 * API Configuration
 * Component: Orchid Growth Stage Recognition
 */
import { Platform } from 'react-native';

// For different environments
const ENV = {
    DEV: {
        BASE_URL: 'http://localhost:8000',        // For iOS simulator
        ANDROID_URL: 'http://10.0.2.2:8000',      // For Android emulator
        LOCAL_URL: 'http://192.168.1.100:8000'    // Replace with your local IP
    },
    PROD: {
        BASE_URL: 'https://your-api-domain.com'   // For production
    }
};

// Detect platform
const isAndroid = Platform.OS === 'android';

// Choose base URL
// react-native-device-info isn't a project dependency, so emulator vs. physical
// device can't be auto-detected. Defaults to the Android emulator address;
// switch to ENV.DEV.LOCAL_URL manually when testing on a physical Android device.
let BASE_URL;
if (__DEV__) {
    if (isAndroid) {
        BASE_URL = ENV.DEV.ANDROID_URL;
    } else {
        // iOS or web
        BASE_URL = ENV.DEV.BASE_URL;
    }
} else {
    BASE_URL = ENV.PROD.BASE_URL;
}

export const API_CONFIG = {
    BASE_URL: BASE_URL,
    ENDPOINTS: {
        // Growth Stage Recognition (Component 2)
        GROWTH_IDENTIFY: '/api/v1/growth/identify',
        GROWTH_IDENTIFY_OBJECTS: '/api/v1/growth/identify-objects',
        GROWTH_STAGES: '/api/v1/growth/stages',
        GROWTH_STAGE_INFO: '/api/v1/growth/stage',
        GROWTH_HEALTH: '/api/v1/growth/health',

        // Bloom Date Prediction (Component 2)
        BLOOM_PREDICT: '/api/v1/bloom/predict',
        BLOOM_PREDICT_OBJECTS: '/api/v1/bloom/predict-objects',
        BLOOM_HEALTH: '/api/v1/bloom/health',

        // Disease Detection (Component 1)
        DISEASE_DETECT: '/api/v1/disease/detect',
        
        // Smart Watering (Component 3)
        WATERING_PREDICT: '/api/v1/watering/predict',
        
        // Hybrid Pollination (Component 4)
        POLLINATION_COMPATIBILITY: '/api/v1/pollination/compatibility',
    },
    TIMEOUT: 30000, // 30 seconds
    MAX_RETRIES: 3,
};