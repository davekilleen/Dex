#!/usr/bin/env node
/**
 * Stop hook: automatic session-learning capture (see Memory_Ownership.md "learning-heartbeat").
 *
 * Session_Learnings/YYYY-MM-DD.md only ever gets populated today via /review or
 * /daily-review, which the user has to remember to run. This hook closes that gap: a
 * hook can't reason about the conversation itself (it's a dumb script), so when a
 * session looks substantive enough to be worth reflecting on, it blocks the Stop once
 * and asks the live Claude session to do the actual extraction, using the canonical
 * template in System/Session_Learnings/README.md.
 *
 * Fires at most once per (session, calendar day) — debounced via a state file, not
 * just stop_hook_active, since Stop fires on every turn and stop_hook_active only
 * guards the single forced continuation, not the rest of the session.
 *
 * Opt-out: System/user-profile.yaml -> learning_heartbeat.enabled: false
 *
 * v1 heuristic: "substantive" = >=3 user turns OR >=8 tool calls in the transcript.
 * This is a cheap proxy, not a precise measure — tune later if it over/under-fires.
 *
 * Verified empirically (in a fork with an additional local Stop hook also using
 * decision:block): when two Stop hooks in the same array both want to block, Claude
 * Code surfaces BOTH reasons rather than dropping one — safe to run alongside other
 * Stop hooks that also use decision:block.
 */

const fs = require('fs');
const path = require('path');

const MIN_USER_TURNS = 3;
const MIN_TOOL_CALLS = 8;

function readStdin() {
  try {
    return fs.readFileSync(0, 'utf8');
  } catch {
    return '';
  }
}

function todayStr() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function isHeartbeatEnabled(vaultRoot) {
  const profilePath = path.join(vaultRoot, 'System', 'user-profile.yaml');
  try {
    const content = fs.readFileSync(profilePath, 'utf8');
    const m = content.match(/learning_heartbeat:\s*\n(?:[ \t]+.*\n?)*/);
    if (!m) return true; // field absent -> default on
    const block = m[0];
    const enabledMatch = block.match(/enabled:\s*(true|false)/);
    if (!enabledMatch) return true;
    return enabledMatch[1] !== 'false';
  } catch {
    return true; // no profile / unreadable -> default on
  }
}

function countSignals(transcriptPath) {
  let lines;
  try {
    lines = fs.readFileSync(transcriptPath, 'utf8').split('\n');
  } catch {
    return { userTurns: 0, toolCalls: 0 };
  }

  let userTurns = 0;
  let toolCalls = 0;
  for (const line of lines) {
    if (!line.trim()) continue;
    let parsed;
    try {
      parsed = JSON.parse(line);
    } catch {
      continue;
    }
    const msg = parsed?.message;
    if (!msg) continue;
    if (msg.role === 'user') {
      const c = msg.content;
      const isHumanText =
        typeof c === 'string' ||
        (Array.isArray(c) && c.some((b) => b?.type === 'text'));
      if (isHumanText) userTurns++;
    }
    if (Array.isArray(msg.content)) {
      for (const block of msg.content) {
        if (block?.type === 'tool_use') toolCalls++;
      }
    }
  }
  return { userTurns, toolCalls };
}

function loadState(statePath) {
  try {
    const raw = JSON.parse(fs.readFileSync(statePath, 'utf8'));
    if (raw && raw.date === todayStr() && Array.isArray(raw.sessionsExtractedToday)) {
      return raw;
    }
  } catch {
    // missing/corrupt -> fresh state
  }
  return { date: todayStr(), sessionsExtractedToday: [] };
}

function saveStateAtomic(statePath, state) {
  const dir = path.dirname(statePath);
  fs.mkdirSync(dir, { recursive: true });
  const tmpPath = `${statePath}.${process.pid}.tmp`;
  fs.writeFileSync(tmpPath, JSON.stringify(state), 'utf8');
  fs.renameSync(tmpPath, statePath);
}

function main() {
  let input = {};
  try {
    input = JSON.parse(readStdin() || '{}');
  } catch {
    process.exit(0); // malformed input -> never block
  }

  // Avoid infinite loops: if we're already in a stop-hook-induced continuation, pass.
  if (input.stop_hook_active) process.exit(0);

  const vaultRoot = process.env.CLAUDE_PROJECT_DIR || process.cwd();

  try {
    if (!isHeartbeatEnabled(vaultRoot)) process.exit(0);
  } catch {
    // fail open
  }

  const transcriptPath = input.transcript_path || process.env.transcript_path;
  if (!transcriptPath || !fs.existsSync(transcriptPath)) process.exit(0);

  const sessionId = input.session_id || 'unknown-session';
  const statePath = path.join(vaultRoot, 'System', 'Session_Learnings', '.heartbeat-state.json');

  let state;
  try {
    state = loadState(statePath);
  } catch {
    process.exit(0); // fail open on any state-file trouble
  }

  if (state.sessionsExtractedToday.includes(sessionId)) process.exit(0);

  const { userTurns, toolCalls } = countSignals(transcriptPath);
  if (userTurns < MIN_USER_TURNS && toolCalls < MIN_TOOL_CALLS) process.exit(0);

  // Mark this session as extracted for today BEFORE blocking, so a failed or
  // interrupted forced-turn can never cause a re-block loop for the rest of the day.
  state.sessionsExtractedToday.push(sessionId);
  try {
    saveStateAtomic(statePath, state);
  } catch {
    process.exit(0); // if we can't record the debounce, don't risk blocking repeatedly
  }

  const reason =
    'Learning heartbeat (Memory_Ownership.md): this looks like a substantive session. ' +
    'Before finishing, reflect on it and extract any learnings worth keeping — mistakes ' +
    'or corrections, preferences mentioned, documentation gaps, workflow inefficiencies. ' +
    'Follow the exact template in System/Session_Learnings/README.md and write conforming ' +
    'entries to System/Session_Learnings/YYYY-MM-DD.md. If nothing meets the bar, say so ' +
    "in one short line and stop — don't fabricate entries. Keep this brief either way.";

  process.stdout.write(JSON.stringify({ decision: 'block', reason }));
  process.exit(0);
}

main();
