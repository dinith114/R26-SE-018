/**
 * The device-health helpers, proven without a device.
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
const src = readFileSync(join(here, '..', 'deviceHealth.js'), 'utf8');
const dh = await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));

const HEALTH = {
  checkedAtMs: 1_791_000_000_000,
  sections: {
    S1: [{ kind: 'silent', title: 'Node stopped reporting', message: 'm', sinceMs: 20 },
         { kind: 'dht', title: 'Temperature sensor not answering', message: 'm', sinceMs: 10 }],
    S2: [],
    S3: [null, { kind: 'x' }, 'junk'],
  },
};

test('issues come back oldest first and junk is dropped', () => {
  assert.deepEqual(dh.sectionIssues(HEALTH, 'S1').map((i) => i.kind), ['dht', 'silent']);
  assert.deepEqual(dh.sectionIssues(HEALTH, 'S3'), []);
  assert.deepEqual(dh.sectionIssues(HEALTH, 'S9'), []);
  assert.deepEqual(dh.sectionIssues(null, 'S1'), []);
});

test('only sections with a real issue are counted', () => {
  assert.equal(dh.sectionsWithIssues(HEALTH), 1);
  assert.equal(dh.sectionsWithIssues({}), 0);
});

test('no check run since a restart is never an all-clear', () => {
  assert.equal(dh.checksStarted(HEALTH), true);
  assert.equal(dh.checksStarted({ checkedAtMs: null, sections: {} }), false);
  assert.equal(dh.checksStarted(undefined), false);
});

test('times are farm time, UTC+5:30', () => {
  // 2026-10-08T08:50:00Z is 14:20 in Sri Lanka.
  assert.equal(dh.farmClock(Date.UTC(2026, 9, 8, 8, 50)), '14:20');
  assert.equal(dh.farmClock(undefined), '');
});
