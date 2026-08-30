/**
 * Dex Claude-hooks bridge — opencode plugin.
 *
 * Runs the repository-wide Claude Code hooks wired in `.claude/settings.json`
 * from opencode, so a vault gets the same lifecycle behaviour in both
 * harnesses without a second copy of the wiring. `.claude/settings.json`
 * stays the source of truth; this file only translates events:
 *
 *   Claude Code event      opencode hook                what happens
 *   SessionStart           event session.created        run hooks, inject stdout as context
 *                          (+ first chat.message)         on the session's first message
 *   UserPromptSubmit       chat.message                 run hooks with {prompt}, append context
 *   PreToolUse <matcher>   tool.execute.before/after    run matching hooks; exit 2 / decision
 *                                                         "block" throws, context is appended
 *                                                         to the tool output
 *   Stop                   event session.idle           run hooks
 *   Notification           permission.ask               run hooks whose matcher includes
 *                                                         permission_prompt
 *   SessionEnd             process exit                 run hooks synchronously (best effort:
 *                                                         opencode has no session-end event)
 *
 * Hooks receive the Claude Code stdin payload shape ({session_id, cwd,
 * hook_event_name, prompt | tool_name + tool_input, ...}) with
 * CLAUDE_PROJECT_DIR set, and their stdout is read the way Claude Code reads
 * it: plain text or {hookSpecificOutput: {additionalContext}} becomes
 * context, {decision: "block"} or exit code 2 blocks. Any other failure
 * fails open, as the hooks themselves are designed to.
 *
 * `dex-safety-guard.sh` is skipped because `dex-safety-guard.js` ports it
 * natively. Set DEX_OPENCODE_BRIDGE_SKIP to a comma-separated list of Claude
 * event names (e.g. "SessionEnd,Stop") to disable groups, and
 * DEX_OPENCODE_BRIDGE_SETTINGS to point at a different settings file.
 */
import fs from "node:fs";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";

const HOOK_TIMEOUT_MS = 60_000;
const EXIT_HOOK_TIMEOUT_MS = 30_000;
const NATIVELY_PORTED = [/dex-safety-guard\.sh/];

// opencode builtin tool ids -> Claude Code tool names (what hook matchers expect).
const TOOL_NAMES = {
  bash: "Bash", read: "Read", write: "Write", edit: "Edit", glob: "Glob", grep: "Grep",
  webfetch: "WebFetch", websearch: "WebSearch", task: "Task", todowrite: "TodoWrite",
  todoread: "TodoRead", list: "LS", patch: "Edit", multiedit: "MultiEdit",
};

export function claudeToolName(tool) {
  const key = String(tool || "").toLowerCase();
  if (TOOL_NAMES[key]) return TOOL_NAMES[key];
  // MCP tools are `<server>_<tool>` in opencode and `mcp__<server>__<tool>` in Claude Code.
  return `mcp__${String(tool).replace(/_/, "__")}`;
}

export function claudeToolInput(tool, args) {
  const a = args || {};
  switch (String(tool).toLowerCase()) {
    case "bash": return { command: a.command, description: a.description };
    case "read": return { file_path: a.filePath, offset: a.offset, limit: a.limit };
    case "write": return { file_path: a.filePath, content: a.content };
    case "edit": case "patch": case "multiedit": return { file_path: a.filePath, ...a };
    default: return a;
  }
}

export function loadHooks(settingsPath) {
  try {
    const settings = JSON.parse(fs.readFileSync(settingsPath, "utf8"));
    return settings.hooks || {};
  } catch {
    return {};
  }
}

/** Flatten one event's config into [{matcher, command}] for commands this bridge should run. */
export function hookCommands(hooks, eventName, subject) {
  const groups = Array.isArray(hooks[eventName]) ? hooks[eventName] : [];
  const out = [];
  for (const group of groups) {
    if (group.matcher && subject !== undefined) {
      let re;
      try { re = new RegExp(`^(?:${group.matcher})$`); } catch { continue; }
      if (!re.test(subject)) continue;
    }
    for (const hook of group.hooks || []) {
      if (hook.type !== "command" || !hook.command) continue;
      if (NATIVELY_PORTED.some((re) => re.test(hook.command))) continue;
      out.push({ matcher: group.matcher, command: hook.command });
    }
  }
  return out;
}

/** Interpret a hook's exit code + stdout the way Claude Code does. */
export function interpretHookResult({ code, stdout, stderr }) {
  const text = (stdout || "").trim();
  let parsed;
  if (text.startsWith("{")) {
    try { parsed = JSON.parse(text); } catch { parsed = undefined; }
  }
  if (code === 2) {
    return { block: true, reason: parsed?.reason || (stderr || "").trim() || text || "blocked by hook" };
  }
  if (code !== 0) return { block: false, context: "" }; // fail open
  if (parsed) {
    if (parsed.decision === "block") return { block: true, reason: parsed.reason || "blocked by hook" };
    const ctx = [parsed.hookSpecificOutput?.additionalContext, parsed.systemMessage]
      .filter((s) => typeof s === "string" && s.trim()).join("\n\n");
    return { block: false, context: ctx };
  }
  return { block: false, context: text };
}

function runHook(command, payload, env, cwd) {
  return new Promise((resolve) => {
    const child = spawn("sh", ["-c", command], { cwd, env, stdio: ["pipe", "pipe", "pipe"] });
    let stdout = "", stderr = "";
    const timer = setTimeout(() => child.kill("SIGKILL"), HOOK_TIMEOUT_MS);
    child.stdout.on("data", (d) => { stdout += d; });
    child.stderr.on("data", (d) => { stderr += d; });
    child.on("error", () => { clearTimeout(timer); resolve({ code: 1, stdout, stderr }); });
    child.on("close", (code) => { clearTimeout(timer); resolve({ code: code ?? 1, stdout, stderr }); });
    child.stdin.on("error", () => {});
    child.stdin.end(JSON.stringify(payload));
  });
}

export const DexClaudeHooksBridge = async ({ directory }) => {
  const settingsPath = process.env.DEX_OPENCODE_BRIDGE_SETTINGS
    || path.join(directory, ".claude", "settings.json");
  const hooks = loadHooks(settingsPath);
  const skip = new Set((process.env.DEX_OPENCODE_BRIDGE_SKIP || "").split(",").map((s) => s.trim()).filter(Boolean));
  const env = { ...process.env, CLAUDE_PROJECT_DIR: directory, transcript_path: "" };
  const base = (sessionID, eventName) => ({
    session_id: sessionID || "opencode",
    transcript_path: "",
    cwd: directory,
    hook_event_name: eventName,
  });

  async function runEvent(eventName, payload, subject) {
    if (skip.has(eventName)) return [];
    const cmds = hookCommands(hooks, eventName, subject);
    return Promise.all(cmds.map(async ({ command }) => {
      const result = await runHook(command, payload, env, directory);
      return { command, ...interpretHookResult(result) };
    }));
  }
  const contextOf = (results) => results.map((r) => r.context).filter(Boolean).join("\n\n");
  const firstBlock = (results) => results.find((r) => r.block);

  const sessionStart = new Map(); // sessionID -> Promise<string> (context, consumed on first message)
  const startSession = (sessionID) => {
    if (!sessionStart.has(sessionID)) {
      sessionStart.set(sessionID, runEvent("SessionStart", { ...base(sessionID, "SessionStart"), source: "startup" }).then(contextOf));
    }
    return sessionStart.get(sessionID);
  };
  const delivered = new Set();
  const pendingToolContext = new Map(); // callID -> context

  let exitRan = false;
  const runSessionEnd = () => {
    if (exitRan || skip.has("SessionEnd")) return;
    exitRan = true;
    for (const { command } of hookCommands(hooks, "SessionEnd")) {
      try {
        spawnSync("sh", ["-c", command], {
          cwd: directory, env, timeout: EXIT_HOOK_TIMEOUT_MS,
          input: JSON.stringify({ ...base("opencode", "SessionEnd"), reason: "exit" }), stdio: ["pipe", "ignore", "ignore"],
        });
      } catch { /* fail open */ }
    }
  };
  process.once("beforeExit", runSessionEnd);
  process.once("exit", runSessionEnd);

  return {
    event: async ({ event }) => {
      if (event.type === "session.created" && !event.properties?.info?.parentID) {
        startSession(event.properties.info.id);
      } else if (event.type === "session.idle") {
        await runEvent("Stop", { ...base(event.properties?.sessionID, "Stop"), stop_hook_active: false });
      }
    },

    "chat.message": async (input, output) => {
      const sessionID = input.sessionID;
      const extra = [];
      if (!delivered.has(sessionID)) {
        delivered.add(sessionID);
        const ctx = await startSession(sessionID);
        if (ctx) extra.push(ctx);
      }
      const prompt = (output.parts || []).filter((p) => p.type === "text").map((p) => p.text).join("\n");
      const results = await runEvent("UserPromptSubmit", { ...base(sessionID, "UserPromptSubmit"), prompt });
      const ctx = contextOf(results);
      if (ctx) extra.push(ctx);
      if (!extra.length) return;
      // Parts here are persisted records with ids, so append to the user's own
      // text part rather than inventing a new one (mirrors Claude Code's
      // additionalContext, which rides along with the prompt).
      const target = (output.parts || []).find((p) => p.type === "text");
      const block = extra.map((t) => `<dex-context>\n${t}\n</dex-context>`).join("\n\n");
      if (target) target.text = `${target.text}\n\n${block}`;
    },

    "tool.execute.before": async (input, output) => {
      const name = claudeToolName(input.tool);
      const results = await runEvent("PreToolUse", {
        ...base(input.sessionID, "PreToolUse"), tool_name: name, tool_input: claudeToolInput(input.tool, output.args),
      }, name);
      const blocked = firstBlock(results);
      if (blocked) throw new Error(`Dex hook (${path.basename(blocked.command.split(" ").pop() || "")}) — ${blocked.reason}`);
      const ctx = contextOf(results);
      if (ctx) pendingToolContext.set(input.callID, ctx);
    },

    "tool.execute.after": async (input, output) => {
      const ctx = pendingToolContext.get(input.callID);
      if (!ctx) return;
      pendingToolContext.delete(input.callID);
      output.output = `${output.output ?? ""}\n\n<dex-context>\n${ctx}\n</dex-context>`;
    },

    "permission.ask": async (input) => {
      await runEvent("Notification", { ...base(input.sessionID, "Notification"), notification_type: "permission_prompt", message: input.title }, "permission_prompt");
    },
  };
};

export default DexClaudeHooksBridge;
