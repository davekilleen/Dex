#!/usr/bin/env node
/**
 * update-obsidian-graph.cjs
 *
 * Regenerates .obsidian/graph.json colorGroups from the vault's folder structure.
 * No plugins required — writes the core graph config directly.
 *
 * Usage:
 *   node .scripts/update-obsidian-graph.cjs           # apply
 *   node .scripts/update-obsidian-graph.cjs --dry-run # preview
 *
 * Quit Obsidian before running, or reload the graph view afterwards
 * (Cmd+P → "Graph view: Open graph view").
 */

const fs = require("fs");
const path = require("path");

const VAULT_ROOT = path.resolve(__dirname, "..");
const GRAPH_JSON = path.join(VAULT_ROOT, ".obsidian", "graph.json");

// --- Palette ---------------------------------------------------------------
// Order matters: more-specific paths first. Obsidian applies first match.
// Hex colors picked for dark-mode contrast; tweak freely.
const GROUPS = [
  // Sub-folders first (more specific paths)
  { query: 'path:"05-Areas/People"',     hex: "#B57EDC" }, // soft lilac
  { query: 'path:"05-Areas/Companies"',  hex: "#7F5AF0" }, // royal violet
  { query: 'path:"05-Areas/Career"',     hex: "#C77DFF" }, // bright orchid
  { query: 'path:"06-Resources/Meeting_Cache"', hex: "#90A4AE" }, // muted steel
  { query: 'path:"00-Inbox/Meetings"',   hex: "#FFD166" }, // warm gold
  { query: 'path:"00-Inbox/Ideas"',      hex: "#FFE066" }, // pale yellow

  // Top-level numbered folders
  { query: "path:00-Inbox",         hex: "#F1C40F" }, // attention yellow
  { query: "path:01-Quarter_Goals", hex: "#5B8DEF" }, // strategic blue
  { query: "path:02-Week_Priorities", hex: "#00C2A8" }, // teal
  { query: "path:03-Tasks",         hex: "#F4845F" }, // warm orange
  { query: "path:04-Projects",      hex: "#2ECC71" }, // emerald
  { query: "path:05-Areas",         hex: "#9B59B6" }, // purple (catch-all under Areas)
  { query: "path:06-Resources",    hex: "#7F8C8D" }, // slate
  { query: "path:07-Archives",     hex: "#95856B" }, // muted sepia

  // Infra / system
  { query: "path:System",          hex: "#E91E63" }, // pink
  { query: "path:core",            hex: "#546E7A" }, // dark slate
  { query: "path:docs",            hex: "#78909C" }, // light slate
  { query: "path:plans",           hex: "#5C6BC0" }, // indigo
  { query: "path:extensions",      hex: "#455A64" }, // gunmetal
  { query: "path:packages",        hex: "#455A64" }, // gunmetal
];

// --- Helpers ---------------------------------------------------------------
function hexToRgbInt(hex) {
  const m = hex.replace("#", "").match(/^([0-9a-f]{6})$/i);
  if (!m) throw new Error(`Invalid hex: ${hex}`);
  const n = parseInt(m[1], 16);
  return n; // Obsidian stores R*65536 + G*256 + B as a single int
}

function buildColorGroups() {
  return GROUPS.map(({ query, hex }) => ({
    query,
    color: { a: 1, rgb: hexToRgbInt(hex) },
  }));
}

function main() {
  const dryRun = process.argv.includes("--dry-run");

  if (!fs.existsSync(GRAPH_JSON)) {
    console.error(`Not found: ${GRAPH_JSON}`);
    console.error("Open the Graph view in Obsidian once to generate it, then re-run.");
    process.exit(1);
  }

  const raw = fs.readFileSync(GRAPH_JSON, "utf8");
  const graph = JSON.parse(raw);
  const next = { ...graph, colorGroups: buildColorGroups() };

  if (dryRun) {
    console.log("DRY RUN — would write:");
    console.log(JSON.stringify(next, null, 2));
    return;
  }

  // Backup once per day
  const stamp = new Date().toISOString().slice(0, 10);
  const backup = `${GRAPH_JSON}.${stamp}.bak`;
  if (!fs.existsSync(backup)) fs.writeFileSync(backup, raw);

  fs.writeFileSync(GRAPH_JSON, JSON.stringify(next, null, 2));
  console.log(`Updated ${GRAPH_JSON}`);
  console.log(`Backup: ${backup}`);
  console.log(`Groups written: ${next.colorGroups.length}`);
  console.log("\nReload graph in Obsidian: Cmd+P → 'Graph view: Open graph view'");
}

main();
