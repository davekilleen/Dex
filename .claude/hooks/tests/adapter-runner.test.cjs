const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const os = require('node:os');

const { loadServiceAliases, resolveAdapterService } = require('../adapters/run.cjs');

const RUNNER = path.resolve(__dirname, '../adapters/run.cjs');

function run(service, operation, payload, options = {}) {
  return spawnSync(process.execPath, [RUNNER, service, operation], {
    encoding: 'utf-8',
    input: `${JSON.stringify(payload)}\n`,
    timeout: 5_000,
    ...options,
  });
}

function resolve(service) {
  return spawnSync(process.execPath, [RUNNER, '--resolve-adapter', service], {
    encoding: 'utf-8',
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

test('atlassian resolves one hop to jira while direct jira behavior remains available', () => {
  const atlassian = parseOnlyJsonLine(run('atlassian', 'create', {
    config: {},
    args: { title: 'No credentials', task_id: 'task-20260712-011' },
  }));
  const jira = parseOnlyJsonLine(run('jira', 'create', {
    config: {},
    args: { title: 'No credentials', task_id: 'task-20260712-012' },
  }));

  assert.equal(resolveAdapterService('atlassian'), 'jira');
  assert.equal(resolveAdapterService('jira'), 'jira');
  assert.equal(resolveAdapterService('constructor', {}), 'constructor');
  assert.equal(atlassian.ok, false);
  assert.equal(jira.ok, false);
  assert.match(atlassian.error, /Atlassian auth not configured/i);
  assert.equal(atlassian.error, jira.error);
});

test('bounded resolver returns only stable requested and adapter identities', () => {
  const result = resolve('atlassian');
  assert.equal(result.status, 0);
  assert.deepEqual(parseOnlyJsonLine(result), {
    ok: true,
    requested_service: 'atlassian',
    adapter_service: 'jira',
  });
  assert.equal(result.stderr, '');
});

test('alias parser rejects malformed, traversal, chained, and cyclic mappings', () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-adapter-aliases-'));
  try {
    const aliases = path.join(temporary, 'aliases.json');
    for (const [payload, pattern] of [
      ['[]', /object/i],
      ['{"atlassian":"jira","atlassian":"cloud"}', /duplicate/i],
      ['{"atlassian":"atlassian"}', /self-referential/i],
      ['{"atlassian":"../jira"}', /invalid/i],
      ['{"atlassian":"jira","jira":"cloud"}', /one hop/i],
      ['{"atlassian":"jira","jira":"atlassian"}', /one hop/i],
    ]) {
      fs.writeFileSync(aliases, payload);
      assert.throws(() => loadServiceAliases(aliases), pattern);
    }
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test('missing adapter is a single structured corrective failure', () => {
  const output = parseOnlyJsonLine(run('adapterless', 'get_changes', {
    config: {},
    args: '2026-07-12T08:00:00Z',
  }));

  assert.equal(output.ok, false);
  assert.match(output.error, /requested service 'adapterless'/i);
  assert.match(output.error, /expected 'adapterless\.cjs'/i);
});
