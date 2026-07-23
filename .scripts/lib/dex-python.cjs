'use strict';

const fs = require('node:fs');
const path = require('node:path');
const childProcess = require('node:child_process');

const capabilityCache = new Map();
const CAPABILITY_CODE = 'import yaml,sys; assert sys.version_info >= (3,10)';

function isExecutableFile(candidate) {
  if (!candidate || !path.isAbsolute(candidate)) return false;
  try {
    fs.accessSync(candidate, fs.constants.X_OK);
    return fs.statSync(candidate).isFile();
  } catch (_) {
    return false;
  }
}

function capability(candidate, spawnSync = childProcess.spawnSync) {
  if (capabilityCache.has(candidate)) return capabilityCache.get(candidate);
  let result;
  try {
    const probe = spawnSync(candidate, ['-c', CAPABILITY_CODE], {
      encoding: 'utf8',
      timeout: 5000,
      maxBuffer: 1024 * 1024,
    });
    result = probe.status === 0 && !probe.error
      ? { ok: true, detail: null }
      : {
        ok: false,
        detail: probe.error?.message
          || String(probe.stderr || '').trim()
          || `capability probe exited ${probe.status}`,
      };
  } catch (error) {
    result = { ok: false, detail: error.message };
  }
  capabilityCache.set(candidate, result);
  return result;
}

function ready(pathname) {
  return {
    path: pathname,
    feature: 'Entity engine Python',
    feature_status: 'ok',
    success: true,
    user_message: 'The entity engine Python interpreter is ready.',
  };
}

function broken(candidate, detail) {
  return {
    path: null,
    feature: 'Entity engine Python',
    feature_status: 'broken',
    success: false,
    user_message: `DEX_PYTHON must use Python 3.10 or newer with PyYAML installed. `
      + `Fix ${candidate}, then run /dex-doctor.`,
    detail,
  };
}

function resolveDexPythonStatus(
  vaultRoot,
  env = process.env,
  spawnSync = childProcess.spawnSync,
) {
  const configured = typeof env.DEX_PYTHON === 'string'
    ? env.DEX_PYTHON.trim()
    : '';
  if (isExecutableFile(configured)) {
    const probe = capability(configured, spawnSync);
    return probe.ok ? ready(configured) : broken(configured, probe.detail);
  }

  const virtualenv = path.join(path.resolve(vaultRoot), '.venv', 'bin', 'python');
  if (isExecutableFile(virtualenv)) {
    const probe = capability(virtualenv, spawnSync);
    return probe.ok ? ready(virtualenv) : broken(virtualenv, probe.detail);
  }
  return {
    path: null,
    feature: 'Entity engine Python',
    feature_status: 'not_installed',
    success: false,
    user_message: 'Entity writes are paused because no safe Dex Python is available. '
      + 'Restore the vault .venv or set DEX_PYTHON to Python 3.10+ with PyYAML, '
      + 'then run /dex-doctor.',
  };
}

function resolveDexPython(vaultRoot, env = process.env) {
  return resolveDexPythonStatus(vaultRoot, env).path;
}

module.exports = {
  CAPABILITY_CODE,
  resolveDexPython,
  resolveDexPythonStatus,
};
