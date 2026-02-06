/**
 * Collapsible Section Component
 * 
 * A section with a title that can be expanded or collapsed.
 */

import { Container, truncateToWidth } from "@mariozechner/pi-tui";
import type { Theme } from "@mariozechner/pi-coding-agent";

/**
 * Collapsible Section
 * 
 * Shows/hides content with a clickable header.
 */
export class CollapsibleSection {
  private title: string;
  private content: Container;
  private theme: Theme;
  private collapsed: boolean;
  private cachedWidth?: number;
  private cachedLines?: string[];

  constructor(title: string, content: Container, theme: Theme, startCollapsed = false) {
    this.title = title;
    this.content = content;
    this.theme = theme;
    this.collapsed = startCollapsed;
  }

  /**
   * Toggle collapsed state
   */
  toggle(): void {
    this.collapsed = !this.collapsed;
    this.invalidate();
  }

  /**
   * Check if section is collapsed
   */
  isCollapsed(): boolean {
    return this.collapsed;
  }

  /**
   * Set collapsed state
   */
  setCollapsed(collapsed: boolean): void {
    if (this.collapsed !== collapsed) {
      this.collapsed = collapsed;
      this.invalidate();
    }
  }

  /**
   * Render the section
   */
  render(width: number): string[] {
    if (this.cachedLines && this.cachedWidth === width) {
      return this.cachedLines;
    }

    const lines: string[] = [];

    // Header line with expand/collapse indicator
    const indicator = this.collapsed ? "▶" : "▼";
    const header = `${indicator} ${this.title}`;
    const headerStyled = this.theme.fg("accent", this.theme.bold(header));
    lines.push(truncateToWidth(headerStyled, width));

    // Content (if expanded)
    if (!this.collapsed) {
      const contentLines = this.content.render(width - 2);
      // Indent content
      lines.push(...contentLines.map((line) => "  " + line));
    }

    this.cachedWidth = width;
    this.cachedLines = lines;
    return lines;
  }

  /**
   * Update the content
   */
  updateContent(content: Container): void {
    this.content = content;
    this.invalidate();
  }

  invalidate(): void {
    this.cachedWidth = undefined;
    this.cachedLines = undefined;
    this.content.invalidate();
  }
}
