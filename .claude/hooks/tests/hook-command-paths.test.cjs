const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const ROOT = path.resolve(__dirname, '../../..');
const SETTINGS_PATH = path.join(ROOT, '.claude/settings.json');
const COMPOSITION_REFRESH = path.join(ROOT, '.claude/hooks/claude-composition-refresh.sh');

function walkCommands(value) {
  if (Array.isArray(value)) return value.flatMap(walkCommands);
  if (value && typeof value === 'object') {
    if (typeof value.command === 'string') return [value.command];
    return Object.values(value).flatMap(walkCommands);
  }
  return [];
}

function hookCommands() {
  const settings = JSON.parse(fs.readFileSync(SETTINGS_PATH, 'utf8'));
  return walkCommands(settings.hooks || {});
}

// Claude Code runs hooks with the cwd of the invoking tool call, which is
// routinely not the vault root (scratchpad, subdirectories, `cd` in compound
// Bash). A bare `.claude/hooks/...` argument therefore resolves against the
// wrong directory and the hook dies before it can read its input.
const RELATIVE_HOOK_ARG = /(^|\s)['"]?\.claude\/hooks\//;

test('no hook command reaches its script through a cwd-relative path', () => {
  const offenders = hookCommands().filter((command) => RELATIVE_HOOK_ARG.test(command));
  assert.deepEqual(
    offenders,
    [],
    `hook commands must anchor script paths to $CLAUDE_PROJECT_DIR:\n${offenders.join('\n')}`,
  );
});

test('every hook script path resolves to a file that exists', () => {
  const missing = [];
  for (const command of hookCommands()) {
    for (const token of command.split(/\s+/)) {
      const cleaned = token.replace(/^["']|["']$/g, '');
      if (!cleaned.includes('.claude/hooks/') && !cleaned.includes('core/utils/')) continue;
      const resolved = cleaned.replace(/^["']?\$\{?CLAUDE_PROJECT_DIR\}?["']?/, ROOT);
      if (!fs.existsSync(resolved)) missing.push(`${cleaned} (in: ${command})`);
    }
  }
  assert.deepEqual(missing, [], `hook scripts not found:\n${missing.join('\n')}`);
});

// The vault runs on macOS and on the Linux replica from one tracked settings
// file, so a hook that reaches for a macOS-only binary has to no-op rather than
// error where that binary does not exist.
test('notification hooks survive a platform without afplay', () => {
  const settings = JSON.parse(fs.readFileSync(SETTINGS_PATH, 'utf8'));
  const commands = [
    ...walkCommands(settings.hooks?.Stop || {}),
    ...walkCommands(settings.hooks?.Notification || {}),
  ];
  assert.ok(commands.length > 0, 'expected Stop/Notification hooks to exist');

  // Stand in for the Linux replica: a PATH with a normal shell and coreutils
  // but no afplay, rather than an empty PATH that no real machine has.
  const linuxLikeBin = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-no-afplay-'));
  for (const tool of ['sh', 'bash', 'env', 'ls']) {
    const source = spawnSync('command', ['-v', tool], { shell: true, encoding: 'utf8' }).stdout.trim();
    if (source) fs.symlinkSync(source, path.join(linuxLikeBin, tool));
  }
  assert.equal(
    spawnSync('/bin/bash', ['-c', 'command -v afplay'], { env: { PATH: linuxLikeBin } }).status,
    1,
    'fixture PATH must not expose afplay',
  );

  for (const command of commands) {
    const result = spawnSync('/bin/bash', ['-c', command], {
      encoding: 'utf8',
      env: { ...process.env, PATH: linuxLikeBin },
    });
    assert.equal(
      result.status,
      0,
      `${command} exited ${result.status} without afplay on PATH:\n${result.stderr}`,
    );
    assert.equal(`${result.stderr}`.trim(), '', `${command} wrote to stderr:\n${result.stderr}`);
  }
});

// Regression proof for the reported failures: the exact PreToolUse hooks that
// errored must survive being launched from an unrelated working directory.
test('PreToolUse hooks run from a foreign cwd', () => {
  const foreignCwd = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-hook-cwd-'));
  const settings = JSON.parse(fs.readFileSync(SETTINGS_PATH, 'utf8'));
  const commands = (settings.hooks?.PreToolUse || []).flatMap((entry) =>
    (entry.hooks || []).map((hook) => hook.command),
  );

  for (const command of commands) {
    const result = spawnSync('/bin/bash', ['-c', command], {
      cwd: foreignCwd,
      encoding: 'utf8',
      env: { ...process.env, CLAUDE_PROJECT_DIR: ROOT },
      input: JSON.stringify({
        tool_name: 'Read',
        tool_input: { file_path: path.join(ROOT, 'README.md') },
      }),
    });
    // Assert only that the hook's own script resolved. A missing npm
    // dependency inside the hook is a different fault and must not be
    // mistaken for the path bug this test guards.
    const script = command
      .split(/\s+/)
      .map((token) => token.replace(/^["']|["']$/g, ''))
      .find((token) => token.includes('.claude/hooks/'));
    const resolved = script.replace(/^["']?\$\{?CLAUDE_PROJECT_DIR\}?["']?/, ROOT);
    const unresolvable = new RegExp(
      `Cannot find module '${resolved}'|${script.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}: No such file`,
    );
    assert.ok(
      !unresolvable.test(`${result.stderr}`),
      `${command} could not reach its script from a foreign cwd:\n${result.stderr}`,
    );
  }
});

test('the composition hook honors the same explicit portable Python command', () => {
  const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-composition-python-'));
  fs.writeFileSync(path.join(sandbox, 'CLAUDE-custom.md'), '# Personal instructions\n');
  const command = path.join(sandbox, 'python command probe');
  const calls = path.join(sandbox, 'python-command-calls');
  fs.writeFileSync(
    command,
    `#!/bin/sh\nprintf '%s\\n' "$*" >> '${calls}'\nprintf '%s\\n' recomposed\n`,
    { mode: 0o755 },
  );

  const result = spawnSync('/bin/bash', [COMPOSITION_REFRESH], {
    encoding: 'utf8',
    env: {
      ...process.env,
      CLAUDE_PROJECT_DIR: sandbox,
      DEX_PYTHON: command,
    },
  });

  assert.equal(result.status, 0, result.stderr);
  assert.equal(fs.existsSync(calls), true);
  assert.match(result.stdout, /customisations have been applied/);
});

test('the composition hook carries native Windows Python discovery', () => {
  const source = fs.readFileSync(COMPOSITION_REFRESH, 'utf8');
  assert.match(source, /\.venv\/Scripts\/python\.exe/);
  assert.match(source, /py -3/);
  assert.doesNotMatch(source, /(?:^|\s)python3\s+-[cm]\b/m);
});
