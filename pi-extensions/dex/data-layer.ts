/**
 * Data Layer for Dex Extension
 * 
 * Provides clean interfaces to vault data and MCPs.
 */

import * as fs from "node:fs";
import * as path from "node:path";

const VAULT_PATH = process.env.VAULT_PATH || "/Users/dave/Claudesidian";
const TASKS_PATH = path.join(VAULT_PATH, "03-Tasks/Tasks.md");
const WEEK_PRIORITIES_PATH = path.join(VAULT_PATH, "02-Week_Priorities");
const DAILY_PLAN_PATH = path.join(VAULT_PATH, "01-Daily_Plan");
const CAREER_EVIDENCE_PATH = path.join(VAULT_PATH, "05-Areas/Career/Evidence");

// Type definitions
export interface Task {
  id: string;
  title: string;
  priority: "P0" | "P1" | "P2" | "P3";
  status: "open" | "started" | "completed";
  dueDate?: string;
  pillar?: string;
  tags?: string[];
  rawLine: string;
}

export interface WeekPriority {
  name: string;
  goal: string;
  tasks: string[];
  completedTasks: string[];
  progress: number;
  status: "on-track" | "behind" | "not-started";
}

export interface CalendarEvent {
  title: string;
  startTime: string;
  endTime: string;
  duration: number;
  attendees?: string[];
}

export interface Evidence {
  date: string;
  achievement: string;
  skill?: string;
  impact?: string;
  competency?: string;
  filePath: string;
}

/**
 * Read file safely
 */
function readFileSync(filePath: string): string | null {
  try {
    return fs.readFileSync(filePath, "utf-8");
  } catch {
    return null;
  }
}

/**
 * Write file safely
 */
function writeFileSync(filePath: string, content: string): boolean {
  try {
    const dir = path.dirname(filePath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(filePath, content, "utf-8");
    return true;
  } catch (error) {
    console.error(`[Dex Data Layer] Failed to write file: ${filePath}`, error);
    return false;
  }
}

/**
 * Format date as YYYY-MM-DD
 */
function formatDate(date: Date = new Date()): string {
  return date.toISOString().slice(0, 10);
}

/**
 * Get day of week (1-5 for Mon-Fri)
 */
function getDayOfWeek(date: Date = new Date()): number {
  const day = date.getDay();
  // Convert Sunday (0) to 7, then map Mon-Fri to 1-5
  return day === 0 ? 7 : day;
}

// ============================================================================
// TASK OPERATIONS
// ============================================================================

/**
 * Parse a task line from Tasks.md
 */
function parseTaskLine(line: string): Task | null {
  // Task format: "- [ ] **Task title** — Context ^task-YYYYMMDD-XXX #P0 #pillar/value"
  const taskMatch = line.match(/^- \[([ xsb])\] (.+)$/);
  if (!taskMatch) return null;

  const [, checkbox, fullText] = taskMatch;
  const status = checkbox === "x" ? "completed" : "open";

  // Extract task ID
  const taskIdMatch = fullText.match(/\^(task-\d{8}-\d{3})/);
  const taskId = taskIdMatch?.[1] || "";

  // Extract title - stop at first — or task ID
  let title = fullText;
  
  // First, extract up to task ID or —
  const titleMatch = fullText.match(/^(.+?)(?:\s+—|\s+\^task-)/);
  if (titleMatch) {
    title = titleMatch[1]!.trim();
  } else {
    // No separator found - just take first chunk before any #tags
    const tagMatch = fullText.match(/^(.+?)(?:\s+#)/);
    if (tagMatch) {
      title = tagMatch[1]!.trim();
    }
  }
  
  // Strip bold markdown (**text**)
  title = title.replace(/^\*\*(.+?)\*\*$/, "$1").trim();

  // Extract priority from inline tag
  const priorityMatch = fullText.match(/#(P[0-3])/);
  const priority = (priorityMatch?.[1] as Task["priority"]) || null;

  // Extract pillar
  const pillarMatch = fullText.match(/#([a-z_]+)/);
  const pillar = pillarMatch?.[1];

  // Extract due date
  const dueDateMatch = fullText.match(/📅 (\d{4}-\d{2}-\d{2})/);
  const dueDate = dueDateMatch?.[1];

  return {
    id: taskId,
    title: title,
    priority: priority || "P2",
    status,
    dueDate,
    pillar,
    rawLine: line,
  };
}

/**
 * Load all tasks from Tasks.md
 */
export function loadTasks(): Task[] {
  console.log("[Dex Data Layer] Loading tasks from:", TASKS_PATH);
  const content = readFileSync(TASKS_PATH);
  if (!content) {
    console.log("[Dex Data Layer] ❌ Tasks file not found or empty");
    return [];
  }

  console.log("[Dex Data Layer] Tasks file read, length:", content.length);
  const tasks: Task[] = [];
  let currentPriority: "P0" | "P1" | "P2" | "P3" = "P2"; // Default priority
  
  for (const line of content.split("\n")) {
    // Check for priority section headers: "## P0 - Urgent" or "## This Week"
    const sectionMatch = line.match(/^##\s+(P[0-3]|This Week)/i);
    if (sectionMatch) {
      const section = sectionMatch[1]!.toUpperCase();
      if (section === "THIS WEEK") {
        currentPriority = "P1"; // "This Week" tasks default to P1
      } else {
        currentPriority = section as "P0" | "P1" | "P2" | "P3";
      }
      console.log(`[Dex Data Layer] Section found: ${section} -> Priority: ${currentPriority}`);
      continue;
    }
    
    const task = parseTaskLine(line);
    if (task) {
      // Use inline priority if present, otherwise use section priority
      if (!task.rawLine.match(/#P[0-3]/)) {
        task.priority = currentPriority;
      }
      console.log(`[Dex Data Layer] Task parsed: [${task.priority}] ${task.title.substring(0, 40)}`);
      tasks.push(task);
    }
  }

  console.log(`[Dex Data Layer] ✅ Loaded ${tasks.length} total tasks`);
  return tasks;
}

/**
 * Load tasks by priority
 */
export function loadTasksByPriority(priority: "P0" | "P1" | "P2" | "P3"): Task[] {
  return loadTasks().filter((t) => t.priority === priority && t.status !== "completed");
}

/**
 * Get P0 tasks
 */
export function getP0Tasks(): Task[] {
  return loadTasksByPriority("P0");
}

/**
 * Get P1 tasks
 */
export function getP1Tasks(): Task[] {
  return loadTasksByPriority("P1");
}

/**
 * Get overdue tasks
 */
export function getOverdueTasks(): Task[] {
  const today = formatDate();
  return loadTasks().filter((t) => {
    if (t.status === "completed") return false;
    if (!t.dueDate) return false;
    return t.dueDate < today;
  });
}

/**
 * Get task summary for quick lookups
 */
export function getTaskSummary(): {
  totalOpen: number;
  p0Count: number;
  p1Count: number;
  overdueCount: number;
  p0Tasks: string[];
  p1Tasks: string[];
  overdueTasks: string[];
} {
  const p0Tasks = getP0Tasks();
  const p1Tasks = getP1Tasks();
  const overdueTasks = getOverdueTasks();
  const allOpen = loadTasks().filter((t) => t.status !== "completed");

  return {
    totalOpen: allOpen.length,
    p0Count: p0Tasks.length,
    p1Count: p1Tasks.length,
    overdueCount: overdueTasks.length,
    p0Tasks: p0Tasks.map((t) => t.title),
    p1Tasks: p1Tasks.map((t) => t.title),
    overdueTasks: overdueTasks.map((t) => t.title),
  };
}

// ============================================================================
// WEEK PROGRESS
// ============================================================================

/**
 * Load week priorities from current week file
 */
export function loadWeekPriorities(): WeekPriority[] {
  // Read Week_Priorities.md directly
  const weekFilePath = path.join(WEEK_PRIORITIES_PATH, "Week_Priorities.md");
  console.log("[Dex Data Layer] Loading week priorities from:", weekFilePath);
  
  const content = readFileSync(weekFilePath);
  if (!content) {
    console.log("[Dex Data Layer] ❌ Week priorities file not found or empty");
    return [];
  }

  console.log("[Dex Data Layer] Week priorities file read, length:", content.length);

  // Look for "## 🎯 Top 3 This Week" section
  const topThreeMatch = content.match(/## 🎯 Top 3 This Week[\s\S]*?\n([\s\S]*?)(?=\n---|\n##|$)/);
  if (!topThreeMatch) {
    console.log("[Dex Data Layer] ❌ Could not find '## 🎯 Top 3 This Week' section");
    return [];
  }

  const section = topThreeMatch[1]!;
  console.log("[Dex Data Layer] Found Top 3 section, length:", section.length);
  
  // Extract numbered goals: 1. **Goal text** or 1. Goal text
  const goalRegex = /^\d+\.\s+(?:\*\*)?(.+?)(?:\*\*)?$/gm;
  const priorities: WeekPriority[] = [];
  
  let match;
  while ((match = goalRegex.exec(section)) !== null) {
    const goalText = match[1]!.trim();
    console.log(`[Dex Data Layer] Goal found: ${goalText.substring(0, 50)}`);
    
    // Determine if goal is completed (contains ✅ or starts with [x])
    const completed = goalText.includes("✅") || goalText.startsWith("[x]");
    
    priorities.push({
      name: `Goal ${priorities.length + 1}`,
      goal: goalText.replace(/✅|^\[x\]\s*/g, "").trim(),
      tasks: [], // Not tracking sub-tasks for now
      completedTasks: completed ? [goalText] : [],
      progress: completed ? 100 : 0,
      status: completed ? "on-track" : "not-started",
    });
  }

  console.log(`[Dex Data Layer] ✅ Loaded ${priorities.length} priorities`);
  return priorities;
}

/**
 * Get week progress summary
 */
export function getWeekProgressSummary() {
  const priorities = loadWeekPriorities();
  const dayOfWeek = getDayOfWeek();

  return {
    dayOfWeek: dayOfWeek <= 5 ? dayOfWeek : 5, // Cap at Friday
    priorities: priorities.map((p) => ({
      name: p.name,
      progress: p.progress,
      status: p.status,
    })),
  };
}

// ============================================================================
// DAILY NOTES
// ============================================================================

/**
 * Load daily note for a specific date
 */
export function loadDailyNote(date: string = formatDate()): string | null {
  const filePath = path.join(DAILY_PLAN_PATH, `${date}.md`);
  return readFileSync(filePath);
}

/**
 * Save daily plan
 */
export function saveDailyPlan(date: string, content: string): boolean {
  const filePath = path.join(DAILY_PLAN_PATH, `${date}.md`);
  return writeFileSync(filePath, content);
}

/**
 * Append to daily note
 */
export function appendToDailyNote(date: string, section: string, content: string): boolean {
  const filePath = path.join(DAILY_PLAN_PATH, `${date}.md`);
  let existing = readFileSync(filePath) || "";

  // Find section or append at end
  const sectionRegex = new RegExp(`## ${section}[\\s\\S]*?(?=\\n## |$)`);
  if (sectionRegex.test(existing)) {
    existing = existing.replace(sectionRegex, `## ${section}\n\n${content}\n`);
  } else {
    existing += `\n## ${section}\n\n${content}\n`;
  }

  return writeFileSync(filePath, existing);
}

// ============================================================================
// CAREER EVIDENCE
// ============================================================================

/**
 * Load career evidence files
 */
export function loadCareerEvidence(): Evidence[] {
  if (!fs.existsSync(CAREER_EVIDENCE_PATH)) return [];

  const evidence: Evidence[] = [];
  const files = fs.readdirSync(CAREER_EVIDENCE_PATH);

  for (const file of files) {
    if (!file.endsWith(".md")) continue;

    const filePath = path.join(CAREER_EVIDENCE_PATH, file);
    const content = readFileSync(filePath);
    if (!content) continue;

    // Extract metadata from frontmatter
    const frontmatterMatch = content.match(/^---\n([\s\S]*?)\n---/);
    if (frontmatterMatch) {
      const frontmatter = frontmatterMatch[1]!;
      const dateMatch = frontmatter.match(/date: (.+)/);
      const skillMatch = frontmatter.match(/skill: (.+)/);
      const competencyMatch = frontmatter.match(/competency: (.+)/);

      // Extract achievement from first heading or content
      const achievementMatch = content.match(/## (.+)|# (.+)/);
      const achievement = achievementMatch?.[1] || achievementMatch?.[2] || file.replace(".md", "");

      evidence.push({
        date: dateMatch?.[1]?.trim() || file.replace(".md", ""),
        achievement,
        skill: skillMatch?.[1]?.trim(),
        competency: competencyMatch?.[1]?.trim(),
        filePath,
      });
    }
  }

  return evidence.sort((a, b) => b.date.localeCompare(a.date));
}

/**
 * Calculate competency scores from evidence
 */
export function calculateCompetencyScores(evidence: Evidence[]) {
  const competencies = new Map<string, { count: number; recent: number }>();

  // Count evidence per competency
  for (const item of evidence) {
    if (!item.competency) continue;

    const existing = competencies.get(item.competency) || { count: 0, recent: 0 };
    existing.count++;

    // Count recent evidence (last 90 days)
    const itemDate = new Date(item.date);
    const ninetyDaysAgo = new Date();
    ninetyDaysAgo.setDate(ninetyDaysAgo.getDate() - 90);
    if (itemDate > ninetyDaysAgo) {
      existing.recent++;
    }

    competencies.set(item.competency, existing);
  }

  // Convert to scores
  return Array.from(competencies.entries()).map(([name, data]) => {
    // Score based on total evidence and recency
    const baseScore = Math.min(data.count * 10, 70); // Max 70 from count
    const recencyBonus = Math.min(data.recent * 10, 30); // Max 30 from recent
    const score = Math.min(baseScore + recencyBonus, 100);

    let status: "weak" | "building" | "on-track" | "strong" | "excellent";
    if (score < 40) status = "weak";
    else if (score < 60) status = "building";
    else if (score < 75) status = "on-track";
    else if (score < 90) status = "strong";
    else status = "excellent";

    return {
      name,
      score,
      status,
      evidenceCount: data.count,
    };
  });
}

// ============================================================================
// CALENDAR INTEGRATION
// ============================================================================

/**
 * Get calendar events for a date (requires calendar-mcp)
 * This is a placeholder - actual implementation uses MCP
 */
export async function getCalendarEvents(date: string = formatDate()): Promise<CalendarEvent[]> {
  // This will be called from the main extension with ctx access
  // For now, return empty array
  return [];
}

/**
 * Analyze calendar shape from events
 */
export function analyzeCalendarShape(events: CalendarEvent[]): {
  shape: "light" | "moderate" | "heavy";
  totalMeetingMinutes: number;
  freeBlocks: Array<{ startTime: string; endTime: string; duration: number; label: string }>;
} {
  const totalMeetingMinutes = events.reduce((sum, e) => sum + e.duration, 0);

  let shape: "light" | "moderate" | "heavy";
  if (totalMeetingMinutes < 120) shape = "light";
  else if (totalMeetingMinutes < 240) shape = "moderate";
  else shape = "heavy";

  // Calculate free blocks (simplified - assume 9am-5pm workday)
  const freeBlocks: Array<{ startTime: string; endTime: string; duration: number; label: string }> = [];

  // Sort events by start time
  const sorted = [...events].sort((a, b) => a.startTime.localeCompare(b.startTime));

  // Find gaps
  let currentTime = "09:00";
  for (const event of sorted) {
    if (event.startTime > currentTime) {
      // Found a gap
      const gapMinutes = calculateMinutesBetween(currentTime, event.startTime);
      if (gapMinutes >= 30) {
        // Only include gaps of 30+ minutes
        freeBlocks.push({
          startTime: currentTime,
          endTime: event.startTime,
          duration: gapMinutes,
          label: gapMinutes >= 90 ? "Deep work block" : "Focus time",
        });
      }
    }
    currentTime = event.endTime;
  }

  // Add final block if day not full
  if (currentTime < "17:00") {
    const gapMinutes = calculateMinutesBetween(currentTime, "17:00");
    if (gapMinutes >= 30) {
      freeBlocks.push({
        startTime: currentTime,
        endTime: "17:00",
        duration: gapMinutes,
        label: gapMinutes >= 90 ? "Deep work block" : "Focus time",
      });
    }
  }

  return { shape, totalMeetingMinutes, freeBlocks };
}

/**
 * Calculate minutes between two time strings (HH:MM format)
 */
function calculateMinutesBetween(start: string, end: string): number {
  const [startHour, startMin] = start.split(":").map(Number);
  const [endHour, endMin] = end.split(":").map(Number);

  const startMinutes = startHour! * 60 + startMin!;
  const endMinutes = endHour! * 60 + endMin!;

  return endMinutes - startMinutes;
}
