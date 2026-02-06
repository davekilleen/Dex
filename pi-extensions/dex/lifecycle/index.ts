/**
 * Lifecycle Module
 * Handles session start, end, and other lifecycle events
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import * as fs from "node:fs";
import * as path from "node:path";
import { setupSounds, playSound } from "./sounds.js";
import { getTaskSummary, getOverdueTasks } from "../context/task.js";

/**
 * Set up all lifecycle handlers
 */
export function setupLifecycle(pi: ExtensionAPI, vaultRoot: string): void {
  // Set up sound notifications
  setupSounds(pi);

  // ============================================================
  // SESSION START
  // ============================================================
  pi.on("session_start", async (_event, ctx) => {
    // 1. Show Dex status indicator in footer
    if (ctx.hasUI) {
      ctx.ui.setStatus("dex", ctx.ui.theme.fg("success", "● Dex"));
    }

    // 2. Git sync (optional, fail silently)
    await gitSync(pi, vaultRoot, ctx);

    // 3. Check for overdue tasks and notify
    await checkTaskAlerts(pi, vaultRoot, ctx);

    // 4. Check if daily plan exists
    await checkDailyPlan(vaultRoot, ctx);

    // 5. Log session start
    await logEvent(vaultRoot, "session_start", { source: "pi" });
  });

  // ============================================================
  // SESSION SHUTDOWN
  // ============================================================
  pi.on("session_shutdown", async (_event, ctx) => {
    // 1. Auto-commit changes (optional)
    await gitAutoCommit(pi, vaultRoot);

    // 2. Log session end
    await logEvent(vaultRoot, "session_end", { source: "pi" });
  });

  // ============================================================
  // MODEL CHANGE
  // Log when user switches models (useful for analytics)
  // ============================================================
  pi.on("model_select", async (event, ctx) => {
    await logEvent(vaultRoot, "model_change", {
      from: event.previousModel?.id,
      to: event.model.id,
      source: event.source,
    });
  });
}

/**
 * Git sync - pull latest changes
 */
async function gitSync(
  pi: ExtensionAPI,
  vaultRoot: string,
  ctx: any
): Promise<void> {
  try {
    // Check if it's a git repo
    const gitDir = path.join(vaultRoot, ".git");
    if (!fs.existsSync(gitDir)) {
      return;
    }

    const result = await pi.exec("git", ["pull", "--quiet"], {
      timeout: 10000,
    });

    if (result.code === 0 && ctx.hasUI) {
      // Only notify if there were actual changes
      if (result.stdout.includes("Updating") || result.stdout.includes("Fast-forward")) {
        ctx.ui.notify("✅ Synced with GitHub", "info");
      }
    }
  } catch (e) {
    // Git not available or not a repo - skip silently
  }
}

/**
 * Git auto-commit on session end
 */
async function gitAutoCommit(pi: ExtensionAPI, vaultRoot: string): Promise<void> {
  try {
    const gitDir = path.join(vaultRoot, ".git");
    if (!fs.existsSync(gitDir)) {
      return;
    }

    // Check for uncommitted changes
    const status = await pi.exec("git", ["status", "--porcelain"], {
      timeout: 3000,
    });

    if (!status.stdout.trim()) {
      return; // No changes
    }

    // Stage and commit
    await pi.exec("git", ["add", "."], { timeout: 5000 });
    await pi.exec(
      "git",
      ["commit", "-m", `Auto-commit from Dex (Pi) - ${new Date().toISOString()}`],
      { timeout: 5000 }
    );

    // Push (optional, may fail if no remote)
    try {
      await pi.exec("git", ["push"], { timeout: 15000 });
    } catch (e) {
      // Push failed - likely no remote configured
    }
  } catch (e) {
    // Auto-commit failed - skip silently
  }
}

/**
 * Check for overdue tasks and P0s
 */
async function checkTaskAlerts(
  pi: ExtensionAPI,
  vaultRoot: string,
  ctx: any
): Promise<void> {
  try {
    const summary = await getTaskSummary(vaultRoot);
    const alerts: string[] = [];

    if (summary.overdue > 0) {
      alerts.push(`⚠️ ${summary.overdue} overdue tasks`);
    }

    if (summary.p0Count > 0) {
      alerts.push(`🔴 ${summary.p0Count} P0 tasks`);
    }

    if (alerts.length > 0 && ctx.hasUI) {
      ctx.ui.notify(alerts.join(" | "), summary.overdue > 0 ? "warning" : "info");
    }
  } catch (e) {
    // Task check failed - skip silently
  }
}

/**
 * Check if daily plan exists for today
 */
async function checkDailyPlan(vaultRoot: string, ctx: any): Promise<void> {
  try {
    const today = new Date().toISOString().split("T")[0];
    const dailyPath = path.join(vaultRoot, "00-Inbox", "Daily", `${today}.md`);

    if (!fs.existsSync(dailyPath) && ctx.hasUI) {
      ctx.ui.notify("📝 No daily plan yet. Run /daily-plan to create one.", "info");
    }
  } catch (e) {
    // Check failed - skip silently
  }
}

/**
 * Log events to session log
 */
async function logEvent(
  vaultRoot: string,
  event: string,
  data: Record<string, any> = {}
): Promise<void> {
  try {
    const logDir = path.join(vaultRoot, "System");
    if (!fs.existsSync(logDir)) {
      return;
    }

    const logPath = path.join(logDir, ".session-log.jsonl");
    const entry = {
      timestamp: new Date().toISOString(),
      event,
      ...data,
    };

    fs.appendFileSync(logPath, JSON.stringify(entry) + "\n");
  } catch (e) {
    // Logging failed - skip silently
  }
}

// Re-export sounds for use elsewhere
export { playSound } from "./sounds.js";
