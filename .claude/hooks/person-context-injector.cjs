#!/usr/bin/env node
/**
 * PreToolUse Read hook: thin wrapper around core/context/person_context.py.
 *
 * The Python module is also exposed as Work MCP get_person_context, so every
 * harness sees the same matching and formatting. This wrapper only translates
 * Claude's stdin payload and fail-opens when the helper cannot run.
 */
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const DEBUG_SKIP = process.env.DEX_HOOK_DEBUG === '1';
function skip(reason) {
  if (DEBUG_SKIP) console.error(`[dex-hook-skip] ${reason}`);
  process.exit(0);
}

function resolvePython(vaultRoot) {
  const candidates = [
    process.env.DEX_PYTHON,
    vaultRoot && path.join(vaultRoot, '.venv', 'bin', 'python'),
    path.join(__dirname, '..', '..', '.venv', 'bin', 'python'),
    'python3',
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (candidate === 'python3' || fs.existsSync(candidate)) return candidate;
  }
  return 'python3';
}

let input;
try {
  input = JSON.parse(fs.readFileSync(0, 'utf-8'));
} catch (error) {
  skip('invalid-json-input');
}

const filePath = input?.tool_input?.path || input?.tool_input?.file_path || '';
if (typeof filePath !== 'string') skip('invalid-file-path');
if (!filePath || filePath.includes('/People/')) {
  skip('missing-file-path-or-recursive-person-file');
}

const ext = path.extname(filePath).toLowerCase();
const skipExts = [
  '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico', '.svg', '.pdf',
  '.zip', '.tar', '.gz', '.mp3', '.mp4', '.mov', '.wav', '.pptx', '.xlsx', '.docx',
];
if (skipExts.includes(ext)) skip(`unsupported-extension:${ext}`);

let vaultRoot;
try {
  const { loadPaths } = require('./paths.cjs');
  const paths = loadPaths();
  vaultRoot = paths.VAULT_ROOT || process.env.CLAUDE_PROJECT_DIR || process.env.VAULT_PATH || process.cwd();
} catch (error) {
  vaultRoot = process.env.CLAUDE_PROJECT_DIR || process.env.VAULT_PATH || process.cwd();
}
if (typeof vaultRoot !== 'string' || !vaultRoot) {
  vaultRoot = process.env.CLAUDE_PROJECT_DIR || process.env.VAULT_PATH || process.cwd();
}

const scriptPath = path.join(__dirname, '..', '..', 'core', 'context', 'person_context.py');
if (!fs.existsSync(scriptPath)) skip('shared-context-module-not-found');
const fullFilePath = path.isAbsolute(filePath) ? filePath : path.join(vaultRoot, filePath);
const result = spawnSync(
  resolvePython(vaultRoot),
  [scriptPath, '--vault', vaultRoot, '--from-file', fullFilePath, '--format', 'hook-json'],
  {
    encoding: 'utf-8',
    timeout: 8000,
    env: {
      ...process.env,
      VAULT_PATH: vaultRoot,
      PYTHONPATH: path.join(__dirname, '..', '..'),
    },
  },
);

if (result.error || result.status !== 0 || !result.stdout) {
  const detail = (result.stderr || result.error || 'person-context-python-failed').toString().split('\n')[0];
  skip(`unexpected-error:${detail}`);
}

let payload;
try {
  payload = JSON.parse(result.stdout);
} catch (error) {
  skip('unexpected-error:person-context-python-json');
}
if (payload?.skip) skip(payload.skip);
if (!payload?.additionalContext) skip('person-context-parse-empty');

console.log(JSON.stringify({
  continue: true,
  hookSpecificOutput: {
    hookEventName: 'PreToolUse',
    additionalContext: payload.additionalContext,
  },
}));
