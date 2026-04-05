#!/usr/bin/env node
/**
 * PreToolUse hook: Inject company/account context when reading files with relationship references.
 * Injects key contacts, recent meetings, open tasks, and status.
 */
const fs = require('fs');
const path = require('path');
const { skip, parseAndValidate, buildIndex, findReferences, outputContext } = require('./lib/context-base.cjs');

const { content, paths, vaultRoot } = parseAndValidate({
  recursionMarkers: ['/05-Areas/Companies/', '/05-Areas/Accounts/']
});

const COMPANIES_DIR = paths.COMPANIES_DIR || path.join(vaultRoot, '05-Areas', 'Companies');
const ACCOUNTS_DIR = path.join(paths.AREAS_DIR || path.join(vaultRoot, '05-Areas'), 'Accounts');

const companyIndex = buildIndex([COMPANIES_DIR, ACCOUNTS_DIR], { recursive: true });

if (Object.keys(companyIndex).length === 0) skip('no-company-pages-indexed');

const found = findReferences(content, companyIndex, {
  fileRefPattern: /05-Areas\/(?:Companies|Accounts)\/[^\s]*?([A-Za-z0-9_-]+)(?:\.md)?/g,
  contextKeywords: ['meeting', 'call', 'demo', 'account', 'deal', 'opportunity'],
  minNameLength: 3
});

if (found.size === 0) skip('no-company-references-found');

const bodyLines = [];
for (const companyFilePath of found) {
  const info = parseCompanyPage(companyFilePath);
  if (!info) continue;
  bodyLines.push(`${info.name}${info.status ? ` - ${info.status}` : ''}`);
  if (info.contacts.length > 0) bodyLines.push(`  Key contacts: ${info.contacts.slice(0, 3).join(', ')}`);
  if (info.lastMeeting) bodyLines.push(`  Last meeting: ${info.lastMeeting}`);
  if (info.openTasks.length > 0) {
    bodyLines.push(`  Open tasks: ${info.openTasks.length}`);
    info.openTasks.slice(0, 2).forEach(task => {
      bodyLines.push(`    - ${task.substring(0, 60)}${task.length > 60 ? '...' : ''}`);
    });
  }
  if (info.context) bodyLines.push(`  Context: ${info.context.substring(0, 100)}${info.context.length > 100 ? '...' : ''}`);
}

outputContext('company_context', 'Referenced companies:', bodyLines);

function parseCompanyPage(filePath) {
  try {
    const raw = fs.readFileSync(filePath, 'utf-8');
    const fileName = path.basename(filePath, '.md');
    const info = { name: fileName.replace(/_/g, ' ').replace(/-/g, ' '), status: null, contacts: [], lastMeeting: null, openTasks: [], context: null };

    if (raw.startsWith('---')) {
      const endIdx = raw.slice(3).indexOf('---');
      if (endIdx !== -1) {
        const fm = raw.slice(3, endIdx + 3);
        const get = (key) => { const m = fm.match(new RegExp(`${key}:\\s*(.+)`)); return m ? m[1].trim() : null; };
        info.status = get('status');
        const nameVal = get('name');
        if (nameVal) info.name = nameVal;

        const contactsMatch = fm.match(/contacts:\s*\n((?:\s*-\s*.+\n)+)/);
        if (contactsMatch) {
          const lines = contactsMatch[1].match(/-\s*(.+)/g);
          if (lines) info.contacts = lines.map(l => l.replace(/^-\s*/, '').trim());
        }
      }
    }

    let match;
    const re = /^- \[ \] (.+)$/gm;
    while ((match = re.exec(raw)) !== null) {
      info.openTasks.push(match[1].replace(/\*\*/g, '').trim());
    }

    const meetingMatch = raw.match(/(?:last meeting|met on|call on)[:\s]+(\d{4}-\d{2}-\d{2}|\w+ \d{1,2},? \d{4})/i);
    if (meetingMatch) info.lastMeeting = meetingMatch[1];

    const body = raw.replace(/^---[\s\S]*?---/, '').trim();
    const firstP = body.split('\n\n')[0];
    if (firstP && !firstP.startsWith('#') && !firstP.startsWith('-')) info.context = firstP.trim();

    if (info.contacts.length === 0) {
      const section = raw.match(/##\s*(?:Key\s+)?Contacts[\s\S]*?(?=##|$)/i);
      if (section) {
        const matches = section[0].match(/[-*]\s*\*?\*?([^*\n]+)\*?\*?/g);
        if (matches) {
          info.contacts = matches.slice(0, 5).map(c => c.replace(/^[-*]\s*\*?\*?/, '').replace(/\*?\*?$/, '').trim()).filter(c => c.length > 0);
        }
      }
    }

    return info;
  } catch (e) { return null; }
}
