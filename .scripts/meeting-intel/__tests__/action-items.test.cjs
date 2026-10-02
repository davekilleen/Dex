'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const {
  assignedPerson,
  routeBucket,
  routeAtMentionActionItems,
} = require('../lib/action-items.cjs');

test('assignedPerson reads @Name and @[Name]: forms', () => {
  assert.equal(assignedPerson('- [ ] @Sarah: send the deck'), 'Sarah');
  assert.equal(assignedPerson('@[Sarah Chen]: send the deck'), 'Sarah Chen');
  assert.equal(assignedPerson('@Tom follow up'), 'Tom');
  assert.equal(assignedPerson('Send the deck to @Sarah'), null);
});

test('routeBucket keeps owner @mentions as For Me', () => {
  assert.equal(routeBucket('@Dana: book the room', 'Dana Wells'), 'me');
  assert.equal(routeBucket('@Sarah: send the deck', 'Dana Wells'), 'others');
  assert.equal(routeBucket('Send the deck', 'Dana Wells'), 'me');
});

test('routeAtMentionActionItems moves @Name lines out of For Me', () => {
  const input = [
    '## Summary',
    '',
    'Talked.',
    '',
    '## Action Items',
    '',
    '### For Me',
    '- [ ] Write the recap',
    '- [ ] @Sarah: send the deck',
    '',
    '### For Others',
    '- [ ] @Tom: confirm dates',
    '',
    '## Pillar Assignment',
    '',
    'Build',
  ].join('\n');

  const routed = routeAtMentionActionItems(input, 'Dana Wells');

  assert.match(routed, /### For Me\n- \[ \] Write the recap\n\n### For Others/);
  assert.match(routed, /@Sarah: send the deck/);
  assert.match(routed, /@Tom: confirm dates/);
  const forMe = routed.split('### For Others')[0];
  assert.doesNotMatch(forMe, /@Sarah/);
});
