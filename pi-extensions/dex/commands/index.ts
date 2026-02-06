/**
 * Commands Module
 * Custom Pi commands for Dex
 * 
 * These commands provide shortcuts and enhanced workflows
 * for Pi users. They don't affect Cursor/Claude Desktop users.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import * as fs from "node:fs";
import * as path from "node:path";
import { getTaskSummary, getOpenTasks, getP0Tasks, getOverdueTasks } from "../context/task.js";

/**
 * Register all Dex commands
 */
export function registerCommands(pi: ExtensionAPI, vaultRoot: string): void {
  // ============================================================
  // /status - Quick Dex status overview
  // ============================================================
  pi.registerCommand("status", {
    description: "Quick Dex status overview (tasks, inbox, reminders)",
    handler: async (args, ctx) => {
      try {
        const summary = await getTaskSummary(vaultRoot);
        const inboxCount = await countInbox(vaultRoot);

        const parts: string[] = [];
        parts.push(`📋 ${summary.open}/${summary.total} tasks`);
        
        if (summary.overdue > 0) {
          parts.push(`⚠️ ${summary.overdue} overdue`);
        }
        if (summary.p0Count > 0) {
          parts.push(`🔴 ${summary.p0Count} P0`);
        }
        
        parts.push(`📥 ${inboxCount} inbox`);

        ctx.ui.notify(parts.join(" | "), "info");
      } catch (e) {
        ctx.ui.notify(`Status check failed: ${e}`, "error");
      }
    },
  });

  // ============================================================
  // /capture <text> - Quick capture to inbox
  // ============================================================
  pi.registerCommand("capture", {
    description: "Quick capture idea or note to inbox",
    handler: async (args, ctx) => {
      if (!args || args.trim().length === 0) {
        ctx.ui.notify("Usage: /capture <your idea or note>", "warning");
        return;
      }

      try {
        const result = await quickCapture(vaultRoot, args.trim());
        ctx.ui.notify(`📝 Captured to ${result.relativePath}`, "success");
      } catch (e) {
        ctx.ui.notify(`Capture failed: ${e}`, "error");
      }
    },
  });

  // ============================================================
  // /focus - Show what to focus on (P0s and overdue)
  // ============================================================
  pi.registerCommand("focus", {
    description: "Show high-priority items to focus on",
    handler: async (args, ctx) => {
      try {
        const p0Tasks = await getP0Tasks(vaultRoot);
        const overdue = await getOverdueTasks(vaultRoot);

        const items: string[] = [];

        if (overdue.length > 0) {
          items.push(`⚠️ **${overdue.length} overdue:**`);
          overdue.slice(0, 3).forEach((t) => {
            items.push(`  • ${t.title} (due: ${t.dueDate})`);
          });
        }

        if (p0Tasks.length > 0) {
          items.push(`🔴 **${p0Tasks.length} P0:**`);
          p0Tasks.slice(0, 3).forEach((t) => {
            items.push(`  • ${t.title}`);
          });
        }

        if (items.length === 0) {
          ctx.ui.notify("✅ All clear! No urgent tasks.", "success");
        } else {
          // For longer output, set it as editor text so user can see full list
          ctx.ui.setEditorText(
            `Focus areas:\n\n${items.join("\n")}\n\nAsk me to help with any of these!`
          );
          ctx.ui.notify(`Found ${overdue.length} overdue + ${p0Tasks.length} P0`, "info");
        }
      } catch (e) {
        ctx.ui.notify(`Focus check failed: ${e}`, "error");
      }
    },
  });

  // ============================================================
  // /today - Show today's context
  // ============================================================
  pi.registerCommand("today", {
    description: "Show today's daily note and relevant context",
    handler: async (args, ctx) => {
      const today = new Date().toISOString().split("T")[0];
      const dailyPath = path.join(vaultRoot, "00-Inbox", "Daily", `${today}.md`);

      if (fs.existsSync(dailyPath)) {
        // Read and set as reference for the conversation
        ctx.ui.setEditorText(`Read my daily plan at ${dailyPath} and summarize what I should focus on today.`);
        ctx.ui.notify("Daily plan found. Press Enter to load context.", "info");
      } else {
        ctx.ui.setEditorText("Help me create a daily plan for today. Run /skill:daily-plan to get started.");
        ctx.ui.notify("No daily plan yet. Let's create one!", "info");
      }
    },
  });

  // ============================================================
  // /tasks [filter] - List tasks with optional filter
  // ============================================================
  pi.registerCommand("tasks", {
    description: "List open tasks (optional: P0, P1, P2, P3, overdue)",
    handler: async (args, ctx) => {
      try {
        let tasks = await getOpenTasks(vaultRoot);
        let filterLabel = "open";

        // Apply filter if provided
        if (args) {
          const filter = args.trim().toUpperCase();
          if (filter === "OVERDUE") {
            tasks = await getOverdueTasks(vaultRoot);
            filterLabel = "overdue";
          } else if (["P0", "P1", "P2", "P3"].includes(filter)) {
            tasks = tasks.filter((t) => t.priority === filter);
            filterLabel = filter;
          }
        }

        if (tasks.length === 0) {
          ctx.ui.notify(`No ${filterLabel} tasks found`, "info");
          return;
        }

        // Format task list
        const lines = tasks.slice(0, 10).map((t) => {
          const emoji = { P0: "🔴", P1: "🟠", P2: "🟡", P3: "🟢" }[t.priority] || "⬜";
          const due = t.dueDate ? ` (${t.dueDate})` : "";
          return `${emoji} ${t.title}${due}`;
        });

        if (tasks.length > 10) {
          lines.push(`... and ${tasks.length - 10} more`);
        }

        ctx.ui.setEditorText(
          `${filterLabel.charAt(0).toUpperCase() + filterLabel.slice(1)} tasks (${tasks.length}):\n\n${lines.join("\n")}\n\nAsk me to help with any of these!`
        );
        ctx.ui.notify(`${tasks.length} ${filterLabel} tasks`, "info");
      } catch (e) {
        ctx.ui.notify(`Task list failed: ${e}`, "error");
      }
    },
  });

  // ============================================================
  // /done <task description> - Mark a task as done
  // ============================================================
  pi.registerCommand("done", {
    description: "Mark a task as done (by description or ID)",
    handler: async (args, ctx) => {
      if (!args || args.trim().length === 0) {
        ctx.ui.notify("Usage: /done <task description or ID>", "warning");
        return;
      }

      const query = args.trim().toLowerCase();
      const tasks = await getOpenTasks(vaultRoot);

      // Try to find matching task
      let match = tasks.find((t) => t.id.toLowerCase() === query);
      
      if (!match) {
        // Fuzzy match by title
        match = tasks.find((t) => t.title.toLowerCase().includes(query));
      }

      if (!match) {
        ctx.ui.notify(`No task found matching "${args.trim()}"`, "warning");
        return;
      }

      // Complete the task
      ctx.ui.setEditorText(
        `Complete the task: "${match.title}" (ID: ${match.id})\n\nUse the dex_task tool with action="complete" and task_id="${match.id}"`
      );
      ctx.ui.notify(`Found: ${match.title}. Press Enter to complete.`, "info");
    },
  });

  // ============================================================
  // /dex - Dex help and feature overview
  // ============================================================
  pi.registerCommand("dex", {
    description: "Show Dex help and available Pi commands",
    handler: async (args, ctx) => {
      const help = `
# Dex Pi Extension

## Quick Commands
- \`/status\` - Overview of tasks and inbox
- \`/focus\` - Show high-priority items
- \`/today\` - Today's context and daily plan
- \`/tasks [filter]\` - List tasks (P0, P1, overdue)
- \`/capture <text>\` - Quick capture to inbox
- \`/done <task>\` - Mark task as done

## Custom Tools (ask Claude to use)
- \`vault_search\` - Full-text search across vault
- \`dex_task\` - Create, complete, list tasks
- \`quick_capture\` - Capture ideas to inbox
- \`dex_status\` - Detailed status overview

## Features
- ✅ Proactive context injection (people, companies, tasks)
- ✅ Notification sounds on completion
- ✅ Auto git sync on session start/end
- ✅ Status indicator in footer

Run any command or ask me about Dex features!
`.trim();

      ctx.ui.setEditorText(help);
      ctx.ui.notify("Dex help loaded", "info");
    },
  });
}

// ============================================================
// HELPER FUNCTIONS
// ============================================================

async function countInbox(vaultRoot: string): Promise<number> {
  let count = 0;
  const inboxDirs = ["Ideas", "Meetings", "Tasks"];

  for (const dir of inboxDirs) {
    const fullDir = path.join(vaultRoot, "00-Inbox", dir);
    if (!fs.existsSync(fullDir)) continue;

    try {
      const files = fs.readdirSync(fullDir);
      count += files.filter((f) => f.endsWith(".md")).length;
    } catch (e) {
      // Skip if can't read
    }
  }

  return count;
}

async function quickCapture(
  vaultRoot: string,
  content: string
): Promise<{ path: string; relativePath: string }> {
  const inboxDir = path.join(vaultRoot, "00-Inbox", "Ideas");
  if (!fs.existsSync(inboxDir)) {
    fs.mkdirSync(inboxDir, { recursive: true });
  }

  const timestamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const title = content.slice(0, 50).replace(/[^a-zA-Z0-9\s]/g, "").trim() || "capture";
  const safeTitle = title.replace(/\s+/g, "_");
  const filename = `${timestamp}-${safeTitle}.md`;
  const filePath = path.join(inboxDir, filename);

  const fileContent = [
    "---",
    "type: quick-capture",
    `captured: ${new Date().toISOString()}`,
    "---",
    "",
    `# ${title}`,
    "",
    content,
  ].join("\n");

  fs.writeFileSync(filePath, fileContent);

  return {
    path: filePath,
    relativePath: path.relative(vaultRoot, filePath),
  };
}
