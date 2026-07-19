const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../../..');
const SETTINGS_PATH = path.join(ROOT, '.claude/settings.json');
const GUARD_PATH = path.join(ROOT, '.claude/hooks/dex-safety-guard.sh');
const GUARD_COMMAND = 'bash .claude/hooks/dex-safety-guard.sh';

function matchingCommands(settings, toolName) {
  return (settings.hooks?.PreToolUse || [])
    .filter((entry) => new RegExp(`^(?:${entry.matcher})$`).test(toolName))
    .flatMap((entry) => entry.hooks || [])
    .map((hook) => hook.command);
}

function assertSafetyRouting(settings) {
  assert.deepEqual(matchingCommands(settings, 'Bash'), [
    GUARD_COMMAND,
    'node .claude/hooks/ensure-mcp-user-scope.cjs',
  ]);
  assert.deepEqual(matchingCommands(settings, 'mcp__firecrawl__firecrawl_scrape'), [
    GUARD_COMMAND,
  ]);
  assert.deepEqual(matchingCommands(settings, 'mcp__rag-web-browser__search'), [
    GUARD_COMMAND,
  ]);
  assert.deepEqual(matchingCommands(settings, 'WebFetch'), []);
}

function runGuard(toolName, script = GUARD_PATH) {
  return spawnSync('/bin/bash', [script], {
    encoding: 'utf8',
    input: JSON.stringify({ tool_name: toolName, tool_input: {} }),
  });
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
    fs.writeFileSync(mutated, source.replace('mcp__firecrawl__*', 'removed_firecrawl_guard'));
    assert.equal(runGuard('mcp__firecrawl__firecrawl_scrape', mutated).status, 0);
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
});
