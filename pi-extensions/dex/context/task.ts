/**
 * Task Context Module
 * Parses and provides context about tasks
 */

import * as fs from "node:fs";
import * as path from "node:path";
import type { TaskContext } from "./types.js";

/**
 * Parse Tasks.md and extract all tasks
 */
export async function parseTasks(vaultRoot: string): Promise<TaskContext[]> {
  const tasksPath = path.join(vaultRoot, "03-Tasks", "Tasks.md");
  
  if (!fs.existsSync(tasksPath)) {
    return [];
  }

  const content = fs.readFileSync(tasksPath, "utf-8");
  const tasks: TaskContext[] = [];

  // Parse task lines
  // Format: - [ ] Task title ^task-20260204-001 [priority] [due:YYYY-MM-DD] [pillar:name]
  const taskPattern = /^- \[([ xX])\] (.+?)(?:\s+\^(task-\d{8}-\d{3}))?(?:\s+\[(P[0-3])\])?(?:\s+due:(\d{4}-\d{2}-\d{2}))?(?:\s+pillar:([^\n]+))?$/gm;

  let match;
  while ((match = taskPattern.exec(content)) !== null) {
    const [, checkbox, title, taskId, priority, dueDate, pillar] = match;
    
    // Determine status from checkbox
    let status: TaskContext["status"] = "n";
    if (checkbox === "x" || checkbox === "X") {
      status = "d";
    } else if (title.toLowerCase().includes("[blocked]") || title.toLowerCase().includes("blocked:")) {
      status = "b";
    } else if (title.toLowerCase().includes("[started]") || title.toLowerCase().includes("wip")) {
      status = "s";
    }

    tasks.push({
      id: taskId || generateTaskId(),
      title: cleanTaskTitle(title),
      status,
      priority: (priority as TaskContext["priority"]) || "P2",
      pillar: pillar?.trim() || null,
      dueDate: dueDate || null,
      context: null,
    });
  }

  return tasks;
}

/**
 * Clean task title by removing status markers
 */
function cleanTaskTitle(title: string): string {
  return title
    .replace(/\[blocked\]/gi, "")
    .replace(/\[started\]/gi, "")
    .replace(/blocked:/gi, "")
    .replace(/wip/gi, "")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Generate a task ID if none exists
 */
function generateTaskId(): string {
  const date = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  // Use timestamp-based counter to avoid collisions with existing IDs
  const counter = (Date.now() % 900) + 100; // 100-999 range, unlikely to collide
  return `task-${date}-${counter.toString().padStart(3, "0")}`;
}

/**
 * Get open tasks (not done)
 */
export async function getOpenTasks(vaultRoot: string): Promise<TaskContext[]> {
  const allTasks = await parseTasks(vaultRoot);
  return allTasks.filter((t) => t.status !== "d");
}

/**
 * Get overdue tasks
 */
export async function getOverdueTasks(vaultRoot: string): Promise<TaskContext[]> {
  const today = new Date().toISOString().split("T")[0];
  const openTasks = await getOpenTasks(vaultRoot);
  return openTasks.filter((t) => t.dueDate && t.dueDate < today);
}

/**
 * Get P0 tasks
 */
export async function getP0Tasks(vaultRoot: string): Promise<TaskContext[]> {
  const openTasks = await getOpenTasks(vaultRoot);
  return openTasks.filter((t) => t.priority === "P0");
}

/**
 * Find task references in text
 */
export async function findTaskReferences(text: string, vaultRoot: string): Promise<TaskContext[]> {
  const allTasks = await parseTasks(vaultRoot);
  const found: TaskContext[] = [];
  const textLower = text.toLowerCase();

  // Match by task ID
  const idPattern = /task-\d{8}-\d{3}/g;
  const idMatches = text.match(idPattern) || [];
  
  for (const id of idMatches) {
    const task = allTasks.find((t) => t.id === id);
    if (task && !found.some((f) => f.id === task.id)) {
      found.push(task);
    }
  }

  // Match by title keywords (only for explicit task discussions)
  if (textLower.includes("task") || textLower.includes("todo") || textLower.includes("action item")) {
    for (const task of allTasks) {
      const titleWords = task.title.toLowerCase().split(/\s+/);
      // Require at least 3 words to match to avoid false positives
      const matchedWords = titleWords.filter((word) => word.length > 3 && textLower.includes(word));
      if (matchedWords.length >= 2 && !found.some((f) => f.id === task.id)) {
        found.push(task);
      }
    }
  }

  return found.slice(0, 5); // Limit to 5 tasks
}

/**
 * Format task contexts for injection
 */
export function formatTaskContext(tasks: TaskContext[]): string {
  if (tasks.length === 0) return "";

  const lines: string[] = ["## Referenced Tasks"];

  for (const task of tasks) {
    const statusEmoji = {
      n: "⬜",
      s: "🔄",
      b: "🚫",
      d: "✅",
    }[task.status];

    lines.push(
      `\n- ${statusEmoji} **[${task.priority}]** ${task.title}` +
        (task.dueDate ? ` (due: ${task.dueDate})` : "") +
        (task.pillar ? ` [${task.pillar}]` : "") +
        `\n  ID: \`${task.id}\``
    );
  }

  return lines.join("\n");
}

/**
 * Get task summary for status display
 */
export async function getTaskSummary(vaultRoot: string): Promise<{
  open: number;
  total: number;
  overdue: number;
  p0Count: number;
}> {
  const allTasks = await parseTasks(vaultRoot);
  const openTasks = allTasks.filter((t) => t.status !== "d");
  const today = new Date().toISOString().split("T")[0];

  return {
    open: openTasks.length,
    total: allTasks.length,
    overdue: openTasks.filter((t) => t.dueDate && t.dueDate < today).length,
    p0Count: openTasks.filter((t) => t.priority === "P0").length,
  };
}
