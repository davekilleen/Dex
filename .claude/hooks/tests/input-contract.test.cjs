const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const HOOKS_DIR = path.resolve(__dirname, '..');
const HOOK_INPUT_MARKERS = /\b(?:tool_input|toolInput|tool_name|hook_event_name|session_id|transcript_path|permission_mode|hook_context|is_interactive|stop_reason)\b/;
const HOOK_ENV_PAYLOAD = /\bCLAUDE_HOOK_[A-Z_]+\b/;
const STDIN_FD_ZERO_READ = /readFileSync\s*\(\s*0\s*,/;

function topLevelHooks() {
  return fs.readdirSync(HOOKS_DIR)
    .filter(fileName => fileName.endsWith('.cjs'))
    .sort()
    .map(fileName => ({
      fileName,
      source: fs.readFileSync(path.join(HOOKS_DIR, fileName), 'utf8'),
    }));
}

test('hook payloads are never read from CLAUDE_HOOK_* environment variables', () => {
  for (const { fileName, source } of topLevelHooks()) {
    assert.doesNotMatch(
      source,
      HOOK_ENV_PAYLOAD,
      `${fileName} must read its hook payload from stdin fd 0`,
    );
  }
});

test('every hook-input consumer reads stdin fd 0', () => {
  const consumers = topLevelHooks().filter(({ source }) => HOOK_INPUT_MARKERS.test(source));
  assert.ok(consumers.length > 0, 'expected to find at least one hook-input consumer');

  for (const { fileName, source } of consumers) {
    assert.match(
      source,
      STDIN_FD_ZERO_READ,
      `${fileName} consumes hook input but does not read stdin fd 0`,
    );
  }
});
