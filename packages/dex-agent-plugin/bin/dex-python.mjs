#!/usr/bin/env node
import { fileURLToPath } from "node:url";
import path from "node:path";


const pluginRoot = fileURLToPath(new URL("..", import.meta.url));
const requestedMode = process.argv[2] || "mcp";
const mode = requestedMode === "--stdio" ? "mcp" : requestedMode;
if (!new Set(["mcp", "hook"]).has(mode)) {
  process.stderr.write("Usage: dex-python.mjs [mcp|hook] [arguments...]\n");
  process.exitCode = 64;
} else {
  const script = path.join(pluginRoot, mode === "hook" ? "hook.py" : "server.py");
  const forwarded = requestedMode === "--stdio" ? process.argv.slice(2) : process.argv.slice(3);
  try {
    const { runPython } = await import("./dex-launcher-lib.mjs");
    const status = await runPython({ script, args: forwarded });
    // Pre-tool hosts commonly fail open on exit 1. A checker that failed to
    // start or crashed must use their blocking exit, just like a refusal.
    process.exitCode = mode === "hook" && status !== 0 ? 2 : status;
  } catch (error) {
    process.stderr.write("Dex runtime could not reach a decision. Check the installed runtime.\n");
    process.exitCode = mode === "hook" ? 2 : 1;
  }
}
