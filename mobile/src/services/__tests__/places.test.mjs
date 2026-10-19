/**
 * Finding the farm: pasted coordinates, search results and the fallback
 * between the two search services, proven without a phone or a network.
 * Loaded from source through a data: URI, as request.test.mjs explains.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'places.js'), 'utf8');
const {
  parseCoordinates, fromPhoton, fromOpenMeteo, tidyResults, searchPlaces, placeNear, inSriLanka,
} = await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));

const near = (a, b, eps = 1e-4) => assert.ok(Math.abs(a - b) < eps, `${a} is not ${b}`);

test('coordinates copied from Google Maps are read', () => {
  const p = parseCoordinates('7.2683, 80.5960');
  near(p.latitude, 7.2683); near(p.longitude, 80.596);
  assert.equal(p.swapped, false);
  const q = parseCoordinates('  7.2683 80.5960 ');
  near(q.latitude, 7.2683); near(q.longitude, 80.596);
});

test('longitude typed first is put the right way round, and says so', () => {
  const p = parseCoordinates('80.5960, 7.2683');
  near(p.latitude, 7.2683); near(p.longitude, 80.596);
  assert.equal(p.swapped, true);
});

test('degrees, minutes and seconds as Google Maps shows them', () => {
  const p = parseCoordinates('7°16\'05.9"N 80°35\'45.6"E');
  near(p.latitude, 7 + 16 / 60 + 5.9 / 3600);
  near(p.longitude, 80 + 35 / 60 + 45.6 / 3600);
});

test('degrees with N and E letters', () => {
  const p = parseCoordinates('7.2683° N, 80.5960° E');
  near(p.latitude, 7.2683); near(p.longitude, 80.596);
});

test('a Google Maps place link gives the PIN, not the view around it', () => {
  const url = 'https://www.google.com/maps/place/Peradeniya/@7.2690,80.5900,15z/'
    + 'data=!3m1!4b1!4m6!3m5!1s0x0:0x0!8m2!3d7.2683!4d80.5960';
  const p = parseCoordinates(url);
  near(p.latitude, 7.2683); near(p.longitude, 80.596);
});

test('other Google Maps link shapes', () => {
  for (const url of [
    'https://maps.google.com/?q=7.2683%2C80.5960',
    'https://www.google.com/maps/search/7.2683,+80.5960',
    'https://www.google.com/maps/@7.2683,80.5960,17z',
  ]) {
    const p = parseCoordinates(url);
    assert.ok(p, url);
    near(p.latitude, 7.2683); near(p.longitude, 80.596);
  }
});

test('things that are not coordinates are refused, not guessed at', () => {
  assert.equal(parseCoordinates(''), null);
  assert.equal(parseCoordinates('Peradeniya'), null);
  assert.equal(parseCoordinates('https://maps.app.goo.gl/AbCd123'), null);  // a short link holds no numbers
  assert.equal(parseCoordinates('95, 200'), null);
});

test('Sri Lanka box', () => {
  assert.equal(inSriLanka(7.2683, 80.596), true);
  assert.equal(inSriLanka(80.596, 7.2683), false);
  assert.equal(inSriLanka(51.5, -0.12), false);
});

const feature = (props, lat, lon) => ({ properties: props, geometry: { coordinates: [lon, lat] } });

test('a town from Photon reads as a town, in its district', () => {
  const r = fromPhoton(feature({ name: 'Pilimatalawa', osm_key: 'place', osm_value: 'town',
    county: 'Kandy District', state: 'Central Province' }, 7.266, 80.552));
  assert.equal(r.name, 'Pilimatalawa');
  assert.equal(r.detail, 'Town · Kandy District, Central Province');
  assert.equal(r.zoom, 14);
  assert.equal(r.isPlace, true);
});

test('a road or a bus stop with the same name is not offered', () => {
  assert.equal(fromPhoton(feature({ name: 'Peradeniya Road', osm_key: 'highway', osm_value: 'primary' }, 7.2, 80.6)), null);
  assert.equal(fromPhoton(feature({ name: 'Peradeniya', osm_key: 'public_transport', osm_value: 'stop' }, 7.2, 80.6)), null);
});

test('a landmark is offered, zoomed close, after the towns', () => {
  const temple = fromPhoton(feature({ name: 'Sudharshanaramaya', osm_key: 'amenity',
    osm_value: 'place_of_worship', city: 'Kiribathgoda', county: 'Gampaha District' }, 6.983, 79.930));
  assert.equal(temple.detail, 'Place of worship · Kiribathgoda, Gampaha District');
  assert.equal(temple.zoom, 17);
  const town = fromPhoton(feature({ name: 'Kiribathgoda', osm_key: 'place', osm_value: 'town',
    county: 'Gampaha District' }, 6.978, 79.927));
  const list = tidyResults([temple, town]);
  assert.deepEqual(list.map((x) => x.name), ['Kiribathgoda', 'Sudharshanaramaya']);
});

test('an object OpenStreetMap only marks "yes" is named by its key, not "Yes"', () => {
  const r = fromPhoton(feature({ name: 'Kiribathgoda Jct.', osm_key: 'junction', osm_value: 'yes',
    city: 'Kiribathgoda', county: 'Gampaha District' }, 6.978, 79.927));
  assert.equal(r.detail, 'Junction · Kiribathgoda, Gampaha District');
});

test('one place reached twice is one row', () => {
  const a = fromOpenMeteo({ name: 'Ratmalana', latitude: 6.8170, longitude: 79.8670, admin2: 'Colombo District' });
  const b = fromOpenMeteo({ name: 'Ratmalana', latitude: 6.8174, longitude: 79.8672, admin2: 'Colombo District' });
  const c = fromOpenMeteo({ name: 'Ratmalana', latitude: 7.5000, longitude: 80.3000, admin2: 'Kurunegala District' });
  assert.equal(tidyResults([a, b, c]).length, 2);
});

/* A fetch that answers per host, and records what was asked. */
const fakeFetch = (answers, asked = []) => async (url) => {
  asked.push(url);
  const host = new URL(url).host;
  const a = answers[host];
  if (a instanceof Error) throw a;
  if (!a) throw new Error('unexpected host ' + host);
  return { ok: true, status: 200, json: async () => a };
};

test('Photon answers first and is limited to Sri Lanka', async () => {
  const asked = [];
  const list = await searchPlaces('Kandy', { fetchImpl: fakeFetch({
    'photon.komoot.io': { features: [feature({ name: 'Kandy', osm_key: 'place', osm_value: 'city',
      county: 'Kandy District', state: 'Central Province' }, 7.29, 80.63)] },
  }, asked) });
  assert.equal(list.length, 1);
  assert.equal(list[0].name, 'Kandy');
  assert.match(asked[0], /bbox=79\.4,5\.7,82\.1,10/);
  assert.equal(asked.length, 1);
});

test('when Photon is unreachable, Open-Meteo answers', async () => {
  const list = await searchPlaces('Kadawatha', { fetchImpl: fakeFetch({
    'photon.komoot.io': new Error('network down'),
    'geocoding-api.open-meteo.com': { results: [{ name: 'Kadawatha', latitude: 7.001, longitude: 79.95,
      admin2: 'Gampaha District', admin1: 'Western Province' }] },
  }) });
  assert.equal(list[0].name, 'Kadawatha');
  assert.equal(list[0].detail, 'Gampaha District, Western Province');
});

test('when Photon finds nothing, Open-Meteo is asked too', async () => {
  const asked = [];
  const list = await searchPlaces('Nowhere', { fetchImpl: fakeFetch({
    'photon.komoot.io': { features: [] },
    'geocoding-api.open-meteo.com': {},
  }, asked) });
  assert.deepEqual(list, []);
  assert.equal(asked.length, 2);
  assert.match(asked[1], /countryCode=LK/);
});

test('no internet is an error, not "no such place"', async () => {
  await assert.rejects(
    searchPlaces('Kandy', { fetchImpl: fakeFetch({
      'photon.komoot.io': new Error('down'), 'geocoding-api.open-meteo.com': new Error('down') }) }),
    /could not be reached/);
});

test('one letter is not searched', async () => {
  const list = await searchPlaces('K', { fetchImpl: () => { throw new Error('should not be called'); } });
  assert.deepEqual(list, []);
});

test('the place under the pin is named by its area, not the nearest school', async () => {
  const words = await placeNear(7.262, 80.584, { fetchImpl: fakeFetch({
    'photon.komoot.io': { features: [{ properties: { name: 'Peradeniya Central College',
      osm_value: 'school', city: 'Eriyagama', district: 'Uda Eriyagama West', county: 'Kandy District' } }] },
  }) });
  assert.equal(words, 'Eriyagama, Kandy District');
});
