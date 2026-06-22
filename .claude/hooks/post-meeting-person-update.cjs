#!/usr/bin/env node
/**
 * Post-meeting person page updater
 * Fires after Write during /process-meetings
 * Extracts person mentions from meeting notes and updates their person pages
 */
const fs = require('fs');
const path = require('path');

// Read the hook context
const input = JSON.parse(process.env.CLAUDE_HOOK_CONTEXT || '{}');
const filePath = input?.tool_input?.file_path || input?.toolInput?.file_path || '';

// Only act on meeting note files
if (!filePath.includes('Meeting_Intel') && !filePath.includes('Meetings/') && !filePath.includes('Meeting_Notes')) {
  process.exit(0);
}

// Verify the file exists
if (!fs.existsSync(filePath)) {
  process.exit(0);
}

const content = fs.readFileSync(filePath, 'utf-8');
const today = new Date().toISOString().split('T')[0];
const meetingName = path.basename(filePath, '.md');

// Extract WikiLink mentions [[Firstname_Lastname]]
const wikiLinkPattern = /\[\[([A-Z][a-z]+_[A-Z][a-z]+[A-Za-z_]*)\]\]/g;
const mentions = new Set();
let match;
while ((match = wikiLinkPattern.exec(content)) !== null) {
  mentions.add(match[1]);
}

// Also try plain name patterns "Firstname Lastname" near key sections
const plainNamePattern = /(?:with|attendee|participant|spoke to|met with)\s+([A-Z][a-z]+\s[A-Z][a-z]+)/gi;
while ((match = plainNamePattern.exec(content)) !== null) {
  mentions.add(match[1].replace(/\s/g, '_'));
}

if (mentions.size === 0) {
  process.exit(0);
}

// Check for person pages and append meeting reference
const peopleDir = path.resolve(path.dirname(filePath), '../../05-Areas/People');
// Also try from vault root
const vaultRoot = process.env.CLAUDE_PROJECT_DIR || path.resolve(path.dirname(filePath), '../..');
const peopleDirAlt = path.join(vaultRoot, 'People');
const actualPeopleDir = fs.existsSync(peopleDir) ? peopleDir : peopleDirAlt;

const updated = [];
for (const name of mentions) {
  const possiblePaths = [
    path.join(actualPeopleDir, 'Internal', `${name}.md`),
    path.join(actualPeopleDir, 'External', `${name}.md`)
  ];

  for (const pp of possiblePaths) {
    if (fs.existsSync(pp)) {
      const existingContent = fs.readFileSync(pp, 'utf-8');
      // Don't add duplicate references
      if (!existingContent.includes(meetingName)) {
        const meetingRef = `\n- [[${meetingName}]] (${today})\n`;

        // Try to append under "## Recent Meetings" or "## Meetings" section
        if (existingContent.includes('## Recent Meetings') || existingContent.includes('## Meetings')) {
          const sectionPattern = /## (?:Recent )?Meetings\n/;
          const updatedContent = existingContent.replace(sectionPattern, (match) => {
            return match + `- [[${meetingName}]] (${today})\n`;
          });
          fs.writeFileSync(pp, updatedContent);
        } else {
          // Append at end
          fs.appendFileSync(pp, meetingRef);
        }
        updated.push(name);
      }
      break;
    }
  }
}

if (updated.length > 0) {
  console.log(`Updated ${updated.length} person page(s): ${updated.join(', ')}`);
}
