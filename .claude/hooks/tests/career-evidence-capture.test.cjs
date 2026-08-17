const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const HOOK = path.resolve(__dirname, '../career-evidence-capture.cjs');

function createVault(t) {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-career-evidence-'));
  fs.mkdirSync(path.join(vault, '05-Areas', 'Career', 'Evidence'), { recursive: true });
  t.after(() => fs.rmSync(vault, { recursive: true, force: true }));
  return vault;
}

function runHook(vault, filePath) {
  return spawnSync(process.execPath, [HOOK], {
    cwd: vault,
    encoding: 'utf8',
    env: {
      ...process.env,
      CLAUDE_PROJECT_DIR: vault,
      VAULT_PATH: vault,
    },
    input: JSON.stringify({
      hook_event_name: 'PostToolUse',
      tool_input: { file_path: filePath },
    }),
  });
}

test('achievement detection emits a consent prompt without writing evidence', (t) => {
  const vault = createVault(t);
  const source = path.join(vault, '05-Areas', 'Career', 'Evidence', 'launch.md');
  const original = [
    '---',
    'date: 2026-07-10',
    '---',
    '# Launch',
    '',
    'Shipped the launch and improved an explicitly measured outcome.',
    '',
  ].join('\n');
  fs.writeFileSync(source, original);

  const result = runHook(vault, source);

  assert.equal(result.status, 0, result.stderr);
  assert.equal(fs.readFileSync(source, 'utf8'), original);
  assert.equal(
    fs.existsSync(path.join(vault, '05-Areas', 'Career', 'Evidence_Log.md')),
    false,
    'a PostToolUse observation must never silently create or append evidence',
  );

  const output = JSON.parse(result.stdout);
  assert.equal(output.continue, true);
  assert.equal(output.hookSpecificOutput.hookEventName, 'PostToolUse');
  const context = output.hookSpecificOutput.additionalContext;
  assert.match(context, /candidate only; nothing was saved/i);
  assert.match(context, /source path: 05-Areas\/Career\/Evidence\/launch\.md/i);
  assert.match(context, /source event date: 2026-07-10/i);
  assert.match(context, /retrieved as-of: \d{4}-\d{2}-\d{2}T/i);
  assert.match(context, /uncertainty:/i);
  assert.match(context, /show the exact proposed bytes/i);
  assert.match(context, /explicit confirmation/i);
  assert.match(context, /read back/i);
});

test('missing source dates stay unknown and still do not create files', (t) => {
  const vault = createVault(t);
  const source = path.join(vault, '05-Areas', 'Career', 'note.md');
  fs.writeFileSync(source, 'Completed a customer launch.\n');

  const result = runHook(vault, source);

  assert.equal(result.status, 0, result.stderr);
  const context = JSON.parse(result.stdout).hookSpecificOutput.additionalContext;
  assert.match(context, /source event date: unknown/i);
  assert.match(context, /uncertainty: source event date is unknown/i);
  assert.deepEqual(
    fs.readdirSync(path.join(vault, '05-Areas', 'Career')),
    ['Evidence', 'note.md'],
  );
});

test('a symlinked Career ancestor cannot expose an outside file', (t) => {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-career-vault-'));
  const outside = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-career-outside-'));
  t.after(() => fs.rmSync(vault, { recursive: true, force: true }));
  t.after(() => fs.rmSync(outside, { recursive: true, force: true }));
  fs.mkdirSync(path.join(vault, '05-Areas'), { recursive: true });
  fs.symlinkSync(outside, path.join(vault, '05-Areas', 'Career'), 'dir');
  const source = path.join(outside, 'private.md');
  fs.writeFileSync(source, 'Achieved a private measured outcome.\n');

  const result = runHook(vault, path.join(vault, '05-Areas', 'Career', 'private.md'));

  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, '');
  assert.equal(fs.readFileSync(source, 'utf8'), 'Achieved a private measured outcome.\n');
});
