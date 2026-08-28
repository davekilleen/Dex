#!/usr/bin/env node
/**
 * Lab-hour heartbeat. If /setup-lab goes quiet after a wait line or a
 * helper that never handed findings back, one Stop-hook nudge continues
 * the hour. Fail open everywhere else.
 */
const fs = require('fs');
const path = require('path');

function skip() {
  process.exit(0);
}

let input = {};
try {
  input = JSON.parse(fs.readFileSync(0, 'utf8') || '{}');
} catch {
  skip();
}

if (input.stop_hook_active) skip();

const vault = process.env.CLAUDE_PROJECT_DIR || process.cwd();
if (!fs.existsSync(path.join(vault, 'System', '.onboarding-lab'))) skip();

const transcriptPath = input.transcript_path;
if (!transcriptPath || !fs.existsSync(transcriptPath)) skip();

const lastText = lastAssistantText(transcriptPath);
if (!isStall(lastText)) skip();

process.stdout.write(
  JSON.stringify({
    decision: 'block',
    reason:
      'The preview hour stalled after a wait line or a helper that did not hand findings back. Read the calendar yourself now. Do not send another meetings helper. Do not say one moment, nearly there, still reading, or waiting on the meetings. Speak the next beat: the cadence, the people-pages question, or one later question if you have not asked it yet.',
  }),
);

function lastAssistantText(filePath) {
  let raw = '';
  try {
    raw = fs.readFileSync(filePath, 'utf8');
  } catch {
    return '';
  }
  let last = '';
  for (const line of raw.split('\n')) {
    if (!line.trim()) continue;
    let obj;
    try {
      obj = JSON.parse(line);
    } catch {
      continue;
    }
    if (obj.type !== 'assistant' || obj.isSidechain) continue;
    const content = obj.message && obj.message.content;
    if (!Array.isArray(content)) continue;
    const texts = content
      .filter((part) => part && part.type === 'text' && part.text)
      .map((part) => String(part.text));
    if (texts.length) last = texts.join('\n');
  }
  return last;
}

function isStall(text) {
  if (!text || !String(text).trim()) return false;
  const trimmed = String(text).trim();
  const withoutStatus = trimmed
    .replace(/\*?\([^)]*\)\*?/g, '')
    .replace(/\bone moment\b/gi, '')
    .replace(/\bnearly there\b/gi, '')
    .replace(/\bstill reading\b/gi, '')
    .replace(/\bwaiting on the meetings\b/gi, '')
    .replace(/\bgive me a moment\b/gi, '')
    .trim();
  if (/\?/.test(withoutStatus)) return false;
  if (!withoutStatus) return true;
  return (
    /^\s*\*?\([^)]+\)\**\s*$/.test(trimmed)
    || /\bone moment\b/i.test(trimmed)
    || /\bnearly there\b/i.test(trimmed)
    || /\bstill reading\b/i.test(trimmed)
    || /\bwaiting on the meetings\b/i.test(trimmed)
    || /\bgive me a moment\b/i.test(trimmed)
  );
}
