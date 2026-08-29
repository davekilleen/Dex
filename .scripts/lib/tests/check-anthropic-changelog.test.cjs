'use strict';

const assert = require('node:assert/strict');
const childProcess = require('node:child_process');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const repoRoot = path.resolve(__dirname, '../../..');
const scriptPath = path.join(repoRoot, '.scripts', 'check-anthropic-changelog.cjs');

const {
  CHANGELOG_SOURCES,
  MAX_REDIRECTS,
  fetchChangelog,
  main,
} = require(scriptPath);

function makeVault(t) {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-changelog-checker-'));
  fs.mkdirSync(path.join(vault, 'System'), { recursive: true });
  fs.mkdirSync(path.join(vault, '.scripts', 'logs'), { recursive: true });
  t.after(() => fs.rmSync(vault, { recursive: true, force: true }));
  return vault;
}

function writeState(vault, state) {
  fs.writeFileSync(
    path.join(vault, 'System', 'claude-code-state.json'),
    JSON.stringify(state, null, 2),
  );
}

function listen(t, handler) {
  const server = http.createServer(handler);
  t.after(() => server.close());
  return new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address();
      resolve({ origin: `http://127.0.0.1:${port}` });
    });
  });
}

function envFor(vault, originPath, extra = {}) {
  return {
    ...process.env,
    DEX_VAULT_ROOT: vault,
    DEX_CHANGELOG_TIMEOUT_MS: '2000',
    DEX_CHANGELOG_SOURCES: originPath,
    ...extra,
  };
}

function runCli(vault, { args = [], sources = '', timeoutMs = 4000, extraEnv = {} } = {}) {
  return childProcess.spawnSync(process.execPath, [scriptPath, ...args], {
    encoding: 'utf8',
    env: {
      ...process.env,
      DEX_VAULT_ROOT: vault,
      DEX_CHANGELOG_TIMEOUT_MS: '200',
      DEX_CHANGELOG_SOURCES: sources,
      ...extraEnv,
    },
    timeout: timeoutMs,
    killSignal: 'SIGKILL',
  });
}

const OFFICIAL_CHANGELOG =
  'https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md';

test('shipped source is Anthropic official Claude Code changelog; no extra https hosts', () => {
  assert.deepEqual(CHANGELOG_SOURCES, [OFFICIAL_CHANGELOG]);
  const sourceText = fs.readFileSync(scriptPath, 'utf8');
  const httpsUrls = [...sourceText.matchAll(/https:\/\/[^\s'"]+/g)].map((match) => match[0]);
  assert.deepEqual(httpsUrls, CHANGELOG_SOURCES);
});

test('product filename stays as shipped', () => {
  assert.equal(path.basename(scriptPath), 'check-anthropic-changelog.cjs');
  assert.ok(fs.existsSync(scriptPath));
});

test('CLI wrapper exits with the returned code on every path', () => {
  const source = fs.readFileSync(scriptPath, 'utf8');
  assert.match(source, /if \(require\.main === module\)/);
  assert.match(source, /process\.exit\(typeof code === 'number' \? code : 1\)/);
  assert.match(source, /process\.exit\(1\)/);
});

test('fetch follows a relative redirect and returns the final body', async (t) => {
  const { origin } = await listen(t, (req, res) => {
    if (req.url === '/from') {
      res.writeHead(302, { Location: '/to' });
      res.end('moved');
      return;
    }
    if (req.url === '/to') {
      res.writeHead(200, { 'Content-Type': 'text/plain' });
      res.end('version 1.2.3 2026-08-27');
      return;
    }
    res.writeHead(404);
    res.end('missing');
  });

  const body = await fetchChangelog(`${origin}/from`);
  assert.match(body, /version 1\.2\.3/);
});

test('fetch follows an absolute redirect across ports', async (t) => {
  const destination = await listen(t, (req, res) => {
    res.writeHead(200, { 'Content-Type': 'text/plain' });
    res.end('arrived-at-destination');
  });
  const start = await listen(t, (req, res) => {
    res.writeHead(301, { Location: `${destination.origin}/final` });
    res.end();
  });

  const body = await fetchChangelog(`${start.origin}/start`);
  assert.equal(body, 'arrived-at-destination');
});

test('fetch rejects after draining a redirect loop instead of hanging', async (t) => {
  const { origin } = await listen(t, (req, res) => {
    res.writeHead(302, { Location: req.url === '/a' ? '/b' : '/a' });
    res.end('loop');
  });

  await assert.rejects(
    () => fetchChangelog(`${origin}/a`, { timeoutMs: 2000 }),
    /Too many redirects/,
  );
});

test('fetch times out when the connected server never responds', async (t) => {
  const { origin } = await listen(t, () => {
    // Intentionally never respond.
  });

  const started = Date.now();
  await assert.rejects(
    () => fetchChangelog(`${origin}/slow`, { timeoutMs: 150 }),
    /timed out/i,
  );
  assert.ok(Date.now() - started < 1500);
});

test('fetch times out when a redirect body never ends', async (t) => {
  const { origin } = await listen(t, (req, res) => {
    res.writeHead(302, { Location: '/to' });
    res.write('partial');
  });

  const started = Date.now();
  await assert.rejects(
    () => fetchChangelog(`${origin}/from`, { timeoutMs: 150 }),
    /timed out/i,
  );
  assert.ok(Date.now() - started < 1500);
});

test('fetch times out when a non-200 body never ends', async (t) => {
  const { origin } = await listen(t, (req, res) => {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.write('partial');
  });

  const started = Date.now();
  await assert.rejects(
    () => fetchChangelog(`${origin}/missing`, { timeoutMs: 150 }),
    /timed out/i,
  );
  assert.ok(Date.now() - started < 1500);
});

test('process exits 0 on skip without fetching', (t) => {
  const vault = makeVault(t);
  writeState(vault, {
    last_check: new Date().toISOString().slice(0, 10),
    last_version_seen: null,
    features_seen: [],
  });

  const result = runCli(vault, { sources: 'http://127.0.0.1:1/unused' });
  assert.equal(result.status, 0, result.stderr || result.stdout);
  assert.equal(result.error, undefined);
  assert.equal(result.stdout, '');
});

test('process exits 1 on fetch failure with no sources, without hanging', (t) => {
  const vault = makeVault(t);
  const started = Date.now();
  const result = runCli(vault, { args: ['--force'], sources: '' });
  assert.equal(result.status, 1, result.stderr || result.stdout);
  assert.equal(result.error, undefined);
  assert.ok(Date.now() - started < 2000);
  assert.match(result.stdout, /could not fetch changelog/i);
});

test('process exits 1 on unreachable source timeout instead of hanging', (t) => {
  const vault = makeVault(t);
  const started = Date.now();
  const result = runCli(vault, {
    args: ['--force'],
    sources: 'http://127.0.0.1:1/slow',
    extraEnv: { DEX_CHANGELOG_TIMEOUT_MS: '150' },
  });
  assert.equal(result.status, 1, result.stderr || result.stdout);
  assert.equal(result.error, undefined);
  assert.ok(Date.now() - started < 2000);
  assert.match(result.stdout, /timed out|could not fetch changelog|ECONNREFUSED/i);
});

test('imported main returns 0 on dry-run after a redirected fetch', async (t) => {
  const vault = makeVault(t);
  const { origin } = await listen(t, (req, res) => {
    if (req.url === '/old') {
      res.writeHead(302, { Location: '/new' });
      res.end();
      return;
    }
    res.writeHead(200, { 'Content-Type': 'text/plain' });
    res.end('version 9.9.9 2026-08-01');
  });

  const code = await main({
    args: ['--force', '--dry-run'],
    env: envFor(vault, `${origin}/old`),
  });
  assert.equal(code, 0);
  const state = JSON.parse(fs.readFileSync(path.join(vault, 'System', 'claude-code-state.json'), 'utf8'));
  assert.equal(state.last_version_seen, null);
  assert.equal(fs.existsSync(path.join(vault, 'System', 'changelog-updates-pending.md')), false);
});

test('imported main returns 1 after draining a non-200 body', async (t) => {
  const vault = makeVault(t);
  const { origin } = await listen(t, (req, res) => {
    res.writeHead(404, { 'Content-Type': 'text/plain' });
    res.end('x'.repeat(2048));
  });

  const code = await main({
    args: ['--force'],
    env: envFor(vault, `${origin}/missing`),
  });
  assert.equal(code, 1);
});

test('imported main returns 0 after a successful redirected check and writes the alert', async (t) => {
  const vault = makeVault(t);
  writeState(vault, { last_check: '2020-01-01', last_version_seen: '1.0.0', features_seen: [] });
  const { origin } = await listen(t, (req, res) => {
    if (req.url === '/legacy') {
      res.writeHead(301, { Location: '/current' });
      res.end();
      return;
    }
    res.writeHead(200, { 'Content-Type': 'text/plain' });
    res.end('version 2.0.0 2026-08-27');
  });

  const code = await main({
    args: ['--force'],
    env: envFor(vault, `${origin}/legacy`),
  });
  assert.equal(code, 0);
  const state = JSON.parse(fs.readFileSync(path.join(vault, 'System', 'claude-code-state.json'), 'utf8'));
  assert.equal(state.last_version_seen, '2.0.0');
  assert.ok(fs.existsSync(path.join(vault, 'System', 'changelog-updates-pending.md')));
});

test('detects Markdown version headings used by the official Claude Code changelog', async (t) => {
  const vault = makeVault(t);
  writeState(vault, { last_check: '2020-01-01', last_version_seen: '1.0.0', features_seen: [] });
  const { origin } = await listen(t, (_req, res) => {
    res.writeHead(200, { 'Content-Type': 'text/plain' });
    res.end('# Changelog\n\n## 2.1.251\n\n- Added a capability\n');
  });

  const code = await main({
    args: ['--force'],
    env: envFor(vault, `${origin}/CHANGELOG.md`),
  });
  assert.equal(code, 0);
  const state = JSON.parse(fs.readFileSync(path.join(vault, 'System', 'claude-code-state.json'), 'utf8'));
  assert.equal(state.last_version_seen, '2.1.251');
  assert.ok(fs.existsSync(path.join(vault, 'System', 'changelog-updates-pending.md')));
});

test('redirect hop cap is a small finite number', () => {
  assert.equal(MAX_REDIRECTS, 5);
});
