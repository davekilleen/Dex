'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const os = require('os');
const path = require('path');
const yaml = require('js-yaml');
const { collectExistingMeetingIds } = require('../sync-from-granola.cjs');
const { meetingSignals, gardenEntities } = require('../lib/gardener.cjs');
const { recordObservations } = require('../lib/contacts-state.cjs');
const { verifyEntities } = require('../verify-entities.cjs');

function withVault(fn) {
  const oldVault = process.env.VAULT_PATH;
  const oldProject = process.env.CLAUDE_PROJECT_DIR;
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-archive-readers-'));
  process.env.VAULT_PATH = vault;
  delete process.env.CLAUDE_PROJECT_DIR;
  try {
    return fn(vault);
  } finally {
    if (oldVault === undefined) delete process.env.VAULT_PATH;
    else process.env.VAULT_PATH = oldVault;
    if (oldProject === undefined) delete process.env.CLAUDE_PROJECT_DIR;
    else process.env.CLAUDE_PROJECT_DIR = oldProject;
    fs.rmSync(vault, { recursive: true, force: true });
  }
}

function writeNote(filePath, fields, body = '# Meeting\n') {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `---\n${yaml.dump(fields)}---\n${body}`);
}

test('collectExistingMeetingIds treats archived granola ids as already imported', () => {
  withVault((vault) => {
    const live = path.join(vault, '00-Inbox', 'Meetings');
    const archived = path.join(vault, '07-Archives', 'Meetings', '2025');
    writeNote(path.join(live, '2026-09-02 - Live.md'), {
      date: '2026-09-02',
      granola_id: 'live-1',
    });
    writeNote(path.join(archived, '2025-01-15 - Old.md'), {
      date: '2025-01-15',
      granola_id: 'archived-1',
    });

    const ids = collectExistingMeetingIds(live, [path.join(vault, '07-Archives', 'Meetings')]);
    assert.equal(ids.has('live-1'), true);
    assert.equal(ids.has('archived-1'), true);
  });
});

test('meetingSignals includes archived notes', () => {
  withVault((vault) => {
    const archived = path.join(vault, '07-Archives', 'Meetings');
    writeNote(path.join(archived, '2026-07-10 - Launch.md'), {
      title: 'Launch review',
      date: '2026-07-10',
      attendees: [{ name: 'Jane Doe', email: 'jane@acme.com', location: 'external' }],
    }, '# Launch review\n\nArchived pricing notes.\n');

    const meetings = meetingSignals(archived);
    assert.equal(meetings.length, 1);
    assert.equal(meetings[0].title, 'Launch review');
    assert.equal(meetings[0].emails.has('jane@acme.com'), true);
  });
});

test('gardener reads archived meetings when building a person signal', async () => {
  await withVault(async (vault) => {
    const { renderPersonPage } = require('../../lib/entity-pages.cjs');
    const { installEntityEngineStub } = require('../../lib/tests/entity-engine-test-helper.cjs');
    const oldPython = process.env.DEX_PYTHON;
    process.env.DEX_PYTHON = installEntityEngineStub(vault);
    const people = path.join(vault, '05-Areas', 'People', 'External');
    fs.mkdirSync(people, { recursive: true });
    fs.writeFileSync(
      path.join(people, 'Jane_Doe.md'),
      renderPersonPage('Jane Doe', 'Product Lead', 'Acme', ['jane@acme.com']),
    );
    writeNote(path.join(vault, '07-Archives', 'Meetings', '2026-07-10 - Launch.md'), {
      title: 'Launch review',
      date: '2026-07-10',
      attendees: [{ name: 'Jane Doe', email: 'jane@acme.com', location: 'external' }],
    }, '# Launch review\n\nArchived pricing notes.\n');

    let signal = '';
    await gardenEntities({
      generate: async (prompt) => {
        signal = prompt;
        return '- Product leader at Acme.\n- Discussing the launch plan.';
      },
      now: new Date('2026-07-12T12:00:00.000Z'),
      limit: 1,
    });
    assert.match(signal, /Launch review/);
    assert.match(signal, /Archived pricing notes/);
    if (oldPython === undefined) delete process.env.DEX_PYTHON;
    else process.env.DEX_PYTHON = oldPython;
  });
});

test('verify-entities counts attendees from archived meetings', () => {
  withVault((vault) => {
    fs.mkdirSync(path.join(vault, 'System'), { recursive: true });
    fs.writeFileSync(path.join(vault, 'System', 'user-profile.yaml'), yaml.dump({
      entity_creation: { mode: 'auto' },
    }));
    const attendees = [
      { name: 'Archive Person', email: 'archive@example.com', location: 'external' },
    ];
    writeNote(path.join(vault, '07-Archives', 'Meetings', '2026-06-10 - Old.md'), {
      date: '2026-06-10',
      attendees,
    });
    recordObservations('m1', { date: '2026-06-01', hasTranscript: false, attendees });
    recordObservations('m2', { date: '2026-06-08', hasTranscript: false, attendees });

    const { report } = verifyEntities({ days: 14, now: new Date('2026-06-10T12:00:00Z') });
    assert.equal(report.counts.tracking, 1);
  });
});
