#!/usr/bin/env node
/**
 * Vault Scanner for Semantic Search Collection Discovery
 * 
 * Analyzes the vault structure and suggests purpose-built qmd collections
 * based on what content actually exists. This is the "concierge" that makes
 * Dex's semantic search smarter than generic indexing.
 * 
 * Usage:
 *   node scan-vault.cjs                    # Full scan with candidates
 *   node scan-vault.cjs --health-check     # Check existing collections
 *   node scan-vault.cjs --suggestions-only # Just new candidates (for daily-plan)
 */

const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const VAULT_PATH = process.env.VAULT_PATH || process.cwd();

// Collection definitions: what we look for and why it matters
const COLLECTION_DEFS = [
  {
    name: 'people',
    paths: ['05-Areas/People'],
    glob: '**/*.md',
    minFiles: 3,
    context: 'Person pages with meeting history, relationship notes, action items, and role context',
    benefit: 'Person lookup finds references by role/title, not just name',
    example: 'Search "VP of Sales" finds the person even if their name isn\'t mentioned',
    priority: 1
  },
  {
    name: 'accounts',
    paths: ['05-Areas/Companies', '05-Areas/Relationships/Key_Accounts'],
    glob: '**/*.md',
    minFiles: 1,
    context: 'Company and account pages with deal status, relationship notes, and interaction history',
    benefit: 'Deal prep pulls account-specific context without inbox noise',
    example: 'Search "renewal risk" finds accounts with churn signals',
    priority: 2
  },
  {
    name: 'meetings',
    paths: ['00-Inbox/Meetings'],
    glob: '**/*.md',
    minFiles: 5,
    context: 'Meeting notes with attendees, key discussion points, decisions made, and action items',
    benefit: '"What was discussed about X?" searches meetings specifically',
    example: 'Search "pricing discussion" finds the right meeting without wading through tasks',
    priority: 1
  },
  {
    name: 'tasks',
    paths: ['03-Tasks'],
    glob: '**/*.md',
    minFiles: 1,
    context: 'Task backlog with priorities (P0-P3), pillar alignment, status tracking, and linked goals',
    benefit: 'Smart task matching for triage and deduplication',
    example: 'Catches "Review metrics" as duplicate of "Check quarterly numbers"',
    priority: 2
  },
  {
    name: 'projects',
    paths: ['04-Projects'],
    glob: '**/*.md',
    minFiles: 1,
    context: 'Active project tracking with status, stakeholders, timelines, and related decisions',
    benefit: 'Project health checks search project docs without inbox noise',
    example: 'Search "blocked" finds stalled projects across all project pages',
    priority: 2
  },
  {
    name: 'goals',
    paths: ['01-Quarter_Goals'],
    glob: '**/*.md',
    minFiles: 1,
    context: 'Quarterly strategic goals with success criteria, milestones, and progress tracking',
    benefit: 'Goal alignment finds thematically related work across the vault',
    example: 'Search "customer retention" finds goals about churn even if worded differently',
    priority: 3
  },
  {
    name: 'priorities',
    paths: ['02-Week_Priorities'],
    glob: '**/*.md',
    minFiles: 1,
    context: 'Weekly priorities linked to quarterly goals with completion tracking',
    benefit: 'Weekly planning discovers patterns in past priority choices',
    example: 'Finds weeks where similar priorities were set, shows what worked',
    priority: 3
  },
  {
    name: 'content',
    paths: ['05-Areas/Content'],
    glob: '**/*.md',
    minFiles: 1,
    context: 'Content ideas, articles, LinkedIn posts, and thought leadership material',
    benefit: 'Content idea search avoids duplicating past topics',
    example: 'Search "AI agents" finds all content pieces touching that theme',
    priority: 3
  },
  {
    name: 'career',
    paths: ['05-Areas/Career'],
    glob: '**/*.md',
    minFiles: 1,
    context: 'Career development evidence, feedback received, skills tracking, and growth goals',
    benefit: 'Career evidence retrieval for reviews and promotion prep',
    example: 'Search "leadership" finds all evidence of leadership competency',
    priority: 3
  },
  {
    name: 'prds',
    paths: ['System/PRDs'],
    glob: '**/*.md',
    minFiles: 1,
    context: 'Product requirement documents, feature specs, and technical design docs',
    benefit: 'PRD search finds related past specs when writing new ones',
    example: 'Search "notification system" finds all PRDs that touched notifications',
    priority: 4
  },
  {
    name: 'resources',
    paths: ['06-Resources'],
    glob: '**/*.md',
    minFiles: 5,
    context: 'Reference material, learnings, system documentation, and guides',
    benefit: 'Finds relevant learnings and reference docs by topic',
    example: 'Search "API integration" finds guides and past learnings about APIs',
    priority: 4
  },
  {
    name: 'plans',
    paths: ['plans'],
    glob: '**/*.md',
    minFiles: 3,
    context: 'Implementation blueprints, component specs, handover docs, and execution plans for Dex features',
    benefit: 'Find past implementation decisions and patterns when building new features',
    example: 'Search "MCP integration" finds all past specs and handovers that touched MCP',
    priority: 3
  },
  {
    name: 'learnings',
    paths: ['System/Session_Learnings'],
    glob: '**/*.md',
    minFiles: 5,
    context: 'Session-to-session learnings capturing what worked, what didn\'t, and system improvements discovered',
    benefit: 'Compound knowledge — past sessions inform current decisions without re-learning',
    example: 'Search "hook migration" finds past session learnings about Claude Code hook changes',
    priority: 3
  },
  {
    name: 'areas',
    paths: ['05-Areas'],
    glob: '**/*.md',
    minFiles: 10,
    context: 'Area-of-responsibility content: career, content strategy, events, partnerships, and internal intel not covered by people/accounts collections',
    benefit: 'Cross-area semantic search surfaces connections across career, content, events, and partnerships',
    example: 'Search "executive sponsor" finds career evidence, event notes, and partnership context together',
    priority: 4
  },
  {
    name: 'intel',
    paths: ['00-Inbox/LinkedIn_Intel', '00-Inbox/Newsletter_Intel', '00-Inbox/YouTube_Intel', '00-Inbox/Twitter_Intel'],
    glob: '**/*.md',
    minFiles: 3,
    context: 'Curated intelligence from LinkedIn, newsletters, YouTube, and Twitter/X — trends, signals, and competitor moves',
    benefit: 'Cross-source signal search finds themes across all intel channels in a single query',
    example: 'Search "agent orchestration" finds LinkedIn posts, newsletter summaries, and video transcripts together',
    priority: 4
  }
];

/**
 * Count markdown files in a directory recursively
 */
function countMdFiles(dirPath) {
  let count = 0;
  try {
    if (!fs.existsSync(dirPath)) return 0;
    const entries = fs.readdirSync(dirPath, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dirPath, entry.name);
      if (entry.isDirectory() && !entry.name.startsWith('.')) {
        count += countMdFiles(fullPath);
      } else if (entry.isFile() && entry.name.endsWith('.md')) {
        count++;
      }
    }
  } catch {
    return 0;
  }
  return count;
}

/**
 * Check if a directory exists and has content
 */
function checkPath(vaultPath, relativePath) {
  const fullPath = path.join(vaultPath, relativePath);
  if (!fs.existsSync(fullPath)) return { exists: false, fileCount: 0 };
  const fileCount = countMdFiles(fullPath);
  return { exists: true, fileCount, fullPath };
}

/**
 * Get existing qmd collections (if qmd is installed)
 */
function getExistingCollections() {
  try {
    const output = execSync('qmd status', { stdio: 'pipe', encoding: 'utf-8' });
    const collections = [];
    const lines = output.split('\n');
    let inCollections = false;
    let currentCollection = null;

    for (const line of lines) {
      // Collection name lines start with two spaces and the name
      const collMatch = line.match(/^\s{2}(\w+)\s+\(qmd:\/\/\w+\/\)/);
      if (collMatch) {
        currentCollection = { name: collMatch[1] };
        collections.push(currentCollection);
        inCollections = true;
        continue;
      }

      // File count line
      if (currentCollection) {
        const filesMatch = line.match(/Files:\s+(\d+)\s+\(updated\s+(.+?)\)/);
        if (filesMatch) {
          currentCollection.fileCount = parseInt(filesMatch[1]);
          currentCollection.lastUpdated = filesMatch[2];
        }
      }
    }

    return collections;
  } catch {
    return [];
  }
}

/**
 * Check if qmd is installed
 */
function isQmdInstalled() {
  try {
    execSync('which qmd', { stdio: 'pipe' });
    return true;
  } catch {
    return false;
  }
}

/**
 * Get pending embedding count
 */
function getPendingEmbeddings() {
  try {
    const output = execSync('qmd status', { stdio: 'pipe', encoding: 'utf-8' });
    const match = output.match(/Pending:\s+(\d+)/);
    return match ? parseInt(match[1]) : 0;
  } catch {
    return 0;
  }
}

/**
 * Scan the vault and discover collection candidates
 */
function scanVault() {
  const candidates = [];
  const skipped = [];
  let totalFiles = 0;

  for (const def of COLLECTION_DEFS) {
    let bestPath = null;
    let bestCount = 0;

    // Check all possible paths, use the one with the most files
    for (const relPath of def.paths) {
      const result = checkPath(VAULT_PATH, relPath);
      if (result.exists && result.fileCount > bestCount) {
        bestPath = relPath;
        bestCount = result.fileCount;
      }
    }

    if (bestPath && bestCount >= def.minFiles) {
      candidates.push({
        name: def.name,
        path: bestPath,
        glob: def.glob,
        fileCount: bestCount,
        context: def.context,
        benefit: def.benefit,
        example: def.example,
        priority: def.priority
      });
      totalFiles += bestCount;
    } else if (bestPath && bestCount > 0 && bestCount < def.minFiles) {
      skipped.push({
        name: def.name,
        path: bestPath,
        fileCount: bestCount,
        minRequired: def.minFiles,
        reason: `Only ${bestCount} file(s) found (need ${def.minFiles} for a useful collection)`
      });
    } else {
      // Determine why it was skipped
      let reason;
      if (def.name === 'career') {
        reason = 'Career folder not set up (run /career-setup)';
      } else if (def.name === 'accounts') {
        reason = 'No company/account pages found yet';
      } else {
        reason = `Folder not found: ${def.paths.join(' or ')}`;
      }

      skipped.push({
        name: def.name,
        path: def.paths[0],
        fileCount: 0,
        reason
      });
    }
  }

  // Sort candidates by priority (1 = highest)
  candidates.sort((a, b) => a.priority - b.priority);

  return {
    candidates,
    skipped,
    totalFiles,
    totalCandidates: candidates.length,
    vaultPath: VAULT_PATH
  };
}

/**
 * Health check: compare existing collections to current vault state
 */
function healthCheck() {
  const existing = getExistingCollections();
  const scan = scanVault();
  const existingNames = new Set(existing.map(c => c.name));

  // Find new candidates (in vault but not yet a collection)
  const newCandidates = scan.candidates.filter(c => !existingNames.has(c.name));

  // Check for stale collections
  const staleCollections = [];
  for (const coll of existing) {
    // Find the matching definition to check current file count
    const def = COLLECTION_DEFS.find(d => d.name === coll.name);
    if (!def) continue;

    for (const relPath of def.paths) {
      const result = checkPath(VAULT_PATH, relPath);
      if (result.exists && result.fileCount > coll.fileCount) {
        staleCollections.push({
          name: coll.name,
          lastUpdated: coll.lastUpdated,
          currentFiles: result.fileCount,
          indexedFiles: coll.fileCount,
          drift: result.fileCount - coll.fileCount
        });
        break;
      }
    }
  }

  const pendingEmbeddings = getPendingEmbeddings();

  const suggestions = [];
  if (staleCollections.length > 0) {
    suggestions.push("Run 'qmd update' to re-index changed files");
  }
  if (pendingEmbeddings > 0) {
    suggestions.push(`Run 'qmd embed' to embed ${pendingEmbeddings} pending documents`);
  }
  if (newCandidates.length > 0) {
    suggestions.push(`${newCandidates.length} new collection(s) available — run /enable-semantic-search`);
  }

  return {
    existing: existing.map(c => c.name),
    existingDetails: existing,
    newCandidates,
    staleCollections,
    pendingEmbeddings,
    suggestions,
    healthy: staleCollections.length === 0 && pendingEmbeddings === 0 && newCandidates.length === 0
  };
}

/**
 * Suggestions only: just return new candidates (for daily-plan integration)
 */
function suggestionsOnly() {
  if (!isQmdInstalled()) {
    return { available: false, suggestions: [] };
  }

  const health = healthCheck();
  return {
    available: true,
    newCandidates: health.newCandidates,
    pendingEmbeddings: health.pendingEmbeddings,
    staleCount: health.staleCollections.length,
    suggestions: health.suggestions
  };
}

// --- Main ---

const args = process.argv.slice(2);
const mode = args.includes('--health-check') ? 'health'
           : args.includes('--suggestions-only') ? 'suggestions'
           : 'scan';

let result;
switch (mode) {
  case 'health':
    result = healthCheck();
    break;
  case 'suggestions':
    result = suggestionsOnly();
    break;
  default:
    result = scanVault();
}

// Output as JSON for the skill to parse
console.log(JSON.stringify(result, null, 2));
