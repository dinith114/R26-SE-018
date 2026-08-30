import { Platform } from 'react-native';

/**
 * API Client Service
 * Handles communication with the FastAPI backend.
 */

/**
 * The backend address comes from the shared config, which is the only place it
 * is written down for the whole app. This module used to derive it from the
 * Metro bundle URL so a laptop's changing LAN IP would not break Expo Go
 * testing; that is exactly the per-file divergence config/backend.js exists to
 * prevent, so it was dropped in favour of the shared value.
 *
 * For local testing against a laptop, change HOST in config/backend.js once.
 */
import BASE_URL from '../config/backend';
const API_PREFIX = '/api/v1/pollination';

/**
 * Attach an image to a FormData under `field`, handling Web vs Native.
 */
const appendImage = async (formData, field, imageUri) => {
  if (Platform.OS === 'web') {
    const response = await fetch(imageUri);
    const blob = await response.blob();
    formData.append(field, blob, 'photo.jpg');
    return;
  }

  const filename = imageUri.split('/').pop() || 'photo.jpg';
  const match = /\.(\w+)$/.exec(filename);
  const type = match ? `image/${match[1]}` : 'image/jpeg';

  formData.append(field, { uri: imageUri, name: filename, type });
};

/**
 * Assess pollination suitability of a plant image.
 *
 * Traits are optional. The backend measures what it can from the image and
 * reports, in `trait_resolution`, where every value came from and which traits
 * it still needs the grower to confirm. Only pass a trait here when the user
 * has explicitly chosen it — see the note on 'unknown' below.
 *
 * @param imageUri    Whole-plant photo (required)
 * @param traits      Any values the user explicitly corrected (optional)
 * @param closeupUri  Close-up of one leaf (optional, improves disease accuracy)
 */
export const assessSuitability = async (imageUri, traits = {}, closeupUri = null) => {
  const formData = new FormData();

  await appendImage(formData, 'image', imageUri);
  if (closeupUri) {
    await appendImage(formData, 'leaf_closeup', closeupUri);
  }

  // Send ONLY traits the user actually chose. Previously every field was sent
  // as 'unknown' when unset, which the backend could not distinguish from a
  // real answer — so the image-derived value was always overwritten.
  ['leaf_condition', 'plant_strength', 'disease_visible', 'flower_condition']
    .forEach((key) => {
      const value = traits[key];
      if (value && value !== 'unknown') {
        formData.append(key, value);
      }
    });

  try {
    const response = await fetch(`${BASE_URL}${API_PREFIX}/assess`, {
      method: 'POST',
      body: formData,
      // Do NOT set Content-Type manually, the browser/fetch automatically 
      // sets it to multipart/form-data with the correct boundary
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({}));
      const detail = error.detail;

      // 422 with a structured detail means the image was screened and refused:
      // it is not an orchid. That is an answer, not a failure, so it is flagged
      // for the screen to render as its own result rather than as an error.
      if (response.status === 422 && detail && detail.error === 'not_an_orchid') {
        const refusal = new Error(detail.message || 'That is not an orchid plant.');
        refusal.notAnOrchid = true;
        refusal.inputCheck = detail.input_check || null;
        throw refusal;
      }

      throw new Error(
        typeof detail === 'string' ? detail : 'Assessment failed'
      );
    }

    return await response.json();
  } catch (error) {
    console.error('Suitability assessment error:', error);

    // A network failure here is indistinguishable from a server error unless
    // the address being dialled is reported. BASE_URL is set once in
    // config/backend.js, so naming it turns "could not connect" into something
    // the reader can actually check.
    if (error.message === 'Network request failed') {
      const reachErr = new Error(
        `Could not reach the server at ${BASE_URL}. ` +
        `Check that the backend is running and reachable from this device.`
      );
      reachErr.baseUrl = BASE_URL;
      throw reachErr;
    }

    throw error;
  }
};

/**
 * The address this app is dialling, for on-screen diagnostics.
 */
export const getApiBaseUrl = () => BASE_URL;

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

/**
 * Assess crossing two named orchids.
 *
 * Order matters: by breeding convention the pod (seed) parent is named first
 * and the pollen donor second, so A x B is a different attempt from B x A.
 *
 * The response carries an evidence `tier` and registered `precedents` — never
 * a success percentage. The orchid register records only crosses that worked,
 * so no success rate can honestly be derived from it.
 */
export const assessCompatibility = async (
  podParent, pollenParent, podHealth = null, pollenHealth = null
) => {
  const body = { pod_parent: podParent, pollen_parent: pollenParent };

  // Carry a Level 1 photo assessment into the cross check. The image says what
  // condition the plant is in; the name says what it can be crossed with.
  if (podHealth) body.pod_health = podHealth;
  if (pollenHealth) body.pollen_health = pollenHealth;

  const response = await fetch(`${BASE_URL}${API_PREFIX}/compatibility`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || 'Compatibility check failed');
  }

  return await response.json();
};

/**
 * Rank candidate pollen donors against one pod parent, best evidence first.
 */
export const rankPartners = async (podParent, candidates) => {
  const response = await fetch(`${BASE_URL}${API_PREFIX}/compatibility/rank`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pod_parent: podParent, candidates }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || 'Ranking failed');
  }

  return await response.json();
};

/**
 * Parent names the knowledge base recognises, for type-ahead suggestions.
 * A name absent from this list can still be assessed — it just falls back to
 * genus-level evidence instead of an exact registered precedent.
 */
export const getKnownParents = async () => {
  const response = await fetch(`${BASE_URL}${API_PREFIX}/compatibility/parents`);
  if (!response.ok) throw new Error('Could not load parent names');
  return await response.json();
};
