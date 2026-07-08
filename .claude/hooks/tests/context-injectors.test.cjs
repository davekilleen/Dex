const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

function runHook(scriptName, stdin, extraEnv = {}) {
  const scriptPath = path.join(__dirname, '..', scriptName);
  return spawnSync('node', [scriptPath], {
    input: stdin,
    encoding: 'utf-8',
    env: { ...process.env, DEX_HOOK_DEBUG: '1', ...extraEnv },
  });
}

/** Create a throwaway vault and return its root. */
function makeVault(files) {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-hook-vault-'));
  for (const [relPath, content] of Object.entries(files)) {
    const abs = path.join(vault, relPath);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, content);
  }
  return vault;
}

function readInput(vault, relPath) {
  return JSON.stringify({ tool_input: { file_path: path.join(vault, relPath) } });
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

// ---------------------------------------------------------------------------
// Happy paths: context actually gets injected
// ---------------------------------------------------------------------------

test('person context injector injects role, company, and open items', () => {
  const vault = makeVault({
    'People/Internal/Jane_Roe.md': [
      '---',
      'name: Jane Roe',
      'role: VP of Operations',
      'company: Acme Corp',
      'last_interaction: 2026-06-20',
      '---',
      '# Jane Roe',
      '- [ ] Send Jane the Q3 forecast',
      '',
    ].join('\n'),
    'Inbox/Meetings/2026-07-01 - Sync.md': 'Meeting notes.\nMet with Jane Roe about rollout.\n',
  });

  const result = runHook(
    'person-context-injector.cjs',
    readInput(vault, 'Inbox/Meetings/2026-07-01 - Sync.md'),
    { CLAUDE_PROJECT_DIR: vault }
  );

  assert.equal(result.status, 0);
  const output = JSON.parse(result.stdout);
  assert.equal(output.continue, true);
  const context = output.hookSpecificOutput.additionalContext;
  assert.match(context, /<person_context>/);
  assert.match(context, /Jane Roe - VP of Operations @ Acme Corp/);
  assert.match(context, /Last interaction: 2026-06-20/);
  assert.match(context, /Send Jane the Q3 forecast/);
});

test('person context injector matches explicit People/ path references', () => {
  const vault = makeVault({
    'People/External/Bob_Jones.md': '---\nrole: Buyer\ncompany: Globex\n---\n# Bob Jones\n',
    'Planning/Tasks.md': '- [ ] Follow up | People/External/Bob_Jones.md ^task-20260601-001\n',
  });

  const result = runHook(
    'person-context-injector.cjs',
    readInput(vault, 'Planning/Tasks.md'),
    { CLAUDE_PROJECT_DIR: vault }
  );

  assert.equal(result.status, 0);
  const context = JSON.parse(result.stdout).hookSpecificOutput.additionalContext;
  assert.match(context, /Bob Jones - Buyer @ Globex/);
});

test('person context injector skips when no known person is referenced', () => {
  const vault = makeVault({
    'People/Internal/Jane_Roe.md': '# Jane Roe\n',
    'Inbox/Meetings/2026-07-01 - Sync.md': 'Meeting with nobody in particular.\n',
  });

  const result = runHook(
    'person-context-injector.cjs',
    readInput(vault, 'Inbox/Meetings/2026-07-01 - Sync.md'),
    { CLAUDE_PROJECT_DIR: vault }
  );

  assert.equal(result.status, 0);
  assert.equal(result.stdout, '');
  assert.match(result.stderr, /\[dex-hook-skip] no-person-references-found/);
});

test('company context injector injects company context for business notes', () => {
  const vault = makeVault({
    'People/Companies/Acme_Corp.md': '# Acme Corp\n- [ ] Renewal paperwork\n',
    'Inbox/Meetings/2026-07-01 - Demo.md': 'Demo call with Acme Corp went well.\n',
  });

  const result = runHook(
    'company-context-injector.cjs',
    readInput(vault, 'Inbox/Meetings/2026-07-01 - Demo.md'),
    { CLAUDE_PROJECT_DIR: vault }
  );

  assert.equal(result.status, 0);
  const output = JSON.parse(result.stdout);
  assert.equal(output.continue, true);
  const context = output.hookSpecificOutput.additionalContext;
  assert.match(context, /<company_context>/);
  assert.match(context, /Acme Corp/);
});

test('company context injector skips when no company is referenced', () => {
  const vault = makeVault({
    'People/Companies/Acme_Corp.md': '# Acme Corp\n',
    'Inbox/Meetings/2026-07-01 - Demo.md': 'Demo call with an unnamed prospect.\n',
  });

  const result = runHook(
    'company-context-injector.cjs',
    readInput(vault, 'Inbox/Meetings/2026-07-01 - Demo.md'),
    { CLAUDE_PROJECT_DIR: vault }
  );

  assert.equal(result.status, 0);
  assert.match(result.stderr, /\[dex-hook-skip] no-company-references-found/);
});
