const { ItemView, Plugin } = require("obsidian");

const VIEW_TYPE = "dex-readonly-brief";
const PILLAR_LIMIT = 5;
const URGENT_LIMIT = 3;
const GOAL_LIMIT = 10;
const DAILY_PLAN_LIMIT = 24;
const EMPTY_SENTENCE = "No recorded decision in your files matched that topic.";
const LATELY_EMPTY = "No recorded decision in your files lately.";
const PERSON_EMPTY = "No person in your files matched that name.";
const TODAY_PEOPLE_HEADING = "Who today's plan names";
const NOBODY_NAMED = "Today's plan does not name anyone in your files.";
const NO_PLAN = "There is no plan for today in your files.";
const LATELY_LIMIT = 3;
const NO_DATE = "no date in that note";
const DATE_STAMP = /^\d{4}-\d{2}-\d{2}$/;
const USER_TREES = [
  "00-Inbox",
  "04-Projects",
  "05-Areas",
  "06-Resources",
  "07-Archives",
];
const PEOPLE_TREES = [
  "05-Areas/People/Internal",
  "05-Areas/People/External",
  "05-Areas/People/CPO_Network",
];
const DECISION_HEADING = /^##\s+(?:Key\s+)?Decisions\s*$/i;
const DECISION_LOG_HEADING = /^##\s+(\d{4}-\d{2}-\d{2})\s+[—–-]\s+(.+)$/;
const DECISION_FIELD = /^\*\*Decision:\*\*\s*(.+?)\s*$/i;
const BULLET = /^[-*]\s+(?:\[[ xX]\]\s+)?(.+)$/;
const DATE_IN_NAME = /^(\d{4}-\d{2}-\d{2})/;
const FRONTMATTER_DATE = /^date:\s*['"]?(\d{4}-\d{2}-\d{2})/im;
const PERSON_FIELD = /^(?:\|\s*(?:\*\*)?)?(name|role|company)(?:\*\*)?\s*(?:\||:)\s*(.*?)(?:\s*\|)?$/i;
const PERSON_HEADING = /^#\s+(.+)$/;
const WIKI_LINK = /\[\[([^\]|#]+)(?:\|[^\]]*)?\]\]/g;
const BLANK_VALUES = new Set(["", "null", "none", "~"]);

function todayLabel(now) {
  const stamp = now instanceof Date ? now : new Date();
  const weekday = stamp.toLocaleDateString("en-US", { weekday: "long" });
  const month = stamp.toLocaleDateString("en-US", { month: "long" });
  const day = String(stamp.getDate()).padStart(2, "0");
  const year = stamp.getFullYear();
  return `${weekday}, ${month} ${day}, ${year}`;
}

function todayStamp(now) {
  const stamp = now instanceof Date ? now : new Date();
  const month = String(stamp.getMonth() + 1).padStart(2, "0");
  const day = String(stamp.getDate()).padStart(2, "0");
  return `${stamp.getFullYear()}-${month}-${day}`;
}

async function readVaultText(app, relativePath) {
  const file = app.vault.getAbstractFileByPath(relativePath);
  if (!file || !file.extension) {
    return "";
  }
  try {
    return await app.vault.cachedRead(file);
  } catch (_error) {
    return "";
  }
}

function loadPillars(text) {
  const pillars = [];
  const lines = String(text || "").split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    if (!/^\s*- id:\s*/.test(lines[index])) {
      continue;
    }
    let name = "";
    let description = "";
    for (let offset = 1; offset <= 4 && index + offset < lines.length; offset += 1) {
      const line = lines[index + offset];
      const nameMatch = line.match(/^\s*name:\s*"?([^"]*)"?\s*$/);
      const descriptionMatch = line.match(/^\s*description:\s*"?([^"]*)"?\s*$/);
      if (nameMatch) {
        name = nameMatch[1].trim();
      }
      if (descriptionMatch) {
        description = descriptionMatch[1].trim();
      }
    }
    if (name) {
      pillars.push({ name, description });
    }
    if (pillars.length >= PILLAR_LIMIT) {
      break;
    }
  }
  return pillars;
}

function loadQuarterGoals(text) {
  const goals = [];
  const lines = String(text || "").split(/\r?\n/);
  for (let index = 0; index < lines.length; index += 1) {
    if (!/^###\s+[0-9]+\.\s+/.test(lines[index])) {
      continue;
    }
    const title = lines[index].replace(/^###\s+/, "").trim();
    if (!title || title.includes("[Goal 1 Title]")) {
      continue;
    }
    let progress = "";
    for (let offset = 1; offset <= 6 && index + offset < lines.length; offset += 1) {
      const line = lines[index + offset];
      if (/^###\s+/.test(line)) {
        break;
      }
      const match = line.match(/^\*\*Progress:\*\*\s*(.*)$/);
      if (match) {
        progress = match[1].trim();
        break;
      }
    }
    goals.push({ title, progress });
    if (goals.length >= GOAL_LIMIT) {
      break;
    }
  }
  return goals;
}

function loadWeekPriorities(text) {
  const lines = String(text || "").split(/\r?\n/);
  const priorities = [];
  let inWeek = false;
  for (const line of lines) {
    if (/^##\s+(?:🎯\s+)?(?:Top 3 )?This Week\s*$/.test(line)) {
      inWeek = true;
      continue;
    }
    if (inWeek && /^##\s+/.test(line)) {
      break;
    }
    if (inWeek && line.trim()) {
      priorities.push(line.trim());
    }
  }
  return priorities;
}

function loadUrgentTasks(text) {
  const urgent = [];
  for (const line of String(text || "").split(/\r?\n/)) {
    if (!/^- \[ \] /.test(line) || !/p0|urgent|today|overdue/i.test(line)) {
      continue;
    }
    urgent.push(line.trim());
    if (urgent.length >= URGENT_LIMIT) {
      break;
    }
  }
  return urgent;
}

function loadDailyPlan(text) {
  const lines = [];
  for (const line of String(text || "").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed) {
      continue;
    }
    lines.push(trimmed);
    if (lines.length >= DAILY_PLAN_LIMIT) {
      break;
    }
  }
  return lines;
}

async function buildTodayBrief(app, now) {
  const pillarsText = await readVaultText(app, "System/pillars.yaml");
  const goalsText = await readVaultText(app, "01-Quarter_Goals/Quarter_Goals.md");
  const weekText = await readVaultText(app, "02-Week_Priorities/Week_Priorities.md");
  const tasksText = await readVaultText(app, "03-Tasks/Tasks.md");
  const dailyText = await readVaultText(app, `00-Inbox/Daily_Plans/${todayStamp(now)}.md`);
  return {
    today: todayLabel(now),
    pillars: loadPillars(pillarsText),
    quarter_goals: loadQuarterGoals(goalsText),
    week_priorities: loadWeekPriorities(weekText),
    urgent_tasks: loadUrgentTasks(tasksText),
    daily_plan: loadDailyPlan(dailyText),
  };
}

function appendSection(root, title, items, formatter) {
  const heading = root.createEl("h2", { text: title });
  heading.addClass("dex-readonly-heading");
  if (!items.length) {
    root.createEl("p", {
      text: "Nothing listed here yet.",
      cls: "dex-readonly-empty",
    });
    return;
  }
  const list = root.createEl("ul");
  for (const item of items) {
    list.createEl("li", { text: formatter(item) });
  }
}

function renderBrief(root, brief) {
  root.empty();
  root.addClass("dex-readonly-panel");
  root.createEl("h1", { text: "Today" });
  root.createEl("p", { text: brief.today || "", cls: "dex-readonly-date" });
  appendSection(root, "Daily plan", brief.daily_plan || [], (item) => item);
  appendSection(root, "Weekly priorities", brief.week_priorities || [], (item) => item);
  appendSection(root, "Urgent tasks", brief.urgent_tasks || [], (item) => item);
  appendSection(root, "Quarter goals", brief.quarter_goals || [], (item) => {
    return item.progress ? `${item.title} — ${item.progress}` : item.title;
  });
  appendSection(root, "Pillars", brief.pillars || [], (item) => {
    return item.description ? `${item.name} — ${item.description}` : item.name;
  });
}

function noteName(relativePath) {
  const base = String(relativePath || "").split("/").pop() || "";
  return base.replace(/\.md$/i, "");
}

function fileDate(relativePath, text) {
  const named = noteName(relativePath).match(DATE_IN_NAME);
  if (named) {
    return named[1];
  }
  const frontmatter = String(text || "").match(FRONTMATTER_DATE);
  if (frontmatter) {
    return frontmatter[1];
  }
  return "";
}

function cleanWords(raw) {
  return String(raw || "")
    .replace(/\[\[[^\]|]*\|([^\]]*)\]\]/g, "$1")
    .replace(/\[\[([^\]]*)\]\]/g, "$1")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .trim();
}

function collectDecisionRecords(text, relativePath) {
  const note = noteName(relativePath);
  const fromFile = fileDate(relativePath, text);
  const records = [];
  let inDecisions = false;
  let headingDate = "";
  let headingTitle = "";
  for (const line of String(text || "").split(/\r?\n/)) {
    const log = line.match(DECISION_LOG_HEADING);
    if (log) {
      inDecisions = false;
      headingDate = log[1];
      headingTitle = String(log[2] || "").trim();
      continue;
    }
    if (DECISION_HEADING.test(line)) {
      inDecisions = true;
      headingDate = "";
      headingTitle = "";
      continue;
    }
    if (/^##\s+/.test(line)) {
      inDecisions = false;
      headingDate = "";
      headingTitle = "";
      continue;
    }
    const field = line.match(DECISION_FIELD);
    if (field) {
      const words = cleanWords(field[1]);
      if (words) {
        records.push({
          words,
          note,
          date: headingDate || fromFile || NO_DATE,
          title: headingTitle,
        });
      }
      continue;
    }
    if (!inDecisions) {
      continue;
    }
    const bullet = line.match(BULLET);
    if (!bullet) {
      continue;
    }
    const words = cleanWords(bullet[1]);
    if (words) {
      records.push({
        words,
        note,
        date: fromFile || headingDate || NO_DATE,
        title: headingTitle,
      });
    }
  }
  return records;
}

function matchDecisions(records, topic) {
  const needle = String(topic || "").trim().replace(/\s+/g, " ").toLowerCase();
  if (!needle) {
    return [];
  }
  const matches = [];
  for (const record of records) {
    const hay = `${record.words || ""} ${record.note || ""} ${record.title || ""}`.toLowerCase();
    if (hay.includes(needle)) {
      matches.push(record);
    }
  }
  return matches;
}

function formatDecisionMatch(record) {
  return `${record.words} (note: ${record.note}, date: ${record.date})`;
}

function recentDecisions(records, limit) {
  const cap = Number.isFinite(limit) ? limit : LATELY_LIMIT;
  const dated = [];
  for (const record of records) {
    const stamp = String(record.date || "");
    if (!DATE_STAMP.test(stamp)) {
      continue;
    }
    dated.push(record);
  }
  dated.sort((left, right) => {
    const a = String(left.date || "");
    const b = String(right.date || "");
    if (a === b) {
      return 0;
    }
    return a < b ? 1 : -1;
  });
  return dated.slice(0, Math.max(0, cap));
}

function isUserMarkdown(path) {
  const relative = String(path || "").replace(/^\/+/, "");
  if (!relative.toLowerCase().endsWith(".md")) {
    return false;
  }
  return USER_TREES.some((tree) => relative === tree || relative.startsWith(`${tree}/`));
}

function isPersonMarkdown(path) {
  const relative = String(path || "").replace(/^\/+/, "");
  if (!relative.toLowerCase().endsWith(".md")) {
    return false;
  }
  const base = relative.split("/").pop() || "";
  if (base.toLowerCase() === "readme.md") {
    return false;
  }
  return PEOPLE_TREES.some((tree) => relative === tree || relative.startsWith(`${tree}/`));
}

function cleanPersonValue(raw) {
  let value = String(raw || "").trim().replace(/\|+$/g, "").trim();
  if (value.length >= 2 && value[0] === value[value.length - 1] && (value[0] === '"' || value[0] === "'")) {
    value = value.slice(1, -1).trim();
  }
  if (BLANK_VALUES.has(value.toLowerCase())) {
    return "";
  }
  return value;
}

function collectPersonRecord(text, relativePath) {
  const note = noteName(relativePath);
  const fields = { name: "", role: "", company: "" };
  let heading = "";
  for (const line of String(text || "").split(/\r?\n/)) {
    if (!heading) {
      const marked = line.match(PERSON_HEADING);
      if (marked) {
        heading = String(marked[1] || "").trim();
      }
    }
    const match = line.trim().match(PERSON_FIELD);
    if (!match) {
      continue;
    }
    const key = String(match[1] || "").toLowerCase();
    if (!(key in fields)) {
      continue;
    }
    fields[key] = cleanPersonValue(match[2]);
  }
  const name = fields.name || heading || note.replace(/_/g, " ");
  if (!name) {
    return null;
  }
  return {
    name,
    role: fields.role,
    company: fields.company,
    note,
  };
}

function matchPeople(records, query) {
  const needle = String(query || "").trim().replace(/\s+/g, " ").toLowerCase();
  if (!needle) {
    return [];
  }
  const matches = [];
  const seen = new Set();
  const folded = needle.replace(/ /g, "_");
  for (const record of records) {
    const name = String(record.name || "").toLowerCase();
    const note = String(record.note || "");
    const spaced = note.replace(/_/g, " ").toLowerCase();
    const stem = note.toLowerCase();
    if (needle !== name && !name.includes(needle) && !spaced.includes(needle) && folded !== stem) {
      continue;
    }
    const key = note || name;
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    matches.push(record);
  }
  return matches;
}

function formatPersonMatch(record) {
  let who = String(record.name || "").trim();
  const role = String(record.role || "").trim();
  const company = String(record.company || "").trim();
  if (role && company) {
    who = `${who} — ${role} at ${company}`;
  } else if (role) {
    who = `${who} — ${role}`;
  } else if (company) {
    who = `${who} — at ${company}`;
  }
  return `${who} (note: ${record.note || ""})`;
}

function isNameBoundary(char) {
  if (!char) {
    return true;
  }
  return !/[\p{L}\p{N}_]/u.test(char);
}

function firstNamedIndex(haystack, needle) {
  const target = String(needle || "").trim();
  if (target.length < 2) {
    return -1;
  }
  const lowered = String(haystack || "").toLowerCase();
  const look = target.toLowerCase();
  let start = 0;
  while (start <= lowered.length) {
    const index = lowered.indexOf(look, start);
    if (index < 0) {
      return -1;
    }
    const before = index ? haystack[index - 1] : "";
    const afterAt = index + target.length;
    const after = afterAt < haystack.length ? haystack[afterAt] : "";
    if (isNameBoundary(before) && isNameBoundary(after)) {
      return index;
    }
    start = index + 1;
  }
  return -1;
}

function recordNeedles(record) {
  const needles = [];
  const seen = new Set();
  const note = String(record.note || "");
  [String(record.name || ""), note.replace(/_/g, " "), note].forEach((raw) => {
    const value = String(raw || "").trim();
    const key = value.toLowerCase();
    if (value.length < 2 || seen.has(key)) {
      return;
    }
    seen.add(key);
    needles.push(value);
  });
  needles.sort((left, right) => right.length - left.length);
  return needles;
}

function wikiTargetNote(raw) {
  const target = String(raw || "").trim().replace(/\\/g, "/");
  if (!target) {
    return "";
  }
  const base = target.split("/").pop() || "";
  return base.replace(/\.md$/i, "").trim();
}

function recordMatchesWiki(record, target) {
  const note = String(record.note || "");
  const name = String(record.name || "");
  const stem = wikiTargetNote(target);
  if (!stem) {
    return false;
  }
  const folded = stem.replace(/ /g, "_");
  const spaced = stem.replace(/_/g, " ");
  return (
    stem.toLowerCase() === note.toLowerCase()
    || folded.toLowerCase() === note.toLowerCase()
    || spaced.toLowerCase() === note.replace(/_/g, " ").toLowerCase()
    || spaced.toLowerCase() === name.toLowerCase()
    || stem.toLowerCase() === name.toLowerCase()
  );
}

function peopleNamedInPlan(records, planText) {
  const haystack = String(planText || "");
  if (!haystack.trim() || !records.length) {
    return [];
  }
  const hits = [];
  const wiki = new RegExp(WIKI_LINK.source, "g");
  let match = wiki.exec(haystack);
  while (match) {
    for (let index = 0; index < records.length; index += 1) {
      if (recordMatchesWiki(records[index], match[1])) {
        hits.push({ at: match.index, record: records[index] });
        break;
      }
    }
    match = wiki.exec(haystack);
  }
  records.forEach((record) => {
    let earliest = -1;
    recordNeedles(record).forEach((needle) => {
      const at = firstNamedIndex(haystack, needle);
      if (at < 0) {
        return;
      }
      if (earliest < 0 || at < earliest) {
        earliest = at;
      }
    });
    if (earliest >= 0) {
      hits.push({ at: earliest, record });
    }
  });
  hits.sort((left, right) => left.at - right.at);
  const ordered = [];
  const seen = new Set();
  hits.forEach((hit) => {
    const key = String(hit.record.note || hit.record.name || "");
    if (!key || seen.has(key)) {
      return;
    }
    seen.add(key);
    ordered.push(hit.record);
  });
  return ordered;
}

async function loadDecisionRecords(app) {
  const files = app.vault.getMarkdownFiles ? app.vault.getMarkdownFiles() : [];
  const records = [];
  for (const file of files) {
    const relative = file.path || "";
    if (!isUserMarkdown(relative)) {
      continue;
    }
    const text = await readVaultText(app, relative);
    records.push(...collectDecisionRecords(text, relative));
  }
  return records;
}

async function loadPersonRecords(app) {
  const files = app.vault.getMarkdownFiles ? app.vault.getMarkdownFiles() : [];
  const records = [];
  for (const file of files) {
    const relative = file.path || "";
    if (!isPersonMarkdown(relative)) {
      continue;
    }
    const text = await readVaultText(app, relative);
    const record = collectPersonRecord(text, relative);
    if (record) {
      records.push(record);
    }
  }
  return records;
}

async function renderTodayPeople(root, app, now) {
  const heading = root.createEl("h2", { text: TODAY_PEOPLE_HEADING });
  heading.addClass("dex-readonly-heading");
  const stamp = todayStamp(now);
  const relative = `00-Inbox/Daily_Plans/${stamp}.md`;
  const file = app.vault.getAbstractFileByPath(relative);
  if (!file || !file.extension) {
    root.createEl("p", {
      text: NO_PLAN,
      cls: "dex-readonly-empty",
    });
    return;
  }
  const text = await readVaultText(app, relative);
  const records = await loadPersonRecords(app);
  const matches = peopleNamedInPlan(records, text);
  if (!matches.length) {
    root.createEl("p", {
      text: NOBODY_NAMED,
      cls: "dex-readonly-empty",
    });
    return;
  }
  const list = root.createEl("ul", { cls: "dex-readonly-today-people" });
  for (const match of matches) {
    list.createEl("li", { text: formatPersonMatch(match) });
  }
}

async function renderLately(root, app) {
  const heading = root.createEl("h2", { text: "Decided lately" });
  heading.addClass("dex-readonly-heading");
  const records = await loadDecisionRecords(app);
  const matches = recentDecisions(records, LATELY_LIMIT);
  if (!matches.length) {
    root.createEl("p", {
      text: LATELY_EMPTY,
      cls: "dex-readonly-empty",
    });
    return;
  }
  const list = root.createEl("ul", { cls: "dex-readonly-lately" });
  for (const match of matches) {
    list.createEl("li", { text: formatDecisionMatch(match) });
  }
}

function renderAsk(root, app) {
  const heading = root.createEl("h2", { text: "What we decided" });
  heading.addClass("dex-readonly-heading");
  const box = root.createEl("div", { cls: "dex-readonly-ask" });
  const input = box.createEl("input");
  input.setAttribute("type", "text");
  input.setAttribute("placeholder", "Type a topic");
  input.setAttribute("aria-label", "Type a topic");
  const button = box.createEl("button", { text: "Look in your files" });
  button.setAttribute("type", "button");
  const results = root.createEl("div", { cls: "dex-readonly-ask-results" });

  async function runAsk() {
    const topic = input.value || "";
    const records = await loadDecisionRecords(app);
    const matches = matchDecisions(records, topic);
    results.empty();
    if (!matches.length) {
      results.createEl("p", {
        text: EMPTY_SENTENCE,
        cls: "dex-readonly-empty",
      });
      return;
    }
    const list = results.createEl("ul");
    for (const match of matches) {
      list.createEl("li", { text: formatDecisionMatch(match) });
    }
  }

  button.addEventListener("click", () => {
    runAsk();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      runAsk();
    }
  });
}

function renderPerson(root, app) {
  const heading = root.createEl("h2", { text: "Who they are" });
  heading.addClass("dex-readonly-heading");
  const box = root.createEl("div", { cls: "dex-readonly-ask" });
  const input = box.createEl("input");
  input.setAttribute("type", "text");
  input.setAttribute("placeholder", "Type a person's name");
  input.setAttribute("aria-label", "Type a person's name");
  const button = box.createEl("button", { text: "Look in your files" });
  button.setAttribute("type", "button");
  const results = root.createEl("div", { cls: "dex-readonly-ask-results" });

  async function runPerson() {
    const query = input.value || "";
    const records = await loadPersonRecords(app);
    const matches = matchPeople(records, query);
    results.empty();
    if (!matches.length) {
      results.createEl("p", {
        text: PERSON_EMPTY,
        cls: "dex-readonly-empty",
      });
      return;
    }
    const list = results.createEl("ul");
    for (const match of matches) {
      list.createEl("li", { text: formatPersonMatch(match) });
    }
  }

  button.addEventListener("click", () => {
    runPerson();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      runPerson();
    }
  });
}

class DexBriefView extends ItemView {
  getViewType() {
    return VIEW_TYPE;
  }

  getDisplayText() {
    return "Dex";
  }

  getIcon() {
    return "calendar";
  }

  async onOpen() {
    const root = this.containerEl.children[1];
    const brief = await buildTodayBrief(this.app);
    renderBrief(root, brief);
    await renderTodayPeople(root, this.app);
    await renderLately(root, this.app);
    renderAsk(root, this.app);
    renderPerson(root, this.app);
    root.createEl("p", {
      text: "This panel is read-only. It does not edit notes, run commands, or use the internet.",
      cls: "dex-readonly-note",
    });
  }
}

class DexReadonlyPlugin extends Plugin {
  async onload() {
    this.registerView(VIEW_TYPE, (leaf) => new DexBriefView(leaf));
    this.app.workspace.onLayoutReady(() => {
      this.revealPanel();
    });
  }

  async revealPanel() {
    const { workspace } = this.app;
    let leaf = workspace.getLeavesOfType(VIEW_TYPE)[0];
    if (!leaf) {
      leaf = workspace.getRightLeaf(false);
      if (!leaf) {
        return;
      }
      await leaf.setViewState({ type: VIEW_TYPE, active: true });
    }
    workspace.revealLeaf(leaf);
  }
}

module.exports = DexReadonlyPlugin;
module.exports.VIEW_TYPE = VIEW_TYPE;
module.exports.buildTodayBrief = buildTodayBrief;
module.exports.renderBrief = renderBrief;
module.exports.renderAsk = renderAsk;
module.exports.renderLately = renderLately;
module.exports.renderTodayPeople = renderTodayPeople;
module.exports.renderPerson = renderPerson;
module.exports.todayLabel = todayLabel;
module.exports.collectDecisionRecords = collectDecisionRecords;
module.exports.matchDecisions = matchDecisions;
module.exports.recentDecisions = recentDecisions;
module.exports.formatDecisionMatch = formatDecisionMatch;
module.exports.collectPersonRecord = collectPersonRecord;
module.exports.matchPeople = matchPeople;
module.exports.peopleNamedInPlan = peopleNamedInPlan;
module.exports.formatPersonMatch = formatPersonMatch;
module.exports.isPersonMarkdown = isPersonMarkdown;
module.exports.EMPTY_SENTENCE = EMPTY_SENTENCE;
module.exports.LATELY_EMPTY = LATELY_EMPTY;
module.exports.LATELY_LIMIT = LATELY_LIMIT;
module.exports.PERSON_EMPTY = PERSON_EMPTY;
module.exports.TODAY_PEOPLE_HEADING = TODAY_PEOPLE_HEADING;
module.exports.NOBODY_NAMED = NOBODY_NAMED;
module.exports.NO_PLAN = NO_PLAN;
