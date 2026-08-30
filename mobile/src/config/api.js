/**
 * API configuration for Component 2 (growth stage and bloom prediction).
 *
 * The backend address is NOT chosen here any more. This module used to pick
 * ENV.DEV.ANDROID_URL (10.0.2.2) on Android - the emulator's alias for the host
 * machine, unreachable from a real phone - and in a release build __DEV__ is
 * false, so it fell through to a 'your-api-domain.com' placeholder. Either way
 * this component could not reach the backend from an installed APK.
 *
 * One constant now, shared with every other screen and service.
 */
import BASE_URL from './backend';

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