#!/usr/bin/env node

/**
 * Proactive intelligence engine for Dex Slack bot.
 * Timer-based checks that surface information without being asked.
 * Uses SQLite preferences for dedup (survives restarts).
 */

const fs = require('fs');
const path = require('path');
const { getCalendarToday, lookupPerson, getWeekPriorities } = require('./data-sources.cjs');
const { callWorkServer } = require('./work-bridge.cjs');
const memory = require('./memory.cjs');

const VAULT_ROOT = path.resolve(__dirname, '../..');
let webClient = null;
let slackUserId = null;

function log(msg) { console.log(`[${new Date().toISOString()}] ${msg}`); }
function logError(msg) { console.error(`[${new Date().toISOString()}] ${msg}`); }

async function sendDM(text) {
  if (!webClient || !slackUserId) return;
  try {
    await webClient.chat.postMessage({ channel: slackUserId, text, mrkdwn: true });
  } catch (e) {
    logError(`[proactive] DM failed: ${e.message}`);
  }
}

function wasAlertedRecently(key, hoursAgo = 12) {
  const last = memory.getPref(`proactive:${key}`);
  if (!last) return false;
  const elapsed = (Date.now() - new Date(last).getTime()) / 3600000;
  return elapsed < hoursAgo;
}

function markAlerted(key) {
  memory.setPref(`proactive:${key}`, new Date().toISOString());
}

// --- Check: Meeting briefs (10-15 min before) ---
async function checkMeetingBriefs() {
  try {
    const { events, error } = getCalendarToday();
    if (error || !events) return;

    const now = new Date();
    for (const event of events) {
      if (event.all_day) continue;
      const start = new Date(event.start);
      const minsUntil = (start - now) / 60000;
      const briefKey = `meeting:${event.title}:${event.start}`;

      if (minsUntil > 0 && minsUntil <= 15 && !wasAlertedRecently(briefKey, 1)) {
        markAlerted(briefKey);

        const attendeeNames = (event.attendees || [])
          .map(a => a.name || a.email || '')
          .filter(n => n && !n.toLowerCase().includes('tom'));

        const personContext = attendeeNames.slice(0, 2).map(name => {
          const person = lookupPerson(name.split(' ')[0]);
          return person.found
            ? `*${person.name}*\n${person.content.split('\n').filter(l => l.trim()).slice(0, 6).join('\n')}`
            : `*${name}* — no notes on file`;
        });

        let text = `\ud83d\udce3 *${event.title}* in ${Math.round(minsUntil)} min`;
        if (event.location) text += `\n\ud83d\udccd ${event.location}`;
        if (attendeeNames.length > 0) text += `\n\ud83d\udc65 ${attendeeNames.join(', ')}`;
        if (personContext.length > 0) text += `\n\n${personContext.join('\n\n')}`;

        await sendDM(text);
        log(`[proactive] Meeting brief: ${event.title}`);
      }
    }
  } catch (e) { logError(`[proactive] Meeting brief check: ${e.message}`); }
}

// --- Check: Stale priorities (Wed+ with no activity) ---
async function checkStalePriorities() {
  try {
    const dayOfWeek = new Date().getDay(); // 0=Sun, 3=Wed
    if (dayOfWeek < 3 || dayOfWeek > 5) return; // Only Wed-Fri

    const wp = getWeekPriorities();
    if (!wp.top3 || wp.top3.length === 0) return;

    // Check if P0 tasks are all still open
    const stalePriorities = [];
    for (const pri of wp.top3) {
      const key = `stale:${pri.title.slice(0, 30)}`;
      if (wasAlertedRecently(key, 24)) continue;

      // Simple heuristic: if a priority has no completed tasks referencing it, it's stale
      const tasks = wp.tasks.P0.concat(wp.tasks.P1);
      const relatedTasks = tasks.filter(t => t.toLowerCase().includes(pri.title.split(' ').slice(0, 3).join(' ').toLowerCase()));
      const allOpen = relatedTasks.every(t => !t.includes('[x]'));

      if (allOpen && relatedTasks.length > 0) {
        stalePriorities.push(pri.title);
        markAlerted(key);
      }
    }

    if (stalePriorities.length > 0) {
      const text = `\u26a0\ufe0f *Priority alert*\n\nThese week priorities have no completed tasks:\n${stalePriorities.map(p => `\u2022 ${p}`).join('\n')}\n\nNeed to reprioritize or delegate?`;
      await sendDM(text);
      log(`[proactive] Stale priority alert: ${stalePriorities.length} items`);
    }
  } catch (e) { logError(`[proactive] Stale priorities check: ${e.message}`); }
}

// --- Check: Commitment deadlines ---
async function checkCommitmentDeadlines() {
  try {
    if (wasAlertedRecently('commitments_today', 8)) return;

    const data = callWorkServer('get_commitments_due');
    if (data.error) return;

    const dueToday = data.commitments_due_today || [];
    if (dueToday.length === 0) return;

    markAlerted('commitments_today');
    const text = `\ud83d\udccc *${dueToday.length} commitment${dueToday.length > 1 ? 's' : ''} due today*\n\n${dueToday.map(c => `\u2022 ${c.title || c.text || JSON.stringify(c)}`).join('\n')}`;
    await sendDM(text);
    log(`[proactive] Commitment deadline alert: ${dueToday.length} items`);
  } catch (e) { logError(`[proactive] Commitment check: ${e.message}`); }
}

// --- Check: Post-meeting synthesis ---
async function checkNewMeetings() {
  try {
    const stateFile = path.join(VAULT_ROOT, '.scripts', 'meeting-intel', 'processed-meetings.json');
    if (!fs.existsSync(stateFile)) return;

    const stat = fs.statSync(stateFile);
    const lastChecked = memory.getPref('proactive:meetings_mtime');
    const currentMtime = stat.mtimeMs.toString();

    if (lastChecked === currentMtime) return;
    memory.setPref('proactive:meetings_mtime', currentMtime);

    // Don't alert on first check (would spam all historical meetings)
    if (!lastChecked) return;

    const meetings = JSON.parse(fs.readFileSync(stateFile, 'utf8'));
    // Find meetings processed in last 10 minutes
    const recentCutoff = Date.now() - 600000;
    const recent = Object.entries(meetings).filter(([, v]) => {
      const ts = new Date(v.processed_at || v.timestamp || 0).getTime();
      return ts > recentCutoff;
    });

    for (const [id, meeting] of recent.slice(0, 2)) {
      const key = `meeting_synth:${id}`;
      if (wasAlertedRecently(key, 24)) continue;
      markAlerted(key);

      const title = meeting.title || id;
      const text = `\ud83d\udcdd *Meeting processed:* ${title}\n\nNotes saved. Ask me for details: "what happened in ${title.split(' ').slice(0, 4).join(' ')}?"`;
      await sendDM(text);
      log(`[proactive] Meeting synthesis: ${title}`);
    }
  } catch (e) { logError(`[proactive] Meeting synthesis check: ${e.message}`); }
}

// --- Schedule ---
const CHECKS = [
  { name: 'meeting_briefs', fn: checkMeetingBriefs, intervalMs: 60_000 },
  { name: 'stale_priorities', fn: checkStalePriorities, intervalMs: 4 * 3600_000 },
  { name: 'commitment_deadlines', fn: checkCommitmentDeadlines, intervalMs: 3600_000 },
  { name: 'new_meetings', fn: checkNewMeetings, intervalMs: 300_000 },
];

function startAll(client, userId) {
  webClient = client;
  slackUserId = userId;

  for (const check of CHECKS) {
    setInterval(() => check.fn().catch(e => logError(`[proactive] ${check.name}: ${e.message}`)), check.intervalMs);
    // Run each check once at startup (staggered to avoid thundering herd)
    setTimeout(() => check.fn().catch(e => logError(`[proactive] ${check.name}: ${e.message}`)), Math.random() * 5000);
  }

  log('[proactive] Engine started with ' + CHECKS.length + ' checks');
}

module.exports = { startAll };
