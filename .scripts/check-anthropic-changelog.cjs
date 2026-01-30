#!/usr/bin/env node

/**
 * Check Anthropic Changelog - Background self-learning automation
 * 
 * Monitors Anthropic's changelog for new Claude Code features and capabilities.
 * Writes alert file when updates detected, prompting user to run /dex-whats-new.
 * 
 * Designed to run automatically via macOS Launch Agent every 6 hours.
 * No Cursor or Claude required - fully autonomous change detection.
 * 
 * Usage:
 *   node .scripts/check-anthropic-changelog.cjs           # Check for updates
 *   node .scripts/check-anthropic-changelog.cjs --force   # Force check even if recently checked
 *   node .scripts/check-anthropic-changelog.cjs --dry-run # Show what would be detected
 */

const fs = require('fs');
const path = require('path');
const https = require('https');

// ============================================================================
// CONFIGURATION
// ============================================================================

const VAULT_ROOT = path.resolve(__dirname, '..');
const STATE_FILE = path.join(VAULT_ROOT, 'System', 'claude-code-state.json');
const PENDING_FILE = path.join(VAULT_ROOT, 'System', 'changelog-updates-pending.md');
const LOG_DIR = path.join(VAULT_ROOT, '.scripts', 'logs');
const LOG_FILE = path.join(LOG_DIR, 'changelog-checker.log');

// Check at most once every 24 hours (unless --force)
const MIN_CHECK_INTERVAL_HOURS = 24;

// Anthropic changelog sources (try in order)
const CHANGELOG_SOURCES = [
  'https://docs.anthropic.com/en/release-notes/changelog',
  'https://www.anthropic.com/changelog'
];

// ============================================================================
// LOGGING
// ============================================================================

function log(message, level = 'INFO') {
  const timestamp = new Date().toISOString();
  const logMessage = `[${timestamp}] [${level}] ${message}`;
  console.log(logMessage);
  
  // Write to log file
  if (!fs.existsSync(LOG_DIR)) {
    fs.mkdirSync(LOG_DIR, { recursive: true });
  }
  fs.appendFileSync(LOG_FILE, logMessage + '\n');
}

// ============================================================================
// STATE MANAGEMENT
// ============================================================================

function loadState() {
  const defaults = {
    last_check: null,
    last_version_seen: null,
    features_seen: []
  };
  
  if (!fs.existsSync(STATE_FILE)) {
    log('State file not found, creating new one');
    saveState(defaults);
    return defaults;
  }
  
  try {
    const state = JSON.parse(fs.readFileSync(STATE_FILE, 'utf-8'));
    return { ...defaults, ...state };
  } catch (e) {
    log(`Error reading state file: ${e.message}`, 'ERROR');
    return defaults;
  }
}

function saveState(state) {
  try {
    fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
    log('State file updated');
  } catch (e) {
    log(`Error writing state file: ${e.message}`, 'ERROR');
  }
}

// ============================================================================
// CHANGE DETECTION
// ============================================================================

function shouldCheck(state, force) {
  if (force) {
    log('Force flag set, checking regardless of last check time');
    return true;
  }
  
  if (!state.last_check) {
    log('No previous check found, running first check');
    return true;
  }
  
  const lastCheck = new Date(state.last_check);
  const now = new Date();
  const hoursSinceLastCheck = (now - lastCheck) / (1000 * 60 * 60);
  
  if (hoursSinceLastCheck < MIN_CHECK_INTERVAL_HOURS) {
    log(`Last check was ${hoursSinceLastCheck.toFixed(1)} hours ago, skipping (minimum interval: ${MIN_CHECK_INTERVAL_HOURS}h)`);
    return false;
  }
  
  log(`Last check was ${hoursSinceLastCheck.toFixed(1)} hours ago, running check`);
  return true;
}

function fetchChangelog(url) {
  return new Promise((resolve, reject) => {
    https.get(url, (res) => {
      if (res.statusCode !== 200) {
        reject(new Error(`HTTP ${res.statusCode}`));
        return;
      }
      
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve(data));
    }).on('error', reject);
  });
}

async function detectChanges(state) {
  log('Fetching Anthropic changelog...');
  
  let changelogContent = null;
  let successUrl = null;
  
  // Try each source URL
  for (const url of CHANGELOG_SOURCES) {
    try {
      log(`Trying ${url}...`);
      changelogContent = await fetchChangelog(url);
      successUrl = url;
      log(`Successfully fetched from ${url}`);
      break;
    } catch (e) {
      log(`Failed to fetch from ${url}: ${e.message}`, 'WARN');
    }
  }
  
  if (!changelogContent) {
    log('Could not fetch changelog from any source', 'ERROR');
    return null;
  }
  
  // Simple heuristic: look for version numbers or date patterns
  // This is intentionally simple - full analysis happens in /dex-whats-new
  const versionMatches = changelogContent.match(/version\s+(\d+\.\d+\.\d+)/gi) || [];
  const dateMatches = changelogContent.match(/202[0-9]-[0-1][0-9]-[0-3][0-9]/g) || [];
  
  // Extract latest version if found
  let latestVersion = null;
  if (versionMatches.length > 0) {
    const versions = versionMatches.map(v => v.match(/(\d+\.\d+\.\d+)/)[1]);
    latestVersion = versions.sort((a, b) => {
      const aParts = a.split('.').map(Number);
      const bParts = b.split('.').map(Number);
      for (let i = 0; i < 3; i++) {
        if (aParts[i] !== bParts[i]) return bParts[i] - aParts[i];
      }
      return 0;
    })[0];
  }
  
  // Extract latest date if found
  let latestDate = null;
  if (dateMatches.length > 0) {
    latestDate = dateMatches.sort().reverse()[0];
  }
  
  // Determine if there are changes
  const hasChanges = 
    (latestVersion && latestVersion !== state.last_version_seen) ||
    (latestDate && (!state.last_check || latestDate > state.last_check));
  
  return {
    hasChanges,
    latestVersion,
    latestDate,
    source: successUrl
  };
}

// ============================================================================
// ALERT MANAGEMENT
// ============================================================================

function createPendingAlert(changes) {
  const content = `# 🆕 Claude Code Updates Detected

**Detected:** ${new Date().toISOString()}
**Source:** ${changes.source}

${changes.latestVersion ? `**Latest version:** ${changes.latestVersion}\n` : ''}${changes.latestDate ? `**Latest update:** ${changes.latestDate}\n` : ''}

---

## What to Do

Run \`/dex-whats-new\` to:
- See what's new since your last check
- Get specific suggestions for how to use new features in Dex
- Update your tracking state

This file will be deleted once you run the command.

---

*Auto-generated by .scripts/check-anthropic-changelog.cjs*
`;

  fs.writeFileSync(PENDING_FILE, content);
  log(`Created pending alert file: ${PENDING_FILE}`);
}

function removePendingAlert() {
  if (fs.existsSync(PENDING_FILE)) {
    fs.unlinkSync(PENDING_FILE);
    log('Removed pending alert file');
  }
}

// ============================================================================
// MAIN
// ============================================================================

async function main() {
  const args = process.argv.slice(2);
  const force = args.includes('--force');
  const dryRun = args.includes('--dry-run');
  
  // Fast path: check last check timestamp without loading full state
  if (!force && fs.existsSync(STATE_FILE)) {
    try {
      const state = JSON.parse(fs.readFileSync(STATE_FILE, 'utf-8'));
      if (state.last_check) {
        const lastCheck = new Date(state.last_check);
        const hoursSince = (new Date() - lastCheck) / (1000 * 60 * 60);
        if (hoursSince < MIN_CHECK_INTERVAL_HOURS) {
          // Exit silently - this is the common case during session start
          process.exit(0);
        }
      }
    } catch (e) {
      // Fall through to normal logging if state file is corrupted
    }
  }
  
  log('=== Anthropic Changelog Check Started ===');
  
  if (dryRun) {
    log('DRY RUN MODE - No files will be modified');
  }
  
  // Load current state
  const state = loadState();
  log(`Current state: last_check=${state.last_check}, last_version=${state.last_version_seen}`);
  
  // Check if we should run
  if (!shouldCheck(state, force)) {
    log('=== Check skipped (too soon) ===');
    return;
  }
  
  // Detect changes
  const changes = await detectChanges(state);
  
  if (!changes) {
    log('=== Check failed (could not fetch changelog) ===', 'ERROR');
    return;
  }
  
  log(`Changes detected: ${changes.hasChanges}`);
  log(`Latest version: ${changes.latestVersion || 'none found'}`);
  log(`Latest date: ${changes.latestDate || 'none found'}`);
  
  if (dryRun) {
    log('DRY RUN - Would have updated state and created alert if changes detected');
    log('=== Dry Run Complete ===');
    return;
  }
  
  // Update state
  const newState = {
    ...state,
    last_check: new Date().toISOString().split('T')[0], // YYYY-MM-DD
    last_version_seen: changes.latestVersion || state.last_version_seen,
    features_seen: state.features_seen // Preserved, updated by /dex-whats-new
  };
  
  saveState(newState);
  
  // Create alert if changes detected
  if (changes.hasChanges) {
    log('NEW CHANGES DETECTED - Creating alert file');
    createPendingAlert(changes);
  } else {
    log('No new changes detected');
    // Remove any existing alert (user may have already reviewed)
    removePendingAlert();
  }
  
  log('=== Check Complete ===');
}

// Run
main().catch(err => {
  log(`Fatal error: ${err.message}`, 'ERROR');
  console.error(err);
  process.exit(1);
});
