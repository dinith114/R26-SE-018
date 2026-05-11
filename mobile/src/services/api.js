import { Platform } from 'react-native';

/**
 * API Client Service
 * Handles communication with the FastAPI backend.
 */

const getBaseUrl = () => {
  // If you test on a physical phone using Expo Go, change this to your PC's IP address
  if (Platform.OS === 'web') return 'http://localhost:8000';
  // Use the exact IP address of this computer for physical devices to connect over Wi-Fi
  return 'http://172.20.10.2:8000';
};

const BASE_URL = getBaseUrl();
const API_PREFIX = '/api/v1/pollination';

/**
 * Assess pollination suitability of a plant image.
 */
export const assessSuitability = async (imageUri, traits = {}) => {
  const formData = new FormData();

  // Handle image upload differently for Web vs Native
  if (Platform.OS === 'web') {
    const response = await fetch(imageUri);
    const blob = await response.blob();
    formData.append('image', blob, 'photo.jpg');
  } else {
    const filename = imageUri.split('/').pop() || 'photo.jpg';
    const match = /\.(\w+)$/.exec(filename);
    const type = match ? `image/${match[1]}` : 'image/jpeg';

    formData.append('image', {
      uri: imageUri,
      name: filename,
      type: type,
    });
  }

  // Append traits
  formData.append('leaf_condition', traits.leaf_condition || 'unknown');
  formData.append('plant_strength', traits.plant_strength || 'unknown');
  formData.append('disease_visible', traits.disease_visible || 'unknown');
  formData.append('flower_condition', traits.flower_condition || 'unknown');

  try {
    const response = await fetch(`${BASE_URL}${API_PREFIX}/assess`, {
      method: 'POST',
      body: formData,
      // Do NOT set Content-Type manually, the browser/fetch automatically 
      // sets it to multipart/form-data with the correct boundary
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'Assessment failed');
    }

    return await response.json();
  } catch (error) {
    console.error('Suitability assessment error:', error);
    throw error;
  }
};

/**
 * Get pollination guidance based on suitability.
 */
export const getGuidance = async (suitability = 'Suitable') => {
  try {
    const response = await fetch(
      `${BASE_URL}${API_PREFIX}/guidance?suitability=${encodeURIComponent(suitability)}`
    );

    if (!response.ok) {
      throw new Error('Failed to fetch guidance');
    }

    return await response.json();
  } catch (error) {
    console.error('Guidance error:', error);
    throw error;
  }
};

/**
 * Check if the ML model is loaded and ready.
 */
export const checkModelHealth = async () => {
  try {
    const response = await fetch(`${BASE_URL}${API_PREFIX}/health`);
    return await response.json();
  } catch (error) {
    console.error('Health check error:', error);
    return { status: 'offline', model_loaded: false };
  }
};
