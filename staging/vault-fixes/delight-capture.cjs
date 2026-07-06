#!/usr/bin/env node
/**
 * Delight Capture Hook (Stop event)
 *
 * Fires after every Claude response. Scans user messages for delight
 * signals — spontaneous positive reactions after using a workflow.
 * Logs candidates to System/Observation_Layer/delight_candidates.jsonl
 * for later surfacing during daily review ("Would you mind sharing that?").
 *
 * Also checks for milestone events — when a skill reaches 5+ invocations
 * and hasn't been celebrated yet.
 *
 * Never interrupts the session. Fails silently. Exits 0 always.
 *
 * 2026-06-10 fix (DexDiff end-to-end review): Claude Code transcripts are
 * JSON-Lines, not a single JSON document. The previous whole-file
 * JSON.parse threw on every real transcript, the catch swallowed it, and
 * the hook captured nothing for 10 weeks. Transcripts are now parsed line
 * by line (the legacy single-array format still works), user text is read
 * from content-block arrays, tool_result blocks are ignored so file
 * contents cannot fake delight, and the milestone check runs even when no
 * user messages are found (it was unreachable behind the early exit).
 */

const fs = require("fs");
const path = require("path");

// Guard: prevent re-entrant execution
if (process.env.DELIGHT_HOOK_ACTIVE === "1") process.exit(0);
process.env.DELIGHT_HOOK_ACTIVE = "1";

const VAULT_ROOT = process.env.CLAUDE_PROJECT_DIR || process.cwd();
const DELIGHT_LOG = path.join(VAULT_ROOT, "System/Observation_Layer/delight_candidates.jsonl");
const STATE_FILE = path.join(VAULT_ROOT, "System/Observation_Layer/.delight-state.json");
const WORKFLOW_MODEL = path.join(VAULT_ROOT, ".dex/workflow-model.json");

// ---------------------------------------------------------------------------
// Delight patterns — phrases that indicate a positive reaction
// ---------------------------------------------------------------------------
const DELIGHT_PATTERNS = [
  // Direct praise
  /\bthat was perfect\b/i,
  /\bsaved me\b/i,
  /\bcan'?t believe\b/i,
  /\bholy shit\b/i,
  /\bthis is great\b/i,
  /\blove this\b/i,
  /\blove you\b/i,
  /\bexactly what I needed\b/i,
  /\bgame changer\b/i,
  /\bamazing\b/i,
  /\bbrilliant\b/i,
  /\bincredible\b/i,
  /\bperfect\b/i,
  /\bwow\b/i,
  /\bwell done\b/i,
  /\bnice one\b/i,
  /\bnailed it\b/i,
  /\byou'?re a legend\b/i,
  // Third-party outcome
  /\bshe couldn'?t believe\b/i,
  /\bhe couldn'?t believe\b/i,
  /\bthey couldn'?t believe\b/i,
  /\bthey were impressed\b/i,
  /\bworked perfectly\b/i,
  /\bworked great\b/i,
  /\bso much better\b/i,
  /\bchanged how I\b/i,
  /\bnever going back\b/i,
  // Time/effort saved
  /\bsaved .{0,20} hours?\b/i,
  /\bsaved .{0,20} minutes?\b/i,
  /\bsaved .{0,20} time\b/i,
  /\bso much faster\b/i,
];

// How much of the transcript tail to consider (lines for JSONL, entries after parse)
const MAX_TAIL_LINES = 400;
const MAX_USER_MESSAGES = 10;

// ---------------------------------------------------------------------------
// Read stdin (hook input)
// ---------------------------------------------------------------------------
function readStdin() {
  try {
    return fs.readFileSync("/dev/stdin", "utf-8");
  } catch {
    return "{}";
  }
}

// ---------------------------------------------------------------------------
// Transcript parsing, JSONL first (current format), legacy array fallback
// ---------------------------------------------------------------------------
function parseTranscriptEntries(raw) {
  const trimmed = raw.trim();
  if (!trimmed) return [];

  // Legacy single-document format: one JSON array (or {messages: [...]})
  if (trimmed.startsWith("[") || trimmed.startsWith("{")) {
    // Could still be JSONL whose first line starts with "{", try whole-file
    // parse first, fall back to line-by-line.
    try {
      const document = JSON.parse(trimmed);
      if (Array.isArray(document)) return document;
      if (document && Array.isArray(document.messages)) return document.messages;
      // A single JSON object that isn't a container, treat as one entry
      if (document && typeof document === "object") return [document];
    } catch {
      /* fall through to JSONL */
    }
  }

  const lines = trimmed.split("\n");
  const tail = lines.slice(-MAX_TAIL_LINES);
  const entries = [];
  for (const line of tail) {
    const candidate = line.trim();
    if (!candidate) continue;
    try {
      entries.push(JSON.parse(candidate));
    } catch {
      /* skip unparseable lines, never abort the whole scan */
    }
  }
  return entries;
}

// Extract human-authored text from one transcript entry. Returns "" for
// anything that is not a real user message (assistant turns, tool results).
function extractUserText(entry) {
  if (!entry || typeof entry !== "object") return "";
  const role = entry.role || entry?.message?.role;
  const isUserType = entry.type === "user" || role === "user";
  if (!isUserType) return "";

  const content = entry.content !== undefined ? entry.content : entry?.message?.content;

  if (typeof content === "string") return content;

  if (Array.isArray(content)) {
    // Content-block array: keep text blocks only. tool_result blocks carry
    // file/tool output in user-role entries and must never count as the
    // user expressing delight.
    return content
      .filter((block) => block && block.type === "text" && typeof block.text === "string")
      .map((block) => block.text)
      .join("\n");
  }

  return "";
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
try {
  let input = {};
  try {
    input = JSON.parse(readStdin());
  } catch {
    input = {};
  }
  const sessionId = input?.session_id || process.env.CLAUDE_SESSION_ID || "unknown";
  const transcriptPath = input?.transcript_path;

  // Read recent transcript entries for user messages
  let userMessages = [];
  if (transcriptPath && fs.existsSync(transcriptPath)) {
    try {
      const entries = parseTranscriptEntries(fs.readFileSync(transcriptPath, "utf-8"));
      for (const entry of entries) {
        const text = extractUserText(entry);
        if (text) userMessages.push(text);
      }
      userMessages = userMessages.slice(-MAX_USER_MESSAGES);
    } catch {
      /* ignore read errors */
    }
  }

  // Also check hook context for recent message
  const recentMessage = input?.message?.content || input?.stop_reason || "";
  if (recentMessage && typeof recentMessage === "string") userMessages.push(recentMessage);

  // Load state (tracks what we've already logged this session)
  let state = {};
  try {
    if (fs.existsSync(STATE_FILE)) {
      state = JSON.parse(fs.readFileSync(STATE_FILE, "utf-8"));
    }
  } catch {
    state = {};
  }

  const loggedPhrases = new Set(state.logged_phrases || []);
  const loggedMilestones = new Set(state.logged_milestones || []);
  const now = new Date().toISOString();
  const candidates = [];

  // Scan for delight signals (skipped naturally when there are no messages -
  // the milestone check below must still run)
  for (const msg of userMessages) {
    for (const pattern of DELIGHT_PATTERNS) {
      const match = msg.match(pattern);
      if (match && !loggedPhrases.has(match[0].toLowerCase())) {
        // Extract context (50 chars before and after the match)
        const idx = msg.indexOf(match[0]);
        const start = Math.max(0, idx - 50);
        const end = Math.min(msg.length, idx + match[0].length + 50);
        const context = msg.substring(start, end).trim();

        candidates.push({
          timestamp: now,
          session_id: sessionId,
          type: "delight",
          phrase: match[0],
          context: context,
          skill: null, // Could be enriched by reading recent tool uses
          status: "pending",
        });
        loggedPhrases.add(match[0].toLowerCase());
      }
    }
  }

  // Check milestones (skill reaches 5+ invocations). Runs regardless of
  // whether any user messages were found, previously unreachable when the
  // transcript parse failed or the turn had no user text.
  if (fs.existsSync(WORKFLOW_MODEL)) {
    try {
      const model = JSON.parse(fs.readFileSync(WORKFLOW_MODEL, "utf-8"));
      const workflows = model.workflows || {};
      for (const [id, data] of Object.entries(workflows)) {
        const freq = data.frequency || {};
        const runs = freq.runs_last_30d || 0;
        if (runs >= 5 && !loggedMilestones.has(id)) {
          candidates.push({
            timestamp: now,
            session_id: sessionId,
            type: "milestone_reached",
            skill_cluster: id,
            display_name: data.display_name || id,
            runs_last_30d: runs,
            status: "pending",
          });
          loggedMilestones.add(id);
        }
      }
    } catch {
      /* ignore */
    }
  }

  // Write candidates
  if (candidates.length > 0) {
    const dir = path.dirname(DELIGHT_LOG);
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
    const lines = candidates.map((c) => JSON.stringify(c)).join("\n") + "\n";
    fs.appendFileSync(DELIGHT_LOG, lines);
  }

  // Save state
  const stateDir = path.dirname(STATE_FILE);
  if (!fs.existsSync(stateDir)) fs.mkdirSync(stateDir, { recursive: true });
  state.logged_phrases = [...loggedPhrases];
  state.logged_milestones = [...loggedMilestones];
  state.last_run = now;
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
} catch {
  // Fail silently — never block the session
}

process.exit(0);
