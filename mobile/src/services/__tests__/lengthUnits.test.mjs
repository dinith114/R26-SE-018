/**
 * Metres and feet for sizes and positions, proven without a device.
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
const src = readFileSync(join(here, '..', 'lengthUnits.js'), 'utf8');
const lu = await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));

test("the farm's house in feet is sent in metres", () => {
  assert.deepEqual(lu.parseLength('16', 'ft'), { m: 4.88 });
  assert.deepEqual(lu.parseLength('32', 'ft'), { m: 9.75 });
  assert.deepEqual(lu.parseLength('4.99', 'm'), { m: 4.99 });
  assert.deepEqual(lu.parseLength('9,7', 'm'), { m: 9.7 });
});

test('metres are shown in either unit', () => {
  assert.equal(lu.formatLength(4.99, 'm'), '4.99 m');
  assert.equal(lu.formatLength(4.99, 'ft'), '16.4 ft');
  assert.equal(lu.formatLength(9.7, 'ft'), '31.8 ft');
  assert.equal(lu.formatLength(null, 'ft'), '--');
  assert.equal(lu.editText(9.75, 'ft'), '32');
  assert.equal(lu.editText(undefined, 'm'), '');
});

test('limits are checked in metres and explained in the unit typed', () => {
  const r = lu.parseLength('700', 'ft', { min: 1, max: 200, what: 'Width' });
  assert.equal(r.error, 'Width must be between 3.3 and 656.2 ft.');
  assert.ok(lu.parseLength('0.5', 'm', { min: 1, max: 200 }).error);
  assert.ok(lu.parseLength('abc', 'm').error);
  assert.ok(lu.parseLength('', 'ft').error);
});

test('switching unit keeps the same length in the box', () => {
  assert.equal(lu.convertText('16', 'ft', 'm'), '4.88');
  assert.equal(lu.convertText('4.88', 'm', 'ft'), '16');
  assert.equal(lu.convertText('abc', 'm', 'ft'), 'abc');
  assert.equal(lu.convertText('3', 'm', 'm'), '3');
});
