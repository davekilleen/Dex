#!/usr/bin/env node
/**
 * Tests for the fixed delight-capture.cjs (zero dependencies, plain node).
 *
 * Proves the four failure modes from the 2026-06-10 review are fixed:
 *  1. real JSON-Lines transcripts are parsed (previously: whole-file
 *     JSON.parse threw, hook captured nothing for 10 weeks)
 *  2. content-block arrays are read (text blocks only)
 *  3. tool_result blocks never produce false delight
 *  4. milestone detection runs even with zero user messages
 * Plus: legacy single-array transcripts still work, and the hook always
 * exits 0 on garbage input.
 *
 * Run: node test-delight-capture.cjs
 */

const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const HOOK = path.join(__dirname, "delight-capture.cjs");

let failures = 0;
function check(name, condition) {
  if (condition) {
    console.log(`  ok    ${name}`);
  } else {
    failures += 1;
    console.log(`  FAIL  ${name}`);
  }
}

function runHook(vaultDir, transcriptPath, extraInput = {}) {
  const input = JSON.stringify({
    session_id: "test-session",
    transcript_path: transcriptPath,
    ...extraInput,
  });
  execFileSync("node", [HOOK], {
    input,
    env: { ...process.env, CLAUDE_PROJECT_DIR: vaultDir, DELIGHT_HOOK_ACTIVE: "" },
    timeout: 30000,
  });
}

function freshVault() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "delight-test-"));
}

function readLog(vaultDir) {
  const logPath = path.join(vaultDir, "System/Observation_Layer/delight_candidates.jsonl");
  if (!fs.existsSync(logPath)) return [];
  return fs
    .readFileSync(logPath, "utf-8")
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}

// ---------------------------------------------------------------------------
// 1. Real Claude Code JSONL transcript with content-block user message
// ---------------------------------------------------------------------------
{
  const vault = freshVault();
  const transcript = path.join(vault, "transcript.jsonl");
  const lines = [
    JSON.stringify({ type: "system", subtype: "init" }),
    JSON.stringify({
      type: "user",
      message: { role: "user", content: [{ type: "text", text: "please prep my meeting" }] },
    }),
    JSON.stringify({
      type: "assistant",
      message: { role: "assistant", content: [{ type: "text", text: "Done — brief is ready." }] },
    }),
    JSON.stringify({
      type: "user",
      message: {
        role: "user",
        content: [{ type: "text", text: "that was perfect, saved me 30 minutes" }],
      },
    }),
  ];
  fs.writeFileSync(transcript, lines.join("\n") + "\n");

  runHook(vault, transcript);
  const entries = readLog(vault);
  console.log("JSONL transcript (the 10-week dead path):");
  check("captures at least one candidate", entries.length >= 1);
  check(
    "captures the 'that was perfect' phrase",
    entries.some((e) => e.phrase && e.phrase.toLowerCase() === "that was perfect")
  );
  check(
    "captures the time-saved phrase",
    entries.some((e) => /saved me/i.test(e.phrase || ""))
  );
}

// ---------------------------------------------------------------------------
// 2. Plain-string user content in JSONL still works
// ---------------------------------------------------------------------------
{
  const vault = freshVault();
  const transcript = path.join(vault, "transcript.jsonl");
  fs.writeFileSync(
    transcript,
    JSON.stringify({ type: "user", message: { role: "user", content: "wow, nice one Dex" } }) + "\n"
  );
  runHook(vault, transcript);
  const entries = readLog(vault);
  console.log("JSONL with plain-string content:");
  check("captures from string content", entries.some((e) => /wow|nice one/i.test(e.phrase || "")));
}

// ---------------------------------------------------------------------------
// 3. Legacy single-array transcript format still works
// ---------------------------------------------------------------------------
{
  const vault = freshVault();
  const transcript = path.join(vault, "transcript.json");
  fs.writeFileSync(
    transcript,
    JSON.stringify([
      { role: "user", content: "this is great, saved me hours honestly" },
      { role: "assistant", content: "Glad it helped." },
    ])
  );
  runHook(vault, transcript);
  const entries = readLog(vault);
  console.log("Legacy array transcript:");
  check("captures from legacy format", entries.length >= 1);
}

// ---------------------------------------------------------------------------
// 4. tool_result blocks never fake delight
// ---------------------------------------------------------------------------
{
  const vault = freshVault();
  const transcript = path.join(vault, "transcript.jsonl");
  fs.writeFileSync(
    transcript,
    JSON.stringify({
      type: "user",
      message: {
        role: "user",
        content: [
          {
            type: "tool_result",
            tool_use_id: "tu_1",
            content: [{ type: "text", text: "README says: this is great, amazing, saved me hours" }],
          },
        ],
      },
    }) + "\n"
  );
  runHook(vault, transcript);
  const entries = readLog(vault);
  console.log("tool_result false-positive guard:");
  check("captures nothing from tool output", entries.length === 0);
}

// ---------------------------------------------------------------------------
// 5. Milestones fire even with zero user messages (previously unreachable)
// ---------------------------------------------------------------------------
{
  const vault = freshVault();
  fs.mkdirSync(path.join(vault, ".dex"), { recursive: true });
  fs.writeFileSync(
    path.join(vault, ".dex/workflow-model.json"),
    JSON.stringify({
      workflows: {
        "meeting-prep": { display_name: "Meeting Prep", frequency: { runs_last_30d: 7 } },
      },
    })
  );
  const transcript = path.join(vault, "transcript.jsonl");
  fs.writeFileSync(
    transcript,
    JSON.stringify({ type: "assistant", message: { role: "assistant", content: "only assistant" } }) + "\n"
  );
  runHook(vault, transcript);
  const entries = readLog(vault);
  console.log("Milestone with no user messages:");
  check(
    "milestone_reached captured",
    entries.some((e) => e.type === "milestone_reached" && e.skill_cluster === "meeting-prep")
  );
}

// ---------------------------------------------------------------------------
// 6. Garbage input never crashes (exit 0 contract)
// ---------------------------------------------------------------------------
{
  const vault = freshVault();
  let exitedZero = true;
  try {
    execFileSync("node", [HOOK], {
      input: "this is not json at all {{{",
      env: { ...process.env, CLAUDE_PROJECT_DIR: vault, DELIGHT_HOOK_ACTIVE: "" },
      timeout: 30000,
    });
  } catch {
    exitedZero = false;
  }
  console.log("Garbage stdin:");
  check("exits 0", exitedZero);
}

console.log("");
if (failures > 0) {
  console.log(`${failures} assertion(s) FAILED`);
  process.exit(1);
}
console.log("All delight-capture assertions passed.");
