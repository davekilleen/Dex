#!/usr/bin/env node

/**
 * Node.js wrapper for calling work_server.py functions.
 * Same execSync pattern used by calendar_office365.py integration.
 */

const { execFileSync } = require('child_process');
const path = require('path');

const VAULT_ROOT = path.resolve(__dirname, '../..');
const BRIDGE_SCRIPT = path.join(__dirname, 'work-bridge.py');

/**
 * Call a work_server.py function and return parsed JSON.
 * @param {string} funcName - Function name (e.g., 'get_week_progress')
 * @param {object} args - Arguments to pass as JSON
 * @returns {object} Parsed JSON result
 */
function callWorkServer(funcName, args = {}) {
  try {
    const cmdArgs = [BRIDGE_SCRIPT, funcName];
    if (Object.keys(args).length > 0) {
      cmdArgs.push(JSON.stringify(args));
    }

    const result = execFileSync('python3', cmdArgs, {
      cwd: VAULT_ROOT,
      env: { ...process.env, VAULT_PATH: VAULT_ROOT },
      timeout: 15000,
      encoding: 'utf8',
      maxBuffer: 1024 * 1024, // 1MB
      stdio: ['pipe', 'pipe', 'pipe'] // suppress stderr INFO logs
    });

    return JSON.parse(result);
  } catch (e) {
    const stderr = e.stderr ? e.stderr.toString().slice(0, 200) : '';
    console.error(`[work-bridge] ${funcName} failed: ${e.message} ${stderr}`);
    return { error: e.message };
  }
}

module.exports = { callWorkServer };
