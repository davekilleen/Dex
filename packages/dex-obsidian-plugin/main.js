const { ItemView, Plugin } = require("obsidian");
const {
  PILLARS_FILE,
  QUARTER_GOALS_FILE,
  WEEK_PRIORITIES_FILE,
  TASKS_FILE,
  dailyPlanFile,
} = require("./paths.js");

const VIEW_TYPE = "dex-readonly-brief";
const PILLAR_LIMIT = 5;
const URGENT_LIMIT = 3;
const GOAL_LIMIT = 10;
const DAILY_PLAN_LIMIT = 24;

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
  const pillarsText = await readVaultText(app, PILLARS_FILE);
  const goalsText = await readVaultText(app, QUARTER_GOALS_FILE);
  const weekText = await readVaultText(app, WEEK_PRIORITIES_FILE);
  const tasksText = await readVaultText(app, TASKS_FILE);
  const dailyText = await readVaultText(app, dailyPlanFile(todayStamp(now)));
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
  root.createEl("p", {
    text: "This panel is read-only. It does not edit notes, run commands, or use the internet.",
    cls: "dex-readonly-note",
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
module.exports.todayLabel = todayLabel;
