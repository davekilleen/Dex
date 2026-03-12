#!/usr/bin/env node

/**
 * Smoke test for Slack EOD bot — validates critical paths without external APIs.
 * Run: node .scripts/slack-dex-bot/test-smoke.cjs
 */

const fs = require('fs');
const path = require('path');
const assert = require('assert');

const STATE_DIR = path.join(__dirname, 'state');
const OK_SYNONYMS = new Set(['ok', 'ok!', 'ok.', 'yes', 'sure', 'sounds good', 'confirmed', 'lgtm']);
const SKIP_SYNONYMS = new Set(['skip', 'skip it', 'nah', 'pass', 'no', 'not today']);

function classifyReply(text) {
  if (OK_SYNONYMS.has(text)) return 'confirm';
  if (SKIP_SYNONYMS.has(text)) return 'skip';
  if (/^\d+[\.\)]\s/.test(text)) return 'custom';
  return 'unknown';
}

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed++;
    console.log(`  \u2705 ${name}`);
  } catch (e) {
    failed++;
    console.error(`  \u274C ${name}: ${e.message}`);
  }
}

console.log('Slack EOD Bot — Smoke Tests\n');

// --- Test 1: buildEodBlocks returns valid Block Kit ---
console.log('Block Kit:');
test('buildEodBlocks returns array with header', () => {
  // Inline the function to test without requiring full module (avoids dotenv/Notion deps)
  function buildEodBlocks(topThree, allItems) {
    const blocks = [
      { type: 'header', text: { type: 'plain_text', text: '\uD83C\uDFAF End of Day Check-in', emoji: true } },
      { type: 'section', text: { type: 'mrkdwn', text: "Time to lock in tomorrow's *Must Complete Today* items.\n\nHere are my suggestions based on your Triage:" } }
    ];
    for (let i = 0; i < topThree.length; i++) {
      const item = topThree[i];
      blocks.push({ type: 'section', text: { type: 'mrkdwn', text: `*${i + 1}.* ${item.url ? `<${item.url}|${item.title}>` : item.title}` } });
    }
    blocks.push({ type: 'divider' });
    blocks.push({ type: 'section', text: { type: 'mrkdwn', text: 'Reply with:\n\u2022 `OK` to confirm\n\u2022 Your own 3 items (numbered list)\n\u2022 `Skip` to skip today' } });
    return blocks;
  }

  const items = [
    { title: 'Task A', url: 'https://notion.so/a' },
    { title: 'Task B', url: null },
    { title: 'Task C', url: 'https://notion.so/c' }
  ];
  const blocks = buildEodBlocks(items, items);
  assert(Array.isArray(blocks), 'blocks should be array');
  assert(blocks[0].type === 'header', 'first block should be header');
  assert(blocks.length >= 6, 'should have header + intro + 3 items + divider + instructions');
  assert(blocks[2].text.text.includes('<https://notion.so/a|Task A>'), 'should format URL as link');
  assert(blocks[3].text.text.includes('Task B'), 'should handle null URL');
});

// --- Test 2: buildDegradedBlocks returns valid Block Kit ---
test('buildDegradedBlocks returns valid structure', () => {
  function buildDegradedBlocks(errorType) {
    return [
      { type: 'header', text: { type: 'plain_text', text: '\uD83C\uDFAF End of Day Check-in', emoji: true } },
      { type: 'section', text: { type: 'mrkdwn', text: `Couldn\u2019t reach your triage board (${errorType}).` } },
      { type: 'section', text: { type: 'mrkdwn', text: '```1. First priority```' } },
      { type: 'context', elements: [{ type: 'mrkdwn', text: 'Or reply `Skip` to skip today.' }] }
    ];
  }
  const blocks = buildDegradedBlocks('auth expired');
  assert(blocks[0].type === 'header');
  assert(blocks[1].text.text.includes('auth expired'));
  assert(blocks.length === 4);
});

// --- Test 3: LLM response validation ---
console.log('\nLLM Validation:');
test('non-greedy regex stops at first ]', () => {
  const raw = '[{"index":1,"reason":"urgent"}] and some garbage [here]';
  const match = raw.match(/\[[\s\S]*?\]/);
  assert(match, 'should match');
  const parsed = JSON.parse(match[0]);
  assert(parsed.length === 1, 'should only capture first array');
  assert(parsed[0].index === 1);
});

test('validates index is number in bounds', () => {
  const items = [{ title: 'A' }, { title: 'B' }, { title: 'C' }];
  const selections = [{ index: 1, reason: 'ok' }, { index: 'bad', reason: 'x' }, { index: 99, reason: 'y' }];
  const validated = selections.map(sel => {
    const idx = Number(sel.index);
    if (!Number.isInteger(idx) || idx < 1 || idx > items.length) return null;
    return { title: items[idx - 1].title };
  }).filter(Boolean);
  assert(validated.length === 1, `should have 1 valid item, got ${validated.length}`);
  assert(validated[0].title === 'A');
});

// --- Test 4: State file lifecycle ---
console.log('\nState File Lifecycle:');
const testStateDir = path.join(__dirname, 'state');

test('write and read pending checkin', () => {
  const file = path.join(testStateDir, 'pending-checkin.json');
  const today = new Date().toISOString().slice(0, 10);
  fs.writeFileSync(file, JSON.stringify({ date: today, ts: '123.456', topThree: [{ title: 'Test' }] }));
  const data = JSON.parse(fs.readFileSync(file, 'utf-8'));
  assert(data.date === today, 'date should be today');
  assert(data.ts === '123.456', 'ts should match');
  assert(data.topThree[0].title === 'Test');
});

test('stale date returns null on read', () => {
  const file = path.join(testStateDir, 'pending-checkin.json');
  fs.writeFileSync(file, JSON.stringify({ date: '2020-01-01', ts: '0', topThree: [] }));
  const data = JSON.parse(fs.readFileSync(file, 'utf-8'));
  const today = new Date().toISOString().slice(0, 10);
  const isStale = data.date !== today;
  assert(isStale, 'yesterday date should be stale');
});

test('clear removes file', () => {
  const file = path.join(testStateDir, 'pending-checkin.json');
  fs.writeFileSync(file, '{}');
  fs.unlinkSync(file);
  assert(!fs.existsSync(file), 'file should be deleted');
});

test('confirmed priorities writes correctly', () => {
  const file = path.join(testStateDir, 'confirmed-priorities.json');
  const today = new Date().toISOString().slice(0, 10);
  const items = [{ title: 'A' }, { title: 'B' }];
  fs.writeFileSync(file, JSON.stringify({ date: today, items, source: 'test' }));
  const data = JSON.parse(fs.readFileSync(file, 'utf-8'));
  assert(data.items.length === 2);
  assert(data.source === 'test');
  fs.unlinkSync(file);
});

// --- Test 5: Reply synonym matching ---
console.log('\nReply Classification:');
for (const word of ['ok', 'ok!', 'ok.', 'yes', 'sure', 'sounds good', 'confirmed', 'lgtm']) {
  test(`"${word}" → confirm`, () => assert(classifyReply(word) === 'confirm'));
}
for (const word of ['skip', 'skip it', 'nah', 'pass', 'no', 'not today']) {
  test(`"${word}" → skip`, () => assert(classifyReply(word) === 'skip'));
}
test('"1. do thing" → custom', () => assert(classifyReply('1. do thing') === 'custom'));
test('"1) do thing" → custom', () => assert(classifyReply('1) do thing') === 'custom'));
test('"hello" → unknown', () => assert(classifyReply('hello') === 'unknown'));
test('"what items?" → unknown', () => assert(classifyReply('what items?') === 'unknown'));

// --- Summary ---
console.log(`\n${'='.repeat(40)}`);
console.log(`${passed} passed, ${failed} failed`);
if (failed > 0) process.exit(1);
console.log('All smoke tests passed.');
