#!/usr/bin/env node
import { fileURLToPath } from "node:url";
import path from "node:path";

import { runPython } from "./dex-launcher-lib.mjs";


const pluginRoot = fileURLToPath(new URL("..", import.meta.url));
const requestedMode = process.argv[2] || "mcp";
const mode = requestedMode === "--stdio" ? "mcp" : requestedMode;
if (!new Set(["mcp", "hook"]).has(mode)) {
  process.stderr.write("Usage: dex-python.mjs [mcp|hook] [arguments...]\n");
  process.exitCode = 64;
} else {
  const script = path.join(pluginRoot, mode === "hook" ? "hook.py" : "server.py");
  const forwarded = requestedMode === "--stdio" ? process.argv.slice(2) : process.argv.slice(3);
  process.exitCode = await runPython({ script, args: forwarded });
}
