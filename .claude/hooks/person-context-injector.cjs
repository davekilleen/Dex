#!/usr/bin/env node
/**
 * PreToolUse hook: Inject person context when reading files with People/ references.
 * Injects role, company, last interaction, and open action items.
 */
const fs = require('fs');
const path = require('path');
const { skip, parseAndValidate, buildIndex, findReferences, outputContext } = require('./lib/context-base.cjs');

const { content, paths, vaultRoot } = parseAndValidate({
  recursionMarkers: ['/People/']
});

const PEOPLE_DIR = paths.PEOPLE_DIR || path.join(vaultRoot, '05-Areas', 'People');
const personIndex = buildIndex(
  ['Internal', 'External', 'CPO_Network'].map(d => path.join(PEOPLE_DIR, d))
);

if (Object.keys(personIndex).length === 0) skip('no-person-pages-indexed');

const found = findReferences(content, personIndex, {
  fileRefPattern: /People\/(?:Internal|External|CPO_Network)\/([A-Za-z0-9_-]+)(?:\.md)?/g,
  contextKeywords: ['meeting', 'attendee', 'call with', 'met with'],
  requireMultiWord: true
});

if (found.size === 0) skip('no-person-references-found');

const bodyLines = [];
for (const personFilePath of found) {
  const info = parsePersonPage(personFilePath);
  if (!info) continue;
  bodyLines.push(`${info.name} - ${info.role || 'No role'} @ ${info.company || 'Unknown'}`);
  if (info.lastInteraction) bodyLines.push(`  Last interaction: ${info.lastInteraction}`);
  if (info.openItems.length > 0) {
    bodyLines.push(`  Open items: ${info.openItems.length}`);
    info.openItems.slice(0, 2).forEach(item => {
      bodyLines.push(`    - ${item.substring(0, 60)}${item.length > 60 ? '...' : ''}`);
    });
  }
}

outputContext('person_context', 'Referenced people:', bodyLines);

function parsePersonPage(filePath) {
  try {
    const raw = fs.readFileSync(filePath, 'utf-8');
    const fileName = path.basename(filePath, '.md');
    const info = { name: fileName.replace(/_/g, ' '), role: null, company: null, lastInteraction: null, openItems: [] };

    if (raw.startsWith('---')) {
      const endIdx = raw.slice(3).indexOf('---');
      if (endIdx !== -1) {
        const fm = raw.slice(3, endIdx + 3);
        const get = (key) => { const m = fm.match(new RegExp(`${key}:\\s*(.+)`)); return m ? m[1].trim() : null; };
        info.role = get('role');
        info.company = get('company');
        info.lastInteraction = get('last_interaction');
        const nameVal = get('name');
        if (nameVal) info.name = nameVal;
      }
    }

    let match;
    const re = /^- \[ \] (.+)$/gm;
    while ((match = re.exec(raw)) !== null) {
      info.openItems.push(match[1].replace(/\*\*/g, '').trim());
    }
    return info;
  } catch (e) { return null; }
}
