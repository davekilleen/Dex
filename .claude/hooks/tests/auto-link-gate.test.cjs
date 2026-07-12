const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const SCRIPT_PATH = path.resolve(__dirname, '../../../.scripts/auto-link-people.cjs');

function createVault(t, { obsidianMode }) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-auto-link-gate-'));
  const vault = path.join(root, 'vault');
  const peopleDir = path.join(vault, '05-Areas', 'People', 'External');
  const meetingsDir = path.join(vault, '00-Inbox', 'Meetings');
  const systemDir = path.join(vault, 'System');
  fs.mkdirSync(peopleDir, { recursive: true });
  fs.mkdirSync(meetingsDir, { recursive: true });
  fs.mkdirSync(systemDir, { recursive: true });
  fs.writeFileSync(
    path.join(systemDir, 'user-profile.yaml'),
    `name: Test User\nobsidian_mode: ${obsidianMode}\n`
  );
  fs.writeFileSync(path.join(peopleDir, 'Jane_Doe.md'), '# Jane Doe\n');
  const note = path.join(meetingsDir, 'note.md');
  fs.writeFileSync(note, 'Talked to Jane Doe about the launch.\n');
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return { vault, note };
}

function freshModule(vault) {
  delete require.cache[SCRIPT_PATH];
  const previous = {
    CLAUDE_PROJECT_DIR: process.env.CLAUDE_PROJECT_DIR,
    VAULT_PATH: process.env.VAULT_PATH,
  };
  process.env.CLAUDE_PROJECT_DIR = vault;
  process.env.VAULT_PATH = vault;
  // paths.cjs resolves its vault root at require time.
  const pathsModule = require.resolve('../paths.cjs');
  delete require.cache[pathsModule];
  const moduleExports = require(SCRIPT_PATH);
  return {
    moduleExports,
    restore() {
      for (const [key, value] of Object.entries(previous)) {
        if (value === undefined) delete process.env[key];
        else process.env[key] = value;
      }
      delete require.cache[SCRIPT_PATH];
      delete require.cache[pathsModule];
    },
  };
}

test('autoLinkFiles is a no-op when obsidian_mode is false', (t) => {
  const { vault, note } = createVault(t, { obsidianMode: false });
  const before = fs.readFileSync(note, 'utf-8');
  const { moduleExports, restore } = freshModule(vault);
  t.after(restore);
  const result = moduleExports.autoLinkFiles([note]);
  assert.equal(result.skipped, 'obsidian_mode_off');
  assert.equal(result.changed, 0);
  assert.equal(fs.readFileSync(note, 'utf-8'), before);
});

test('autoLinkFiles links names across files when obsidian_mode is true', (t) => {
  const { vault, note } = createVault(t, { obsidianMode: true });
  const { moduleExports, restore } = freshModule(vault);
  t.after(restore);
  const result = moduleExports.autoLinkFiles([note]);
  assert.equal(result.skipped, null);
  assert.equal(result.changed, 1);
  assert.match(fs.readFileSync(note, 'utf-8'), /\[\[.*Jane_Doe\|Jane Doe\]\]/);
  // Second run: idempotent through the batch API too.
  const again = moduleExports.autoLinkFiles([note]);
  assert.equal(again.changed, 0);
});

test('autoLinkFiles survives an unreadable file and still links the rest', (t) => {
  const { vault, note } = createVault(t, { obsidianMode: true });
  const { moduleExports, restore } = freshModule(vault);
  t.after(restore);
  const missing = path.join(vault, '00-Inbox', 'Meetings', 'missing.md');
  const result = moduleExports.autoLinkFiles([missing, note]);
  assert.equal(result.changed, 1);
  assert.equal(result.results.length, 2);
  assert.ok(result.results[0].error);
});

test('CLI exits cleanly without linking when obsidian_mode is false', (t) => {
  const { vault, note } = createVault(t, { obsidianMode: false });
  const before = fs.readFileSync(note, 'utf-8');
  const run = spawnSync(process.execPath, [SCRIPT_PATH, note], {
    cwd: vault,
    encoding: 'utf-8',
    env: { CLAUDE_PROJECT_DIR: vault, VAULT_PATH: vault, PATH: '/usr/bin:/bin' },
    timeout: 10_000,
  });
  assert.equal(run.status, 0);
  assert.match(run.stdout, /obsidian_mode is false/);
  assert.equal(fs.readFileSync(note, 'utf-8'), before);
});
