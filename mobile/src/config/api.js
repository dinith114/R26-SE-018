/**
 * api.js — backend connection settings.
 *
 * COMPONENT 1 (disease detection). Only this component's screens read this file.
 *
 * ---------------------------------------------------------------------------
 * IF THE APP SAYS IT CANNOT REACH THE SERVER, CHANGE ONE LINE: API_HOST BELOW.
 * ---------------------------------------------------------------------------
 *
 * Why this is not just "localhost":
 *
 * When Expo Go runs on your phone, `localhost` means THE PHONE ITSELF, not your
 * laptop. The phone has no server on it, so the request fails instantly. You
 * must give the phone your laptop's address on the Wi-Fi network.
 *
 * How to find it (Windows):
 *     ipconfig
 * Look under your Wi-Fi adapter for "IPv4 Address", e.g. 192.168.1.101
 *
 * Two things must both be true:
 *   1. The phone and the laptop are on the SAME Wi-Fi network.
 *   2. The backend was started with --host 0.0.0.0, not the default. The
 *      default only accepts connections from the laptop itself.
 *
 *      cd backend
 *      .venv/Scripts/python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
 *
 * If it still fails, Windows Firewall is usually the cause — allow Python on
 * private networks when the prompt appears.
 */

// Your laptop's Wi-Fi IPv4 address. Detected as 192.168.1.101 on 30 Aug 2026.
// This changes when you join a different Wi-Fi network, so re-check with ipconfig.
export const API_HOST = '192.168.1.101';
export const API_PORT = 8000;

export const API_BASE_URL = `http://${API_HOST}:${API_PORT}`;
export const DISEASE_API = `${API_BASE_URL}/api/v1/disease`;

/**
 * Request timeout in milliseconds.
 *
 * Generous on purpose. The very first /detect call after the server starts has
 * to load two TensorFlow models from disk, which takes several seconds. Every
 * call after that is fast because the models stay cached in memory.
 */
export const REQUEST_TIMEOUT_MS = 60000;

/** Largest photo the backend accepts. Matches MAX_UPLOAD_BYTES in the API. */
export const MAX_IMAGE_BYTES = 12 * 1024 * 1024;

/**
 * Confidence below which the backend reports "unidentified" instead of naming a
 * disease. Chosen from the validation sweep, not the test set.
 * See PROJECT_CONTEXT.md section 4c.
 *
 * Sent as a query parameter so the value is visible and adjustable from the app
 * rather than hidden in the server.
 */
export const CONFIDENCE_THRESHOLD = 0.7;
