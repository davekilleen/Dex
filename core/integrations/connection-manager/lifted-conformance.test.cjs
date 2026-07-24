'use strict';

const { test } = require('node:test');
const assert = require('node:assert');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const SOURCE_COMMIT = '2b34aa4d';
// Optional: point DEX_DESKTOP_REPO at a dex-desktop checkout to additionally
// byte-verify against the pinned source commit. Without it (CI, contributor
// machines) the test still verifies the pinned sha256 of every lifted file.
const DESKTOP_REPO = process.env.DEX_DESKTOP_REPO || '';
const LIB = path.join(__dirname, 'lib');

// Both byte hashes are pinned. For adapted files, changing one byte requires
// updating this manifest and its human-readable divergence contract together.
const FILES = {
  'rate-limit.js': {
    source: '5d13f30889095f2f8bf169b8e8cf4e742ef0eda68eb89de789f0a32f0a0ac7b4',
    lifted: 'a53b67ad5ea4a02e95d60684b9a6196e0a51652120d5a7c1566f2a4de3e8eff2',
    mode: 'header-only',
    divergences: ['source provenance header'],
  },
  'oauth-refresh.js': {
    source: '0f29891a988d913c8b4bfddc9ee9d8f4c91328784534107ff65abe3d4cac4783',
    lifted: '9540de5ac106f3863552359f0d950c0ef2e182c2a1d17c9aaf2e5dd15a814f35',
    mode: 'injectable-delay',
    divergences: ['source provenance header', 'injectable delay used only to prove Retry-After clamping'],
  },
  'connector-model.js': {
    source: '6d96ababba84dcd0d07b85db52e0427d6434ac57f7c2f7a762ee9f8aad9f822c',
    lifted: '29fcf20f3eab1f3ba65a6bcad33e7e0c9cd0aab2df6d377ad11bd785f58b4ac8',
    mode: 'core-adaptation',
    divergences: [
      'Core five-state credential model',
      'Desktop complete, partial, stale, failed, and sync-schedule fields omitted',
      'live verification remains separate evidence on connected credentials',
      'status constants come from the generated connections contract source',
    ],
  },
  'connector-verify.js': {
    source: 'd4181a12fdbee65dd3c464e055d0142f804fb2658a19ad71eacf5366f9c1a020',
    lifted: 'd8325fd377caf21c6613fb36755dd9bd92e9fae80aff3927ba4ea1e82914c67c',
    mode: 'core-adaptation',
    divergences: [
      'Core provider ids and Google calendarList, Slack auth.test, and Linear viewer probes',
      'Linear GraphQL embedded 401 or 403 recognition',
      'probe event naming and no Desktop sync-capability evidence fields',
      'Slack HTTP-200 failures remain unknown because only 401 or 403 class evidence disconnects',
    ],
  },
  'connector-ledger.js': {
    source: '956612fbebc115fa7512aaf5db91676bfe40fa0c08d0927e52f4508e28e14cbf',
    lifted: '451bd6d497da9f54919dcac431025f7ad2bbe37695180d5cef1a366c902ceef8',
    mode: 'core-adaptation',
    divergences: [
      'credentials/ledger path and Core connect, refresh, probe, and break vocabulary',
      'Desktop sync counts, cursors, schedules, and page receipts omitted',
      'fs-safe is the sole atomic writer and adds a per-connection cross-process lock',
    ],
  },
};

function sha256(data) {
  return crypto.createHash('sha256').update(data).digest('hex');
}

function pinnedSource(name) {
  if (!fs.existsSync(DESKTOP_REPO)) return null;
  const result = spawnSync(
    'git',
    ['-C', DESKTOP_REPO, 'show', `${SOURCE_COMMIT}:packages/dex-engine/${name}`],
    { encoding: null }
  );
  assert.equal(result.status, 0, result.stderr && result.stderr.toString());
  return result.stdout;
}

function withoutHeader(local) {
  const newline = local.indexOf(0x0a);
  assert.notEqual(newline, -1);
  return local.subarray(newline + 1);
}

for (const [name, contract] of Object.entries(FILES)) {
  test(`lifted conformance: ${name} matches pinned source plus documented divergences`, () => {
    const local = fs.readFileSync(path.join(LIB, name));
    assert.equal(
      local.subarray(0, local.indexOf(0x0a)).toString(),
      `// Lifted from dex-desktop@${SOURCE_COMMIT}: packages/dex-engine/${name}`
    );
    assert.equal(sha256(local), contract.lifted);
    assert.ok(contract.divergences.length > 0);

    const source = pinnedSource(name);
    if (source) assert.equal(sha256(source), contract.source);

    if (contract.mode === 'header-only' && source) {
      assert.deepEqual(withoutHeader(local), source);
    } else if (contract.mode === 'injectable-delay' && source) {
      const normalized = withoutHeader(local)
        .toString()
        .replace(
          '\t// DEX CORE DIVERGENCE: injectable delay keeps Retry-After/clamp tests instant.\n\tdelayImpl = delay,\n',
          ''
        )
        .replace('await delayImpl(waitMs)', 'await delay(waitMs)');
      assert.equal(normalized, source.toString());
    } else if (contract.mode === 'core-adaptation') {
      assert.match(local.toString(), /DEX CORE DIVERGENCE:/);
    }
  });
}
