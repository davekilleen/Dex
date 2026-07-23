'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const {
  refreshEntityCoolingFeed,
} = require('../sync-from-granola.cjs');

test('sync cooling refresh uses the shared Python resolver and vault import path', (t) => {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-sync-cooling-'));
  const python = path.join(vault, 'python');
  fs.writeFileSync(python, '#!/bin/sh\nexit 0\n');
  fs.chmodSync(python, 0o755);
  t.after(() => fs.rmSync(vault, { recursive: true, force: true }));
  const calls = [];
  const spawn = (command, args, options) => {
    calls.push({ command, args, options });
    return { status: 0, stdout: '', stderr: '' };
  };

  const result = refreshEntityCoolingFeed(vault, {
    env: {
      DEX_PYTHON: python,
      DEX_REPO_ROOT: '/example/dex-core',
      PYTHONPATH: '/example/existing',
    },
    spawnSync: spawn,
    logger: () => assert.fail('success must not log an error'),
  });

  assert.deepEqual(result, { ok: true });
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[1].args, ['-m', 'core.entity_engine.cooling']);
  assert.equal(calls[1].options.cwd, vault);
  assert.equal(calls[1].options.env.VAULT_PATH, vault);
  assert.equal(
    calls[1].options.env.PYTHONPATH,
    ['/example/dex-core', vault, '/example/existing'].join(path.delimiter),
  );
});

test('sync cooling refresh logs once and remains non-fatal on failure', (t) => {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-sync-cooling-'));
  const python = path.join(vault, 'python');
  fs.writeFileSync(python, '#!/bin/sh\nexit 0\n');
  fs.chmodSync(python, 0o755);
  t.after(() => fs.rmSync(vault, { recursive: true, force: true }));
  const messages = [];
  let calls = 0;

  const result = refreshEntityCoolingFeed(vault, {
    env: { DEX_PYTHON: python },
    spawnSync: () => {
      calls += 1;
      return calls === 1
        ? { status: 0, stdout: '', stderr: '' }
        : { status: 1, stdout: '', stderr: 'index unavailable' };
    },
    logger: message => messages.push(message),
  });

  assert.equal(result.ok, false);
  assert.equal(messages.length, 1);
  assert.match(messages[0], /Cooling feed refresh skipped.*index unavailable/);
});

