/**
 * Growth stages: the three that decide plant food, and the six the photo check
 * names.
 *
 * DELIBERATELY IMPORTS NOTHING, like deviceHealth.js, so it is tested in plain
 * Node (__tests__/growthStage.test.mjs).
 *
 * Feeding knows three stages (Active 30-10-10, Flowering 10-30-20, Dormant not
 * fed). The growth-stage photo model (ml-models/growth_stage) names six. Which
 * of the three a photo result counts as is a PROPOSAL shown to the farmer, who
 * confirms or changes it before anything is saved. Agreed with nobody yet: the
 * growth-stage component's owner should check it (15 Oct 2026).
 */

export const FEED_STAGES = [
  { key: 'Active',    label: 'Active',
    sub: 'Growing new leaves and roots, no flower spike. Fed 30-10-10.' },
  { key: 'Flowering', label: 'Flowering',
    sub: 'A spike, buds or open flowers. Fed 10-30-20 for the blooms.' },
  { key: 'Dormant',   label: 'Dormant',
    sub: 'Resting, no new growth. Not fed: a resting plant cannot use it.' },
];

export const PHOTO_TO_FEED = {
  vegetative:     'Active',
  budding:        'Flowering',
  pre_bloom:      'Flowering',
  full_bloom:     'Flowering',
  wilting:        'Dormant',
  seed_formation: 'Dormant',
};

const PHOTO_NAMES = {
  vegetative: 'Vegetative', budding: 'Budding', pre_bloom: 'Pre-bloom',
  full_bloom: 'Full bloom', wilting: 'Wilting', seed_formation: 'Seed formation',
};

/** 'Pre-Bloom Stage', 'pre-bloom', 'pre_bloom' -> 'pre_bloom'; unknown -> ''. */
export function photoKey(value) {
  if (typeof value !== 'string') return '';
  const k = value.trim().toLowerCase().replace(/\s*stage$/, '').replace(/[\s-]+/g, '_');
  const alias = { vegetative_growth: 'vegetative', bloom: 'full_bloom', seed: 'seed_formation' };
  const key = alias[k] || k;
  return PHOTO_TO_FEED[key] ? key : '';
}

export const photoName = (key) => PHOTO_NAMES[photoKey(key)] || '';

/** The feeding stage a photo result is proposed as, or null if unknown. */
export function feedStageFor(photo) {
  return PHOTO_TO_FEED[photoKey(photo)] || null;
}

export const isFeedStage = (s) => FEED_STAGES.some((f) => f.key === s);
