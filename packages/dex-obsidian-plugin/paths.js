/**
 * Vault-relative path constants for the read-only Obsidian panel.
 * Mirrors core/paths.py. This file is the path-contract source for the panel.
 */
const PILLARS_FILE = "System/pillars.yaml";
const QUARTER_GOALS_FILE = "01-Quarter_Goals/Quarter_Goals.md";
const WEEK_PRIORITIES_FILE = "02-Week_Priorities/Week_Priorities.md";
const TASKS_FILE = "03-Tasks/Tasks.md";
const DAILY_PLANS_DIR = "00-Inbox/Daily_Plans";

function dailyPlanFile(stamp) {
  return `${DAILY_PLANS_DIR}/${stamp}.md`;
}

module.exports = {
  PILLARS_FILE,
  QUARTER_GOALS_FILE,
  WEEK_PRIORITIES_FILE,
  TASKS_FILE,
  DAILY_PLANS_DIR,
  dailyPlanFile,
};
