'use strict';

const assert = require('node:assert/strict');
const childProcess = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const yaml = require('js-yaml');

const repoRoot = path.resolve(__dirname, '../../..');
const provisionScript = path.join(repoRoot, 'core', 'provision.cjs');
const contract = JSON.parse(fs.readFileSync(path.join(repoRoot, 'core', 'provision-contract.json'), 'utf8'));

function copy(source, target) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.copyFileSync(source, target);
}

function makeReleaseTree({ claude = true } = {}) {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-provision-'));
  copy(path.join(repoRoot, 'System', '.mcp.json.example'), path.join(vault, 'System', '.mcp.json.example'));
  copy(path.join(repoRoot, 'System', 'user-profile-template.yaml'), path.join(vault, 'System', 'user-profile-template.yaml'));
  copy(path.join(repoRoot, 'core', 'paths.py'), path.join(vault, 'core', 'paths.py'));
  fs.mkdirSync(path.join(vault, '.scripts'), { recursive: true });
  copy(path.join(repoRoot, 'package.json'), path.join(vault, 'package.json'));
  if (claude) copy(path.join(repoRoot, 'CLAUDE.md'), path.join(vault, 'CLAUDE.md'));
  return vault;
}

function runProvision(vault, args = []) {
  const result = childProcess.spawnSync(
    process.execPath,
    [provisionScript, '--path', vault, ...args, '--json'],
    { encoding: 'utf8' },
  );
  let summary = null;
  try { summary = JSON.parse(result.stdout); } catch (_) { /* asserted by caller */ }
  return { ...result, summary };
}

function fileSnapshot(root) {
  const result = {};
  function walk(directory) {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const filePath = path.join(directory, entry.name);
      if (entry.isDirectory()) walk(filePath);
      else result[path.relative(root, filePath)] = fs.readFileSync(filePath).toString('base64');
    }
  }
  walk(root);
  return result;
}

function withVault(callback, options) {
  const vault = makeReleaseTree(options);
  try { return callback(vault); } finally { fs.rmSync(vault, { recursive: true, force: true }); }
}

test('fresh provision creates the full profile, seeds, MCP config, paths, and byte-stable marker', () => {
  withVault(vault => {
    const profilePath = path.join(vault, 'desktop-profile.json');
    fs.writeFileSync(profilePath, JSON.stringify({
      name: 'Ada Lovelace',
      role: 'CTO',
      company: 'Analytical Engines',
      company_size: 'scaling',
      email_domain: 'engines.test',
      work_email: 'ada@engines.test',
      obsidian_mode: true,
      pillars: [
        { name: 'Build', description: 'Ship the engine' },
        { name: 'Learn Fast', description: 'Run experiments' },
      ],
      communication: { formality: 'formal', directness: 'very_direct' },
      ignored_key: 'not accepted',
    }));

    const first = runProvision(vault, ['--profile', profilePath]);
    assert.equal(first.status, 0, first.stderr);
    assert.equal(first.summary.ok, true);
    assert.ok(first.summary.created.length > 0);

    for (const directory of contract.para_directories) {
      assert.equal(fs.statSync(path.join(vault, directory)).isDirectory(), true, directory);
    }
    assert.match(fs.readFileSync(path.join(vault, contract.seed_files.tasks), 'utf8'), /## Build #build/);
    assert.equal(fs.existsSync(path.join(vault, contract.seed_files.week_priorities)), true);

    const profile = yaml.load(fs.readFileSync(path.join(vault, 'System', 'user-profile.yaml'), 'utf8'));
    assert.equal(profile.name, 'Ada Lovelace');
    assert.equal(profile.work_email, 'ada@engines.test');
    assert.deepEqual(profile.entity_creation, { mode: 'auto' });
    assert.equal(profile.communication.formality, 'formal');
    assert.equal(profile.communication.detail_level, 'concise');
    assert.equal(profile.ignored_key, undefined);
    assert.deepEqual(profile.capabilities, {
      career: { enabled: false },
      companies: { enabled: false },
      quarter_goals: { enabled: false },
    });
    assert.equal(fs.existsSync(path.join(vault, '05-Areas', 'Career')), false);
    assert.equal(fs.existsSync(path.join(vault, '05-Areas', 'Companies')), false);
    assert.equal(fs.existsSync(path.join(vault, '01-Quarter_Goals')), false);

    const pillars = yaml.load(fs.readFileSync(path.join(vault, 'System', 'pillars.yaml'), 'utf8'));
    assert.deepEqual(pillars.pillars[0], {
      id: 'build', name: 'Build', description: 'Ship the engine',
    });
    const marker = JSON.parse(fs.readFileSync(path.join(vault, 'System', '.onboarding-complete'), 'utf8'));
    assert.equal(marker.completed, true);
    assert.equal(marker.provisioned_by, 'core/provision.cjs');
    assert.equal(marker.adopted, false);
    assert.equal(marker.version, JSON.parse(fs.readFileSync(path.join(vault, 'package.json'))).version);

    const mcp = JSON.parse(fs.readFileSync(path.join(vault, '.mcp.json'), 'utf8'));
    assert.equal(mcp.mcpServers['work-mcp'].env.VAULT_PATH, vault);
    const paths = JSON.parse(fs.readFileSync(path.join(vault, 'core', 'paths.json'), 'utf8'));
    assert.equal(paths.VAULT_ROOT, vault);
    assert.equal(paths.CONTACTS_STATE_FILE, path.join(vault, 'System', '.dex', 'contacts.json'));
    assert.match(paths._comment, /paths\.py regenerates/);

    const before = fileSnapshot(vault);
    const second = runProvision(vault, ['--profile', profilePath]);
    assert.equal(second.status, 0, second.stderr);
    assert.deepEqual(second.summary.created, []);
    assert.deepEqual(fileSnapshot(vault), before);
  });
});

test('fresh provision surfaces only the selected capability rooms', () => {
  withVault(vault => {
    const profilePath = path.join(vault, 'desktop-profile.json');
    fs.writeFileSync(profilePath, JSON.stringify({
      capabilities: {
        career: { enabled: true },
        companies: { enabled: false },
        quarter_goals: { enabled: false },
      },
    }));

    const result = runProvision(vault, ['--profile', profilePath]);

    assert.equal(result.status, 0, result.stderr);
    assert.equal(fs.existsSync(path.join(vault, '05-Areas', 'Career', 'Evidence', 'README.md')), true);
    for (const skill of ['career-setup', 'career-coach', 'resume-builder']) {
      assert.equal(fs.existsSync(path.join(vault, '.claude', 'skills', skill, 'SKILL.md')), true);
    }
    assert.equal(fs.existsSync(path.join(vault, '05-Areas', 'Companies')), false);
    assert.equal(fs.existsSync(path.join(vault, '01-Quarter_Goals')), false);
  });
});

test('fresh provision fills omitted capability rooms from template defaults', () => {
  withVault(vault => {
    const profilePath = path.join(vault, 'desktop-profile.json');
    fs.writeFileSync(profilePath, JSON.stringify({
      capabilities: { career: { enabled: true } },
    }));

    const result = runProvision(vault, ['--profile', profilePath]);

    assert.equal(result.status, 0, result.stderr);
    const profile = yaml.load(fs.readFileSync(path.join(vault, 'System', 'user-profile.yaml'), 'utf8'));
    assert.deepEqual(profile.capabilities, {
      career: { enabled: true },
      companies: { enabled: false },
      quarter_goals: { enabled: false },
    });
  });
});

test('adopt migrates the legacy quarterly switch forward before provisioning', () => {
  withVault(vault => {
    fs.writeFileSync(
      path.join(vault, 'System', 'user-profile.yaml'),
      'name: Existing\nquarterly_planning:\n  enabled: true\n  q1_start_month: 4\n',
    );

    const result = runProvision(vault, ['--adopt']);

    assert.equal(result.status, 0, result.stderr);
    const profile = yaml.load(fs.readFileSync(path.join(vault, 'System', 'user-profile.yaml'), 'utf8'));
    assert.equal(profile.capabilities.quarter_goals.enabled, true);
    assert.equal(profile.quarterly_planning.q1_start_month, 4);
    assert.equal(fs.existsSync(path.join(vault, '01-Quarter_Goals', 'Quarter_Goals.md')), true);
    assert.equal(fs.existsSync(path.join(vault, '.claude', 'skills', 'quarter-plan', 'SKILL.md')), true);
    assert.equal(fs.existsSync(path.join(vault, '.claude', 'skills', 'quarter-review', 'SKILL.md')), true);
  });
});

test('adopt preserves user values and content, fills profile gaps, and merges MCP servers', () => {
  withVault(vault => {
    const profilePath = path.join(vault, 'desktop-profile.json');
    fs.writeFileSync(profilePath, JSON.stringify({
      name: 'Replacement Name', role: 'Founder', company: 'New Co',
      pillars: [{ name: 'Replacement' }], communication: { formality: 'formal' },
    }));
    fs.writeFileSync(path.join(vault, 'System', 'user-profile.yaml'), 'name: Existing Name\ncustom: keep\n');
    const pillarsContent = 'pillars:\n  - id: mine\n    name: Mine\n    description: Keep me\n';
    fs.writeFileSync(path.join(vault, 'System', 'pillars.yaml'), pillarsContent);
    fs.mkdirSync(path.join(vault, '00-Inbox', 'Ideas'), { recursive: true });
    fs.writeFileSync(path.join(vault, '00-Inbox', 'Ideas', 'mine.md'), 'untouched\n');
    const extension = 'MY PRIVATE EXTENSION\nwith exact bytes';
    fs.appendFileSync(path.join(vault, 'CLAUDE.md'), `\n${extension}\n`);
    fs.writeFileSync(path.join(vault, '.mcp.json'), JSON.stringify({
      extra: 'keep',
      mcpServers: {
        'work-mcp': { command: 'mine' },
        'user-added': { command: 'custom' },
      },
    }, null, 2));

    const result = runProvision(vault, ['--profile', profilePath, '--adopt']);
    assert.equal(result.status, 0, result.stderr);
    const profile = yaml.load(fs.readFileSync(path.join(vault, 'System', 'user-profile.yaml'), 'utf8'));
    assert.equal(profile.name, 'Existing Name');
    assert.equal(profile.role, 'Founder');
    assert.equal(profile.custom, 'keep');
    // Adopt must NOT flip an existing vault to auto-create: the key stays absent
    // so the engine's suggest default applies (existing users opt in deliberately).
    assert.equal(profile.entity_creation, undefined);
    assert.equal(fs.readFileSync(path.join(vault, 'System', 'pillars.yaml'), 'utf8'), pillarsContent);
    assert.equal(fs.readFileSync(path.join(vault, '00-Inbox', 'Ideas', 'mine.md'), 'utf8'), 'untouched\n');
    assert.match(fs.readFileSync(path.join(vault, 'CLAUDE.md'), 'utf8'), new RegExp(extension.replace('\n', '\\n')));
    const mcp = JSON.parse(fs.readFileSync(path.join(vault, '.mcp.json'), 'utf8'));
    assert.deepEqual(mcp.mcpServers['work-mcp'], { command: 'mine' });
    assert.deepEqual(mcp.mcpServers['user-added'], { command: 'custom' });
    assert.equal(mcp.extra, 'keep');
    assert.equal(mcp.mcpServers['calendar-mcp'].env.VAULT_PATH, vault);
    assert.equal(JSON.parse(fs.readFileSync(path.join(vault, 'System', '.onboarding-complete'))).adopted, true);
  });
});

test('adopt preserves an existing entity_creation choice', () => {
  withVault(vault => {
    fs.writeFileSync(
      path.join(vault, 'System', 'user-profile.yaml'),
      'name: Existing\nentity_creation:\n  mode: "off"\n',
    );
    const result = runProvision(vault, ['--adopt']);
    assert.equal(result.status, 0, result.stderr);
    const profile = yaml.load(fs.readFileSync(path.join(vault, 'System', 'user-profile.yaml'), 'utf8'));
    assert.deepEqual(profile.entity_creation, { mode: 'off' });
  });
});

test('adopt never overwrites existing seeds even without an onboarding marker', () => {
  withVault(vault => {
    fs.mkdirSync(path.join(vault, '03-Tasks'), { recursive: true });
    fs.writeFileSync(path.join(vault, '03-Tasks', 'Tasks.md'), 'my tasks\n');
    assert.equal(fs.existsSync(path.join(vault, 'System', '.onboarding-complete')), false);
    const result = runProvision(vault, ['--adopt']);
    assert.equal(result.status, 0, result.stderr);
    assert.equal(fs.readFileSync(path.join(vault, '03-Tasks', 'Tasks.md'), 'utf8'), 'my tasks\n');
  });
});

test('dry-run reports all work and writes nothing', () => {
  withVault(vault => {
    const before = fileSnapshot(vault);
    const result = runProvision(vault, ['--dry-run']);
    assert.equal(result.status, 0, result.stderr);
    assert.equal(result.summary.dry_run, true);
    assert.ok(result.summary.created.length > 0);
    assert.deepEqual(fileSnapshot(vault), before);
  });
});

test('missing shipped paths produce one clear non-zero failure', () => {
  const vault = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-provision-missing-'));
  try {
    const result = runProvision(vault);
    assert.notEqual(result.status, 0);
    assert.match(result.summary.errors[0], /System\/\.mcp\.json\.example/);
    assert.match(result.summary.errors[0], /core\/paths\.py/);
    assert.match(result.summary.errors[0], /\.scripts\//);
    assert.match(result.summary.errors[0], /System\/user-profile-template\.yaml/);
  } finally { fs.rmSync(vault, { recursive: true, force: true }); }
});

test('USER_EXTENSIONS content is preserved byte-for-byte while the profile block changes', () => {
  withVault(vault => {
    const claudePath = path.join(vault, 'CLAUDE.md');
    const before = fs.readFileSync(claudePath, 'utf8').match(/## USER_EXTENSIONS_START[\s\S]*?## USER_EXTENSIONS_END/)[0];
    const profilePath = path.join(vault, 'profile.json');
    fs.writeFileSync(profilePath, JSON.stringify({ name: 'Grace Hopper' }));
    assert.equal(runProvision(vault, ['--profile', profilePath]).status, 0);
    const content = fs.readFileSync(claudePath, 'utf8');
    assert.match(content, /\*\*Name:\*\* Grace Hopper/);
    assert.equal(content.match(/## USER_EXTENSIONS_START[\s\S]*?## USER_EXTENSIONS_END/)[0], before);
  });
});

test('ownership contract is valid and covers every release top-level path', () => {
  assert.equal(contract.version, 1);
  assert.deepEqual(Object.keys(contract.ownership).sort(), [
    'generated', 'mergeable-config', 'shipped', 'user-owned',
  ]);
  const distignore = fs.readFileSync(path.join(repoRoot, '.distignore'), 'utf8')
    .split('\n')
    .map(line => line.split('#')[0].trim())
    .filter(Boolean);
  const tracked = childProcess.execFileSync('git', ['ls-files'], { cwd: repoRoot, encoding: 'utf8' })
    .trim().split('\n').filter(Boolean);
  const ships = tracked.filter(file => !distignore.some(pattern => {
    const normalized = pattern.replace(/\/$/, '');
    return file === normalized || file.startsWith(`${normalized}/`);
  }));
  const coveredRoots = new Set(Object.values(contract.ownership).flat().map(rule => rule.split('/')[0]));
  const missing = [...new Set(ships.map(file => file.split('/')[0]))]
    .filter(topLevel => !coveredRoots.has(topLevel));
  assert.deepEqual(missing, []);
});
