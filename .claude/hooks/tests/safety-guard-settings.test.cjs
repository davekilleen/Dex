const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../../..');
const SETTINGS_PATH = path.join(ROOT, '.claude/settings.json');
const GUARD_PATH = path.join(ROOT, '.claude/hooks/dex-safety-guard.sh');
const GUARD_COMMAND = 'bash "$CLAUDE_PROJECT_DIR"/.claude/hooks/dex-safety-guard.sh';

function matchingCommands(settings, toolName) {
  return (settings.hooks?.PreToolUse || [])
    .filter((entry) => new RegExp(`^(?:${entry.matcher})$`).test(toolName))
    .flatMap((entry) => entry.hooks || [])
    .map((hook) => hook.command);
}

function assertSafetyRouting(settings) {
  assert.deepEqual(matchingCommands(settings, 'Bash'), [
    GUARD_COMMAND,
    'node "$CLAUDE_PROJECT_DIR"/.claude/hooks/ensure-mcp-user-scope.cjs',
  ]);
  assert.deepEqual(matchingCommands(settings, 'mcp__firecrawl__firecrawl_scrape'), [
    GUARD_COMMAND,
  ]);
  assert.deepEqual(matchingCommands(settings, 'mcp__rag-web-browser__search'), [
    GUARD_COMMAND,
  ]);
  assert.deepEqual(matchingCommands(settings, 'WebFetch'), []);
}

function runGuard(toolName, script = GUARD_PATH, command = undefined, cwd = undefined, envOverrides = {}) {
  const env = { ...process.env };
  if (cwd !== undefined) {
    // The shared gate deliberately honours explicit harness vault variables
    // ahead of cwd. Keep this fixture isolated from CI's global VAULT_PATH.
    delete env.CLAUDE_PROJECT_DIR;
    env.VAULT_PATH = cwd;
  }
  return spawnSync('/bin/bash', [script], {
    encoding: 'utf8',
    cwd,
    timeout: 5000,
    env: { ...env, ...envOverrides },
    input: JSON.stringify({ tool_name: toolName, tool_input: command ? { command } : {} }),
  });
}

function restrictedPath(t, { includePython }) {
  const bin = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-safety-path-'));
  if (includePython) {
    const located = spawnSync('/bin/bash', ['-lc', 'command -v python3'], { encoding: 'utf8' });
    assert.equal(located.status, 0, located.stderr);
    fs.symlinkSync(located.stdout.trim(), path.join(bin, 'python'));
  }
  t.after(() => fs.rmSync(bin, { recursive: true, force: true }));
  return bin;
}

test('actual settings route Bash and MCP tools to the intended guards only', () => {
  assertSafetyRouting(JSON.parse(fs.readFileSync(SETTINGS_PATH, 'utf8')));
});

test('matcher guard-removal mutations are detected', () => {
  const settings = JSON.parse(fs.readFileSync(SETTINGS_PATH, 'utf8'));
  const withoutMcpGuard = structuredClone(settings);
  withoutMcpGuard.hooks.PreToolUse = withoutMcpGuard.hooks.PreToolUse.filter(
    (entry) => entry.matcher !== 'mcp__.*',
  );
  assert.throws(() => assertSafetyRouting(withoutMcpGuard));

  const withoutBashGuard = structuredClone(settings);
  withoutBashGuard.hooks.PreToolUse.find((entry) => entry.matcher === 'Bash').hooks =
    withoutBashGuard.hooks.PreToolUse.find((entry) => entry.matcher === 'Bash').hooks
      .filter((hook) => hook.command !== GUARD_COMMAND);
  assert.throws(() => assertSafetyRouting(withoutBashGuard));
});

test('guard blocks Firecrawl and RAG-browser MCPs but allows native WebFetch and Scrapling', () => {
  for (const toolName of [
    'mcp__firecrawl__firecrawl_scrape',
    'mcp__rag-web-browser__search',
    'mcp__rag_web_browser__search',
  ]) {
    const result = runGuard(toolName);
    assert.equal(result.status, 2, `${toolName}: ${result.stdout} ${result.stderr}`);
  }
  for (const toolName of [
    'WebFetch',
    'mcp__scrapling__get',
    'mcp__my_mcp__rag-web-browser-helper',
    'mcp__my_firecrawl_helper__search',
  ]) {
    const result = runGuard(toolName);
    assert.equal(result.status, 0, `${toolName}: ${result.stdout} ${result.stderr}`);
  }
});

test('blocked-scraper guard-removal mutation loses protection', () => {
  const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-safety-mutation-'));
  try {
    const mutated = path.join(temporary, 'guard.sh');
    const source = fs.readFileSync(GUARD_PATH, 'utf8');
    fs.writeFileSync(
      mutated,
      source.replaceAll('mcp__firecrawl__*', 'removed_firecrawl_guard'),
    );
    assert.equal(runGuard('mcp__firecrawl__firecrawl_scrape', mutated).status, 0);
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});

test('guard blocks raw Git mutations while a live migration lock is held', () => {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-migration-guard-'));
  try {
    const lock = path.join(vault, 'System', '.dex', 'mutation.lock');
    fs.mkdirSync(path.dirname(lock), { recursive: true });
    fs.writeFileSync(lock, `${JSON.stringify({ pid: process.pid, kind: 'migration' })}\n`);

    const blocked = runGuard('Bash', GUARD_PATH, 'git reset --hard HEAD', vault);
    assert.equal(blocked.status, 2, blocked.stdout + blocked.stderr);
    assert.match(blocked.stdout, /--resume/);
    assert.match(blocked.stdout, /--restore/);

    const allowedRead = runGuard('Bash', GUARD_PATH, 'git status --short', vault);
    assert.equal(allowedRead.status, 0, allowedRead.stdout + allowedRead.stderr);
  } finally {
    fs.rmSync(vault, { recursive: true, force: true });
  }
});

test('guard ignores stale and non-migration mutation locks', () => {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-migration-guard-stale-'));
  try {
    const lock = path.join(vault, 'System', '.dex', 'mutation.lock');
    fs.mkdirSync(path.dirname(lock), { recursive: true });
    for (const payload of [
      { pid: 2147483647, kind: 'migration' },
      { pid: process.pid, kind: 'update' },
    ]) {
      fs.writeFileSync(lock, `${JSON.stringify(payload)}\n`);
      const result = runGuard('Bash', GUARD_PATH, 'git reset --hard HEAD', vault);
      assert.equal(result.status, 0, result.stdout + result.stderr);
    }
  } finally {
    fs.rmSync(vault, { recursive: true, force: true });
  }
});

test('guard falls back to python when python3 is unavailable', (t) => {
  const result = runGuard(
    'Bash',
    GUARD_PATH,
    'rm -rf /',
    undefined,
    { DEX_PYTHON: '', PATH: restrictedPath(t, { includePython: true }) },
  );
  assert.equal(result.status, 2, result.stdout + result.stderr);
});

test('guard fails open when no Python is available', (t) => {
  const result = runGuard(
    'Bash',
    GUARD_PATH,
    'rm -rf /',
    undefined,
    { DEX_PYTHON: '', PATH: restrictedPath(t, { includePython: false }) },
  );
  // The shared Python gate is the only enforcement. Without a launcher the
  // hook must not invent a second bash rule set that can drift from it.
  assert.equal(result.status, 0, result.stdout + result.stderr);
});

test('guard allows safe absolute paths when no Python is available', (t) => {
  const result = runGuard(
    'Bash',
    GUARD_PATH,
    'rm -rf /tmp/foo',
    undefined,
    { DEX_PYTHON: '', PATH: restrictedPath(t, { includePython: false }) },
  );
  assert.equal(result.status, 0, result.stdout + result.stderr);
});

test('guard ignores an unusable DEX_PYTHON and falls back to a supported interpreter', (t) => {
  const result = runGuard(
    'Bash',
    GUARD_PATH,
    'rm -rf /',
    undefined,
    {
      DEX_PYTHON: path.join(os.tmpdir(), 'missing-dex-python'),
      PATH: restrictedPath(t, { includePython: true }),
    },
  );
  assert.equal(result.status, 2, result.stdout + result.stderr);
});
