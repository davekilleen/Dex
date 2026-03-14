const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const path = require('node:path');

function runHook(scriptName, stdin) {
  const scriptPath = path.join(__dirname, '..', scriptName);
  return spawnSync('node', [scriptPath], {
    input: stdin,
    encoding: 'utf-8',
    env: { ...process.env, DEX_HOOK_DEBUG: '1' },
  });
}

test('person context injector emits skip reason on invalid JSON', () => {
  const result = runHook('person-context-injector.cjs', 'not-json');
  assert.equal(result.status, 0);
  assert.match(result.stderr, /\[dex-hook-skip] invalid-json-input/);
});

test('person context injector emits skip reason when file path missing', () => {
  const result = runHook('person-context-injector.cjs', JSON.stringify({ tool_input: {} }));
  assert.equal(result.status, 0);
  assert.match(result.stderr, /\[dex-hook-skip] missing-file-path-or-recursive-person-file/);
});

test('company context injector emits skip reason on invalid JSON', () => {
  const result = runHook('company-context-injector.cjs', '{oops');
  assert.equal(result.status, 0);
  assert.match(result.stderr, /\[dex-hook-skip] invalid-json-input/);
});

test('company context injector emits skip reason when file path missing', () => {
  const result = runHook('company-context-injector.cjs', JSON.stringify({ tool_input: {} }));
  assert.equal(result.status, 0);
  assert.match(result.stderr, /\[dex-hook-skip] missing-file-path-or-recursive-company-file/);
});
