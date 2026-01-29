#!/usr/bin/env node
/**
 * PreToolUse hook: Inject company/account context when reading files with relationship references
 * 
 * When Claude reads a file containing references to companies or accounts,
 * this hook looks up the referenced company pages and injects:
 * - Key contacts
 * - Recent meetings
 * - Open tasks
 * - Status/context
 * 
 * Detection methods:
 * - File paths containing 05-Areas/Accounts/
 * - Company names matching files in accounts folder
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

// Skip if no file path or if reading a company page itself (avoid recursion)
if (!filePath || filePath.includes('/05-Areas/Companies/') || filePath.includes('/05-Areas/Accounts/')) {
  process.exit(0);
}

const VAULT_ROOT = process.env.CLAUDE_PROJECT_DIR || process.env.VAULT_PATH || process.cwd();
// Primary location for company pages (new universal pattern)
const COMPANIES_DIR = path.join(VAULT_ROOT, '02-Areas', 'Companies');
// Legacy location for backwards compatibility
const ACCOUNTS_DIR = path.join(VAULT_ROOT, '02-Areas', 'Accounts');

// Helper function to recursively scan a directory for company files
function scanDir(dirPath, index) {
  try {
    const entries = fs.readdirSync(dirPath, { withFileTypes: true });
    
    for (const entry of entries) {
      const fullPath = path.join(dirPath, entry.name);
      
      if (entry.isDirectory()) {
        scanDir(fullPath, index);
      } else if (entry.name.endsWith('.md')) {
        const fileName = entry.name.replace('.md', '');
        // Create variations for matching
        const normalizedName = fileName.toLowerCase();
        const spacedName = fileName.replace(/_/g, ' ').toLowerCase();
        const dashName = fileName.replace(/-/g, ' ').toLowerCase();
        
        index[normalizedName] = fullPath;
        index[spacedName] = fullPath;
        index[dashName] = fullPath;
      }
    }
  } catch (e) {
    // Skip directories we can't read
  }
}

// Build an index of all company names to their files
function buildCompanyIndex() {
  const index = {};
  
  // Scan new location first (Companies/)
  if (fs.existsSync(COMPANIES_DIR)) {
    scanDir(COMPANIES_DIR, index);
  }
  
  // Scan legacy location for backwards compatibility (Accounts/)
  if (fs.existsSync(ACCOUNTS_DIR)) {
    scanDir(ACCOUNTS_DIR, index);
  }
  
  return index;
}

try {
  // Resolve the full file path
  const fullFilePath = filePath.startsWith('/') ? filePath : path.join(VAULT_ROOT, filePath);
  
  if (!fs.existsSync(fullFilePath)) {
    process.exit(0);
  }
  
  // Read the file to find company references
  const content = fs.readFileSync(fullFilePath, 'utf-8');
  
  // Build company index
  const companyIndex = buildCompanyIndex();
  const companyNames = Object.keys(companyIndex);
  
  if (companyNames.length === 0) {
    process.exit(0);
  }
  
  // Find referenced companies in the content
  const foundCompanies = new Set();
  
  // Method 1: File path references (05-Areas/Companies/ or 05-Areas/Accounts/)
  const fileRefPattern = /02-Areas\/(?:Companies|Accounts)\/[^\s]*?([A-Za-z0-9_-]+)(?:\.md)?/g;
  let match;
  while ((match = fileRefPattern.exec(content)) !== null) {
    const name = match[1].toLowerCase();
    if (companyIndex[name]) {
      foundCompanies.add(companyIndex[name]);
    }
  }
  
  // Method 2: Direct company name matches in meeting notes or business context
  const contentLower = content.toLowerCase();
  const isBusinessContext = contentLower.includes('meeting') || 
                            contentLower.includes('call') || 
                            contentLower.includes('demo') ||
                            contentLower.includes('account') ||
                            contentLower.includes('deal') ||
                            contentLower.includes('opportunity');
  
  if (isBusinessContext) {
    for (const name of companyNames) {
      // Only match multi-character names to avoid false positives
      if (name.length > 3) {
        const spacedName = name.replace(/_/g, ' ').replace(/-/g, ' ');
        if (contentLower.includes(spacedName)) {
          foundCompanies.add(companyIndex[name]);
        }
      }
    }
  }
  
  // Only proceed if we found companies
  if (foundCompanies.size === 0) {
    process.exit(0);
  }
  
  // Look up each company and build context
  const companyContexts = [];
  
  for (const companyFilePath of foundCompanies) {
    const companyInfo = parseCompanyPage(companyFilePath);
    if (companyInfo) {
      companyContexts.push(companyInfo);
    }
  }
  
  // Only inject if we found relevant company pages
  if (companyContexts.length === 0) {
    process.exit(0);
  }
  
  // Build context (silent - no headers, just data)
  const contextLines = [
    '<company_context>',
    'Referenced companies:'
  ];
  
  for (const company of companyContexts) {
    contextLines.push(`${company.name}${company.status ? ` - ${company.status}` : ''}`);
    
    if (company.contacts && company.contacts.length > 0) {
      contextLines.push(`  Key contacts: ${company.contacts.slice(0, 3).join(', ')}`);
    }
    
    if (company.lastMeeting) {
      contextLines.push(`  Last meeting: ${company.lastMeeting}`);
    }
    
    if (company.openTasks && company.openTasks.length > 0) {
      contextLines.push(`  Open tasks: ${company.openTasks.length}`);
      company.openTasks.slice(0, 2).forEach(task => {
        contextLines.push(`    - ${task.substring(0, 60)}${task.length > 60 ? '...' : ''}`);
      });
    }
    
    if (company.context) {
      contextLines.push(`  Context: ${company.context.substring(0, 100)}${company.context.length > 100 ? '...' : ''}`);
    }
  }
  
  contextLines.push('</company_context>');
  
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
 * Parse a company page and extract key info
 */
function parseCompanyPage(filePath) {
  try {
    const content = fs.readFileSync(filePath, 'utf-8');
    const fileName = path.basename(filePath, '.md');
    
    const info = {
      name: fileName.replace(/_/g, ' ').replace(/-/g, ' '),
      status: null,
      contacts: [],
      lastMeeting: null,
      openTasks: [],
      context: null
    };
    
    // Parse YAML frontmatter
    if (content.startsWith('---')) {
      const endMatch = content.slice(3).indexOf('---');
      if (endMatch !== -1) {
        const frontmatter = content.slice(3, endMatch + 3);
        
        // Extract fields
        const statusMatch = frontmatter.match(/status:\s*(.+)/);
        if (statusMatch) info.status = statusMatch[1].trim();
        
        const nameMatch = frontmatter.match(/name:\s*(.+)/);
        if (nameMatch) info.name = nameMatch[1].trim();
        
        // Try to find contacts in frontmatter
        const contactsMatch = frontmatter.match(/contacts:\s*\n((?:\s*-\s*.+\n)+)/);
        if (contactsMatch) {
          const contactLines = contactsMatch[1].match(/-\s*(.+)/g);
          if (contactLines) {
            info.contacts = contactLines.map(l => l.replace(/^-\s*/, '').trim());
          }
        }
      }
    }
    
    // Extract open tasks
    const taskRegex = /^- \[ \] (.+)$/gm;
    let match;
    while ((match = taskRegex.exec(content)) !== null) {
      info.openTasks.push(match[1].replace(/\*\*/g, '').trim());
    }
    
    // Find last meeting reference
    const meetingPattern = /(?:last meeting|met on|call on)[:\s]+(\d{4}-\d{2}-\d{2}|\w+ \d{1,2},? \d{4})/i;
    const meetingMatch = content.match(meetingPattern);
    if (meetingMatch) {
      info.lastMeeting = meetingMatch[1];
    }
    
    // Extract context from first paragraph after frontmatter
    const bodyContent = content.replace(/^---[\s\S]*?---/, '').trim();
    const firstParagraph = bodyContent.split('\n\n')[0];
    if (firstParagraph && !firstParagraph.startsWith('#') && !firstParagraph.startsWith('-')) {
      info.context = firstParagraph.trim();
    }
    
    // Find contacts from ## Contacts or ## Key Contacts section
    const contactsSection = content.match(/##\s*(?:Key\s+)?Contacts[\s\S]*?(?=##|$)/i);
    if (contactsSection && info.contacts.length === 0) {
      const contactMatches = contactsSection[0].match(/[-*]\s*\*?\*?([^*\n]+)\*?\*?/g);
      if (contactMatches) {
        info.contacts = contactMatches.slice(0, 5).map(c => 
          c.replace(/^[-*]\s*\*?\*?/, '').replace(/\*?\*?$/, '').trim()
        ).filter(c => c.length > 0);
      }
    }
    
    return info;
  } catch (e) {
    return null;
  }
}
