#!/usr/bin/env node
/**
 * Integration Concierge — Vault Scanner
 *
 * Scans the vault for signals that indicate which external tools the user works with.
 * Returns intelligent integration recommendations ranked by signal strength.
 *
 * Called by:
 * - Onboarding Step 8 (first-time integration discovery)
 * - /getting-started (post-onboarding tour)
 * - /dex-level-up (feature discovery)
 *
 * Outputs JSON to stdout with tool signals and recommendations.
 *
 * Signal types:
 * - Direct mentions: "Todoist", "Jira", "Trello" in notes
 * - URL patterns: zoom.us links, todoist.com links, atlassian.net URLs
 * - Calendar signatures: "Teams meeting", "Zoom Meeting" in event titles
 * - Email patterns: @gmail.com, @outlook.com in person pages
 * - File patterns: .ics attachments, Jira ticket IDs (PROJ-123)
 */

const fs = require('fs');
const path = require('path');

const { loadPaths } = require('./paths.cjs');

const _paths = loadPaths();
const VAULT_ROOT = _paths.VAULT_ROOT || process.env.CLAUDE_PROJECT_DIR || process.env.VAULT_PATH || path.resolve(__dirname, '../..');
const CONFIG_FILE = path.join(VAULT_ROOT, 'System', 'integrations', 'config.yaml');
const ARCHIVES_BASENAME = path.basename(_paths.ARCHIVES_DIR);

// ---------------------------------------------------------------------------
// Integration signal definitions
// ---------------------------------------------------------------------------

const INTEGRATIONS = {
  'google-workspace': {
    id: 'google-workspace',
    name: 'Google Workspace (Gmail + Calendar + Docs)',
    shortName: 'Gmail',
    setup: '/google-workspace-setup',
    signals: {
      keywords: ['gmail', 'google docs', 'google sheets', 'google drive', 'google calendar', 'google meet'],
      urls: [/gmail\.com/i, /docs\.google\.com/i, /drive\.google\.com/i, /meet\.google\.com/i, /calendar\.google\.com/i],
      email: [/@gmail\.com/i, /@googlemail\.com/i],
      calendar: [/google meet/i],
    },
    value: 'Email digest in daily plans, email context in meeting prep, follow-up detection',
    setupTime: '3 min',
    auth: 'OAuth (Google account)',
  },
  teams: {
    id: 'teams',
    name: 'Microsoft Teams',
    shortName: 'Teams',
    setup: '/ms-teams-setup',
    signals: {
      keywords: ['microsoft teams', 'teams meeting', 'teams call', 'ms teams'],
      urls: [/teams\.microsoft\.com/i, /teams\.live\.com/i],
      email: [/@outlook\.com/i, /@hotmail\.com/i, /@live\.com/i],
      calendar: [/teams meeting/i, /microsoft teams/i],
    },
    value: 'Teams digest alongside Slack, chat context in meeting prep',
    setupTime: '2 min',
    auth: 'OAuth (Microsoft account)',
  },
  todoist: {
    id: 'todoist',
    name: 'Todoist',
    shortName: 'Todoist',
    setup: '/todoist-setup',
    signals: {
      keywords: ['todoist', 'todoist task', 'todoist project'],
      urls: [/todoist\.com/i, /app\.todoist\.com/i],
    },
    value: 'Two-way task sync — complete in either place, both stay current',
    setupTime: '1 min',
    auth: 'API key (from Todoist settings)',
  },
  things: {
    id: 'things',
    name: 'Things 3',
    shortName: 'Things 3',
    setup: '/things-setup',
    signals: {
      keywords: ['things 3', 'things app', 'things today', 'things inbox'],
      urls: [/things:\/\//i, /culturedcode\.com/i],
    },
    value: 'Two-way task sync, Mac-native, works offline, no account needed',
    setupTime: '30 sec',
    auth: 'None (local AppleScript)',
  },
  trello: {
    id: 'trello',
    name: 'Trello',
    shortName: 'Trello',
    setup: '/trello-setup',
    signals: {
      keywords: ['trello', 'trello board', 'trello card'],
      urls: [/trello\.com/i],
    },
    value: 'Board sync — cards become tasks, moving to Done completes in Dex',
    setupTime: '2 min',
    auth: 'API key + token',
  },
  zoom: {
    id: 'zoom',
    name: 'Zoom',
    shortName: 'Zoom',
    setup: '/zoom-setup',
    signals: {
      keywords: ['zoom call', 'zoom meeting', 'zoom recording', 'zoom link'],
      urls: [/zoom\.us/i, /zoom\.com/i],
      calendar: [/zoom meeting/i],
    },
    value: 'Recording access and meeting scheduling',
    setupTime: '2 min',
    auth: 'OAuth (Zoom account)',
    note: 'If Granola is connected, Zoom mainly adds scheduling (meetings already captured).',
  },
  atlassian: {
    id: 'atlassian',
    name: 'Atlassian (Jira + Confluence)',
    shortName: 'Jira/Confluence',
    setup: '/atlassian-setup',
    signals: {
      keywords: ['jira', 'confluence', 'atlassian', 'sprint', 'epic', 'jira ticket'],
      urls: [/atlassian\.net/i, /jira\./i, /confluence\./i],
      patterns: [/[A-Z]{2,10}-\d{1,6}/g], // Jira ticket IDs like PROJ-123
    },
    value: 'Jira tickets and Confluence docs in daily plans, sprint tracking',
    setupTime: '3 min',
    auth: 'OAuth (Atlassian Cloud)',
  },
};

// ---------------------------------------------------------------------------
// Vault scanning
// ---------------------------------------------------------------------------

function scanDirectory(dir, extensions, maxDepth = 3, depth = 0) {
  const files = [];
  if (depth >= maxDepth) return files;

  try {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      // Skip hidden dirs, node_modules, archives, System
      if (entry.name.startsWith('.') || entry.name === 'node_modules') continue;
      if (entry.name === ARCHIVES_BASENAME || entry.name === 'z. Archive') continue;

      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        files.push(...scanDirectory(fullPath, extensions, maxDepth, depth + 1));
      } else if (extensions.some(ext => entry.name.endsWith(ext))) {
        files.push(fullPath);
      }
    }
  } catch {
    // Permission denied or other error — skip silently
  }
  return files;
}

function scanForSignals() {
  const results = {};

  for (const [key, integration] of Object.entries(INTEGRATIONS)) {
    results[key] = {
      ...integration,
      score: 0,
      mentions: 0,
      examples: [],
    };
  }

  // Scan markdown files across the vault
  const scanDirs = [
    _paths.INBOX_DIR,
    _paths.PROJECTS_DIR,
    _paths.AREAS_DIR,
    _paths.TASKS_DIR,
    _paths.WEEK_PRIORITIES_DIR,
  ];

  const files = [];
  for (const dir of scanDirs) {
    if (fs.existsSync(dir)) {
      files.push(...scanDirectory(dir, ['.md'], 4));
    }
  }

  // Limit to most recent 200 files for performance
  const recentFiles = files
    .map(f => ({ path: f, mtime: fs.statSync(f).mtimeMs }))
    .sort((a, b) => b.mtime - a.mtime)
    .slice(0, 200);

  for (const { path: filePath } of recentFiles) {
    let content;
    try {
      content = fs.readFileSync(filePath, 'utf-8').toLowerCase();
    } catch {
      continue;
    }

    const shortPath = path.relative(VAULT_ROOT, filePath);

    for (const [key, integration] of Object.entries(INTEGRATIONS)) {
      const signals = integration.signals;
      let fileHits = 0;

      // Keyword search
      if (signals.keywords) {
        for (const kw of signals.keywords) {
          const regex = new RegExp(kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'gi');
          const matches = content.match(regex);
          if (matches) {
            fileHits += matches.length;
          }
        }
      }

      // URL pattern search
      if (signals.urls) {
        for (const pattern of signals.urls) {
          const matches = content.match(pattern);
          if (matches) {
            fileHits += matches.length;
          }
        }
      }

      // Calendar signature search
      if (signals.calendar) {
        for (const pattern of signals.calendar) {
          const matches = content.match(pattern);
          if (matches) {
            fileHits += matches.length * 2; // Calendar signals are high-confidence
          }
        }
      }

      // Jira-style ticket pattern search
      if (signals.patterns) {
        for (const pattern of signals.patterns) {
          const matches = content.match(pattern);
          if (matches) {
            // Filter out false positives (common abbreviations)
            const real = matches.filter(m => !['AM', 'PM', 'UK', 'US', 'EU', 'AI', 'VP', 'HR', 'IT', 'QA'].includes(m.split('-')[0]));
            fileHits += real.length;
          }
        }
      }

      if (fileHits > 0) {
        results[key].mentions += fileHits;
        results[key].score += fileHits;
        if (results[key].examples.length < 3) {
          results[key].examples.push(shortPath);
        }
      }
    }
  }

  // Email pattern scan (person pages only)
  const peopleDirs = [
    path.join(_paths.PEOPLE_DIR, 'Internal'),
    path.join(_paths.PEOPLE_DIR, 'External'),
  ];

  for (const dir of peopleDirs) {
    if (!fs.existsSync(dir)) continue;
    const personFiles = scanDirectory(dir, ['.md'], 2);
    for (const pf of personFiles) {
      let content;
      try {
        content = fs.readFileSync(pf, 'utf-8');
      } catch {
        continue;
      }

      for (const [key, integration] of Object.entries(INTEGRATIONS)) {
        if (integration.signals.email) {
          for (const pattern of integration.signals.email) {
            if (pattern.test(content)) {
              results[key].score += 3; // High signal from person pages
              results[key].mentions++;
            }
          }
        }
      }
    }
  }

  return results;
}

// ---------------------------------------------------------------------------
// Check already-enabled integrations
// ---------------------------------------------------------------------------

function getEnabledIntegrations() {
  try {
    const config = fs.readFileSync(CONFIG_FILE, 'utf-8');
    const enabled = [];
    // Simple regex to find enabled integrations
    const blocks = config.split(/^(?=\w)/m);
    for (const block of blocks) {
      const nameMatch = block.match(/^([\w-]+):/);
      const enabledMatch = block.match(/enabled:\s*true/);
      if (nameMatch && enabledMatch) {
        enabled.push(nameMatch[1]);
      }
    }
    return enabled;
  } catch {
    return [];
  }
}

// ---------------------------------------------------------------------------
// Check Granola status (for Zoom recommendation)
// ---------------------------------------------------------------------------

function isGranolaConfigured() {
  try {
    const config = fs.readFileSync(CONFIG_FILE, 'utf-8');
    return /granola:[\s\S]*?enabled:\s*true/.test(config);
  } catch {
    // Also check if Granola MCP is in the server list
    try {
      const mcpConfig = fs.readFileSync(path.join(VAULT_ROOT, 'System', '.mcp.json'), 'utf-8');
      return mcpConfig.includes('granola');
    } catch {
      return false;
    }
  }
}

// ---------------------------------------------------------------------------
// Generate recommendations
// ---------------------------------------------------------------------------

function generateRecommendations(signals) {
  const enabled = getEnabledIntegrations();
  const hasGranola = isGranolaConfigured();

  const recommendations = {
    high_value: [],    // Score >= 5 and not enabled
    moderate_value: [], // Score 1-4 and not enabled
    available: [],     // Score 0, not enabled
    already_connected: [], // Already enabled
  };

  for (const [key, data] of Object.entries(signals)) {
    if (enabled.includes(key)) {
      recommendations.already_connected.push({
        id: key,
        name: data.shortName,
      });
      continue;
    }

    const entry = {
      id: key,
      name: data.name,
      shortName: data.shortName,
      setup: data.setup,
      value: data.value,
      setupTime: data.setupTime,
      auth: data.auth,
      score: data.score,
      mentions: data.mentions,
      examples: data.examples,
    };

    // Add Granola note to Zoom
    if (key === 'zoom' && hasGranola) {
      entry.note = 'You already have Granola capturing meetings. Zoom mainly adds scheduling capability.';
      entry.score = Math.max(0, entry.score - 3); // Reduce score since overlap
    }

    if (data.note) {
      entry.note = entry.note || data.note;
    }

    if (entry.score >= 5) {
      recommendations.high_value.push(entry);
    } else if (entry.score >= 1) {
      recommendations.moderate_value.push(entry);
    } else {
      recommendations.available.push(entry);
    }
  }

  // Sort each tier by score descending
  recommendations.high_value.sort((a, b) => b.score - a.score);
  recommendations.moderate_value.sort((a, b) => b.score - a.score);

  return recommendations;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

function main() {
  const signals = scanForSignals();
  const recommendations = generateRecommendations(signals);

  console.log(JSON.stringify(recommendations, null, 2));
}

main();
