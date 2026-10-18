/**
 * Grower cross logbook — API client.
 *
 * The compatibility engine answers from the RHS register, which lists only
 * crosses that succeeded. This talks to the half that collects what the
 * grower actually attempted, failures included — the denominator the
 * register structurally cannot hold.
 *
 * Nothing here predicts anything. It is a record.
 */
import BASE_URL from '../config/backend';

const PREFIX = '/api/v1/pollination/log';

/** One place to turn a failed response into a message worth reading. */
const unwrap = async (response, what) => {
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(
      typeof body.detail === 'string' ? body.detail : `Could not ${what}`
    );
  }
  return response.json();
};

/* A network failure and a server error look identical to the caller unless
   the address being dialled is named. The grower will be standing in a
   greenhouse when this fails, so it has to say what to check. */
const reachable = (error) => {
  if (error.message === 'Network request failed') {
    const e = new Error(
      `Could not reach the server at ${BASE_URL}. Check the backend is `
      + 'running and this phone is on the same network.'
    );
    e.baseUrl = BASE_URL;
    return e;
  }
  return error;
};

/** The stage pipeline and exit vocabulary, so the app never hardcodes them. */
export const getLogReference = async () => {
  try {
    return await unwrap(await fetch(`${BASE_URL}${PREFIX}/reference`), 'load the stages');
  } catch (error) {
    throw reachable(error);
  }
};

/**
 * Upload one parent photograph; returns the id the record will carry.
 *
 * Photos are stored server-side rather than inside the record. A logbook
 * entry is a few hundred bytes and should stay that way, and these two
 * photographs are taken again for every cross, for years.
 */
export const uploadLogPhoto = async (uri) => {
  const form = new FormData();
  const name = uri.split('/').pop() || 'photo.jpg';
  const ext = (name.split('.').pop() || 'jpg').toLowerCase();
  form.append('image', {
    uri,
    name,
    type: ext === 'png' ? 'image/png' : 'image/jpeg',
  });

  try {
    const response = await fetch(`${BASE_URL}${PREFIX}/photo`, {
      method: 'POST',
      body: form,
      // Content-Type is left unset on purpose: fetch sets it with the
      // multipart boundary, and setting it by hand breaks the upload.
    });
    const data = await unwrap(response, 'upload the photo');
    return data.photoId;
  } catch (error) {
    throw reachable(error);
  }
};

/** Absolute URL for a stored photo id, for <Image source={{ uri }} />. */
export const logPhotoUrl = (photoId) =>
  photoId ? `${BASE_URL}${PREFIX}/photo/${photoId}` : null;

/**
 * Register one plant.
 *
 * `name` is optional on purpose. Half the plants in a working collection have
 * a lost or unreadable tag, and a logbook that refuses them is one the grower
 * stops using. An unnamed plant gets an id it can be labelled with instead.
 */
export const registerPlant = async ({ name = '', photo = '', genus = '', location = '' }) => {
  const form = new FormData();
  form.append('name', name);
  form.append('photo', photo);
  form.append('genus', genus);
  form.append('location', location);

  try {
    const response = await fetch(`${BASE_URL}${PREFIX}/plants`, {
      method: 'POST',
      body: form,
    });
    const data = await unwrap(response, 'register the plant');
    return data.plant;
  } catch (error) {
    throw reachable(error);
  }
};

export const getPlants = async () => {
  try {
    const data = await unwrap(await fetch(`${BASE_URL}${PREFIX}/plants`), 'load plants');
    return data.plants || [];
  } catch (error) {
    throw reachable(error);
  }
};

/**
 * Record one attempted cross. Pod parent first, never sorted.
 *
 * The health readings travel as snapshots of the day the pollinia were moved.
 * A plant re-assessed six months later must not rewrite what was true at
 * pollination.
 */
export const logCross = async (payload) => {
  try {
    const response = await fetch(`${BASE_URL}${PREFIX}/crosses`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await unwrap(response, 'log the cross');
    return data.cross;
  } catch (error) {
    throw reachable(error);
  }
};

export const getCrosses = async () => {
  try {
    const data = await unwrap(await fetch(`${BASE_URL}${PREFIX}/crosses`), 'load the logbook');
    return data.crosses || [];
  } catch (error) {
    throw reachable(error);
  }
};

/**
 * Advance a cross, or close it at the gate it failed.
 *
 * Pass either `stage` or `outcome`, not both. Which gate it stopped at is the
 * whole signal: no pod set is usually technique, an aborted capsule is
 * usually the pod parent's condition, and an empty capsule is where genetic
 * incompatibility actually shows.
 */
export const updateCrossStage = async (crossId, { stage = '', outcome = '', note = '' }) => {
  try {
    const response = await fetch(`${BASE_URL}${PREFIX}/crosses/${crossId}/stage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stage, outcome, note }),
    });
    const data = await unwrap(response, 'update the cross');
    return data.cross;
  } catch (error) {
    throw reachable(error);
  }
};

/** Counts per gate, with denominators. Rates only once there are enough. */
export const getLogStats = async () => {
  try {
    return await unwrap(await fetch(`${BASE_URL}${PREFIX}/stats`), 'load the counts');
  } catch (error) {
    throw reachable(error);
  }
};

/**
 * Remove a record.
 *
 * Needed for the test entries and duplicates anyone makes while learning the
 * app. It is also the one call here that can undo the point of the logbook:
 * delete every cross that failed and what is left is a book of successes,
 * which is the exact bias the RHS register already has. The screen asks a
 * differently worded question before removing a recorded failure.
 */
export const deleteCross = async (crossId) => {
  try {
    const response = await fetch(`${BASE_URL}${PREFIX}/crosses/${crossId}`, {
      method: 'DELETE',
    });
    return await unwrap(response, 'remove the record');
  } catch (error) {
    throw reachable(error);
  }
};

/**
 * The two lists behind the Varieties tab.
 *
 * `mine` is what this grower has — the collection shipped with the project
 * plus every plant registered through the logbook, each with a photograph
 * where one exists. `register` is what the knowledge base has evidence for,
 * names only.
 *
 * They are kept apart because they answer different questions, and because
 * the second doubles as an honest statement of coverage: a grower can see
 * exactly how much the register knows before relying on it.
 */
export const getVarieties = async () => {
  try {
    return await unwrap(
      await fetch(`${BASE_URL}/api/v1/pollination/varieties`),
      'load the varieties'
    );
  } catch (error) {
    throw reachable(error);
  }
};

/** Absolute URL for a plant photograph, for <Image source={{ uri }} />. */
export const varietyPhotoUrl = (photo) =>
  photo ? `${BASE_URL}/api/v1/pollination/varieties/photo/${photo}` : null;
