/**
 * The History tab's ranges and day grouping, proven without a device.
 *
 * Run: cd mobile && node --test src/services/__tests__/
 * Loaded from source through a data: URI, as request.test.mjs explains.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'historyRange.js'), 'utf8');
const hr = await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));

// 15 Oct 2026 01:30 at the farm = 14 Oct 20:00 UTC. A phone or server reading
// UTC would call this the 14th; the farm calls it the 15th.
const NOW = Date.UTC(2026, 9, 14, 20, 0);

test('farm dates are UTC+5:30, not the phone clock', () => {
  assert.equal(hr.farmDate(NOW), '2026-10-15');
  assert.equal(hr.farmMidnight('2026-10-15'), Date.UTC(2026, 9, 14, 18, 30));
  assert.equal(hr.farmDate(hr.farmMidnight('2026-10-15')), '2026-10-15');
  assert.equal(hr.farmDate(hr.farmMidnight('2026-10-15') - 1), '2026-10-14');
});

test('today and yesterday are farm days', () => {
  const today = hr.rangeWindow({ kind: 'today', label: 'Today' }, NOW);
  assert.equal(today.start, hr.farmMidnight('2026-10-15'));
  assert.equal(today.end, NOW);
  assert.equal(today.live, true);
  const y = hr.rangeWindow({ kind: 'yesterday', label: 'Yesterday' }, NOW);
  assert.equal(y.start, hr.farmMidnight('2026-10-14'));
  assert.equal(y.end, hr.farmMidnight('2026-10-15') - 1);
  assert.equal(y.live, false);
});

test('last N hours ends now', () => {
  const w = hr.rangeWindow(hr.HISTORY_PRESETS.find((p) => p.key === 'h24'), NOW);
  assert.equal(w.end - w.start, 24 * 3600000);
  assert.equal(w.end, NOW);
});

test('a custom range covers whole farm days and never runs past now', () => {
  const w = hr.rangeWindow({ kind: 'custom', from: '2026-10-10', to: '2026-10-12' }, NOW);
  assert.equal(w.start, hr.farmMidnight('2026-10-10'));
  assert.equal(w.end, hr.farmMidnight('2026-10-13') - 1);
  assert.equal(hr.spanDays(w), 3);
  assert.equal(w.label, '10-12 Oct');
  const upToToday = hr.rangeWindow({ kind: 'custom', from: '2026-10-15', to: '2026-10-15' }, NOW);
  assert.equal(upToToday.end, NOW);
  assert.equal(upToToday.label, '15 Oct');
  const reversed = hr.rangeWindow({ kind: 'custom', from: '2026-10-12', to: '2026-10-10' }, NOW);
  assert.equal(reversed.start, w.start);
});

test('labels stay short enough for a button', () => {
  assert.equal(hr.customLabel('2026-09-28', '2026-10-03'), '28 Sep - 3 Oct');
  assert.equal(hr.customLabel('2026-10-14', '2026-10-14'), '14 Oct');
  assert.equal(hr.localStamp('2026-10-14 08:55'), 'Wed 14 Oct 08:55');
  assert.equal(hr.localStamp(null), '');
});

test('timeline items group into days in the order they came', () => {
  const items = [
    { local: '2026-10-15 01:20:00', kind: 'reading' },
    { local: '2026-10-15 00:05:00', kind: 'water' },
    { local: '2026-10-14 23:59:10', kind: 'reading' },
    { local: '2026-10-14 06:00:00', kind: 'tray' },
    null,
  ];
  const g = hr.groupByDay(items);
  assert.deepEqual(g.map((d) => [d.day, d.title, d.items.length]),
    [['2026-10-15', 'Thu 15 Oct', 2], ['2026-10-14', 'Wed 14 Oct', 2]]);
  assert.equal(hr.clockOf(items[2]), '23:59:10');
});

test('a month grid starts on Sunday and pads both ends', () => {
  const g = hr.monthGrid(2026, 10);          // 1 Oct 2026 is a Thursday
  assert.deepEqual(g[0], [null, null, null, null, '2026-10-01', '2026-10-02', '2026-10-03']);
  assert.equal(g.flat().filter(Boolean).length, 31);
  assert.ok(g.every((w) => w.length === 7));
  assert.equal(hr.monthTitle(2026, 10), 'October 2026');
});

test('picking two days makes a range, either way round, never in the future', () => {
  let s = hr.pickDay(null, '2026-10-12', '2026-10-15');
  assert.deepEqual(s, { from: '2026-10-12', to: '2026-10-12', done: false });
  s = hr.pickDay(s, '2026-10-09', '2026-10-15');
  assert.deepEqual(s, { from: '2026-10-09', to: '2026-10-12', done: true });
  assert.deepEqual(hr.pickDay(s, '2026-10-14', '2026-10-15'),
    { from: '2026-10-14', to: '2026-10-14', done: false });
  assert.equal(hr.pickDay(s, '2026-10-16', '2026-10-15'), s);
  const far = hr.pickDay({ from: '2026-08-01', to: '2026-08-01', done: false }, '2026-10-01', '2026-10-15');
  assert.equal(far.done, false);             // over 31 days starts a new pick
});

test('type chips ask the server for the right kinds', () => {
  assert.equal(hr.typesFor('all'), 'reading,water,feed,tray');
  assert.equal(hr.typesFor('feed'), 'feed');
  assert.equal(hr.typesFor('nonsense'), 'reading,water,feed,tray');
});

test('chart points grow with the span but stay small', () => {
  assert.equal(hr.chartPoints(6 * 3600000), 36);
  assert.equal(hr.chartPoints(24 * 3600000), 48);
  assert.equal(hr.chartPoints(31 * 86400000), 72);
});
