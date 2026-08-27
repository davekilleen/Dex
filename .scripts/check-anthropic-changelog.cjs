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

'use strict';

const fs = require('fs');
const path = require('path');
const http = require('http');
const https = require('https');

// ============================================================================
// CONFIGURATION
// ============================================================================

function vaultRoot(env = process.env) {
  return env.DEX_VAULT_ROOT
    ? path.resolve(env.DEX_VAULT_ROOT)
    : path.resolve(__dirname, '..');
}

function stateFile(env = process.env) {
  return path.join(vaultRoot(env), 'System', 'claude-code-state.json');
}

function pendingFile(env = process.env) {
  return path.join(vaultRoot(env), 'System', 'changelog-updates-pending.md');
}

function logDir(env = process.env) {
  return path.join(vaultRoot(env), '.scripts', 'logs');
}

function logFile(env = process.env) {
  return path.join(logDir(env), 'changelog-checker.log');
}

// Check at most once every 24 hours (unless --force)
const MIN_CHECK_INTERVAL_HOURS = 24;
const MAX_REDIRECTS = 5;
const DEFAULT_TIMEOUT_MS = 15000;

// Changelog sources (try in order). Keep these product URLs as shipped;
// fetch follows redirects instead of replacing them.
const CHANGELOG_SOURCES = [
  'https://docs.anthropic.com/en/release-notes/changelog',
  'https://www.anthropic.com/changelog'
];

function resolveChangelogSources(env = process.env) {
  if (env.DEX_CHANGELOG_SOURCES === undefined) {
    return CHANGELOG_SOURCES.slice();
  }
  return String(env.DEX_CHANGELOG_SOURCES)
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function requestTimeoutMs(env = process.env) {
  const raw = env.DEX_CHANGELOG_TIMEOUT_MS;
  if (raw) {
    const parsed = Number(raw);
    if (Number.isFinite(parsed) && parsed > 0) {
      return parsed;
    }
  }
  return DEFAULT_TIMEOUT_MS;
}

// ============================================================================
// LOGGING
// ============================================================================

function log(message, level = 'INFO', env = process.env) {
  const timestamp = new Date().toISOString();
  const logMessage = `[${timestamp}] [${level}] ${message}`;
  console.log(logMessage);

  const directory = logDir(env);
  if (!fs.existsSync(directory)) {
    fs.mkdirSync(directory, { recursive: true });
  }
  fs.appendFileSync(logFile(env), logMessage + '\n');
}

// ============================================================================
// STATE MANAGEMENT
// ============================================================================

function loadState(env = process.env) {
  const defaults = {
    last_check: null,
    last_version_seen: null,
    features_seen: []
  };
  const file = stateFile(env);

  if (!fs.existsSync(file)) {
    log('State file not found, creating new one', 'INFO', env);
    saveState(defaults, env);
    return defaults;
  }

  try {
    const state = JSON.parse(fs.readFileSync(file, 'utf-8'));
    return { ...defaults, ...state };
  } catch (e) {
    log(`Error reading state file: ${e.message}`, 'ERROR', env);
    return defaults;
  }
}

function saveState(state, env = process.env) {
  try {
    const file = stateFile(env);
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify(state, null, 2));
    log('State file updated', 'INFO', env);
  } catch (e) {
    log(`Error writing state file: ${e.message}`, 'ERROR', env);
  }
}

// ============================================================================
// CHANGE DETECTION
// ============================================================================

function shouldCheck(state, force, env = process.env) {
  if (force) {
    log('Force flag set, checking regardless of last check time', 'INFO', env);
    return true;
  }

  if (!state.last_check) {
    log('No previous check found, running first check', 'INFO', env);
    return true;
  }

  const lastCheck = new Date(state.last_check);
  const now = new Date();
  const hoursSinceLastCheck = (now - lastCheck) / (1000 * 60 * 60);

  if (hoursSinceLastCheck < MIN_CHECK_INTERVAL_HOURS) {
    log(
      `Last check was ${hoursSinceLastCheck.toFixed(1)} hours ago, skipping (minimum interval: ${MIN_CHECK_INTERVAL_HOURS}h)`,
      'INFO',
      env,
    );
    return false;
  }

  log(`Last check was ${hoursSinceLastCheck.toFixed(1)} hours ago, running check`, 'INFO', env);
  return true;
}

function clientForUrl(urlObject) {
  if (urlObject.protocol === 'https:') return https;
  if (urlObject.protocol === 'http:') return http;
  return null;
}

function drainResponse(res) {
  return new Promise((resolve) => {
    res.on('end', resolve);
    res.on('error', resolve);
    res.resume();
  });
}

function fetchChangelog(url, options = {}) {
  const remaining = options.remaining ?? MAX_REDIRECTS;
  const timeoutMs = options.timeoutMs ?? requestTimeoutMs(options.env || process.env);
  return new Promise((resolve, reject) => {
    let settled = false;
    const finish = (err, value) => {
      if (settled) return;
      settled = true;
      if (err) reject(err);
      else resolve(value);
    };

    let parsed;
    try {
      parsed = new URL(url);
    } catch (e) {
      finish(new Error(`Invalid URL: ${e.message}`));
      return;
    }

    const client = clientForUrl(parsed);
    if (!client) {
      finish(new Error(`Unsupported protocol: ${parsed.protocol}`));
      return;
    }

    let handedOff = false;
    const req = client.get(parsed, { agent: false }, (res) => {
      const status = res.statusCode || 0;
      if (status >= 300 && status < 400 && res.headers.location) {
        const location = res.headers.location;
        drainResponse(res).then(() => {
          if (settled) return;
          handedOff = true;
          req.setTimeout(0);
          if (remaining <= 0) {
            finish(new Error('Too many redirects'));
            return;
          }
          let nextUrl;
          try {
            nextUrl = new URL(location, url).toString();
          } catch (e) {
            finish(new Error(`Invalid redirect: ${e.message}`));
            return;
          }
          return fetchChangelog(nextUrl, { ...options, remaining: remaining - 1 });
        }).then((body) => {
          if (body !== undefined) finish(null, body);
        }).catch((err) => finish(err));
        return;
      }

      if (status !== 200) {
        drainResponse(res).then(() => {
          if (!settled) finish(new Error(`HTTP ${status}`));
        });
        return;
      }

      const chunks = [];
      res.on('data', (chunk) => chunks.push(chunk));
      res.on('end', () => finish(null, Buffer.concat(chunks).toString('utf8')));
      res.on('error', (err) => finish(err));
    });

    req.setTimeout(timeoutMs, () => {
      if (settled || handedOff) return;
      req.destroy(new Error('Request timed out'));
      finish(new Error('Request timed out'));
    });
    req.on('error', (err) => {
      if (!handedOff) finish(err);
    });
  });
}

async function detectChanges(state, env = process.env) {
  log('Fetching Anthropic changelog...', 'INFO', env);

  let changelogContent = null;
  let successUrl = null;
  const sources = resolveChangelogSources(env);

  for (const url of sources) {
    try {
      log(`Trying ${url}...`, 'INFO', env);
      changelogContent = await fetchChangelog(url, { env, timeoutMs: requestTimeoutMs(env) });
      successUrl = url;
      log(`Successfully fetched from ${url}`, 'INFO', env);
      break;
    } catch (e) {
      log(`Failed to fetch from ${url}: ${e.message}`, 'WARN', env);
    }
  }

  if (!changelogContent) {
    log('Could not fetch changelog from any source', 'ERROR', env);
    return null;
  }

  // Simple heuristic: look for version numbers or date patterns
  // This is intentionally simple - full analysis happens in /dex-whats-new
  const versionMatches = changelogContent.match(/version\s+(\d+\.\d+\.\d+)/gi) || [];
  const dateMatches = changelogContent.match(/202[0-9]-[0-1][0-9]-[0-3][0-9]/g) || [];

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

  let latestDate = null;
  if (dateMatches.length > 0) {
    latestDate = dateMatches.sort().reverse()[0];
  }

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

function createPendingAlert(changes, env = process.env) {
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

  fs.writeFileSync(pendingFile(env), content);
  log(`Created pending alert file: ${pendingFile(env)}`, 'INFO', env);
}

function removePendingAlert(env = process.env) {
  const file = pendingFile(env);
  if (fs.existsSync(file)) {
    fs.unlinkSync(file);
    log('Removed pending alert file', 'INFO', env);
  }
}

// ============================================================================
// MAIN
// ============================================================================

async function main(options = {}) {
  const env = options.env || process.env;
  const args = options.args || process.argv.slice(2);
  const force = args.includes('--force');
  const dryRun = args.includes('--dry-run');
  const file = stateFile(env);

  // Fast path: check last check timestamp without loading full state
  if (!force && fs.existsSync(file)) {
    try {
      const state = JSON.parse(fs.readFileSync(file, 'utf-8'));
      if (state.last_check) {
        const lastCheck = new Date(state.last_check);
        const hoursSince = (new Date() - lastCheck) / (1000 * 60 * 60);
        if (hoursSince < MIN_CHECK_INTERVAL_HOURS) {
          return 0;
        }
      }
    } catch (e) {
      // Fall through to normal logging if state file is corrupted
    }
  }

  log('=== Anthropic Changelog Check Started ===', 'INFO', env);

  if (dryRun) {
    log('DRY RUN MODE - No files will be modified', 'INFO', env);
  }

  const state = loadState(env);
  log(`Current state: last_check=${state.last_check}, last_version=${state.last_version_seen}`, 'INFO', env);

  if (!shouldCheck(state, force, env)) {
    log('=== Check skipped (too soon) ===', 'INFO', env);
    return 0;
  }

  const changes = await detectChanges(state, env);

  if (!changes) {
    log('=== Check failed (could not fetch changelog) ===', 'ERROR', env);
    return 1;
  }

  log(`Changes detected: ${changes.hasChanges}`, 'INFO', env);
  log(`Latest version: ${changes.latestVersion || 'none found'}`, 'INFO', env);
  log(`Latest date: ${changes.latestDate || 'none found'}`, 'INFO', env);

  if (dryRun) {
    log('DRY RUN - Would have updated state and created alert if changes detected', 'INFO', env);
    log('=== Dry Run Complete ===', 'INFO', env);
    return 0;
  }

  const newState = {
    ...state,
    last_check: new Date().toISOString().split('T')[0], // YYYY-MM-DD
    last_version_seen: changes.latestVersion || state.last_version_seen,
    features_seen: state.features_seen // Preserved, updated by /dex-whats-new
  };

  saveState(newState, env);

  if (changes.hasChanges) {
    log('NEW CHANGES DETECTED - Creating alert file', 'INFO', env);
    createPendingAlert(changes, env);
  } else {
    log('No new changes detected', 'INFO', env);
    removePendingAlert(env);
  }

  log('=== Check Complete ===', 'INFO', env);
  return 0;
}

if (require.main === module) {
  main()
    .then((code) => process.exit(typeof code === 'number' ? code : 1))
    .catch((err) => {
      try {
        log(`Fatal error: ${err.message}`, 'ERROR');
      } catch (_) {
        console.error(`Fatal error: ${err.message}`);
      }
      console.error(err);
      process.exit(1);
    });
}

module.exports = {
  CHANGELOG_SOURCES,
  MAX_REDIRECTS,
  fetchChangelog,
  main,
  resolveChangelogSources,
  requestTimeoutMs,
};
