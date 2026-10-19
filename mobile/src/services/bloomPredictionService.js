/**
 * Bloom Date Prediction Service
 * Component 2: Orchid Growth Stage Recognition & Bloom Prediction
 */
import { Platform } from 'react-native';
import { ref, query, orderByKey, startAt, endAt, get } from 'firebase/database';
import { API_CONFIG } from '../config/api';
import { database } from '../config/firebase';
import { getOverview } from './careV2';
import { getClaims } from './auth';
import * as ImagePicker from 'expo-image-picker';

// A Firebase push id starts with its creation time (epoch ms) in this alphabet,
// so a key range is a time range. The firmware writes buffered readings under
// keys built from their OWN time, so this holds for late uploads too.
const PUSH_CHARS = '-0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ_abcdefghijklmnopqrstuvwxyz';
const pushKeyPrefix = (ms) => {
    let n = Math.floor(ms);
    let out = '';
    for (let i = 0; i < 8; i += 1) {
        out = PUSH_CHARS[n % 64] + out;
        n = Math.floor(n / 64);
    }
    return out;
};

// Same plausibility bounds the backend uses; -999 is the firmware's failure marker
const PLAUSIBLE = { temperature: [5, 55], humidity: [5, 100], light: [0, 200000] };
const measured = (reading, key) => {
    const v = Number(reading?.[key]);
    const [lo, hi] = PLAUSIBLE[key];
    return Number.isFinite(v) && v > -999 && v >= lo && v <= hi ? v : null;
};

class BloomPredictionService {
    /**
     * Every section on the farm, flattened for a dropdown.
     * @returns {Promise<Array<{key, houseId, sectionId, label}>>}
     */
    static async getSections() {
        const data = await getOverview();
        const list = [];
        (data?.houses || []).forEach((house) => {
            const houseName = house.meta?.name || house.houseId;
            (house.sections || []).forEach((sec) => {
                list.push({
                    key: `${house.houseId}-${sec.sectionId}`,
                    houseId: house.houseId,
                    sectionId: sec.sectionId,
                    label: `${houseName} · ${sec.meta?.name || sec.meta?.label || sec.sectionId}`,
                });
            });
        });
        return list;
    }

    /**
     * The section's sensor reading nearest to `atMs`, within ± windowMin.
     * Nodes report every few minutes, so an exact match is rare.
     *
     * @returns {Promise<null | {timestamp, offsetMin, temperature, humidity, light}>}
     *          null when no reading falls inside the window. A failed sensor's
     *          value comes back as null so the user types that one in.
     */
    static async getReadingAt(houseId, sectionId, atMs, windowMin = 10) {
        // Each farm lives under its tenant: /tenants/{tenantId}/farm/...
        const { tenantId } = await getClaims();
        if (!tenantId) {
            throw new Error('This account is not linked to a farm, so sensor history is unavailable.');
        }
        const span = windowMin * 60000;
        const historyQuery = query(
            ref(database, `tenants/${tenantId}/farm/history/${houseId}/${sectionId}`),
            orderByKey(),
            startAt(pushKeyPrefix(atMs - span)),
            endAt(pushKeyPrefix(atMs + span) + '~'),
        );
        const snapshot = await get(historyQuery);
        const records = snapshot.val() || {};

        let best = null;
        Object.values(records).forEach((r) => {
            const t = Number(r?.timestamp);
            if (!Number.isFinite(t) || Math.abs(t - atMs) > span) return;
            const values = {
                temperature: measured(r, 'temperature'),
                humidity: measured(r, 'humidity'),
                light: measured(r, 'light'),
            };
            if (Object.values(values).every((v) => v === null)) return;
            if (!best || Math.abs(t - atMs) < Math.abs(best.timestamp - atMs)) {
                best = { timestamp: t, ...values };
            }
        });

        return best && { ...best, offsetMin: (best.timestamp - atMs) / 60000 };
    }

    /**
     * Build the multipart form for a bloom prediction request: the image
     * plus the temperature/humidity/light readings taken at capture time.
     */
    static _buildFormData(imageUri, { temperature, humidity, lightIntensity, captureDate }) {
        const formData = new FormData();
        const fileName = imageUri.split('/').pop() || 'orchid.jpg';

        if (Platform.OS === 'web') {
            // Web needs an async blob fetch, so the caller appends 'file' itself after this returns
        } else {
            formData.append('file', { uri: imageUri, name: fileName, type: fileName.toLowerCase().endsWith('.png') ? 'image/png' : 'image/jpeg' });
        }

        formData.append('temperature', String(temperature));
        formData.append('humidity', String(humidity));
        formData.append('light_intensity', String(lightIntensity));
        if (captureDate) {
            formData.append('capture_date', captureDate);
        }

        return { formData, fileName };
    }

    /**
     * Upload an image plus temperature/humidity/light readings and predict
     * a single bloom date for the whole photo.
     *
     * @param {string} imageUri - Local URI of the selected/captured photo
     * @param {object} conditions - { temperature, humidity, lightIntensity, captureDate? }
     */
    static async predictBloomDate(imageUri, conditions) {
        try {
            const { formData, fileName } = this._buildFormData(imageUri, conditions);

            if (Platform.OS === 'web') {
                const fileResponse = await fetch(imageUri);
                const blob = await fileResponse.blob();
                formData.append('file', blob, fileName);
            }

            const response = await fetch(
                `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.BLOOM_PREDICT}`,
                {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'Accept': 'application/json',
                    },
                }
            );

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.detail || 'Bloom prediction failed');
            }

            return result;
        } catch (error) {
            console.error('Bloom date prediction error:', error);
            throw error;
        }
    }

    /**
     * Upload an image plus temperature/humidity/light readings and predict
     * a bloom date for each individually detected orchid plant/flower
     * bunch/bud/seed pod in the photo.
     *
     * @param {string} imageUri - Local URI of the selected/captured photo
     * @param {object} conditions - { temperature, humidity, lightIntensity, captureDate? }
     */
    static async predictBloomDateObjects(imageUri, conditions) {
        try {
            const { formData, fileName } = this._buildFormData(imageUri, conditions);

            if (Platform.OS === 'web') {
                const fileResponse = await fetch(imageUri);
                const blob = await fileResponse.blob();
                formData.append('file', blob, fileName);
            }

            const response = await fetch(
                `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.BLOOM_PREDICT_OBJECTS}`,
                {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'Accept': 'application/json',
                    },
                }
            );

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.detail || 'Bloom prediction failed');
            }

            return result;
        } catch (error) {
            console.error('Bloom date object prediction error:', error);
            throw error;
        }
    }

    /**
     * Health check
     */
    static async healthCheck() {
        try {
            const response = await fetch(
                `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.BLOOM_HEALTH}`
            );
            return await response.json();
        } catch (error) {
            console.error('Bloom prediction health check error:', error);
            return { status: 'unhealthy' };
        }
    }

    /**
     * Pick image from gallery
     */
    static async pickImage() {
        try {
            const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
            if (!permission.granted) {
                throw new Error('Permission to access gallery is required');
            }

            const result = await ImagePicker.launchImageLibraryAsync({
                mediaTypes: ['images'],
                allowsEditing: true,
                quality: 0.9,
            });

            if (result.canceled || !result.assets?.length) {
                return null;
            }

            return result.assets[0].uri;
        } catch (error) {
            console.error('Pick image error:', error);
            throw error;
        }
    }

    /**
     * Take photo with camera
     */
    static async takePhoto() {
        try {
            const permission = await ImagePicker.requestCameraPermissionsAsync();
            if (!permission.granted) {
                throw new Error('Permission to access camera is required');
            }

            const result = await ImagePicker.launchCameraAsync({
                allowsEditing: true,
                quality: 0.9,
            });

            if (result.canceled || !result.assets?.length) {
                return null;
            }

            return result.assets[0].uri;
        } catch (error) {
            console.error('Take photo error:', error);
            throw error;
        }
    }
}

export default BloomPredictionService;
