/**
 * Finding the farm on a map: place search, "what is near this point", and
 * reading coordinates a farmer pasted. Used by components/LocationPicker.js.
 *
 * No imports and no React Native, so node --test can load it from source
 * (services/__tests__/places.test.mjs).
 *
 * Two search services, because neither is enough alone:
 *
 *   Photon (photon.komoot.io) searches OpenStreetMap. It knows Sri Lankan
 *   villages better: tested 19 Oct 2026 it found "Pilimathalawa" under its
 *   map spelling, Pilimatalawa, and put Kiribathgoda in Gampaha District.
 *   It also answers "what is near this point", which the map uses to say
 *   where the pin is in words.
 *
 *   Open-Meteo's geocoder (GeoNames data) is the fallback. It is the same
 *   company the outdoor forecast comes from, and on the same day it found
 *   nothing for "Pilimathalawa" and filed Kiribathgoda under Colombo, which is
 *   why it is second.
 *
 * Both are free with no key. Searches are limited to Sri Lanka: the forecast
 * is fetched in the Asia/Colombo timezone (backend forecast.py), so the
 * system only works there anyway.
 */

/** Sri Lanka with a small margin, as south/west/north/east degrees. */
export const LK_BOX = { south: 5.7, west: 79.4, north: 10.0, east: 82.1 };

export const inSriLanka = (lat, lon) =>
  Number.isFinite(lat) && Number.isFinite(lon)
  && lat >= LK_BOX.south && lat <= LK_BOX.north
  && lon >= LK_BOX.west && lon <= LK_BOX.east;

const PHOTON = 'https://photon.komoot.io';
const OPEN_METEO = 'https://geocoding-api.open-meteo.com/v1/search';

/* A road or a bus stop shares a town's name and is not where a farm is.
   "Peradeniya" returned four of these after the place itself. */
const SKIP_KEYS = new Set(['highway', 'public_transport', 'railway', 'route', 'boundary']);

/* How close to zoom for each kind of place. A town needs its surroundings in
   view to be recognised; a temple or a school is already a precise spot. */
const PLACE_KIND = {
  city:          { label: 'City',    zoom: 13 },
  town:          { label: 'Town',    zoom: 14 },
  village:       { label: 'Village', zoom: 15 },
  hamlet:        { label: 'Village', zoom: 15 },
  suburb:        { label: 'Area',    zoom: 15 },
  quarter:       { label: 'Area',    zoom: 15 },
  neighbourhood: { label: 'Area',    zoom: 15 },
  locality:      { label: 'Area',    zoom: 15 },
};

const sentence = (s) => {
  const t = String(s || '').replace(/_/g, ' ').trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : '';
};

const unique = (parts) =>
  parts.filter(Boolean).filter((v, i, a) => a.indexOf(v) === i);

async function fetchJson(url, { fetchImpl, timeoutMs = 8000 } = {}) {
  const doFetch = fetchImpl || fetch;
  const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timer = ctl ? setTimeout(() => ctl.abort(), timeoutMs) : null;
  try {
    const res = await doFetch(url, {
      headers: { Accept: 'application/json' },
      ...(ctl ? { signal: ctl.signal } : {}),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } finally {
    if (timer) clearTimeout(timer);
  }
}

/** One Photon feature as a search result, or null for a road, a stop or a bad point. */
export function fromPhoton(feature) {
  const p = feature?.properties || {};
  if (SKIP_KEYS.has(p.osm_key)) return null;
  const [lon, lat] = feature?.geometry?.coordinates || [];
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  const name = p.name || p.city || p.county;
  if (!name) return null;

  const place = p.osm_key === 'place' ? PLACE_KIND[p.osm_value] : null;
  // OpenStreetMap writes "yes" for an object with no particular kind; a result
  // labelled "Yes" (Kiribathgoda Jct., live, 19 Oct) reads as a bug.
  const kind = place ? place.label
    : sentence(p.osm_value && p.osm_value !== 'yes' ? p.osm_value : p.osm_key);
  // "Kiribathgoda, Gampaha District, Western Province", leaving out whatever
  // only repeats the name.
  const where = unique([p.city, p.county, p.state]).filter((v) => v !== name);
  return {
    name,
    detail: unique([kind, where.join(', ')]).join(' · '),
    latitude: lat,
    longitude: lon,
    zoom: place ? place.zoom : 17,
    isPlace: !!place,
  };
}

/** One Open-Meteo result in the same shape. */
export function fromOpenMeteo(r) {
  if (!r || !Number.isFinite(r.latitude) || !Number.isFinite(r.longitude) || !r.name) return null;
  return {
    name: r.name,
    detail: unique([r.admin2, r.admin1]).join(', '),
    latitude: r.latitude,
    longitude: r.longitude,
    zoom: 14,
    isPlace: true,
  };
}

/* Towns and villages first, then landmarks; one row per place. Two results
   with the same name less than about a kilometre apart are one place reached
   twice (the town and its bus stand), not two choices. */
export function tidyResults(list, max = 8) {
  const seen = new Set();
  const out = [];
  const ordered = [...list.filter((x) => x && x.isPlace), ...list.filter((x) => x && !x.isPlace)];
  for (const r of ordered) {
    const key = `${r.name.toLowerCase()}|${r.latitude.toFixed(2)}|${r.longitude.toFixed(2)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(r);
    if (out.length >= max) break;
  }
  return out;
}

/**
 * Places in Sri Lanka matching `query`, best first. Photon, then Open-Meteo if
 * Photon fails or finds nothing. Throws only when BOTH could not be reached,
 * so "no such place" ([]) and "no internet" (an Error) stay different answers.
 */
export async function searchPlaces(query, opts = {}) {
  const q = String(query || '').trim();
  if (q.length < 2) return [];

  let firstError = null;
  try {
    const url = `${PHOTON}/api/?q=${encodeURIComponent(q)}&limit=15&lang=en`
      + `&bbox=${LK_BOX.west},${LK_BOX.south},${LK_BOX.east},${LK_BOX.north}`;
    const j = await fetchJson(url, opts);
    const list = tidyResults((j.features || []).map(fromPhoton));
    if (list.length) return list;
  } catch (e) {
    firstError = e;
  }

  try {
    const url = `${OPEN_METEO}?name=${encodeURIComponent(q)}`
      + '&count=10&language=en&format=json&countryCode=LK';
    const j = await fetchJson(url, opts);
    return tidyResults((j.results || []).map(fromOpenMeteo));
  } catch (e) {
    if (firstError) {
      throw new Error('Place search could not be reached. Check the internet connection, or move the map instead.');
    }
    return [];      // Photon answered "nothing"; the fallback failing does not change that
  }
}

/**
 * A few words for where a point is, e.g. "Eriyagama, Kandy District", or null.
 *
 * The nearest OpenStreetMap object is often a school or a bus stop, so this
 * names the area that object is IN rather than the object itself.
 */
export async function placeNear(lat, lon, opts = {}) {
  const url = `${PHOTON}/reverse?lat=${Number(lat).toFixed(6)}&lon=${Number(lon).toFixed(6)}&lang=en&limit=1`;
  const j = await fetchJson(url, opts);
  const p = j?.features?.[0]?.properties;
  if (!p) return null;
  const area = p.city || p.locality || p.district || p.name;
  const words = unique([area, p.county]).join(', ');
  return words || null;
}

/* ── Typed or pasted coordinates ───────────────────────────────────────────── */

const NUM = '(-?\\d{1,3}(?:\\.\\d+)?)';

const dms = (deg, min, sec, hemi) => {
  const v = Number(deg) + Number(min) / 60 + Number(sec || 0) / 3600;
  return /[SW]/i.test(hemi) ? -v : v;
};

/**
 * Coordinates out of whatever the farmer pasted, or null.
 *
 * Accepts "7.2683, 80.5960" (what Google Maps copies when you press and hold
 * on a spot), "7.2683 80.5960", "7.2683° N, 80.5960° E", the degrees-minutes-
 * seconds form Google Maps shows under a place (7°16'05.9"N 80°35'45.6"E), and
 * a full Google Maps link. A shortened maps.app.goo.gl link holds no
 * coordinates and returns null.
 *
 * Returns { latitude, longitude, swapped }. `swapped` is true when the two
 * numbers were the wrong way round: longitude first is the usual mistake, and
 * "80.59, 7.26" is a valid point near the North Pole rather than an error, so
 * it is caught by asking which order lands in Sri Lanka.
 */
export function parseCoordinates(text) {
  let t = String(text || '').trim();
  if (!t) return null;
  try { t = decodeURIComponent(t); } catch (_) { /* keep it as typed */ }

  let lat = null;
  let lon = null;

  const d = t.match(/(\d{1,3})\s*°\s*(\d{1,2})\s*['′]\s*(\d{1,2}(?:\.\d+)?)?\s*(?:["″]|'')?\s*([NS])[\s,;]*(\d{1,3})\s*°\s*(\d{1,2})\s*['′]\s*(\d{1,2}(?:\.\d+)?)?\s*(?:["″]|'')?\s*([EW])/i);
  if (d) {
    lat = dms(d[1], d[2], d[3], d[4]);
    lon = dms(d[5], d[6], d[7], d[8]);
  } else {
    const patterns = [
      new RegExp(`!3d${NUM}!4d${NUM}`),                                   // a Google Maps place link: the pin
      new RegExp(`[?&](?:q|query|ll|destination|center)=${NUM}\\s*,\\s*${NUM}`), // ?q=7.26,80.59
      new RegExp(`/(?:search|place|dir)/${NUM},\\+?\\s*${NUM}`),          // .../search/7.26,+80.59
      new RegExp(`@${NUM},${NUM}`),                                        // a Google Maps link: the view
      new RegExp(`^${NUM}\\s*°?\\s*([NS])?\\s*[,;\\s]\\s*${NUM}\\s*°?\\s*([EW])?$`, 'i'), // plain numbers
    ];
    for (const re of patterns) {
      const m = t.match(re);
      if (!m) continue;
      if (m.length === 5) {                     // the plain form, with optional N/S and E/W
        lat = parseFloat(m[1]) * (/s/i.test(m[2] || '') ? -1 : 1);
        lon = parseFloat(m[3]) * (/w/i.test(m[4] || '') ? -1 : 1);
      } else {
        lat = parseFloat(m[1]);
        lon = parseFloat(m[2]);
      }
      break;
    }
  }

  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  if (!inSriLanka(lat, lon) && inSriLanka(lon, lat)) {
    return { latitude: lon, longitude: lat, swapped: true };
  }
  if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
  return { latitude: lat, longitude: lon, swapped: false };
}
