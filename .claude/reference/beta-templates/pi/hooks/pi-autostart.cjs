#!/usr/bin/env node
/**
 * SessionStart hook: Auto-start Pi when beta activated
 *
 * Automatically launches Pi in the background when a Claude Code session starts,
 * if the user has the Pi beta activated in their profile.
 *
 * Checks:
 * 1. Pi beta activated in System/user-profile.yaml (beta.activated.pi: true)
 * 2. Not disabled via PI_AUTOSTART=false env var
 * 3. Not disabled via pi_autostart: false in user-profile.yaml
 * 4. Pi not already running
 * 5. Pi command exists on system
 */
const fs = require('fs');
const path = require('path');
const { execSync, spawn } = require('child_process');

// Get vault root from environment
const VAULT_ROOT = process.env.CLAUDE_PROJECT_DIR || process.env.VAULT_PATH || process.cwd();
const USER_PROFILE = path.join(VAULT_ROOT, 'System', 'user-profile.yaml');
const LOG_FILE = path.join(VAULT_ROOT, 'System', '.pi-autostart.log');

/**
 * Simple YAML parser for our specific needs
 * Handles nested keys like beta.activated.pi
 */
function parseYamlValue(content, keyPath) {
  const keys = keyPath.split('.');
  const lines = content.split('\n');

  let currentIndent = 0;
  let foundPath = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // Skip empty lines and comments
    if (!trimmed || trimmed.startsWith('#')) continue;

    // Calculate indent level (2 spaces per level)
    const indent = line.search(/\S/);
    const level = Math.floor(indent / 2);

    // If indent decreased, pop from found path
    while (foundPath.length > level) {
      foundPath.pop();
    }

    // Parse key: value
    const match = trimmed.match(/^([^:]+):\s*(.*)$/);
    if (!match) continue;

    const key = match[1].trim();
    const value = match[2].trim();

    // Update found path
    foundPath[level] = key;

    // Check if this matches our target path
    const currentPath = foundPath.slice(0, level + 1).join('.');

    if (currentPath === keyPath) {
      // Found it! Parse the value
      if (value === 'true') return true;
      if (value === 'false') return false;
      if (value === '') return null;
      // Remove quotes if present
      return value.replace(/^["']|["']$/g, '');
    }
  }

  return undefined;
}

/**
 * Log message to file (for debugging)
 */
function log(message) {
  const timestamp = new Date().toISOString();
  const logLine = `[${timestamp}] ${message}\n`;
  try {
    fs.appendFileSync(LOG_FILE, logLine);
  } catch (e) {
    // Silently fail logging
  }
}

/**
 * Check if a process is running
 */
function isProcessRunning(processName) {
  try {
    // Use pgrep to check for running process
    const result = execSync(`pgrep -x "${processName}" 2>/dev/null`, {
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe']
    });
    return result.trim().length > 0;
  } catch (e) {
    // pgrep returns exit code 1 if no processes found
    return false;
  }
}

/**
 * Check if command exists
 */
function commandExists(command) {
  try {
    execSync(`which "${command}" 2>/dev/null`, {
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe']
    });
    return true;
  } catch (e) {
    return false;
  }
}

/**
 * Main hook logic
 */
function main() {
  // Check 1: Environment variable override
  if (process.env.PI_AUTOSTART === 'false') {
    log('Disabled via PI_AUTOSTART=false environment variable');
    return;
  }

  // Check 2: Read user profile
  if (!fs.existsSync(USER_PROFILE)) {
    log('User profile not found, skipping Pi autostart');
    return;
  }

  let profileContent;
  try {
    profileContent = fs.readFileSync(USER_PROFILE, 'utf-8');
  } catch (e) {
    log(`Failed to read user profile: ${e.message}`);
    return;
  }

  // Check 3: Disabled in user profile
  const piAutostartDisabled = parseYamlValue(profileContent, 'pi_autostart');
  if (piAutostartDisabled === false) {
    log('Disabled via pi_autostart: false in user-profile.yaml');
    return;
  }

  // Check 4: Pi beta not activated
  const piBetaActivated = parseYamlValue(profileContent, 'beta.activated.pi');
  if (piBetaActivated !== true) {
    log('Pi beta not activated (beta.activated.pi is not true)');
    return;
  }

  // Check 5: Pi already running
  if (isProcessRunning('pi')) {
    log('Pi is already running');
    return;
  }

  // Check 6: Pi command exists
  if (!commandExists('pi')) {
    log('Pi command not found. Install with: npm install -g @anthropic-ai/claude-code-pi');
    // Output a warning that will be shown to user
    console.log(JSON.stringify({
      continue: true,
      hookSpecificOutput: {
        hookEventName: "SessionStart",
        additionalContext: "\n--- Pi Beta ---\nPi autostart enabled but 'pi' command not found.\nInstall: npm install -g @anthropic-ai/claude-code-pi\n---\n"
      }
    }));
    return;
  }

  // All checks passed - start Pi in background
  try {
    // Spawn Pi detached from this process
    const piProcess = spawn('pi', [], {
      detached: true,
      stdio: 'ignore',
      cwd: VAULT_ROOT
    });

    // Unref to allow this script to exit
    piProcess.unref();

    log(`Started Pi (PID: ${piProcess.pid})`);

    // Output success message
    console.log(JSON.stringify({
      continue: true,
      hookSpecificOutput: {
        hookEventName: "SessionStart",
        additionalContext: "\n--- Pi ---\nPi started automatically in background.\n---\n"
      }
    }));

  } catch (e) {
    log(`Failed to start Pi: ${e.message}`);
    console.log(JSON.stringify({
      continue: true,
      hookSpecificOutput: {
        hookEventName: "SessionStart",
        additionalContext: `\n--- Pi ---\nFailed to auto-start Pi: ${e.message}\n---\n`
      }
    }));
  }
}

// Run the hook
main();
