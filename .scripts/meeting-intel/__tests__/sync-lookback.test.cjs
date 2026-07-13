'use strict';

const assert = require('node:assert/strict');
const test = require('node:test');
const { deriveLookbackDays } = require('../sync-from-granola.cjs');

const now = new Date('2026-07-13T12:00:00.000Z');

test('sync lookback defaults to seven days without a valid lastSync', () => {
  assert.equal(deriveLookbackDays({}, now), 7);
  assert.equal(deriveLookbackDays({ lastSync: null }, now), 7);
  assert.equal(deriveLookbackDays({ lastSync: 'not-a-date' }, now), 7);
});

test('sync lookback floors at seven days and adds a one-day overlap', () => {
  assert.equal(deriveLookbackDays({ lastSync: '2026-07-12T12:00:00.000Z' }, now), 7);
  assert.equal(deriveLookbackDays({ lastSync: '2026-07-05T12:00:00.000Z' }, now), 9);
});

test('sync lookback caps delayed recovery at thirty days', () => {
  assert.equal(deriveLookbackDays({ lastSync: '2026-05-01T12:00:00.000Z' }, now), 30);
});
