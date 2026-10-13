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
        LOCAL_URL: 'http://192.168.113.51:8000'      // Your PC's Wi-Fi IP (ipconfig)
    },
    PROD: {
        BASE_URL: 'https://your-api-domain.com'   // For production
    }
};

// Detect platform
const isAndroid = Platform.OS === 'android';
const isWeb = Platform.OS === 'web';

// react-native-device-info isn't a project dependency, so an Android
// emulator vs. a physical Android device can't be auto-detected - set this
// manually if you switch to emulator testing.
// true:  running in the Android emulator on this machine (uses ENV.DEV.ANDROID_URL)
// false: running via Expo Go on a real phone (uses ENV.DEV.LOCAL_URL)
const USE_ANDROID_EMULATOR = false;

// Choose base URL. Web always uses localhost since the browser runs on the
// same machine as the backend; native (phone) needs the PC's LAN IP because
// "localhost" on the phone means the phone itself, not this computer.
let BASE_URL;
if (__DEV__) {
    if (isWeb) {
        BASE_URL = ENV.DEV.BASE_URL;
    } else if (isAndroid && USE_ANDROID_EMULATOR) {
        BASE_URL = ENV.DEV.ANDROID_URL;
    } else {
        BASE_URL = ENV.DEV.LOCAL_URL;
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