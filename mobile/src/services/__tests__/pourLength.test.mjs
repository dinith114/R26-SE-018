/**
 * Pour lengths in words, typed minutes and seconds, and the master's limit.
 * Loaded from source through a data: URI, as request.test.mjs explains.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(join(here, '..', 'pourLength.js'), 'utf8');
const P = await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));

test('lengths read as minutes once they reach a minute', () => {
  assert.equal(P.pourLabel(600), '10 min');
  assert.equal(P.pourLabel(90), '1 min 30 s');
  assert.equal(P.pourLabel(45), '45 s');
  assert.equal(P.pourLabel(0), '0 s');
});

test('a running countdown reads m:ss above a minute', () => {
  assert.equal(P.countdown(598), '9:58');
  assert.equal(P.countdown(60), '1:00');
  assert.equal(P.countdown(45), '45 s');
});

test('typed minutes and seconds become one length', () => {
  assert.equal(P.joinSecs('10', ''), 600);
  assert.equal(P.joinSecs('', '45'), 45);
  assert.equal(P.joinSecs('1', '30'), 90);
  assert.deepEqual(P.splitSecs(630), { min: 10, sec: 30 });
});

test('nothing, letters or more than an hour is not a length', () => {
  assert.equal(P.joinSecs('', ''), null);
  assert.equal(P.joinSecs('ten', ''), null);
  assert.equal(P.joinSecs('61', '0'), null);
  assert.equal(P.joinSecs('-1', '0'), null);
});

test('the default is ten minutes and the ceiling an hour', () => {
  assert.equal(P.DEFAULT_POUR_SEC, 600);
  assert.equal(P.MAX_POUR_SEC, 3600);
  assert.equal(P.clampPour(99999), 3600);
  assert.equal(P.clampPour(0), 1);
});

test('plus and minus step by 10 s when short and a minute when long', () => {
  assert.equal(P.stepPour(600, 1), 660);
  assert.equal(P.stepPour(600, -1), 540);
  assert.equal(P.stepPour(30, 1), 40);
  assert.equal(P.stepPour(120, -1), 110);
  assert.equal(P.stepPour(110, 1), 120);
  assert.equal(P.stepPour(5, -1), 1);
});

test('litres from the flow rate', () => {
  assert.equal(P.litresLabel(600, 300), 'about 180 L');
  assert.equal(P.litresLabel(5, 300), 'about 1.5 L');
  assert.equal(P.litresLabel(600, null), null);
});

test('an old master is named when the length is longer than it can run', () => {
  const limit = { maxSec: 120, reason: 'Flash it with validation-2.9 to allow longer pours.' };
  assert.equal(P.limitNote(60, limit), null);
  assert.match(P.limitNote(600, limit), /stop after 2 min\. Flash it with validation-2\.9/);
  assert.equal(P.limitNote(600, { maxSec: 3600, reason: null }), null);
  assert.equal(P.limitNote(600, null), null);
});
