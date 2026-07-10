#!/usr/bin/env node
/**
 * SessionStart hook: Auto-start Pi when configured
 *
 * Automatically launches Pi in the background when a Claude Code session starts.
 *
 * Checks:
 * 1. Explicitly enabled via PI_AUTOSTART=true or pi_autostart: true
 * 2. Not disabled via PI_AUTOSTART=false
 * 3. Pi not already running
 * 4. Pi command exists on system
 */
const fs = require('fs');
const path = require('path');
const { execSync, spawn } = require('child_process');

// Get vault root from environment
const VAULT_ROOT = process.env.CLAUDE_PROJECT_DIR || process.env.VAULT_PATH || process.cwd();
const USER_PROFILE = path.join(VAULT_ROOT, 'System', 'user-profile.yaml');
const LOG_FILE = path.join(VAULT_ROOT, 'System', '.pi-autostart.log');

/** Check the one supported profile opt-in without parsing arbitrary YAML. */
function isPiAutostartEnabled(content) {
  return content.split('\n').some((line) => /^pi_autostart:\s*true\s*(?:#.*)?$/.test(line));
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

  // Check 2: Read the profile only when the environment did not opt in
  if (process.env.PI_AUTOSTART !== 'true') {
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

    // Check 3: Explicitly enabled in the profile
    if (!isPiAutostartEnabled(profileContent)) {
      log('Pi autostart is not enabled');
      return;
    }
  }

  // Check 4: Pi already running
  if (isProcessRunning('pi')) {
    log('Pi is already running');
    return;
  }

  // Check 5: Pi command exists
  if (!commandExists('pi')) {
    log('Pi command not found. Install with: npm install -g @anthropic-ai/claude-code-pi');
    // Output a warning that will be shown to user
    console.log(JSON.stringify({
      continue: true,
      hookSpecificOutput: {
        hookEventName: "SessionStart",
        additionalContext: "\n--- Pi ---\nPi autostart enabled but 'pi' command not found.\nInstall: npm install -g @anthropic-ai/claude-code-pi\n---\n"
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
