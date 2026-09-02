/**
 * Dex Safety Guard — opencode plugin.
 *
 * Port of .claude/hooks/dex-safety-guard.sh (a Claude Code PreToolUse hook)
 * to opencode's plugin API. Same rules, same reasons:
 *
 *   - hard blocks: raw Git repair during a live vault migration, recursive
 *     delete of root/home, disk wipes, force-push to main/master, SQL DROP,
 *     `gh repo delete`, and the non-preferred scraper MCPs.
 *   - warnings: chmod 777 and kill -9 are allowed, but the tool output is
 *     prefixed with the same warning the shell hook printed.
 *
 * A block is a thrown Error from `tool.execute.before`; opencode surfaces it
 * to the model as the tool's failure, which is the closest equivalent of the
 * hook's exit 2 + reason. No dependencies, so it runs from a fresh clone.
 */
import fs from "node:fs";
import path from "node:path";

const MIGRATION_LOCK = path.join("System", ".dex", "mutation.lock");

const HARD_BLOCKS = [
  {
    re: /rm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)?(-[a-zA-Z]*r[a-zA-Z]*\s+)?(\/|~\/?\s|"\$HOME"|\/Users)/,
    reason: "Blocked: recursive delete targeting root, home, or /Users",
  },
  { re: /rm\s+-rf\s+\//, reason: "Blocked: rm -rf /" },
  { re: /(diskutil\s+eraseDisk|mkfs\s|dd\s+if=)/i, reason: "Blocked: disk wipe/format command" },
  { re: /git\s+push\s+.*--force.*\s+(main|master)/, reason: "Blocked: force push to main/master" },
  { re: /git\s+push\s+.*\s+(main|master).*--force/, reason: "Blocked: force push to main/master" },
  { re: /(DROP\s+TABLE|DROP\s+DATABASE)/i, reason: "Blocked: SQL DROP command" },
  { re: /gh\s+repo\s+delete/, reason: "Blocked: GitHub repo deletion" },
];

const WARNINGS = [
  {
    re: /chmod\s+777/,
    reason: "WARNING: chmod 777 grants full permissions to all users. Consider more restrictive permissions.",
  },
  {
    re: /kill\s+-9/,
    reason: "WARNING: kill -9 force-terminates without cleanup. Ensure this is the intended process.",
  },
];

// Raw Git writes while the migrator holds the mutation lock can turn a
// recoverable pause into a corrupted topology.
const GIT_REPAIR =
  /(^|[;&|\s])git\s+(add|am|apply|bisect\s+(good|bad|reset|start)|branch\s.*(-[dDmM]|--delete|--move)|checkout|cherry-pick|clean|commit|merge|mv|rebase|reset|restore|revert|rm|stash|switch|tag)([\s;&|]|$)/;

// opencode exposes MCP tools as `<server>_<tool>`; Claude Code as `mcp__<server>__<tool>`.
const BLOCKED_SCRAPERS = /^(mcp__)?(firecrawl|rag[-_]web[-_]browser)(__|_)/i;

function processIsRunning(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    return err && err.code === "EPERM";
  }
}

export function migrationLockLive(directory) {
  try {
    const lock = JSON.parse(fs.readFileSync(path.join(directory, MIGRATION_LOCK), "utf8"));
    return lock.kind === "migration" && processIsRunning(lock.pid);
  } catch {
    return false;
  }
}

/** Pure rule evaluation, exported so it can be unit-tested without opencode. */
export function evaluate({ tool, command, directory }) {
  const name = String(tool || "");
  if (BLOCKED_SCRAPERS.test(name)) {
    return {
      decision: "block",
      reason: `WRONG SCRAPER: Scrapling is the configured default. Use scrapling get/fetch/stealthy_fetch instead of ${name}.`,
    };
  }
  if (!command) return { decision: "allow" };

  if (GIT_REPAIR.test(command) && migrationLockLive(directory)) {
    return {
      decision: "block",
      reason:
        "A brain/vault migration is active. Do not use raw Git repair commands. Run the migrator with --resume to continue or --restore to return to the pre-split layout.",
    };
  }
  for (const rule of HARD_BLOCKS) {
    if (rule.re.test(command)) return { decision: "block", reason: rule.reason };
  }
  for (const rule of WARNINGS) {
    if (rule.re.test(command)) return { decision: "allow", reason: rule.reason };
  }
  return { decision: "allow" };
}

const isBash = (tool) => String(tool).toLowerCase() === "bash";

export const DexSafetyGuard = async ({ directory }) => {
  const pendingWarnings = new Map();
  return {
    "tool.execute.before": async (input, output) => {
      const command = isBash(input.tool) ? output?.args?.command : undefined;
      const verdict = evaluate({ tool: input.tool, command, directory });
      if (verdict.decision === "block") throw new Error(`Dex safety guard — ${verdict.reason}`);
      if (verdict.reason) pendingWarnings.set(input.callID, verdict.reason);
    },
    "tool.execute.after": async (input, output) => {
      const warning = pendingWarnings.get(input.callID);
      if (!warning) return;
      pendingWarnings.delete(input.callID);
      output.output = `[Dex safety guard] ${warning}\n\n${output.output ?? ""}`;
    },
  };
};

export default DexSafetyGuard;
