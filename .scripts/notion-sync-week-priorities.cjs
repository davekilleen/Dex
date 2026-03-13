#!/usr/bin/env node

const fs = require("fs");
const path = require("path");

const VAULT_PATH = process.env.VAULT_PATH || path.resolve(__dirname, "..");
const WEEK_FILE = path.join(VAULT_PATH, "02-Week_Priorities", "Week_Priorities.md");
const STATE_FILE = path.join(VAULT_PATH, "System", ".notion-week-sync-state.json");

function loadEnv() {
  const envPath = path.join(VAULT_PATH, ".env");
  if (!fs.existsSync(envPath)) return;
  const lines = fs.readFileSync(envPath, "utf8").split("\n");
  for (const raw of lines) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const idx = line.indexOf("=");
    const key = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim();
    process.env[key] = value;
  }
}

function parseWeekInfo(markdown) {
  const weekOfMatch = markdown.match(/\*\*Week of:\*\*\s*([0-9]{4}-[0-9]{2}-[0-9]{2})/);
  const generatedMatch = markdown.match(/\*Generated:\s*([^\*]+)\*/);
  const weekOf = weekOfMatch ? weekOfMatch[1] : null;
  const generatedAt = generatedMatch ? generatedMatch[1].trim() : "";
  if (!weekOf) return null;
  return {
    weekOf,
    generatedAt,
    title: `Week Plan - ${weekOf}`,
  };
}

function chunkText(content, max = 1800) {
  const lines = content.split("\n");
  const chunks = [];
  let cur = "";
  for (const line of lines) {
    const next = cur ? `${cur}\n${line}` : line;
    if (next.length > max && cur) {
      chunks.push(cur);
      cur = line;
    } else {
      cur = next;
    }
  }
  if (cur) chunks.push(cur);
  return chunks;
}

async function notionRequest(method, endpoint, body, token) {
  const res = await fetch(`https://api.notion.com/v1/${endpoint}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      "Notion-Version": "2022-06-28",
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let json;
  try {
    json = JSON.parse(text);
  } catch {
    json = { raw: text };
  }
  if (!res.ok) {
    throw new Error(`Notion API ${res.status}: ${text}`);
  }
  return json;
}

async function getTitlePropertyName(dbId, token) {
  const db = await notionRequest("GET", `databases/${dbId}`, null, token);
  const props = db.properties || {};
  for (const [name, info] of Object.entries(props)) {
    if (info.type === "title") return name;
  }
  return "Name";
}

async function findExistingPage(dbId, titleProp, title, token) {
  const query = {
    filter: {
      property: titleProp,
      title: {
        equals: title,
      },
    },
    page_size: 1,
  };
  const data = await notionRequest("POST", `databases/${dbId}/query`, query, token);
  return data.results && data.results.length ? data.results[0] : null;
}

function loadState() {
  if (!fs.existsSync(STATE_FILE)) return {};
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE, "utf8"));
  } catch {
    return {};
  }
}

function saveState(state) {
  fs.writeFileSync(STATE_FILE, JSON.stringify(state, null, 2));
}

async function run() {
  loadEnv();
  const token = process.env.NOTION_API_TOKEN;
  const dbId = process.env.NOTION_WEEK_DB_ID;
  if (!token || token.includes("your_")) {
    throw new Error("NOTION_API_TOKEN missing or placeholder");
  }
  if (!dbId || dbId.includes("your_")) {
    throw new Error("NOTION_WEEK_DB_ID missing. Set this in .env");
  }
  if (!fs.existsSync(WEEK_FILE)) {
    throw new Error("Week priorities file not found");
  }

  const md = fs.readFileSync(WEEK_FILE, "utf8");
  const info = parseWeekInfo(md);
  if (!info) {
    throw new Error("Could not parse '**Week of:** YYYY-MM-DD' from week plan");
  }

  const state = loadState();
  const signature = `${info.weekOf}:${info.generatedAt}`;
  if (state.lastSignature === signature && state.lastPageUrl) {
    console.log(JSON.stringify({ success: true, skipped: true, url: state.lastPageUrl }));
    return;
  }

  const titleProp = await getTitlePropertyName(dbId, token);
  const existing = await findExistingPage(dbId, titleProp, info.title, token);
  if (existing) {
    await notionRequest("PATCH", `pages/${existing.id}`, { archived: true }, token);
  }

  const contentBlocks = chunkText(md).map((chunk) => ({
    object: "block",
    type: "paragraph",
    paragraph: {
      rich_text: [{ type: "text", text: { content: chunk } }],
    },
  }));

  const payload = {
    parent: { database_id: dbId },
    properties: {
      [titleProp]: {
        title: [{ type: "text", text: { content: info.title } }],
      },
    },
    children: [
      {
        object: "block",
        type: "heading_2",
        heading_2: {
          rich_text: [{ type: "text", text: { content: `Week Plan (${info.weekOf})` } }],
        },
      },
      ...contentBlocks,
    ],
  };

  // Add tags if database supports it.
  try {
    const db = await notionRequest("GET", `databases/${dbId}`, null, token);
    if (db.properties && db.properties.Tags && db.properties.Tags.type === "multi_select") {
      payload.properties.Tags = { multi_select: [{ name: "week-plan" }, { name: "dex" }] };
    }
  } catch {
    // Non-fatal: tag support is optional.
  }

  const created = await notionRequest("POST", "pages", payload, token);
  state.lastSignature = signature;
  state.lastPageId = created.id;
  state.lastPageUrl = created.url;
  state.lastSyncedAt = new Date().toISOString();
  state.weekOf = info.weekOf;
  saveState(state);

  console.log(JSON.stringify({ success: true, week_of: info.weekOf, page_id: created.id, url: created.url }));
}

run().catch((err) => {
  console.log(JSON.stringify({ success: false, error: err.message }));
  process.exit(1);
});
