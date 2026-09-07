// Canonical source: copy to the assembled plugin's bin/ directory.
// Capture the checker output so failures cannot leak partial/invalid decisions.
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const reason = "Dex could not check this hook request. Check the selected vault and hook runtime.";
const args = process.argv.slice(2);
const surface = args[1];
const event = args[3];
const valid = args.length === 4 && args[0] === "--surface" && args[2] === "--event"
  && ["copilot-cli", "vscode"].includes(surface)
  && ["preToolUse", "PreToolUse", "sessionStart", "SessionStart", "sessionEnd", "SessionEnd", "agentStop", "Stop"].includes(event);

function fail() {
  const decision = { permissionDecision: "deny", permissionDecisionReason: reason };
  const output = surface === "vscode"
    ? { hookSpecificOutput: { hookEventName: "PreToolUse", ...decision } } : decision;
  process.stderr.write(`${reason}\n`);
  process.stdout.write(`${JSON.stringify(output)}\n`);
  process.exitCode = 2;
}

function validOutput(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const keysAre = (object, keys) => Object.keys(object).length === keys.length
    && keys.every((key) => Object.hasOwn(object, key));
  if (Object.keys(value).length === 0) return true;
  const fields = surface === "vscode" ? value.hookSpecificOutput : value;
  if (fields?.permissionDecision === "deny" && typeof fields.permissionDecisionReason === "string"
      && fields.permissionDecisionReason.length > 0) {
    return surface === "vscode"
      ? keysAre(value, ["hookSpecificOutput"]) && keysAre(fields, ["hookEventName", "permissionDecision", "permissionDecisionReason"])
        && fields.hookEventName === "PreToolUse"
      : keysAre(value, ["permissionDecision", "permissionDecisionReason"]);
  }
  if (["sessionStart", "SessionStart"].includes(event) && typeof fields?.additionalContext === "string") {
    return surface === "vscode"
      ? keysAre(value, ["hookSpecificOutput"]) && keysAre(fields, ["hookEventName", "additionalContext"])
        && fields.hookEventName === "SessionStart"
      : keysAre(value, ["additionalContext"]);
  }
  if (!["preToolUse", "PreToolUse"].includes(event)) return false;
  return surface === "vscode" ? keysAre(value, ["systemMessage"]) && typeof value.systemMessage === "string"
    : keysAre(value, ["permissionDecisionReason"]) && typeof value.permissionDecisionReason === "string";
}

try {
  if (!valid) throw new Error("invalid invocation");
  const { pythonCandidates } = await import("./dex-launcher-lib.mjs");
  const input = readFileSync(0, "utf8");
  if (Buffer.byteLength(input) > 1024 * 1024) throw new Error("oversized input");
  const script = fileURLToPath(new URL("../runtime/core/harnesses/copilot_hooks.py", import.meta.url));
  let result;
  for (const candidate of pythonCandidates()) {
    result = spawnSync(candidate.command, [...candidate.args, script, ...args], {
      input, encoding: "utf8", windowsHide: true, timeout: 8000, maxBuffer: 1024 * 1024,
    });
    if (result.error?.code !== "ENOENT") break;
  }
  if (!result || result.error || result.status !== 0) throw new Error("checker failed");
  const output = JSON.parse(result.stdout);
  if (!validOutput(output)) throw new Error("invalid checker output");
  process.stdout.write(`${JSON.stringify(output)}\n`);
} catch {
  fail();
}
