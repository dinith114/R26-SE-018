/**
 * Bloom Date Prediction Service
 * Component 2: Orchid Growth Stage Recognition & Bloom Prediction
 */
import { Platform } from 'react-native';
import { File } from 'expo-file-system';
import { API_CONFIG } from '../config/api';
import * as ImagePicker from 'expo-image-picker';

class BloomPredictionService {
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
            formData.append('file', new File(imageUri));
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
