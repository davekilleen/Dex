#!/usr/bin/env node
// Unit test for .opencode/plugin/dex-safety-guard.js — run: node scripts/test-opencode-safety-guard.mjs
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const { evaluate, DexSafetyGuard } = await import(
  path.join(here, "..", ".opencode", "plugin", "dex-safety-guard.js")
);

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "dex-guard-"));
let failed = 0;
const check = (ok, label) => {
  failed += ok ? 0 : 1;
  console.log(`${ok ? "ok  " : "FAIL"} ${label}`);
};

const cases = [
  ["bash", "ls -la", "allow"],
  ["bash", "rm -rf /", "block"],
  ["bash", "rm -rf ~/ ", "block"],
  ["bash", "rm -rf ./build", "allow"],
  ["bash", "sudo dd if=/dev/zero of=/dev/disk2", "block"],
  ["bash", "git push --force origin main", "block"],
  ["bash", "git push origin feature --force", "allow"],
  ["bash", "psql -c 'drop table users'", "block"],
  ["bash", "gh repo delete foo", "block"],
  ["bash", "chmod 777 x", "allow", "WARNING"],
  ["bash", "kill -9 123", "allow", "WARNING"],
  ["firecrawl_scrape", undefined, "block"],
  ["mcp__rag-web-browser__search", undefined, "block"],
  ["work-mcp_list_tasks", undefined, "allow"],
  ["read", undefined, "allow"],
  ["bash", "git commit -m x", "allow"],
];
for (const [tool, command, want, reasonPrefix] of cases) {
  const v = evaluate({ tool, command, directory: dir });
  const ok = v.decision === want && (!reasonPrefix || (v.reason ?? "").startsWith(reasonPrefix));
  check(ok, `${tool} ${JSON.stringify(command ?? "")} -> ${v.decision}${v.reason ? ` (${v.reason.slice(0, 40)}…)` : ""}`);
}

const lock = path.join(dir, "System", ".dex", "mutation.lock");
fs.mkdirSync(path.dirname(lock), { recursive: true });
fs.writeFileSync(lock, JSON.stringify({ kind: "migration", pid: process.pid }));
check(evaluate({ tool: "bash", command: "git commit -m x", directory: dir }).decision === "block", "live migration lock blocks git commit");
check(evaluate({ tool: "bash", command: "git status", directory: dir }).decision === "allow", "live migration lock still allows git status");
fs.writeFileSync(lock, JSON.stringify({ kind: "migration", pid: 999999 }));
check(evaluate({ tool: "bash", command: "git commit -m x", directory: dir }).decision === "allow", "stale lock (dead pid) allows git commit");

const hooks = await DexSafetyGuard({ directory: dir });
let threw = false;
try {
  await hooks["tool.execute.before"]({ tool: "bash", callID: "1" }, { args: { command: "rm -rf /" } });
} catch (err) {
  threw = /Dex safety guard — Blocked:/.test(err.message);
}
check(threw, "before-hook throws with the block reason");
await hooks["tool.execute.before"]({ tool: "bash", callID: "2" }, { args: { command: "chmod 777 x" } });
const out = { title: "", output: "done", metadata: {} };
await hooks["tool.execute.after"]({ tool: "bash", callID: "2", args: {} }, out);
check(out.output.startsWith("[Dex safety guard] WARNING: chmod 777"), "after-hook prefixes the warning onto tool output");

fs.rmSync(dir, { recursive: true, force: true });
console.log(failed ? `\n${failed} failed` : "\nall passed");
process.exit(failed ? 1 : 0);
