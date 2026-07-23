'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const childProcess = require('node:child_process');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  deadLetterPath,
  flushEntityOps,
  loadDeadLetters,
  pendingStorePath,
  requeueDeadLetters,
} = require('../entity-engine-client.cjs');
const {
  mergeFrontmatterText,
  parseEntityPage,
  renderPersonPage,
  replaceMachineRegion,
} = require('../entity-pages.cjs');
const {
  beginEntityPhase,
  completeEntityPhases,
} = require('../../meeting-intel/lib/entity-phase.cjs');

const REPO_ROOT = path.resolve(__dirname, '../../..');

function makeVault(t) {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-engine-client-'));
  const python = path.join(vault, 'python');
  fs.writeFileSync(python, '#!/bin/sh\nexit 0\n');
  fs.chmodSync(python, 0o755);
  t.after(() => fs.rmSync(vault, { recursive: true, force: true }));
  return { vault, python };
}

function createOp(vault) {
  const content = '# Jane Example\n';
  return {
    op: 'create',
    path: path.join(vault, '05-Areas', 'People', 'External', 'Jane_Example.md'),
    content,
    allowed_root: vault,
    target_fingerprint: crypto.createHash('sha256').update(content).digest('hex'),
  };
}

function atAttempt(attempt) {
  return new Date(Date.UTC(2026, 6, 1, attempt * 24));
}

function resolveRealPython() {
  const candidates = [
    process.env.DEX_TEST_PYTHON,
    process.env.DEX_PYTHON,
    path.join(REPO_ROOT, '.venv', 'bin', 'python'),
    path.join(REPO_ROOT, '..', 'clean-venv', 'bin', 'python'),
    'python3',
  ].filter(Boolean);
  for (const candidate of candidates) {
    const probe = childProcess.spawnSync(
      candidate,
      ['-c', 'import sys, yaml; print(sys.executable)'],
      { encoding: 'utf8' },
    );
    if (probe.status === 0) return probe.stdout.trim();
  }
  throw new Error('No Python interpreter with PyYAML is available for parity tests');
}

function realCliSpawn(command, args, options) {
  return childProcess.spawnSync(command, args, {
    ...options,
    cwd: REPO_ROOT,
  });
}

function hookIntent(relativePath, line, date) {
  return {
    kind: 'hook-interaction',
    interaction: { path: relativePath, line, date },
  };
}

function touchIntent(touches) {
  return { kind: 'touch-log', touches };
}

function appendLegacyInteraction(original, line) {
  const heading = /^## Meetings\s*$/m.exec(original);
  const insertion = heading.index + heading[0].length;
  const suffix = original.slice(insertion);
  return `${original.slice(0, insertion)}\n${line}${suffix.startsWith('\n') ? '' : '\n'}${suffix}`;
}

function runRealParityMutation(vault, operation) {
  return flushEntityOps({
    vaultRoot: vault,
    ops: [operation],
    scope: 'parity',
    env: { ...process.env, DEX_PYTHON: resolveRealPython() },
    spawnSync: realCliSpawn,
  });
}

test('CLI unavailability persists retry ops and leaves the meeting entity phase pending', (t) => {
  const { vault, python } = makeVault(t);
  const state = { processedMeetings: {} };
  beginEntityPhase(state, [{ id: 'meeting-1', title: 'Example' }]);

  const result = flushEntityOps({
    vaultRoot: vault,
    ops: [createOp(vault)],
    meetingIds: ['meeting-1'],
    scope: 'creation',
    env: { DEX_PYTHON: python },
    spawnSync: () => ({ status: null, stdout: '', stderr: '', error: new Error('unavailable') }),
  });
  completeEntityPhases(state, result.completed_meeting_ids);

  assert.equal(result.ok, false);
  assert.equal(state.processedMeetings['meeting-1'].entity_phase, 'pending');
  const pending = JSON.parse(fs.readFileSync(pendingStorePath(vault), 'utf8'));
  assert.equal(pending.batches.length, 1);
  assert.deepEqual(pending.batches[0].meeting_ids, ['meeting-1']);
  assert.equal(pending.batches[0].ops.length, 1);
});

test('a successful batch clears retry state and completes the meeting entity phase', (t) => {
  const { vault, python } = makeVault(t);
  const state = { processedMeetings: {} };
  beginEntityPhase(state, [{ id: 'meeting-1', title: 'Example' }]);
  const op = createOp(vault);
  const unavailable = () => ({
    status: null, stdout: '', stderr: '', error: new Error('unavailable'),
  });
  flushEntityOps({
    vaultRoot: vault,
    ops: [op],
    meetingIds: ['meeting-1'],
    scope: 'creation',
    env: { DEX_PYTHON: python },
    spawnSync: unavailable,
    now: new Date('2026-07-01T00:00:00.000Z'),
  });

  const result = flushEntityOps({
    vaultRoot: vault,
    scope: 'creation',
    env: { DEX_PYTHON: python },
    now: new Date('2026-07-02T00:00:00.000Z'),
    spawnSync: (_python, _args, options) => {
      const request = JSON.parse(options.input);
      return {
        status: 0,
        stderr: '',
        stdout: JSON.stringify({
          results: request.ops.map((item) => ({
            path: item.path,
            status: 'created',
            fingerprint: op.target_fingerprint,
          })),
        }),
      };
    },
  });
  completeEntityPhases(state, result.completed_meeting_ids);

  assert.equal(result.ok, true);
  assert.equal(state.processedMeetings['meeting-1'].entity_phase, 'complete');
  assert.equal(fs.existsSync(pendingStorePath(vault)), false);
});

test('real Python hook-region bytes equal the JS-computed target', (t) => {
  const { vault } = makeVault(t);
  const page = path.join(vault, '05-Areas', 'People', 'External', 'Jane_Example.md');
  fs.mkdirSync(path.dirname(page), { recursive: true });
  const original = renderPersonPage(
    'Jane Example',
    'Engineer',
    'Acme',
    ['jane@example.com'],
    [],
    'external',
  );
  fs.writeFileSync(page, original);
  const relativePath = '00-Inbox/Meetings/roadmap.md';
  const line = '- [Roadmap Review](00-Inbox/Meetings/roadmap.md) — 2026-07-10';
  const withInteraction = replaceMachineRegion(original, 'recent-interactions', line);
  const touch = {
    ts: '2026-07-10',
    type: 'meeting',
    direction: 'none',
    source: { id: 'roadmap', title: 'Roadmap Review' },
  };
  const expected = mergeFrontmatterText(
    page,
    withInteraction,
    {
      last_interaction: '2026-07-10',
      touches: [touch],
      last_touched: '2026-07-10',
    },
  );
  const expectedComposite = replaceMachineRegion(
    expected,
    'update-log',
    '- 2026-07-10 — meeting · two-way — Roadmap Review [roadmap]',
  );

  const result = runRealParityMutation(vault, {
    op: 'mutate',
    path: page,
    intent: hookIntent(relativePath, line, '2026-07-10'),
  });

  assert.equal(result.ok, true, result.error);
  assert.deepEqual(fs.readFileSync(page), Buffer.from(expectedComposite, 'utf8'));
  assert.deepEqual(parseEntityPage(page).touches, [touch]);
});

test('real Python hook-legacy bytes equal the JS-computed target', (t) => {
  const { vault } = makeVault(t);
  const page = path.join(vault, '05-Areas', 'People', 'External', 'Jane_Example.md');
  fs.mkdirSync(path.dirname(page), { recursive: true });
  const original = [
    '---',
    'type: person',
    'name: Jane Example',
    'last_interaction: 2026-01-01',
    '---',
    '# Jane Example',
    '',
    '## Meetings',
    '',
    '- Older meeting',
    '',
  ].join('\n');
  fs.writeFileSync(page, original);
  const relativePath = '00-Inbox/Meetings/roadmap.md';
  const line = '- [Roadmap Review](00-Inbox/Meetings/roadmap.md) — 2026-07-10';
  const replacement = appendLegacyInteraction(original, line);

  const result = runRealParityMutation(vault, {
    op: 'mutate',
    path: page,
    intent: hookIntent(relativePath, line, '2026-07-10'),
  });

  assert.equal(result.ok, true, result.error);
  const updated = fs.readFileSync(page, 'utf8');
  assert.match(updated, /## Meetings\n\n- \[Roadmap Review\]/);
  assert.match(updated, /<!-- dex:auto:update-log -->/);
  assert.match(updated, /Roadmap Review \[roadmap\]/);
  assert.deepEqual(parseEntityPage(page).touches, [{
    ts: '2026-07-10',
    type: 'meeting',
    direction: 'none',
    source: { id: 'roadmap', title: 'Roadmap Review' },
  }]);
});

test('hook interactions leave quarantined pages untouched in both page layouts', (t) => {
  const { vault, python } = makeVault(t);
  const layouts = [
    [
      '---',
      'type: person',
      'name: [malformed',
      '---',
      '# Managed Example',
      '',
      '## Recent Interactions',
      '',
      '<!-- dex:auto:recent-interactions -->',
      '<!-- /dex:auto -->',
      '',
    ].join('\n'),
    [
      '---',
      'type: person',
      'name: [malformed',
      '---',
      '# Legacy Example',
      '',
      '## Meetings',
      '',
    ].join('\n'),
  ];
  let spawned = 0;

  for (const [index, original] of layouts.entries()) {
    const page = path.join(
      vault,
      '05-Areas',
      'People',
      'External',
      `Malformed_${index}.md`,
    );
    fs.mkdirSync(path.dirname(page), { recursive: true });
    fs.writeFileSync(page, original);

    const result = flushEntityOps({
      vaultRoot: vault,
      ops: [{
        op: 'mutate',
        path: page,
        intent: hookIntent(
          '00-Inbox/Meetings/roadmap.md',
          '- [Roadmap Review](00-Inbox/Meetings/roadmap.md) — 2026-07-10',
          '2026-07-10',
        ),
      }],
      scope: `quarantined-${index}`,
      env: { DEX_PYTHON: python },
      spawnSync: (_command, _args, options) => {
        spawned += 1;
        const request = JSON.parse(options.input);
        assert.equal(request.ops[0].target_fingerprint, undefined);
        return {
          status: 0,
          stderr: '',
          stdout: JSON.stringify({
            results: [{
              path: page,
              status: 'quarantined',
              fingerprint: crypto.createHash('sha256').update(original).digest('hex'),
            }],
          }),
        };
      },
    });

    assert.equal(result.error, undefined);
    assert.equal(fs.readFileSync(page, 'utf8'), original);
    assert.doesNotMatch(fs.readFileSync(page, 'utf8'), /dex:auto:update-log/);
  }

  assert.equal(spawned, 2);
});

test('hook interaction followed by sync touch deduplicates the same meeting', (t) => {
  const { vault } = makeVault(t);
  const page = path.join(vault, '05-Areas', 'People', 'External', 'Jane_Example.md');
  fs.mkdirSync(path.dirname(page), { recursive: true });
  fs.writeFileSync(page, renderPersonPage(
    'Jane Example', null, null, ['jane@example.org'], [], 'external',
  ));
  const touch = {
    ts: '2026-07-10',
    type: 'meeting',
    direction: 'none',
    source: { id: 'roadmap', title: 'Roadmap Review' },
  };

  const hook = runRealParityMutation(vault, {
    op: 'mutate',
    path: page,
    intent: hookIntent(
      '00-Inbox/Meetings/roadmap.md',
      '- [Roadmap Review](00-Inbox/Meetings/roadmap.md) — 2026-07-10',
      '2026-07-10',
    ),
  });
  assert.equal(hook.ok, true, hook.error);
  assert.deepEqual(parseEntityPage(page).touches, [touch]);

  const sync = runRealParityMutation(vault, {
    op: 'mutate',
    path: page,
    intent: touchIntent([touch]),
  });
  assert.equal(sync.ok, true, sync.error);
  assert.deepEqual(parseEntityPage(page).touches, [touch]);
});

test('real Python gardener bytes equal the JS-computed target', (t) => {
  const { vault } = makeVault(t);
  const page = path.join(vault, '05-Areas', 'People', 'External', 'Jane_Example.md');
  fs.mkdirSync(path.dirname(page), { recursive: true });
  const original = renderPersonPage(
    'Jane Example',
    'Engineer',
    'Acme',
    ['jane@example.com'],
    [],
    'external',
  );
  fs.writeFileSync(page, original);
  const projection = '- Product leader at Acme.\n- Discussing the launch plan.';
  const withRegion = original.replace(
    '## Key Context\n\n## Relationships',
    '## Key Context\n\n<!-- dex:auto:context-summary -->\n'
      + '<!-- /dex:auto -->\n\n## Relationships',
  );
  const expected = replaceMachineRegion(withRegion, 'context-summary', projection);

  const result = runRealParityMutation(vault, {
    op: 'mutate',
    path: page,
    intent: {
      kind: 'gardener-summary',
      region_projection: projection,
    },
  });

  assert.equal(result.ok, true, result.error);
  assert.deepEqual(fs.readFileSync(page), Buffer.from(expected, 'utf8'));
});

test('touch-log materializes as one composite CAS write and is idempotent', (t) => {
  const { vault } = makeVault(t);
  const page = path.join(vault, '05-Areas', 'People', 'External', 'Jane_Example.md');
  fs.mkdirSync(path.dirname(page), { recursive: true });
  fs.writeFileSync(page, renderPersonPage(
    'Jane Example',
    'Engineer',
    'Acme',
    ['jane@example.com'],
    [],
    'external',
  ));
  const touch = {
    ts: '2026-07-10',
    type: 'meeting',
    direction: 'none',
    source: { id: 'meeting-1', title: 'Roadmap Review' },
    nature: 'Reviewed the launch plan.',
  };
  const operation = {
    op: 'mutate',
    path: page,
    entity_identity: {
      kind: 'person',
      name: 'Jane Example',
      emails: ['jane@example.com'],
    },
    intent: touchIntent([touch]),
  };

  const first = runRealParityMutation(vault, operation);
  assert.equal(first.ok, true, first.error);
  const firstBytes = fs.readFileSync(page);
  const firstParsed = parseEntityPage(page);
  assert.deepEqual(firstParsed.touches, [touch]);
  assert.equal(firstParsed.last_touched, '2026-07-10');
  assert.match(firstBytes.toString(), /meeting · two-way — Roadmap Review \[meeting-1\]/);

  const second = runRealParityMutation(vault, operation);
  assert.equal(second.ok, true, second.error);
  assert.deepEqual(fs.readFileSync(page), firstBytes);
  assert.deepEqual(parseEntityPage(page).touches, [touch]);
});

test('touch-log ensures update-log on a legacy page before the composite write', (t) => {
  const { vault } = makeVault(t);
  const page = path.join(vault, '05-Areas', 'People', 'External', 'Legacy.md');
  fs.mkdirSync(path.dirname(page), { recursive: true });
  fs.writeFileSync(page, '# Legacy\n\n**Role:** Engineer\n');
  const touch = {
    ts: '2026-07-11',
    type: 'mention',
    source: { id: 'meeting-2', title: 'Launch Review' },
  };

  const result = runRealParityMutation(vault, {
    op: 'mutate',
    path: page,
    intent: touchIntent([touch]),
  });

  assert.equal(result.ok, true, result.error);
  const updated = fs.readFileSync(page, 'utf8');
  assert.match(updated, /<!-- dex:auto:update-log -->/);
  assert.match(updated, /mention · mention — Launch Review \[meeting-2\]/);
  assert.deepEqual(parseEntityPage(page).touches, [touch]);
});

test('touch-log deduplicates an existing unquoted YAML date', (t) => {
  const { vault } = makeVault(t);
  const page = path.join(vault, '05-Areas', 'People', 'External', 'Existing.md');
  fs.mkdirSync(path.dirname(page), { recursive: true });
  fs.writeFileSync(page, [
    '---',
    'type: person',
    'name: Existing',
    'touches:',
    '  - ts: 2026-07-12',
    '    type: meeting',
    '    direction: none',
    '    source: {id: meeting-3, title: Existing Meeting}',
    'last_touched: 2026-07-12',
    '---',
    '# Existing',
    '',
    '## Update Log',
    '',
    '<!-- dex:auto:update-log -->',
    '- 2026-07-12 — meeting · two-way — Existing Meeting [meeting-3]',
    '<!-- /dex:auto -->',
    '',
  ].join('\n'));
  const touch = {
    ts: '2026-07-12',
    type: 'meeting',
    direction: 'none',
    source: { id: 'meeting-3', title: 'Existing Meeting' },
  };

  const result = runRealParityMutation(vault, {
    op: 'mutate',
    path: page,
    intent: touchIntent([touch]),
  });

  assert.equal(result.ok, true, result.error);
  const parsed = parseEntityPage(page);
  assert.deepEqual(parsed.touches, [touch]);
  assert.equal(parsed.last_touched, '2026-07-12');
});

test('invalid touch-log intent is classified as permanent', (t) => {
  const { vault, python } = makeVault(t);
  const page = path.join(vault, '05-Areas', 'People', 'External', 'Jane_Example.md');
  fs.mkdirSync(path.dirname(page), { recursive: true });
  fs.writeFileSync(page, renderPersonPage(
    'Jane Example', null, null, ['jane@example.org'], [], 'external',
  ));

  const result = flushEntityOps({
    vaultRoot: vault,
    ops: [{
      op: 'mutate',
      path: page,
      intent: touchIntent([{
        ts: '2026-07-10T10:00:00Z',
        type: 'email',
        source: {},
      }]),
    }],
    scope: 'touch',
    env: { DEX_PYTHON: python },
    spawnSync: () => {
      throw new Error('the CLI must not run for an invalid touch intent');
    },
  });

  assert.equal(result.ok, false);
  const pending = JSON.parse(fs.readFileSync(pendingStorePath(vault), 'utf8'));
  assert.equal(pending.batches[0].ops[0].permanent_attempts, 1);
  assert.equal(pending.batches[0].ops[0].transient_attempts, 0);
  assert.match(pending.batches[0].ops[0].last_error, /Invalid touch-log mutation intent/);
});

test('a TOCTOU conflict stays pending and rematerializes from the next page bytes', (t) => {
  const { vault } = makeVault(t);
  const page = path.join(vault, '05-Areas', 'People', 'External', 'Jane_Example.md');
  fs.mkdirSync(path.dirname(page), { recursive: true });
  const original = renderPersonPage(
    'Jane Example',
    'Engineer',
    'Acme',
    ['jane@example.com'],
    [],
    'external',
  );
  fs.writeFileSync(page, original);
  const line = '- [Roadmap Review](00-Inbox/Meetings/roadmap.md) — 2026-07-10';
  const operation = {
    op: 'mutate',
    path: page,
    intent: hookIntent(
      '00-Inbox/Meetings/roadmap.md',
      line,
      '2026-07-10',
    ),
  };
  const python = resolveRealPython();

  const conflicted = flushEntityOps({
    vaultRoot: vault,
    ops: [operation],
    scope: 'hook',
    env: { ...process.env, DEX_PYTHON: python },
    now: new Date('2026-07-01T00:00:00.000Z'),
    spawnSync: (_command, _args, options) => {
      const edited = fs.readFileSync(page, 'utf8').replace(
        '## Recent Interactions',
        'A concurrent user edit.\n\n## Recent Interactions',
      );
      fs.writeFileSync(page, edited);
      return {
        status: 0,
        stderr: '',
        stdout: JSON.stringify({
          results: [{
            path: page,
            status: 'conflict',
            fingerprint: crypto.createHash('sha256').update(edited).digest('hex'),
          }],
        }),
      };
    },
  });

  assert.equal(conflicted.ok, false);
  const pending = JSON.parse(fs.readFileSync(pendingStorePath(vault), 'utf8'));
  assert.equal(pending.batches[0].ops[0].permanent_attempts, 1);
  assert.deepEqual(pending.batches[0].ops[0].intent, operation.intent);

  const replayed = flushEntityOps({
    vaultRoot: vault,
    scope: 'hook',
    env: { ...process.env, DEX_PYTHON: python },
    now: new Date('2026-07-02T00:00:00.000Z'),
    spawnSync: realCliSpawn,
  });

  assert.equal(replayed.ok, true, replayed.error);
  const updated = fs.readFileSync(page, 'utf8');
  assert.match(updated, /A concurrent user edit\./);
  assert.match(updated, /Roadmap Review/);
  assert.equal(fs.existsSync(pendingStorePath(vault)), false);
});

test('a target removed after materialization is transient and identity-retryable', (t) => {
  const { vault, python } = makeVault(t);
  const page = path.join(
    vault,
    '05-Areas',
    'People',
    'External',
    'Jane_Example.md',
  );
  fs.mkdirSync(path.dirname(page), { recursive: true });
  fs.writeFileSync(
    page,
    renderPersonPage(
      'Jane Example',
      'Engineer',
      'Example Org',
      ['jane@example.com'],
      [],
      'external',
    ),
  );
  const operation = {
    op: 'mutate',
    path: page,
    entity_identity: {
      kind: 'person',
      name: 'Jane Example',
      emails: ['jane@example.com'],
    },
    intent: hookIntent(
      '00-Inbox/Meetings/example.md',
      '- [Example](00-Inbox/Meetings/example.md) — 2026-07-10',
      '2026-07-10',
    ),
  };

  const result = flushEntityOps({
    vaultRoot: vault,
    ops: [operation],
    scope: 'hook',
    env: { DEX_PYTHON: python },
    now: new Date('2026-07-01T00:00:00.000Z'),
    spawnSync: (_command, _args, options) => {
      const request = JSON.parse(options.input);
      fs.unlinkSync(page);
      return {
        status: 0,
        stderr: '',
        stdout: JSON.stringify({
          results: [{
            path: request.ops[0].path,
            status: 'missing',
            fingerprint: null,
          }],
        }),
      };
    },
  });

  assert.equal(result.ok, false);
  const pending = JSON.parse(fs.readFileSync(pendingStorePath(vault), 'utf8'));
  assert.equal(pending.batches[0].ops[0].permanent_attempts, 0);
  assert.equal(pending.batches[0].ops[0].transient_attempts, 1);
  assert.equal(pending.batches[0].ops[0].target_missing_attempts, 1);
  assert.equal(fs.existsSync(deadLetterPath(vault)), false);
});

test('missing interpreters remain transient before the escalation window', (t) => {
  const { vault } = makeVault(t);
  const operation = createOp(vault);

  for (let attempt = 0; attempt < 7; attempt += 1) {
    const result = flushEntityOps({
      vaultRoot: vault,
      ops: attempt === 0 ? [operation] : [],
      meetingIds: ['meeting-missing-python'],
      scope: 'creation',
      env: {},
      now: atAttempt(attempt),
    });
    assert.equal(result.ok, false);
    assert.deepEqual(result.dead_lettered_ops || [], []);
  }

  const pending = JSON.parse(fs.readFileSync(pendingStorePath(vault), 'utf8'));
  assert.equal(pending.batches[0].ops[0].permanent_attempts || 0, 0);
  assert.equal(pending.batches[0].ops[0].transient_attempts, 7);
  assert.match(pending.batches[0].ops[0].last_attempt_at, /^2026-/);
  assert.match(pending.batches[0].ops[0].next_attempt_at, /^2026-/);
  assert.equal(fs.existsSync(deadLetterPath(vault)), false);
});

test('an incapable configured interpreter is surfaced but remains transient', (t) => {
  const { vault } = makeVault(t);
  const incapable = path.join(vault, 'python-3.9-without-yaml');
  fs.writeFileSync(incapable, '#!/bin/sh\nexit 1\n');
  fs.chmodSync(incapable, 0o755);

  const result = flushEntityOps({
    vaultRoot: vault,
    ops: [createOp(vault)],
    meetingIds: ['meeting-bad-python'],
    scope: 'creation',
    env: { DEX_PYTHON: incapable },
    now: new Date('2026-07-01T00:00:00.000Z'),
  });

  assert.equal(result.ok, false);
  assert.equal(result.feature_status, 'broken');
  assert.match(result.user_message, /Python 3\.10.*PyYAML/i);
  const pending = JSON.parse(fs.readFileSync(pendingStorePath(vault), 'utf8'));
  assert.equal(pending.batches[0].ops[0].permanent_attempts, 0);
  assert.equal(pending.batches[0].ops[0].transient_attempts, 1);
  assert.equal(fs.existsSync(deadLetterPath(vault)), false);
});

test('an operation is not retried inside its persisted backoff window', (t) => {
  const { vault, python } = makeVault(t);
  const operation = createOp(vault);
  let calls = 0;
  const reject = () => {
    calls += 1;
    return {
      status: 0,
      stderr: '',
      stdout: JSON.stringify({
        results: [{
          path: operation.path,
          status: 'conflict',
          fingerprint: '0'.repeat(64),
        }],
      }),
    };
  };

  flushEntityOps({
    vaultRoot: vault,
    ops: [operation],
    scope: 'creation',
    env: { DEX_PYTHON: python },
    spawnSync: reject,
    now: new Date('2026-07-01T00:00:00.000Z'),
  });
  const pendingAfterFirst = JSON.parse(
    fs.readFileSync(pendingStorePath(vault), 'utf8'),
  );
  const retryAt = pendingAfterFirst.batches[0].ops[0].next_attempt_at;

  const backedOff = flushEntityOps({
    vaultRoot: vault,
    scope: 'creation',
    env: { DEX_PYTHON: python },
    spawnSync: reject,
    now: new Date('2026-07-01T00:01:00.000Z'),
  });

  assert.equal(backedOff.ok, false);
  assert.equal(calls, 1);
  assert.equal(
    JSON.parse(fs.readFileSync(pendingStorePath(vault), 'utf8'))
      .batches[0].ops[0].next_attempt_at,
    retryAt,
  );
});

test('infrastructure and crashed-CLI failures remain transient', async (t) => {
  const cases = [
    ['spawn ENOENT', () => {
      const error = new Error('missing executable');
      error.code = 'ENOENT';
      return { status: null, stdout: '', stderr: '', error };
    }],
    ['spawn ETIMEDOUT', () => {
      const error = new Error('timed out');
      error.code = 'ETIMEDOUT';
      return { status: null, stdout: '', stderr: '', error };
    }],
    ['spawn ENOBUFS', () => {
      const error = new Error('buffer exceeded');
      error.code = 'ENOBUFS';
      return { status: null, stdout: '', stderr: '', error };
    }],
    ['signal kill', () => ({
      status: null, signal: 'SIGKILL', stdout: '', stderr: '',
    })],
    ['non-zero exit', () => ({
      status: 1, stdout: '', stderr: 'engine crashed',
    })],
    ['empty stdout', () => ({
      status: 0, stdout: '', stderr: '',
    })],
    ['malformed stdout', () => ({
      status: 0, stdout: '{"results":[', stderr: '',
    })],
    ['truncated result set', () => ({
      status: 0, stdout: '{"results":[]}', stderr: '',
    })],
  ];

  for (const [label, response] of cases) {
    await t.test(label, (inner) => {
      const { vault, python } = makeVault(inner);
      const result = flushEntityOps({
        vaultRoot: vault,
        ops: [createOp(vault)],
        scope: 'creation',
        env: { DEX_PYTHON: python },
        spawnSync: response,
        now: new Date('2026-07-01T00:00:00.000Z'),
      });

      assert.equal(result.ok, false);
      const pending = JSON.parse(
        fs.readFileSync(pendingStorePath(vault), 'utf8'),
      );
      assert.equal(pending.batches[0].ops[0].permanent_attempts || 0, 0);
      assert.equal(pending.batches[0].ops[0].transient_attempts, 1);
      assert.match(pending.batches[0].ops[0].next_attempt_at, /^2026-/);
      assert.equal(fs.existsSync(deadLetterPath(vault)), false);
    });
  }
});

test('a structurally invalid mutation intent dead-letters after the permanent cap', (t) => {
  const { vault, python } = makeVault(t);
  const page = path.join(
    vault,
    '05-Areas',
    'People',
    'External',
    'Jane_Example.md',
  );
  fs.mkdirSync(path.dirname(page), { recursive: true });
  fs.writeFileSync(
    page,
    renderPersonPage(
      'Jane Example',
      'Engineer',
      'Example Org',
      ['jane@example.org'],
      [],
      'external',
    ),
  );
  const operation = {
    op: 'mutate',
    path: page,
    entity_identity: {
      kind: 'person',
      name: 'Jane Example',
      emails: ['jane@example.org'],
    },
    intent: {
      kind: 'hook-interaction',
      interaction: {
        path: '00-Inbox/Meetings/example.md',
        date: '2026-07-10',
      },
    },
  };
  let terminal;

  for (let attempt = 1; attempt <= 5; attempt += 1) {
    terminal = flushEntityOps({
      vaultRoot: vault,
      ops: attempt === 1 ? [operation] : [],
      meetingIds: attempt === 1 ? ['meeting-invalid-intent'] : [],
      scope: 'hook',
      env: { DEX_PYTHON: python },
      now: atAttempt(attempt),
      spawnSync: () => {
        throw new Error('the CLI must not run for an invalid intent');
      },
    });
  }

  assert.equal(terminal.dead_lettered_ops.length, 1);
  assert.equal(fs.existsSync(pendingStorePath(vault)), false);
  const [entry] = loadDeadLetters(vault);
  assert.equal(entry.permanent_attempts, 5);
  assert.equal(entry.transient_attempts, 0);
  assert.match(entry.reason, /Invalid hook mutation intent/);
});

test('a persistently failing CLI escalates to the shared dead-letter signal', (t) => {
  const { vault, python } = makeVault(t);
  const operation = createOp(vault);
  const crash = () => ({
    status: 1,
    stdout: '',
    stderr: 'engine defect',
  });
  let terminal = null;

  for (let attempt = 1; attempt <= 15; attempt += 1) {
    const result = flushEntityOps({
      vaultRoot: vault,
      ops: attempt === 1 ? [operation] : [],
      meetingIds: attempt === 1 ? ['meeting-cli-defect'] : [],
      scope: 'creation',
      env: { DEX_PYTHON: python },
      now: atAttempt(attempt),
      spawnSync: crash,
    });
    if (result.dead_lettered_ops?.length) {
      terminal = result;
      break;
    }
  }

  assert.ok(terminal, 'the persistent infrastructure failure must surface');
  assert.equal(terminal.dead_lettered_ops.length, 1);
  assert.equal(fs.existsSync(pendingStorePath(vault)), false);
  const [entry] = loadDeadLetters(vault);
  assert.equal(entry.permanent_attempts, 0);
  assert.ok(entry.transient_attempts <= 15);
  assert.match(entry.reason, /infrastructure failure persisted/i);
});

test('five genuine per-operation rejections dead-letter the op', (t) => {
  const { vault, python } = makeVault(t);
  const operation = createOp(vault);
  const pendingPath = pendingStorePath(vault);
  const ledgerPath = deadLetterPath(vault);
  const conflict = () => ({
    status: 0,
    stderr: '',
    stdout: JSON.stringify({
      results: [{
        path: operation.path,
        status: 'conflict',
        fingerprint: '0'.repeat(64),
      }],
    }),
  });

  for (let attempt = 1; attempt <= 5; attempt += 1) {
    const result = flushEntityOps({
      vaultRoot: vault,
      ops: attempt === 1 ? [operation] : [],
      scope: 'creation',
      env: { DEX_PYTHON: python },
      spawnSync: conflict,
      now: atAttempt(attempt),
    });
    assert.equal(result.ok, false);
    if (attempt < 5) {
      const pending = JSON.parse(fs.readFileSync(pendingPath, 'utf8'));
      assert.equal(pending.batches.length, 1);
      assert.equal(pending.batches[0].ops[0].permanent_attempts, attempt);
      assert.equal(fs.existsSync(ledgerPath), false);
    }
  }

  assert.equal(fs.existsSync(pendingPath), false);
  const entries = fs.readFileSync(ledgerPath, 'utf8').trim().split('\n')
    .map(line => JSON.parse(line));
  assert.equal(entries.length, 1);
  assert.equal(entries[0].permanent_attempts, 5);
  assert.equal(entries[0].failure_class, 'permanent');
  assert.equal(entries[0].scope, 'creation');
  assert.deepEqual(entries[0].op, operation);
});

test('dead-letter append is idempotent across replay after a settlement crash', (t) => {
  const { vault, python } = makeVault(t);
  const operation = createOp(vault);
  const pendingPath = pendingStorePath(vault);
  const ledgerPath = deadLetterPath(vault);
  const reject = () => ({
    status: 0,
    stderr: '',
    stdout: JSON.stringify({
      results: [{
        path: operation.path,
        status: 'conflict',
        fingerprint: '0'.repeat(64),
      }],
    }),
  });

  for (let attempt = 1; attempt <= 5; attempt += 1) {
    flushEntityOps({
      vaultRoot: vault,
      ops: attempt === 1 ? [operation] : [],
      scope: 'creation',
      env: { DEX_PYTHON: python },
      now: atAttempt(attempt),
      spawnSync: reject,
    });
  }
  const first = fs.readFileSync(ledgerPath, 'utf8').trim().split('\n');
  const entry = JSON.parse(first[0]);
  fs.writeFileSync(pendingPath, `${JSON.stringify({
    version: 1,
    batches: [{
      id: entry.batch_id,
      scope: 'creation',
      meeting_ids: [],
      ops: [{
        ...operation,
        permanent_attempts: 4,
        transient_attempts: 0,
        target_missing_attempts: 0,
        backoff_attempts: 4,
        last_attempt_at: atAttempt(4).toISOString(),
        next_attempt_at: atAttempt(5).toISOString(),
      }],
    }],
  }, null, 2)}\n`);
  flushEntityOps({
    vaultRoot: vault,
    scope: 'creation',
    env: { DEX_PYTHON: python },
    now: atAttempt(6),
    spawnSync: reject,
  });

  assert.equal(fs.readFileSync(ledgerPath, 'utf8').trim().split('\n').length, 1);
  assert.equal(fs.existsSync(pendingPath), false);
});

test('dead-letter heal requeues with reset lifecycle and clears after success', (t) => {
  const { vault, python } = makeVault(t);
  const operation = createOp(vault);
  const reject = () => ({
    status: 0,
    stderr: '',
    stdout: JSON.stringify({
      results: [{
        path: operation.path,
        status: 'conflict',
        fingerprint: '0'.repeat(64),
      }],
    }),
  });

  for (let attempt = 1; attempt <= 5; attempt += 1) {
    flushEntityOps({
      vaultRoot: vault,
      ops: attempt === 1 ? [operation] : [],
      meetingIds: attempt === 1 ? ['meeting-heal'] : [],
      scope: 'creation',
      env: { DEX_PYTHON: python },
      now: atAttempt(attempt),
      spawnSync: reject,
    });
  }
  assert.equal(loadDeadLetters(vault).length, 1);
  assert.equal(fs.existsSync(pendingStorePath(vault)), false);

  const healed = requeueDeadLetters(vault);

  assert.equal(healed.requeued, 1);
  assert.deepEqual(healed.dead_letter_ids.length, 1);
  assert.deepEqual(loadDeadLetters(vault), []);
  const pending = JSON.parse(fs.readFileSync(pendingStorePath(vault), 'utf8'));
  assert.deepEqual(pending.batches[0].meeting_ids, ['meeting-heal']);
  assert.deepEqual(pending.batches[0].ops, [operation]);

  const replayed = flushEntityOps({
    vaultRoot: vault,
    scope: 'creation',
    env: { DEX_PYTHON: python },
    now: atAttempt(6),
    spawnSync: (_command, _args, options) => {
      const request = JSON.parse(options.input);
      return {
        status: 0,
        stderr: '',
        stdout: JSON.stringify({
          results: request.ops.map(item => ({
            path: item.path,
            status: 'created',
            fingerprint: operation.target_fingerprint,
          })),
        }),
      };
    },
  });

  assert.equal(replayed.ok, true, replayed.error);
  assert.deepEqual(replayed.completed_meeting_ids, ['meeting-heal']);
  assert.equal(fs.existsSync(pendingStorePath(vault)), false);
  assert.deepEqual(loadDeadLetters(vault), []);
});

test('a renamed target page is re-resolved by entity identity', (t) => {
  const { vault, python } = makeVault(t);
  const directory = path.join(
    vault,
    '05-Areas',
    'People',
    'External',
  );
  fs.mkdirSync(directory, { recursive: true });
  const originalPath = path.join(directory, 'Jane_Example.md');
  const renamedPath = path.join(directory, 'Jane_Renamed.md');
  fs.writeFileSync(
    originalPath,
    renderPersonPage(
      'Jane Example',
      'Engineer',
      'Example Org',
      ['jane@example.com'],
      [],
      'external',
    ),
  );
  const operation = {
    op: 'mutate',
    path: originalPath,
    entity_identity: {
      kind: 'person',
      name: 'Jane Example',
      emails: ['jane@example.com'],
    },
    intent: hookIntent(
      '00-Inbox/Meetings/roadmap.md',
      '- [Roadmap Review](00-Inbox/Meetings/roadmap.md) — 2026-07-10',
      '2026-07-10',
    ),
  };

  flushEntityOps({
    vaultRoot: vault,
    ops: [operation],
    scope: 'hook',
    env: {},
    now: new Date('2026-07-01T00:00:00.000Z'),
  });
  fs.renameSync(originalPath, renamedPath);
  let requestedPath;
  const replayed = flushEntityOps({
    vaultRoot: vault,
    scope: 'hook',
    env: { DEX_PYTHON: python },
    now: new Date('2026-07-02T00:00:00.000Z'),
    spawnSync: (_command, _args, options) => {
      const request = JSON.parse(options.input);
      requestedPath = request.ops[0].path;
      return {
        status: 0,
        stderr: '',
        stdout: JSON.stringify({
          results: [{
            path: requestedPath,
            status: 'updated',
            fingerprint: '1'.repeat(64),
          }],
        }),
      };
    },
  });

  assert.equal(replayed.ok, true, replayed.error);
  assert.equal(requestedPath, renamedPath);
  assert.equal(fs.existsSync(pendingStorePath(vault)), false);
});

test('a genuinely missing target surfaces after bounded identity retries', (t) => {
  const { vault, python } = makeVault(t);
  const missingPath = path.join(
    vault,
    '05-Areas',
    'People',
    'External',
    'Jane_Missing.md',
  );
  const operation = {
    op: 'mutate',
    path: missingPath,
    entity_identity: {
      kind: 'person',
      name: 'Jane Missing',
      emails: ['jane.missing@example.org'],
    },
    intent: hookIntent(
      '00-Inbox/Meetings/example.md',
      '- [Example](00-Inbox/Meetings/example.md) — 2026-07-10',
      '2026-07-10',
    ),
  };

  let terminal;
  for (let attempt = 1; attempt <= 5; attempt += 1) {
    terminal = flushEntityOps({
      vaultRoot: vault,
      ops: attempt === 1 ? [operation] : [],
      meetingIds: attempt === 1 ? ['meeting-missing-target'] : [],
      scope: 'hook',
      env: { DEX_PYTHON: python },
      now: atAttempt(attempt),
    });
  }

  assert.equal(terminal.ok, false);
  assert.equal(terminal.dead_lettered_ops.length, 1);
  const entry = terminal.dead_lettered_ops[0];
  assert.equal(entry.meeting_id, 'meeting-missing-target');
  assert.equal(entry.op_type, 'mutate');
  assert.equal(entry.entity_path, missingPath);
  assert.deepEqual(entry.entity_identity, operation.entity_identity);
  assert.match(entry.reason, /target page missing after 5/i);
  assert.equal(entry.permanent_attempts, 0);
  assert.equal(entry.target_missing_attempts, 5);
});

test('large operation sets are executed in bounded scaled chunks', (t) => {
  const { vault, python } = makeVault(t);
  const operations = Array.from({ length: 121 }, (_, index) => {
    const content = `# Person ${index}\n`;
    return {
      op: 'create',
      path: path.join(
        vault,
        '05-Areas',
        'People',
        'External',
        `Person_${index}.md`,
      ),
      content,
      allowed_root: vault,
      target_fingerprint: crypto.createHash('sha256').update(content).digest('hex'),
    };
  });
  const requests = [];

  const result = flushEntityOps({
    vaultRoot: vault,
    ops: operations,
    scope: 'creation',
    env: { DEX_PYTHON: python },
    now: new Date('2026-07-01T00:00:00.000Z'),
    spawnSync: (_command, _args, options) => {
      const request = JSON.parse(options.input);
      requests.push({
        count: request.ops.length,
        timeout: options.timeout,
        maxBuffer: options.maxBuffer,
      });
      return {
        status: 0,
        stderr: '',
        stdout: JSON.stringify({
          results: request.ops.map(item => ({
            path: item.path,
            status: 'created',
            fingerprint: operations.find(op => op.path === item.path)
              .target_fingerprint,
          })),
        }),
      };
    },
  });

  assert.equal(result.ok, true, result.error);
  assert.ok(requests.length > 1);
  assert.equal(requests.reduce((sum, request) => sum + request.count, 0), 121);
  assert.ok(requests.every(request => request.count <= 50));
  assert.ok(requests.every(request => request.timeout > 30_000));
  assert.ok(requests.every(request => request.maxBuffer > 1024 * 1024));
});

test('one intent materialization failure does not consume a sibling batch attempt', (t) => {
  const { vault, python } = makeVault(t);
  const missingPage = path.join(
    vault,
    '05-Areas',
    'People',
    'External',
    'Missing_Person.md',
  );
  const invalid = {
    op: 'mutate',
    path: missingPage,
    intent: hookIntent(
      '00-Inbox/Meetings/roadmap.md',
      '- [Roadmap Review](00-Inbox/Meetings/roadmap.md) — 2026-07-10',
      '2026-07-10',
    ),
  };
  flushEntityOps({
    vaultRoot: vault,
    ops: [invalid],
    scope: 'hook',
    env: { DEX_PYTHON: python },
    spawnSync: () => {
      throw new Error('the CLI must not run when no operation materializes');
    },
  });

  const create = createOp(vault);
  let request;
  const result = flushEntityOps({
    vaultRoot: vault,
    ops: [create],
    scope: 'hook',
    env: { DEX_PYTHON: python },
    spawnSync: (_command, _args, options) => {
      request = JSON.parse(options.input);
      return {
        status: 0,
        stderr: '',
        stdout: JSON.stringify({
          results: [{
            path: create.path,
            status: 'created',
            fingerprint: create.target_fingerprint,
          }],
        }),
      };
    },
  });

  const { target_fingerprint: _targetFingerprint, ...createCliOp } = create;
  assert.deepEqual(request.ops, [createCliOp]);
  assert.equal(result.ok, false);
  assert.equal(result.completed_batches.length, 1);
  assert.deepEqual(result.results, [{
    path: create.path,
    status: 'created',
    fingerprint: create.target_fingerprint,
  }]);
  const pending = JSON.parse(fs.readFileSync(pendingStorePath(vault), 'utf8'));
  assert.equal(pending.batches.length, 1);
  assert.equal(pending.batches[0].ops.length, 1);
  assert.equal(pending.batches[0].ops[0].path, missingPage);
  assert.equal(pending.batches[0].ops[0].transient_attempts, 1);
  assert.equal(pending.batches[0].ops[0].permanent_attempts, 0);
});

test('a partial batch returns only applied effects and keeps failed effects aligned', (t) => {
  const { vault, python } = makeVault(t);
  const create = createOp(vault);
  const missingPage = path.join(
    vault,
    '05-Areas',
    'People',
    'External',
    'Missing_Person.md',
  );
  const invalid = {
    op: 'mutate',
    path: missingPage,
    intent: hookIntent(
      '00-Inbox/Meetings/roadmap.md',
      '- [Roadmap Review](00-Inbox/Meetings/roadmap.md) — 2026-07-10',
      '2026-07-10',
    ),
  };
  const effects = [
    { path: create.path, kind: 'applied-effect' },
    { path: missingPage, kind: 'pending-effect' },
  ];

  const result = flushEntityOps({
    vaultRoot: vault,
    ops: [create, invalid],
    scope: 'gardener',
    metadata: { effects },
    env: { DEX_PYTHON: python },
    spawnSync: () => ({
      status: 0,
      stderr: '',
      stdout: JSON.stringify({
        results: [{
          path: create.path,
          status: 'created',
          fingerprint: create.target_fingerprint,
        }],
      }),
    }),
  });

  assert.equal(result.ok, false);
  assert.equal(result.completed_batches.length, 1);
  assert.deepEqual(result.completed_batches[0].ops, [create]);
  assert.deepEqual(result.completed_batches[0].metadata.effects, [effects[0]]);

  const pending = JSON.parse(fs.readFileSync(pendingStorePath(vault), 'utf8'));
  assert.equal(pending.batches.length, 1);
  assert.deepEqual(
    {
      op: pending.batches[0].ops[0].op,
      path: pending.batches[0].ops[0].path,
      intent: pending.batches[0].ops[0].intent,
      permanent_attempts: pending.batches[0].ops[0].permanent_attempts,
      transient_attempts: pending.batches[0].ops[0].transient_attempts,
      target_missing_attempts: pending.batches[0].ops[0].target_missing_attempts,
    },
    {
      ...invalid,
      permanent_attempts: 0,
      transient_attempts: 1,
      target_missing_attempts: 1,
    },
  );
  assert.match(pending.batches[0].ops[0].last_attempt_at, /^\d{4}-/);
  assert.match(pending.batches[0].ops[0].next_attempt_at, /^\d{4}-/);
  assert.deepEqual(pending.batches[0].metadata.effects, [effects[1]]);
});
