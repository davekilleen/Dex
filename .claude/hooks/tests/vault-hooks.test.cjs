/**
 * Tests for the remaining vault hooks:
 *   - post-meeting-person-update.cjs (CLAUDE_HOOK_CONTEXT env input)
 *   - career-evidence-capture.cjs    (CLAUDE_HOOK_CONTEXT env input)
 *   - daily-plan-quick-ref.cjs       (reads Archive/Plans/<today>.md)
 *   - ensure-mcp-user-scope.cjs      (stdin JSON, permission decision)
 *   - maintenance.cjs                (vault health report on stdout)
 *
 * Each spawns the real hook against a throwaway vault.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const HOOKS = path.join(__dirname, '..');
const TODAY = new Date().toISOString().split('T')[0];

function makeVault(files = {}) {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-vhooks-'));
  for (const [relPath, content] of Object.entries(files)) {
    const abs = path.join(vault, relPath);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, content);
  }
  return vault;
}

function runHook(script, { vault, filePath, stdin, env = {} } = {}) {
  const hookEnv = { ...process.env, CLAUDE_PROJECT_DIR: vault, ...env };
  if (filePath) {
    hookEnv.CLAUDE_HOOK_CONTEXT = JSON.stringify({ tool_input: { file_path: filePath } });
  }
  return spawnSync('node', [path.join(HOOKS, script)], {
    input: stdin,
    encoding: 'utf-8',
    env: hookEnv,
  });
}

// ---------------------------------------------------------------------------
// post-meeting-person-update.cjs
// ---------------------------------------------------------------------------

test('post-meeting hook appends meeting refs to mentioned person pages', () => {
  const vault = makeVault({
    'People/External/Jane_Roe.md': '# Jane Roe\n\n## Meetings\n',
    'People/Internal/Bob_Jones.md': '# Bob Jones\n',
    [`Inbox/Meetings/${TODAY} - Acme Sync.md`]:
      'Met with Bob Jones and [[Jane_Roe]] about the rollout.\n',
  });
  const meeting = path.join(vault, 'Inbox', 'Meetings', `${TODAY} - Acme Sync.md`);

  const result = runHook('post-meeting-person-update.cjs', { vault, filePath: meeting });

  assert.equal(result.status, 0);
  assert.match(result.stdout, /Updated 2 person page/);
  const jane = fs.readFileSync(path.join(vault, 'People/External/Jane_Roe.md'), 'utf8');
  // Wikilink mention lands under the existing ## Meetings section
  assert.match(jane, /## Meetings\n- \[\[.*Acme Sync\]\] \(\d{4}-\d{2}-\d{2}\)/);
  const bob = fs.readFileSync(path.join(vault, 'People/Internal/Bob_Jones.md'), 'utf8');
  // Plain "Met with Bob Jones" mention appends at end (no Meetings section)
  assert.match(bob, /- \[\[.*Acme Sync\]\]/);
});

test('post-meeting hook does not add duplicate references', () => {
  const vault = makeVault({
    'People/External/Jane_Roe.md': '# Jane Roe\n',
    [`Inbox/Meetings/${TODAY} - Sync.md`]: 'Notes on [[Jane_Roe]].\n',
  });
  const meeting = path.join(vault, 'Inbox', 'Meetings', `${TODAY} - Sync.md`);

  runHook('post-meeting-person-update.cjs', { vault, filePath: meeting });
  runHook('post-meeting-person-update.cjs', { vault, filePath: meeting });

  const jane = fs.readFileSync(path.join(vault, 'People/External/Jane_Roe.md'), 'utf8');
  const refs = jane.match(/- \[\[.*Sync\]\]/g) || [];
  assert.equal(refs.length, 1);
});

test('post-meeting hook ignores non-meeting files', () => {
  const vault = makeVault({
    'People/External/Jane_Roe.md': '# Jane Roe\n',
    'Projects/Notes.md': 'Mentions [[Jane_Roe]].\n',
  });

  const result = runHook('post-meeting-person-update.cjs', {
    vault, filePath: path.join(vault, 'Projects', 'Notes.md'),
  });

  assert.equal(result.status, 0);
  assert.equal(result.stdout, '');
  assert.equal(fs.readFileSync(path.join(vault, 'People/External/Jane_Roe.md'), 'utf8'), '# Jane Roe\n');
});

// ---------------------------------------------------------------------------
// career-evidence-capture.cjs
// ---------------------------------------------------------------------------

test('career hook logs achievements with detected skill areas', () => {
  const vault = makeVault({
    'Career/2026-07-01 - Big Win.md':
      '# Big Win\nClosed the Acme deal, increased territory revenue 40% and improved pipeline coverage.\n',
  });

  const result = runHook('career-evidence-capture.cjs', {
    vault, filePath: path.join(vault, 'Career', '2026-07-01 - Big Win.md'),
  });

  assert.equal(result.status, 0);
  assert.match(result.stdout, /Career evidence captured/);
  const log = fs.readFileSync(path.join(vault, '05-Areas/Career/Evidence_Log.md'), 'utf8');
  assert.match(log, /\| Date \| Skill Area \| Source \| Description \|/);
  assert.match(log, /Sales/);
  assert.match(log, /\[\[2026-07-01 - Big Win\]\]/);
  assert.match(log, /increased territory revenue 40%/);
});

test('career hook stays silent without achievement markers', () => {
  const vault = makeVault({
    'Career/notes.md': '# Random musings\nSome text with no metrics at all.\n',
  });

  const result = runHook('career-evidence-capture.cjs', {
    vault, filePath: path.join(vault, 'Career', 'notes.md'),
  });

  assert.equal(result.status, 0);
  assert.ok(!fs.existsSync(path.join(vault, '05-Areas/Career/Evidence_Log.md')));
});

test('career hook ignores files outside Career/', () => {
  const vault = makeVault({
    'Projects/deal.md': 'Increased revenue 40%\n',
  });

  const result = runHook('career-evidence-capture.cjs', {
    vault, filePath: path.join(vault, 'Projects', 'deal.md'),
  });

  assert.equal(result.status, 0);
  assert.ok(!fs.existsSync(path.join(vault, '05-Areas/Career/Evidence_Log.md')));
});

// ---------------------------------------------------------------------------
// daily-plan-quick-ref.cjs
// ---------------------------------------------------------------------------

test('quick-ref hook condenses the daily plan', () => {
  const plan = [
    '# Daily Plan',
    '## Top Focus',
    '1. [Close Acme quote](link)',
    '2. [Prep Globex demo](link)',
    '3. [Call vendor](link)',
    '4. [Should be cut — max 3](link)',
    '## Negotiation',
    '| Deal | Next step |',
    '|------|-----------|',
    '| Acme TruLaser | Confirm config |',
    '## Do Today',
    '- [ ] Send proposal ^task-20260707-001',
    '- [ ] Log activity',
    '## Heads Up',
    '- Lease expiry: Gwynedd in 45 days',
  ].join('\n');
  const vault = makeVault({ [`Archive/Plans/${TODAY}.md`]: plan });

  const result = runHook('daily-plan-quick-ref.cjs', { vault });

  assert.equal(result.status, 0);
  const quickRefPath = path.join(vault, 'Inbox', 'Daily_Plans', `${TODAY}-quickref.md`);
  const quickRef = fs.readFileSync(quickRefPath, 'utf8');
  assert.match(quickRef, /# Quick Ref/);
  assert.match(quickRef, /\[Close Acme quote\]/);
  assert.ok(!quickRef.includes('Should be cut'), 'focus items must cap at 3');
  assert.match(quickRef, /- Acme TruLaser — Confirm config/);
  assert.match(quickRef, /- \[ \] Send proposal/);
  assert.match(quickRef, /Lease expiry: Gwynedd in 45 days/);
});

test('quick-ref hook is a no-op without a plan for today', () => {
  const vault = makeVault({});
  const result = runHook('daily-plan-quick-ref.cjs', { vault });
  assert.equal(result.status, 0);
  assert.ok(!fs.existsSync(path.join(vault, 'Inbox', 'Daily_Plans', `${TODAY}-quickref.md`)));
});

// ---------------------------------------------------------------------------
// ensure-mcp-user-scope.cjs
// ---------------------------------------------------------------------------

function runScopeHook(command, env = {}) {
  return spawnSync('node', [path.join(HOOKS, 'ensure-mcp-user-scope.cjs')], {
    input: JSON.stringify({ tool_input: { command } }),
    encoding: 'utf-8',
    env: { ...process.env, CLAUDE_CODE_NONINTERACTIVE: '', ...env },
  });
}

test('scope hook allows explicit user/project scope and unrelated commands', () => {
  assert.equal(runScopeHook('claude mcp add --scope user foo -- npx foo').stdout, '');
  assert.equal(runScopeHook('claude mcp add --scope project foo -- npx foo').stdout, '');
  assert.equal(runScopeHook('git status').stdout, '');
});

test('scope hook asks interactively and denies headless without scope', () => {
  const ask = JSON.parse(runScopeHook('claude mcp add foo -- npx foo').stdout);
  assert.equal(ask.hookSpecificOutput.permissionDecision, 'ask');
  assert.match(ask.hookSpecificOutput.permissionDecisionReason, /--scope user/);

  const deny = JSON.parse(
    runScopeHook('claude mcp add foo -- npx foo', { CLAUDE_CODE_NONINTERACTIVE: '1' }).stdout
  );
  assert.equal(deny.hookSpecificOutput.permissionDecision, 'deny');
});

// ---------------------------------------------------------------------------
// maintenance.cjs
// ---------------------------------------------------------------------------

test('maintenance report finds stale inbox files, broken links, and orphans', () => {
  const vault = makeVault({
    'Inbox/Ideas/old-idea.md': '# Old idea\n',
    'Inbox/Ideas/fresh-idea.md': '# Fresh idea\n',
    'Projects/Acme.md': 'See [[Missing_Page]] and [[Jane_Roe]].\n',
    'People/External/Jane_Roe.md': '# Jane Roe\n',
    'People/External/Old_Contact.md': '# Old Contact\n',
    '03-Tasks/Tasks.md': '- [ ] Follow up with Jane_Roe ^task-20260707-001\n',
  });
  // Age one inbox file past the 30-day threshold
  const oldTime = new Date(Date.now() - 40 * 86400000);
  fs.utimesSync(path.join(vault, 'Inbox/Ideas/old-idea.md'), oldTime, oldTime);

  const result = spawnSync('node', [path.join(HOOKS, 'maintenance.cjs')], {
    encoding: 'utf-8',
    env: { ...process.env, CLAUDE_PROJECT_DIR: vault },
  });

  assert.equal(result.status, 0);
  assert.match(result.stdout, /## Stale Inbox Files \(>30 days\): 1/);
  assert.match(result.stdout, /old-idea\.md \(40 days\)/);
  assert.match(result.stdout, /## Broken WikiLinks: 1/);
  assert.match(result.stdout, /\[\[Missing_Page\]\]/);
  // Jane is referenced in Tasks.md; Old_Contact is not
  assert.match(result.stdout, /## Orphaned Person Pages: 1/);
  assert.match(result.stdout, /Old_Contact\.md/);
});

test('maintenance report declares a healthy vault healthy', () => {
  const vault = makeVault({
    'Inbox/Ideas/fresh.md': '# Fresh\n',
    'People/External/Jane_Roe.md': '# Jane Roe\n',
    '03-Tasks/Tasks.md': '- [ ] Ping Jane_Roe\n',
  });

  const result = spawnSync('node', [path.join(HOOKS, 'maintenance.cjs')], {
    encoding: 'utf-8',
    env: { ...process.env, CLAUDE_PROJECT_DIR: vault },
  });

  assert.equal(result.status, 0);
  assert.match(result.stdout, /Total issues: 0/);
  assert.match(result.stdout, /Vault is healthy!/);
});
