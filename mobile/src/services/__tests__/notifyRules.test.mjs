/**
 * Clearing notifications, proven without a device.
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
const src = readFileSync(join(here, '..', 'notifyRules.js'), 'utf8');
const nr = await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));

const H = 3600000;
const T0 = 1_792_000_000_000;
const stale = (days) => ({ id: 'H1-S1-stale', level: 'warning', message: `H1 · S1: no reading for ${days} days` });
const plan = (at) => ({ id: 'H3-S1-plan', level: 'info', message: `Demo · Bright edge: ${at} for 101s.` });
const tray = { id: 'H3-S2-tray', level: 'action', message: 'tray needs 15s' };

test('a cleared problem stays hidden while its wording changes', () => {
  let c = nr.clearOne({}, stale(4), T0);
  assert.deepEqual(nr.splitAlerts([stale(5), tray], c).shown, [tray]);
  assert.equal(nr.badgeCount([stale(5), tray], c), 1);
});

test("clearing today's watering does not hide tomorrow's", () => {
  const c = nr.clearOne({}, plan('06:19'), T0);
  assert.equal(nr.splitAlerts([plan('06:19')], c).shown.length, 0);
  assert.equal(nr.splitAlerts([plan('06:31')], c).shown.length, 1);
});

test('info items never count on the bell', () => {
  assert.equal(nr.badgeCount([plan('06:19'), tray], {}), 1);
});

test('clear all hides everything there now, and restore brings one back', () => {
  let c = nr.clearAll({}, [stale(4), tray, plan('06:19')], T0);
  assert.equal(nr.splitAlerts([stale(4), tray, plan('06:19')], c).shown.length, 0);
  assert.equal(nr.badgeCount([stale(4), tray], c), 0);
  c = nr.restoreOne(c, tray);
  assert.deepEqual(nr.splitAlerts([stale(4), tray], c).shown, [tray]);
});

test('a problem that went away for over two hours is told again when it returns', () => {
  let c = nr.clearOne({}, tray, T0);
  c = nr.refreshSeen(c, [], T0 + 1 * H);              // gone an hour: still remembered
  assert.ok(c['H3-S2-tray']);
  c = nr.refreshSeen(c, [], T0 + 2.5 * H);            // gone over two hours: forgotten
  assert.equal(c['H3-S2-tray'], undefined);
  assert.equal(nr.splitAlerts([tray], c).shown.length, 1);
});

test('one empty fetch does not bring back what was cleared', () => {
  let c = nr.clearOne({}, tray, T0);
  c = nr.refreshSeen(c, [], T0 + 60000);
  c = nr.refreshSeen(c, [tray], T0 + 120000);
  assert.equal(nr.splitAlerts([tray], c).shown.length, 0);
});

test('a problem that lasts all day stays cleared all day', () => {
  let c = nr.clearOne({}, stale(4), T0);
  for (let m = 1; m <= 24 * 60; m++) c = nr.refreshSeen(c, [stale(4)], T0 + m * 60000);
  assert.equal(nr.splitAlerts([stale(5)], c).shown.length, 0);
});

test('a quiet poll returns the same object, so nothing is written', () => {
  const c = nr.clearOne({}, tray, T0);
  assert.equal(nr.refreshSeen(c, [tray], T0 + 60000), c);
  const none = {};
  assert.equal(nr.refreshSeen(none, [tray], T0), none);
});

test('junk in the list is ignored', () => {
  assert.deepEqual(nr.splitAlerts([null, {}, tray], {}).shown.length, 3);
  assert.equal(nr.clearKey(null), null);
  assert.deepEqual(nr.clearOne({}, {}, T0), {});
});
