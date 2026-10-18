/**
 * Growth-stage names and the photo-to-feeding proposal, proven without a device.
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
const src = readFileSync(join(here, '..', 'growthStage.js'), 'utf8');
const gs = await import('data:text/javascript;base64,' + Buffer.from(src).toString('base64'));

test('every photo stage maps to a feeding stage', () => {
  for (const [photo, feed] of Object.entries(gs.PHOTO_TO_FEED)) {
    assert.ok(gs.isFeedStage(feed), `${photo} -> ${feed}`);
  }
  assert.equal(Object.keys(gs.PHOTO_TO_FEED).length, 6);
});

test('the photo model and the server name the same six stages', () => {
  const cfg = readFileSync(join(here, '..', '..', '..', '..', 'ml-models', 'growth_stage', 'src', 'config.py'), 'utf8');
  const block = cfg.slice(cfg.indexOf('STAGE_LABELS = ['), cfg.indexOf(']', cfg.indexOf('STAGE_LABELS = [')));
  const model = [...block.matchAll(/'([a-z_]+)'/g)].map((m) => m[1]).sort();
  assert.deepEqual(model, Object.keys(gs.PHOTO_TO_FEED).sort());
  const server = readFileSync(join(here, '..', '..', '..', '..', 'backend', 'app', 'api', 'routes', 'smart_care_v2.py'), 'utf8');
  const tuple = server.slice(server.indexOf('PHOTO_STAGES = ('), server.indexOf(')', server.indexOf('PHOTO_STAGES = (')));
  assert.deepEqual([...tuple.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]).sort(), model);
});

test('names from the photo screen are understood in any of its spellings', () => {
  assert.equal(gs.photoKey('Pre-Bloom Stage'), 'pre_bloom');
  assert.equal(gs.photoKey('full_bloom'), 'full_bloom');
  assert.equal(gs.photoKey('Vegetative Growth Stage'), 'vegetative');
  assert.equal(gs.photoKey('Seed Formation'), 'seed_formation');
  assert.equal(gs.photoKey('Blooming nicely'), '');
  assert.equal(gs.photoKey(undefined), '');
});

test('the proposal: buds and flowers feed as Flowering, fading flowers rest', () => {
  assert.equal(gs.feedStageFor('vegetative'), 'Active');
  assert.equal(gs.feedStageFor('Budding Stage'), 'Flowering');
  assert.equal(gs.feedStageFor('full_bloom'), 'Flowering');
  assert.equal(gs.feedStageFor('wilting'), 'Dormant');
  assert.equal(gs.feedStageFor('nonsense'), null);
  assert.equal(gs.photoName('pre_bloom'), 'Pre-bloom');
});
