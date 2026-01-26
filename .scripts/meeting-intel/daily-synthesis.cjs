#!/usr/bin/env node

/**
 * Daily Synthesis - Aggregate meeting insights into daily digest
 * 
 * Reads all meeting notes from today (or specified date) and generates
 * a synthesis digest highlighting:
 * - Key decisions made
 * - Action items by owner
 * - Meeting intelligence signals
 * - Cross-meeting themes
 * 
 * Usage:
 *   node .scripts/meeting-intel/daily-synthesis.cjs           # Today
 *   node .scripts/meeting-intel/daily-synthesis.cjs 2026-01-17  # Specific date
 */

const fs = require('fs');
const path = require('path');
const yaml = require('js-yaml');
const { generateContentRaw, GEMINI_API_KEY } = require('../lib/gemini-client.cjs');

// ============================================================================
// CONFIGURATION
// ============================================================================

const VAULT_ROOT = path.resolve(__dirname, '../..');
const MEETINGS_DIR = path.join(VAULT_ROOT, 'Inbox', 'Meetings');
const PILLARS_FILE = path.join(VAULT_ROOT, 'System', 'pillars.yaml');
const PROFILE_FILE = path.join(VAULT_ROOT, 'System', 'user-profile.yaml');

// ============================================================================
// HELPERS
// ============================================================================

function log(message) {
  const timestamp = new Date().toISOString();
  console.log(`[${timestamp}] ${message}`);
}

function loadPillars() {
  if (!fs.existsSync(PILLARS_FILE)) {
    return { 'General': 0 };
  }
  try {
    const pillarsData = yaml.load(fs.readFileSync(PILLARS_FILE, 'utf-8'));
    const pillars = {};
    for (const p of pillarsData.pillars) {
      const name = p.name || p.id;
      pillars[name] = 0;
    }
    return pillars;
  } catch (e) {
    return { 'General': 0 };
  }
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

function readMeetingNotes(date) {
  const dayDir = path.join(MEETINGS_DIR, date);
  
  if (!fs.existsSync(dayDir)) {
    return [];
  }
  
  const files = fs.readdirSync(dayDir).filter(f => f.endsWith('.md'));
  const notes = [];
  
  for (const file of files) {
    const content = fs.readFileSync(path.join(dayDir, file), 'utf-8');
    
    // Parse frontmatter
    const frontmatterMatch = content.match(/^---\n([\s\S]*?)\n---/);
    const frontmatter = {};
    if (frontmatterMatch) {
      for (const line of frontmatterMatch[1].split('\n')) {
        const colonIndex = line.indexOf(':');
        if (colonIndex > 0) {
          const key = line.substring(0, colonIndex).trim();
          const value = line.substring(colonIndex + 1).trim().replace(/^["'\[]|["'\]]$/g, '');
          frontmatter[key] = value;
        }
      }
    }
    
    // Extract main content (after frontmatter)
    const mainContent = content.replace(/^---\n[\s\S]*?\n---\n*/, '');
    
    notes.push({
      file,
      filepath: `Inbox/Meetings/${date}/${file}`,
      title: frontmatter.title || file.replace('.md', '').replace(/-/g, ' '),
      participants: frontmatter.participants || '',
      company: frontmatter.company || '',
      pillar: frontmatter.pillar || '',
      time: frontmatter.time || '',
      duration: frontmatter.duration || '',
      content: mainContent
    });
  }
  
  return notes;
}

function extractInsights(notes, pillarsTemplate) {
  const insights = {
    decisions: [],
    actionItemsMe: [],
    actionItemsOthers: [],
    meetingIntel: [],
    participants: new Set(),
    companies: new Set(),
    pillars: { ...pillarsTemplate }
  };
  
  for (const note of notes) {
    const content = note.content;
    
    // Track participants and companies
    if (note.participants) {
      note.participants.split(',').forEach(p => insights.participants.add(p.trim()));
    }
    if (note.company) {
      insights.companies.add(note.company);
    }
    
    // Track pillar alignment
    if (note.pillar) {
      const pillars = note.pillar.replace(/[\[\]"']/g, '').split(',').map(p => p.trim());
      pillars.forEach(p => {
        // Match case-insensitively
        const matchedPillar = Object.keys(insights.pillars).find(
          k => k.toLowerCase() === p.toLowerCase()
        );
        if (matchedPillar) {
          insights.pillars[matchedPillar]++;
        }
      });
    }
    
    // Extract decisions section
    const decisionsMatch = content.match(/## Decisions Made\n\n([\s\S]*?)(?=\n## |$)/i);
    if (decisionsMatch) {
      const decisionLines = decisionsMatch[1].match(/^[-*]\s*(.+)/gm) || [];
      decisionLines.forEach(line => {
        const decision = line.replace(/^[-*]\s*/, '').trim();
        if (decision && decision.length > 5) {
          insights.decisions.push({
            decision,
            meeting: note.title,
            filepath: note.filepath
          });
        }
      });
    }
    
    // Extract action items - For Me section
    const actionMeMatch = content.match(/### For Me\n\n([\s\S]*?)(?=\n### |$)/i);
    if (actionMeMatch) {
      const actionLines = actionMeMatch[1].match(/^[-*]\s*\[[ x]\]\s*(.+)/gm) || [];
      actionLines.forEach(line => {
        const action = line.replace(/^[-*]\s*\[[ x]\]\s*/, '').trim();
        if (action && action.length > 5) {
          insights.actionItemsMe.push({
            action,
            meeting: note.title,
            filepath: note.filepath
          });
        }
      });
    }
    
    // Extract action items - For Others section
    const actionOthersMatch = content.match(/### For Others\n\n([\s\S]*?)(?=\n## |$)/i);
    if (actionOthersMatch) {
      const actionLines = actionOthersMatch[1].match(/^[-*]\s*\[[ x]\]\s*(.+)/gm) || [];
      actionLines.forEach(line => {
        const action = line.replace(/^[-*]\s*\[[ x]\]\s*/, '').trim();
        if (action && action.length > 5) {
          insights.actionItemsOthers.push({
            action,
            meeting: note.title,
            filepath: note.filepath
          });
        }
      });
    }
    
    // Extract meeting intelligence
    const intelMatch = content.match(/## Meeting Intelligence\n\n([\s\S]*?)(?=\n## |$)/i);
    if (intelMatch) {
      // Pain points
      const painMatch = intelMatch[1].match(/\*\*Pain Points:\*\*\n([\s\S]*?)(?=\n\*\*|$)/i);
      if (painMatch) {
        const painLines = painMatch[1].match(/^[-*]\s*(.+)/gm) || [];
        painLines.forEach(line => {
          const pain = line.replace(/^[-*]\s*/, '').trim();
          if (pain && pain.length > 5 && !pain.includes('None identified')) {
            insights.meetingIntel.push({
              type: 'Pain Point',
              detail: pain,
              meeting: note.title,
              company: note.company
            });
          }
        });
      }
      
      // Requests/Needs
      const requestMatch = intelMatch[1].match(/\*\*Requests\/Needs:\*\*\n([\s\S]*?)(?=\n\*\*|$)/i);
      if (requestMatch) {
        const requestLines = requestMatch[1].match(/^[-*]\s*(.+)/gm) || [];
        requestLines.forEach(line => {
          const request = line.replace(/^[-*]\s*/, '').trim();
          if (request && request.length > 5 && !request.includes('None identified')) {
            insights.meetingIntel.push({
              type: 'Request',
              detail: request,
              meeting: note.title,
              company: note.company
            });
          }
        });
      }
      
      // Competitive mentions
      const compMatch = intelMatch[1].match(/\*\*Competitive Mentions:\*\*\n([\s\S]*?)(?=\n\*\*|$)/i);
      if (compMatch) {
        const compLines = compMatch[1].match(/^[-*]\s*(.+)/gm) || [];
        compLines.forEach(line => {
          const comp = line.replace(/^[-*]\s*/, '').trim();
          if (comp && comp.length > 5 && !comp.includes('None identified')) {
            insights.meetingIntel.push({
              type: 'Competitive Intel',
              detail: comp,
              meeting: note.title,
              company: note.company
            });
          }
        });
      }
    }
  }
  
  return insights;
}

async function callGeminiApi(prompt) {
  return await generateContentRaw(prompt, { maxOutputTokens: 2000 });
}

async function generateThemeSynthesis(notes, profile) {
  if (!GEMINI_API_KEY || notes.length === 0) {
    return null;
  }
  
  const summaries = notes.map(n => 
    `**${n.title}** (${n.participants})\n${n.content.substring(0, 2000)}`
  ).join('\n\n---\n\n');
  
  const prompt = `You are synthesizing today's meeting intelligence for a ${profile.role}${profile.company ? ` at ${profile.company}` : ''}.

Here are the meeting notes from today:

${summaries}

Generate a brief synthesis that identifies:

1. **Cross-Meeting Themes**: What topics or patterns appeared across multiple meetings?

2. **Key Outcomes**: Most important decisions or commitments made today.

3. **Relationship Signals**: Notable dynamics, concerns, or opportunities with people/companies.

4. **Follow-up Priority**: What needs immediate attention vs can wait?

Keep it concise and actionable. Format in clean markdown. No more than 300 words.`;

  try {
    return await callGeminiApi(prompt);
  } catch (err) {
    log(`Theme synthesis failed: ${err.message}`);
    return null;
  }
}

function generateDigest(date, notes, insights, themeSynthesis) {
  let content = `---
date: ${date}
type: meeting-digest
meetings_processed: ${notes.length}
---

# Meeting Digest - ${date}

**Meetings:** ${notes.length} | **People:** ${insights.participants.size} | **Companies:** ${Array.from(insights.companies).filter(c => c).length}

## Meetings Analyzed

${notes.map(n => `- ${n.filepath}${n.company ? ` (${n.company})` : ''}`).join('\n')}

`;

  if (themeSynthesis) {
    content += `## Daily Synthesis

${themeSynthesis}

`;
  }

  if (insights.decisions.length > 0) {
    content += `## Decisions Made

${insights.decisions.map(d => `- ${d.decision} — *${d.filepath}*`).join('\n')}

`;
  }

  if (insights.actionItemsMe.length > 0) {
    content += `## My Action Items

${insights.actionItemsMe.map(a => `- [ ] ${a.action} — *${a.filepath}*`).join('\n')}

`;
  }

  if (insights.actionItemsOthers.length > 0) {
    content += `## Waiting On Others

${insights.actionItemsOthers.map(a => `- [ ] ${a.action} — *${a.filepath}*`).join('\n')}

`;
  }

  if (insights.meetingIntel.length > 0) {
    content += `## Meeting Intelligence

${insights.meetingIntel.map(c => `- **${c.type}**: ${c.detail}${c.company ? ` *(${c.company})*` : ''}`).join('\n')}

`;
  }

  // Pillar distribution
  const activePillars = Object.entries(insights.pillars).filter(([, count]) => count > 0);
  if (activePillars.length > 0) {
    content += `## Pillar Distribution

${activePillars.map(([pillar, count]) => `- ${pillar}: ${count} meeting${count > 1 ? 's' : ''}`).join('\n')}

`;
  }

  content += `---
*Generated by Dex Meeting Intel*
`;

  return content;
}

// ============================================================================
// MAIN
// ============================================================================

async function main() {
  const dateArg = process.argv[2];
  const date = dateArg || new Date().toISOString().split('T')[0];
  
  log(`Generating Meeting digest for ${date}...`);
  
  // Load configuration
  const pillarsTemplate = loadPillars();
  const profile = loadUserProfile();
  
  // Read meeting notes for the date
  const notes = readMeetingNotes(date);
  
  if (notes.length === 0) {
    log(`No meeting notes found for ${date}`);
    log(`Process meetings first with: node .scripts/meeting-intel/sync-from-granola.cjs`);
    return;
  }
  
  log(`Found ${notes.length} meeting notes`);
  
  // Extract insights
  const insights = extractInsights(notes, pillarsTemplate);
  log(`Decisions: ${insights.decisions.length}, Action items: ${insights.actionItemsMe.length + insights.actionItemsOthers.length}`);
  
  // Generate theme synthesis with Gemini (optional)
  let themeSynthesis = null;
  if (GEMINI_API_KEY && notes.length >= 2) {
    log('Generating theme synthesis with Gemini...');
    themeSynthesis = await generateThemeSynthesis(notes, profile);
  }
  
  // Generate digest
  const digest = generateDigest(date, notes, insights, themeSynthesis);
  
  // Save digest
  const digestPath = path.join(MEETINGS_DIR, `digest-${date}.md`);
  fs.writeFileSync(digestPath, digest);
  log(`Saved digest to ${digestPath}`);
  
  // Print summary
  console.log('\n' + '='.repeat(60));
  console.log(`MEETING DIGEST - ${date}`);
  console.log('='.repeat(60));
  console.log(`Meetings: ${notes.length}`);
  console.log(`Decisions: ${insights.decisions.length}`);
  console.log(`My Action Items: ${insights.actionItemsMe.length}`);
  console.log(`Waiting On Others: ${insights.actionItemsOthers.length}`);
  console.log(`Meeting Intel: ${insights.meetingIntel.length}`);
  console.log('='.repeat(60) + '\n');
}

main().catch(err => {
  log(`FATAL: ${err.message}`);
  console.error(err);
  process.exit(1);
});
