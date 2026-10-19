/**
 * The "where would a new sensor help most" suggestion, proven without a device.
 * Loaded from source through a data: URI, as request.test.mjs explains.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'placementHint.js'), 'utf8');
const { furthestPoint } = await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));

test('no size, no suggestion', () => {
  assert.equal(furthestPoint(0, 10, []), null);
  assert.equal(furthestPoint(5, null, []), null);
});

test('no sensors yet: the middle of the house', () => {
  assert.deepEqual(furthestPoint(4, 10, []), { x: 2, y: 5, distance: null });
});

test('the gap between sensors is found, inside the walls', () => {
  // four sensors in the top half of a 4.99 x 9.7 m house: the empty bottom wins
  const s = [{ x: 1.25, y: 2.43 }, { x: 3.74, y: 2.43 }, { x: 1.25, y: 4.8 }, { x: 3.74, y: 4.8 }];
  const p = furthestPoint(4.99, 9.7, s);
  assert.ok(p.y > 8.5, `expected the far end, got y=${p.y}`);
  assert.ok(p.x >= 0.5 && p.x <= 4.49 && p.y <= 9.2, 'kept half a metre in from the walls');
  assert.ok(p.distance > 4, `distance ${p.distance}`);
});

test('every candidate is at least as far as the suggestion says', () => {
  const s = [{ x: 1, y: 1 }];
  const p = furthestPoint(6, 6, s);
  assert.equal(Math.round(Math.hypot(p.x - 1, p.y - 1) * 10) / 10, p.distance);
});
