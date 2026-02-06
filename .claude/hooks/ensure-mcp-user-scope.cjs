#!/usr/bin/env node
/**
 * PreToolUse hook: enforce user scope for MCP additions.
 *
 * Behavior:
 * - If command is `claude mcp add` without an explicit --scope, ask/confirm (interactive)
 * - If non-interactive, deny with a clear instruction
 * - If --scope user/project is explicit, allow
 */
const fs = require('fs');

let input;
try {
  input = JSON.parse(fs.readFileSync(0, 'utf-8'));
} catch (e) {
  process.exit(0);
}

const command = input?.tool_input?.command || '';
if (!command || !/\bclaude\b\s+mcp\s+add\b/.test(command)) {
  process.exit(0);
}

const hasScope = /\B--scope\b/.test(command);
const hasUserScope = /\B--scope\b\s+user\b/.test(command);
const hasProjectScope = /\B--scope\b\s+project\b/.test(command);

if (hasScope && (hasUserScope || hasProjectScope)) {
  process.exit(0);
}

const nonInteractive =
  input?.hook_context?.mode === 'headless' ||
  input?.hook_context?.interactive === false ||
  input?.is_interactive === false ||
  process.env.CLAUDE_CODE_NONINTERACTIVE === '1';

const reasonLines = [
  'Dex requires an explicit MCP scope so your config stays safe.',
  '',
  'Use the Dex wrapper:',
  '  /dex-add-mcp',
  '',
  'Or run:',
  '  claude mcp add --scope user <server-name> -- <command> <args>',
  '',
  'If you want to share with a team:',
  '  claude mcp add --scope project <server-name> -- <command> <args>'
];

const output = {
  hookSpecificOutput: {
    hookEventName: 'PreToolUse',
    permissionDecision: nonInteractive ? 'deny' : 'ask',
    permissionDecisionReason: reasonLines.join('\n')
  }
};

console.log(JSON.stringify(output));
