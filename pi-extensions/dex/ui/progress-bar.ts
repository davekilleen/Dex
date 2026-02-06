/**
 * Progress Bar Helper
 * 
 * Renders horizontal progress bars with theme support.
 */

export interface ProgressBarTheme {
  filled: (s: string) => string;
  empty: (s: string) => string;
}

/**
 * Render a progress bar
 * 
 * @param progress - Percentage (0-100)
 * @param width - Total width in characters
 * @param theme - Theme functions for filled/empty states
 * @returns Styled progress bar string
 */
export function renderProgressBar(
  progress: number,
  width: number,
  theme: ProgressBarTheme
): string {
  const clampedProgress = Math.max(0, Math.min(100, progress));
  const filled = Math.round((clampedProgress / 100) * width);
  const empty = width - filled;
  
  return theme.filled("█".repeat(filled)) + theme.empty("░".repeat(empty));
}

/**
 * Render a compact progress bar with percentage
 * 
 * @param progress - Percentage (0-100)
 * @param width - Total width for bar (excluding percentage text)
 * @param theme - Theme functions
 * @returns "[███░░] 60%"
 */
export function renderProgressBarWithPercentage(
  progress: number,
  width: number,
  theme: ProgressBarTheme
): string {
  const bar = renderProgressBar(progress, width, theme);
  const pct = Math.round(progress);
  return `[${bar}] ${pct}%`;
}
