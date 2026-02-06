/**
 * Daily Review Wizard
 * 
 * End-of-day review with inline actions for task completion,
 * commitment creation, and career evidence capture.
 */

import { Container, Text, Spacer, truncateToWidth, matchesKey, Key } from "@mariozechner/pi-tui";
import { CollapsibleSection } from "../ui/collapsible-section.js";
import type { Theme } from "@mariozechner/pi-coding-agent";

export interface Task {
  id: string;
  title: string;
  status: "open" | "completed";
}

export interface Commitment {
  text: string;
  source: string; // "conversation" | "email" | "slack"
  type: "promise" | "ask";
  dismissed: boolean;
}

export interface EvidenceSuggestion {
  achievement: string;
  skill?: string;
  impact?: string;
  dismissed: boolean;
}

export interface DailyReviewWizardProps {
  completedTasks: Task[];
  openTasks: Task[];
  commitments: Commitment[];
  careerEvidenceSuggestions: EvidenceSuggestion[];
  onTaskComplete: (taskId: string) => Promise<void>;
  onTaskReschedule: (taskId: string) => Promise<void>;
  onCommitmentCreate: (commitment: Commitment) => Promise<void>;
  onCommitmentDismiss: (commitment: Commitment) => void;
  onEvidenceCapture: (suggestion: EvidenceSuggestion) => Promise<void>;
  onEvidenceDismiss: (suggestion: EvidenceSuggestion) => void;
  onComplete: () => void;
  onCancel: () => void;
}

type Section = "completed" | "open" | "commitments" | "evidence";

/**
 * Daily Review Wizard
 * 
 * Interactive end-of-day review with inline actions.
 */
export class DailyReviewWizard {
  private props: DailyReviewWizardProps;
  private theme: Theme;
  private currentSection: Section = "completed";
  private selectedIndex: number = 0;
  private sections: Map<Section, boolean> = new Map([
    ["completed", false],
    ["open", false],
    ["commitments", false],
    ["evidence", false],
  ]);
  private cachedWidth?: number;
  private cachedLines?: string[];

  constructor(props: DailyReviewWizardProps, theme: Theme) {
    this.props = props;
    this.theme = theme;
  }

  /**
   * Handle keyboard input
   */
  handleInput(data: string): void {
    if (matchesKey(data, Key.up)) {
      this.moveSelection(-1);
    } else if (matchesKey(data, Key.down)) {
      this.moveSelection(1);
    } else if (matchesKey(data, Key.tab)) {
      this.moveToNextSection();
    } else if (matchesKey(data, Key.shift(Key.tab))) {
      this.moveToPrevSection();
    } else if (matchesKey(data, Key.enter)) {
      this.executeAction();
    } else if (matchesKey(data, "d")) {
      this.handleDismiss();
    } else if (matchesKey(data, "c")) {
      this.toggleSection();
    } else if (matchesKey(data, Key.escape)) {
      this.props.onCancel();
    } else if (matchesKey(data, "s")) {
      this.props.onComplete();
    }
  }

  /**
   * Render the wizard
   */
  render(width: number): string[] {
    if (this.cachedLines && this.cachedWidth === width) {
      return this.cachedLines;
    }

    const container = new Container();

    // Title
    const title = this.theme.fg("accent", this.theme.bold("Daily Review"));
    container.addChild(new Text("┌─ " + title + " " + "─".repeat(Math.max(0, width - 18)) + "┐", 0, 0));
    container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));

    // Completed tasks section
    this.renderCompletedSection(container, width);
    container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));

    // Open tasks section
    this.renderOpenSection(container, width);
    container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));

    // Commitments section
    this.renderCommitmentsSection(container, width);
    container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));

    // Career evidence section
    if (this.props.careerEvidenceSuggestions.length > 0) {
      this.renderEvidenceSection(container, width);
      container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));
    }

    // Actions
    const actions = "[Save Review (s)] [Add Notes] [Cancel (esc)]";
    container.addChild(new Text("│ " + this.theme.fg("dim", truncateToWidth(actions, width - 4)) + " ".repeat(Math.max(0, width - 4 - actions.length)) + " │", 0, 0));
    container.addChild(new Text("│" + " ".repeat(width - 2) + "│", 0, 0));

    // Bottom border
    container.addChild(new Text("└" + "─".repeat(width - 2) + "┘", 0, 0));

    this.cachedWidth = width;
    this.cachedLines = container.render(width);
    return this.cachedLines;
  }

  private renderCompletedSection(container: Container, width: number): void {
    const isActive = this.currentSection === "completed";
    const collapsed = this.sections.get("completed") ?? false;
    const indicator = collapsed ? "▶" : "▼";

    const headerText = `${indicator} ✅ Tasks Completed Today (${this.props.completedTasks.length})`;
    const headerStyled = isActive
      ? this.theme.fg("accent", this.theme.bold(headerText))
      : this.theme.fg("text", headerText);

    container.addChild(new Text("│ " + truncateToWidth(headerStyled, width - 4) + " ".repeat(Math.max(0, width - 4 - this.getVisibleWidth(headerStyled))) + " │", 0, 0));

    if (!collapsed) {
      container.addChild(new Text("│ " + this.theme.fg("dim", "─".repeat(width - 4)) + " │", 0, 0));

      if (this.props.completedTasks.length === 0) {
        const emptyText = this.theme.fg("dim", "No tasks completed today");
        container.addChild(new Text("│   " + emptyText + " ".repeat(Math.max(0, width - 6 - emptyText.length)) + " │", 0, 0));
      } else {
        for (const task of this.props.completedTasks) {
          const taskText = `✓ ${truncateToWidth(task.title, width - 8)}`;
          container.addChild(new Text("│   " + this.theme.fg("success", taskText) + " ".repeat(Math.max(0, width - 6 - taskText.length)) + " │", 0, 0));
        }
      }
    }
  }

  private renderOpenSection(container: Container, width: number): void {
    const isActive = this.currentSection === "open";
    const collapsed = this.sections.get("open") ?? false;
    const indicator = collapsed ? "▶" : "▼";

    const headerText = `${indicator} 📋 Still Open (${this.props.openTasks.length})`;
    const headerStyled = isActive
      ? this.theme.fg("accent", this.theme.bold(headerText))
      : this.theme.fg("text", headerText);

    container.addChild(new Text("│ " + truncateToWidth(headerStyled, width - 4) + " ".repeat(Math.max(0, width - 4 - this.getVisibleWidth(headerStyled))) + " │", 0, 0));

    if (!collapsed) {
      container.addChild(new Text("│ " + this.theme.fg("dim", "─".repeat(width - 4)) + " │", 0, 0));

      if (this.props.openTasks.length === 0) {
        const emptyText = this.theme.fg("dim", "All caught up!");
        container.addChild(new Text("│   " + emptyText + " ".repeat(Math.max(0, width - 6 - emptyText.length)) + " │", 0, 0));
      } else {
        for (let i = 0; i < this.props.openTasks.length; i++) {
          const task = this.props.openTasks[i]!;
          const isSelected = isActive && i === this.selectedIndex;
          this.renderOpenTaskLine(container, task, isSelected, width);
        }
      }
    }
  }

  private renderOpenTaskLine(container: Container, task: Task, isSelected: boolean, width: number): void {
    const prefix = isSelected ? ">" : " ";
    const taskText = `${prefix} [ ] → ${truncateToWidth(task.title, width - 30)}`;
    const actions = "[Done] [Reschedule]";

    const line = isSelected
      ? this.theme.fg("accent", this.theme.bold(taskText)) + " " + this.theme.fg("dim", actions)
      : this.theme.fg("text", taskText);

    container.addChild(new Text("│  " + line + " ".repeat(Math.max(0, width - 4 - this.getVisibleWidth(line))) + " │", 0, 0));
  }

  private renderCommitmentsSection(container: Container, width: number): void {
    const isActive = this.currentSection === "commitments";
    const collapsed = this.sections.get("commitments") ?? false;
    const indicator = collapsed ? "▶" : "▼";
    const activeCommitments = this.props.commitments.filter((c) => !c.dismissed);

    const headerText = `${indicator} ⚡ Commitments Detected (${activeCommitments.length})`;
    const headerStyled = isActive
      ? this.theme.fg("accent", this.theme.bold(headerText))
      : this.theme.fg("text", headerText);

    container.addChild(new Text("│ " + truncateToWidth(headerStyled, width - 4) + " ".repeat(Math.max(0, width - 4 - this.getVisibleWidth(headerStyled))) + " │", 0, 0));

    if (!collapsed) {
      container.addChild(new Text("│ " + this.theme.fg("dim", "─".repeat(width - 4)) + " │", 0, 0));

      if (activeCommitments.length === 0) {
        const emptyText = this.theme.fg("dim", "No commitments detected");
        container.addChild(new Text("│   " + emptyText + " ".repeat(Math.max(0, width - 6 - emptyText.length)) + " │", 0, 0));
      } else {
        for (let i = 0; i < activeCommitments.length; i++) {
          const commitment = activeCommitments[i]!;
          const isSelected = isActive && i === this.selectedIndex;
          this.renderCommitmentLine(container, commitment, isSelected, width);
        }
      }
    }
  }

  private renderCommitmentLine(container: Container, commitment: Commitment, isSelected: boolean, width: number): void {
    const prefix = isSelected ? ">" : " ";
    const icon = commitment.type === "promise" ? "💬" : "📩";
    const commitText = `${prefix} ${icon} "${truncateToWidth(commitment.text, width - 36)}"`;
    const actions = "[Create Task] [Dismiss]";

    const line = isSelected
      ? this.theme.fg("accent", this.theme.bold(commitText)) + " " + this.theme.fg("dim", actions)
      : this.theme.fg("text", commitText);

    container.addChild(new Text("│  " + line + " ".repeat(Math.max(0, width - 4 - this.getVisibleWidth(line))) + " │", 0, 0));
  }

  private renderEvidenceSection(container: Container, width: number): void {
    const isActive = this.currentSection === "evidence";
    const collapsed = this.sections.get("evidence") ?? false;
    const indicator = collapsed ? "▶" : "▼";
    const activeSuggestions = this.props.careerEvidenceSuggestions.filter((s) => !s.dismissed);

    const headerText = `${indicator} 🏆 Career Evidence`;
    const headerStyled = isActive
      ? this.theme.fg("accent", this.theme.bold(headerText))
      : this.theme.fg("text", headerText);

    container.addChild(new Text("│ " + truncateToWidth(headerStyled, width - 4) + " ".repeat(Math.max(0, width - 4 - this.getVisibleWidth(headerStyled))) + " │", 0, 0));

    if (!collapsed) {
      container.addChild(new Text("│ " + this.theme.fg("dim", "─".repeat(width - 4)) + " │", 0, 0));

      if (activeSuggestions.length === 0) {
        const emptyText = this.theme.fg("dim", "No evidence suggestions");
        container.addChild(new Text("│   " + emptyText + " ".repeat(Math.max(0, width - 6 - emptyText.length)) + " │", 0, 0));
      } else {
        for (let i = 0; i < activeSuggestions.length; i++) {
          const suggestion = activeSuggestions[i]!;
          const isSelected = isActive && i === this.selectedIndex;
          this.renderEvidenceLine(container, suggestion, isSelected, width);
        }
      }
    }
  }

  private renderEvidenceLine(container: Container, suggestion: EvidenceSuggestion, isSelected: boolean, width: number): void {
    const prefix = isSelected ? ">" : " ";
    const evidenceText = `${prefix} ${truncateToWidth(suggestion.achievement, width - 34)}`;
    const actions = "[Capture] [Skip]";

    const line = isSelected
      ? this.theme.fg("accent", this.theme.bold(evidenceText)) + " " + this.theme.fg("dim", actions)
      : this.theme.fg("text", evidenceText);

    container.addChild(new Text("│  " + line + " ".repeat(Math.max(0, width - 4 - this.getVisibleWidth(line))) + " │", 0, 0));
  }

  private moveSelection(delta: number): void {
    const maxIndex = this.getMaxIndexForSection(this.currentSection);
    this.selectedIndex = Math.max(0, Math.min(maxIndex, this.selectedIndex + delta));
    this.invalidate();
  }

  private moveToNextSection(): void {
    const sections: Section[] = ["completed", "open", "commitments", "evidence"];
    const currentIndex = sections.indexOf(this.currentSection);
    this.currentSection = sections[(currentIndex + 1) % sections.length]!;
    this.selectedIndex = 0;
    this.invalidate();
  }

  private moveToPrevSection(): void {
    const sections: Section[] = ["completed", "open", "commitments", "evidence"];
    const currentIndex = sections.indexOf(this.currentSection);
    this.currentSection = sections[(currentIndex - 1 + sections.length) % sections.length]!;
    this.selectedIndex = 0;
    this.invalidate();
  }

  private toggleSection(): void {
    const current = this.sections.get(this.currentSection) ?? false;
    this.sections.set(this.currentSection, !current);
    this.invalidate();
  }

  private async executeAction(): Promise<void> {
    switch (this.currentSection) {
      case "open":
        await this.completeOpenTask();
        break;
      case "commitments":
        await this.createCommitmentTask();
        break;
      case "evidence":
        await this.captureEvidence();
        break;
    }
  }

  private async completeOpenTask(): Promise<void> {
    const task = this.props.openTasks[this.selectedIndex];
    if (task) {
      await this.props.onTaskComplete(task.id);
      this.invalidate();
    }
  }

  private async createCommitmentTask(): Promise<void> {
    const activeCommitments = this.props.commitments.filter((c) => !c.dismissed);
    const commitment = activeCommitments[this.selectedIndex];
    if (commitment) {
      await this.props.onCommitmentCreate(commitment);
      this.invalidate();
    }
  }

  private async captureEvidence(): Promise<void> {
    const activeSuggestions = this.props.careerEvidenceSuggestions.filter((s) => !s.dismissed);
    const suggestion = activeSuggestions[this.selectedIndex];
    if (suggestion) {
      await this.props.onEvidenceCapture(suggestion);
      this.invalidate();
    }
  }

  private handleDismiss(): void {
    switch (this.currentSection) {
      case "commitments":
        const activeCommitments = this.props.commitments.filter((c) => !c.dismissed);
        const commitment = activeCommitments[this.selectedIndex];
        if (commitment) {
          this.props.onCommitmentDismiss(commitment);
          this.invalidate();
        }
        break;
      case "evidence":
        const activeSuggestions = this.props.careerEvidenceSuggestions.filter((s) => !s.dismissed);
        const suggestion = activeSuggestions[this.selectedIndex];
        if (suggestion) {
          this.props.onEvidenceDismiss(suggestion);
          this.invalidate();
        }
        break;
    }
  }

  private getMaxIndexForSection(section: Section): number {
    switch (section) {
      case "completed":
        return Math.max(0, this.props.completedTasks.length - 1);
      case "open":
        return Math.max(0, this.props.openTasks.length - 1);
      case "commitments":
        return Math.max(0, this.props.commitments.filter((c) => !c.dismissed).length - 1);
      case "evidence":
        return Math.max(0, this.props.careerEvidenceSuggestions.filter((s) => !s.dismissed).length - 1);
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
