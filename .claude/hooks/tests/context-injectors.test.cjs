const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const FIXTURE_VAULT = path.resolve(__dirname, '../../../core/tests/fixtures/vault');

function createSandbox(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-context-hook-'));
  const vault = path.join(root, 'vault');
  const home = path.join(root, 'home');
  fs.cpSync(FIXTURE_VAULT, vault, { recursive: true });
  fs.mkdirSync(home);
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return { vault, home };
}

function runHook(scriptName, stdin, sandbox) {
  const scriptPath = path.join(__dirname, '..', scriptName);
  return spawnSync(process.execPath, [scriptPath], {
    input: stdin,
    encoding: 'utf-8',
    env: {
      CLAUDE_HOOK_CONTEXT: '{}',
      CLAUDE_PROJECT_DIR: sandbox.vault,
      DEX_HOOK_DEBUG: '1',
      HOME: sandbox.home,
      PATH: '/usr/bin:/bin',
      VAULT_PATH: sandbox.vault,
    },
  });
}

test('person context injector emits skip reason on invalid JSON', (t) => {
  const sandbox = createSandbox(t);
  const result = runHook('person-context-injector.cjs', 'not-json', sandbox);
  assert.equal(result.status, 0);
  assert.match(result.stderr, /\[dex-hook-skip] invalid-json-input/);
});

test('person context injector emits skip reason when file path missing', (t) => {
  const sandbox = createSandbox(t);
  const result = runHook('person-context-injector.cjs', JSON.stringify({ tool_input: {} }), sandbox);
  assert.equal(result.status, 0);
  assert.match(result.stderr, /\[dex-hook-skip] missing-file-path-or-recursive-person-file/);
});

test('company context injector emits skip reason on invalid JSON', (t) => {
  const sandbox = createSandbox(t);
  const result = runHook('company-context-injector.cjs', '{oops', sandbox);
  assert.equal(result.status, 0);
  assert.match(result.stderr, /\[dex-hook-skip] invalid-json-input/);
});

test('company context injector emits skip reason when file path missing', (t) => {
  const sandbox = createSandbox(t);
  const result = runHook('company-context-injector.cjs', JSON.stringify({ tool_input: {} }), sandbox);
  assert.equal(result.status, 0);
  assert.match(result.stderr, /\[dex-hook-skip] missing-file-path-or-recursive-company-file/);
});

test('person context injector emits fixture person context', (t) => {
  const sandbox = createSandbox(t);
  const note = path.join(sandbox.vault, '00-Inbox', 'Meetings', 'person-context.md');
  fs.writeFileSync(note, '# Meeting\n\nMeeting with Alice Smith about the launch.\n');

  const result = runHook(
    'person-context-injector.cjs',
    JSON.stringify({ tool_input: { file_path: note } }),
    sandbox,
  );

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /<person_context>/);
  assert.match(result.stdout, /Alice Smith/);
  assert.match(result.stdout, /<\/person_context>/);
});

test('company context injector emits fixture company context', (t) => {
  const sandbox = createSandbox(t);
  const company = path.join(sandbox.vault, '05-Areas', 'Companies', 'Acme_Corp.md');
  fs.writeFileSync(company, '---\nname: Acme Corp\nstatus: Active\n---\n\nRenewal account.\n');
  const note = path.join(sandbox.vault, '00-Inbox', 'Meetings', 'company-context.md');
  fs.writeFileSync(note, '# Meeting\n\nMeeting with Acme Corp about the renewal.\n');

  const result = runHook(
    'company-context-injector.cjs',
    JSON.stringify({ tool_input: { path: note } }),
    sandbox,
  );

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /<company_context>/);
  assert.match(result.stdout, /Acme Corp/);
  assert.match(result.stdout, /<\/company_context>/);
});
