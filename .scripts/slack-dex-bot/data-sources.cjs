#!/usr/bin/env node

/**
 * Data sources for Dex Slack conversational interface.
 * Reads calendar, tasks, people, priorities, and vault content.
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');
const yaml = require('js-yaml');

const VAULT_ROOT = path.resolve(__dirname, '../..');

/**
 * Load user profile from System/user-profile.yaml
 */
function loadProfile() {
  try {
    const raw = fs.readFileSync(path.join(VAULT_ROOT, 'System', 'user-profile.yaml'), 'utf8');
    return yaml.load(raw) || {};
  } catch { return {}; }
}

/**
 * Load pillars from System/pillars.yaml
 */
function loadPillars() {
  try {
    const raw = fs.readFileSync(path.join(VAULT_ROOT, 'System', 'pillars.yaml'), 'utf8');
    return yaml.load(raw) || {};
  } catch { return {}; }
}

/**
 * Get today's calendar events via Office 365 or EventKit script.
 * Returns: [{ title, start, end, location, attendees?, all_day }]
 */
function getCalendarToday() {
  const profile = loadProfile();
  const backend = profile.calendar_backend || 'office365';
  const calName = (profile.calendar && profile.calendar.work_calendar) || 'Work';

  const scriptDir = path.join(VAULT_ROOT, 'core', 'mcp', 'scripts');
  const script = backend === 'office365' ? 'calendar_office365.py' : 'calendar_eventkit.py';
  const scriptPath = path.join(scriptDir, script);

  try {
    const result = execSync(
      `python3 "${scriptPath}" attendees "${calName}" 0 1`,
      {
        cwd: VAULT_ROOT,
        env: { ...process.env, VAULT_PATH: VAULT_ROOT },
        timeout: 15000,
        encoding: 'utf8'
      }
    );
    const events = JSON.parse(result);
    if (events.error) return { error: events.error, events: [] };
    return { events };
  } catch (e) {
    return { error: e.message, events: [] };
  }
}

/**
 * Get week priorities from 02-Week_Priorities/Week_Priorities.md
 * Returns: { weekOf, top3: [{title, pillar, detail}], commitments: [string], tasks: {P0:[], P1:[], P2:[]} }
 */
function getWeekPriorities() {
  const filePath = path.join(VAULT_ROOT, '02-Week_Priorities', 'Week_Priorities.md');
  try {
    const content = fs.readFileSync(filePath, 'utf8');
    const result = { weekOf: '', top3: [], commitments: [], tasks: { P0: [], P1: [], P2: [] } };

    // Week of
    const weekMatch = content.match(/\*\*Week of:\*\*\s*(.+)/);
    if (weekMatch) result.weekOf = weekMatch[1].trim();

    // Top 3
    const top3Section = content.match(/## .* Top 3 This Week\n([\s\S]*?)(?=\n---|\n## )/);
    if (top3Section) {
      const items = top3Section[1].matchAll(/\d+\.\s+\*\*(.+?)\*\*\s*[—\-]+\s*\*\*(.+?)\*\*/g);
      for (const m of items) {
        result.top3.push({ title: m[1].trim(), pillar: m[2].trim() });
      }
    }

    // Commitments
    const commitSection = content.match(/## .* Commitments Due This Week\n([\s\S]*?)(?=\n---|\n## )/);
    if (commitSection) {
      const lines = commitSection[1].match(/^- \[.\]\s+(.+)$/gm);
      if (lines) result.commitments = lines.map(l => l.replace(/^- \[.\]\s+/, ''));
    }

    // Tasks by priority
    const taskSections = {
      P0: content.match(/### Must Complete \(P0\)\n([\s\S]*?)(?=\n###|\n---|\n## )/),
      P1: content.match(/### Should Complete \(P1\)\n([\s\S]*?)(?=\n###|\n---|\n## )/),
      P2: content.match(/### If Time Permits \(P2\)\n([\s\S]*?)(?=\n###|\n---|\n## )/)
    };
    for (const [pri, match] of Object.entries(taskSections)) {
      if (match) {
        const lines = match[1].match(/^- \[.\]\s+(.+)$/gm);
        if (lines) result.tasks[pri] = lines.map(l => l.replace(/^- \[.\]\s+/, ''));
      }
    }

    return result;
  } catch { return { weekOf: '', top3: [], commitments: [], tasks: { P0: [], P1: [], P2: [] } }; }
}

/**
 * Get tasks from 03-Tasks/Tasks.md
 * Returns: { P0: [{title, status}], P1: [...], P2: [...], P3: [...] }
 */
function getTasks() {
  const filePath = path.join(VAULT_ROOT, '03-Tasks', 'Tasks.md');
  try {
    const content = fs.readFileSync(filePath, 'utf8');
    const result = { P0: [], P1: [], P2: [], P3: [] };
    let currentPri = null;

    for (const line of content.split('\n')) {
      if (line.includes('P0 - Urgent')) currentPri = 'P0';
      else if (line.includes('P1 - Important')) currentPri = 'P1';
      else if (line.includes('P2 - Normal')) currentPri = 'P2';
      else if (line.includes('P3 - Backlog')) currentPri = 'P3';
      else if (line.includes('Task Format') || line.startsWith('---')) currentPri = null;

      if (currentPri && /^- \[.\]/.test(line.trim())) {
        const statusChar = line.match(/\[(.)\]/)?.[1] || ' ';
        const status = { ' ': 'open', 's': 'started', 'b': 'blocked', 'x': 'done' }[statusChar] || 'open';
        const title = line.replace(/^-\s*\[.\]\s*/, '').replace(/\*\*/g, '').trim();
        result[currentPri].push({ title, status });
      }
    }
    return result;
  } catch { return { P0: [], P1: [], P2: [], P3: [] }; }
}

/**
 * Look up a person by name. Scans people folder directly (no index dependency).
 * Returns: { found: true, name, path, content } or { found: false }
 */
function lookupPerson(name) {
  if (!name) return { found: false };

  const peopleDirs = [
    path.join(VAULT_ROOT, '05-Areas', 'People', 'External'),
    path.join(VAULT_ROOT, '05-Areas', 'People', 'Internal')
  ];

  const query = name.toLowerCase().replace(/\s+/g, '_');
  let bestMatch = null;
  let bestScore = 0;

  for (const dir of peopleDirs) {
    if (!fs.existsSync(dir)) continue;
    const files = fs.readdirSync(dir).filter(f => f.endsWith('.md') && f !== 'README.md');

    for (const file of files) {
      const baseName = file.replace('.md', '').toLowerCase();
      // Exact match
      if (baseName === query) {
        bestMatch = path.join(dir, file);
        bestScore = 100;
        break;
      }
      // Partial match: any query word appears in filename
      const queryWords = query.split('_');
      const fileWords = baseName.split('_');
      let score = 0;
      for (const qw of queryWords) {
        for (const fw of fileWords) {
          if (fw.startsWith(qw) || qw.startsWith(fw)) score += 50;
          else if (fw.includes(qw) || qw.includes(fw)) score += 25;
        }
      }
      if (score > bestScore) {
        bestScore = score;
        bestMatch = path.join(dir, file);
      }
    }
    if (bestScore === 100) break;
  }

  if (!bestMatch || bestScore < 25) return { found: false };

  try {
    const content = fs.readFileSync(bestMatch, 'utf8');
    const displayName = path.basename(bestMatch, '.md').replace(/_/g, ' ');
    return { found: true, name: displayName, path: bestMatch, content };
  } catch { return { found: false }; }
}

/**
 * Search vault for matching markdown files.
 * Returns: [{ file, matches: [string] }] (top 5 results)
 */
function searchVault(query) {
  if (!query) return [];

  const searchDirs = ['00-Inbox', '02-Week_Priorities', '03-Tasks', '04-Projects', '05-Areas']
    .map(d => path.join(VAULT_ROOT, d))
    .filter(d => fs.existsSync(d));

  if (searchDirs.length === 0) return [];

  try {
    const result = execSync(
      `grep -ril "${query.replace(/"/g, '\\"')}" ${searchDirs.map(d => `"${d}"`).join(' ')} --include="*.md" 2>/dev/null | head -10`,
      { encoding: 'utf8', timeout: 5000 }
    ).trim();

    if (!result) return [];

    const files = result.split('\n').filter(Boolean).slice(0, 5);
    return files.map(filePath => {
      try {
        const content = fs.readFileSync(filePath, 'utf8');
        // Find lines matching the query for context
        const lines = content.split('\n');
        const matches = [];
        const q = query.toLowerCase();
        for (let i = 0; i < lines.length && matches.length < 3; i++) {
          if (lines[i].toLowerCase().includes(q)) {
            matches.push(lines[i].trim().slice(0, 120));
          }
        }
        const relPath = path.relative(VAULT_ROOT, filePath);
        return { file: relPath, matches };
      } catch { return { file: filePath, matches: [] }; }
    });
  } catch { return []; }
}

/**
 * Create a task in 03-Tasks/Tasks.md.
 * Generates a task ID, appends under the priority section.
 * Returns: { success, task_id, title, priority, pillar }
 */
function createTask(title, pillar, priority) {
  priority = priority || 'P2';
  const filePath = path.join(VAULT_ROOT, '03-Tasks', 'Tasks.md');

  // Generate task ID: task-YYYYMMDD-XXX
  const dateStr = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const existing = (() => {
    try {
      const content = fs.readFileSync(filePath, 'utf8');
      const ids = content.match(/\^task-\d{8}-(\d{3})/g) || [];
      return ids.map(id => parseInt(id.slice(-3)));
    } catch { return []; }
  })();
  const nextNum = (existing.length > 0 ? Math.max(...existing) + 1 : 1);
  const taskId = `task-${dateStr}-${String(nextNum).padStart(3, '0')}`;

  // Resolve pillar name
  const pillarsData = loadPillars();
  const pillarObj = (pillarsData.pillars || []).find(p => p.id === pillar || p.name.toLowerCase().includes(pillar.toLowerCase()));
  const pillarName = pillarObj ? pillarObj.name : pillar;

  // Build task line
  const taskEntry = `- [ ] **${title}** ^${taskId}\n\t- Pillar: ${pillarName} | Priority: ${priority}`;

  // Map priority to section header
  const sectionMap = {
    P0: '## P0 - Urgent (max 3)',
    P1: '## P1 - Important (max 5)',
    P2: '## P2 - Normal (max 10)',
    P3: '## P3 - Backlog'
  };
  const section = sectionMap[priority] || sectionMap.P2;

  try {
    let content = fs.readFileSync(filePath, 'utf8');
    if (content.includes(section)) {
      const parts = content.split(section);
      content = parts[0] + section + '\n\n' + taskEntry + '\n' + parts[1];
    } else {
      content += `\n${section}\n\n${taskEntry}\n`;
    }
    fs.writeFileSync(filePath, content, 'utf8');
    return { success: true, task_id: taskId, title, priority, pillar: pillarName };
  } catch (e) {
    return { success: false, error: e.message };
  }
}

/**
 * Complete a task by fuzzy-matching title in 03-Tasks/Tasks.md and Week_Priorities.md.
 * Checks off the first matching open task.
 * Returns: { success, title, file }
 */
function completeTask(query) {
  if (!query) return { success: false, error: 'No task description provided' };

  const files = [
    path.join(VAULT_ROOT, '03-Tasks', 'Tasks.md'),
    path.join(VAULT_ROOT, '02-Week_Priorities', 'Week_Priorities.md')
  ];

  const q = query.toLowerCase();

  for (const filePath of files) {
    try {
      const content = fs.readFileSync(filePath, 'utf8');
      const lines = content.split('\n');
      let modified = false;

      for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        if (/^- \[ \]/.test(line) && line.toLowerCase().includes(q)) {
          lines[i] = line.replace('- [ ]', '- [x]');
          const timestamp = new Date().toISOString().slice(0, 16).replace('T', ' ');
          lines[i] += ` \u2705 ${timestamp}`;
          modified = true;

          const title = line.replace(/^- \[ \]\s*/, '').replace(/\*\*/g, '').split('^')[0].trim();
          fs.writeFileSync(filePath, lines.join('\n'), 'utf8');
          const relPath = path.relative(VAULT_ROOT, filePath);
          return { success: true, title, file: relPath };
        }
      }
    } catch { /* skip file */ }
  }

  return { success: false, error: `No open task matching "${query}" found` };
}

module.exports = {
  loadProfile,
  loadPillars,
  getCalendarToday,
  getWeekPriorities,
  getTasks,
  lookupPerson,
  searchVault,
  createTask,
  completeTask
};
