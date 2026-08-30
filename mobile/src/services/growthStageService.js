/**
 * Growth Stage Recognition Service
 * Component 2: Orchid Growth Stage Recognition & Bloom Prediction
 */
import { Platform } from 'react-native';
import { API_CONFIG } from '../config/api';
import * as ImagePicker from 'expo-image-picker';

class GrowthStageService {
    /**
     * Upload image for growth stage prediction
     */
    static async identifyGrowthStage(imageUri) {
        try {
            const formData = new FormData();
            const fileName = imageUri.split('/').pop() || 'orchid.jpg';
            const extension = (fileName.split('.').pop() || 'jpg').toLowerCase();
            const mimeType = extension === 'png' ? 'image/png' : 'image/jpeg';

            // For web
            if (Platform.OS === 'web') {
                const fileResponse = await fetch(imageUri);
                const blob = await fileResponse.blob();
                formData.append('file', blob, fileName);
            } else {
                // For mobile
                formData.append('file', {
                    uri: imageUri,
                    name: fileName,
                    type: mimeType,
                });
            }

            const response = await fetch(
                `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.GROWTH_IDENTIFY}`,
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
                throw new Error(result.detail || 'Prediction failed');
            }

            return result;
        } catch (error) {
            console.error('Growth stage identification error:', error);
            throw error;
        }
    }

    /**
     * Upload image for per-object growth stage prediction: detects each
     * orchid plant/flower bunch/bud/seed pod in the photo separately and
     * returns a growth stage prediction for each one.
     */
    static async identifyGrowthStageObjects(imageUri) {
        try {
            const formData = new FormData();
            const fileName = imageUri.split('/').pop() || 'orchid.jpg';
            const extension = (fileName.split('.').pop() || 'jpg').toLowerCase();
            const mimeType = extension === 'png' ? 'image/png' : 'image/jpeg';

            if (Platform.OS === 'web') {
                const fileResponse = await fetch(imageUri);
                const blob = await fileResponse.blob();
                formData.append('file', blob, fileName);
            } else {
                formData.append('file', {
                    uri: imageUri,
                    name: fileName,
                    type: mimeType,
                });
            }

            const response = await fetch(
                `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.GROWTH_IDENTIFY_OBJECTS}`,
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
                throw new Error(result.detail || 'Detection failed');
            }

            return result;
        } catch (error) {
            console.error('Growth stage object detection error:', error);
            throw error;
        }
    }

    /**
     * Get all growth stages
     */
    static async getStages() {
        try {
            const response = await fetch(
                `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.GROWTH_STAGES}`
            );
            const result = await response.json();
            
            if (!response.ok) {
                throw new Error(result.detail || 'Failed to fetch stages');
            }
            
            return result.data.stages;
        } catch (error) {
            console.error('Get stages error:', error);
            throw error;
        }
    }

    /**
     * Get stage information by key
     */
    static async getStageInfo(stageKey) {
        try {
            const response = await fetch(
                `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.GROWTH_STAGE_INFO}/${stageKey}`
            );
            const result = await response.json();
            
            if (!response.ok) {
                throw new Error(result.detail || 'Failed to fetch stage info');
            }
            
            return result.data;
        } catch (error) {
            console.error('Get stage info error:', error);
            throw error;
        }
    }

    /**
     * Health check
     */
    static async healthCheck() {
        try {
            const response = await fetch(
                `${API_CONFIG.BASE_URL}${API_CONFIG.ENDPOINTS.GROWTH_HEALTH}`
            );
            const result = await response.json();
            return result;
        } catch (error) {
            console.error('Health check error:', error);
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
                mediaTypes: ImagePicker.MediaTypeOptions.Images,
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

export default GrowthStageService;