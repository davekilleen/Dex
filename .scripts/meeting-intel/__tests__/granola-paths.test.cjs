'use strict';

const assert = require('node:assert/strict');
const path = require('path');
const test = require('node:test');

const {
  classifyPlatform,
  detectGranola,
  installedAppReason,
  winJoin,
  windowsToGitBash,
} = require('../lib/granola-paths.cjs');

function windowsEnv(overrides = {}) {
  return {
    APPDATA: 'C:\\Users\\Sam\\AppData\\Roaming',
    LOCALAPPDATA: 'C:\\Users\\Sam\\AppData\\Local',
    USERPROFILE: 'C:\\Users\\Sam',
    PROGRAMFILES: 'C:\\Program Files',
    'PROGRAMFILES(X86)': 'C:\\Program Files (x86)',
    ...overrides,
  };
}

function kindFrom(existing) {
  const folded = new Map(
    Object.entries(existing).map(([candidate, kind]) => [candidate.toLowerCase(), kind]),
  );
  return (candidate) => folded.get(String(candidate).toLowerCase()) || null;
}

test('classifies Git Bash / Cygwin as Windows', () => {
  assert.equal(classifyPlatform('cygwin'), 'win32');
  assert.equal(classifyPlatform('CYGWIN_NT-10.0'), 'win32');
  assert.equal(classifyPlatform('msys'), 'win32');
  assert.equal(classifyPlatform('darwin'), 'darwin');
  assert.equal(classifyPlatform('linux'), 'linux');
});

test('resolves the stable per-user Granola.exe and Roaming data directory', () => {
  const exe = 'C:\\Users\\Sam\\AppData\\Local\\Programs\\@granolaelectron\\Granola.exe';
  const data = 'C:\\Users\\Sam\\AppData\\Roaming\\Granola';
  const result = detectGranola({
    platform: 'win32',
    env: windowsEnv(),
    kind: kindFrom({ [exe]: 'file', [data]: 'dir' }),
  });
  assert.equal(result.installed, true);
  assert.equal(result.app_path, exe);
  assert.equal(result.data_path, data);
  assert.equal(
    result.app_path_posix,
    '/c/Users/Sam/AppData/Local/Programs/@granolaelectron/Granola.exe',
  );
});

test('Linux stays a no-op even with Windows environment variables', () => {
  const result = detectGranola({
    platform: 'linux',
    env: windowsEnv(),
    kind: kindFrom({
      'C:\\Users\\Sam\\AppData\\Roaming\\Granola': 'dir',
    }),
  });
  assert.equal(result.installed, false);
  assert.deepEqual(result.tried, []);
});

test('macOS still requires the application bundle', () => {
  const missingApp = detectGranola({
    platform: 'darwin',
    env: { HOME: '/Users/sam' },
    home: '/Users/sam',
    kind: kindFrom({ '/Users/sam/Library/Application Support/Granola': 'dir' }),
  });
  assert.equal(missingApp.installed, false);
  assert.equal(missingApp.data_found, true);

  const found = detectGranola({
    platform: 'darwin',
    env: { HOME: '/Users/sam' },
    home: '/Users/sam',
    kind: kindFrom({ '/Applications/Granola.app': 'dir' }),
  });
  assert.equal(found.installed, true);
  assert.equal(found.app_path, '/Applications/Granola.app');
});

test('UNC and OneDrive AppData candidates stay intact', () => {
  const unc = detectGranola({
    platform: 'win32',
    env: windowsEnv({ APPDATA: '\\\\fileserver\\users\\sam\\AppData\\Roaming' }),
    kind: kindFrom({
      '\\\\fileserver\\users\\sam\\AppData\\Roaming\\Granola': 'dir',
    }),
  });
  assert.equal(unc.data_path, '\\\\fileserver\\users\\sam\\AppData\\Roaming\\Granola');

  const onedrive = detectGranola({
    platform: 'win32',
    env: windowsEnv({ APPDATA: 'C:\\Users\\Sam\\OneDrive\\AppData\\Roaming' }),
    kind: () => null,
  });
  assert.equal(
    onedrive.tried.find((probe) => probe.kind === 'data').path,
    'C:\\Users\\Sam\\OneDrive\\AppData\\Roaming\\Granola',
  );
});

test('control characters and missing env vars do not invent a path', () => {
  const rejected = detectGranola({
    platform: 'win32',
    env: windowsEnv({ APPDATA: 'C:\\Users\\Sam\\AppData\\Roaming\nC:\\evil' }),
    kind: kindFrom({ 'C:\\Users\\Sam\\AppData\\Roaming\\Granola': 'dir' }),
  });
  assert.equal(rejected.data_path, 'C:\\Users\\Sam\\AppData\\Roaming\\Granola');
  assert.equal(
    rejected.tried.some((probe) => probe.path.includes('\n')),
    false,
  );
});

test('winJoin keeps UNC roots and collapses ..', () => {
  assert.equal(
    winJoin('\\\\fileserver\\users\\sam', 'AppData', 'Roaming', 'Granola'),
    '\\\\fileserver\\users\\sam\\AppData\\Roaming\\Granola',
  );
  assert.equal(
    winJoin('C:\\Users\\Sam\\AppData\\Roaming\\..\\..\\..\\..\\Windows', 'Granola'),
    'C:\\Windows\\Granola',
  );
  assert.equal(windowsToGitBash('C:\\Users\\Sam\\AppData\\Roaming\\Granola'), '/c/Users/Sam/AppData/Roaming/Granola');
});

test('installed reason is Windows-aware and Mac-safe for tests', () => {
  assert.equal(installedAppReason('win32'), 'installed on your Windows PC');
  assert.equal(installedAppReason('darwin'), 'installed on your Mac');
  assert.equal(installedAppReason('linux'), 'installed on your Mac');
});

test('re-export stays pointed at the shared resolver', () => {
  const shared = require('../../../core/integrations/granola_paths.cjs');
  const local = require('../lib/granola-paths.cjs');
  assert.equal(local.detectGranola, shared.detectGranola);
  assert.equal(path.basename(require.resolve('../lib/granola-paths.cjs')), 'granola-paths.cjs');
});
