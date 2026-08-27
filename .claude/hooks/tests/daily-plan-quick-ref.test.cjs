const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { loadPaths } = require('../paths.cjs');

const HOOK = path.resolve(__dirname, '../daily-plan-quick-ref.cjs');
const SOURCE_PATHS = loadPaths();

function remapVaultPath(vault, sourcePath) {
  return path.join(vault, path.relative(SOURCE_PATHS.VAULT_ROOT, sourcePath));
}

function createVault(t) {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-daily-plan-quickref-'));
  const planDir = remapVaultPath(vault, SOURCE_PATHS.DAILY_PLANS_DIR);
  fs.mkdirSync(planDir, { recursive: true });
  t.after(() => fs.rmSync(vault, { recursive: true, force: true }));
  return { vault, planDir };
}

function runHook(vault) {
  return spawnSync(process.execPath, [HOOK], {
    cwd: vault,
    encoding: 'utf8',
    env: {
      ...process.env,
      CLAUDE_PROJECT_DIR: vault,
      VAULT_PATH: vault,
    },
  });
}

test('quickref is written next to the inbox daily plan, not an archived copy', (t) => {
  const { vault, planDir } = createVault(t);
  const today = new Date().toISOString().split('T')[0];
  fs.writeFileSync(
    path.join(planDir, `${today}.md`),
    ['# Daily Plan', '', '## Today\'s Focus', '- Ship the inbox path fix', ''].join('\n'),
    'utf8',
  );

  const result = runHook(vault);

  assert.equal(result.status, 0, result.stderr);
  const quickref = path.join(planDir, `${today}-quickref.md`);
  assert.equal(fs.existsSync(quickref), true);
  const body = fs.readFileSync(quickref, 'utf8');
  assert.match(body, /Ship the inbox path fix/);
  assert.equal(fs.existsSync(path.join(vault, '00-Inbox', 'Daily_Prep', `${today}-quickref.md`)), false);
  assert.equal(fs.existsSync(path.join(vault, '07-Archives', 'Plans', `${today}-quickref.md`)), false);
});

test('missing inbox daily plan is a silent no-op', (t) => {
  const { vault } = createVault(t);
  const result = runHook(vault);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.stdout, '');
});
