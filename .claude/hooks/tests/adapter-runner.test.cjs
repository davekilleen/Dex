const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const path = require('node:path');

const RUNNER = path.resolve(__dirname, '../adapters/run.cjs');

function run(service, operation, payload, options = {}) {
  return spawnSync(process.execPath, [RUNNER, service, operation], {
    encoding: 'utf-8',
    input: `${JSON.stringify(payload)}\n`,
    timeout: 5_000,
    ...options,
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

test('real runner redacts thrown Trello fetch URL and exception details', (t) => {
  const fs = require('node:fs');
  const os = require('node:os');
  const preloadRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-trello-fetch-'));
  t.after(() => fs.rmSync(preloadRoot, { recursive: true, force: true }));
  const preload = path.join(preloadRoot, 'throw-fetch.cjs');
  fs.writeFileSync(preload, `
global.fetch = async (url) => {
  const error = new Error('synthetic transport ' + url);
  error.cause = { body: String(url), authorization: 'synthetic-header-secret' };
  throw error;
};
`);
  const apiKey = 'synthetic-runner-query-key';
  const token = 'synthetic-runner-query-token';
  const result = run('trello', 'health', {
    config: { api_key: apiKey, token },
    args: null,
  }, {
    env: { ...process.env, NODE_OPTIONS: `--require=${preload}` },
  });
  const output = parseOnlyJsonLine(result);
  const serialized = `${result.stdout}${result.stderr}`;

  assert.notEqual(result.status, 0);
  assert.deepEqual(output, { ok: false, error: 'Trello API GET transport failed' });
  assert.equal(serialized.includes(apiKey), false);
  assert.equal(serialized.includes(token), false);
  assert.equal(serialized.includes('synthetic-header-secret'), false);
  assert.equal(serialized.includes('api.trello.com'), false);
});
