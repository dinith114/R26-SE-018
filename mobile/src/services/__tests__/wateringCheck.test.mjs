/**
 * The "How watering times were checked" arithmetic, proven without a device.
 *
 * Run: cd mobile && node --test src/services/__tests__/
 *
 * Loaded from source through a data: URI, for the same reason as
 * placementFlow.test.mjs: the app has no "type": "module", and evaluating the
 * real file keeps this a test of the shipped code.
 *
 * The validation fixture is the SHIPPED backend/app/data/watering_validation.json,
 * so a change to what the script writes is a change these tests see.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'wateringCheck.js'), 'utf8');
const wc = await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));

const VALIDATION = JSON.parse(readFileSync(
  join(here, '..', '..', '..', '..', 'backend', 'app', 'data', 'watering_validation.json'), 'utf8'));

/* Shaped exactly as shadehouse_check.compare() returns it (enough: true), with
   the route's wrapper. Three byHour rows are enough to test runs and gaps. */
const CHECK = {
  status: 'success', houseId: 'H1',
  location: { latitude: 6.914174, longitude: 79.972934, source: 'farm settings' },
  sinceMs: null,
  hours: 901, sectionHours: 3743, sections: ['S1', 'S10', 'S2'],
  from: '2026-08-20T16:00Z', to: '2026-09-27T14:00Z',
  outdoorSource: {
    source: 'mixed', note: 'ERA5 archive for the older days ...',
    latitude: 6.914174, longitude: 79.972934,
    parts: [{ api: 'archive', from: '2026-09-26', to: '2026-09-28', hours: 72 },
            { api: 'forecast', from: '2026-09-29', to: '2026-10-05', hours: 168 }],
  },
  assumed: { warming: 3.5, humidityLift: 7.0, transmission: 0.45 },
  tolerance: { warming: 1.0, humidityLift: 4.0, transmission: 0.10 },
  labels: { warming: 'Day warming at full sun', humidityLift: 'Humidity lift',
            transmission: 'Light transmission' },
  units: { warming: 'C', humidityLift: '%', transmission: 'fraction' },
  excluded: {
    S1: { seeded: 96, badClock: 0, beforeSince: 0, temperature: 2, humidity: 2,
          light: 990, lightAtCeiling: 0 },
    S2: { seeded: 96, badClock: 1, beforeSince: 0, temperature: 0, humidity: 0,
          light: 5, lightAtCeiling: 3 },
  },
  enough: true,
  measured: { warming: 3.85, humidityLift: -9.81, transmission: 0.094 },
  gap: { warming: 0.35, humidityLift: -16.81, transmission: -0.356 },
  verdict: { warming: 'within tolerance', humidityLift: 'out of tolerance',
             transmission: 'not enough data: no bright hours (outdoor radiation above 100 W/m2) with a valid light reading' },
  hoursUsed: { warming: 1272, humidityLift: 2781, transmission: 0 },
  overall: { holds: false, checked: ['warming', 'humidityLift'], unchecked: ['transmission'],
             suggested: {}, text: 'At least one constant is out of tolerance: humidity lift.' },
  perSection: {
    S10: { hours: 5, measured: { warming: null, humidityLift: null, transmission: null },
           verdict: { warming: 'not enough data: 5 overlapping hours, need 12' } },
    S2: { hours: 400, measured: { warming: 5.22, humidityLift: -2.41, transmission: 0.005 },
          verdict: { warming: 'out of tolerance', humidityLift: 'within tolerance',
                     transmission: 'out of tolerance' } },
    S1: { hours: 901, measured: { warming: 5.67, humidityLift: -14.2, transmission: 0.147 },
          verdict: { warming: 'out of tolerance', humidityLift: 'out of tolerance',
                     transmission: 'out of tolerance' } },
  },
  estimateError: {
    temperature: { hours: 3700, outdoorPlusAssumed: 2.35, outdoorAsIs: 2.64 },
    humidity: { hours: 3700, outdoorPlusAssumed: 15.83, outdoorAsIs: 11.14 },
  },
  // Deliberately out of order: the chart sorts by the row's own farm time.
  byHour: [
    { hourUtc: 20, localTime: '01:30', n: 4, indoorTemp: 24.5, indoorRh: 90,
      outdoorTemp: 24.0, outdoorRh: 92, assumedTemp: 24.0, assumedRh: 99 },
    { hourUtc: 19, localTime: '00:30', n: 4, indoorTemp: 25.0, indoorRh: 88,
      outdoorTemp: 24.4, outdoorRh: 91, assumedTemp: 24.4, assumedRh: 98 },
    { hourUtc: 21, localTime: '02:30', n: 0, indoorTemp: null, indoorRh: null,
      outdoorTemp: null, outdoorRh: null, assumedTemp: null, assumedRh: null },
    { hourUtc: 22, localTime: '03:30', n: 3, indoorTemp: 23.9, indoorRh: 91,
      outdoorTemp: 23.5, outdoorRh: 93, assumedTemp: 23.5, assumedRh: 99 },
    // An hour missing altogether (04:30) must also break the line.
    { hourUtc: 0, localTime: '05:30', n: 2, indoorTemp: 24.1, indoorRh: 92,
      outdoorTemp: 23.6, outdoorRh: 94, assumedTemp: 23.6, assumedRh: 99 },
  ],
};

test('numbers print without Intl, and a missing one prints as a dash', () => {
  assert.equal(wc.int(58436), '58,436');
  assert.equal(wc.int(2364), '2,364');
  assert.equal(wc.int(999), '999');
  assert.equal(wc.int(null), '—');
  assert.equal(wc.num(3.5, 2), '3.5');
  assert.equal(wc.num(3.849, 2), '3.85');
  assert.equal(wc.num(-0.001, 2), '0');            // never "-0"
  assert.equal(wc.num(NaN), '—');
  assert.equal(wc.num('8.4'), '—');                // a string is not a number
});

test('only text or a number ever reaches the screen as text', () => {
  assert.equal(wc.str('2017-2024'), '2017-2024');
  assert.equal(wc.str(58436), '58436');
  assert.equal(wc.str({ years: 1 }), '—');        // an object would be a render error
  assert.equal(wc.str(['a']), '—');
  assert.equal(wc.str('   '), '—');
  assert.equal(wc.str(undefined, ''), '');
  assert.equal(wc.siteName('nuwara-eliya'), 'Nuwara Eliya');
  assert.equal(wc.siteName('galle'), 'Galle');
  assert.equal(wc.siteName(7), '—');
  assert.deepEqual(VALIDATION.dataset.sites.map(wc.siteName).every((s) => s !== '—'), true);
});

test('splits come off the shipped validation file, out-of-time flagged', () => {
  const rows = wc.splitRows(VALIDATION);
  assert.equal(rows.length, VALIDATION.splits.length);
  assert.deepEqual(rows.map((r) => r.key), VALIDATION.splits.map((s) => s.name));
  const oot = wc.headlineSplit(VALIDATION);
  const raw = VALIDATION.splits.find((s) => s.name === 'OUT-OF-TIME');
  assert.ok(oot && oot.outOfTime);
  assert.equal(oot.name, 'Out-of-time');
  // The display name comes from the file's own label, not from this module.
  assert.equal(rows[0].name.toUpperCase(), VALIDATION.splits[0].label.split(' (')[0]);
  assert.equal(oot.hourMaeMin, raw.hourMaeMin);    // read, not restated
  assert.equal(oot.testYears, raw.testYears);
  assert.equal(rows.filter((r) => r.outOfTime).length, 1);
});

test('a validation file missing fields gives dashes, not a crash', () => {
  assert.deepEqual(wc.splitRows(null), []);
  assert.deepEqual(wc.splitRows({ splits: 'nope' }), []);
  assert.equal(wc.headlineSplit({}), null);
  const [r] = wc.splitRows({ splits: [{ name: 'MYSTERY', hourMaeMin: '8' }, null] });
  assert.equal(r.name, 'Mystery');
  assert.equal(wc.splitName({ name: 5, label: {} }), '—');
  assert.equal(r.hourMaeMin, null);
  assert.equal(r.outOfTime, false);
});

test('verdict strings sort into the four pills', () => {
  assert.equal(wc.verdictKind('within tolerance'), 'ok');
  assert.equal(wc.verdictKind('out of tolerance'), 'bad');
  assert.equal(wc.verdictKind('not enough data: no sunny hours'), 'unmeasured');
  assert.equal(wc.verdictKind(undefined), 'unknown');
  assert.equal(wc.verdictKind('maybe'), 'unknown');
});

test('values are shown in the unit the server named', () => {
  assert.equal(wc.valueText(3.85, 'C'), '3.85 °C');
  assert.equal(wc.valueText(0.35, 'C', true), '+0.35 °C');
  assert.equal(wc.valueText(-9.81, '%'), '-9.8 %');
  assert.equal(wc.valueText(0.45, 'fraction'), '45 %');     // a fraction, as a percentage
  assert.equal(wc.valueText(0.094, 'fraction'), '9.4 %');
  assert.equal(wc.valueText(null, 'C'), '—');
});

test('quantity rows carry assumed, measured, tolerance and the reason', () => {
  const rows = wc.quantityRows(CHECK);
  assert.deepEqual(rows.map((r) => r.key), ['warming', 'humidityLift', 'transmission']);
  const [w, h, t] = rows;
  assert.equal(w.label, 'Day warming at full sun');
  assert.equal(w.assumed, '3.5 °C');
  assert.equal(w.measured, '3.85 °C');
  assert.equal(w.tolerance, '±1 °C');
  assert.equal(w.hours, 1272);
  assert.equal(w.kind, 'ok');
  assert.equal(w.reason, null);
  assert.equal(h.kind, 'bad');
  assert.equal(h.gap, '-16.8 %');
  assert.equal(t.kind, 'unmeasured');
  assert.match(t.reason, /^not enough data/);
  assert.equal(t.tolerance, '±10 %');
  assert.deepEqual(wc.verdictGroups(CHECK), {
    ok: ['Day warming at full sun'], bad: ['Humidity lift'], unmeasured: ['Light transmission'],
  });
});

test('an empty check gives three unknown rows instead of throwing', () => {
  const rows = wc.quantityRows(undefined);
  assert.equal(rows.length, 3);
  assert.ok(rows.every((r) => r.kind === 'unknown' && r.measured === '—' && r.hours === null));
  assert.deepEqual(wc.sectionRows(null), []);
  assert.deepEqual(wc.sourceParts({ outdoorSource: null }), []);
  const e = wc.excludedTotals({});
  assert.equal(e.seeded, 0);
});

test('sections are listed in natural order, each with its own verdicts', () => {
  const rows = wc.sectionRows(CHECK);
  assert.deepEqual(rows.map((r) => r.sid), ['S1', 'S2', 'S10']);
  assert.equal(rows[0].warming.text, '5.67 °C');
  assert.equal(rows[1].humidityLift.kind, 'ok');
  assert.equal(rows[2].warming.text, '—');
  assert.equal(rows[2].warming.kind, 'unmeasured');
});

test('exclusions are summed over sections', () => {
  const e = wc.excludedTotals(CHECK);
  assert.equal(e.seeded, 192);
  assert.equal(e.badClock, 1);
  assert.equal(e.light, 995);
  assert.equal(e.lightAtCeiling, 3);
});

test('the outdoor source says which API covered which days', () => {
  const parts = wc.sourceParts(CHECK);
  assert.deepEqual(parts.map((p) => p.api), ['ERA5 archive', 'Forecast model']);
  assert.equal(parts[0].era5, true);
  assert.equal(parts[1].era5, false);
  assert.equal(parts[0].from, '26 Sep');
  assert.equal(parts[1].hours, 168);
  assert.equal(wc.dayText('2026-13-01'), '—');
  assert.equal(wc.dayText('2025-01-01', true), '1 Jan 2025');
  assert.equal(wc.sentence('one row per site and day'), 'One row per site and day.');
  assert.equal(wc.sentence('Done.'), 'Done.');
  assert.equal(wc.sentence(null), '');
});

test('the period stamps parse as UTC', () => {
  assert.equal(wc.isoHourMs('2026-08-20T16:00Z'), Date.UTC(2026, 7, 20, 16, 0));
  assert.equal(wc.isoHourMs('2026-08-20 16:00'), null);
  assert.equal(wc.isoMs(VALIDATION.generatedAt), Date.parse(VALIDATION.generatedAt));
  assert.equal(wc.isoMs(undefined), null);
});

test('the 24-hour chart is in farm time and keeps gaps as gaps', () => {
  const c = wc.hourlyChart(CHECK, 'temperature');
  // 00:30, 01:30 | gap at 02:30 (n 0) | 03:30 | 04:30 absent | 05:30
  assert.deepEqual(c.indoor.map((run) => run.map((p) => p.x)), [[0.5, 1.5], [3.5], [5.5]]);
  assert.deepEqual(c.indoor[0].map((p) => p.y), [25.0, 24.5]);
  assert.equal(c.assumed.length, 3);
  assert.equal(c.hoursWithIndoor, 4);
  assert.equal(c.nTotal, 13);
  assert.ok(c.yMin < 23.5 && c.yMax > 25.0);
  assert.equal(c.empty, false);
  const h = wc.hourlyChart(CHECK, 'humidity');
  assert.deepEqual(h.indoor[0].map((p) => p.y), [88, 90]);
  const none = wc.hourlyChart({ byHour: [{ localTime: '05:30', n: 0, indoorTemp: null }] });
  assert.equal(none.empty, true);
  assert.ok(Number.isFinite(none.yMin) && none.yMax > none.yMin);
  assert.equal(wc.localHour('24:00'), null);
  assert.equal(wc.clockTick(6), '06:00');
  assert.equal(wc.clockTick(24), '24:00');
});

test('the house is the node\'s own, then the first real one, never a guess', () => {
  const ov = { houses: [
    { houseId: 'H2', meta: { simulated: true } },
    { houseId: 'H1', meta: {} },
    { houseId: 'H3', meta: { simulated: true } },
  ] };
  assert.equal(wc.pickHouseId(ov, { assignedTo: 'H1/S1' }), 'H1');
  assert.equal(wc.pickHouseId(ov, { assignedTo: 'H3/S1' }), 'H1');   // simulated: skipped
  assert.equal(wc.pickHouseId(ov, null), 'H1');
  assert.equal(wc.pickHouseId({ houses: [{ houseId: 'H9', meta: { simulated: true } }] }), 'H9');
  assert.equal(wc.pickHouseId({ houses: [] }), null);
  assert.equal(wc.pickHouseId(undefined), null);
});

test('the read window is computed from now, and "all" sends nothing', () => {
  const now = Date.UTC(2026, 9, 10, 12, 0);
  assert.equal(wc.sinceMsFor('all', now), null);
  assert.equal(wc.sinceMsFor('1d', now), now - 86400000);
  assert.equal(wc.sinceMsFor('3d', now), now - 3 * 86400000);
  assert.equal(wc.sinceMsFor('nonsense', now), null);
});

test('a failed check says why, and what would fix it', () => {
  const e409 = Object.assign(new Error('Not enough data: 3 hours ...'), { status: 409 });
  const a = wc.checkFailure(e409, 'H1');
  assert.equal(a.kind, 'notyet');
  assert.equal(a.reason, 'Not enough data: 3 hours ...');      // the server's words
  assert.match(a.needed, /sensor node inside the shade house/);
  assert.equal(wc.checkFailure(Object.assign(new Error('x'), { status: 404 }), 'H1').kind, 'notyet');
  assert.equal(wc.checkFailure(Object.assign(new Error('x'), { status: 503 }), 'H1').kind, 'offline');
  assert.equal(wc.checkFailure(new Error('Network request failed'), 'H1').kind, 'error');
  assert.equal(wc.checkFailure(null, null).kind, 'nohouse');
  assert.equal(wc.checkFailure({ message: 42 }, 'H1').reason, 'The check could not be loaded.');
});
