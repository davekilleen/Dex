/**
 * Dashboard Widget
 * 
 * Shows your day at a glance: week priorities, top tasks, focus time
 */

export interface WeekPriority {
  text: string;
  completed: boolean;
}

export interface TopTask {
  text: string;
  priority: "P0" | "P1" | "P2";
}

export interface DashboardData {
  weekPriorities: WeekPriority[]; // Up to 3
  topTasks: TopTask[]; // Up to 3
  focusHoursAvailable: number; // Total free time today
}

/**
 * Render dashboard widget as text lines
 */
export function renderDashboard(data: DashboardData, width: number): string[] {
  const lines: string[] = [];
  
  // Top border
  lines.push("┌─ Your Day at a Glance " + "─".repeat(Math.max(0, width - 26)) + "┐");
  lines.push("│" + " ".repeat(width - 2) + "│");
  
  // Column headers
  const leftHeader = "Week Priorities";
  const rightHeader = "Top Tasks";
  const headerGap = Math.floor((width - leftHeader.length - rightHeader.length - 4) / 2);
  const header = `│  ${leftHeader}${" ".repeat(headerGap)}${rightHeader}${" ".repeat(Math.max(0, width - 4 - leftHeader.length - headerGap - rightHeader.length))}│`;
  lines.push(header);
  
  // Underlines
  const leftUnderline = "─".repeat(leftHeader.length);
  const rightUnderline = "─".repeat(rightHeader.length);
  const underline = `│  ${leftUnderline}${" ".repeat(headerGap)}${rightUnderline}${" ".repeat(Math.max(0, width - 4 - leftUnderline.length - headerGap - rightUnderline.length))}│`;
  lines.push(underline);
  
  // Data rows (up to 3)
  const maxRows = 3;
  for (let i = 0; i < maxRows; i++) {
    const leftItem = data.weekPriorities[i];
    const rightItem = data.topTasks[i];
    
    const leftText = leftItem
      ? `${leftItem.completed ? "☑" : "□"} ${truncate(leftItem.text, 25)}`
      : "";
    const rightText = rightItem
      ? `${getPriorityIcon(rightItem.priority)} ${truncate(rightItem.text, 30)}`
      : "";
    
    const leftPadded = leftText.padEnd(27); // Fixed width for left column
    const gap = " ".repeat(Math.max(0, headerGap - 2));
    const row = `│  ${leftPadded}${gap}${rightText}${" ".repeat(Math.max(0, width - 4 - leftPadded.length - gap.length - rightText.length))}│`;
    lines.push(row);
  }
  
  // Empty line
  lines.push("│" + " ".repeat(width - 2) + "│");
  
  // Focus time
  const focusText = `📅 Focus Time Available: ${formatHours(data.focusHoursAvailable)}`;
  lines.push(`│  ${focusText}${" ".repeat(Math.max(0, width - 4 - focusText.length))}│`);
  
  // Empty line
  lines.push("│" + " ".repeat(width - 2) + "│");
  
  // Bottom border
  lines.push("└" + "─".repeat(width - 2) + "┘");
  
  return lines;
}

/**
 * Get priority icon
 */
function getPriorityIcon(priority: "P0" | "P1" | "P2"): string {
  switch (priority) {
    case "P0":
      return "🔥";
    case "P1":
      return "⚡";
    case "P2":
      return "○";
  }
}

/**
 * Truncate text to max length
 */
function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen - 3) + "...";
}

/**
 * Format hours (decimal) as human-readable
 */
function formatHours(hours: number): string {
  if (hours === 0) return "None (meetings fully booked)";
  if (hours < 1) return `${Math.round(hours * 60)} minutes`;
  
  const wholeHours = Math.floor(hours);
  const minutes = Math.round((hours - wholeHours) * 60);
  
  if (minutes === 0) {
    return wholeHours === 1 ? "1 hour" : `${wholeHours} hours`;
  }
  
  return `${wholeHours}h ${minutes}m`;
}

/**
 * Parse AppleScript date string to minutes since midnight
 * Format: "Wednesday, February 5, 2026 at 9:30:00 AM"
 */
function parseAppleScriptTime(dateStr: string): number | null {
  try {
    // Extract time portion: "9:30:00 AM" or "9:30:00 PM"
    const timeMatch = dateStr.match(/(\d{1,2}):(\d{2}):(\d{2})\s*(AM|PM)/i);
    if (!timeMatch) return null;
    
    let hours = parseInt(timeMatch[1]!);
    const minutes = parseInt(timeMatch[2]!);
    const ampm = timeMatch[4]!.toUpperCase();
    
    // Convert to 24-hour format
    if (ampm === "PM" && hours !== 12) {
      hours += 12;
    } else if (ampm === "AM" && hours === 12) {
      hours = 0;
    }
    
    return hours * 60 + minutes;
  } catch {
    return null;
  }
}

/**
 * Calculate remaining focus time from now until 6pm UK time
 * 
 * @param events Today's calendar events (with AppleScript date strings)
 * @returns Hours of free time remaining
 */
export function calculateRemainingFocusTime(events: Array<{
  start?: string; // AppleScript format: "Wednesday, February 5, 2026 at 9:30:00 AM"
  end?: string;
  startTime?: string; // Fallback: "HH:MM" format
  endTime?: string;
  duration?: number;
}>): number {
  // Get current time in UK timezone
  const now = new Date();
  const ukTime = new Date(now.toLocaleString("en-US", { timeZone: "Europe/London" }));
  const currentHour = ukTime.getHours();
  const currentMinute = ukTime.getMinutes();
  const currentTimeMinutes = currentHour * 60 + currentMinute;
  
  // End of workday: 6pm UK time = 18:00 = 1080 minutes
  const endOfDayMinutes = 18 * 60;
  
  // If already past 6pm, no focus time left
  if (currentTimeMinutes >= endOfDayMinutes) {
    return 0;
  }
  
  // Total remaining time in the day
  const remainingDayMinutes = endOfDayMinutes - currentTimeMinutes;
  
  // Calculate meeting time from now until 6pm
  let meetingMinutesRemaining = 0;
  
  for (const event of events) {
    let eventStartMinutes: number | null = null;
    let eventEndMinutes: number | null = null;
    
    // Try AppleScript format first (from calendar MCP)
    if (event.start && event.end) {
      eventStartMinutes = parseAppleScriptTime(event.start);
      eventEndMinutes = parseAppleScriptTime(event.end);
    }
    
    // Fallback to HH:MM format
    if (eventStartMinutes === null && event.startTime) {
      const [startHour, startMin] = event.startTime.split(":").map(Number);
      if (startHour !== undefined) {
        eventStartMinutes = startHour * 60 + (startMin || 0);
      }
    }
    
    if (eventEndMinutes === null && event.endTime) {
      const [endHour, endMin] = event.endTime.split(":").map(Number);
      if (endHour !== undefined) {
        eventEndMinutes = endHour * 60 + (endMin || 0);
      }
    }
    
    // Skip if we couldn't parse times
    if (eventStartMinutes === null || eventEndMinutes === null) continue;
    
    // Only count meetings that haven't ended yet and are before 6pm
    if (eventEndMinutes > currentTimeMinutes && eventStartMinutes < endOfDayMinutes) {
      // Calculate overlap with remaining day
      const overlapStart = Math.max(eventStartMinutes, currentTimeMinutes);
      const overlapEnd = Math.min(eventEndMinutes, endOfDayMinutes);
      const overlapMinutes = Math.max(0, overlapEnd - overlapStart);
      
      meetingMinutesRemaining += overlapMinutes;
    }
  }
  
  // Free time = remaining day - remaining meetings
  const focusMinutes = Math.max(0, remainingDayMinutes - meetingMinutesRemaining);
  return focusMinutes / 60;
}
