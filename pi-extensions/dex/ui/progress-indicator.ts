/**
 * Progress Indicator Component
 * 
 * Shows real-time progress of parallel sub-agent execution.
 */

import { Container, Text, Spacer, truncateToWidth } from "@mariozechner/pi-tui";
import { renderProgressBar, type ProgressBarTheme } from "./progress-bar.js";
import type { Theme } from "@mariozechner/pi-coding-agent";

export interface ScoutProgress {
  name: string;
  status: "pending" | "running" | "complete" | "error";
  progress: number; // 0-100
  duration?: number; // ms
  error?: string;
}

export interface ProgressIndicatorOptions {
  title?: string;
  showEstimate?: boolean;
}

/**
 * Progress Indicator Component
 * 
 * Visual feedback for parallel sub-agent operations.
 */
export class ProgressIndicator {
  private scouts: Map<string, ScoutProgress>;
  private options: Required<ProgressIndicatorOptions>;
  private theme: Theme;
  private cachedWidth?: number;
  private cachedLines?: string[];

  constructor(
    scouts: ScoutProgress[],
    theme: Theme,
    options: ProgressIndicatorOptions = {}
  ) {
    this.scouts = new Map(scouts.map((s) => [s.name, s]));
    this.theme = theme;
    this.options = {
      title: options.title ?? "Smart Work: Planning",
      showEstimate: options.showEstimate ?? true,
    };
  }

  /**
   * Update a specific scout's progress
   */
  updateScout(name: string, update: Partial<ScoutProgress>): void {
    const scout = this.scouts.get(name);
    if (scout) {
      Object.assign(scout, update);
      this.invalidate();
    }
  }

  /**
   * Get completed count
   */
  get completedCount(): number {
    return Array.from(this.scouts.values()).filter(
      (s) => s.status === "complete"
    ).length;
  }

  /**
   * Get total count
   */
  get totalCount(): number {
    return this.scouts.size;
  }

  /**
   * Get average duration of completed scouts
   */
  get averageDuration(): number {
    const completed = Array.from(this.scouts.values()).filter(
      (s) => s.status === "complete" && s.duration !== undefined
    );
    if (completed.length === 0) return 0;
    const total = completed.reduce((sum, s) => sum + (s.duration ?? 0), 0);
    return total / completed.length;
  }

  /**
   * Estimate remaining time
   */
  get estimatedRemaining(): number {
    const remaining = this.totalCount - this.completedCount;
    if (remaining === 0) return 0;
    const avg = this.averageDuration;
    return avg > 0 ? avg * remaining : 0;
  }

  /**
   * Render the progress indicator
   */
  render(width: number): string[] {
    if (this.cachedLines && this.cachedWidth === width) {
      return this.cachedLines;
    }

    const lines: string[] = [];

    // Top border
    lines.push(this.theme.fg("border", "┌─ " + this.options.title + " " + "─".repeat(Math.max(0, width - this.options.title.length - 4)) + "┐"));

    // Empty line
    lines.push(this.theme.fg("border", "│") + " ".repeat(width - 2) + this.theme.fg("border", "│"));

    // Status message
    const statusMsg = this.getStatusMessage();
    lines.push(this.theme.fg("border", "│") + "  " + truncateToWidth(statusMsg, width - 4) + " ".repeat(Math.max(0, width - 4 - statusMsg.length)) + this.theme.fg("border", "│"));

    // Empty line
    lines.push(this.theme.fg("border", "│") + " ".repeat(width - 2) + this.theme.fg("border", "│"));

    // Scout progress bars
    for (const scout of this.scouts.values()) {
      const line = this.renderScoutLine(scout, width);
      lines.push(this.theme.fg("border", "│") + "  " + line + " ".repeat(Math.max(0, width - 4 - this.getVisibleWidth(line))) + this.theme.fg("border", "│"));
    }

    // Empty line
    lines.push(this.theme.fg("border", "│") + " ".repeat(width - 2) + this.theme.fg("border", "│"));

    // Summary line if showing estimate
    if (this.options.showEstimate && this.completedCount > 0) {
      const summary = this.getSummaryLine();
      lines.push(this.theme.fg("border", "│") + "  " + truncateToWidth(summary, width - 4) + " ".repeat(Math.max(0, width - 4 - summary.length)) + this.theme.fg("border", "│"));
      lines.push(this.theme.fg("border", "│") + " ".repeat(width - 2) + this.theme.fg("border", "│"));
    }

    // Bottom border
    lines.push(this.theme.fg("border", "└" + "─".repeat(width - 2) + "┘"));

    this.cachedWidth = width;
    this.cachedLines = lines;
    return lines;
  }

  private getStatusMessage(): string {
    const completed = this.completedCount;
    const total = this.totalCount;

    if (completed === 0) {
      return this.theme.fg("dim", `Spawning ${total} parallel scouts...`);
    } else if (completed === total) {
      return this.theme.fg("success", "✅ All scouts complete!");
    } else {
      return this.theme.fg("accent", `Processing: ${completed}/${total} complete`);
    }
  }

  private renderScoutLine(scout: ScoutProgress, width: number): string {
    const barWidth = 10;
    const progressBarTheme: ProgressBarTheme = {
      filled: (s) => this.getStatusColor(scout.status)(s),
      empty: (s) => this.theme.fg("dim", s),
    };

    const statusIcon = this.getStatusIcon(scout.status);
    const bar = renderProgressBar(scout.progress, barWidth, progressBarTheme);
    const statusText = this.getStatusText(scout);

    return `${statusIcon} ${truncateToWidth(scout.name, 20).padEnd(20)} [${bar}] ${statusText}`;
  }

  private getStatusIcon(status: ScoutProgress["status"]): string {
    switch (status) {
      case "pending":
        return this.theme.fg("dim", "⏸");
      case "running":
        return this.theme.fg("accent", "⏳");
      case "complete":
        return this.theme.fg("success", "✅");
      case "error":
        return this.theme.fg("error", "❌");
    }
  }

  private getStatusColor(status: ScoutProgress["status"]): (s: string) => string {
    switch (status) {
      case "pending":
        return (s) => this.theme.fg("dim", s);
      case "running":
        return (s) => this.theme.fg("accent", s);
      case "complete":
        return (s) => this.theme.fg("success", s);
      case "error":
        return (s) => this.theme.fg("error", s);
    }
  }

  private getStatusText(scout: ScoutProgress): string {
    switch (scout.status) {
      case "pending":
        return this.theme.fg("dim", "Waiting...");
      case "running":
        return this.theme.fg("accent", "Running...");
      case "complete":
        return scout.duration
          ? this.theme.fg("success", `Complete (${(scout.duration / 1000).toFixed(1)}s)`)
          : this.theme.fg("success", "Complete");
      case "error":
        return scout.error
          ? this.theme.fg("error", `Error: ${scout.error}`)
          : this.theme.fg("error", "Error");
    }
  }

  private getSummaryLine(): string {
    const completed = this.completedCount;
    const total = this.totalCount;
    const avg = this.averageDuration;
    const est = this.estimatedRemaining();

    const avgText = avg > 0 ? `Avg: ${(avg / 1000).toFixed(1)}s` : "";
    const estText = est > 0 ? `Est. remaining: ${(est / 1000).toFixed(1)}s` : "";

    const parts = [
      this.theme.fg("dim", `${completed}/${total} complete`),
      avgText && this.theme.fg("dim", avgText),
      estText && this.theme.fg("dim", estText),
    ].filter(Boolean);

    return parts.join(this.theme.fg("dim", " • "));
  }

  private getVisibleWidth(str: string): number {
    // Simple ANSI stripping for width calculation
    // eslint-disable-next-line no-control-regex
    return str.replace(/\x1b\[[0-9;]*m/g, "").length;
  }

  invalidate(): void {
    this.cachedWidth = undefined;
    this.cachedLines = undefined;
  }
}
