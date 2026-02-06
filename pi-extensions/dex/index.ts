/**
 * Dex for PI - The Complete Extension
 * 
 * Transforms Dex into a proactive, parallel, intelligent productivity system.
 * 
 * Superpowers:
 * 1. Proactive Context Injection - Know before you ask
 * 2. Parallel Sub-Agent Processing - 4x faster operations
 * 3. Tool Composability - Internal chaining, minimal token cost
 * 4. Rich Interactivity - Streaming updates, visual feedback
 * 5. Dynamic Adaptation - Smart model routing
 */

import * as fs from "node:fs";
import * as path from "node:path";
import * as os from "node:os";
import { spawn, exec } from "node:child_process";
import { promisify } from "node:util";
import type { ExtensionAPI, ExtensionContext } from "@mariozechner/pi-coding-agent";
import { Type, type Static } from "@sinclair/typebox";
import { StringEnum } from "@mariozechner/pi-ai";
import { Text, Container, Markdown } from "@mariozechner/pi-tui";
import { registerOrchestratorTools } from "./orchestrator.js";
import { registerCommitmentDetector } from "./commitment-detector.js";
import { registerModelRouter } from "./model-router.js";

const execAsync = promisify(exec);

// ============================================================================
// CONFIGURATION
// ============================================================================

const VAULT_PATH = process.env.VAULT_PATH || "/Users/dave/Claudesidian";
const PEOPLE_PATH = path.join(VAULT_PATH, "05-Areas/People");
const COMPANIES_PATH = path.join(VAULT_PATH, "05-Areas/Companies");
const TASKS_PATH = path.join(VAULT_PATH, "03-Tasks/Tasks.md");
const INBOX_PATH = path.join(VAULT_PATH, "00-Inbox");
const DAILY_PLANS_PATH = path.join(VAULT_PATH, "07-Archives/Plans");

// ============================================================================
// UTILITIES
// ============================================================================

function fileExists(filePath: string): boolean {
  try {
    return fs.existsSync(filePath);
  } catch {
    return false;
  }
}

function readFileSync(filePath: string): string | null {
  try {
    return fs.readFileSync(filePath, "utf-8");
  } catch {
    return null;
  }
}

function writeFileSync(filePath: string, content: string): boolean {
  try {
    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(filePath, content, "utf-8");
    return true;
  } catch {
    return false;
  }
}

function formatTimestamp(): string {
  return new Date().toISOString().replace("T", " ").slice(0, 19);
}

function formatDate(): string {
  return new Date().toISOString().slice(0, 10);
}

// ============================================================================
// PERSON DETECTION & CONTEXT
// ============================================================================

interface PersonContext {
  name: string;
  filePath: string;
  role?: string;
  company?: string;
  lastMeeting?: string;
  openTasks: string[];
  recentContext: string;
}

function findPersonFiles(): Map<string, string> {
  const personMap = new Map<string, string>();
  
  const scanDir = (dir: string) => {
    if (!fs.existsSync(dir)) return;
    try {
      const entries = fs.readdirSync(dir, { withFileTypes: true });
      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          scanDir(fullPath);
        } else if (entry.name.endsWith(".md")) {
          // Extract name from filename: "Sarah_Chen.md" -> "sarah chen"
          const name = entry.name.replace(".md", "").replace(/_/g, " ").toLowerCase();
          personMap.set(name, fullPath);
          // Also add first name only
          const firstName = name.split(" ")[0];
          if (!personMap.has(firstName)) {
            personMap.set(firstName, fullPath);
          }
        }
      }
    } catch {}
  };
  
  scanDir(PEOPLE_PATH);
  return personMap;
}

function detectPeopleInText(text: string): string[] {
  const personFiles = findPersonFiles();
  const detected: string[] = [];
  const textLower = text.toLowerCase();
  
  for (const [name, filePath] of personFiles) {
    // Match whole words only
    const regex = new RegExp(`\\b${name}\\b`, "i");
    if (regex.test(textLower) && !detected.includes(filePath)) {
      detected.push(filePath);
    }
  }
  
  return detected;
}

function loadPersonContext(filePath: string): PersonContext | null {
  const content = readFileSync(filePath);
  if (!content) return null;
  
  const name = path.basename(filePath, ".md").replace(/_/g, " ");
  
  // Extract key fields from person page
  let role: string | undefined;
  let company: string | undefined;
  let lastMeeting: string | undefined;
  const openTasks: string[] = [];
  
  // Parse role/title
  const roleMatch = content.match(/\*\*Role\*\*:\s*(.+)/i) || content.match(/Role:\s*(.+)/i);
  if (roleMatch) role = roleMatch[1].trim();
  
  // Parse company
  const companyMatch = content.match(/\*\*Company\*\*:\s*(.+)/i) || content.match(/Company:\s*(.+)/i);
  if (companyMatch) company = companyMatch[1].trim();
  
  // Find open tasks mentioning this person
  const tasksContent = readFileSync(TASKS_PATH);
  if (tasksContent) {
    const nameLower = name.toLowerCase();
    const lines = tasksContent.split("\n");
    for (const line of lines) {
      if (line.includes("- [ ]") && line.toLowerCase().includes(nameLower)) {
        openTasks.push(line.replace(/^[\s-]*\[\s*\]\s*/, "").trim());
      }
    }
  }
  
  // Get recent context (last 500 chars of page)
  const recentContext = content.slice(-1500);
  
  return {
    name,
    filePath,
    role,
    company,
    lastMeeting,
    openTasks,
    recentContext
  };
}

function formatPersonContexts(contexts: PersonContext[]): string {
  if (contexts.length === 0) return "";
  
  let output = "<dex_person_context>\n";
  output += "The following people were mentioned. Here's relevant context:\n\n";
  
  for (const ctx of contexts) {
    output += `## ${ctx.name}\n`;
    if (ctx.role) output += `**Role:** ${ctx.role}\n`;
    if (ctx.company) output += `**Company:** ${ctx.company}\n`;
    if (ctx.openTasks.length > 0) {
      output += `**Open tasks involving ${ctx.name}:**\n`;
      for (const task of ctx.openTasks.slice(0, 5)) {
        output += `- ${task}\n`;
      }
    }
    output += `\n**Recent context:**\n${ctx.recentContext.slice(0, 800)}\n\n`;
  }
  
  output += "</dex_person_context>";
  return output;
}

// ============================================================================
// COMPANY DETECTION & CONTEXT
// ============================================================================

interface CompanyContext {
  name: string;
  filePath: string;
  industry?: string;
  contacts: string[];
  recentContext: string;
}

function findCompanyFiles(): Map<string, string> {
  const companyMap = new Map<string, string>();
  
  if (!fs.existsSync(COMPANIES_PATH)) return companyMap;
  
  try {
    const entries = fs.readdirSync(COMPANIES_PATH, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.name.endsWith(".md")) {
        const name = entry.name.replace(".md", "").replace(/_/g, " ").toLowerCase();
        companyMap.set(name, path.join(COMPANIES_PATH, entry.name));
      }
    }
  } catch {}
  
  return companyMap;
}

function detectCompaniesInText(text: string): string[] {
  const companyFiles = findCompanyFiles();
  const detected: string[] = [];
  const textLower = text.toLowerCase();
  
  for (const [name, filePath] of companyFiles) {
    const regex = new RegExp(`\\b${name}\\b`, "i");
    if (regex.test(textLower) && !detected.includes(filePath)) {
      detected.push(filePath);
    }
  }
  
  return detected;
}

function loadCompanyContext(filePath: string): CompanyContext | null {
  const content = readFileSync(filePath);
  if (!content) return null;
  
  const name = path.basename(filePath, ".md").replace(/_/g, " ");
  const contacts: string[] = [];
  
  // Extract contacts mentioned
  const contactMatches = content.matchAll(/\[\[([^\]]+)\]\]/g);
  for (const match of contactMatches) {
    if (match[1] && !contacts.includes(match[1])) {
      contacts.push(match[1]);
    }
  }
  
  return {
    name,
    filePath,
    contacts,
    recentContext: content.slice(-1000)
  };
}

function formatCompanyContexts(contexts: CompanyContext[]): string {
  if (contexts.length === 0) return "";
  
  let output = "<dex_company_context>\n";
  output += "The following companies were mentioned. Here's relevant context:\n\n";
  
  for (const ctx of contexts) {
    output += `## ${ctx.name}\n`;
    if (ctx.contacts.length > 0) {
      output += `**Known contacts:** ${ctx.contacts.slice(0, 5).join(", ")}\n`;
    }
    output += `\n**Recent context:**\n${ctx.recentContext.slice(0, 600)}\n\n`;
  }
  
  output += "</dex_company_context>";
  return output;
}

// ============================================================================
// TASK CONTEXT
// ============================================================================

interface TaskSummary {
  p0Tasks: string[];
  p1Tasks: string[];
  overdueTasks: string[];
  startedTasks: string[];
  totalOpen: number;
}

function getTaskSummary(): TaskSummary {
  const content = readFileSync(TASKS_PATH);
  const summary: TaskSummary = {
    p0Tasks: [],
    p1Tasks: [],
    overdueTasks: [],
    startedTasks: [],
    totalOpen: 0
  };
  
  if (!content) return summary;
  
  const lines = content.split("\n");
  const today = formatDate();
  
  for (const line of lines) {
    if (!line.includes("- [ ]")) continue;
    
    summary.totalOpen++;
    const taskText = line.replace(/^[\s-]*\[\s*\]\s*/, "").trim();
    
    if (line.includes("#P0") || line.includes("P0:")) {
      summary.p0Tasks.push(taskText);
    } else if (line.includes("#P1") || line.includes("P1:")) {
      summary.p1Tasks.push(taskText);
    }
    
    // Check for started tasks
    if (line.includes("🔄") || line.includes("[started]")) {
      summary.startedTasks.push(taskText);
    }
    
    // Check for overdue (has date before today)
    const dateMatch = line.match(/(\d{4}-\d{2}-\d{2})/);
    if (dateMatch && dateMatch[1] < today) {
      summary.overdueTasks.push(taskText);
    }
  }
  
  return summary;
}

function formatTaskContext(): string {
  const summary = getTaskSummary();
  
  if (summary.totalOpen === 0) return "";
  
  let output = "<dex_task_context>\n";
  output += `**Task Overview:** ${summary.totalOpen} open tasks\n\n`;
  
  if (summary.p0Tasks.length > 0) {
    output += "**P0 (Critical):**\n";
    for (const task of summary.p0Tasks.slice(0, 3)) {
      output += `- ${task}\n`;
    }
    output += "\n";
  }
  
  if (summary.overdueTasks.length > 0) {
    output += "**⚠️ Overdue:**\n";
    for (const task of summary.overdueTasks.slice(0, 3)) {
      output += `- ${task}\n`;
    }
    output += "\n";
  }
  
  if (summary.startedTasks.length > 0) {
    output += "**In Progress:**\n";
    for (const task of summary.startedTasks.slice(0, 3)) {
      output += `- ${task}\n`;
    }
  }
  
  output += "</dex_task_context>";
  return output;
}

// ============================================================================
// MEETING DETECTION
// ============================================================================

function detectMeetingIntent(text: string): boolean {
  const meetingKeywords = [
    "meeting with", "call with", "1:1 with", "sync with",
    "prep for", "prepare for", "get ready for",
    "my meeting", "the meeting", "our meeting",
    "tomorrow's meeting", "today's meeting"
  ];
  
  const textLower = text.toLowerCase();
  return meetingKeywords.some(kw => textLower.includes(kw));
}

// ============================================================================
// NATIVE TOOLS
// ============================================================================

const VaultSearchParams = Type.Object({
  query: Type.String({ description: "Search query (keywords or phrases)" }),
  type: Type.Optional(StringEnum(["all", "people", "companies", "projects", "tasks", "meetings", "notes"] as const)),
  limit: Type.Optional(Type.Number({ default: 10, description: "Max results" }))
});

const TaskParams = Type.Object({
  action: StringEnum(["create", "complete", "list", "suggest"] as const),
  title: Type.Optional(Type.String({ description: "Task title for create action" })),
  task_id: Type.Optional(Type.String({ description: "Task ID for complete action" })),
  priority: Type.Optional(StringEnum(["P0", "P1", "P2", "P3"] as const)),
  pillar: Type.Optional(Type.String({ description: "Strategic pillar" })),
  context: Type.Optional(Type.String({ description: "Additional context" }))
});

const QuickCaptureParams = Type.Object({
  content: Type.String({ description: "Content to capture" }),
  type: StringEnum(["idea", "note", "task", "meeting"] as const),
  title: Type.Optional(Type.String({ description: "Optional title" })),
  tags: Type.Optional(Type.Array(Type.String()))
});

const CalendarParams = Type.Object({
  action: StringEnum(["today", "upcoming", "list_calendars", "next"] as const),
  calendar: Type.Optional(Type.String({ description: "Calendar name" })),
  days: Type.Optional(Type.Number({ default: 7 })),
  start_date: Type.Optional(Type.String({ description: "Start date YYYY-MM-DD" }))
});

// ============================================================================
// VAULT SEARCH IMPLEMENTATION
// ============================================================================

interface SearchResult {
  path: string;
  title: string;
  excerpt: string;
  score: number;
}

async function searchVault(query: string, type: string = "all", limit: number = 10): Promise<SearchResult[]> {
  const results: SearchResult[] = [];
  const queryLower = query.toLowerCase();
  const queryTerms = queryLower.split(/\s+/);
  
  const searchPaths: string[] = [];
  
  if (type === "all" || type === "people") {
    searchPaths.push(PEOPLE_PATH);
  }
  if (type === "all" || type === "companies") {
    searchPaths.push(COMPANIES_PATH);
  }
  if (type === "all" || type === "projects") {
    searchPaths.push(path.join(VAULT_PATH, "04-Projects"));
  }
  if (type === "all" || type === "meetings") {
    searchPaths.push(path.join(VAULT_PATH, "00-Inbox/Meetings"));
  }
  if (type === "all" || type === "notes") {
    searchPaths.push(path.join(VAULT_PATH, "00-Inbox"));
  }
  if (type === "tasks") {
    // Just search tasks file
    const tasksContent = readFileSync(TASKS_PATH);
    if (tasksContent) {
      const lines = tasksContent.split("\n");
      for (const line of lines) {
        if (line.includes("- [ ]") && queryTerms.some(t => line.toLowerCase().includes(t))) {
          results.push({
            path: TASKS_PATH,
            title: "Task",
            excerpt: line.trim(),
            score: 1
          });
        }
      }
    }
    return results.slice(0, limit);
  }
  
  const scanDir = (dir: string) => {
    if (!fs.existsSync(dir)) return;
    try {
      const entries = fs.readdirSync(dir, { withFileTypes: true });
      for (const entry of entries) {
        const fullPath = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          scanDir(fullPath);
        } else if (entry.name.endsWith(".md")) {
          const content = readFileSync(fullPath);
          if (!content) continue;
          
          const contentLower = content.toLowerCase();
          const titleLower = entry.name.toLowerCase();
          
          // Score based on matches
          let score = 0;
          for (const term of queryTerms) {
            if (titleLower.includes(term)) score += 10;
            const matches = (contentLower.match(new RegExp(term, "g")) || []).length;
            score += matches;
          }
          
          if (score > 0) {
            // Extract excerpt around first match
            let excerpt = "";
            const firstTermIndex = contentLower.indexOf(queryTerms[0]);
            if (firstTermIndex >= 0) {
              const start = Math.max(0, firstTermIndex - 50);
              const end = Math.min(content.length, firstTermIndex + 150);
              excerpt = content.slice(start, end).replace(/\n/g, " ").trim();
              if (start > 0) excerpt = "..." + excerpt;
              if (end < content.length) excerpt += "...";
            }
            
            results.push({
              path: fullPath.replace(VAULT_PATH + "/", ""),
              title: entry.name.replace(".md", "").replace(/_/g, " "),
              excerpt,
              score
            });
          }
        }
      }
    } catch {}
  };
  
  for (const searchPath of searchPaths) {
    scanDir(searchPath);
  }
  
  // Sort by score and limit
  results.sort((a, b) => b.score - a.score);
  return results.slice(0, limit);
}

// ============================================================================
// TASK OPERATIONS
// ============================================================================

function generateTaskId(): string {
  const date = formatDate().replace(/-/g, "");
  const random = Math.floor(Math.random() * 1000).toString().padStart(3, "0");
  return `task-${date}-${random}`;
}

function createTask(title: string, priority: string = "P2", pillar?: string, context?: string): { success: boolean; taskId: string; message: string } {
  const tasksContent = readFileSync(TASKS_PATH) || "# Tasks\n\n";
  const taskId = generateTaskId();
  
  let taskLine = `- [ ] ${title} ^${taskId}`;
  if (priority) taskLine += ` #${priority}`;
  if (pillar) taskLine += ` #${pillar}`;
  
  // Find the right section or append at end
  const lines = tasksContent.split("\n");
  let insertIndex = lines.length;
  
  // Try to find a section matching priority
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes(`## ${priority}`) || lines[i].includes(`### ${priority}`)) {
      insertIndex = i + 1;
      break;
    }
  }
  
  lines.splice(insertIndex, 0, taskLine);
  
  if (writeFileSync(TASKS_PATH, lines.join("\n"))) {
    return { success: true, taskId, message: `Created task: ${title} (${taskId})` };
  }
  
  return { success: false, taskId: "", message: "Failed to write tasks file" };
}

function completeTask(taskId: string): { success: boolean; message: string } {
  const tasksContent = readFileSync(TASKS_PATH);
  if (!tasksContent) return { success: false, message: "Tasks file not found" };
  
  const lines = tasksContent.split("\n");
  let found = false;
  
  for (let i = 0; i < lines.length; i++) {
    if (lines[i].includes(taskId) && lines[i].includes("- [ ]")) {
      lines[i] = lines[i].replace("- [ ]", "- [x]") + ` ✅ ${formatTimestamp()}`;
      found = true;
      break;
    }
  }
  
  if (!found) return { success: false, message: `Task ${taskId} not found or already complete` };
  
  if (writeFileSync(TASKS_PATH, lines.join("\n"))) {
    return { success: true, message: `Completed task ${taskId}` };
  }
  
  return { success: false, message: "Failed to update tasks file" };
}

function listTasks(priority?: string): string {
  const summary = getTaskSummary();
  let output = `## Open Tasks (${summary.totalOpen} total)\n\n`;
  
  if (summary.p0Tasks.length > 0) {
    output += "### P0 - Critical\n";
    summary.p0Tasks.forEach(t => output += `- [ ] ${t}\n`);
    output += "\n";
  }
  
  if (summary.p1Tasks.length > 0) {
    output += "### P1 - High Priority\n";
    summary.p1Tasks.forEach(t => output += `- [ ] ${t}\n`);
    output += "\n";
  }
  
  if (summary.overdueTasks.length > 0) {
    output += "### ⚠️ Overdue\n";
    summary.overdueTasks.forEach(t => output += `- [ ] ${t}\n`);
    output += "\n";
  }
  
  if (summary.startedTasks.length > 0) {
    output += "### 🔄 In Progress\n";
    summary.startedTasks.forEach(t => output += `- [ ] ${t}\n`);
  }
  
  return output;
}

// ============================================================================
// QUICK CAPTURE
// ============================================================================

function quickCapture(content: string, type: string, title?: string, tags?: string[]): { success: boolean; path: string; message: string } {
  const timestamp = formatTimestamp();
  const dateStr = formatDate();
  
  let targetDir: string;
  let filename: string;
  
  switch (type) {
    case "idea":
      targetDir = path.join(INBOX_PATH, "Ideas");
      filename = title ? `${dateStr} - ${title}.md` : `${dateStr} - Idea.md`;
      break;
    case "meeting":
      targetDir = path.join(INBOX_PATH, "Meetings");
      filename = title ? `${dateStr} - ${title}.md` : `${dateStr} - Meeting Notes.md`;
      break;
    case "task":
      // For tasks, create in tasks file
      const result = createTask(content, "P2");
      return { success: result.success, path: TASKS_PATH, message: result.message };
    default:
      targetDir = INBOX_PATH;
      filename = title ? `${dateStr} - ${title}.md` : `${dateStr} - Note.md`;
  }
  
  const filePath = path.join(targetDir, filename);
  
  let fileContent = `---\ncaptured: ${timestamp}\ntype: ${type}\n`;
  if (tags && tags.length > 0) {
    fileContent += `tags: [${tags.join(", ")}]\n`;
  }
  fileContent += `---\n\n${content}\n`;
  
  if (writeFileSync(filePath, fileContent)) {
    return { success: true, path: filePath.replace(VAULT_PATH + "/", ""), message: `Captured to ${filename}` };
  }
  
  return { success: false, path: "", message: "Failed to write file" };
}

// ============================================================================
// CALENDAR INTEGRATION (via AppleScript)
// ============================================================================

async function getCalendarEvents(action: string, calendar?: string, days: number = 7): Promise<string> {
  try {
    let script: string;
    
    if (action === "today") {
      script = `
        tell application "Calendar"
          set today to current date
          set tomorrow to today + 1 * days
          set eventList to {}
          repeat with cal in calendars
            ${calendar ? `if name of cal is "${calendar}" then` : ""}
            set calEvents to (every event of cal whose start date ≥ today and start date < tomorrow)
            repeat with evt in calEvents
              set eventInfo to (start date of evt as string) & " | " & (summary of evt) & " | " & (location of evt)
              set end of eventList to eventInfo
            end repeat
            ${calendar ? "end if" : ""}
          end repeat
          return eventList as string
        end tell
      `;
    } else if (action === "list_calendars") {
      script = `
        tell application "Calendar"
          set calNames to {}
          repeat with cal in calendars
            set end of calNames to name of cal
          end repeat
          return calNames as string
        end tell
      `;
    } else if (action === "next") {
      script = `
        tell application "Calendar"
          set now to current date
          set nextWeek to now + 7 * days
          set nextEvent to missing value
          set earliestDate to nextWeek
          repeat with cal in calendars
            ${calendar ? `if name of cal is "${calendar}" then` : ""}
            set calEvents to (every event of cal whose start date > now and start date < nextWeek)
            repeat with evt in calEvents
              if start date of evt < earliestDate then
                set earliestDate to start date of evt
                set nextEvent to evt
              end if
            end repeat
            ${calendar ? "end if" : ""}
          end repeat
          if nextEvent is not missing value then
            return (start date of nextEvent as string) & " | " & (summary of nextEvent)
          else
            return "No upcoming events"
          end if
        end tell
      `;
    } else {
      return "Unknown calendar action";
    }
    
    const { stdout } = await execAsync(`osascript -e '${script.replace(/'/g, "'\\''")}'`);
    return stdout.trim() || "No events found";
  } catch (error) {
    return `Calendar error: ${error}`;
  }
}

// ============================================================================
// STATUS TRACKING
// ============================================================================

interface DexStatus {
  tasksOpen: number;
  tasksP0: number;
  tasksOverdue: number;
  meetingsToday: number;
  nextMeeting?: string;
  weekDay: number;
  weekProgress: string;
}

async function getDexStatus(): Promise<DexStatus> {
  const taskSummary = getTaskSummary();
  const dayOfWeek = new Date().getDay();
  const weekDay = dayOfWeek === 0 ? 7 : dayOfWeek; // Monday = 1
  
  let meetingsToday = 0;
  let nextMeeting: string | undefined;
  
  try {
    const calendarOutput = await getCalendarEvents("today");
    meetingsToday = (calendarOutput.match(/\|/g) || []).length;
    
    const nextOutput = await getCalendarEvents("next");
    if (!nextOutput.includes("No upcoming")) {
      nextMeeting = nextOutput.split("|")[1]?.trim();
    }
  } catch {}
  
  return {
    tasksOpen: taskSummary.totalOpen,
    tasksP0: taskSummary.p0Tasks.length,
    tasksOverdue: taskSummary.overdueTasks.length,
    meetingsToday,
    nextMeeting,
    weekDay,
    weekProgress: `Day ${weekDay}/5`
  };
}

function formatStatusLine(status: DexStatus): string {
  const parts: string[] = [];
  
  if (status.tasksP0 > 0) {
    parts.push(`🔴 ${status.tasksP0} P0`);
  }
  
  if (status.tasksOverdue > 0) {
    parts.push(`⚠️ ${status.tasksOverdue} overdue`);
  }
  
  parts.push(`${status.tasksOpen} tasks`);
  
  if (status.meetingsToday > 0) {
    parts.push(`${status.meetingsToday} meetings`);
  }
  
  if (status.nextMeeting) {
    parts.push(`Next: ${status.nextMeeting.slice(0, 20)}`);
  }
  
  return parts.join(" | ");
}

// ============================================================================
// EXTENSION ENTRY POINT
// ============================================================================

export default function (pi: ExtensionAPI) {
  
  // =========================================================================
  // PROACTIVE CONTEXT INJECTION
  // =========================================================================
  
  pi.on("before_agent_start", async (event, ctx) => {
    const injections: string[] = [];
    
    // Detect and inject person context
    const personFiles = detectPeopleInText(event.prompt);
    if (personFiles.length > 0) {
      const contexts = personFiles
        .map(f => loadPersonContext(f))
        .filter((c): c is PersonContext => c !== null);
      
      if (contexts.length > 0) {
        injections.push(formatPersonContexts(contexts));
      }
    }
    
    // Detect and inject company context
    const companyFiles = detectCompaniesInText(event.prompt);
    if (companyFiles.length > 0) {
      const contexts = companyFiles
        .map(f => loadCompanyContext(f))
        .filter((c): c is CompanyContext => c !== null);
      
      if (contexts.length > 0) {
        injections.push(formatCompanyContexts(contexts));
      }
    }
    
    // Detect meeting intent and inject task context
    if (detectMeetingIntent(event.prompt)) {
      injections.push(formatTaskContext());
    }
    
    // If any injections, return them
    if (injections.length > 0) {
      return {
        message: {
          customType: "dex-context-injection",
          content: injections.join("\n\n"),
          display: false
        }
      };
    }
    
    return {};
  });
  
  // =========================================================================
  // REACTIVE CONTEXT (when reading files)
  // =========================================================================
  
  pi.on("tool_call", async (event, ctx) => {
    // When reading a person page, inject related context
    if (event.toolName === "read") {
      const pathArg = (event.input as any).path || (event.input as any).file_path || "";
      if (pathArg.includes("People/")) {
        // This is a person page read - could inject related context
        // For now, just log that we detected it
      }
    }
    
    return {};
  });
  
  // =========================================================================
  // SESSION LIFECYCLE
  // =========================================================================
  
  pi.on("session_start", async (_event, ctx) => {
    if (ctx.hasUI) {
      // Dashboard widget: week priorities + top tasks + focus time
      try {
        const dataLayer = await import("./data-layer.js");
        const dashboard = await import("./dashboard-widget.js");
        
        // 1. Get week priorities (up to 3)
        const weekPriorities = dataLayer.loadWeekPriorities();
        const weekPriorityItems: Array<{ text: string; completed: boolean }> = weekPriorities
          .slice(0, 3)
          .map((p) => ({
            text: p.goal,
            completed: p.progress >= 100,
          }));
        
        // 2. Get top tasks (P0s first, then fill with P1s/P2s up to 3)
        const allTasks = dataLayer.loadTasks();
        const p0Tasks = allTasks.filter((t) => t.priority === "P0" && t.status !== "completed");
        const p1Tasks = allTasks.filter((t) => t.priority === "P1" && t.status !== "completed");
        const p2Tasks = allTasks.filter((t) => t.priority === "P2" && t.status !== "completed");
        
        const topTasks: Array<{ text: string; priority: "P0" | "P1" | "P2" }> = [];
        
        // Add P0s first
        for (const task of p0Tasks.slice(0, 3)) {
          topTasks.push({ text: task.title, priority: "P0" });
        }
        
        // Fill with P1s if < 3
        if (topTasks.length < 3) {
          for (const task of p1Tasks.slice(0, 3 - topTasks.length)) {
            topTasks.push({ text: task.title, priority: "P1" });
          }
        }
        
        // Fill with P2s if still < 3
        if (topTasks.length < 3) {
          for (const task of p2Tasks.slice(0, 3 - topTasks.length)) {
            topTasks.push({ text: task.title, priority: "P2" });
          }
        }
        
        // 3. Calculate remaining focus hours from now until 6pm UK time
        // NOTE: Calendar query is SLOW (15-45s) so we skip it on startup
        // Use time-based estimate instead. User can ask about calendar explicitly.
        let focusHoursAvailable = 0;
        
        const now = new Date();
        const ukTime = new Date(now.toLocaleString("en-US", { timeZone: "Europe/London" }));
        const currentHour = ukTime.getHours();
        const currentMinute = ukTime.getMinutes();
        const minutesUntil6pm = Math.max(0, (18 * 60) - (currentHour * 60 + currentMinute));
        focusHoursAvailable = minutesUntil6pm / 60;
        
        // Render dashboard widget (in bottom bar, below editor)
        const dashboardData = {
          weekPriorities: weekPriorityItems,
          topTasks,
          focusHoursAvailable,
        };
        
        ctx.ui.setWidget("dex-dashboard", (_tui, _theme) => ({
          render: (width) => dashboard.renderDashboard(dashboardData, width),
          invalidate: () => {},
        }), { placement: "belowEditor" });
        
        // Simple footer status
        const taskSummary = dataLayer.getTaskSummary();
        const footerParts = ["● Dex"];
        if (taskSummary.p0Count > 0) {
          footerParts.push(`${taskSummary.p0Count} P0`);
        }
        ctx.ui.setStatus("dex", footerParts.join(" | "));
        
      } catch (error) {
        console.error("[Dex] Dashboard error:", error);
        // Fallback to simple status
        const taskSummary = getTaskSummary();
        ctx.ui.setStatus("dex", `● Dex | ${taskSummary.totalOpen} tasks`);
      }
    }
    
    // Git sync in background (don't await to avoid blocking)
    if (fs.existsSync(path.join(VAULT_PATH, ".git"))) {
      execAsync(`cd "${VAULT_PATH}" && git pull --rebase 2>/dev/null`).catch(() => {});
    }
  });
  
  pi.on("agent_end", async (event, ctx) => {
    // Play notification sound
    try {
      spawn("afplay", ["/System/Library/Sounds/Glass.aiff"], { detached: true, stdio: "ignore" }).unref();
    } catch {}
    
    // Update status with task count (no calendar - it's slow!)
    const taskSummary = getTaskSummary();
    ctx.ui.setStatus("dex", `● Dex | ${taskSummary.totalOpen} tasks`);
  });
  
  pi.on("session_shutdown", async (_event, ctx) => {
    // Git commit and push
    if (fs.existsSync(path.join(VAULT_PATH, ".git"))) {
      try {
        await execAsync(`cd "${VAULT_PATH}" && git add -A && git commit -m "Dex auto-sync: ${formatTimestamp()}" && git push 2>/dev/null`);
      } catch {}
    }
  });
  
  // =========================================================================
  // NATIVE TOOLS
  // =========================================================================
  
  // Vault Search Tool
  pi.registerTool({
    name: "pi_vault_search",
    label: "Vault Search",
    description: "Search across the Dex vault for content, people, projects, or tasks. Returns relevant excerpts with file paths.",
    parameters: VaultSearchParams,
    
    async execute(toolCallId, params, signal, onUpdate, ctx) {
      const results = await searchVault(
        params.query,
        params.type || "all",
        params.limit || 10
      );
      
      if (results.length === 0) {
        return {
          content: [{ type: "text", text: `No results found for "${params.query}"` }],
          details: { results: [] }
        };
      }
      
      let output = `Found ${results.length} results for "${params.query}":\n\n`;
      for (const result of results) {
        output += `### ${result.title}\n`;
        output += `**Path:** ${result.path}\n`;
        output += `${result.excerpt}\n\n`;
      }
      
      return {
        content: [{ type: "text", text: output }],
        details: { results }
      };
    },
    
    renderCall(args, theme) {
      const text = theme.fg("toolTitle", theme.bold("vault_search ")) +
        theme.fg("accent", `"${args.query}"`) +
        (args.type && args.type !== "all" ? theme.fg("dim", ` (${args.type})`) : "");
      return new Text(text, 0, 0);
    },
    
    renderResult(result, { expanded }, theme) {
      const details = result.details as { results: SearchResult[] };
      const count = details?.results?.length || 0;
      
      if (count === 0) {
        return new Text(theme.fg("warning", "No results found"), 0, 0);
      }
      
      let text = theme.fg("success", `✓ Found ${count} results`);
      
      if (expanded && details.results) {
        for (const r of details.results.slice(0, 5)) {
          text += `\n  ${theme.fg("accent", r.title)} ${theme.fg("dim", `(${r.path})`)}`;
        }
      }
      
      return new Text(text, 0, 0);
    }
  });
  
  // Task Management Tool
  pi.registerTool({
    name: "pi_dex_task",
    label: "Dex Task",
    description: "Manage tasks: create, complete, list, or get suggestions. Tasks are validated and tracked.",
    parameters: TaskParams,
    
    async execute(toolCallId, params, signal, onUpdate, ctx) {
      switch (params.action) {
        case "create":
          if (!params.title) {
            return {
              content: [{ type: "text", text: "Error: title required for create action" }],
              details: { error: true }
            };
          }
          const createResult = createTask(
            params.title,
            params.priority || "P2",
            params.pillar,
            params.context
          );
          return {
            content: [{ type: "text", text: createResult.message }],
            details: { success: createResult.success, taskId: createResult.taskId }
          };
          
        case "complete":
          if (!params.task_id) {
            return {
              content: [{ type: "text", text: "Error: task_id required for complete action" }],
              details: { error: true }
            };
          }
          const completeResult = completeTask(params.task_id);
          return {
            content: [{ type: "text", text: completeResult.message }],
            details: { success: completeResult.success }
          };
          
        case "list":
          const taskList = listTasks(params.priority);
          return {
            content: [{ type: "text", text: taskList }],
            details: { summary: getTaskSummary() }
          };
          
        case "suggest":
          const summary = getTaskSummary();
          let suggestions = "## Suggested Focus\n\n";
          if (summary.p0Tasks.length > 0) {
            suggestions += `**Start with P0:** ${summary.p0Tasks[0]}\n\n`;
          } else if (summary.overdueTasks.length > 0) {
            suggestions += `**Clear overdue:** ${summary.overdueTasks[0]}\n\n`;
          } else if (summary.startedTasks.length > 0) {
            suggestions += `**Finish what you started:** ${summary.startedTasks[0]}\n\n`;
          }
          return {
            content: [{ type: "text", text: suggestions }],
            details: { summary }
          };
          
        default:
          return {
            content: [{ type: "text", text: "Unknown action" }],
            details: { error: true }
          };
      }
    },
    
    renderCall(args, theme) {
      let text = theme.fg("toolTitle", theme.bold("dex_task ")) +
        theme.fg("accent", args.action);
      if (args.title) text += theme.fg("dim", ` "${args.title.slice(0, 40)}"`);
      if (args.task_id) text += theme.fg("dim", ` ${args.task_id}`);
      return new Text(text, 0, 0);
    },
    
    renderResult(result, { expanded }, theme) {
      const details = result.details as any;
      if (details?.error) {
        return new Text(theme.fg("error", result.content[0]?.text || "Error"), 0, 0);
      }
      if (details?.success === false) {
        return new Text(theme.fg("warning", result.content[0]?.text || "Failed"), 0, 0);
      }
      return new Text(theme.fg("success", "✓ ") + (result.content[0]?.text || "Done"), 0, 0);
    }
  });
  
  // Quick Capture Tool
  pi.registerTool({
    name: "pi_quick_capture",
    label: "Quick Capture",
    description: "Quickly capture an idea, note, task, or meeting notes to the inbox.",
    parameters: QuickCaptureParams,
    
    async execute(toolCallId, params, signal, onUpdate, ctx) {
      const result = quickCapture(
        params.content,
        params.type,
        params.title,
        params.tags
      );
      
      return {
        content: [{ type: "text", text: result.message }],
        details: { success: result.success, path: result.path }
      };
    },
    
    renderCall(args, theme) {
      const preview = args.content.length > 50 ? args.content.slice(0, 50) + "..." : args.content;
      return new Text(
        theme.fg("toolTitle", theme.bold("quick_capture ")) +
        theme.fg("accent", args.type) +
        theme.fg("dim", ` "${preview}"`),
        0, 0
      );
    }
  });
  
  // Dex Status Tool
  pi.registerTool({
    name: "pi_dex_status",
    label: "Dex Status",
    description: "Get a quick overview of your Dex state: tasks, meetings, week progress.",
    parameters: Type.Object({}),
    
    async execute(toolCallId, params, signal, onUpdate, ctx) {
      const status = await getDexStatus();
      
      let output = "## Dex Status\n\n";
      output += `**Week Progress:** ${status.weekProgress}\n`;
      output += `**Tasks:** ${status.tasksOpen} open`;
      if (status.tasksP0 > 0) output += ` (${status.tasksP0} P0!)`;
      if (status.tasksOverdue > 0) output += ` (${status.tasksOverdue} overdue)`;
      output += `\n`;
      output += `**Meetings Today:** ${status.meetingsToday}\n`;
      if (status.nextMeeting) {
        output += `**Next Meeting:** ${status.nextMeeting}\n`;
      }
      
      return {
        content: [{ type: "text", text: output }],
        details: status
      };
    }
  });
  
  // Calendar Tool
  pi.registerTool({
    name: "pi_dex_calendar",
    label: "Dex Calendar",
    description: "Access Apple Calendar events: today's meetings, upcoming events, or next meeting.",
    parameters: CalendarParams,
    
    async execute(toolCallId, params, signal, onUpdate, ctx) {
      const result = await getCalendarEvents(
        params.action,
        params.calendar,
        params.days || 7
      );
      
      return {
        content: [{ type: "text", text: result }],
        details: { action: params.action }
      };
    }
  });
  
  // =========================================================================
  // QUICK COMMANDS
  // =========================================================================
  
  pi.registerCommand("status", {
    description: "Show Dex status (tasks, meetings, week progress)",
    handler: async (args, ctx) => {
      const status = await getDexStatus();
      ctx.ui.notify(formatStatusLine(status), "info");
    }
  });
  
  pi.registerCommand("capture", {
    description: "Quick capture to inbox",
    handler: async (args, ctx) => {
      if (!args) {
        ctx.ui.notify("Usage: /capture <content>", "warning");
        return;
      }
      const result = quickCapture(args, "note");
      ctx.ui.notify(result.message, result.success ? "success" : "error");
    }
  });
  
  pi.registerCommand("focus", {
    description: "Get suggested focus task",
    handler: async (args, ctx) => {
      const summary = getTaskSummary();
      let focus: string;
      if (summary.p0Tasks.length > 0) {
        focus = `P0: ${summary.p0Tasks[0]}`;
      } else if (summary.overdueTasks.length > 0) {
        focus = `Overdue: ${summary.overdueTasks[0]}`;
      } else if (summary.startedTasks.length > 0) {
        focus = `Continue: ${summary.startedTasks[0]}`;
      } else {
        focus = "No urgent tasks!";
      }
      ctx.ui.notify(focus, "info");
    }
  });
  
  pi.registerCommand("tasks", {
    description: "List open tasks",
    handler: async (args, ctx) => {
      const summary = getTaskSummary();
      ctx.ui.notify(`${summary.totalOpen} tasks (${summary.p0Tasks.length} P0, ${summary.overdueTasks.length} overdue)`, "info");
    }
  });
  
  pi.registerCommand("today", {
    description: "Show today's calendar",
    handler: async (args, ctx) => {
      const events = await getCalendarEvents("today");
      ctx.ui.notify(events || "No meetings today", "info");
    }
  });
  
  pi.registerCommand("done", {
    description: "Mark a task done by ID or search term",
    handler: async (args, ctx) => {
      if (!args) {
        ctx.ui.notify("Usage: /done <task-id or search term>", "warning");
        return;
      }
      
      // If it looks like a task ID, complete directly
      if (args.startsWith("task-")) {
        const result = completeTask(args);
        ctx.ui.notify(result.message, result.success ? "success" : "error");
        return;
      }
      
      // Otherwise, search for matching task
      const tasksContent = readFileSync(TASKS_PATH);
      if (!tasksContent) {
        ctx.ui.notify("Tasks file not found", "error");
        return;
      }
      
      const searchLower = args.toLowerCase();
      const lines = tasksContent.split("\n");
      
      for (const line of lines) {
        if (line.includes("- [ ]") && line.toLowerCase().includes(searchLower)) {
          const idMatch = line.match(/\^(task-\d+-\d+)/);
          if (idMatch) {
            const result = completeTask(idMatch[1]);
            ctx.ui.notify(result.message, result.success ? "success" : "error");
            return;
          }
        }
      }
      
      ctx.ui.notify(`No open task matching "${args}"`, "warning");
    }
  });
  
  pi.registerCommand("dex", {
    description: "Dex help and status",
    handler: async (args, ctx) => {
      const status = await getDexStatus();
      ctx.ui.notify(
        `Dex for PI\n` +
        `Tasks: ${status.tasksOpen} | Meetings: ${status.meetingsToday} | ${status.weekProgress}\n` +
        `Commands: /status /capture /focus /tasks /today /done /plan`,
        "info"
      );
    }
  });

  // Dashboard refresh - updates as tasks complete
  pi.registerCommand("refresh", {
    description: "Refresh dashboard with current tasks and calendar",
    handler: async (args, ctx) => {
      if (!ctx.hasUI) return;

      try {
        const dataLayer = await import("./data-layer.js");
        const dashboard = await import("./dashboard-widget.js");
        
        // Reload week priorities
        const weekPriorities = dataLayer.loadWeekPriorities();
        const weekPriorityItems: Array<{ text: string; completed: boolean }> = weekPriorities
          .slice(0, 3)
          .map((p) => ({
            text: p.goal,
            completed: p.progress >= 100,
          }));
        
        // Reload top tasks
        const allTasks = dataLayer.loadTasks();
        const p0Tasks = allTasks.filter((t) => t.priority === "P0" && t.status !== "completed");
        const p1Tasks = allTasks.filter((t) => t.priority === "P1" && t.status !== "completed");
        const p2Tasks = allTasks.filter((t) => t.priority === "P2" && t.status !== "completed");
        
        const topTasks: Array<{ text: string; priority: "P0" | "P1" | "P2" }> = [];
        
        for (const task of p0Tasks.slice(0, 3)) {
          topTasks.push({ text: task.title, priority: "P0" });
        }
        if (topTasks.length < 3) {
          for (const task of p1Tasks.slice(0, 3 - topTasks.length)) {
            topTasks.push({ text: task.title, priority: "P1" });
          }
        }
        if (topTasks.length < 3) {
          for (const task of p2Tasks.slice(0, 3 - topTasks.length)) {
            topTasks.push({ text: task.title, priority: "P2" });
          }
        }
        
        // Recalculate remaining focus time
        let focusHoursAvailable = 0;
        
        try {
          const today = new Date().toISOString().slice(0, 10);
          const calendarResult = await pi.tools.call("calendar_get_events", { start_date: today });
          
          // Calendar MCP returns { success: true, events: [...] }
          if (calendarResult && calendarResult.success && Array.isArray(calendarResult.events)) {
            // Pass events with original AppleScript format for proper time parsing
            const events = calendarResult.events.map((e: any) => ({
              title: e.title || e.summary || "Untitled",
              start: e.start, // AppleScript format
              end: e.end,
              duration: e.duration || 60,
            }));
            
            focusHoursAvailable = dashboard.calculateRemainingFocusTime(events);
          } else {
            const now = new Date();
            const ukTime = new Date(now.toLocaleString("en-US", { timeZone: "Europe/London" }));
            const currentHour = ukTime.getHours();
            const currentMinute = ukTime.getMinutes();
            const minutesUntil6pm = Math.max(0, (18 * 60) - (currentHour * 60 + currentMinute));
            focusHoursAvailable = minutesUntil6pm / 60;
          }
        } catch {
          const now = new Date();
          const ukTime = new Date(now.toLocaleString("en-US", { timeZone: "Europe/London" }));
          const currentHour = ukTime.getHours();
          const currentMinute = ukTime.getMinutes();
          const minutesUntil6pm = Math.max(0, (18 * 60) - (currentHour * 60 + currentMinute));
          focusHoursAvailable = minutesUntil6pm / 60;
        }
        
        // Update dashboard widget (in bottom bar)
        const dashboardData = {
          weekPriorities: weekPriorityItems,
          topTasks,
          focusHoursAvailable,
        };
        
        ctx.ui.setWidget("dex-dashboard", (_tui, _theme) => ({
          render: (width) => dashboard.renderDashboard(dashboardData, width),
          invalidate: () => {},
        }), { placement: "belowEditor" });
        
        // Update footer
        const taskSummary = dataLayer.getTaskSummary();
        const footerParts = ["● Dex"];
        if (taskSummary.p0Count > 0) {
          footerParts.push(`${taskSummary.p0Count} P0`);
        }
        ctx.ui.setStatus("dex", footerParts.join(" | "));
        
        ctx.ui.notify("Dashboard refreshed", "success");
      } catch (error) {
        console.error("[Dex] Refresh error:", error);
        ctx.ui.notify("Failed to refresh dashboard", "error");
      }
    }
  });
  
  // =========================================================================
  // REGISTER ORCHESTRATOR (Sub-Agent Coordination)
  // =========================================================================
  
  registerOrchestratorTools(pi);
  
  // =========================================================================
  // REGISTER COMMITMENT DETECTOR (Ambient Intelligence)
  // =========================================================================
  
  registerCommitmentDetector(pi);
  
  // =========================================================================
  // REGISTER MODEL ROUTER (Smart Model Selection)
  // =========================================================================
  
  registerModelRouter(pi);
}
