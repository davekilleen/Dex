/**
 * End-to-end tests for meeting-cache-builder.cjs.
 *
 * The builder is a CLI-style hook (runs main() on load), so each test spawns
 * it against a throwaway vault via CLAUDE_PROJECT_DIR and asserts on the
 * System/Memory/meeting-cache.json it writes.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const SCRIPT = path.join(__dirname, '..', 'meeting-cache-builder.cjs');

function isoDaysAgo(days) {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return d.toISOString().slice(0, 10);
}

function makeVault(files = {}) {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-mcache-'));
  fs.mkdirSync(path.join(vault, '00-Inbox', 'Meetings'), { recursive: true });
  for (const [relPath, content] of Object.entries(files)) {
    const abs = path.join(vault, relPath);
    fs.mkdirSync(path.dirname(abs), { recursive: true });
    fs.writeFileSync(abs, content);
  }
  return vault;
}

function runBuilder(vault, args = []) {
  return spawnSync('node', [SCRIPT, ...args], {
    encoding: 'utf-8',
    env: { ...process.env, CLAUDE_PROJECT_DIR: vault },
  });
}

function readCache(vault) {
  return JSON.parse(
    fs.readFileSync(path.join(vault, 'System', 'Memory', 'meeting-cache.json'), 'utf-8')
  );
}

const RECENT = isoDaysAgo(5);

const MEETING_MD = `---
date: ${RECENT}
participants: [Jane Roe, Bob Jones]
company: Acme Corp
---
# Acme Q3 Sync

## Key Decisions
- [x] Agreed to move forward with the pilot ^task-20260601-001
- **Budget** approved for [[Projects/Acme_Rollout|the rollout]]

## Action Items
- [ ] Send recap to [[Jane_Roe|Jane]] by August

## Summary
- Team is aligned and on track, strong momentum
`;

test('builds a structured cache entry from a meeting file', () => {
  const vault = makeVault({
    [`00-Inbox/Meetings/${RECENT} - Acme Sync.md`]: MEETING_MD,
  });

  const result = runBuilder(vault);
  assert.equal(result.status, 0);

  const cache = readCache(vault);
  assert.equal(cache.meetings.length, 1);
  const m = cache.meetings[0];
  assert.equal(m.title, 'Acme Q3 Sync');
  assert.equal(m.date, RECENT);
  assert.deepEqual(m.attendees, ['Jane Roe', 'Bob Jones']);
  assert.equal(m.company, 'Acme Corp');
  // Checkbox, task-ID, wikilink, and bold markers are stripped
  assert.deepEqual(m.decisions, [
    'Agreed to move forward with the pilot',
    'Budget approved for the rollout',
  ]);
  assert.deepEqual(m.action_items, ['Send recap to Jane by August']);
  assert.equal(m.sentiment, 'positive');
  // "by August" resolves against the meeting's year
  assert.equal(m.follow_up_date, `${RECENT.slice(0, 4)}-08-01`);
  assert.ok(m.key_points.length > 0); // falls back to ## Summary
});

test('derives date and title from filename when content lacks them', () => {
  const vault = makeVault({
    [`00-Inbox/Meetings/${RECENT} - Vendor Demo.md`]: 'Just some unstructured notes.\n',
  });

  runBuilder(vault);
  const m = readCache(vault).meetings[0];
  assert.equal(m.date, RECENT);
  assert.equal(m.title, 'Vendor Demo');
  assert.equal(m.sentiment, 'neutral');
});

test('negative sentiment is detected', () => {
  const vault = makeVault({
    [`00-Inbox/Meetings/${RECENT} - Escalation.md`]:
      '# Escalation\nProject is blocked and the customer is frustrated.\n',
  });

  runBuilder(vault);
  assert.equal(readCache(vault).meetings[0].sentiment, 'negative');
});

test('meetings older than 90 days are skipped', () => {
  const old = isoDaysAgo(120);
  const vault = makeVault({
    [`00-Inbox/Meetings/${old} - Ancient Sync.md`]: '# Ancient Sync\n',
    [`00-Inbox/Meetings/${RECENT} - Fresh Sync.md`]: '# Fresh Sync\n',
  });

  runBuilder(vault);
  const cache = readCache(vault);
  assert.equal(cache.meetings.length, 1);
  assert.equal(cache.meetings[0].title, 'Fresh Sync');
});

test('second run skips unchanged files, --rebuild reprocesses', () => {
  const vault = makeVault({
    [`00-Inbox/Meetings/${RECENT} - Sync.md`]: '# Sync\n',
  });

  runBuilder(vault);
  const first = readCache(vault).meetings[0].cached_at;

  runBuilder(vault);
  assert.equal(readCache(vault).meetings[0].cached_at, first, 'unchanged file was re-parsed');

  const rebuilt = runBuilder(vault, ['--rebuild']);
  assert.equal(rebuilt.status, 0);
  assert.notEqual(readCache(vault).meetings[0].cached_at, first, '--rebuild did not re-parse');
});

test('stale cache entries are pruned on the next run', () => {
  const vault = makeVault({
    [`00-Inbox/Meetings/${RECENT} - Sync.md`]: '# Sync\n',
  });
  // Seed a cache containing an entry older than the prune window
  const cacheFile = path.join(vault, 'System', 'Memory', 'meeting-cache.json');
  fs.mkdirSync(path.dirname(cacheFile), { recursive: true });
  fs.writeFileSync(
    cacheFile,
    JSON.stringify({
      version: 1,
      last_updated: null,
      meetings: [
        {
          date: isoDaysAgo(200),
          title: 'Stale',
          source_file: '00-Inbox/Meetings/old.md',
        },
      ],
      _file_mtimes: { '00-Inbox/Meetings/old.md': 123 },
    })
  );

  runBuilder(vault);
  const cache = readCache(vault);
  assert.deepEqual(cache.meetings.map((m) => m.title), ['Sync']);
  assert.ok(!('00-Inbox/Meetings/old.md' in cache._file_mtimes));
});

test('meetings are sorted newest first', () => {
  const vault = makeVault({
    [`00-Inbox/Meetings/${isoDaysAgo(10)} - Older.md`]: '# Older\n',
    [`00-Inbox/Meetings/${isoDaysAgo(2)} - Newer.md`]: '# Newer\n',
  });

  runBuilder(vault);
  assert.deepEqual(
    readCache(vault).meetings.map((m) => m.title),
    ['Newer', 'Older']
  );
});

test('exits cleanly when meetings directory is missing', () => {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-mcache-empty-'));
  const result = runBuilder(vault);
  assert.equal(result.status, 0);
  assert.match(result.stderr, /No meetings directory found/);
  assert.ok(!fs.existsSync(path.join(vault, 'System', 'Memory', 'meeting-cache.json')));
});

test('exits cleanly when directory has no meeting files', () => {
  const vault = makeVault({ '00-Inbox/Meetings/README.md': '# readme\n' });
  const result = runBuilder(vault);
  assert.equal(result.status, 0);
  assert.match(result.stderr, /No meeting files found/);
});
