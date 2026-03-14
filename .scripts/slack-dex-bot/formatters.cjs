#!/usr/bin/env node

/**
 * Slack Block Kit formatters for Dex conversational interface.
 * All formatters return { blocks: [...], text: string } where text is the fallback.
 */

/**
 * Wrap a plain text response into Block Kit blocks.
 */
function wrapResponse(text, headerEmoji, headerText) {
  const blocks = [];

  if (headerText) {
    blocks.push({
      type: 'header',
      text: { type: 'plain_text', text: `${headerEmoji || ''} ${headerText}`.trim(), emoji: true }
    });
  }

  // Split long text into section blocks (Slack max 3000 chars per block)
  const chunks = splitText(text, 2800);
  for (const chunk of chunks) {
    blocks.push({
      type: 'section',
      text: { type: 'mrkdwn', text: chunk }
    });
  }

  return { blocks, text: stripMrkdwn(text) };
}

/**
 * Format day overview (calendar + priorities + tasks).
 */
function formatDayOverview(llmResponse) {
  return wrapResponse(llmResponse, '\ud83d\udccb', 'Your Day');
}

/**
 * Format calendar query results.
 */
function formatCalendarView(llmResponse) {
  return wrapResponse(llmResponse, '\ud83d\udcc5', 'Calendar');
}

/**
 * Format person lookup results.
 */
function formatPersonBrief(llmResponse) {
  return wrapResponse(llmResponse, '\ud83d\udc64', 'Person Brief');
}

/**
 * Format meeting prep results.
 */
function formatMeetingPrep(llmResponse) {
  return wrapResponse(llmResponse, '\ud83c\udfaf', 'Meeting Prep');
}

/**
 * Format vault search results.
 */
function formatSearchResults(llmResponse) {
  return wrapResponse(llmResponse, '\ud83d\udd0d', 'Search Results');
}

/**
 * Format unknown intent response.
 */
function formatUnknown(llmResponse) {
  return wrapResponse(llmResponse, null, null);
}

/**
 * Format error message.
 */
function formatError(message) {
  return {
    blocks: [{
      type: 'section',
      text: { type: 'mrkdwn', text: `Something went wrong: ${message}\n\nTry again or check Dex in Claude Code.` }
    }],
    text: `Error: ${message}`
  };
}

/**
 * Format "thinking" indicator.
 */
function formatThinking() {
  return {
    blocks: [{
      type: 'context',
      elements: [{ type: 'mrkdwn', text: ':hourglass_flowing_sand: Thinking...' }]
    }],
    text: 'Thinking...'
  };
}

// --- Helpers ---

function splitText(text, maxLen) {
  if (text.length <= maxLen) return [text];
  const chunks = [];
  let remaining = text;
  while (remaining.length > 0) {
    if (remaining.length <= maxLen) {
      chunks.push(remaining);
      break;
    }
    // Split at last newline within limit
    let splitIdx = remaining.lastIndexOf('\n', maxLen);
    if (splitIdx < maxLen * 0.5) splitIdx = maxLen; // No good split point
    chunks.push(remaining.slice(0, splitIdx));
    remaining = remaining.slice(splitIdx).trimStart();
  }
  return chunks;
}

function stripMrkdwn(text) {
  return text.replace(/\*/g, '').replace(/`/g, '').replace(/~/g, '').slice(0, 500);
}

module.exports = {
  wrapResponse,
  formatDayOverview,
  formatCalendarView,
  formatPersonBrief,
  formatMeetingPrep,
  formatSearchResults,
  formatUnknown,
  formatError,
  formatThinking
};
