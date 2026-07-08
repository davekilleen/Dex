#!/usr/bin/env node
/**
 * Meeting summary generator — fires on Stop after /process-meetings completes.
 * Reads the processed-meetings state file and emits a one-line status to stderr
 * so the session transcript shows what was actually processed.
 */
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const VAULT_PATH = process.env.VAULT_PATH || process.cwd();
const STATE_FILE = path.join(VAULT_PATH, '.scripts/meeting-intel/processed-meetings.json');

function summarise() {
  if (!fs.existsSync(STATE_FILE)) {
    process.stderr.write('[meeting-summary] No processed-meetings state file found — skipping summary.\n');
    process.exit(0);
  }

  let state;
  try {
    state = JSON.parse(fs.readFileSync(STATE_FILE, 'utf8'));
  } catch {
    process.stderr.write('[meeting-summary] Could not parse state file — skipping summary.\n');
    process.exit(0);
  }

  const meetings = Array.isArray(state.meetings) ? state.meetings : [];
  const lastSync = state.last_sync ? new Date(state.last_sync).toLocaleString() : 'unknown';

  const recent = meetings.filter((m) => {
    if (!m.processed_at) return false;
    const age = Date.now() - new Date(m.processed_at).getTime();
    return age < 24 * 60 * 60 * 1000; // processed in last 24 h
  });

  const tasksExtracted = recent.reduce((sum, m) => sum + (m.tasks_extracted || 0), 0);
  const peopleUpdated = recent.reduce((sum, m) => sum + (m.people_updated || 0), 0);

  const parts = [`${recent.length} meeting(s) processed`];
  if (peopleUpdated > 0) parts.push(`${peopleUpdated} person page(s) updated`);
  if (tasksExtracted > 0) parts.push(`${tasksExtracted} task(s) extracted`);
  parts.push(`last sync: ${lastSync}`);

  process.stderr.write(`[meeting-summary] ${parts.join(' · ')}\n`);
}

summarise();
process.exit(0);
