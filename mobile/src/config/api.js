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
        LOCAL_URL: 'http://192.168.1.129:8000'    // this laptop; keep in step with careV2.js
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
if (Platform.OS === 'web') {
    BASE_URL = ENV.DEV.BASE_URL;
} else {
    /* The LAN address, on device and in release alike.
   
       This used to pick ENV.DEV.ANDROID_URL (10.0.2.2) on Android, which is the
       emulator's alias for the host machine and unreachable from a real phone;
       and in a RELEASE build __DEV__ is false, so it fell through to
       ENV.PROD.BASE_URL - the 'your-api-domain.com' placeholder. Either way this
       component could not reach the backend from the APK on a physical device.
   
       Kept in step with LAN_IP in services/careV2.js. Both must be updated when
       the laptop's address changes; `node preflight.js` prints it. */
    BASE_URL = ENV.DEV.LOCAL_URL;
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