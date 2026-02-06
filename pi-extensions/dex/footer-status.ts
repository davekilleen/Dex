/**
 * Smart Footer Status for Dex
 * 
 * Shows actionable information: urgent tasks, calendar shape, focus time
 */

export interface FooterStatusData {
  p0Count: number;
  overdueCount: number;
  totalOpen: number;
  calendarShape?: "light" | "moderate" | "heavy";
  meetingCount?: number;
  nextFocusBlock?: { start: string; end: string; duration: number };
}

/**
 * Generate smart footer status text
 * 
 * Format: ● Dex | [URGENT] | [CALENDAR SHAPE] | [FOCUS TIME]
 * Example: ● Dex | 2 P0 | Moderate (4 mtgs) | Focus: 2-4pm
 */
export function generateFooterStatus(data: FooterStatusData): string {
  const parts: string[] = ["● Dex"];

  // Part 1: Urgent items (most important)
  const urgentCount = data.p0Count + data.overdueCount;
  if (urgentCount > 0) {
    const urgentParts: string[] = [];
    if (data.p0Count > 0) urgentParts.push(`${data.p0Count} P0`);
    if (data.overdueCount > 0) urgentParts.push(`${data.overdueCount} overdue`);
    parts.push(urgentParts.join(" + "));
  } else {
    // No urgent items - show total open
    if (data.totalOpen > 0) {
      parts.push(`${data.totalOpen} open`);
    } else {
      parts.push("All clear!");
    }
  }

  // Part 2: Calendar shape (if available)
  if (data.calendarShape && data.meetingCount !== undefined) {
    const shapeLabel = data.calendarShape.charAt(0).toUpperCase() + data.calendarShape.slice(1);
    if (data.meetingCount === 0) {
      parts.push("No meetings");
    } else {
      parts.push(`${shapeLabel} (${data.meetingCount} mtgs)`);
    }
  }

  // Part 3: Next focus block (if available)
  if (data.nextFocusBlock) {
    const { start, end, duration } = data.nextFocusBlock;
    if (duration >= 60) {
      // Show time range for substantial blocks
      parts.push(`Focus: ${start}-${end}`);
    } else if (duration >= 30) {
      // Just show start time for shorter blocks
      parts.push(`Focus: ${start} (${duration}min)`);
    }
  }

  return parts.join(" | ");
}

/**
 * Get next focus block from calendar free blocks
 */
export function getNextFocusBlock(
  freeBlocks: Array<{ startTime: string; endTime: string; duration: number }>
): { start: string; end: string; duration: number } | undefined {
  // Get current time in HH:MM format
  const now = new Date();
  const currentTime = `${now.getHours().toString().padStart(2, "0")}:${now.getMinutes().toString().padStart(2, "0")}`;

  // Find first block that starts after now and is at least 30 minutes
  for (const block of freeBlocks) {
    if (block.startTime > currentTime && block.duration >= 30) {
      return {
        start: formatTime(block.startTime),
        end: formatTime(block.endTime),
        duration: block.duration,
      };
    }
  }

  return undefined;
}

/**
 * Format time for display (remove leading zeros, add am/pm)
 */
function formatTime(time: string): string {
  const [hours, minutes] = time.split(":").map(Number);
  if (hours === undefined || minutes === undefined) return time;

  const ampm = hours >= 12 ? "pm" : "am";
  const displayHours = hours % 12 || 12;
  
  if (minutes === 0) {
    return `${displayHours}${ampm}`;
  }
  return `${displayHours}:${minutes.toString().padStart(2, "0")}${ampm}`;
}

/**
 * Determine calendar shape from meeting count and total minutes
 */
export function determineCalendarShape(
  meetingCount: number,
  totalMinutes: number
): "light" | "moderate" | "heavy" {
  if (meetingCount === 0) return "light";
  if (totalMinutes < 120 || meetingCount <= 2) return "light";
  if (totalMinutes < 240 || meetingCount <= 4) return "moderate";
  return "heavy";
}
