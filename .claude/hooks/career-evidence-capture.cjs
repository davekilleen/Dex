#!/usr/bin/env node
/**
 * Career Evidence Auto-Capture
 * Fires after Write during /career-coach
 * Detects achievements in career-related files and logs them
 */
const fs = require('fs');
const path = require('path');

function main() {
  // Read hook context from stdin, per the Claude Code hook contract
  const input = JSON.parse(fs.readFileSync(0, 'utf-8'));
  const filePath = input?.tool_input?.file_path || input?.toolInput?.file_path || '';

  // Only act on Career directory files
  if (!filePath.includes('05-Areas/Career') && !filePath.includes('Career/')) {
    process.exit(0);
  }

  if (!fs.existsSync(filePath)) {
    process.exit(0);
  }

  const content = fs.readFileSync(filePath, 'utf-8');
  const today = new Date().toISOString().split('T')[0];
  const fileName = path.basename(filePath, '.md');

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

  // Append to Evidence Log
  const vaultRoot = process.env.CLAUDE_PROJECT_DIR || path.resolve(__dirname, '../..');
  const evidenceLogPath = path.join(vaultRoot, '05-Areas/Career/Evidence_Log.md');

  // Create log if it doesn't exist
  if (!fs.existsSync(evidenceLogPath)) {
    const header = `# Career Evidence Log\n\nAuto-captured achievements from career coaching sessions.\n\n| Date | Skill Area | Source | Description |\n|------|-----------|--------|-------------|\n`;
    // Ensure directory exists
    const dir = path.dirname(evidenceLogPath);
    if (!fs.existsSync(dir)) {
      fs.mkdirSync(dir, { recursive: true });
    }
    fs.writeFileSync(evidenceLogPath, header);
  }

  // Append entry
  const entry = `| ${today} | ${skillArea} | [[${fileName}]] | ${briefDesc.replace(/\|/g, '/')} |\n`;
  fs.appendFileSync(evidenceLogPath, entry);

  console.log(`Career evidence captured: ${skillArea} from ${fileName}`);
}

try {
  main();
} catch {
  process.exit(0);
}
