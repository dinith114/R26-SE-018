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


/* ---------------------------------------------------------------------------
 * Component 1 - disease detection
 *
 * Appended below API_CONFIG; nothing above this line is modified. The host and
 * endpoints come from API_CONFIG, which every component shares. Only the values
 * here are specific to disease detection.
 *
 * WHY THESE EXPORTS MUST EXIST
 * Without them, services/diseaseApi.js imports undefined. The upload URL then
 * becomes "undefined/detect", which the browser treats as a RELATIVE path and
 * sends to the Expo dev server on port 8081 instead of the backend on 8000.
 * The dev server answers every unknown path with its index.html, so the app
 * receives HTML where it expected JSON and reports "the server sent a response
 * the app could not read". The failure looks like a backend problem and is not.
 * ------------------------------------------------------------------------- */

export const API_BASE_URL = API_CONFIG.BASE_URL;
export const DISEASE_API = `${API_CONFIG.BASE_URL}/api/v1/disease`;

/** Host without scheme or port, shown in error hints so a grower can see which
 *  address failed. */
export const API_HOST = API_CONFIG.BASE_URL.replace(/^https?:\/\//, '').split(':')[0];

/**
 * Generous on purpose: the first /detect call after the server starts loads two
 * TensorFlow models from disk, which takes several seconds. Later calls are fast.
 */
export const REQUEST_TIMEOUT_MS = 60000;

/**
 * Confidence below which the backend reports "unidentified" rather than naming
 * a disease. Chosen from the VALIDATION sweep, never the test set.
 * See ml-models/disease_detection/PROJECT_CONTEXT.md section 4c.
 */
export const CONFIDENCE_THRESHOLD = 0.7;
