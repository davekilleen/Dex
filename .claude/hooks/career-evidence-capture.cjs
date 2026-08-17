#!/usr/bin/env node
/**
 * Career Evidence Candidate Detector
 * Fires after Write during /career-coach
 * Detects possible achievements and asks the active skill to seek consent.
 * This hook is deliberately read-only: it never creates or appends evidence.
 */
const fs = require('fs');
const path = require('path');
const { loadPaths } = require('./paths.cjs');

const _paths = loadPaths();

function isRegularVaultFile(filePath) {
  const vaultRoot = path.resolve(_paths.VAULT_ROOT);
  const absoluteFilePath = path.resolve(filePath);
  const relativeToVault = path.relative(vaultRoot, absoluteFilePath);
  if (
    relativeToVault === ''
    || relativeToVault.startsWith(`..${path.sep}`)
    || relativeToVault === '..'
    || path.isAbsolute(relativeToVault)
  ) return false;

  let cursor = vaultRoot;
  const parts = relativeToVault.split(path.sep);
  for (const [index, part] of parts.entries()) {
    cursor = path.join(cursor, part);
    let stat;
    try {
      stat = fs.lstatSync(cursor);
    } catch {
      return false;
    }
    if (stat.isSymbolicLink()) return false;
    const isLast = index === parts.length - 1;
    if (isLast ? !stat.isFile() : !stat.isDirectory()) return false;
  }
  return true;
}

function main() {
  // Read hook context from stdin, per the Claude Code hook contract
  const input = JSON.parse(fs.readFileSync(0, 'utf-8'));
  const filePath = input?.tool_input?.file_path || input?.toolInput?.file_path || '';

  // Only act on regular, non-symlink files inside the canonical Career directory.
  const absoluteFilePath = path.resolve(filePath);
  const relativeToCareer = path.relative(_paths.CAREER_DIR, absoluteFilePath);
  if (
    relativeToCareer === '' ||
    relativeToCareer.startsWith(`..${path.sep}`) ||
    relativeToCareer === '..' ||
    path.isAbsolute(relativeToCareer)
  ) {
    process.exit(0);
  }

  if (!isRegularVaultFile(absoluteFilePath)) {
    process.exit(0);
  }

  const content = fs.readFileSync(absoluteFilePath, 'utf-8');
  const retrievedAt = new Date().toISOString();
  const fileName = path.basename(absoluteFilePath, '.md');

  // Check for achievement markers
  const achievementPatterns = [
    /\d+%/,                          // Percentages
    /\$[\d,]+/,                      // Dollar amounts
    /\d+x/i,                         // Multipliers
    /delivered|achieved|improved|reduced|increased|launched|completed|shipped/i,
    /revenue|growth|adoption|retention|NPS|CSAT/i,
    /award|recognition|promotion|certification/i
  ];

  const hasAchievementMarkers = achievementPatterns.some(pattern => pattern.test(content));

  if (!hasAchievementMarkers) {
    process.exit(0);
  }

  // Determine skill area from content
  const skillAreas = [];
  const skillPatterns = {
    'Leadership': /leadership|team|managed|mentored|coached/i,
    'Strategy': /strategy|strategic|roadmap|vision|planning/i,
    'Technical': /technical|architecture|system|engineering|code/i,
    'Communication': /presentation|stakeholder|executive|board|communication/i,
    'Customer': /customer|client|user|NPS|satisfaction|retention/i,
    'Product': /product|feature|launch|release|adoption/i,
    'Sales': /deal|revenue|pipeline|close|win/i
  };

  for (const [area, pattern] of Object.entries(skillPatterns)) {
    if (pattern.test(content)) {
      skillAreas.push(area);
    }
  }

  const skillArea = skillAreas.length > 0 ? skillAreas.join(', ') : 'General';

  // Extract a brief description (first line with achievement markers, or first non-header line)
  let briefDesc = '';
  for (const line of content.split('\n')) {
    const trimmed = line.trim();
    if (trimmed.startsWith('#') || trimmed === '' || trimmed === '---') continue;
    if (achievementPatterns.some(p => p.test(trimmed))) {
      briefDesc = trimmed.substring(0, 120);
      break;
    }
  }
  if (!briefDesc) {
    briefDesc = `Evidence captured from ${fileName}`;
  }

  const frontmatter = content.match(/^---\s*\n([\s\S]*?)\n---(?:\s*\n|$)/);
  const eventDateMatch = frontmatter?.[1]?.match(/^date:\s*["']?(\d{4}-\d{2}-\d{2})["']?\s*$/m);
  const eventDate = eventDateMatch?.[1] || 'unknown';
  const sourcePath = path.relative(_paths.VAULT_ROOT, absoluteFilePath).split(path.sep).join('/');
  const evidenceLogPath = path.join(_paths.CAREER_DIR, 'Evidence_Log.md');
  const destinationPath = path.relative(_paths.VAULT_ROOT, evidenceLogPath).split(path.sep).join('/');
  const entry = `| ${eventDate} | ${skillArea} | [[${fileName}]] | ${briefDesc.replace(/\|/g, '/')} |`;
  const uncertainty = eventDate === 'unknown'
    ? 'source event date is unknown; do not substitute the retrieval date'
    : 'achievement meaning and skill-area classification are inferred and require user validation';

  const output = {
    continue: true,
    hookSpecificOutput: {
      hookEventName: 'PostToolUse',
      additionalContext: [
        '<career_evidence_candidate>',
        'Candidate only; nothing was saved.',
        `Source path: ${sourcePath}`,
        `Source event date: ${eventDate}`,
        `Retrieved as-of: ${retrievedAt}`,
        `Proposed destination: ${destinationPath}`,
        `Unconfirmed candidate entry: ${entry}`,
        `Uncertainty: ${uncertainty}.`,
        'Before any save, show the exact proposed bytes and destination, obtain explicit confirmation for this evidence entry, then write and read back the destination. If confirmation or read-back is absent, do not save or claim capture.',
        '</career_evidence_candidate>',
      ].join('\n'),
    },
  };
  console.log(JSON.stringify(output));
}

try {
  main();
} catch {
  process.exit(0);
}
