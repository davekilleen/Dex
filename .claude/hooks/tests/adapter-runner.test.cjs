const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const path = require('node:path');

const RUNNER = path.resolve(__dirname, '../adapters/run.cjs');

function run(service, operation, payload) {
  return spawnSync(process.execPath, [RUNNER, service, operation], {
    encoding: 'utf-8',
    input: `${JSON.stringify(payload)}\n`,
    timeout: 5_000,
  });
}

function parseOnlyJsonLine(result) {
  const lines = result.stdout.trim().split('\n');
  assert.equal(lines.length, 1, `garbage stdout: ${result.stdout}`);
  return JSON.parse(lines[0]);
}

test('runner rejects unsafe service names with structured stdout', () => {
  const result = run('../todoist', 'create', { config: {}, args: {} });
  const output = parseOnlyJsonLine(result);

  assert.notEqual(result.status, 0);
  assert.equal(output.ok, false);
  assert.match(output.error, /service/i);
});

test('runner turns adapter throws into structured stdout without garbage', () => {
  const result = run('todoist', 'create', {
    config: {},
    args: { title: 'No credentials', task_id: 'task-20260712-010' },
  });
  const output = parseOnlyJsonLine(result);

  assert.notEqual(result.status, 0);
  assert.equal(output.ok, false);
  assert.match(output.error, /API key/i);
});
