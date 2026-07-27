const test = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { loadPaths } = require('../paths.cjs');

const CONCIERGE_PATH = path.resolve(__dirname, '../integration-concierge.cjs');
const SOURCE_PATHS = loadPaths();

function remapVaultPath(vault, sourcePath) {
  return path.join(vault, path.relative(SOURCE_PATHS.VAULT_ROOT, sourcePath));
}

function createFixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-integration-concierge-'));
  const vault = path.join(root, 'vault');
  const appDir = path.join(root, 'Applications');
  const inboxDir = remapVaultPath(vault, SOURCE_PATHS.INBOX_DIR);
  const projectsDir = remapVaultPath(vault, SOURCE_PATHS.PROJECTS_DIR);
  const peopleDir = remapVaultPath(vault, SOURCE_PATHS.PEOPLE_DIR);
  const systemDir = remapVaultPath(vault, SOURCE_PATHS.SYSTEM_DIR);
  const integrationsDir = path.join(systemDir, 'integrations');

  for (const dir of [
    inboxDir,
    projectsDir,
    path.join(peopleDir, 'Internal'),
    integrationsDir,
    appDir,
  ]) {
    fs.mkdirSync(dir, { recursive: true });
  }

  t.after(() => fs.rmSync(root, { recursive: true, force: true }));

  return {
    root,
    vault,
    appDir,
    inboxDir,
    systemDir,
    configFile: path.join(integrationsDir, 'config.yaml'),
    env: {
      CLAUDE_PROJECT_DIR: vault,
      DEX_APP_DIRS: appDir,
      VAULT_PATH: vault,
    },
  };
}

function runConcierge(env) {
  const result = spawnSync(process.execPath, [CONCIERGE_PATH], {
    env: { ...process.env, ...env },
    encoding: 'utf-8',
    timeout: 5_000,
  });

  assert.equal(
    result.status,
    0,
    `integration-concierge.cjs exited ${result.status}\nstdout:\n${result.stdout}\nstderr:\n${result.stderr}`,
  );
  return JSON.parse(result.stdout);
}

function recommendationFor(output, id) {
  return [
    ...output.high_value,
    ...output.moderate_value,
    ...output.available,
  ].find((entry) => entry.id === id);
}

function assertOutputShape(output) {
  assert.deepEqual(Object.keys(output), [
    'high_value',
    'moderate_value',
    'available',
    'already_connected',
    'connect_detected',
  ]);
}

const CURATED_SETUP_ROUTES = {
  'google-workspace': '/google-workspace-setup',
  teams: '/ms-teams-setup',
  todoist: '/todoist-setup',
  things: '/things-setup',
  trello: '/trello-setup',
  zoom: '/zoom-setup',
  atlassian: '/atlassian-setup',
  // Granola is curated, not a /connect route: granola_server.py reads
  // GRANOLA_API_KEY from the environment or the vault .env, so a credential
  // stored by the connection manager would be invisible to it.
  granola: '/granola-setup',
};

const CONNECT_APP_ROUTES = {
  slack: { name: 'Slack', shortName: 'Slack', app: 'Slack.app' },
  notion: { name: 'Notion', shortName: 'Notion', app: 'Notion.app' },
  linear: { name: 'Linear', shortName: 'Linear', app: 'Linear.app' },
  obsidian: { name: 'Obsidian', shortName: 'Obsidian', app: 'Obsidian.app' },
  cursor: { name: 'Cursor', shortName: 'Cursor', app: 'Cursor.app' },
  figma: { name: 'Figma', shortName: 'Figma', app: 'Figma.app' },
};

test('curated integrations preserve their setup skills and ordering', (t) => {
  const fixture = createFixture(t);
  const output = runConcierge(fixture.env);

  assert.deepEqual(
    output.available.map((entry) => entry.id),
    Object.keys(CURATED_SETUP_ROUTES),
  );
  assert.deepEqual(output.connect_detected, []);
  for (const [id, setup] of Object.entries(CURATED_SETUP_ROUTES)) {
    const entry = recommendationFor(output, id);
    assert.equal(entry.route, 'skill', id);
    assert.equal(entry.setup, setup, id);
  }
});

test('installed detection-only apps use connect routes without fabricated setup skills', (t) => {
  const fixture = createFixture(t);
  for (const { app } of Object.values(CONNECT_APP_ROUTES)) {
    fs.mkdirSync(path.join(fixture.appDir, app));
  }

  const output = runConcierge(fixture.env);
  const legacyEntries = [
    ...output.high_value,
    ...output.moderate_value,
    ...output.available,
    ...output.already_connected,
  ];

  for (const [id, expected] of Object.entries(CONNECT_APP_ROUTES)) {
    const entry = output.connect_detected.find((candidate) => candidate.id === id);
    assert.ok(entry, id);
    assert.equal(entry.route, 'connect', id);
    assert.equal(Object.hasOwn(entry, 'setup'), false, id);
    assert.equal(Object.hasOwn(entry, 'setupSkill'), false, id);
    assert.equal(entry.name, expected.name, id);
    assert.equal(entry.shortName, expected.shortName, id);
    assert.deepEqual(entry.installedApps, [expected.app], id);
    assert.equal(entry.reason, 'installed on your Mac', id);
    assert.ok(entry.value, id);
    assert.equal(legacyEntries.some((candidate) => candidate.id === id), false, id);
  }
});

test('installed Things app promotes the integration to high value', (t) => {
  const fixture = createFixture(t);
  fs.mkdirSync(path.join(fixture.appDir, 'Things3.app'));

  const output = runConcierge(fixture.env);
  const things = output.high_value.find((entry) => entry.id === 'things');

  assert.ok(things, JSON.stringify(output, null, 2));
  assert.equal(things.reason, 'installed on your Mac');
  assert.ok(things.score >= 6);
  assert.deepEqual(things.installedApps, ['Things3.app']);
  assert.deepEqual(things.configuredMcp, []);
});

test('installed app matching is case insensitive across configured app directories', (t) => {
  const fixture = createFixture(t);
  const secondAppDir = path.join(fixture.root, 'User Applications');
  fs.mkdirSync(path.join(secondAppDir, 'things3.app'), { recursive: true });

  const output = runConcierge({
    ...fixture.env,
    DEX_APP_DIRS: [fixture.appDir, secondAppDir].join(path.delimiter),
  });
  const things = output.high_value.find((entry) => entry.id === 'things');

  assert.ok(things, JSON.stringify(output, null, 2));
  assert.equal(things.reason, 'installed on your Mac');
  assert.deepEqual(things.installedApps, ['things3.app']);
});

test('integration with no detected signals stays available', (t) => {
  const fixture = createFixture(t);

  const output = runConcierge(fixture.env);
  const things = output.available.find((entry) => entry.id === 'things');

  assert.ok(things, JSON.stringify(output, null, 2));
  assert.equal(things.reason, 'available to connect');
  assert.deepEqual(things.installedApps, []);
  assert.deepEqual(things.configuredMcp, []);
});

test('configured Trello MCP server boosts an integration that is not enabled', (t) => {
  const fixture = createFixture(t);
  fs.writeFileSync(
    path.join(fixture.vault, '.mcp.json'),
    JSON.stringify({ mcpServers: { 'mcp-server-trello': {} } }),
  );

  const output = runConcierge(fixture.env);
  const trello = recommendationFor(output, 'trello');

  assert.ok(trello, JSON.stringify(output, null, 2));
  assert.equal(trello.reason, 'already set up but not switched on yet');
  assert.ok(trello.score >= 4);
  assert.deepEqual(trello.configuredMcp, ['mcp-server-trello']);
  assert.equal(output.already_connected.some((entry) => entry.id === 'trello'), false);
});

test('configured MCP server matching allows a longer server-name substring', (t) => {
  const fixture = createFixture(t);
  fs.writeFileSync(
    path.join(fixture.vault, '.mcp.json'),
    JSON.stringify({ mcpServers: { 'todoist-mcp-server': {} } }),
  );

  const output = runConcierge(fixture.env);
  const todoist = recommendationFor(output, 'todoist');

  assert.ok(todoist, JSON.stringify(output, null, 2));
  assert.equal(todoist.reason, 'already set up but not switched on yet');
  assert.deepEqual(todoist.configuredMcp, ['todoist-mcp-server']);
});

test('configured MCP substring matching does not accept a shorter generic key', (t) => {
  const fixture = createFixture(t);
  fs.writeFileSync(
    path.join(fixture.vault, '.mcp.json'),
    JSON.stringify({ mcpServers: { mcp: {} } }),
  );

  const output = runConcierge(fixture.env);

  for (const id of ['google-workspace', 'teams', 'todoist', 'things', 'trello', 'zoom', 'atlassian']) {
    assert.deepEqual(recommendationFor(output, id).configuredMcp, []);
  }
});

test('enabled integration stays already connected even when its app is installed', (t) => {
  const fixture = createFixture(t);
  fs.mkdirSync(path.join(fixture.appDir, 'Trello.app'));
  fs.writeFileSync(fixture.configFile, 'trello:\n  enabled: true\n');

  const output = runConcierge(fixture.env);

  assert.deepEqual(
    output.already_connected.find((entry) => entry.id === 'trello'),
    { id: 'trello', name: 'Trello' },
  );
  assert.equal(recommendationFor(output, 'trello'), undefined);
});

test('malformed MCP config is ignored without changing the output tiers', (t) => {
  const fixture = createFixture(t);
  fs.writeFileSync(path.join(fixture.vault, '.mcp.json'), '{not valid JSON');

  const output = runConcierge(fixture.env);
  const trello = output.available.find((entry) => entry.id === 'trello');

  assertOutputShape(output);
  assert.ok(trello, JSON.stringify(output, null, 2));
  assert.equal(trello.reason, 'available to connect');
  assert.deepEqual(trello.configuredMcp, []);
});

test('vault text signals still produce a mentions-based reason', (t) => {
  const fixture = createFixture(t);
  fs.writeFileSync(
    path.join(fixture.inboxDir, 'trello-note.md'),
    '# Planning\n\nWe should review the Trello board before the meeting.\n',
  );

  const output = runConcierge(fixture.env);
  const trello = recommendationFor(output, 'trello');

  assert.ok(trello, JSON.stringify(output, null, 2));
  assert.ok(trello.mentions > 0);
  assert.ok(trello.examples.length > 0);
  assert.equal(
    trello.reason,
    `${trello.mentions} mention${trello.mentions === 1 ? '' : 's'} in your notes (e.g. ${trello.examples[0]})`,
  );
  assert.deepEqual(trello.installedApps, []);
  assert.deepEqual(trello.configuredMcp, []);
});

test('MCP configs are unioned across candidate files and support top-level server keys', (t) => {
  const fixture = createFixture(t);
  const claudeDir = path.join(fixture.vault, '.claude');
  fs.mkdirSync(claudeDir);
  fs.writeFileSync(
    path.join(fixture.systemDir, '.mcp.json'),
    JSON.stringify({ 'zoom-mcp': {} }),
  );
  fs.writeFileSync(
    path.join(claudeDir, 'mcp-servers.json'),
    JSON.stringify({ mcpServers: { 'teams-mcp': {} } }),
  );

  const output = runConcierge(fixture.env);
  const zoom = recommendationFor(output, 'zoom');
  const teams = recommendationFor(output, 'teams');

  assert.deepEqual(zoom.configuredMcp, ['zoom-mcp']);
  assert.deepEqual(teams.configuredMcp, ['teams-mcp']);
  assert.equal(zoom.reason, 'already set up but not switched on yet');
  assert.equal(teams.reason, 'already set up but not switched on yet');
});
