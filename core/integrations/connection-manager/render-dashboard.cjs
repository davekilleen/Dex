#!/usr/bin/env node
'use strict';
/**
 * render-dashboard.cjs — Generate {DEX_VAULT}/System/Connected_Apps.md from the
 * connection registry. Pure read: calls health.allConnectionsHealth() (no network)
 * and reads the registry for timestamp fields the health view doesn't surface.
 *
 * The file is GENERATED — edits to it are overwritten. Source of truth is
 * {DEX_VAULT}/System/credentials/connections.json.
 *
 *   node render-dashboard.cjs        write the dashboard
 *
 * Exports renderDashboard() (returns the markdown string) and writeDashboard()
 * (writes the file and returns its path).
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

const health = require('./health.cjs');
const store = require('./token-store.cjs');

/** Resolve the vault root: $DEX_VAULT, else ~/Vault. */
function vaultRoot() {
  return process.env.DEX_VAULT || path.join(os.homedir(), 'Vault');
}

function dashboardPath() {
  return path.join(vaultRoot(), 'System', 'Connected_Apps.md');
}

// Status → icon. Matches connect.cjs status sweep.
const STATUS_ICON = {
  connected: '🟢',
  expiring: '🟡',
  expired: '🟠',
  needs_reauth: '🔴',
  error: '🔴',
  not_connected: '⚪',
};

const NEEDS_ATTENTION = new Set(['needs_reauth', 'expired']);

function fmtDate(value) {
  if (!value) return '—';
  try {
    // Accept ISO strings or epoch ms.
    const d = typeof value === 'number' ? new Date(value) : new Date(String(value));
    if (Number.isNaN(d.getTime())) return '—';
    return d.toISOString().slice(0, 10);
  } catch {
    return '—';
  }
}

function fmtScopes(scopes) {
  if (!Array.isArray(scopes) || scopes.length === 0) return '—';
  return scopes.join(', ');
}

function tableHeader() {
  return [
    '| App | Account | Status | Scopes | Connected | Last refreshed | Last used | Error |',
    '|-----|---------|--------|--------|-----------|----------------|-----------|-------|',
  ].join('\n');
}

function tableRow(row, reg) {
  const icon = STATUS_ICON[row.status] || '•';
  const r = reg[row.service] || {};
  const connected = fmtDate(r.connectedAt);
  const lastRefreshed = fmtDate(row.lastRefreshedAt || r.lastRefreshedAt);
  const lastUsed = fmtDate(r.lastUsedAt);
  const error = row.error ? String(row.error) : '—';
  const account = row.alias || 'default'; // multi-account: which account of this provider
  return `| ${row.provider || row.service} | ${account} | ${icon} ${row.status} | ${fmtScopes(row.scopes)} | ${connected} | ${lastRefreshed} | ${lastUsed} | ${error} |`;
}

/** Build the full markdown document as a string. */
function renderDashboard() {
  const rows = health.allConnectionsHealth();
  const reg = store.readRegistry();
  const generated = new Date().toISOString();

  const header = [
    '<!-- do not edit — generated from connections.json by render-dashboard.cjs -->',
    '',
    '# Connected Apps',
    '',
    `*Generated: ${generated}*`,
    '',
  ].join('\n');

  if (!rows.length) {
    return [
      header,
      'No apps connected yet — run `/connect` to add one.',
      '',
    ].join('\n');
  }

  const attention = rows.filter((r) => NEEDS_ATTENTION.has(r.status));
  const rest = rows.filter((r) => !NEEDS_ATTENTION.has(r.status));

  const sections = [header];

  if (attention.length) {
    sections.push(
      '## Needs attention',
      '',
      'These connections need you to reconnect — run `/connect <app>`.',
      '',
      tableHeader(),
      ...attention.map((r) => tableRow(r, reg)),
      ''
    );
  }

  sections.push(
    '## All connections',
    '',
    tableHeader(),
    ...rest.map((r) => tableRow(r, reg)),
    ''
  );

  return sections.join('\n');
}

/** Render and write the dashboard file. Returns the absolute path written. */
function writeDashboard() {
  const out = dashboardPath();
  fs.mkdirSync(path.dirname(out), { recursive: true });
  fs.writeFileSync(out, renderDashboard());
  return out;
}

if (require.main === module) {
  const out = writeDashboard();
  console.log(`Wrote ${out}`);
}

module.exports = { renderDashboard, writeDashboard, dashboardPath, vaultRoot };
