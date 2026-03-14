/**
 * Ritual Command Bar
 *
 * Collapsible bar below chat showing daily/weekly/quarterly rituals
 * Collapsed: 1 line with status indicators (🔴 pending, ✅ done)
 * Expanded: Interactive overlay with full SelectList
 */

import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { DynamicBorder } from "@mariozechner/pi-coding-agent";
import { Container, type SelectItem, SelectList, Text, truncateToWidth } from "@mariozechner/pi-tui";
import * as fs from "node:fs";
import * as path from "node:path";

const VAULT_PATH = process.env.VAULT_PATH || process.cwd();

// ============================================================================
// RITUAL STATE DETECTION
// ============================================================================

interface RitualState {
  id: string;
  label: string;
  command: string;
  status: "pending" | "overdue" | "completed";
  priority: number; // Higher = show first in collapsed view
  description?: string;
}

function formatDate(): string {
  return new Date().toISOString().slice(0, 10);
}

function getDayOfWeek(): number {
  const day = new Date().getDay();
  return day === 0 ? 7 : day; // Monday = 1, Sunday = 7
}

function getWeekNumber(): string {
  const now = new Date();
  const start = new Date(now.getFullYear(), 0, 1);
  const diff = now.getTime() - start.getTime();
  const oneWeek = 1000 * 60 * 60 * 24 * 7;
  return `W${Math.ceil(diff / oneWeek)}`;
}

function getQuarter(): string {
  const month = new Date().getMonth() + 1;
  const quarter = Math.ceil(month / 3);
  const year = new Date().getFullYear();
  return `Q${quarter}-${year}`;
}

function checkFileExists(filePath: string): boolean {
  try {
    return fs.existsSync(filePath);
  } catch {
    return false;
  }
}

function checkFileUpdatedToday(filePath: string): boolean {
  try {
    if (!fs.existsSync(filePath)) return false;
    const stats = fs.statSync(filePath);
    const today = formatDate();
    const fileDate = stats.mtime.toISOString().slice(0, 10);
    return fileDate === today;
  } catch {
    return false;
  }
}

function checkWeekPrioritiesExist(): boolean {
  const filePath = path.join(VAULT_PATH, "02-Week_Priorities/Week_Priorities.md");
  try {
    if (!fs.existsSync(filePath)) return false;
    const content = fs.readFileSync(filePath, "utf-8");
    const currentWeek = getWeekNumber();
    // Check if current week section exists with priorities
    return content.includes(`## Week ${currentWeek}`) || content.includes(`## ${currentWeek}`);
  } catch {
    return false;
  }
}

function checkQuarterGoalsExist(): boolean {
  const filePath = path.join(VAULT_PATH, "01-Quarter_Goals/Quarter_Goals.md");
  try {
    if (!fs.existsSync(filePath)) return false;
    const content = fs.readFileSync(filePath, "utf-8");
    const currentQuarter = getQuarter();
    // Check if current quarter section exists with goals
    return content.includes(`## ${currentQuarter}`) || content.includes(currentQuarter);
  } catch {
    return false;
  }
}

/**
 * Get current ritual states based on file existence and timing
 */
function getRitualStates(): RitualState[] {
  const today = formatDate();
  const yesterday = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
  const dayOfWeek = getDayOfWeek();

  const rituals: RitualState[] = [];

  // Daily Review (from yesterday if not done)
  const yesterdayReview = path.join(VAULT_PATH, `00-Inbox/Daily_Reviews/Daily_Review_${yesterday}.md`);
  if (!checkFileExists(yesterdayReview) && dayOfWeek !== 1) {
    // Monday morning doesn't nag about Sunday review
    rituals.push({
      id: "daily-review-yesterday",
      label: "Daily Review (yesterday)",
      command: "daily-review",
      status: "overdue",
      priority: 100,
      description: "Review yesterday's progress and capture learnings"
    });
  }

  // Daily Plan (for today)
  const todayPlan = path.join(VAULT_PATH, `00-Inbox/Daily_Plans/${today}.md`);
  if (!checkFileExists(todayPlan)) {
    rituals.push({
      id: "daily-plan",
      label: "Daily Plan",
      command: "daily-plan",
      status: "pending",
      priority: 90,
      description: "Plan priorities and set focus for today"
    });
  } else {
    rituals.push({
      id: "daily-plan",
      label: "Daily Plan",
      command: "daily-plan",
      status: "completed",
      priority: 0,
      description: "Already done today"
    });
  }

  // Weekly Plan (Monday morning or Sunday evening)
  if (dayOfWeek === 1 || dayOfWeek === 7) {
    if (!checkWeekPrioritiesExist()) {
      rituals.push({
        id: "weekly-plan",
        label: "Weekly Plan",
        command: "week-plan",
        status: "pending",
        priority: 80,
        description: "Set priorities for the week ahead"
      });
    } else {
      rituals.push({
        id: "weekly-plan",
        label: "Weekly Plan",
        command: "week-plan",
        status: "completed",
        priority: 0,
        description: "Already done for this week"
      });
    }
  }

  // Weekly Review (Friday afternoon/evening)
  if (dayOfWeek === 5) {
    const todayReview = path.join(VAULT_PATH, `00-Inbox/Daily_Reviews/Daily_Review_${today}.md`);
    // Check if today's review has "Week Review" section (indicates weekly review done)
    let weekReviewDone = false;
    try {
      if (fs.existsSync(todayReview)) {
        const content = fs.readFileSync(todayReview, "utf-8");
        weekReviewDone = content.includes("## Week Review") || content.includes("## Weekly Review");
      }
    } catch {}

    if (!weekReviewDone) {
      rituals.push({
        id: "weekly-review",
        label: "Weekly Review",
        command: "week-review",
        status: "pending",
        priority: 70,
        description: "Review week's progress and capture patterns"
      });
    } else {
      rituals.push({
        id: "weekly-review",
        label: "Weekly Review",
        command: "week-review",
        status: "completed",
        priority: 0,
        description: "Already done for this week"
      });
    }
  }

  // Quarterly Plan (first week of quarter or last week of previous quarter)
  const month = new Date().getMonth() + 1;
  const isQuarterStart = [1, 4, 7, 10].includes(month);
  const isQuarterEnd = [3, 6, 9, 12].includes(month);

  if (isQuarterStart || isQuarterEnd) {
    if (!checkQuarterGoalsExist()) {
      rituals.push({
        id: "quarterly-plan",
        label: "Quarterly Plan",
        command: "quarter-plan",
        status: "pending",
        priority: 60,
        description: "Set strategic goals for the quarter"
      });
    } else {
      rituals.push({
        id: "quarterly-plan",
        label: "Quarterly Plan",
        command: "quarter-plan",
        status: "completed",
        priority: 0,
        description: "Already done for this quarter"
      });
    }
  }

  // Sort by priority (highest first)
  rituals.sort((a, b) => b.priority - a.priority);

  return rituals;
}

/**
 * Get status icon for ritual
 */
function getStatusIcon(status: "pending" | "overdue" | "completed"): string {
  switch (status) {
    case "overdue": return "🔴";
    case "pending": return "🟡";
    case "completed": return "✅";
  }
}

/**
 * Get quick actions (always-available shortcuts)
 */
function getQuickActions(): SelectItem[] {
  return [
    { value: "triage", label: "📋 Triage Inbox", description: "Organize and process inbox items" },
    { value: "meeting-prep", label: "📅 Meeting Prep", description: "Prepare for today's meetings" },
    { value: "project-health", label: "🎯 Project Health", description: "Check project status and blockers" },
  ];
}

// ============================================================================
// COLLAPSED WIDGET (1 LINE)
// ============================================================================

export function renderCollapsedWidget(width: number): string[] {
  const rituals = getRitualStates();

  // Show only pending/overdue (not completed)
  const pending = rituals.filter(r => r.status !== "completed");

  if (pending.length === 0) {
    // All done! Show completed count
    const completed = rituals.filter(r => r.status === "completed");
    const text = `✅ All rituals complete (${completed.length})  📋 Quick actions available  [Press Ctrl+. to expand]`;
    return [truncateToWidth(text, width)];
  }

  // Build compact line: "🔴 Review  🟡 Plan  📋 Triage  📅 Meetings  [↓ More]"
  const parts: string[] = [];

  for (const ritual of pending.slice(0, 3)) {
    parts.push(`${getStatusIcon(ritual.status)} ${ritual.label}`);
  }

  // Add quick actions hint
  parts.push("📋 Quick actions");

  // Add expand hint
  const remainingCount = Math.max(0, pending.length - 3);
  if (remainingCount > 0) {
    parts.push(`[↓ ${remainingCount} more]`);
  } else {
    parts.push("[↓ Expand]");
  }

  const text = parts.join("  ");
  return [truncateToWidth(text, width)];
}

// ============================================================================
// EXPANDED OVERLAY (INTERACTIVE)
// ============================================================================

export async function showExpandedRituals(ctx: ExtensionContext, pi: ExtensionAPI): Promise<void> {
  const rituals = getRitualStates();

  // Build SelectList items
  const items: SelectItem[] = [];

  // Add rituals (pending/overdue first, then completed)
  const pending = rituals.filter(r => r.status !== "completed");
  const completed = rituals.filter(r => r.status === "completed");

  // Pending/overdue rituals
  for (const ritual of pending) {
    items.push({
      value: ritual.command,
      label: `${getStatusIcon(ritual.status)} ${ritual.label}`,
      description: ritual.description || ""
    });
  }

  // Separator (if we have both pending and completed)
  if (pending.length > 0 && completed.length > 0) {
    items.push({
      value: "_separator_done",
      label: "─── Done Today ───",
      description: ""
    });
  }

  // Completed rituals (grayed out, still selectable to re-run)
  for (const ritual of completed) {
    items.push({
      value: ritual.command,
      label: `${getStatusIcon(ritual.status)} ${ritual.label}`,
      description: ritual.description || ""
    });
  }

  // Separator before quick actions
  items.push({
    value: "_separator_quick",
    label: "─── Quick Actions ───",
    description: ""
  });

  // Quick actions
  items.push(...getQuickActions());

  // Show interactive overlay
  const result = await ctx.ui.custom<string | null>((tui, theme, _kb, done) => {
    const container = new Container();

    // Top border
    container.addChild(new DynamicBorder((s: string) => theme.fg("accent", s)));

    // Title
    container.addChild(new Text(theme.fg("accent", theme.bold("Your Rituals & Actions")), 1, 0));

    // SelectList
    const selectList = new SelectList(items, Math.min(items.length, 12), {
      selectedPrefix: (t) => theme.fg("accent", t),
      selectedText: (t) => theme.fg("accent", t),
      description: (t) => theme.fg("muted", t),
      scrollInfo: (t) => theme.fg("dim", t),
      noMatch: (t) => theme.fg("warning", t),
    });

    selectList.onSelect = (item) => {
      // Skip separators
      if (item.value.startsWith("_separator_")) {
        return;
      }
      done(item.value);
    };
    selectList.onCancel = () => done(null);
    container.addChild(selectList);

    // Help text
    container.addChild(new Text(theme.fg("dim", "↑↓ navigate • enter select • esc cancel • type to filter"), 1, 0));

    // Bottom border
    container.addChild(new DynamicBorder((s: string) => theme.fg("accent", s)));

    return {
      render: (w) => container.render(w),
      invalidate: () => container.invalidate(),
      handleInput: (data) => { selectList.handleInput(data); tui.requestRender(); },
    };
  });

  // Execute selected command
  if (result) {
    // Small delay to ensure UI fully closed before executing command
    setTimeout(async () => {
      try {
        await pi.executeCommand(result, "", ctx);
      } catch (error) {
        ctx.ui.notify(`Failed to execute /${result}`, "error");
      }
    }, 100);
  }
}

// ============================================================================
// REGISTRATION
// ============================================================================

export function registerRitualCommandBar(pi: ExtensionAPI) {
  // Session start: show collapsed widget
  pi.on("session_start", async (_event, ctx) => {
    if (!ctx.hasUI) return;

    // Render collapsed widget below editor
    ctx.ui.setWidget("ritual-command-bar", (_tui, _theme) => ({
      render: (width) => {
        try {
          return renderCollapsedWidget(width);
        } catch (error) {
          console.error("[Dex] Ritual command bar error:", error);
          return [];
        }
      },
      invalidate: () => {},
    }), { placement: "belowEditor" });
  });

  // Command: /rituals (expand view)
  pi.registerCommand("rituals", {
    description: "Show ritual command bar (daily plan, review, etc.)",
    handler: async (args, ctx) => {
      await showExpandedRituals(ctx, pi);
    }
  });

  // Keyboard shortcut: Ctrl+. (expand view)
  pi.registerShortcut("ctrl+.", {
    description: "Show ritual command bar",
    handler: async (ctx) => {
      // Execute the command instead of calling showExpandedRituals directly
      // This ensures proper context is passed
      await pi.executeCommand("rituals", "", ctx);
    }
  });

  // Command: refresh ritual bar (after completing rituals)
  pi.registerCommand("refresh-rituals", {
    description: "Refresh ritual command bar status",
    handler: async (args, ctx) => {
      if (!ctx.hasUI) return;

      // Re-render widget to show updated status
      ctx.ui.setWidget("ritual-command-bar", (_tui, _theme) => ({
        render: (width) => {
          try {
            return renderCollapsedWidget(width);
          } catch (error) {
            console.error("[Dex] Ritual command bar error:", error);
            return [];
          }
        },
        invalidate: () => {},
      }), { placement: "belowEditor" });

      ctx.ui.notify("Ritual bar refreshed", "success");
    }
  });

  // Agent end: refresh widget (in case rituals completed during turn)
  pi.on("agent_end", async (_event, ctx) => {
    if (!ctx.hasUI) return;

    // Re-render widget to show updated status
    ctx.ui.setWidget("ritual-command-bar", (_tui, _theme) => ({
      render: (width) => {
        try {
          return renderCollapsedWidget(width);
        } catch (error) {
          console.error("[Dex] Ritual command bar error:", error);
          return [];
        }
      },
      invalidate: () => {},
    }), { placement: "belowEditor" });
  });
}
