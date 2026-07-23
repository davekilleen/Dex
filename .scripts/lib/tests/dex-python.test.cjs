'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const {
  resolveDexPython,
  resolveDexPythonStatus,
} = require('../dex-python.cjs');

function executable(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, '#!/bin/sh\nexit 0\n');
  fs.chmodSync(filePath, 0o755);
}

test('DEX_PYTHON wins over the vault virtualenv', (t) => {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-python-'));
  t.after(() => fs.rmSync(vault, { recursive: true, force: true }));
  const configured = path.join(vault, 'configured-python');
  const virtualenv = path.join(vault, '.venv', 'bin', 'python');
  executable(configured);
  executable(virtualenv);

  assert.equal(resolveDexPython(vault, { DEX_PYTHON: configured }), configured);
});

test('the vault virtualenv is used when DEX_PYTHON is absent', (t) => {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-python-'));
  t.after(() => fs.rmSync(vault, { recursive: true, force: true }));
  const virtualenv = path.join(vault, '.venv', 'bin', 'python');
  executable(virtualenv);

  assert.equal(resolveDexPython(vault, {}), virtualenv);
});

test('bare interpreter names and launchd PATH fallbacks are rejected', (t) => {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-python-'));
  t.after(() => fs.rmSync(vault, { recursive: true, force: true }));

  assert.equal(
    resolveDexPython(vault, { DEX_PYTHON: 'python3', PATH: '/usr/bin:/bin' }),
    null,
  );
});

test('an executable DEX_PYTHON without the required capability is rejected once', (t) => {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-python-'));
  t.after(() => fs.rmSync(vault, { recursive: true, force: true }));
  const configured = path.join(vault, 'python-3.9-without-yaml');
  const marker = path.join(vault, 'probe-count');
  fs.writeFileSync(configured, [
    '#!/bin/sh',
    `printf x >> ${JSON.stringify(marker)}`,
    'exit 1',
    '',
  ].join('\n'));
  fs.chmodSync(configured, 0o755);

  const first = resolveDexPythonStatus(vault, { DEX_PYTHON: configured });
  const second = resolveDexPythonStatus(vault, { DEX_PYTHON: configured });

  assert.equal(first.path, null);
  assert.equal(first.feature_status, 'broken');
  assert.match(first.user_message, /Python 3\.10.*PyYAML/i);
  assert.deepEqual(second, first);
  assert.equal(fs.readFileSync(marker, 'utf8'), 'x');
  assert.equal(resolveDexPython(vault, { DEX_PYTHON: configured }), null);
  assert.equal(fs.readFileSync(marker, 'utf8'), 'x');
});
