/**
 * diseaseApi.js — all network calls for the disease detection component.
 *
 * Every function returns either a result or throws an ApiError carrying a
 * message that is safe to show a grower. Raw errors ("Network request failed")
 * are useless to a user, so they are translated here rather than in the screen.
 *
 * ---------------------------------------------------------------------------
 * IMPORTANT DISTINCTION — an unrecognised plant is NOT an error.
 * ---------------------------------------------------------------------------
 *
 * If the photo shows something that is neither healthy, nor Black Leaf Spot,
 * nor Phyllosticta Leaf Spot, the backend still returns HTTP 200 with
 * `disease: "unidentified"`. That is a successful, deliberate answer: the model
 * knows three classes, so anything else falls below the confidence threshold
 * and is referred for expert review.
 *
 * So the screen has three outcomes, not two:
 *
 *     success + identified    -> show disease, severity, treatment
 *     success + unidentified  -> show a clear "not recognised" message
 *     thrown ApiError         -> show a failure message with a Retry button
 *
 * ---------------------------------------------------------------------------
 * WHY THE UPLOAD USES XMLHttpRequest AND NOT fetch
 * ---------------------------------------------------------------------------
 *
 * The first version used fetch with a FormData body and an AbortController for
 * the timeout. The server rejected every upload with HTTP 422 Unprocessable
 * Entity — meaning the multipart body arrived without a readable `image` field,
 * even though the identical request from Python worked.
 *
 * In React Native, fetch is a polyfill over XMLHttpRequest, and combining a
 * FormData body with an abort signal is a known source of broken multipart
 * encoding. XMLHttpRequest handles file uploads natively, has its own timeout
 * that does not interfere with the body, and is what upload libraries use
 * underneath. GET requests below still use fetch, where none of this applies.
 *
 * ---------------------------------------------------------------------------
 * WHY THE FILE IS ATTACHED TWO DIFFERENT WAYS
 * ---------------------------------------------------------------------------
 *
 * The app runs both in Expo Go on a phone and in a browser via Expo Web, and
 * the two have genuinely different FormData implementations:
 *
 *   native   FormData understands a { uri, name, type } object and streams the
 *            file from disk itself.
 *
 *   browser  FormData follows the web standard, where a non-Blob value is
 *            converted with String(). Passing the same object produces the
 *            literal text "[object Object]", and the server rejects it with
 *            422 "Expected UploadFile, received: <class 'str'>".
 *
 * So on web the file is fetched into a real Blob first. `buildImageForm` below
 * is the only place this difference exists.
 */

import { Platform } from 'react-native';

import {
  DISEASE_API,
  API_BASE_URL,
  API_HOST,
  REQUEST_TIMEOUT_MS,
  CONFIDENCE_THRESHOLD,
} from '../config/api';

/** An error with a message that can be shown to the user as-is. */
export class ApiError extends Error {
  constructor(message, { kind = 'unknown', status = null, hint = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind; // 'network' | 'server' | 'models' | 'image' | 'timeout'
    this.status = status;
    this.hint = hint;
  }
}

const NETWORK_HINT =
  `Tried ${API_BASE_URL}\n\n` +
  '• Is the backend running? It must be started with --host 0.0.0.0\n' +
  '• Is your phone on the same Wi-Fi as the laptop?\n' +
  `• Is ${API_HOST} still the laptop's IP? Check with ipconfig and update ` +
  'src/config/api.js\n' +
  '• Windows Firewall may be blocking Python';

/** Pull a readable message out of whatever the server sent back. */
function detailFromText(text, fallback) {
  try {
    const body = JSON.parse(text);
    if (typeof body?.detail === 'string') return body.detail;
    if (Array.isArray(body?.detail) && body.detail.length) {
      // FastAPI validation errors look like [{loc:[...], msg:'...', type:'...'}]
      const first = body.detail[0];
      const where = Array.isArray(first?.loc) ? first.loc.join(' → ') : '';
      return where ? `${first.msg} (${where})` : first?.msg || fallback;
    }
    return fallback;
  } catch {
    return fallback;
  }
}

/**
 * Guess a filename and MIME type from a local image URI.
 *
 * The backend rejects anything that is not an image content type, so this has
 * to be right. Expo returns URIs like
 * file:///.../ImagePicker/abcd-1234.jpeg
 */
function describeImage(uri, fallbackMime) {
  const clean = String(uri).split('?')[0];
  let name = clean.split('/').pop() || 'photo.jpg';
  const ext = (name.includes('.') ? name.split('.').pop() : '').toLowerCase();

  const types = {
    jpg: 'image/jpeg',
    jpeg: 'image/jpeg',
    png: 'image/png',
    webp: 'image/webp',
    heic: 'image/heic',
  };

  const type = types[ext] || fallbackMime || 'image/jpeg';

  // Some Android gallery URIs have no extension at all. The backend checks the
  // content type rather than the name, but a sensible name keeps logs readable.
  if (!ext) {
    const guessed = type.split('/')[1] === 'jpeg' ? 'jpg' : type.split('/')[1];
    name = `${name}.${guessed}`;
  }

  return { name, type };
}

/**
 * POST a multipart form with XMLHttpRequest.
 *
 * Resolves with { status, text } for ANY HTTP status — a 4xx is a real reply,
 * not a transport failure, so the caller decides what it means. Rejects only
 * when the request never completed.
 */
function postForm(url, formData, timeoutMs = REQUEST_TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();

    xhr.open('POST', url);
    xhr.timeout = timeoutMs;
    xhr.setRequestHeader('Accept', 'application/json');
    // Content-Type is deliberately NOT set. XMLHttpRequest must generate it
    // itself so it can include the multipart boundary. Setting it by hand is
    // the classic cause of a 422 on a file upload.

    xhr.onload = () => resolve({ status: xhr.status, text: xhr.responseText });

    xhr.onerror = () =>
      reject(new ApiError('Cannot reach the server.', {
        kind: 'network',
        hint: NETWORK_HINT,
      }));

    xhr.ontimeout = () =>
      reject(new ApiError('The server took too long to respond.', {
        kind: 'timeout',
        hint:
          'The first analysis after starting the server is slow because it ' +
          'loads the models. Wait a moment and try again.',
      }));

    xhr.send(formData);
  });
}

/**
 * Upload one photograph and get the full cascade result.
 *
 * `asset` may be the Expo ImagePicker asset ({ uri, mimeType, fileName }) or a
 * plain uri string.
 *
 * Returns the `result` object from the API:
 *   { disease, confident, confidence, probabilities,
 *     severity, severity_confidence, severity_probabilities,
 *     explanation, treatment, ... }
 *
 * `disease` is "unidentified" when confidence is below the threshold — check
 * that in the screen; it is not an error.
 */
async function buildImageForm(uri, name, type) {
  const form = new FormData();

  if (Platform.OS === 'web') {
    // Web FormData needs a real Blob. The picker gives a blob: or data: URL,
    // and fetching it back is the standard way to turn that into a Blob.
    let blob;
    try {
      const local = await fetch(uri);
      blob = await local.blob();
    } catch {
      throw new ApiError('Could not read the selected image.', {
        kind: 'image',
        hint: 'Pick the photo again, or try a different file.',
      });
    }
    // The third argument is the filename; without it browsers send "blob".
    form.append('image', blob, name);
    return form;
  }

  // Native (Expo Go / a built app): FormData streams the file from this shape.
  form.append('image', { uri, name, type });
  return form;
}

export async function detectDisease(asset) {
  const uri = typeof asset === 'string' ? asset : asset?.uri;
  if (!uri) {
    throw new ApiError('No image selected.', { kind: 'image' });
  }

  const described = describeImage(uri, typeof asset === 'object' ? asset?.mimeType : null);
  const name =
    (typeof asset === 'object' && asset?.fileName) || described.name;

  const form = await buildImageForm(uri, name, described.type);

  const { status, text } = await postForm(
    `${DISEASE_API}/detect?threshold=${CONFIDENCE_THRESHOLD}`,
    form
  );

  if (status === 503) {
    throw new ApiError(
      detailFromText(text, 'The prediction models are not available.'),
      {
        kind: 'models',
        status,
        hint:
          'The trained model files are missing on the server. Check that ' +
          'ml-models/disease_detection/models/ contains disease_model.keras ' +
          'and class_names.json.',
      }
    );
  }

  if (status === 400) {
    throw new ApiError(
      detailFromText(text, 'That file could not be read as a photograph.'),
      { kind: 'image', status, hint: 'Choose a JPEG or PNG photo.' }
    );
  }

  if (status === 422) {
    // The upload reached the server but the file field was not readable.
    throw new ApiError(
      detailFromText(text, 'The server could not read the uploaded file.'),
      {
        kind: 'image',
        status,
        hint:
          'The photo did not upload in a form the server could read. Try ' +
          'picking a different image from your gallery.',
      }
    );
  }

  if (status < 200 || status >= 300) {
    throw new ApiError(
      detailFromText(text, `Server error (HTTP ${status}).`),
      { kind: 'server', status }
    );
  }

  let payload;
  try {
    payload = JSON.parse(text);
  } catch {
    throw new ApiError('The server sent a response the app could not read.', {
      kind: 'server',
      status,
    });
  }

  if (!payload?.result) {
    throw new ApiError('The server response was missing the analysis result.', {
      kind: 'server',
      status,
    });
  }

  return payload.result;
}

/* -------------------------------------------------------------------------- */
/* GET requests — plain fetch is fine here, there is no body to encode.        */
/* -------------------------------------------------------------------------- */

async function getJson(url, timeoutMs = 15000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      headers: { Accept: 'application/json' },
      signal: controller.signal,
    });
    const text = await response.text();
    if (!response.ok) {
      throw new ApiError(
        detailFromText(text, `Server error (HTTP ${response.status}).`),
        { kind: 'server', status: response.status }
      );
    }
    return JSON.parse(text);
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err.name === 'AbortError') {
      throw new ApiError('The server took too long to respond.', { kind: 'timeout' });
    }
    throw new ApiError('Cannot reach the server.', {
      kind: 'network',
      hint: NETWORK_HINT,
    });
  } finally {
    clearTimeout(timer);
  }
}

/** Ask the backend whether its models are loaded. */
export async function checkStatus() {
  return getJson(`${DISEASE_API}/status`);
}

/** Treatment lookup without running a model. */
export async function getTreatment(disease, severity) {
  const query = severity ? `?severity=${encodeURIComponent(severity)}` : '';
  const body = await getJson(
    `${DISEASE_API}/treatments/${encodeURIComponent(disease)}${query}`
  );
  return body.treatment;
}
