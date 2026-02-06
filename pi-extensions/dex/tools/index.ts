/**
 * Custom Tools Module
 * Pi-exclusive tools that enhance Dex functionality
 * 
 * These tools are ONLY available to Pi users - they don't affect
 * Cursor or Claude Desktop users at all.
 */

import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { StringEnum } from "@mariozechner/pi-ai";
import * as fs from "node:fs";
import * as path from "node:path";
import {
  parseTasks,
  getOpenTasks,
  getTaskSummary,
  getOverdueTasks,
  getP0Tasks,
} from "../context/task.js";
import type { TaskContext } from "../context/types.js";

/**
 * Register all Dex tools
 */
export function registerTools(pi: ExtensionAPI, vaultRoot: string): void {
  // ============================================================
  // VAULT SEARCH TOOL
  // Full-text search across the entire vault
  // ============================================================
  pi.registerTool({
    name: "pi_vault_search",
    label: "Pi Vault Search",
    description:
      "Search across the entire Dex vault for content, people, projects, or tasks. " +
      "Returns relevant excerpts with file paths.",
    parameters: Type.Object({
      query: Type.String({ description: "Search query (keywords or phrases)" }),
      type: Type.Optional(
        StringEnum([
          "all",
          "people",
          "companies",
          "projects",
          "tasks",
          "meetings",
          "notes",
        ] as const)
      ),
      limit: Type.Optional(
        Type.Number({ description: "Max results (default: 10)", default: 10 })
      ),
    }),

    async execute(toolCallId, params, signal, onUpdate, ctx) {
      onUpdate?.({
        content: [{ type: "text", text: "Searching vault..." }],
      });

      try {
        const results = await searchVault(
          vaultRoot,
          params.query,
          params.type || "all",
          params.limit || 10
        );

        if (results.length === 0) {
          return {
            content: [
              { type: "text", text: `No results found for "${params.query}"` },
            ],
            details: { count: 0, query: params.query },
          };
        }

        const formatted = results
          .map(
            (r) =>
              `### ${r.title}\n**Type:** ${r.type} | **File:** ${r.path}\n\n${r.excerpt}\n`
          )
          .join("\n---\n\n");

        return {
          content: [
            {
              type: "text",
              text: `Found ${results.length} results for "${params.query}":\n\n${formatted}`,
            },
          ],
          details: { count: results.length, results },
        };
      } catch (e) {
        return {
          content: [{ type: "text", text: `Search failed: ${e}` }],
          details: { error: String(e) },
          isError: true,
        };
      }
    },
  });

  // ============================================================
  // DEX TASK TOOL
  // Task operations for Pi users
  // ============================================================
  pi.registerTool({
    name: "pi_dex_task",
    label: "Pi Dex Task",
    description:
      "Create, complete, or list tasks in Dex. " +
      "Use action='list' to see open tasks, 'create' to add new, 'complete' to mark done.",
    parameters: Type.Object({
      action: StringEnum(["create", "complete", "list", "suggest"] as const),
      task_id: Type.Optional(
        Type.String({
          description: "Task ID for complete action (e.g., task-20260204-001)",
        })
      ),
      title: Type.Optional(
        Type.String({ description: "Task title for create action" })
      ),
      priority: Type.Optional(StringEnum(["P0", "P1", "P2", "P3"] as const)),
      pillar: Type.Optional(Type.String({ description: "Strategic pillar" })),
      context: Type.Optional(
        Type.String({ description: "Additional context for the task" })
      ),
    }),

    async execute(toolCallId, params, signal, onUpdate, ctx) {
      try {
        switch (params.action) {
          case "create": {
            if (!params.title) {
              return {
                content: [
                  { type: "text", text: "Error: title required for create" },
                ],
                isError: true,
              };
            }
            const newTask = await createTask(vaultRoot, {
              title: params.title,
              priority: params.priority || "P2",
              pillar: params.pillar || null,
              context: params.context || null,
            });
            return {
              content: [
                {
                  type: "text",
                  text: `✅ Created task: ${newTask.id}\n\n**${params.title}** [${params.priority || "P2"}]`,
                },
              ],
              details: newTask,
            };
          }

          case "complete": {
            if (!params.task_id) {
              return {
                content: [
                  { type: "text", text: "Error: task_id required for complete" },
                ],
                isError: true,
              };
            }
            const completed = await completeTask(vaultRoot, params.task_id);
            if (!completed) {
              return {
                content: [
                  {
                    type: "text",
                    text: `Task ${params.task_id} not found`,
                  },
                ],
                isError: true,
              };
            }
            return {
              content: [
                {
                  type: "text",
                  text: `✅ Completed: ${params.task_id}\n\n~~${completed.title}~~`,
                },
              ],
              details: completed,
            };
          }

          case "list": {
            const tasks = await getOpenTasks(vaultRoot);
            const filtered = params.priority
              ? tasks.filter((t) => t.priority === params.priority)
              : tasks;

            if (filtered.length === 0) {
              return {
                content: [
                  {
                    type: "text",
                    text: params.priority
                      ? `No open ${params.priority} tasks`
                      : "No open tasks",
                  },
                ],
                details: { count: 0 },
              };
            }

            const formatted = formatTaskList(filtered);
            return {
              content: [{ type: "text", text: formatted }],
              details: { count: filtered.length },
            };
          }

          case "suggest": {
            const summary = await getTaskSummary(vaultRoot);
            const p0Tasks = await getP0Tasks(vaultRoot);
            const overdue = await getOverdueTasks(vaultRoot);

            let suggestions: string[] = [];

            if (overdue.length > 0) {
              suggestions.push(`⚠️ **${overdue.length} overdue tasks** need attention`);
              overdue.slice(0, 3).forEach((t) => {
                suggestions.push(`  - ${t.title} (due: ${t.dueDate})`);
              });
            }

            if (p0Tasks.length > 0) {
              suggestions.push(`\n🔴 **${p0Tasks.length} P0 tasks** to focus on:`);
              p0Tasks.slice(0, 3).forEach((t) => {
                suggestions.push(`  - ${t.title}`);
              });
            }

            if (suggestions.length === 0) {
              suggestions.push("✅ All clear! No urgent tasks.");
            }

            return {
              content: [{ type: "text", text: suggestions.join("\n") }],
              details: summary,
            };
          }

          default:
            return {
              content: [
                { type: "text", text: `Unknown action: ${params.action}` },
              ],
              isError: true,
            };
        }
      } catch (e) {
        return {
          content: [{ type: "text", text: `Task operation failed: ${e}` }],
          details: { error: String(e) },
          isError: true,
        };
      }
    },
  });

  // ============================================================
  // QUICK CAPTURE TOOL
  // Fast capture to inbox
  // ============================================================
  pi.registerTool({
    name: "pi_quick_capture",
    label: "Pi Quick Capture",
    description:
      "Quickly capture an idea, note, or task to the inbox. " +
      "Content will be saved with timestamp for later triage.",
    parameters: Type.Object({
      content: Type.String({ description: "Content to capture" }),
      type: StringEnum(["idea", "note", "task", "meeting"] as const),
      title: Type.Optional(Type.String({ description: "Optional title" })),
      tags: Type.Optional(Type.Array(Type.String())),
    }),

    async execute(toolCallId, params, signal, onUpdate, ctx) {
      try {
        const result = await captureToInbox(vaultRoot, {
          content: params.content,
          type: params.type,
          title: params.title,
          tags: params.tags,
        });

        return {
          content: [
            {
              type: "text",
              text: `📝 Captured to: ${result.relativePath}\n\nTitle: ${result.title}`,
            },
          ],
          details: result,
        };
      } catch (e) {
        return {
          content: [{ type: "text", text: `Capture failed: ${e}` }],
          details: { error: String(e) },
          isError: true,
        };
      }
    },
  });

  // ============================================================
  // DEX STATUS TOOL
  // Quick overview of Dex state
  // ============================================================
  pi.registerTool({
    name: "pi_dex_status",
    label: "Pi Dex Status",
    description: "Get a quick overview of Dex state: tasks, inbox, and recent activity.",
    parameters: Type.Object({}),

    async execute(toolCallId, params, signal, onUpdate, ctx) {
      try {
        const summary = await getTaskSummary(vaultRoot);
        const inboxCount = await countInboxItems(vaultRoot);

        const status = [
          "# Dex Status\n",
          `📋 **Tasks:** ${summary.open} open / ${summary.total} total`,
          summary.overdue > 0
            ? `  ⚠️ ${summary.overdue} overdue`
            : "  ✅ None overdue",
          summary.p0Count > 0
            ? `  🔴 ${summary.p0Count} P0`
            : "  No P0 tasks",
          "",
          `📥 **Inbox:** ${inboxCount} items to triage`,
          "",
          `🕐 **Now:** ${new Date().toLocaleString()}`,
        ].join("\n");

        return {
          content: [{ type: "text", text: status }],
          details: { tasks: summary, inbox: inboxCount },
        };
      } catch (e) {
        return {
          content: [{ type: "text", text: `Status check failed: ${e}` }],
          details: { error: String(e) },
          isError: true,
        };
      }
    },
  });
}

// ============================================================
// HELPER FUNCTIONS
// ============================================================

interface SearchResult {
  title: string;
  path: string;
  type: string;
  excerpt: string;
  score: number;
}

async function searchVault(
  vaultRoot: string,
  query: string,
  type: string,
  limit: number
): Promise<SearchResult[]> {
  const results: SearchResult[] = [];
  const queryLower = query.toLowerCase();
  const queryWords = queryLower.split(/\s+/).filter((w) => w.length > 2);

  // Define search paths based on type
  const searchPaths: { dir: string; type: string }[] = [];
  
  if (type === "all" || type === "people") {
    searchPaths.push({ dir: "05-Areas/People", type: "person" });
  }
  if (type === "all" || type === "companies") {
    searchPaths.push({ dir: "05-Areas/Companies", type: "company" });
  }
  if (type === "all" || type === "projects") {
    searchPaths.push({ dir: "04-Projects", type: "project" });
  }
  if (type === "all" || type === "meetings") {
    searchPaths.push({ dir: "00-Inbox/Meetings", type: "meeting" });
  }
  if (type === "all" || type === "notes") {
    searchPaths.push({ dir: "00-Inbox/Ideas", type: "note" });
  }

  for (const { dir, type: fileType } of searchPaths) {
    const fullDir = path.join(vaultRoot, dir);
    if (!fs.existsSync(fullDir)) continue;

    const files = walkDir(fullDir);
    for (const file of files) {
      if (!file.endsWith(".md")) continue;

      try {
        const content = fs.readFileSync(file, "utf-8");
        const contentLower = content.toLowerCase();

        // Score based on query match
        let score = 0;
        for (const word of queryWords) {
          if (contentLower.includes(word)) {
            score += 1;
          }
        }

        if (score > 0) {
          // Extract excerpt around first match
          const firstMatchIndex = contentLower.indexOf(queryWords[0] || queryLower);
          const excerptStart = Math.max(0, firstMatchIndex - 50);
          const excerptEnd = Math.min(content.length, firstMatchIndex + 200);
          let excerpt = content.slice(excerptStart, excerptEnd).trim();
          if (excerptStart > 0) excerpt = "..." + excerpt;
          if (excerptEnd < content.length) excerpt = excerpt + "...";

          results.push({
            title: path.basename(file, ".md").replace(/_/g, " "),
            path: path.relative(vaultRoot, file),
            type: fileType,
            excerpt,
            score,
          });
        }
      } catch (e) {
        // Skip files we can't read
      }
    }
  }

  // Sort by score descending, limit results
  return results.sort((a, b) => b.score - a.score).slice(0, limit);
}

function walkDir(dir: string): string[] {
  const files: string[] = [];
  
  try {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        files.push(...walkDir(fullPath));
      } else {
        files.push(fullPath);
      }
    }
  } catch (e) {
    // Skip directories we can't read
  }

  return files;
}

async function createTask(
  vaultRoot: string,
  task: {
    title: string;
    priority: string;
    pillar: string | null;
    context: string | null;
  }
): Promise<TaskContext> {
  const tasksPath = path.join(vaultRoot, "03-Tasks", "Tasks.md");
  
  // Generate task ID
  const date = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  const existingTasks = await parseTasks(vaultRoot);
  const todayTasks = existingTasks.filter((t) => t.id.includes(date));
  const num = (todayTasks.length + 1).toString().padStart(3, "0");
  const taskId = `task-${date}-${num}`;

  // Build task line
  let taskLine = `- [ ] ${task.title} ^${taskId}`;
  if (task.priority) taskLine += ` [${task.priority}]`;
  if (task.pillar) taskLine += ` pillar:${task.pillar}`;

  // Append to Tasks.md
  let content = fs.existsSync(tasksPath)
    ? fs.readFileSync(tasksPath, "utf-8")
    : "# Tasks\n\n";

  // Find the right section or append at end
  const inboxSection = content.indexOf("## Inbox");
  if (inboxSection !== -1) {
    const nextSection = content.indexOf("\n## ", inboxSection + 1);
    const insertPos = nextSection !== -1 ? nextSection : content.length;
    content =
      content.slice(0, insertPos) + "\n" + taskLine + content.slice(insertPos);
  } else {
    content += "\n" + taskLine;
  }

  fs.writeFileSync(tasksPath, content);

  return {
    id: taskId,
    title: task.title,
    status: "n",
    priority: task.priority as TaskContext["priority"],
    pillar: task.pillar,
    dueDate: null,
    context: task.context,
  };
}

async function completeTask(
  vaultRoot: string,
  taskId: string
): Promise<TaskContext | null> {
  const tasksPath = path.join(vaultRoot, "03-Tasks", "Tasks.md");
  if (!fs.existsSync(tasksPath)) return null;

  let content = fs.readFileSync(tasksPath, "utf-8");
  const taskPattern = new RegExp(
    `^(- \\[) \\] (.+?)\\s*\\^${taskId}(.*)$`,
    "m"
  );
  const match = content.match(taskPattern);

  if (!match) return null;

  // Mark as complete with timestamp
  const timestamp = new Date().toISOString().slice(0, 16).replace("T", " ");
  content = content.replace(
    taskPattern,
    `$1x] $2 ^${taskId}$3 ✅ ${timestamp}`
  );

  fs.writeFileSync(tasksPath, content);

  return {
    id: taskId,
    title: match[2],
    status: "d",
    priority: "P2",
    pillar: null,
    dueDate: null,
    context: null,
  };
}

function formatTaskList(tasks: TaskContext[]): string {
  const lines = ["# Open Tasks\n"];

  // Group by priority
  const byPriority: Record<string, TaskContext[]> = {
    P0: [],
    P1: [],
    P2: [],
    P3: [],
  };

  for (const task of tasks) {
    byPriority[task.priority]?.push(task);
  }

  for (const priority of ["P0", "P1", "P2", "P3"]) {
    const priorityTasks = byPriority[priority];
    if (priorityTasks && priorityTasks.length > 0) {
      const emoji = { P0: "🔴", P1: "🟠", P2: "🟡", P3: "🟢" }[priority];
      lines.push(`\n## ${emoji} ${priority} (${priorityTasks.length})\n`);
      for (const task of priorityTasks) {
        const dueStr = task.dueDate ? ` (due: ${task.dueDate})` : "";
        const pillarStr = task.pillar ? ` [${task.pillar}]` : "";
        lines.push(`- [ ] ${task.title}${dueStr}${pillarStr}`);
        lines.push(`  ID: \`${task.id}\``);
      }
    }
  }

  return lines.join("\n");
}

async function captureToInbox(
  vaultRoot: string,
  capture: {
    content: string;
    type: string;
    title?: string;
    tags?: string[];
  }
): Promise<{ path: string; relativePath: string; title: string }> {
  // Determine directory based on type
  const typeDir = {
    idea: "Ideas",
    note: "Ideas",
    task: "Tasks",
    meeting: "Meetings",
  }[capture.type] || "Ideas";

  const inboxDir = path.join(vaultRoot, "00-Inbox", typeDir);
  if (!fs.existsSync(inboxDir)) {
    fs.mkdirSync(inboxDir, { recursive: true });
  }

  // Generate filename
  const timestamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const title =
    capture.title ||
    capture.content.slice(0, 50).replace(/[^a-zA-Z0-9\s]/g, "").trim() ||
    "capture";
  const safeTitle = title.replace(/\s+/g, "_").slice(0, 50);
  const filename = `${timestamp}-${safeTitle}.md`;
  const filePath = path.join(inboxDir, filename);

  // Build content
  const lines = [
    "---",
    `type: ${capture.type}`,
    `captured: ${new Date().toISOString()}`,
    capture.tags?.length ? `tags: [${capture.tags.join(", ")}]` : null,
    "---",
    "",
    `# ${title}`,
    "",
    capture.content,
  ].filter((l) => l !== null);

  fs.writeFileSync(filePath, lines.join("\n"));

  return {
    path: filePath,
    relativePath: path.relative(vaultRoot, filePath),
    title,
  };
}

async function countInboxItems(vaultRoot: string): Promise<number> {
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
