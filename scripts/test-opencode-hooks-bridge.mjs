#!/usr/bin/env node
// Test for .opencode/plugin/dex-claude-hooks-bridge.js — run from the vault root:
//   node scripts/test-opencode-hooks-bridge.mjs
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const vault = path.resolve(here, "..");
const pluginPath = path.join(vault, ".opencode", "plugin", "dex-claude-hooks-bridge.js");
const { claudeToolName, hookCommands, interpretHookResult, DexClaudeHooksBridge } = await import(pluginPath);

let failed = 0;
const check = (ok, label, detail = "") => { failed += ok ? 0 : 1; console.log(`${ok ? "ok  " : "FAIL"} ${label}${ok || !detail ? "" : `  [${detail}]`}`); };

// --- translators
check(claudeToolName("read") === "Read", "read -> Read");
check(claudeToolName("bash") === "Bash", "bash -> Bash");
check(claudeToolName("work-mcp_list_tasks") === "mcp__work-mcp__list_tasks", "MCP tool name maps to mcp__server__tool");
const hooks = { PreToolUse: [
  { matcher: "Read", hooks: [{ type: "command", command: "node inject.cjs" }] },
  { matcher: "Bash", hooks: [{ type: "command", command: "bash .claude/hooks/dex-safety-guard.sh" }, { type: "command", command: "node scope.cjs" }] },
  { matcher: "mcp__.*", hooks: [{ type: "command", command: "bash .claude/hooks/dex-safety-guard.sh" }] },
]};
check(hookCommands(hooks, "PreToolUse", "Read").map((h) => h.command).join() === "node inject.cjs", "matcher selects Read hooks only");
check(hookCommands(hooks, "PreToolUse", "Bash").map((h) => h.command).join() === "node scope.cjs", "natively-ported safety guard is skipped");
check(hookCommands(hooks, "PreToolUse", "mcp__work-mcp__x").length === 0, "mcp matcher matches, guard skipped -> nothing to run");
check(interpretHookResult({ code: 2, stdout: "", stderr: "nope" }).reason === "nope", "exit 2 blocks with stderr reason");
check(interpretHookResult({ code: 0, stdout: '{"decision":"block","reason":"r"}' }).block === true, "decision:block blocks");
check(interpretHookResult({ code: 0, stdout: '{"hookSpecificOutput":{"additionalContext":"ctx"}}' }).context === "ctx", "additionalContext becomes context");
check(interpretHookResult({ code: 0, stdout: "plain text\n" }).context === "plain text", "plain stdout becomes context");
check(interpretHookResult({ code: 1, stdout: "x" }).block === false && interpretHookResult({ code: 1, stdout: "x" }).context === "", "non-zero exit fails open");

// --- integration against the real vault (no exit/sound hooks)
process.env.DEX_OPENCODE_BRIDGE_SKIP = "SessionEnd,Stop,Notification";
const bridge = await DexClaudeHooksBridge({ directory: vault });
const sid = `bridge-test-${Date.now()}`; // soft-promise detector offers capture once per session id
await bridge.event({ event: { type: "session.created", properties: { info: { id: sid, directory: vault } } } });
const msg = { message: {}, parts: [{ type: "text", text: "I'll send Sarah the deck tomorrow" }] };
await bridge["chat.message"]({ sessionID: sid }, msg);
const text = msg.parts[0].text;
const blocks = (text.match(/<dex-context>/g) || []).length;
check(text.startsWith("I'll send Sarah the deck tomorrow"), "user's own prompt text is preserved");
check(text.includes("Dex Session Context"), "SessionStart context injected on first message", text.slice(0, 120));
check(blocks >= 2, "UserPromptSubmit hook (soft-promise detector) added context", `blocks=${blocks}`);
check(msg.parts.length === 1, "no new parts were invented");
const msg2 = { message: {}, parts: [{ type: "text", text: "hello again" }] };
await bridge["chat.message"]({ sessionID: sid }, msg2);
check(!msg2.parts[0].text.includes("Dex Session Context"), "SessionStart context delivered only once per session");
let threw = null;
try { await bridge["tool.execute.before"]({ tool: "read", sessionID: sid, callID: "c1" }, { args: { filePath: path.join(vault, "README.md") } }); } catch (e) { threw = e; }
check(threw === null, "Read hooks run without blocking", threw?.message);
try { threw = null; await bridge["tool.execute.before"]({ tool: "bash", sessionID: sid, callID: "c2" }, { args: { command: "claude mcp add foo -- npx foo" } }); } catch (e) { threw = e; }
console.log(`info ensure-mcp-user-scope on 'claude mcp add' without --scope: ${threw ? "blocked: " + threw.message.slice(0, 80) : "allowed"}`);

// --- SessionEnd on process exit, with a stub settings file so nothing touches the real vault
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "dex-bridge-"));
const marker = path.join(tmp, "session-end-ran");
fs.writeFileSync(path.join(tmp, "settings.json"), JSON.stringify({ hooks: { SessionEnd: [{ hooks: [{ type: "command", command: `cat > "${marker}"` }] }] } }));
const child = spawnSync(process.execPath, ["--input-type=module", "-e",
  `const { DexClaudeHooksBridge } = await import(${JSON.stringify(pluginPath)}); await DexClaudeHooksBridge({ directory: ${JSON.stringify(tmp)} });`],
  { env: { ...process.env, DEX_OPENCODE_BRIDGE_SETTINGS: path.join(tmp, "settings.json"), DEX_OPENCODE_BRIDGE_SKIP: "" }, encoding: "utf8" });
const ran = fs.existsSync(marker);
check(ran, "SessionEnd hooks run on process exit", child.stderr.slice(0, 200));
if (ran) check(JSON.parse(fs.readFileSync(marker, "utf8")).hook_event_name === "SessionEnd", "SessionEnd hook received the Claude-shaped payload");
fs.rmSync(tmp, { recursive: true, force: true });

console.log(failed ? `\n${failed} failed` : "\nall passed");
process.exit(failed ? 1 : 0);
