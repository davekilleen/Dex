/**
 * Week Progress Bar Component
 * 
 * Shows week progress (Day X/5) and priority status in compact or full mode.
 */

import { truncateToWidth } from "@mariozechner/pi-tui";
import { renderProgressBar, type ProgressBarTheme } from "./progress-bar.js";
import type { Theme } from "@mariozechner/pi-coding-agent";

export interface PriorityProgress {
  name: string; // "Priority 1", "Priority 2", etc.
  progress: number; // 0-100
  status: "on-track" | "behind" | "not-started";
}

export interface WeekProgress {
  dayOfWeek: number; // 1-5 (Mon-Fri)
  priorities: PriorityProgress[];
}

/**
 * Week Progress Bar Component
 * 
 * Can render in compact mode (for footer) or full mode (for widget).
 */
export class WeekProgressBar {
  private progress: WeekProgress;
  private theme: Theme;
  private cachedCompact?: string;
  private cachedFull?: { width: number; lines: string[] };

  constructor(progress: WeekProgress, theme: Theme) {
    this.progress = progress;
    this.theme = theme;
  }

  /**
   * Update progress data
   */
  update(progress: WeekProgress): void {
    this.progress = progress;
    this.invalidate();
  }

  /**
   * Render compact mode for footer
   * 
   * Format: "Day 3/5 [▓▓▓░░] ⚠️ P2,P3"
   */
  renderCompact(): string {
    if (this.cachedCompact) {
      return this.cachedCompact;
    }

    const { dayOfWeek, priorities } = this.progress;
    const parts: string[] = [];

    // Day indicator
    parts.push(this.theme.fg("text", `Day ${dayOfWeek}/5`));

    // Overall progress bar (average of all priorities)
    const avgProgress = this.getAverageProgress();
    const barWidth = 5;
    const progressBarTheme: ProgressBarTheme = {
      filled: (s) => this.theme.fg("accent", s),
      empty: (s) => this.theme.fg("dim", s),
    };
    const bar = renderProgressBar(avgProgress, barWidth, progressBarTheme);
    parts.push(`[${bar}]`);

    // Warning indicators for behind/not-started priorities
    const warnings = priorities
      .filter((p) => p.status === "behind" || p.status === "not-started")
      .map((p) => p.name.replace("Priority ", "P"));

    if (warnings.length > 0) {
      parts.push(this.theme.fg("warning", `⚠️ ${warnings.join(",")}`));
    }

    this.cachedCompact = parts.join(" ");
    return this.cachedCompact;
  }

  /**
   * Render full mode for widget
   * 
   * Shows detailed progress bars for each priority.
   */
  renderFull(width: number): string[] {
    if (this.cachedFull && this.cachedFull.width === width) {
      return this.cachedFull.lines;
    }

    const lines: string[] = [];
    const { dayOfWeek, priorities } = this.progress;

    // Header
    const header = this.theme.fg("accent", this.theme.bold("Week Progress"));
    lines.push("┌─ " + header + " " + "─".repeat(Math.max(0, width - 16)) + "┐");

    // Day indicator
    const dayText = `Day ${dayOfWeek}/5`;
    lines.push("│ " + truncateToWidth(dayText, width - 4) + " ".repeat(Math.max(0, width - 4 - dayText.length)) + " │");

    // Empty line
    lines.push("│" + " ".repeat(width - 2) + "│");

    // Priority progress bars
    for (const priority of priorities) {
      const line = this.renderPriorityLine(priority, width - 4);
      lines.push("│ " + line + " ".repeat(Math.max(0, width - 4 - this.getVisibleWidth(line))) + " │");
    }

    // Bottom border
    lines.push("└" + "─".repeat(width - 2) + "┘");

    this.cachedFull = { width, lines };
    return lines;
  }

  private renderPriorityLine(priority: PriorityProgress, maxWidth: number): string {
    const barWidth = 10;
    const progressBarTheme: ProgressBarTheme = {
      filled: (s) => this.getStatusColor(priority.status)(s),
      empty: (s) => this.theme.fg("dim", s),
    };

    const bar = renderProgressBar(priority.progress, barWidth, progressBarTheme);
    const statusIcon = this.getStatusIcon(priority.status);
    const label = priority.name.padEnd(12);

    return truncateToWidth(
      `${label} [${bar}] ${Math.round(priority.progress)}% ${statusIcon}`,
      maxWidth
    );
  }

  private getStatusIcon(status: PriorityProgress["status"]): string {
    switch (status) {
      case "on-track":
        return this.theme.fg("success", "✅");
      case "behind":
        return this.theme.fg("warning", "⚠️");
      case "not-started":
        return this.theme.fg("error", "❗");
    }
  }

  private getStatusColor(status: PriorityProgress["status"]): (s: string) => string {
    switch (status) {
      case "on-track":
        return (s) => this.theme.fg("success", s);
      case "behind":
        return (s) => this.theme.fg("warning", s);
      case "not-started":
        return (s) => this.theme.fg("error", s);
    }
  }

  private getAverageProgress(): number {
    if (this.progress.priorities.length === 0) return 0;
    const total = this.progress.priorities.reduce((sum, p) => sum + p.progress, 0);
    return total / this.progress.priorities.length;
  }

  private getVisibleWidth(str: string): number {
    // Simple ANSI stripping for width calculation
    // eslint-disable-next-line no-control-regex
    return str.replace(/\x1b\[[0-9;]*m/g, "").length;
  }

  /**
   * Render as a Component-compatible object
   */
  render(width: number): string[] {
    return this.renderFull(width);
  }

  invalidate(): void {
    this.cachedCompact = undefined;
    this.cachedFull = undefined;
  }
}
