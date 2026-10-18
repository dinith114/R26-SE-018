/**
 * The live status strip's words, proven without a device.
 * Loaded from source through a data: URI, as request.test.mjs explains.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'activityText.js'), 'utf8');
const { describe: say, pollMs, forPlace, POLL_ACTIVE_MS, POLL_IDLE_MS } =
  await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));

const base = { houseId: 'H4', houseName: 'Calibration demo', sectionIds: ['S2'],
  sectionNames: ['Section 2'], action: 'water', by: 'user', durationSec: 90 };

test('a running pour counts down between polls and fills its bar', () => {
  const d = say({ ...base, state: 'running', remainingSec: 60 }, { elapsed: 15 });
  assert.equal(d.title, 'Watering · Calibration demo · Section 2');
  assert.equal(d.sub, '45 s left · started by hand');
  assert.equal(d.remaining, 45);
  assert.ok(Math.abs(d.progress - 0.5) < 1e-9);
  assert.equal(d.canStop, true);
});

test('an automatic tray fill says so', () => {
  const d = say({ ...base, action: 'tray', by: 'auto', state: 'running', remainingSec: 10, durationSec: 15 });
  assert.match(d.title, /^Filling the tray/);
  assert.match(d.sub, /automatic$/);
});

test('waiting, finished, stopped, refused and unanswered each read differently', () => {
  assert.match(say({ ...base, state: 'waiting' }).title, /^Waiting for the controller/);
  assert.match(say({ ...base, state: 'done', ranSec: 90, endedAtSec: 1000 }, { nowSec: 1030 }).sub, /^90 s · finished just now$/);
  assert.equal(say({ ...base, state: 'stopped', ranSec: 12 }).sub, 'ran 12 of 90 s');
  assert.match(say({ ...base, state: 'refused', outcome: 'stale' }).sub, /\(stale\)/);
  assert.match(say({ ...base, state: 'unconfirmed' }).title, /^No answer/);
});

test('a whole-house run names the house and the count, and on a section screen just itself', () => {
  const run = { ...base, state: 'running', remainingSec: 30, sectionIds: ['S1', 'S2', 'S3'],
    sectionNames: ['Section 1', 'Section 2', 'Section 3'] };
  assert.equal(say(run).title, 'Watering · Calibration demo · 3 sections, one run');
  assert.equal(say(run, { sectionId: 'S2' }).title, 'Watering · 3 sections, one run');
  assert.equal(say({ ...base, state: 'running', remainingSec: 5 }, { sectionId: 'S2' }).title, 'Watering');
});

test('polls fast only while something moves', () => {
  assert.equal(pollMs([{ state: 'done' }]), POLL_IDLE_MS);
  assert.equal(pollMs([{ state: 'done' }, { state: 'waiting' }]), POLL_ACTIVE_MS);
  assert.equal(pollMs(null), POLL_IDLE_MS);
});

test('a section sees the runs that cover it, a house sees its own', () => {
  const items = [{ houseId: 'H1', sectionIds: ['S1', 'S2'] }, { houseId: 'H4', sectionIds: ['S2'] }];
  assert.equal(forPlace(items, 'H1', 'S2').length, 1);
  assert.equal(forPlace(items, 'H4').length, 1);
  assert.equal(forPlace(items).length, 2);
});
