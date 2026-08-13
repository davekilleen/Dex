#!/usr/bin/env node
/**
 * PreToolUse hook: Inject person context when reading files with People/ references
 *
 * Thin wrapper around core/context/person_context.py — the same payload
 * Work MCP's get_person_context returns. Do not reimplement the payload here.
 *
 * Triggered on Read tool
 */
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const DEBUG_SKIP = process.env.DEX_HOOK_DEBUG === '1';
function skip(reason) {
  if (DEBUG_SKIP) {
    console.error(`[dex-hook-skip] ${reason}`);
  }
  process.exit(0);
}

function resolvePython(vaultRoot) {
  const hookDir = __dirname;
  const candidates = [
    process.env.DEX_PYTHON,
    vaultRoot && path.join(vaultRoot, '.venv', 'bin', 'python'),
    path.join(hookDir, '..', '..', '.venv', 'bin', 'python'),
    'python3',
  ].filter(Boolean);
  for (const candidate of candidates) {
    if (candidate === 'python3' || fs.existsSync(candidate)) {
      return candidate;
    }
  }
  return 'python3';
}

// Read hook input from stdin
let input;
try {
  input = JSON.parse(fs.readFileSync(0, 'utf-8'));
} catch (e) {
  skip('invalid-json-input');
}

const filePath = input.tool_input?.path || input.tool_input?.file_path || '';

// Skip if no file path or if reading a Person page itself (avoid recursion)
if (!filePath || filePath.includes('/People/')) {
  skip('missing-file-path-or-recursive-person-file');
}

// Skip binary/non-text files (images, PDFs, archives, etc.)
const ext = path.extname(filePath).toLowerCase();
const skipExts = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico', '.svg', '.pdf', '.zip', '.tar', '.gz', '.mp3', '.mp4', '.mov', '.wav', '.pptx', '.xlsx', '.docx'];
if (skipExts.includes(ext)) {
  skip(`unsupported-extension:${ext}`);
}

const { loadPaths } = require('./paths.cjs');
const _paths = loadPaths();
const VAULT_ROOT = _paths.VAULT_ROOT || process.env.CLAUDE_PROJECT_DIR || process.env.VAULT_PATH || process.cwd();
const fullFilePath = filePath.startsWith('/') ? filePath : path.join(VAULT_ROOT, filePath);

const scriptPath = path.join(__dirname, '..', '..', 'core', 'context', 'person_context.py');
const python = resolvePython(VAULT_ROOT);
const result = spawnSync(
  python,
  [scriptPath, '--vault', VAULT_ROOT, '--from-file', fullFilePath, '--format', 'hook-json'],
  {
    encoding: 'utf-8',
    timeout: 8000,
    env: {
      ...process.env,
      VAULT_PATH: VAULT_ROOT,
      PYTHONPATH: path.join(__dirname, '..', '..'),
    },
  },
);

if (result.status !== 0 || !result.stdout) {
  skip(`unexpected-error:${(result.stderr || result.error || 'person-context-python-failed').toString().split('\n')[0]}`);
}

let payload;
try {
  payload = JSON.parse(result.stdout);
} catch (e) {
  skip('unexpected-error:person-context-python-json');
}

if (payload.skip) {
  skip(payload.skip);
}

if (!payload.additionalContext) {
  skip('person-context-parse-empty');
}

const output = {
  continue: true,
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    additionalContext: payload.additionalContext,
  },
};
console.log(JSON.stringify(output));
