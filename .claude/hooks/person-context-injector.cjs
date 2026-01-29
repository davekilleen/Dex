#!/usr/bin/env node
/**
 * PreToolUse hook: Inject person context when reading files with People/ references
 * 
 * When Claude reads a file containing references to people (by name or file path),
 * this hook looks up the referenced person pages and injects:
 * - Role & company
 * - Last interaction date
 * - Open action items
 * 
 * Detection methods:
 * - File paths containing People/
 * - Names matching files in People/Internal/ or People/External/
 * - Common name patterns in meeting notes
 * 
 * Triggered on Read tool
 */
const fs = require('fs');
const path = require('path');

// Read hook input from stdin
let input;
try {
  input = JSON.parse(fs.readFileSync(0, 'utf-8'));
} catch (e) {
  process.exit(0); // Invalid input, skip silently
}

const filePath = input.tool_input?.path || input.tool_input?.file_path || '';

// Skip if no file path or if reading a Person page itself (avoid recursion)
if (!filePath || filePath.includes('/People/')) {
  process.exit(0);
}

const VAULT_ROOT = process.env.CLAUDE_PROJECT_DIR || process.env.VAULT_PATH || process.cwd();
const PEOPLE_DIR = path.join(VAULT_ROOT, 'People');

// Build an index of all person names to their files
function buildPersonIndex() {
  const index = {};
  const subdirs = ['Internal', 'External', 'CPO_Network'];
  
  for (const subdir of subdirs) {
    const dirPath = path.join(PEOPLE_DIR, subdir);
    if (!fs.existsSync(dirPath)) continue;
    
    try {
      const files = fs.readdirSync(dirPath);
      for (const file of files) {
        if (!file.endsWith('.md')) continue;
        
        const fileName = file.replace('.md', '');
        // Create variations for matching
        const normalizedName = fileName.toLowerCase();
        const spacedName = fileName.replace(/_/g, ' ').toLowerCase();
        
        const filePath = path.join(dirPath, file);
        index[normalizedName] = filePath;
        index[spacedName] = filePath;
      }
    } catch (e) {
      // Skip directories we can't read
    }
  }
  
  return index;
}

try {
  // Resolve the full file path
  const fullFilePath = filePath.startsWith('/') ? filePath : path.join(VAULT_ROOT, filePath);
  
  if (!fs.existsSync(fullFilePath)) {
    process.exit(0);
  }
  
  // Read the file to find person references
  const content = fs.readFileSync(fullFilePath, 'utf-8');
  
  // Build person index
  const personIndex = buildPersonIndex();
  const personNames = Object.keys(personIndex);
  
  if (personNames.length === 0) {
    process.exit(0);
  }
  
  // Find referenced people in the content
  const foundPeople = new Set();
  
  // Method 1: File path references (People/Internal/John_Doe.md or just People/Internal/John_Doe)
  const fileRefPattern = /People\/(?:Internal|External|CPO_Network)\/([A-Za-z0-9_-]+)(?:\.md)?/g;
  let match;
  while ((match = fileRefPattern.exec(content)) !== null) {
    const name = match[1].toLowerCase();
    if (personIndex[name]) {
      foundPeople.add(personIndex[name]);
    }
  }
  
  // Method 2: Direct name matches (only if content looks like meeting notes or has person context)
  // Look for patterns like "met with John Doe" or "John Doe mentioned"
  const contentLower = content.toLowerCase();
  const isMeetingNotes = contentLower.includes('meeting') || 
                         contentLower.includes('attendee') || 
                         contentLower.includes('call with') ||
                         contentLower.includes('met with');
  
  if (isMeetingNotes) {
    for (const name of personNames) {
      // Only match full names (with underscores or spaces)
      if (name.includes(' ') || name.includes('_')) {
        const spacedName = name.replace(/_/g, ' ');
        if (contentLower.includes(spacedName)) {
          foundPeople.add(personIndex[name]);
        }
      }
    }
  }
  
  // Only proceed if we found people
  if (foundPeople.size === 0) {
    process.exit(0);
  }
  
  // Look up each person and build context
  const personContexts = [];
  
  for (const personFilePath of foundPeople) {
    const personInfo = parsePersonPage(personFilePath);
    if (personInfo) {
      personContexts.push(personInfo);
    }
  }
  
  // Only inject if we found relevant person pages
  if (personContexts.length === 0) {
    process.exit(0);
  }
  
  // Build context (silent - no headers, just data)
  const contextLines = [
    '<person_context>',
    'Referenced people:'
  ];
  
  for (const person of personContexts) {
    contextLines.push(`${person.name} - ${person.role || 'No role'} @ ${person.company || 'Unknown'}`);
    if (person.lastInteraction) {
      contextLines.push(`  Last interaction: ${person.lastInteraction}`);
    }
    if (person.openItems && person.openItems.length > 0) {
      contextLines.push(`  Open items: ${person.openItems.length}`);
      person.openItems.slice(0, 2).forEach(item => {
        contextLines.push(`    - ${item.substring(0, 60)}${item.length > 60 ? '...' : ''}`);
      });
    }
  }
  
  contextLines.push('</person_context>');
  
  // Output context
  const output = {
    continue: true,
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      additionalContext: '\n' + contextLines.join('\n')
    }
  };
  console.log(JSON.stringify(output));
  
} catch (e) {
  // Silently fail - don't block the read operation
  process.exit(0);
}

/**
 * Parse a person page and extract key info
 */
function parsePersonPage(filePath) {
  try {
    const content = fs.readFileSync(filePath, 'utf-8');
    const fileName = path.basename(filePath, '.md');
    
    const info = {
      name: fileName.replace(/_/g, ' '),
      role: null,
      company: null,
      lastInteraction: null,
      openItems: []
    };
    
    // Parse YAML frontmatter
    if (content.startsWith('---')) {
      const endMatch = content.slice(3).indexOf('---');
      if (endMatch !== -1) {
        const frontmatter = content.slice(3, endMatch + 3);
        
        // Extract fields
        const roleMatch = frontmatter.match(/role:\s*(.+)/);
        if (roleMatch) info.role = roleMatch[1].trim();
        
        const companyMatch = frontmatter.match(/company:\s*(.+)/);
        if (companyMatch) info.company = companyMatch[1].trim();
        
        const lastIntMatch = frontmatter.match(/last_interaction:\s*(.+)/);
        if (lastIntMatch) info.lastInteraction = lastIntMatch[1].trim();
        
        // Get name from frontmatter if available
        const nameMatch = frontmatter.match(/name:\s*(.+)/);
        if (nameMatch) info.name = nameMatch[1].trim();
      }
    }
    
    // Extract open action items
    const actionItemRegex = /^- \[ \] (.+)$/gm;
    let match;
    while ((match = actionItemRegex.exec(content)) !== null) {
      info.openItems.push(match[1].replace(/\*\*/g, '').trim());
    }
    
    return info;
  } catch (e) {
    return null;
  }
}
