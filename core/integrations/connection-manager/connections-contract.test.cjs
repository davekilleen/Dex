'use strict';

const { test } = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync, spawnSync } = require('node:child_process');

const REPO = path.resolve(__dirname, '../../..');
const DIST = path.join(REPO, 'packages', 'dex-contracts', 'dist');
const FIXTURES = path.join(REPO, 'packages', 'dex-contracts', 'fixtures', 'connections');
const CONTRACT = path.join(DIST, 'connections.contract.json');
const SCHEMA = path.join(DIST, 'connections.schema.json');
const MANIFEST = path.join(DIST, 'connections-engine.manifest.json');

test('connections contract, schema, fixtures, and engine manifest are committed generated artifacts', () => {
  for (const file of [CONTRACT, SCHEMA, MANIFEST]) {
    assert.equal(fs.existsSync(file), true, `${path.relative(REPO, file)} must exist`);
  }
  for (const file of [
    'token.least-privilege.json',
    'token.class-b-envelope.json',
    'token.v2-envelope.json',
    ...['connected', 'expiring', 'expired', 'needs_reauth', 'not_connected'].map((status) => `status.${status}.json`),
  ]) {
    assert.equal(fs.existsSync(path.join(FIXTURES, file)), true, `fixture ${file} must exist`);
  }
});

test('connections contract artifacts regenerate without drift and validate every golden fixture', () => {
  execFileSync('node', [path.join(REPO, 'scripts', 'check-connections-contract.mjs')], { cwd: REPO, stdio: 'pipe' });
  execFileSync('node', [path.join(REPO, 'scripts', 'build-connections-engine-manifest.mjs'), '--check'], {
    cwd: REPO,
    stdio: 'pipe',
  });
});

test('foreign smoke consumer uses only CLIs plus contract/schema against a scratch vault', () => {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-connections-consumer-'));
  const env = { ...process.env, DEX_VAULT: vault, DEX_CM_NO_KEYCHAIN: '1' };
  try {
    execFileSync('node', [path.join(__dirname, 'connect.cjs'), 'set-key', 'linear', '--no-probe'], {
      cwd: REPO,
      env,
      input: 'FAKE-LINEAR-KEY\n',
      stdio: ['pipe', 'pipe', 'pipe'],
    });
    const output = execFileSync(
      'node',
      [
        path.join(REPO, 'scripts', 'connections-consumer-smoke.mjs'),
        '--contract',
        CONTRACT,
      ],
      { cwd: REPO, env, stdio: 'pipe' }
    ).toString();
    assert.match(output, /connections consumer smoke passed/);
  } finally {
    fs.rmSync(vault, { recursive: true, force: true });
  }
});

test('real accessor and status CLIs conform to the published schemas and exit-code ABI', async () => {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-connections-conformance-'));
  const env = { ...process.env, DEX_VAULT: vault, DEX_CM_NO_KEYCHAIN: '1' };
  const contract = JSON.parse(fs.readFileSync(CONTRACT, 'utf8'));
  const schema = JSON.parse(fs.readFileSync(SCHEMA, 'utf8'));
  const { validateAgainstSchema } = await import(path.join(REPO, 'scripts', 'connections-contract-validation.mjs'));
  const getToken = path.join(__dirname, contract.cli.getToken.executable);
  try {
    execFileSync(
      'node',
      [
        '-e',
        "require(process.argv[1]).saveToken('fixture-oauth',{access_token:'FAKE-AT',refresh_token:'FAKE-RT',expires_at:1893456000000,scope:'read'},{provider:'google'})",
        path.join(__dirname, 'token-store.cjs'),
      ],
      { env, stdio: 'pipe' }
    );
    const least = JSON.parse(execFileSync('node', [getToken, 'fixture-oauth'], { env }).toString());
    validateAgainstSchema(least, schema.$defs.leastPrivilegeToken, schema);
    const full = JSON.parse(execFileSync('node', [getToken, 'fixture-oauth', '--full'], { env }).toString());
    validateAgainstSchema(full, schema.$defs.fullToken, schema);
    const raw = execFileSync('node', [getToken, 'fixture-oauth', '--access-token-only'], { env }).toString();
    validateAgainstSchema(raw, schema.$defs.accessTokenOnly, schema);

    const status = JSON.parse(
      execFileSync('node', [path.join(__dirname, contract.cli.status.executable), 'status', '--json'], { env }).toString()
    );
    validateAgainstSchema(status, schema.$defs.statusOutput, schema);
    const envelope = JSON.parse(
      fs.readFileSync(path.join(vault, 'System', 'credentials', 'tokens', 'fixture-oauth.json'), 'utf8')
    );
    validateAgainstSchema(envelope, schema.$defs.tokenEnvelopeV2, schema);

    assert.equal(spawnSync('node', [getToken, 'missing'], { env }).status, contract.cli.getToken.exitCodes.not_connected);
    assert.equal(spawnSync('node', [getToken], { env }).status, contract.cli.getToken.exitCodes.error);
    fs.writeFileSync(path.join(vault, 'System', 'credentials', 'tokens', 'fixture-oauth.json'), 'corrupt');
    assert.equal(
      spawnSync('node', [getToken, 'fixture-oauth'], { env }).status,
      contract.cli.getToken.exitCodes.needs_reauth
    );
  } finally {
    fs.rmSync(vault, { recursive: true, force: true });
  }
});
