/**
 * Read intervals: presets, custom values and how they are said, without a device.
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
const src = readFileSync(join(here, '..', 'readInterval.js'), 'utf8');
const ri = await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));

test('intervals read as people say them, without rounding a custom value away', () => {
  assert.equal(ri.formatInterval(15000), '15 s');
  assert.equal(ri.formatInterval(60000), '1 min');
  assert.equal(ri.formatInterval(90000), '1 min 30 s');      // used to read "2 min"
  assert.equal(ri.formatInterval(300000), '5 min');
  assert.equal(ri.formatInterval(3600000), '1 h');
  assert.equal(ri.formatInterval(null), '--');
  assert.equal(ri.intervalSentence(45000), 'every 45 s');
});

test('a custom value in seconds or minutes, decimals allowed', () => {
  assert.deepEqual(ri.parseCustom('90', 's'), { ms: 90000 });
  assert.deepEqual(ri.parseCustom('2.5', 'min'), { ms: 150000 });
  assert.deepEqual(ri.parseCustom(' 10 ', 'min'), { ms: 600000 });
  assert.deepEqual(ri.parseCustom('1,5', 'min'), { ms: 90000 });
});

test('the limits are the firmware and server limits', () => {
  const fw = readFileSync(join(here, '..', '..', '..', '..', 'firmware', 'sensor_node_validate', 'sensor_node_validate.ino'), 'utf8');
  assert.match(fw, new RegExp(`READ_INTERVAL_MIN_MS\\s*=\\s*${ri.READ_MIN_MS}UL`));
  assert.match(fw, new RegExp(`READ_INTERVAL_MAX_MS\\s*=\\s*${ri.READ_MAX_MS}UL`));
  const py = readFileSync(join(here, '..', '..', '..', '..', 'backend', 'app', 'api', 'routes', 'devices.py'), 'utf8');
  assert.match(py, /READ_INTERVAL_MIN_MS = 5_000/);
  assert.match(py, /READ_INTERVAL_MAX_MS = 3_600_000/);
  assert.ok(ri.parseCustom('4', 's').error);
  assert.ok(ri.parseCustom('61', 'min').error);
  assert.deepEqual(ri.parseCustom('5', 's'), { ms: 5000 });
  assert.deepEqual(ri.parseCustom('60', 'min'), { ms: 3600000 });
});

test('nonsense is refused with a reason', () => {
  for (const bad of ['', 'abc', '-5', '1e3', '5 min']) {
    assert.ok(ri.parseCustom(bad, 's').error, bad);
  }
});

test('the custom box is prefilled in the unit the value reads best in', () => {
  assert.deepEqual(ri.splitForEdit(300000), { text: '5', unit: 'min' });
  assert.deepEqual(ri.splitForEdit(90000), { text: '90', unit: 's' });
  assert.deepEqual(ri.splitForEdit(undefined), { text: '', unit: 'min' });
  assert.equal(ri.isPreset(300000), true);
  assert.equal(ri.isPreset(90000), false);
});
