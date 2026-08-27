#!/usr/bin/env node
/**
 * Daily Plan Quick Reference Generator
 * Fires on Stop after /daily-plan completes
 * Creates a condensed <50 line quickref from the full daily plan
 */
const fs = require('fs');
const path = require('path');
const { loadPaths } = require('./paths.cjs');

const paths = loadPaths();
const planDir = paths.DAILY_PLANS_DIR;
if (!planDir) {
  process.exit(0);
}

const today = new Date().toISOString().split('T')[0];
const planPath = path.join(planDir, `${today}.md`);
const quickRefPath = path.join(planDir, `${today}-quickref.md`);

// Only run if today's plan exists
if (!fs.existsSync(planPath)) {
  process.exit(0);
}

const content = fs.readFileSync(planPath, 'utf-8');
const lines = content.split('\n');

// Extract key sections
let focusItems = [];
let timeBlocks = [];
let keyMeetings = [];
let currentSection = '';

for (const line of lines) {
  // Detect sections
  if (line.match(/^#{1,3}\s.*focus/i) || line.match(/^#{1,3}\s.*priorities/i) || line.match(/^#{1,3}\s.*top\s/i)) {
    currentSection = 'focus';
    continue;
  }
  if (line.match(/^#{1,3}\s.*schedule/i) || line.match(/^#{1,3}\s.*time.?block/i) || line.match(/^#{1,3}\s.*calendar/i)) {
    currentSection = 'schedule';
    continue;
  }
  if (line.match(/^#{1,3}\s.*meeting/i)) {
    currentSection = 'meetings';
    continue;
  }
  if (line.match(/^#{1,3}\s/)) {
    currentSection = 'other';
    continue;
  }

  // Collect items
  const trimmed = line.trim();
  if (!trimmed || trimmed === '---') continue;

  if (currentSection === 'focus' && (trimmed.startsWith('-') || trimmed.startsWith('*') || trimmed.match(/^\d+\./))) {
    if (focusItems.length < 5) focusItems.push(trimmed);
  }
  if (currentSection === 'schedule' && trimmed.length > 0) {
    if (timeBlocks.length < 10) timeBlocks.push(trimmed);
  }
  if (currentSection === 'meetings' && (trimmed.startsWith('-') || trimmed.startsWith('*') || trimmed.match(/^\d+\./))) {
    if (keyMeetings.length < 5) keyMeetings.push(trimmed);
  }
}

// Build quickref
const quickRef = [
  `# Quick Ref — ${today}`,
  '',
  '## Top Focus',
  ...(focusItems.length > 0 ? focusItems : ['- Check full plan for details']),
  '',
  '## Key Meetings',
  ...(keyMeetings.length > 0 ? keyMeetings : ['- No meetings extracted']),
  '',
  '## Time Blocks',
  ...(timeBlocks.length > 0 ? timeBlocks : ['- See full plan']),
  '',
  `---`,
  `*Full plan: [[${today}]]*`
].join('\n');

fs.writeFileSync(quickRefPath, quickRef);
console.log(`Quick ref generated: ${quickRefPath}`);
