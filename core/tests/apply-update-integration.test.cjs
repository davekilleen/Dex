'use strict';

const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const test = require('node:test');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const FIXTURE_SCRIPT = path.join(REPO_ROOT, 'scripts', 'make-aged-vault-fixture.sh');
const MIGRATOR_RELATIVE = path.join('core', 'migrations', 'v1-to-v2-brain-vault-split.cjs');
const UPDATER_PATH = path.join(REPO_ROOT, 'core', 'update', 'apply-update.cjs');

function command(name, args, options = {}) {
  const result = spawnSync(name, args, {
    cwd: options.cwd || REPO_ROOT,
    encoding: 'utf8',
    env: { ...process.env, ...(options.env || {}) },
    timeout: options.timeout || 180_000,
  });
  const statuses = options.expectedStatuses || [options.expectedStatus ?? 0];
  assert.ok(
    statuses.includes(result.status),
    `${name} ${args.join(' ')}\nstatus=${result.status}\n${result.stdout}\n${result.stderr}`,
  );
  return result;
}

function git(cwd, ...args) {
  return command('git', args, { cwd }).stdout.trim();
}

function fixtureGitEnvironment(fixtureRoot, remote) {
  const wrapperDirectory = path.join(fixtureRoot, 'git-wrapper');
  fs.mkdirSync(wrapperDirectory, { recursive: true });
  const wrapper = path.join(wrapperDirectory, 'git');
  const source = `#!/usr/bin/env node
'use strict';
const { spawnSync } = require('node:child_process');
const args = process.argv.slice(2);
const commandIndex = args.findIndex((arg) => arg === 'fetch' || arg === 'ls-remote');
if (commandIndex >= 0 && !(args[commandIndex] === 'ls-remote' && args.includes('--get-url'))) {
  const originIndex = args.findIndex((arg, index) => (
    index > commandIndex
    && (arg === 'origin' || arg === 'https://github.com/davekilleen/Dex.git')
  ));
  if (originIndex >= 0) {
    args[originIndex] = process.env.DEX_UPDATE_FIXTURE_REMOTE;
    args.unshift('-c', 'protocol.file.allow=always');
  }
}
const result = spawnSync(process.env.DEX_REAL_GIT, args, { stdio: 'inherit', env: process.env });
if (result.error) throw result.error;
process.exitCode = result.status === null ? 1 : result.status;
`;
  fs.writeFileSync(wrapper, source, { mode: 0o755 });
  return {
    PATH: `${wrapperDirectory}${path.delimiter}${process.env.PATH}`,
    DEX_REAL_GIT: command('/usr/bin/which', ['git']).stdout.trim(),
    DEX_UPDATE_FIXTURE_REMOTE: remote,
  };
}

function makeFixture() {
  const result = command('bash', [FIXTURE_SCRIPT], { timeout: 240_000 });
  const match = result.stdout.match(/Fixture ready: (.+)\n?$/m);
  assert.ok(match, result.stdout);
  return match[1];
}

function write(root, relative, content) {
  const destination = path.join(root, relative);
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.writeFileSync(destination, content);
}

function refreshManifest(repo) {
  const manifest = path.join(repo, 'System', '.installed-files.manifest');
  fs.mkdirSync(path.dirname(manifest), { recursive: true });
  fs.writeFileSync(manifest, '');
  git(repo, 'add', '-A');
  const tree = git(repo, 'write-tree');
  const paths = git(repo, 'ls-tree', '-r', '--name-only', tree).split('\n').filter(Boolean).sort();
  fs.writeFileSync(manifest, `${paths.join('\n')}\n`);
  git(repo, 'add', '--', 'System/.installed-files.manifest');
}

function fabricateRelease(vault) {
  const fixtureRoot = path.dirname(vault);
  const upstream = path.join(fixtureRoot, 'upstream');
  git(upstream, 'checkout', '--quiet', 'release');
  write(upstream, 'core/update/synthetic-added.cjs', 'module.exports = "v2.0.1";\n');
  write(upstream, 'README.md', '# Dex synthetic v2.0.1\n');
  fs.copyFileSync(UPDATER_PATH, path.join(upstream, 'core', 'update', 'apply-update.cjs'));
  fs.unlinkSync(path.join(upstream, 'LICENSE'));
  fs.unlinkSync(path.join(upstream, 'COMMERCIAL_LICENSE.md'));
  const packagePath = path.join(upstream, 'package.json');
  const packageJson = JSON.parse(fs.readFileSync(packagePath, 'utf8'));
  packageJson.version = '2.0.1';
  packageJson.dex = { ...(packageJson.dex || {}), vault_schema: 1, brain_support: '>=2.0.0 <3.0.0' };
  fs.writeFileSync(packagePath, `${JSON.stringify(packageJson, null, 2)}\n`);
  refreshManifest(upstream);
  git(upstream, 'commit', '--quiet', '-m', 'release: synthetic v2.0.1');
  git(upstream, 'tag', '-f', 'dist-v2.0.1');
  return { upstream, oid: git(upstream, 'rev-parse', 'HEAD') };
}

function digest(file) {
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

test('apply, crash-resume, and rollback replace only owned brain files in an aged migrated vault', { timeout: 300_000 }, () => {
  const vault = makeFixture();
  command(process.execPath, [path.join(vault, MIGRATOR_RELATIVE), '--auto'], {
    cwd: vault,
    timeout: 240_000,
  });

  const brain = path.join(vault, '.dex', 'brain.git');
  const previousOid = git(vault, `--git-dir=${brain}`, 'rev-parse', 'refs/dex/installed');
  const para = path.join(vault, '04-Projects', 'ignored-by-v1.md');
  const taskSeed = path.join(vault, '03-Tasks', 'Tasks.md');
  const custom = path.join(vault, 'CLAUDE-custom.md');
  const paraHash = digest(para);
  const seedHash = digest(taskSeed);
  const customBytes = fs.readFileSync(custom);
  fs.appendFileSync(path.join(vault, 'COMMERCIAL_LICENSE.md'), '\nUser note on commercial terms.\n');
  const keptDroppedBytes = fs.readFileSync(path.join(vault, 'COMMERCIAL_LICENSE.md'));

  const release = fabricateRelease(vault);
  const transportEnvironment = fixtureGitEnvironment(path.dirname(vault), release.upstream);
  const killed = spawnSync(process.execPath, [UPDATER_PATH, '--apply', '--target', 'dist-v2.0.1'], {
    cwd: vault,
    encoding: 'utf8',
    env: {
      ...process.env,
      ...transportEnvironment,
      DEX_UPDATE_TEST_SIGKILL_AFTER_MUTATION: 'replace brain file README.md',
    },
    timeout: 240_000,
  });
  assert.equal(killed.status, null, `${killed.stdout}\n${killed.stderr}`);
  assert.equal(killed.signal, 'SIGKILL');
  const interrupted = JSON.parse(fs.readFileSync(path.join(vault, 'System', '.dex', 'update-state.json'), 'utf8'));
  assert.equal(interrupted.pendingMutation, 'replace brain file README.md');
  assert.equal(fs.readFileSync(path.join(vault, 'README.md'), 'utf8'), '# Dex synthetic v2.0.1\n');

  const resumed = command(process.execPath, [UPDATER_PATH, '--resume'], {
    cwd: vault,
    env: transportEnvironment,
    timeout: 240_000,
  });
  assert.match(resumed.stdout, /DEX_UPDATE_COMPLETE/);
  assert.match(resumed.stdout, /DEX_DEPENDENCIES npm=[01] pip=[01]/);

  assert.equal(digest(para), paraHash);
  assert.equal(digest(taskSeed), seedHash);
  assert.deepEqual(fs.readFileSync(custom), customBytes);
  assert.equal(fs.readFileSync(path.join(vault, 'README.md'), 'utf8'), '# Dex synthetic v2.0.1\n');
  assert.equal(fs.readFileSync(path.join(vault, 'core', 'update', 'synthetic-added.cjs'), 'utf8'), 'module.exports = "v2.0.1";\n');
  assert.equal(fs.existsSync(path.join(vault, 'LICENSE')), false);
  assert.deepEqual(fs.readFileSync(path.join(vault, 'COMMERCIAL_LICENSE.md')), keptDroppedBytes);
  assert.deepEqual(fs.readFileSync(custom), customBytes);
  assert.match(fs.readFileSync(path.join(vault, 'CLAUDE.md'), 'utf8'), /fixture sentinel: café/);
  assert.equal(fs.existsSync(path.join(vault, 'System', 'update-report.md')), false);
  assert.match(fs.readFileSync(path.join(vault, 'System', '.dex', 'update-report.md'), 'utf8'), /README\.md.*backed up/is);
  const backupReadme = path.join(vault, 'System', 'backups', 'pre-update-2.0.1', 'README.md');
  assert.match(fs.readFileSync(backupReadme, 'utf8'), /Fixture user patch|Another long-time user note/);
  assert.equal(git(vault, `--git-dir=${brain}`, 'rev-parse', 'refs/dex/installed'), release.oid);
  const history = JSON.parse(fs.readFileSync(path.join(vault, 'System', '.dex', 'installed-history.json'), 'utf8'));
  assert.equal(history.at(-1).oid, release.oid);
  assert.equal(history.at(-1).previous, previousOid);
  assert.match(history.at(-1).manifestHash, /^[a-f0-9]{64}$/);
  const heldBack = JSON.parse(fs.readFileSync(path.join(vault, 'System', '.dex', 'held-back-paths.json'), 'utf8'));
  const machineExclude = fs.readFileSync(path.join(vault, '.git', 'info', 'exclude'), 'utf8');
  assert.match(machineExclude, /^\/System\/backups\/$/m);
  for (const relative of heldBack.paths) {
    assert.match(machineExclude, new RegExp(`^/${relative.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`, 'm'));
  }
  const mcp = JSON.parse(fs.readFileSync(path.join(vault, '.mcp.json'), 'utf8'));
  assert.ok(mcp.mcpServers['custom-fixture']);
  assert.ok(mcp.mcpServers['work-mcp']);
  assert.equal(JSON.stringify(mcp).includes('{{VAULT_PATH}}'), false);

  const rolledBack = command(process.execPath, [UPDATER_PATH, '--rollback'], {
    cwd: vault,
    env: transportEnvironment,
    timeout: 240_000,
  });
  assert.match(rolledBack.stdout, /DEX_ROLLBACK_COMPLETE/);
  assert.equal(git(vault, `--git-dir=${brain}`, 'rev-parse', 'refs/dex/installed'), previousOid);
  assert.equal(fs.existsSync(path.join(vault, 'core', 'update', 'synthetic-added.cjs')), false);
  assert.equal(fs.existsSync(path.join(vault, 'LICENSE')), true);
  assert.equal(digest(para), paraHash);
  assert.equal(digest(taskSeed), seedHash);
  assert.deepEqual(fs.readFileSync(custom), customBytes);
});
