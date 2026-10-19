'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const { listMeetingSourceFiles } = require('../meeting-cache-builder.cjs');
const { checkMeetingQueue } = require('../meeting-queue-check.cjs');
const { detectExistingDailyPlans, defaultPaths, resolveDailyPlansDir } = require('../../../core/runtime/paths.cjs');

const NOW = Date.parse('2026-07-27T12:00:00Z');
const TODAY = new Date(NOW).toISOString().slice(0, 10);

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-archive-hooks-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  return root;
}

function writePlan(directory, day) {
  fs.mkdirSync(directory, { recursive: true });
  fs.writeFileSync(
    path.join(directory, `${day}.md`),
    `---\ndate: ${day}\ntype: daily-plan\n---\n# Daily Plan — ${day}\n`,
  );
}

test('defaultPaths expose archived meeting and daily-plan homes', () => {
  const paths = defaultPaths('/vault');
  assert.equal(paths.ARCHIVED_MEETINGS_DIR, path.join('/vault', '07-Archives', 'Meetings'));
  assert.equal(
    paths.ARCHIVED_DAILY_PLANS_DIR,
    path.join('/vault', '07-Archives', 'Plans', 'Daily'),
  );
});

test('meeting-cache-builder lists archived notes without changing the write target', (t) => {
  const vault = fixture(t);
  const live = path.join(vault, '00-Inbox', 'Meetings', TODAY);
  const archived = path.join(vault, '07-Archives', 'Meetings');
  fs.mkdirSync(live, { recursive: true });
  fs.mkdirSync(archived, { recursive: true });
  const liveNote = path.join(live, 'live.md');
  const archivedNote = path.join(archived, 'old.md');
  fs.writeFileSync(liveNote, '# Live\n');
  fs.writeFileSync(archivedNote, '# Old\n');
  fs.writeFileSync(path.join(archived, 'README.md'), '# Archived Meetings\n');

  const files = listMeetingSourceFiles(live, archived);
  assert.deepEqual(new Set(files), new Set([liveNote, archivedNote]));
});

test('meeting-queue-check uses archived granola ids to hide a queued re-import', (t) => {
  const root = fixture(t);
  const archived = path.join(root, '07-Archives', 'Meetings');
  fs.mkdirSync(archived, { recursive: true });
  fs.writeFileSync(
    path.join(archived, '2026-01-15 - Old.md'),
    [
      '---',
      'date: 2026-01-15',
      'granola_id: meeting-1',
      'ai_analyzed: true',
      '---',
      '',
      '# Old',
      '',
      '<!-- tasks-extracted: 2026-01-15T11:00:00Z -->',
      '',
    ].join('\n'),
  );
  const queue = path.join(root, '00-Inbox', 'Meetings', 'queue');
  fs.mkdirSync(queue, { recursive: true });
  fs.writeFileSync(
    path.join(queue, 'meeting-1.json'),
    JSON.stringify({ id: 'meeting-1', title: 'Already archived' }),
  );

  const result = checkMeetingQueue({ vaultRoot: root, now: NOW });
  assert.deepEqual(result, { count: 0, lines: [] });
});

test('CJS daily-plan detection never picks archived Plans/Daily as live', (t) => {
  const vault = fixture(t);
  writePlan(path.join(vault, '07-Archives', 'Plans', 'Daily'), '2026-09-27');
  assert.equal(detectExistingDailyPlans(vault), null);
  assert.equal(
    resolveDailyPlansDir(vault),
    path.join(vault, '00-Inbox', 'Daily_Plans'),
  );
});

test('CJS daily-plan detection still keeps legacy 07-Archives/Plans', (t) => {
  const vault = fixture(t);
  writePlan(path.join(vault, '07-Archives', 'Plans'), '2026-09-28');
  writePlan(path.join(vault, '07-Archives', 'Plans', 'Daily'), '2026-09-27');
  assert.equal(detectExistingDailyPlans(vault), '07-Archives/Plans');
});

test('scan-vault suggests a meetings_archive collection', (t) => {
  const vault = fixture(t);
  const archived = path.join(vault, '07-Archives', 'Meetings');
  fs.mkdirSync(archived, { recursive: true });
  for (let i = 1; i <= 5; i += 1) {
    fs.writeFileSync(path.join(archived, `note-${i}.md`), `# Meeting ${i}\n`);
  }
  const script = path.resolve(__dirname, '../../../.scripts/semantic-search/scan-vault.cjs');
  const scan = spawnSync(process.execPath, [script], {
    env: { ...process.env, VAULT_PATH: vault },
    encoding: 'utf8',
  });
  assert.equal(scan.status, 0, scan.stderr);
  const result = JSON.parse(scan.stdout);
  const archive = result.candidates.find((item) => item.name === 'meetings_archive');
  assert.ok(archive, 'meetings_archive should be a candidate');
  assert.equal(archive.fileCount, 5);

  const health = spawnSync(process.execPath, [script, '--health-check'], {
    env: { ...process.env, VAULT_PATH: vault },
    encoding: 'utf8',
  });
  assert.equal(health.status, 0, health.stderr);
  const healthResult = JSON.parse(health.stdout);
  assert.ok(
    healthResult.suggestions.some((line) => line.includes('meetings_archive')),
    healthResult.suggestions.join('\n'),
  );
});

test('enable-semantic-search skill table lists meetings_archive', () => {
  const skillPath = path.resolve(__dirname, '../../../.claude/skills/enable-semantic-search/SKILL.md');
  const text = fs.readFileSync(skillPath, 'utf8');
  assert.match(text, /`meetings_archive`/);
  assert.match(text, /07-Archives\/Meetings/);
});
