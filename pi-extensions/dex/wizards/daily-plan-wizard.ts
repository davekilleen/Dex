/**
 * Daily Plan Wizard
 * 
 * Interactive multi-step wizard for daily planning.
 */

import { Container, Text, Spacer, truncateToWidth, matchesKey, Key } from "@mariozechner/pi-tui";
import { ProgressIndicator, type ScoutProgress } from "../ui/progress-indicator.js";
import { WeekProgressBar, type WeekProgress } from "../ui/week-progress.js";
import { CollapsibleSection } from "../ui/collapsible-section.js";
import type { Theme } from "@mariozechner/pi-coding-agent";

export interface CalendarEvent {
  title: string;
  startTime: string;
  endTime: string;
  duration: number; // minutes
}

export interface FreeBlock {
  startTime: string;
  endTime: string;
  duration: number; // minutes
  label: string;
}

export interface CalendarScoutResult {
  events: CalendarEvent[];
  freeBlocks: FreeBlock[];
  shape: "light" | "moderate" | "heavy";
  totalMeetingMinutes: number;
}

export interface TaskScoutResult {
  p0Tasks: string[];
  p1Tasks: string[];
  overdueTasksstring[];
  totalOpen: number;
}

export interface WeekScoutResult {
  dayOfWeek: number;
  weekProgress: WeekProgress;
}

export interface FocusSuggestion {
  task: string;
  reason: string;
  selected: boolean;
}

export interface DailyPlanWizardProps {
  calendarData?: CalendarScoutResult;
  taskData?: TaskScoutResult;
  weekData?: WeekScoutResult;
  onComplete: (plan: { focusTasks: string[]; notes: string }) => void;
  onCancel: () => void;
}

type WizardState = "loading" | "ready" | "customizing" | "generating";

/**
 * Daily Plan Wizard
 * 
 * Multi-step interactive daily planning experience.
 */
export class DailyPlanWizard {
  private props: DailyPlanWizardProps;
  private theme: Theme;
  private state: WizardState;
  private focusSuggestions: FocusSuggestion[];
  private selectedFocusIndex: number = 0;
  private sections: {
    calendar?: CollapsibleSection;
    week?: CollapsibleSection;
    focus?: CollapsibleSection;
  } = {};
  private cachedWidth?: number;
  private cachedLines?: string[];

  constructor(props: DailyPlanWizardProps, theme: Theme) {
    this.props = props;
    this.theme = theme;
    this.state = props.calendarData ? "ready" : "loading";
    this.focusSuggestions = this.generateFocusSuggestions();
  }

  /**
   * Handle keyboard input
   */
  handleInput(data: string): void {
    if (this.state === "loading" || this.state === "generating") {
      if (matchesKey(data, Key.escape)) {
        this.props.onCancel();
      }
      return;
    }

    if (matchesKey(data, Key.up)) {
      this.selectedFocusIndex = Math.max(0, this.selectedFocusIndex - 1);
      this.invalidate();
    } else if (matchesKey(data, Key.down)) {
      this.selectedFocusIndex = Math.min(this.focusSuggestions.length - 1, this.selectedFocusIndex + 1);
      this.invalidate();
    } else if (matchesKey(data, Key.space)) {
      this.toggleFocusSelection();
    } else if (matchesKey(data, Key.enter)) {
      this.generatePlan();
    } else if (matchesKey(data, Key.escape)) {
      this.props.onCancel();
    } else if (matchesKey(data, "c")) {
      this.state = "customizing";
      this.invalidate();
    }
  }

  /**
   * Render the wizard
   */
  render(width: number): string[] {
    if (this.cachedLines && this.cachedWidth === width && this.state !== "loading") {
      return this.cachedLines;
    }

    const container = new Container();

    // Title
    const title = this.theme.fg("accent", this.theme.bold("Daily Plan Wizard"));
    container.addChild(new Text("┌─ " + title + " " + "─".repeat(Math.max(0, width - 22)) + "┐", 0, 0));
    container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));

    if (this.state === "loading") {
      this.renderLoadingState(container, width);
    } else if (this.state === "generating") {
      this.renderGeneratingState(container, width);
    } else {
      this.renderReadyState(container, width);
    }

    // Bottom border
    container.addChild(new Text("└" + "─".repeat(width - 2) + "┘", 0, 0));

    this.cachedWidth = width;
    this.cachedLines = container.render(width);
    return this.cachedLines;
  }

  private renderLoadingState(container: Container, width: number): void {
    const loadingText = this.theme.fg("dim", "⏳ Gathering context...");
    container.addChild(new Text("│ " + loadingText + " ".repeat(Math.max(0, width - 4 - loadingText.length)) + " │", 0, 0));
    container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));

    // TODO: Show progress indicator when we have scout progress
    const statusText = this.theme.fg("dim", "Loading calendar, tasks, and week progress...");
    container.addChild(new Text("│ " + statusText + " ".repeat(Math.max(0, width - 4 - statusText.length)) + " │", 0, 0));
    container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));
  }

  private renderGeneratingState(container: Container, width: number): void {
    const genText = this.theme.fg("accent", "✨ Generating your daily plan...");
    container.addChild(new Text("│ " + genText + " ".repeat(Math.max(0, width - 4 - this.getVisibleWidth(genText))) + " │", 0, 0));
    container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));
  }

  private renderReadyState(container: Container, width: number): void {
    // Calendar section
    if (this.props.calendarData) {
      this.renderCalendarSection(container, width);
      container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));
      container.addChild(new Text("│ " + this.theme.fg("dim", "─".repeat(width - 4)) + " │", 0, 0));
      container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));
    }

    // Week progress section
    if (this.props.weekData) {
      this.renderWeekProgressSection(container, width);
      container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));
      container.addChild(new Text("│ " + this.theme.fg("dim", "─".repeat(width - 4)) + " │", 0, 0));
      container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));
    }

    // Focus suggestions
    this.renderFocusSection(container, width);
    container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));

    // Actions
    const actions = "[Generate Plan] [Customize (c)] [Cancel (esc)]";
    container.addChild(new Text("│ " + this.theme.fg("dim", truncateToWidth(actions, width - 4)) + " ".repeat(Math.max(0, width - 4 - actions.length)) + " │", 0, 0));
    container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));
  }

  private renderCalendarSection(container: Container, width: number): void {
    const cal = this.props.calendarData!;
    const shapeLabel = cal.shape.toUpperCase();
    const shapeColor = cal.shape === "light" ? "success" : cal.shape === "moderate" ? "warning" : "error";
    const shapeText = this.theme.fg(shapeColor, shapeLabel);

    const headerText = `📅 Today's Shape: ${shapeText} (${cal.events.length} meetings, ${(cal.totalMeetingMinutes / 60).toFixed(1)} hours)`;
    container.addChild(new Text("│ " + headerText + " ".repeat(Math.max(0, width - 4 - this.getVisibleWidth(headerText))) + " │", 0, 0));
    container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));

    // Free blocks
    if (cal.freeBlocks.length > 0) {
      container.addChild(new Text("│ " + this.theme.fg("text", "Free Blocks:") + " ".repeat(Math.max(0, width - 16)) + " │", 0, 0));
      for (const block of cal.freeBlocks) {
        const blockText = `• ${block.startTime}-${block.endTime} (${block.duration} min) - ${block.label}`;
        container.addChild(new Text("│ " + this.theme.fg("dim", truncateToWidth(blockText, width - 4)) + " ".repeat(Math.max(0, width - 4 - blockText.length)) + " │", 0, 0));
      }
    }
  }

  private renderWeekProgressSection(container: Container, width: number): void {
    const week = this.props.weekData!;
    const weekBar = new WeekProgressBar(week.weekProgress, this.theme);

    const headerText = `📊 Week Progress: Day ${week.dayOfWeek}/5`;
    container.addChild(new Text("│ " + this.theme.fg("accent", this.theme.bold(headerText)) + " ".repeat(Math.max(0, width - 4 - headerText.length)) + " │", 0, 0));

    // Render week progress lines
    const progressLines = weekBar.renderFull(width - 4);
    for (const line of progressLines) {
      container.addChild(new Text("│ " + line + " ".repeat(Math.max(0, width - 4 - this.getVisibleWidth(line))) + " │", 0, 0));
    }
  }

  private renderFocusSection(container: Container, width: number): void {
    const headerText = "🎯 Suggested Focus (based on week progress):";
    container.addChild(new Text("│ " + this.theme.fg("accent", this.theme.bold(headerText)) + " ".repeat(Math.max(0, width - 4 - this.getVisibleWidth(headerText))) + " │", 0, 0));
    container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));

    for (let i = 0; i < this.focusSuggestions.length; i++) {
      const suggestion = this.focusSuggestions[i]!;
      const isSelected = i === this.selectedFocusIndex;
      const checkbox = suggestion.selected ? "☑" : "☐";
      const prefix = isSelected ? "> " : "  ";
      const text = `${prefix}${checkbox} ${suggestion.task}`;

      const styled = isSelected
        ? this.theme.fg("accent", this.theme.bold(truncateToWidth(text, width - 4)))
        : this.theme.fg("text", truncateToWidth(text, width - 4));

      container.addChild(new Text("│ " + styled + " ".repeat(Math.max(0, width - 4 - this.getVisibleWidth(styled))) + " │", 0, 0));
    }

    // Help text
    container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));
    const helpText = "↑↓ navigate • space toggle • enter generate";
    container.addChild(new Text("│ " + this.theme.fg("dim", truncateToWidth(helpText, width - 4)) + " ".repeat(Math.max(0, width - 4 - helpText.length)) + " │", 0, 0));
  }

  private generateFocusSuggestions(): FocusSuggestion[] {
    const suggestions: FocusSuggestion[] = [];

    // Add P0/overdue tasks
    if (this.props.taskData) {
      for (const task of this.props.taskData.p0Tasks.slice(0, 2)) {
        suggestions.push({
          task: truncateToWidth(task, 60),
          reason: "P0 task - needs attention",
          selected: true,
        });
      }

      for (const task of this.props.taskData.overdueTaskasks.slice(0, 1)) {
        suggestions.push({
          task: truncateToWidth(task, 60),
          reason: "Overdue - catch up needed",
          selected: true,
        });
      }
    }

    // Add week progress catch-up if behind
    if (this.props.weekData) {
      const behind = this.props.weekData.weekProgress.priorities.filter((p) => p.status === "behind");
      for (const priority of behind.slice(0, 1)) {
        suggestions.push({
          task: `${priority.name} - needs catch-up`,
          reason: "Behind on weekly priority",
          selected: true,
        });
      }
    }

    // Ensure at least one suggestion
    if (suggestions.length === 0) {
      suggestions.push({
        task: "Review open tasks",
        reason: "Start your day organized",
        selected: true,
      });
    }

    return suggestions;
  }

  private toggleFocusSelection(): void {
    const suggestion = this.focusSuggestions[this.selectedFocusIndex];
    if (suggestion) {
      suggestion.selected = !suggestion.selected;
      this.invalidate();
    }
  }

  private generatePlan(): void {
    this.state = "generating";
    this.invalidate();

    // Get selected focus tasks
    const focusTasks = this.focusSuggestions
      .filter((s) => s.selected)
      .map((s) => s.task);

    // Call completion callback (this would trigger actual plan generation)
    setTimeout(() => {
      this.props.onComplete({
        focusTasks,
        notes: "",
      });
    }, 500);
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
