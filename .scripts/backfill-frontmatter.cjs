#!/usr/bin/env node
/**
 * backfill-frontmatter.cjs
 *
 * One-pass backfill of YAML frontmatter into People, Companies, Projects pages
 * to match the schemas defined in CLAUDE.md's USER_EXTENSIONS block.
 *
 * Strategy:
 *   - Read existing frontmatter (preserve all keys).
 *   - Infer missing fields from body content using conservative rules.
 *   - Add empty placeholders for any schema keys still missing.
 *   - Write back; backup originals to .scripts/backfill-backup-<ts>/ mirror tree.
 *
 * Usage:
 *   node .scripts/backfill-frontmatter.cjs --dry-run   # preview (default if no flag)
 *   node .scripts/backfill-frontmatter.cjs --apply     # actually write
 */

const fs = require("fs");
const path = require("path");

const VAULT = path.resolve(__dirname, "..");
const TIMESTAMP = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
const BACKUP_DIR = path.join(VAULT, ".scripts", `backfill-backup-${TIMESTAMP}`);

const PILLARS = new Set(["al_liwan_labs", "change_knowledge_mgmt", "digital_asset_strategy"]);

const TARGETS = [
  { folder: "05-Areas/People/Internal", type: "person" },
  { folder: "05-Areas/People/External", type: "person" },
  { folder: "05-Areas/Companies",       type: "company" },
  { folder: "04-Projects",               type: "project" },
];

const SCHEMAS = {
  person:  ["name", "company", "role", "last_met", "linkedin"],
  company: ["name", "domain", "stage"],
  project: ["project", "status", "pillar", "owner", "created"],
};

const SKIP_NAMES = new Set(["README.md", "Untitled.md", "_index.md"]);

// --- Build company index for cross-reference --------------------------------
function buildCompanyIndex() {
  const dir = path.join(VAULT, "05-Areas/Companies");
  if (!fs.existsSync(dir)) return new Set();
  return new Set(
    fs.readdirSync(dir)
      .filter(f => f.endsWith(".md") && !SKIP_NAMES.has(f))
      .map(f => f.replace(/\.md$/, ""))
  );
}
const COMPANY_NAMES = buildCompanyIndex();

// --- YAML parsing (flat key:value only) ------------------------------------
function parseFrontmatter(content) {
  const m = content.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
  if (!m) return { fm: {}, body: content, hasFM: false };
  const fm = {};
  for (const line of m[1].split(/\r?\n/)) {
    const kv = line.match(/^([a-zA-Z_][\w-]*)\s*:\s*(.*)$/);
    if (kv) {
      let v = kv[2].trim();
      if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
        v = v.slice(1, -1);
      }
      fm[kv[1]] = v;
    }
  }
  return { fm, body: content.slice(m[0].length), hasFM: true };
}

function serializeFrontmatter(fm, schemaKeys) {
  const lines = ["---"];
  const seen = new Set();
  for (const key of schemaKeys) {
    seen.add(key);
    const val = fm[key];
    lines.push(formatKV(key, val));
  }
  for (const key of Object.keys(fm)) {
    if (!seen.has(key)) lines.push(formatKV(key, fm[key]));
  }
  lines.push("---");
  return lines.join("\n") + "\n";
}

function formatKV(key, val) {
  if (val === undefined || val === null || val === "") return `${key}:`;
  const s = String(val);
  if (/^[\[\{]/.test(s)) return `${key}: ${s}`;
  if (/[:#"'`\n]/.test(s)) return `${key}: "${s.replace(/"/g, '\\"')}"`;
  return `${key}: ${s}`;
}

// --- Inference rules -------------------------------------------------------
function nameFromFilename(filename) {
  return filename.replace(/\.md$/, "").replace(/_/g, " ");
}

function inferLastMet(body) {
  const meetingLinks = body.match(/\[\[(20\d{2}-\d{2}-\d{2})[-\w_|.\]]/g) || [];
  const dates = meetingLinks
    .map(m => m.match(/(20\d{2}-\d{2}-\d{2})/)[1])
    .concat((body.match(/\b(20\d{2}-\d{2}-\d{2})\b/g) || []));
  if (!dates.length) return "";
  return dates.sort().reverse()[0];
}

function inferCompany(body, ownStem) {
  const matches = body.matchAll(/\[\[([\w._-]+?)(?:\|[^\]]+)?\]\]/g);
  const counts = new Map();
  for (const m of matches) {
    const stem = m[1];
    if (stem === ownStem) continue;
    if (COMPANY_NAMES.has(stem)) {
      counts.set(stem, (counts.get(stem) || 0) + 1);
    }
  }
  if (!counts.size) return "";
  const top = [...counts.entries()].sort((a, b) => b[1] - a[1])[0][0];
  return `[[${top}]]`;
}

function inferLinkedIn(body) {
  const m = body.match(/https?:\/\/(?:[\w-]+\.)?linkedin\.com\/[\w\-/?=&%.]+/i);
  return m ? m[0] : "";
}

function inferDomain(body) {
  const urlMatch = body.match(/https?:\/\/(?:www\.)?([\w-]+\.[\w.-]+)/);
  if (urlMatch && !urlMatch[1].endsWith(".md")) return urlMatch[1];
  const emailMatch = body.match(/@([\w-]+\.[\w.-]+)/);
  if (emailMatch) return emailMatch[1];
  return "";
}

function inferStatus(body) {
  const m = body.match(/\*\*Status:?\*\*\s*([^\n*]+)/i)
        || body.match(/^Status:\s*([^\n]+)/m);
  if (!m) return "";
  const s = m[1].toLowerCase().trim();
  if (/active|in[- ]?progress|ongoing|live/.test(s)) return "active";
  if (/paus|hold|wait/.test(s))                       return "paused";
  if (/done|complete|shipped|delivered/.test(s))      return "done";
  if (/archiv|killed|cancelled|canceled/.test(s))     return "archived";
  return s.split(/\s+/)[0];
}

function inferPillar(body) {
  const m = body.match(/\*\*Pillar:?\*\*\s*([^\n*]+)/i)
        || body.match(/^pillar:\s*([^\n]+)/im);
  if (!m) return "";
  const raw = m[1].toLowerCase().replace(/[^\w]+/g, "_").replace(/^_|_$/g, "");
  if (PILLARS.has(raw)) return raw;
  if (/labs|innovation/.test(raw))         return "al_liwan_labs";
  if (/change|knowledge|adoption/.test(raw)) return "change_knowledge_mgmt";
  if (/digital|asset|gfo|maritime|sri/.test(raw)) return "digital_asset_strategy";
  return raw;
}

function inferCreated(filepath, body) {
  const m = body.match(/\bcreated:\s*(20\d{2}-\d{2}-\d{2})/i);
  if (m) return m[1];
  try {
    const st = fs.statSync(filepath);
    return new Date(st.birthtime || st.mtime).toISOString().slice(0, 10);
  } catch { return ""; }
}

// --- Per-file processor ----------------------------------------------------
function processFile(filepath, type) {
  const filename = path.basename(filepath);
  if (SKIP_NAMES.has(filename)) return { skipped: "name" };

  const raw = fs.readFileSync(filepath, "utf8");
  const { fm, body } = parseFrontmatter(raw);
  const stem = filename.replace(/\.md$/, "");
  const updated = { ...fm };
  const added = [];
  const filled = [];

  const setIfMissing = (key, value) => {
    if ((!updated[key] || updated[key] === "Unknown") && value) {
      updated[key] = value;
      filled.push(key);
    } else if (!(key in updated)) {
      updated[key] = "";
      added.push(key);
    }
  };

  if (type === "person") {
    if (!updated.name || updated.name === "Unknown") {
      updated.name = nameFromFilename(filename); filled.push("name");
    }
    setIfMissing("last_met", inferLastMet(body));
    setIfMissing("company",  inferCompany(body, stem));
    setIfMissing("linkedin", inferLinkedIn(body));
    if (!("role" in updated))     { updated.role = ""; added.push("role"); }
  } else if (type === "company") {
    if (!updated.name) { updated.name = nameFromFilename(filename); filled.push("name"); }
    setIfMissing("domain", inferDomain(body));
    if (!("stage" in updated)) { updated.stage = ""; added.push("stage"); }
  } else if (type === "project") {
    if (!updated.project) { updated.project = nameFromFilename(filename); filled.push("project"); }
    setIfMissing("status",  inferStatus(body));
    setIfMissing("pillar",  inferPillar(body));
    if (!updated.owner)  { updated.owner = "David Orban"; filled.push("owner"); }
    setIfMissing("created", inferCreated(filepath, body));
  }

  for (const k of SCHEMAS[type]) {
    if (updated[k] === "Unknown" || updated[k] === "unknown") updated[k] = "";
  }
  const newFM = serializeFrontmatter(updated, SCHEMAS[type]);
  const newBody = body.replace(/^\r?\n+/, "");
  const newContent = newFM + (newBody.length ? "\n" + newBody : "");

  if (newContent === raw) return { unchanged: true };

  return { raw, newContent, added, filled, filepath };
}

// --- Walk + main ----------------------------------------------------------
function walk(folder, type) {
  const dir = path.join(VAULT, folder);
  if (!fs.existsSync(dir)) return [];
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...walk(path.relative(VAULT, full), type));
    } else if (entry.name.endsWith(".md")) {
      out.push({ path: full, type });
    }
  }
  return out;
}

function backup(filepath, raw) {
  const rel = path.relative(VAULT, filepath);
  const dest = path.join(BACKUP_DIR, rel);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.writeFileSync(dest, raw);
}

function main() {
  const apply = process.argv.includes("--apply");
  const verbose = process.argv.includes("--verbose");
  const stats = { processed: 0, modified: 0, unchanged: 0, skipped: 0, byType: {} };
  const samples = [];

  for (const target of TARGETS) {
    const files = walk(target.folder, target.type);
    stats.byType[target.type] = stats.byType[target.type] || { total: 0, modified: 0, filledLastMet: 0, filledCompany: 0, filledLinkedIn: 0, filledStatus: 0, filledPillar: 0 };
    stats.byType[target.type].total += files.length;

    for (const file of files) {
      stats.processed++;
      const result = processFile(file.path, file.type);
      if (result.skipped) { stats.skipped++; continue; }
      if (result.unchanged) { stats.unchanged++; continue; }
      stats.modified++;
      stats.byType[file.type].modified++;
      for (const k of result.filled) {
        const counterKey = `filled${k.charAt(0).toUpperCase() + k.slice(1).replace(/_(.)/g, (_, c) => c.toUpperCase())}`;
        if (counterKey in stats.byType[file.type]) stats.byType[file.type][counterKey]++;
      }
      if (samples.length < 5) {
        samples.push({
          file: path.relative(VAULT, file.path),
          filled: result.filled,
          added: result.added,
        });
      }
      if (apply) {
        backup(file.path, result.raw);
        fs.writeFileSync(file.path, result.newContent);
      } else if (verbose) {
        console.log("---", path.relative(VAULT, file.path));
        console.log(result.newContent.split("\n").slice(0, 10).join("\n"));
      }
    }
  }

  console.log(apply ? "\nAPPLIED" : "\nDRY RUN — no files written (use --apply)");
  console.log("Processed:", stats.processed);
  console.log("Modified: ", stats.modified);
  console.log("Unchanged:", stats.unchanged);
  console.log("Skipped:  ", stats.skipped);
  console.log("\nBy type:");
  for (const [k, v] of Object.entries(stats.byType)) {
    console.log(`  ${k.padEnd(8)} total ${v.total}, modified ${v.modified}`,
      Object.entries(v)
        .filter(([k2, v2]) => k2.startsWith("filled") && v2 > 0)
        .map(([k2, v2]) => `${k2.replace("filled", "+")}=${v2}`)
        .join(" "));
  }
  if (samples.length) {
    console.log("\nFirst 5 samples:");
    for (const s of samples) {
      console.log(`  ${s.file}`);
      console.log(`    filled: ${s.filled.join(", ") || "(none)"}`);
      console.log(`    added empty: ${s.added.join(", ") || "(none)"}`);
    }
  }
  if (apply) console.log(`\nBackup: ${BACKUP_DIR}`);
}

main();
