'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const yaml = require('js-yaml');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const { provision } = require(path.join(REPO_ROOT, 'core', 'provision.cjs'));

function makeVault({ existingProfile } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'dex-provision-working-week-'));
  for (const directory of ['System', 'core', '.scripts']) {
    fs.mkdirSync(path.join(root, directory), { recursive: true });
  }
  for (const relative of [
    'System/.mcp.json.example',
    'System/user-profile-template.yaml',
    'core/paths.py',
    'package.json',
    'CLAUDE.md',
  ]) {
    fs.copyFileSync(path.join(REPO_ROOT, relative), path.join(root, relative));
  }
  if (existingProfile !== undefined) {
    fs.writeFileSync(
      path.join(root, 'System', 'user-profile.yaml'),
      existingProfile,
      'utf8',
    );
  }
  return root;
}

function writeOverlay(root, workingWeek) {
  const overlay = path.join(root, 'profile.json');
  fs.writeFileSync(
    overlay,
    `${JSON.stringify({ name: 'Test User', working_week: workingWeek })}\n`,
    'utf8',
  );
  return overlay;
}

test('fresh provision writes the confirmed working week', () => {
  const root = makeVault();
  const overlay = writeOverlay(root, {
    days: ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday'],
  });

  const summary = provision({ path: root, profile: overlay });

  assert.equal(summary.ok, true, summary.errors.join('\n'));
  const profile = yaml.load(
    fs.readFileSync(path.join(root, 'System', 'user-profile.yaml'), 'utf8'),
  );
  assert.deepEqual(profile.working_week, {
    days: ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday'],
  });
});

test('working week overlay must contain at least one day', () => {
  const root = makeVault();
  const overlay = writeOverlay(root, { days: [] });

  const summary = provision({ path: root, profile: overlay });

  assert.equal(summary.ok, false);
  assert.match(summary.errors.join('\n'), /working_week.*non-empty array/i);
});

test('working week overlay must be an object', () => {
  const root = makeVault();
  const overlay = writeOverlay(root, ['monday']);

  const summary = provision({ path: root, profile: overlay });

  assert.equal(summary.ok, false);
  assert.match(summary.errors.join('\n'), /working_week.*object/i);
});

test('adopting an existing vault does not invent a working week', () => {
  const root = makeVault({ existingProfile: 'name: Existing User\ncustom: keep\n' });

  const summary = provision({ path: root, adopt: true });

  assert.equal(summary.ok, true, summary.errors.join('\n'));
  const profile = yaml.load(
    fs.readFileSync(path.join(root, 'System', 'user-profile.yaml'), 'utf8'),
  );
  assert.equal(profile.name, 'Existing User');
  assert.equal(profile.custom, 'keep');
  assert.equal(Object.hasOwn(profile, 'working_week'), false);
});
