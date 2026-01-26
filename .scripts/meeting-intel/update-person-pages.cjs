#!/usr/bin/env node

/**
 * Update Person Pages - Auto-update person pages from meeting notes
 * 
 * Scans meeting notes in Inbox/Meetings/ and updates corresponding
 * person pages in People/ with:
 * - Recent Mentions (meeting links)
 * - Action items assigned to them
 * - Last Interaction date
 * 
 * Usage:
 *   node .scripts/meeting-intel/update-person-pages.cjs           # Today
 *   node .scripts/meeting-intel/update-person-pages.cjs 2026-01-17  # Specific date
 *   node .scripts/meeting-intel/update-person-pages.cjs --all       # All processed
 */

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');

// ============================================================================
// CONFIGURATION
// ============================================================================

const VAULT_ROOT = path.resolve(__dirname, '../..');
const MEETINGS_DIR = path.join(VAULT_ROOT, 'Inbox', 'Meetings');
const PEOPLE_DIR = path.join(VAULT_ROOT, 'People');
const PROFILE_FILE = path.join(VAULT_ROOT, 'System', 'user-profile.yaml');

// ============================================================================
// HELPERS
// ============================================================================

function log(message) {
  const timestamp = new Date().toISOString();
  console.log(`[${timestamp}] ${message}`);
}

function getToday() {
  return new Date().toISOString().split('T')[0];
}

function slugify(name) {
  return name
    .trim()
    .replace(/[^a-zA-Z0-9\s]/g, '')
    .replace(/\s+/g, '_');
}

function loadUserProfile() {
  const defaults = {
    name: 'User',
    role: 'Professional',
    company: ''
  };
  
  if (!fs.existsSync(PROFILE_FILE)) {
    return defaults;
  }
  
  try {
    const profile = yaml.load(fs.readFileSync(PROFILE_FILE, 'utf-8'));
    return { ...defaults, ...profile };
  } catch (e) {
    return defaults;
  }
}

function getOwnerNames(profile) {
  const names = [profile.name];
  
  // Add variations: first name, lowercase versions
  if (profile.name && profile.name.includes(' ')) {
    const firstName = profile.name.split(' ')[0];
    names.push(firstName);
  }
  
  return names.map(n => n.toLowerCase());
}

function findPersonPage(name) {
  const slug = slugify(name);
  const folders = ['Internal', 'External'];
  
  for (const folder of folders) {
    const folderPath = path.join(PEOPLE_DIR, folder);
    if (!fs.existsSync(folderPath)) continue;
    
    const files = fs.readdirSync(folderPath);
    for (const file of files) {
      if (file.endsWith('.md')) {
        const baseName = file.replace('.md', '');
        // Check exact match or close match
        if (baseName.toLowerCase() === slug.toLowerCase() ||
            baseName.toLowerCase().includes(slug.toLowerCase()) ||
            slug.toLowerCase().includes(baseName.toLowerCase())) {
          return path.join(folderPath, file);
        }
      }
    }
  }
  
  return null;
}

function createPersonPage(name, meetingPath, meetingTitle, actionItems) {
  const slug = slugify(name);
  const today = getToday();
  const pagePath = path.join(PEOPLE_DIR, 'External', `${slug}.md`);
  
  // Ensure External folder exists
  const externalDir = path.join(PEOPLE_DIR, 'External');
  if (!fs.existsSync(externalDir)) {
    fs.mkdirSync(externalDir, { recursive: true });
  }
  
  const content = `---
name: "${name}"
company: ""
role: ""
created: ${today}
last_interaction: ${today}
tags: [person, auto-created]
---

# ${name}

## Overview

| Field | Value |
|-------|-------|
| **Role** |  |
| **Company** |  |
| **Email** |  |
| **LinkedIn** |  |

---

## Context

<!-- Add how you met, relationship context -->

---

## Key Topics

<!-- Recurring themes in conversations -->

---

## Recent Mentions

- ${meetingPath} — ${today}

---

## Action Items

${actionItems.length > 0 ? actionItems.map(a => `- [ ] ${a}`).join('\n') : '<!-- Action items involving this person -->'}

---

## Meeting History

- ${meetingPath} — ${today}

---
*Auto-created from meeting note*
`;

  fs.writeFileSync(pagePath, content);
  return pagePath;
}

function updatePersonPage(pagePath, meetingPath, meetingTitle, actionItems) {
  let content = fs.readFileSync(pagePath, 'utf-8');
  const today = getToday();
  const meetingLink = meetingPath;
  
  // Check if meeting already added
  if (content.includes(meetingPath)) {
    return false; // Already updated
  }
  
  // Update last_interaction in frontmatter
  content = content.replace(
    /last_interaction:\s*\d{4}-\d{2}-\d{2}/,
    `last_interaction: ${today}`
  );
  
  // Add to Recent Mentions section
  const recentMentionsRegex = /(## Recent Mentions\n\n)([\s\S]*?)(\n\n## |\n---)/;
  const recentMatch = content.match(recentMentionsRegex);
  if (recentMatch) {
    const existingMentions = recentMatch[2].trim();
    const newMention = `- ${meetingLink} — ${today}`;
    
    // Keep max 20 mentions
    const mentions = existingMentions.split('\n').filter(m => m.startsWith('- '));
    mentions.unshift(newMention);
    const trimmedMentions = mentions.slice(0, 20);
    
    content = content.replace(
      recentMentionsRegex,
      `$1${trimmedMentions.join('\n')}\n$3`
    );
  }
  
  // Add action items if any
  if (actionItems.length > 0) {
    const actionRegex = /(## Action Items\n\n)([\s\S]*?)(\n\n## |\n---)/;
    const actionMatch = content.match(actionRegex);
    if (actionMatch) {
      const existingActions = actionMatch[2].trim();
      const newActions = actionItems.map(a => `- [ ] ${a} — ${meetingLink}`).join('\n');
      
      let updatedActions = existingActions;
      if (existingActions.includes('<!-- Action items')) {
        updatedActions = newActions;
      } else {
        updatedActions = newActions + '\n' + existingActions;
      }
      
      content = content.replace(
        actionRegex,
        `$1${updatedActions}\n$3`
      );
    }
  }
  
  // Add to Meeting History section
  const historyRegex = /(## Meeting History\n\n)([\s\S]*?)(\n---|\n\n## |$)/;
  const historyMatch = content.match(historyRegex);
  if (historyMatch) {
    const existingHistory = historyMatch[2].trim();
    const newEntry = `- ${meetingLink} — ${today}`;
    
    let updatedHistory = existingHistory;
    if (existingHistory.includes('<!-- ') || existingHistory === '') {
      updatedHistory = newEntry;
    } else {
      updatedHistory = newEntry + '\n' + existingHistory;
    }
    
    content = content.replace(
      historyRegex,
      `$1${updatedHistory}\n$3`
    );
  }
  
  fs.writeFileSync(pagePath, content);
  return true;
}

function extractParticipants(content, ownerNames) {
  const participants = [];
  
  // Look for participants in frontmatter
  const frontmatterMatch = content.match(/participants:\s*\[([^\]]+)\]/);
  if (frontmatterMatch) {
    const names = frontmatterMatch[1].split(',').map(n => n.trim().replace(/["']/g, ''));
    participants.push(...names);
  }
  
  // Look for **Participants:** line
  const participantsLine = content.match(/\*\*Participants:\*\*\s*([^\n]+)/);
  if (participantsLine) {
    const names = participantsLine[1]
      .split(/,|and/)
      .map(n => n.trim())
      .filter(n => n && !n.includes('People/'));
    participants.push(...names);
  }
  
  // Filter out owner names
  const filtered = participants.filter(p => {
    const pLower = p.toLowerCase();
    return !ownerNames.some(owner => 
      pLower === owner || 
      pLower.includes(owner) ||
      owner.includes(pLower)
    );
  });
  
  // Deduplicate
  return [...new Set(filtered)].filter(p => p.length > 2);
}

function extractActionItemsForPerson(content, personName) {
  const actionItems = [];
  
  // Look for action items mentioning this person
  const forOthersMatch = content.match(/### For Others\n\n([\s\S]*?)(?=\n## |$)/i);
  if (forOthersMatch) {
    const lines = forOthersMatch[1].split('\n');
    for (const line of lines) {
      if (line.includes(personName) || 
          line.toLowerCase().includes(personName.toLowerCase()) ||
          line.includes(`@${personName}`)) {
        const action = line.replace(/^[-*]\s*\[[ x]\]\s*/, '').replace(/@\S+:?\s*/, '').trim();
        if (action.length > 5) {
          actionItems.push(action);
        }
      }
    }
  }
  
  return actionItems;
}

function readMeetingNotes(date) {
  const dayDir = path.join(MEETINGS_DIR, date);
  
  if (!fs.existsSync(dayDir)) {
    return [];
  }
  
  const files = fs.readdirSync(dayDir).filter(f => f.endsWith('.md'));
  const notes = [];
  const profile = loadUserProfile();
  const ownerNames = getOwnerNames(profile);
  
  for (const file of files) {
    const content = fs.readFileSync(path.join(dayDir, file), 'utf-8');
    const title = file.replace('.md', '').replace(/-/g, ' ');
    
    notes.push({
      file,
      path: `Inbox/Meetings/${date}/${file.replace('.md', '')}.md`,
      title,
      content,
      participants: extractParticipants(content, ownerNames)
    });
  }
  
  return notes;
}

function getAllProcessedDates() {
  if (!fs.existsSync(MEETINGS_DIR)) return [];
  
  return fs.readdirSync(MEETINGS_DIR)
    .filter(f => /^\d{4}-\d{2}-\d{2}$/.test(f))
    .filter(f => fs.statSync(path.join(MEETINGS_DIR, f)).isDirectory())
    .sort()
    .reverse();
}

// ============================================================================
// MAIN
// ============================================================================

async function main() {
  const args = process.argv.slice(2);
  const processAll = args.includes('--all');
  const dateArg = args.find(a => /^\d{4}-\d{2}-\d{2}$/.test(a));
  
  let datesToProcess = [];
  
  if (processAll) {
    datesToProcess = getAllProcessedDates();
    log(`Processing all dates: ${datesToProcess.length} found`);
  } else {
    const date = dateArg || getToday();
    datesToProcess = [date];
    log(`Processing date: ${date}`);
  }
  
  let totalUpdates = 0;
  let totalCreates = 0;
  
  for (const date of datesToProcess) {
    const notes = readMeetingNotes(date);
    
    if (notes.length === 0) {
      log(`No meeting notes found for ${date}`);
      continue;
    }
    
    log(`Found ${notes.length} meeting notes for ${date}`);
    
    for (const note of notes) {
      log(`  Processing: ${note.title}`);
      log(`    Participants: ${note.participants.join(', ') || 'none found'}`);
      
      for (const participant of note.participants) {
        const actionItems = extractActionItemsForPerson(note.content, participant);
        const existingPage = findPersonPage(participant);
        
        if (existingPage) {
          const updated = updatePersonPage(existingPage, note.path, note.title, actionItems);
          if (updated) {
            log(`    ✓ Updated: ${participant}`);
            totalUpdates++;
          } else {
            log(`    - Skipped (already linked): ${participant}`);
          }
        } else {
          const newPage = createPersonPage(participant, note.path, note.title, actionItems);
          log(`    + Created: ${participant} → ${path.relative(VAULT_ROOT, newPage)}`);
          totalCreates++;
        }
      }
    }
  }
  
  // Summary
  console.log('\n' + '='.repeat(60));
  console.log('PERSON PAGE UPDATE SUMMARY');
  console.log('='.repeat(60));
  console.log(`Dates processed: ${datesToProcess.length}`);
  console.log(`Pages updated: ${totalUpdates}`);
  console.log(`Pages created: ${totalCreates}`);
  console.log('='.repeat(60) + '\n');
}

main().catch(err => {
  log(`FATAL: ${err.message}`);
  console.error(err);
  process.exit(1);
});
