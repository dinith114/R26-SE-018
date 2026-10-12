/**
 * The placement-flow chart arithmetic, proven without a device.
 *
 * Run: cd mobile && node --test src/services/__tests__/
 *
 * Loaded from source through a data: URI, for the same reason as
 * request.test.mjs: the app has no "type": "module", and evaluating the real
 * file keeps this a test of the shipped code.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'placementFlow.js'), 'utf8');
const pf = await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));

test('ticks are round numbers covering the range', () => {
  assert.deepEqual(pf.niceTicks(0, 1, 4), [0, 0.25, 0.5, 0.75, 1]);
  assert.deepEqual(pf.niceTicks(0, 10, 5), [0, 2, 4, 6, 8, 10]);
  assert.deepEqual(pf.niceTicks(3, 3), [3]);
  assert.deepEqual(pf.niceTicks(NaN, 3), []);
});

test('a segment is centred between its ends and as long as the gap', () => {
  const s = pf.segment(0, 0, 30, 40, 2);
  assert.equal(s.width, 50);
  assert.equal(s.left + s.width / 2, 15);   // centre x
  assert.equal(s.top + s.height / 2, 20);   // centre y
  assert.ok(Math.abs(s.angle - Math.atan2(40, 30)) < 1e-12);
});

test('the y scale is flipped so a larger value sits higher', () => {
  const y = pf.scaler([0, 10], [100, 0]);
  assert.equal(y(0), 100);
  assert.equal(y(10), 0);
});

const ANALYSIS = {
  coverage: {
    pairs: [
      { a: 'S1', b: 'S2', distance: 2, temperature: 0.21, humidity: 0.9, vpd: 0.03 },
      { a: 'S1', b: 'S3', distance: 4, temperature: 0.42, humidity: 1.7, vpd: 0.06 },
      { a: 'S2', b: 'S3', distance: 2, temperature: 0.2, humidity: 0.8, vpd: 0.03 },
    ],
    fields: {
      temperature: { tolerance: 0.5, unit: '°C', slope: 0.1, intercept: 0.01, r2: 0.99,
                     radius: 4.9, status: 'extrapolated' },
      humidity: { tolerance: 2, unit: '%', status: 'too-few-pairs', radius: null },
    },
  },
  placement: {
    recommended: 4,
    periods: { choose: 30, validate: 10, test: 27 },
    rows: [
      { sensors: 2, selected: 'grid', methods: {
        pysensors: { normalized: 0.9 }, grid: { normalized: 0.7 },
        kriging_greedy: { normalized: 0.8 }, random: { normalized: 1.1 },
        best: { normalized: 0.6 }, worst: { normalized: 1.6 } } },
      { sensors: 3, selected: 'pysensors', methods: {
        pysensors: { normalized: 0.4 }, grid: { normalized: 0.5 },
        kriging_greedy: { normalized: 0.6 }, random: { normalized: 0.8 } } },
    ],
  },
  buckets: { minutes: 10, common: 67, fit: 40, test: 27 },
  series: {
    hourMs: [3600000 * 10, 3600000 * 11, 3600000 * 13],
    nodes: { S1: { temperature: [25, 26, 27] }, S2: { temperature: [25.5, null, 28] } },
  },
  raw: {
    S1: { records: 100, first: 1, last: 2,
          rejected: { temperature: { failed: 3, missing: 0, implausible: 1 },
                      humidity: { failed: 3, missing: 0, implausible: 0 } },
          valid: { temperature: 96, light: 0 } },
  },
};

test('coverage chart reads every pair and the fit, and invents nothing', () => {
  const c = pf.coverageChart(ANALYSIS, 'temperature');
  assert.equal(c.points.length, 3);
  assert.deepEqual(c.points[1], { x: 4, y: 0.42, label: 'S1–S3' });
  assert.equal(c.radius, 4.9);
  assert.equal(c.tolerance, 0.5);
  assert.ok(c.xMax > 4.9, 'the radius marker must be inside the chart');
  assert.ok(Math.abs(c.line.y0 - 0.01) < 1e-12);
  // A field with no fit draws no line and no radius.
  const h = pf.coverageChart(ANALYSIS, 'humidity');
  assert.equal(h.line, null);
  assert.equal(h.radius, null);
  assert.equal(h.status, 'too-few-pairs');
});

test('placement chart: one line per method, range only where every subset was tried', () => {
  const p = pf.placementChart(ANALYSIS);
  assert.deepEqual(p.ks, [2, 3]);
  assert.deepEqual(p.lines.grid, [{ x: 2, y: 0.7 }, { x: 3, y: 0.5 }]);
  assert.deepEqual(p.range, [{ x: 2, lo: 0.6, hi: 1.6 }]);
  assert.deepEqual(p.selected.map((s) => s.method), ['grid', 'pysensors']);
  assert.equal(p.recommended, 4);
  assert.ok(p.yMax >= 1.6);
});

test('series keeps gaps as gaps and measures x in hours', () => {
  const s = pf.seriesChart(ANALYSIS, 'temperature');
  assert.deepEqual(s.lines.S1.map((q) => q.x), [0, 1, 3]);
  assert.deepEqual(s.lines.S2.map((q) => q.y), [25.5, 28]);   // the null is not drawn
  assert.ok(s.yMin < 25 && s.yMax > 28);
});

test('period split adds up to the aligned periods', () => {
  const sp = pf.periodSplit(ANALYSIS);
  assert.deepEqual(sp.parts.map((q) => q.n), [30, 10, 27]);
  assert.equal(sp.parts[2].hours, 4.5);
});

test('cleaning rows add temperature and humidity rejections', () => {
  const [r] = pf.cleaningRows(ANALYSIS);
  assert.equal(r.failed, 6);
  assert.equal(r.implausible, 1);
  assert.equal(r.validLight, 0);
});

test('farm time is UTC+5:30 whatever the phone is set to', () => {
  // 2026-10-10T08:30:00Z is 14:00 in Sri Lanka, a Saturday.
  assert.equal(pf.farmTime(Date.UTC(2026, 9, 10, 8, 30)), 'Sat 10 Oct, 14:00');
  assert.equal(pf.fmt(null), '—');
  assert.equal(pf.fmt(0.1234, 2), '0.12');
});

test('an upper bound is never worded as a radius', () => {
  assert.equal(pf.reachText({ radius: 4.9, areaM2: 75.4, bound: null }).short, '4.9 m');
  const ub = pf.reachText({ radius: 5, areaM2: 78.5, bound: 'atMost' });
  assert.equal(ub.short, 'under 5.0 m');
  assert.ok(ub.upper && ub.long.startsWith('less than'));
  assert.equal(pf.reachText({ radius: null, atLeast: 8.6 }).short, 'at least 8.6 m');
  assert.equal(pf.reachText(null), null);
});
