/**
 * Task Board Component
 * 
 * Kanban-style task visualization in terminal.
 */

import { Container, Text, Spacer, truncateToWidth, matchesKey, Key } from "@mariozechner/pi-tui";
import type { Theme } from "@mariozechner/pi-coding-agent";

export interface Task {
  id: string; // task ID (e.g., "^task-001")
  title: string;
  priority: "P0" | "P1" | "P2";
  status: "todo" | "in-progress" | "done";
}

export interface TaskColumn {
  id: string;
  title: string;
  filter: (task: Task) => boolean;
}

export interface TaskBoardCallbacks {
  onTaskMove?: (taskId: string, toColumn: string) => Promise<void>;
  onTaskComplete?: (taskId: string) => Promise<void>;
  onTaskAdd?: () => Promise<void>;
  onClose?: () => void;
}

/**
 * Task Board Component
 * 
 * Interactive kanban board for tasks.
 */
export class TaskBoard {
  private tasks: Task[];
  private columns: TaskColumn[];
  private callbacks: TaskBoardCallbacks;
  private theme: Theme;
  private selectedColumn: number = 0;
  private selectedCard: number = 0;
  private cachedWidth?: number;
  private cachedLines?: string[];

  constructor(
    tasks: Task[],
    columns: TaskColumn[],
    callbacks: TaskBoardCallbacks,
    theme: Theme
  ) {
    this.tasks = tasks;
    this.columns = columns;
    this.callbacks = callbacks;
    this.theme = theme;
  }

  /**
   * Handle keyboard input
   */
  handleInput(data: string): void {
    if (matchesKey(data, Key.left)) {
      this.moveColumnSelection(-1);
    } else if (matchesKey(data, Key.right)) {
      this.moveColumnSelection(1);
    } else if (matchesKey(data, Key.up)) {
      this.moveCardSelection(-1);
    } else if (matchesKey(data, Key.down)) {
      this.moveCardSelection(1);
    } else if (matchesKey(data, Key.enter)) {
      this.viewSelectedCard();
    } else if (matchesKey(data, "d")) {
      this.completeSelectedCard();
    } else if (matchesKey(data, "m")) {
      this.moveSelectedCard();
    } else if (matchesKey(data, "a")) {
      this.addTask();
    } else if (matchesKey(data, Key.escape)) {
      this.callbacks.onClose?.();
    }
  }

  /**
   * Render the task board
   */
  render(width: number): string[] {
    if (this.cachedLines && this.cachedWidth === width) {
      return this.cachedLines;
    }

    const lines: string[] = [];

    // Title
    const title = this.theme.fg("accent", this.theme.bold("Task Board"));
    lines.push("┌─ " + title + " " + "─".repeat(Math.max(0, width - 15)) + "┐");

    // Column headers
    const columnWidth = Math.floor((width - 2 - this.columns.length - 1) / this.columns.length);
    const headerLine = this.renderColumnHeaders(columnWidth);
    lines.push("│ " + headerLine + " ".repeat(Math.max(0, width - 4 - this.getVisibleWidth(headerLine))) + " │");

    // Separator
    const separatorLine = this.columns
      .map(() => "─".repeat(columnWidth))
      .join("┼");
    lines.push("│ " + separatorLine + " ".repeat(Math.max(0, width - 4 - separatorLine.length)) + " │");

    // Cards (get max height needed)
    const maxHeight = this.getMaxColumnHeight();
    for (let row = 0; row < maxHeight; row++) {
      const cardLine = this.renderCardRow(row, columnWidth);
      lines.push("│ " + cardLine + " ".repeat(Math.max(0, width - 4 - this.getVisibleWidth(cardLine))) + " │");
    }

    // Actions
    lines.push("│" + " ".repeat(width - 2) + "│");
    const actions = "[Add Task (a)] [Move (m)] [Done (d)] [Filter] [Sort]";
    lines.push("│ " + this.theme.fg("dim", truncateToWidth(actions, width - 4)) + " ".repeat(Math.max(0, width - 4 - actions.length)) + " │");

    // Bottom border
    lines.push("└" + "─".repeat(width - 2) + "┘");

    this.cachedWidth = width;
    this.cachedLines = lines;
    return lines;
  }

  private renderColumnHeaders(columnWidth: number): string {
    return this.columns
      .map((col, i) => {
        const tasksInColumn = this.getTasksForColumn(col);
        const header = `${col.title} (${tasksInColumn.length})`;
        const isSelected = i === this.selectedColumn;
        const styled = isSelected
          ? this.theme.fg("accent", this.theme.bold(header))
          : this.theme.fg("text", header);
        return truncateToWidth(styled, columnWidth).padEnd(columnWidth + (styled.length - this.getVisibleWidth(styled)));
      })
      .join("│");
  }

  private renderCardRow(row: number, columnWidth: number): string {
    return this.columns
      .map((col, colIndex) => {
        const tasks = this.getTasksForColumn(col);
        const task = tasks[row];

        if (!task) {
          return " ".repeat(columnWidth);
        }

        const isSelected = colIndex === this.selectedColumn && row === this.selectedCard;
        return this.renderCard(task, columnWidth, isSelected);
      })
      .join("│");
  }

  private renderCard(task: Task, width: number, isSelected: boolean): string {
    const prefix = isSelected ? "> " : "  ";
    const title = truncateToWidth(task.title, width - 4);
    const id = task.id.length > 12 ? task.id.substring(0, 12) + "..." : task.id;

    const cardText = `${prefix}${title}`;
    const idText = `${id}`;

    if (isSelected) {
      return this.theme.fg("accent", this.theme.bold(truncateToWidth(cardText, width))).padEnd(width + (cardText.length - this.getVisibleWidth(cardText)));
    } else {
      return this.theme.fg("text", truncateToWidth(cardText, width)).padEnd(width);
    }
  }

  private getTasksForColumn(column: TaskColumn): Task[] {
    return this.tasks.filter(column.filter);
  }

  private getMaxColumnHeight(): number {
    return Math.max(...this.columns.map((col) => this.getTasksForColumn(col).length), 1);
  }

  private moveColumnSelection(delta: number): void {
    this.selectedColumn = Math.max(0, Math.min(this.columns.length - 1, this.selectedColumn + delta));
    this.selectedCard = 0; // Reset card selection
    this.invalidate();
  }

  private moveCardSelection(delta: number): void {
    const currentColumn = this.columns[this.selectedColumn];
    if (!currentColumn) return;

    const tasks = this.getTasksForColumn(currentColumn);
    if (tasks.length === 0) return;

    this.selectedCard = Math.max(0, Math.min(tasks.length - 1, this.selectedCard + delta));
    this.invalidate();
  }

  private viewSelectedCard(): void {
    const currentColumn = this.columns[this.selectedColumn];
    if (!currentColumn) return;

    const tasks = this.getTasksForColumn(currentColumn);
    const task = tasks[this.selectedCard];
    if (task) {
      // TODO: Show task details in overlay
      console.log("View task:", task.id);
    }
  }

  private async completeSelectedCard(): Promise<void> {
    const currentColumn = this.columns[this.selectedColumn];
    if (!currentColumn) return;

    const tasks = this.getTasksForColumn(currentColumn);
    const task = tasks[this.selectedCard];
    if (task && this.callbacks.onTaskComplete) {
      await this.callbacks.onTaskComplete(task.id);
      this.invalidate();
    }
  }

  private async moveSelectedCard(): Promise<void> {
    const currentColumn = this.columns[this.selectedColumn];
    if (!currentColumn) return;

    const tasks = this.getTasksForColumn(currentColumn);
    const task = tasks[this.selectedCard];
    if (task && this.callbacks.onTaskMove) {
      // For now, just move to next column
      const nextColumnIndex = (this.selectedColumn + 1) % this.columns.length;
      const nextColumn = this.columns[nextColumnIndex];
      if (nextColumn) {
        await this.callbacks.onTaskMove(task.id, nextColumn.id);
        this.invalidate();
      }
    }
  }

  private async addTask(): Promise<void> {
    if (this.callbacks.onTaskAdd) {
      await this.callbacks.onTaskAdd();
      this.invalidate();
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
