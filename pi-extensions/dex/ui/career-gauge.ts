/**
 * Career Readiness Gauge Component
 * 
 * Shows promotion readiness with competency breakdown.
 */

import { Container, Text, Spacer, truncateToWidth } from "@mariozechner/pi-tui";
import { renderProgressBar, type ProgressBarTheme } from "./progress-bar.js";
import type { Theme } from "@mariozechner/pi-coding-agent";

export interface CompetencyProgress {
  name: string;
  score: number; // 0-100
  status: "weak" | "building" | "on-track" | "strong" | "excellent";
  evidenceCount: number;
}

export interface GapAnalysis {
  competency: string;
  recommendation: string;
}

export interface CareerReadiness {
  overallScore: number; // 0-100
  status: "not-ready" | "building" | "nearly-ready" | "ready";
  competencies: CompetencyProgress[];
  gaps: GapAnalysis[];
  currentLevel?: string; // e.g., "IC4"
  targetLevel?: string; // e.g., "IC5"
}

/**
 * Career Readiness Gauge Component
 * 
 * Visual assessment of promotion readiness.
 */
export class CareerReadinessGauge {
  private readiness: CareerReadiness;
  private theme: Theme;
  private cachedWidth?: number;
  private cachedLines?: string[];

  constructor(readiness: CareerReadiness, theme: Theme) {
    this.readiness = readiness;
    this.theme = theme;
  }

  /**
   * Update readiness data
   */
  update(readiness: CareerReadiness): void {
    this.readiness = readiness;
    this.invalidate();
  }

  /**
   * Render the gauge
   */
  render(width: number): string[] {
    if (this.cachedLines && this.cachedWidth === width) {
      return this.cachedLines;
    }

    const container = new Container();

    // Title
    const title = this.getTitle();
    container.addChild(new Text(this.theme.fg("border", "┌─ " + title + " " + "─".repeat(Math.max(0, width - title.length - 4)) + "┐"), 0, 0));
    container.addChild(new Text(this.theme.fg("border", "│") + " ".repeat(width - 2) + this.theme.fg("border", "│"), 0, 0));

    // Overall score
    this.addOverallScore(container, width);
    container.addChild(new Text(this.theme.fg("border", "│") + " ".repeat(width - 2) + this.theme.fg("border", "│"), 0, 0));

    // Competency breakdown section
    container.addChild(new Text(this.theme.fg("border", "│ ") + this.theme.fg("accent", this.theme.bold("─── Competency Breakdown ───")) + " ".repeat(Math.max(0, width - 32)) + this.theme.fg("border", "│"), 0, 0));
    container.addChild(new Text(this.theme.fg("border", "│") + " ".repeat(width - 2) + this.theme.fg("border", "│"), 0, 0));

    // Competencies
    for (const comp of this.readiness.competencies) {
      this.addCompetencyLine(container, comp, width);
    }
    container.addChild(new Text(this.theme.fg("border", "│") + " ".repeat(width - 2) + this.theme.fg("border", "│"), 0, 0));

    // Gap analysis if present
    if (this.readiness.gaps.length > 0) {
      container.addChild(new Text(this.theme.fg("border", "│ ") + this.theme.fg("accent", this.theme.bold("─── Gap Analysis ───")) + " ".repeat(Math.max(0, width - 24)) + this.theme.fg("border", "│"), 0, 0));
      container.addChild(new Text(this.theme.fg("border", "│") + " ".repeat(width - 2) + this.theme.fg("border", "│"), 0, 0));

      container.addChild(new Text(this.theme.fg("border", "│ ") + this.theme.fg("text", "Focus Areas:") + " ".repeat(Math.max(0, width - 16)) + this.theme.fg("border", "│"), 0, 0));
      for (let i = 0; i < this.readiness.gaps.length; i++) {
        this.addGapLine(container, this.readiness.gaps[i]!, i + 1, width);
      }
      container.addChild(new Text(this.theme.fg("border", "│") + " ".repeat(width - 2) + this.theme.fg("border", "│"), 0, 0));
    }

    // Actions
    const actions = "[View Evidence] [Capture New Evidence] [Export Assessment]";
    const actionsLine = this.theme.fg("border", "│ ") + this.theme.fg("dim", truncateToWidth(actions, width - 4)) + " ".repeat(Math.max(0, width - 4 - actions.length)) + this.theme.fg("border", "│");
    container.addChild(new Text(actionsLine, 0, 0));

    // Bottom border
    container.addChild(new Text(this.theme.fg("border", "└" + "─".repeat(width - 2) + "┘"), 0, 0));

    this.cachedWidth = width;
    this.cachedLines = container.render(width);
    return this.cachedLines;
  }

  private getTitle(): string {
    const { currentLevel, targetLevel } = this.readiness;
    if (currentLevel && targetLevel) {
      return `Promotion Readiness: ${currentLevel} → ${targetLevel}`;
    }
    return "Promotion Readiness";
  }

  private addOverallScore(container: Container, width: number): void {
    const { overallScore, status } = this.readiness;
    const barWidth = 20;
    const progressBarTheme: ProgressBarTheme = {
      filled: (s) => this.getOverallStatusColor(status)(s),
      empty: (s) => this.theme.fg("dim", s),
    };

    const bar = renderProgressBar(overallScore, barWidth, progressBarTheme);
    const scoreLine = `Overall: ${overallScore}/100    [${bar}] ${overallScore}%`;
    const padding = " ".repeat(Math.max(0, width - 4 - scoreLine.length));
    container.addChild(new Text(this.theme.fg("border", "│ ") + scoreLine + padding + this.theme.fg("border", "│"), 0, 0));

    const statusText = `Status: ${this.getStatusLabel(status)}`;
    const statusPadding = " ".repeat(Math.max(0, width - 4 - statusText.length));
    container.addChild(new Text(this.theme.fg("border", "│ ") + this.getOverallStatusColor(status)(statusText) + statusPadding + this.theme.fg("border", "│"), 0, 0));
  }

  private addCompetencyLine(container: Container, comp: CompetencyProgress, width: number): void {
    const barWidth = 10;
    const progressBarTheme: ProgressBarTheme = {
      filled: (s) => this.getCompetencyStatusColor(comp.status)(s),
      empty: (s) => this.theme.fg("dim", s),
    };

    const bar = renderProgressBar(comp.score, barWidth, progressBarTheme);
    const statusIcon = this.getCompetencyStatusIcon(comp.status);
    const label = comp.name.padEnd(18);
    const line = `${label} [${bar}] ${Math.round(comp.score).toString().padStart(3)}%   ${statusIcon}`;
    const padding = " ".repeat(Math.max(0, width - 4 - this.getVisibleWidth(line)));
    container.addChild(new Text(this.theme.fg("border", "│ ") + line + padding + this.theme.fg("border", "│"), 0, 0));
  }

  private addGapLine(container: Container, gap: GapAnalysis, index: number, width: number): void {
    const line = `${index}. ${gap.competency} - ${gap.recommendation}`;
    const truncated = truncateToWidth(line, width - 6);
    const padding = " ".repeat(Math.max(0, width - 6 - truncated.length));
    container.addChild(new Text(this.theme.fg("border", "│   ") + this.theme.fg("text", truncated) + padding + this.theme.fg("border", "│"), 0, 0));
  }

  private getStatusLabel(status: CareerReadiness["status"]): string {
    switch (status) {
      case "not-ready":
        return "Not Ready";
      case "building":
        return "Building";
      case "nearly-ready":
        return "Nearly Ready";
      case "ready":
        return "Ready";
    }
  }

  private getOverallStatusColor(status: CareerReadiness["status"]): (s: string) => string {
    switch (status) {
      case "not-ready":
        return (s) => this.theme.fg("error", s);
      case "building":
        return (s) => this.theme.fg("warning", s);
      case "nearly-ready":
        return (s) => this.theme.fg("accent", s);
      case "ready":
        return (s) => this.theme.fg("success", s);
    }
  }

  private getCompetencyStatusIcon(status: CompetencyProgress["status"]): string {
    switch (status) {
      case "weak":
        return this.theme.fg("error", "⚠️ Needs more evidence");
      case "building":
        return this.theme.fg("warning", "🔄 Building");
      case "on-track":
        return this.theme.fg("accent", "✅ On track");
      case "strong":
        return this.theme.fg("success", "✅ Strong");
      case "excellent":
        return this.theme.fg("success", "✅ Excellent");
    }
  }

  private getCompetencyStatusColor(status: CompetencyProgress["status"]): (s: string) => string {
    switch (status) {
      case "weak":
        return (s) => this.theme.fg("error", s);
      case "building":
        return (s) => this.theme.fg("warning", s);
      case "on-track":
        return (s) => this.theme.fg("accent", s);
      case "strong":
        return (s) => this.theme.fg("success", s);
      case "excellent":
        return (s) => this.theme.fg("success", s);
    }
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
