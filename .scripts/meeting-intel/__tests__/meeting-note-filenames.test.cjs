'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {
  createBasicMeetingNote,
  createMeetingNote,
  resolveMeetingNoteTarget,
} = require('../sync-from-granola.cjs');

const PROFILE = { name: 'Owner', obsidian_mode: false };
const PILLARS = ['General'];
const ANALYSIS = '## Summary\n\nUseful discussion.\n\n## Pillar Assignment\n\nGeneral\n';

function meeting(id) {
  return {
    id,
    title: 'Weekly Sync',
    createdAt: '2026-07-12T10:00:00Z',
    notes: 'Detailed notes for a real meeting.',
    transcript: '',
    participants: [],
    attendees: [],
    owner: null,
    company: '',
    duration: null,
    source: 'api',
  };
}

function assertCollisionSafety(t, label, writer) {
  const meetingsDir = fs.mkdtempSync(path.join(os.tmpdir(), `dex-${label}-notes-`));
  t.after(() => fs.rmSync(meetingsDir, { recursive: true, force: true }));
  const options = { meetingsDir, logger: () => {} };

  const first = writer(meeting('11111111-alpha'), options);
  const second = writer(meeting('22222222-beta'), options);
  const rerun = writer(meeting('22222222-beta'), options);

  const datedDir = path.join(meetingsDir, '2026-07-12');
  const files = fs.readdirSync(datedDir).sort();
  assert.equal(files.length, 2, `${label} must keep both distinct meetings`);
  assert.equal(path.basename(first.filepath), 'weekly-sync.md');
  assert.equal(path.basename(second.filepath), 'weekly-sync-22222222.md');
  assert.equal(rerun.filepath, second.filepath, `${label} rerun must reuse its suffixed note`);
  assert.match(fs.readFileSync(first.filepath, 'utf-8'), /granola_id: "11111111-alpha"/);
  assert.match(fs.readFileSync(second.filepath, 'utf-8'), /granola_id: "22222222-beta"/);
}

test('AI meeting notes suffix only a different same-title meeting and rerun idempotently', (t) => {
  assertCollisionSafety(t, 'ai', (item, options) => (
    createMeetingNote(item, ANALYSIS, PROFILE, PILLARS, options)
  ));
});

test('basic meeting notes suffix only a different same-title meeting and rerun idempotently', (t) => {
  assertCollisionSafety(t, 'basic', (item, options) => (
    createBasicMeetingNote(item, PROFILE, options)
  ));
});

test('quoted Granola id in YAML frontmatter still owns the clean filename', (t) => {
  const meetingsDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-frontmatter-owner-'));
  t.after(() => fs.rmSync(meetingsDir, { recursive: true, force: true }));

  const datedDir = path.join(meetingsDir, '2026-07-12');
  const cleanPath = path.join(datedDir, 'weekly-sync.md');
  fs.mkdirSync(datedDir, { recursive: true });
  fs.writeFileSync(
    cleanPath,
    '---\ngranola_id: "same-id" # valid YAML comment\n---\n\n# Weekly Sync\n',
  );

  const target = resolveMeetingNoteTarget(meeting('same-id'), meetingsDir);

  assert.equal(target.filepath, cleanPath);
});

test('Granola id text outside frontmatter cannot claim the clean filename', (t) => {
  const meetingsDir = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-body-id-lookalike-'));
  t.after(() => fs.rmSync(meetingsDir, { recursive: true, force: true }));

  const datedDir = path.join(meetingsDir, '2026-07-12');
  const cleanPath = path.join(datedDir, 'weekly-sync.md');
  fs.mkdirSync(datedDir, { recursive: true });
  fs.writeFileSync(cleanPath, '# Manual note\n\ngranola_id: same-id\n');

  const target = resolveMeetingNoteTarget(meeting('same-id'), meetingsDir);

  assert.equal(path.basename(target.filepath), 'weekly-sync-same-id.md');
});
