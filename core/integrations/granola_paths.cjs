'use strict';

/**
 * Locate the Granola desktop app and its user-data directory.
 *
 * Dex meeting sync uses Granola's official public API. This module does not
 * read Granola's local data files. It only answers "is Granola on this
 * machine, and where?" so installers and the integration concierge can detect
 * the app on Windows as well as macOS.
 *
 * Installer entry point:
 *   node core/integrations/granola_paths.cjs --json
 */

const fs = require('fs');
const path = require('path');

const OVERRIDE_APP_ENV = 'DEX_GRANOLA_APP';
const OVERRIDE_DATA_ENV = 'DEX_GRANOLA_DATA';
const DEBUG_ENV = 'DEX_GRANOLA_PATHS_DEBUG';

const WINDOWS_APP_RELATIVES = [
  ['Programs', '@granolaelectron', 'Granola.exe'],
  ['Programs', 'Granola', 'Granola.exe'],
];
const WINDOWS_MACHINE_APP_RELATIVES = [
  ['@granolaelectron', 'Granola.exe'],
  ['Granola', 'Granola.exe'],
];

function debugLog(...args) {
  if (String(process.env[DEBUG_ENV] || '').trim()) {
    console.error('dex.granola_paths:', ...args);
  }
}

function classifyPlatform(raw) {
  const value = String(raw || process.platform || '').trim().toLowerCase();
  if (
    value === 'win32' ||
    value === 'windows' ||
    value === 'cygwin' ||
    value === 'msys' ||
    value === 'mingw' ||
    value.startsWith('cygwin') ||
    value.startsWith('msys') ||
    value.startsWith('mingw')
  ) {
    return 'win32';
  }
  if (value === 'darwin' || value === 'macos' || value === 'mac') {
    return 'darwin';
  }
  return 'linux';
}

function sanitizeEnvValue(name, value) {
  if (value === undefined || value === null) {
    return { value: null, reason: `missing env ${name}` };
  }
  let cleaned = String(value).trim();
  if (!cleaned) {
    return { value: null, reason: `empty env ${name}` };
  }
  for (let i = 0; i < cleaned.length; i += 1) {
    const code = cleaned.charCodeAt(i);
    if (code < 32 || code === 127) {
      return { value: null, reason: `rejected env ${name}: control characters` };
    }
  }
  if (
    cleaned.length >= 2 &&
    cleaned[0] === cleaned[cleaned.length - 1] &&
    (cleaned[0] === "'" || cleaned[0] === '"')
  ) {
    cleaned = cleaned.slice(1, -1).trim();
    if (!cleaned) {
      return { value: null, reason: `empty env ${name}` };
    }
  }
  if (cleaned === '.' || cleaned === '..') {
    return { value: null, reason: `rejected env ${name}: relative path` };
  }
  return { value: cleaned, reason: null };
}

function looksPosixAbsolute(value) {
  return value.startsWith('/') && !value.startsWith('//');
}

function joinOsPath(base, ...parts) {
  if (looksPosixAbsolute(base)) {
    return parts.length ? path.posix.join(base, ...parts) : base;
  }
  return winJoin(base, ...parts);
}

function winJoin(base, ...parts) {
  const raw = [base, ...parts].map(String);
  let prefix = '';
  let rest = raw[0] || '';
  if (rest.startsWith('\\\\') || rest.startsWith('//')) {
    prefix = '\\\\';
    rest = rest.replace(/^[\\/]+/, '');
  } else if (/^[A-Za-z]:/.test(rest)) {
    prefix = `${rest.slice(0, 2)}\\`;
    rest = rest.slice(2).replace(/^[\\/]+/, '');
  }
  const segs = [];
  const push = (chunk) => {
    for (const seg of String(chunk).replace(/\//g, '\\').split('\\')) {
      if (!seg || seg === '.') continue;
      if (seg === '..') {
        if (segs.length) segs.pop();
        continue;
      }
      segs.push(seg);
    }
  };
  push(rest);
  for (const part of raw.slice(1)) push(part);
  if (prefix === '\\\\') return `\\\\${segs.join('\\')}`;
  return `${prefix}${segs.join('\\')}`;
}

function windowsToGitBash(winPath) {
  if (!winPath) return null;
  const normalized = String(winPath).replace(/\//g, '\\');
  if (normalized.startsWith('\\\\')) {
    return `//${normalized.slice(2).replace(/\\/g, '/')}`;
  }
  if (normalized.length >= 2 && normalized[1] === ':' && /[A-Za-z]/.test(normalized[0])) {
    const drive = normalized[0].toLowerCase();
    const rest = normalized.slice(2).replace(/\\/g, '/').replace(/^\/+/, '');
    return rest ? `/${drive}/${rest}` : `/${drive}`;
  }
  return null;
}

function windowsPosixAliases(winPath) {
  const gitBash = windowsToGitBash(winPath);
  if (!gitBash) return [];
  const aliases = [gitBash];
  if (
    gitBash.startsWith('/') &&
    gitBash.length >= 2 &&
    /[a-z]/i.test(gitBash[1]) &&
    (gitBash.length === 2 || gitBash[2] === '/')
  ) {
    aliases.push(`/cygdrive${gitBash}`);
  }
  return [...new Set(aliases)];
}

function defaultKind(candidatePath) {
  const seen = new Set();
  for (const candidate of [candidatePath, ...windowsPosixAliases(candidatePath)]) {
    if (seen.has(candidate)) continue;
    seen.add(candidate);
    try {
      const stat = fs.statSync(candidate);
      if (stat.isDirectory()) return 'dir';
      if (stat.isFile()) return 'file';
    } catch (error) {
      if (error && error.code !== 'ENOENT' && error.code !== 'ENOTDIR') {
        debugLog(`probe failed for ${candidate}: ${error.message}`);
      }
    }
  }
  return null;
}

function firstEnv(env, names) {
  let lastReason = null;
  let lastName = names[0] || '';
  for (const name of names) {
    const { value, reason } = sanitizeEnvValue(name, env[name]);
    if (value) return { value, name, reason: null };
    lastReason = reason;
    lastName = name;
  }
  return { value: null, name: lastName, reason: lastReason };
}

function userProfileHome(env) {
  const profile = firstEnv(env, ['USERPROFILE', 'HOME']);
  if (profile.value) return profile;
  const drive = firstEnv(env, ['HOMEDRIVE']);
  const homePath = firstEnv(env, ['HOMEPATH']);
  if (drive.value && homePath.value) {
    return {
      value: joinOsPath(drive.value, homePath.value.replace(/^[\\/]+/, '')),
      name: 'HOMEDRIVE+HOMEPATH',
      reason: null,
    };
  }
  return { value: null, name: 'USERPROFILE', reason: profile.reason || drive.reason || homePath.reason };
}

function dedupe(candidates) {
  const seen = new Set();
  const out = [];
  for (const item of candidates) {
    const key = item.path.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(item);
  }
  return out;
}

function windowsAppCandidates(env) {
  const candidates = [];
  const override = sanitizeEnvValue(OVERRIDE_APP_ENV, env[OVERRIDE_APP_ENV]);
  if (override.value) {
    candidates.push({ path: joinOsPath(override.value), source: `env ${OVERRIDE_APP_ENV}`, kind: 'app' });
  } else if (env[OVERRIDE_APP_ENV] !== undefined) {
    debugLog(`skip app override: ${override.reason}`);
  }

  let local = firstEnv(env, ['LOCALAPPDATA']);
  if (!local.value) {
    const home = userProfileHome(env);
    if (home.value) {
      local = { value: joinOsPath(home.value, 'AppData', 'Local'), name: `${home.name}\\AppData\\Local`, reason: null };
    } else {
      debugLog(`no LOCALAPPDATA: ${local.reason || home.reason}`);
    }
  }
  if (local.value) {
    for (const relative of WINDOWS_APP_RELATIVES) {
      candidates.push({
        path: joinOsPath(local.value, ...relative),
        source: `${local.name}\\${relative.join('\\')}`,
        kind: 'app',
      });
    }
  }

  for (const envName of ['PROGRAMFILES', 'PROGRAMFILES(X86)']) {
    const root = firstEnv(env, [envName]);
    if (!root.value) {
      debugLog(`skip ${envName}: ${root.reason}`);
      continue;
    }
    for (const relative of WINDOWS_MACHINE_APP_RELATIVES) {
      candidates.push({
        path: joinOsPath(root.value, ...relative),
        source: `${root.name}\\${relative.join('\\')}`,
        kind: 'app',
      });
    }
  }
  return dedupe(candidates);
}

function windowsDataCandidates(env) {
  const candidates = [];
  const override = sanitizeEnvValue(OVERRIDE_DATA_ENV, env[OVERRIDE_DATA_ENV]);
  if (override.value) {
    candidates.push({ path: joinOsPath(override.value), source: `env ${OVERRIDE_DATA_ENV}`, kind: 'data' });
  } else if (env[OVERRIDE_DATA_ENV] !== undefined) {
    debugLog(`skip data override: ${override.reason}`);
  }

  const roaming = firstEnv(env, ['APPDATA']);
  if (roaming.value) {
    candidates.push({
      path: joinOsPath(roaming.value, 'Granola'),
      source: `${roaming.name}\\Granola`,
      kind: 'data',
    });
  } else {
    debugLog(`no APPDATA: ${roaming.reason}`);
  }

  const home = userProfileHome(env);
  if (home.value) {
    candidates.push({
      path: joinOsPath(home.value, 'AppData', 'Roaming', 'Granola'),
      source: `${home.name}\\AppData\\Roaming\\Granola`,
      kind: 'data',
    });
    candidates.push({
      path: joinOsPath(home.value, 'AppData', 'Local', 'Granola'),
      source: `${home.name}\\AppData\\Local\\Granola`,
      kind: 'data',
    });
  } else {
    debugLog(`no user home for data fallbacks: ${home.reason}`);
  }

  const local = firstEnv(env, ['LOCALAPPDATA']);
  if (local.value) {
    candidates.push({
      path: joinOsPath(local.value, 'Granola'),
      source: `${local.name}\\Granola`,
      kind: 'data',
    });
  } else {
    debugLog(`no LOCALAPPDATA for data fallback: ${local.reason}`);
  }
  return dedupe(candidates);
}

function darwinAppCandidates(env, home) {
  const candidates = [];
  const override = sanitizeEnvValue(OVERRIDE_APP_ENV, env[OVERRIDE_APP_ENV]);
  if (override.value) {
    candidates.push({ path: override.value, source: `env ${OVERRIDE_APP_ENV}`, kind: 'app' });
  } else if (env[OVERRIDE_APP_ENV] !== undefined) {
    debugLog(`skip app override: ${override.reason}`);
  }
  candidates.push({ path: '/Applications/Granola.app', source: '/Applications/Granola.app', kind: 'app' });
  if (home) {
    candidates.push({
      path: path.posix.join(home, 'Applications', 'Granola.app'),
      source: '~/Applications/Granola.app',
      kind: 'app',
    });
  }
  return dedupe(candidates);
}

function darwinDataCandidates(env, home) {
  const candidates = [];
  const override = sanitizeEnvValue(OVERRIDE_DATA_ENV, env[OVERRIDE_DATA_ENV]);
  if (override.value) {
    candidates.push({ path: override.value, source: `env ${OVERRIDE_DATA_ENV}`, kind: 'data' });
  } else if (env[OVERRIDE_DATA_ENV] !== undefined) {
    debugLog(`skip data override: ${override.reason}`);
  }
  if (home) {
    candidates.push({
      path: path.posix.join(home, 'Library', 'Application Support', 'Granola'),
      source: '~/Library/Application Support/Granola',
      kind: 'data',
    });
  } else {
    debugLog('no HOME for macOS Granola data directory');
  }
  return dedupe(candidates);
}

function probe(candidate, kindOf, expect) {
  const found = kindOf(candidate.path);
  let reason = 'found';
  let ok = true;
  if (found == null) {
    ok = false;
    reason = 'missing';
  } else if (found !== expect) {
    ok = false;
    reason = `not a ${expect}`;
  }
  debugLog(`tried ${candidate.kind} ${candidate.path} (${candidate.source}): ${reason}`);
  return {
    kind: candidate.kind,
    path: candidate.path,
    source: candidate.source,
    ok,
    reason,
  };
}

function detectGranola({
  platform,
  env = process.env,
  kind,
  home,
} = {}) {
  const family = classifyPlatform(platform);
  const kindOf = kind || defaultKind;
  let resolvedHome = home;
  if (resolvedHome == null) {
    resolvedHome = sanitizeEnvValue('HOME', env.HOME).value;
  }

  if (family === 'linux') {
    debugLog('linux: Granola desktop detection is a no-op');
    return {
      platform: 'linux',
      installed: false,
      app_found: false,
      data_found: false,
      app_path: null,
      data_path: null,
      app_path_posix: null,
      data_path_posix: null,
      tried: [],
    };
  }

  const appExpect = family === 'win32' ? 'file' : 'dir';
  const dataExpect = 'dir';
  const appCandidates = family === 'win32'
    ? windowsAppCandidates(env)
    : darwinAppCandidates(env, resolvedHome);
  const dataCandidates = family === 'win32'
    ? windowsDataCandidates(env)
    : darwinDataCandidates(env, resolvedHome);

  const tried = [];
  let appPath = null;
  let dataPath = null;

  for (const candidate of appCandidates) {
    const result = probe(candidate, kindOf, appExpect);
    tried.push(result);
    if (result.ok && appPath == null) appPath = result.path;
  }
  for (const candidate of dataCandidates) {
    const result = probe(candidate, kindOf, dataExpect);
    tried.push(result);
    if (result.ok && dataPath == null) dataPath = result.path;
  }

  const appFound = appPath != null;
  const dataFound = dataPath != null;
  const installed = appFound || (family === 'win32' && dataFound);

  debugLog(`granola detect platform=${family} installed=${installed} app=${appPath} data=${dataPath}`);
  return {
    platform: family,
    installed,
    app_found: appFound,
    data_found: dataFound,
    app_path: appPath,
    data_path: dataPath,
    app_path_posix: family === 'win32' && appPath ? windowsToGitBash(appPath) : null,
    data_path_posix: family === 'win32' && dataPath ? windowsToGitBash(dataPath) : null,
    tried,
  };
}

function installedAppReason(platform = process.platform) {
  return classifyPlatform(platform) === 'win32'
    ? 'installed on your Windows PC'
    : 'installed on your Mac';
}

function main(argv = process.argv.slice(2)) {
  const platformFlag = argv.includes('--platform')
    ? argv[argv.indexOf('--platform') + 1]
    : undefined;
  const locations = detectGranola({ platform: platformFlag });
  process.stdout.write(`${JSON.stringify(locations, null, 2)}\n`);
  return locations.installed ? 0 : 1;
}

if (require.main === module) {
  process.exit(main());
}

module.exports = {
  OVERRIDE_APP_ENV,
  OVERRIDE_DATA_ENV,
  classifyPlatform,
  sanitizeEnvValue,
  winJoin,
  windowsToGitBash,
  detectGranola,
  installedAppReason,
  main,
};
