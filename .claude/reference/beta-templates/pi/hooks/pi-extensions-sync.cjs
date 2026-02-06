#!/usr/bin/env node
/**
 * SessionStart hook: Sync Pi-built extensions into Dex's skill system
 *
 * Scans .pi/extensions/ for TypeScript extensions and:
 * 1. Parses metadata (name, description, tools, commands)
 * 2. Generates skill stubs in .claude/skills/pi-generated/
 * 3. Creates a registry file for quick lookup
 * 4. Outputs session context about available Pi tools
 *
 * Triggered on SessionStart
 */
const fs = require('fs');
const path = require('path');

const VAULT_ROOT = process.env.CLAUDE_PROJECT_DIR || process.env.VAULT_PATH || process.cwd();
const PI_EXTENSIONS_DIR = path.join(VAULT_ROOT, '.pi', 'extensions');
const PI_SKILLS_DIR = path.join(VAULT_ROOT, '.claude', 'skills', 'pi-generated');
const PI_REGISTRY_FILE = path.join(VAULT_ROOT, '.claude', 'pi-extensions-registry.json');

/**
 * Parse a TypeScript extension file to extract metadata
 */
function parseExtension(filePath) {
  try {
    const content = fs.readFileSync(filePath, 'utf-8');
    const fileName = path.basename(filePath, '.ts');

    const extension = {
      id: fileName,
      name: fileName,
      file: filePath,
      description: '',
      tools: [],
      commands: [],
      lastModified: fs.statSync(filePath).mtime.toISOString()
    };

    // Extract JSDoc comment at top of file
    const topDocMatch = content.match(/^\/\*\*\s*\n([\s\S]*?)\*\//);
    if (topDocMatch) {
      const docContent = topDocMatch[1]
        .split('\n')
        .map(line => line.replace(/^\s*\*\s?/, '').trim())
        .filter(line => line && !line.startsWith('@'))
        .join(' ');
      extension.description = docContent.substring(0, 500);
    }

    // Extract registered tools using pi.registerTool pattern
    const toolMatches = content.matchAll(/pi\.registerTool\(\s*\{([^}]+name:\s*["']([^"']+)["'][^}]+description:\s*[`"']([^`"']+)[`"'][^}]*)\}/gs);
    for (const match of toolMatches) {
      const toolName = match[2];
      const toolDesc = match[3].split('\n')[0].trim(); // First line of description
      extension.tools.push({
        name: toolName,
        description: toolDesc
      });
    }

    // Also try alternate pattern where description comes first
    const altToolMatches = content.matchAll(/pi\.registerTool\(\s*\{[^}]*description:\s*[`"']([^`"']+)[`"'][^}]*name:\s*["']([^"']+)["'][^}]*\}/gs);
    for (const match of altToolMatches) {
      const toolName = match[2];
      const toolDesc = match[1].split('\n')[0].trim();
      // Avoid duplicates
      if (!extension.tools.find(t => t.name === toolName)) {
        extension.tools.push({
          name: toolName,
          description: toolDesc
        });
      }
    }

    // More flexible tool parsing - look for registerTool calls with better regex
    // Match the entire registerTool block including nested objects
    const registerToolPattern = /pi\.registerTool\(\s*\{([\s\S]*?)parameters:\s*Type/g;
    const toolBlocks = content.matchAll(registerToolPattern);

    for (const match of toolBlocks) {
      const block = match[1];
      const nameMatch = block.match(/name:\s*["']([^"']+)["']/);
      const labelMatch = block.match(/label:\s*["']([^"']+)["']/);

      // Extract description - handle template literals with backticks
      let description = 'No description';
      const descBacktickMatch = block.match(/description:\s*`([\s\S]*?)`/);
      const descQuoteMatch = block.match(/description:\s*["']([^"']+)["']/);

      if (descBacktickMatch) {
        // Clean up the multi-line description
        description = descBacktickMatch[1]
          .split('\n')
          .map(line => line.trim())
          .filter(line => line)
          .join(' ')
          .substring(0, 200);
      } else if (descQuoteMatch) {
        description = descQuoteMatch[1];
      }

      if (nameMatch) {
        const toolName = nameMatch[1];
        // Avoid duplicates - update if we found a better description
        const existing = extension.tools.find(t => t.name === toolName);
        if (!existing) {
          extension.tools.push({
            name: toolName,
            label: labelMatch ? labelMatch[1] : toolName,
            description: description
          });
        } else if (existing.description === 'No description' || existing.description === 'Action to perform') {
          existing.description = description;
          if (labelMatch) existing.label = labelMatch[1];
        }
      }
    }

    // Extract registered commands using pi.registerCommand pattern
    const cmdMatches = content.matchAll(/pi\.registerCommand\(\s*["']([^"']+)["']\s*,\s*\{[^}]*description:\s*["']([^"']+)["']/g);
    for (const match of cmdMatches) {
      extension.commands.push({
        name: match[1],
        description: match[2]
      });
    }

    // Extract module exports default function
    const exportMatch = content.match(/export\s+default\s+function\s*\(\s*(\w+)\s*:\s*ExtensionAPI\s*\)/);
    if (exportMatch) {
      extension.isValidExtension = true;
    }

    return extension;
  } catch (e) {
    console.error(`Failed to parse ${filePath}:`, e.message);
    return null;
  }
}

/**
 * Generate a Dex skill stub for a Pi extension
 */
function generateSkillStub(extension) {
  const toolsList = extension.tools.map(t =>
    `- **${t.name}** - ${t.description}`
  ).join('\n');

  const commandsList = extension.commands.map(c =>
    `- \`${c.name}\` - ${c.description}`
  ).join('\n');

  const toolsSection = extension.tools.length > 0
    ? `## Available Tools\n\n${toolsList}\n\n`
    : '';

  const commandsSection = extension.commands.length > 0
    ? `## Commands\n\n${commandsList}\n\n`
    : '';

  const usageExamples = extension.tools.map(t => {
    if (t.name.includes('task')) {
      return `Use the **${t.name}** tool to manage tasks`;
    } else if (t.name.includes('calendar')) {
      return `Use the **${t.name}** tool to access calendar events`;
    }
    return `Use the **${t.name}** tool`;
  }).join('\n- ');

  return `---
name: pi:${extension.id}
description: ${extension.description || `Pi extension: ${extension.name}`}
source: pi-extension
auto_generated: true
last_synced: ${new Date().toISOString()}
---

# Pi Extension: ${extension.name}

> **Note:** This skill was auto-generated from \`.pi/extensions/${extension.id}.ts\`
> It provides access to Pi tools within the Dex environment.

${extension.description || 'No description available.'}

${toolsSection}${commandsSection}## How to Use

This extension was built in Pi and synced to Dex. The tools are available to Pi but
provide context for Dex about what capabilities exist in the Pi environment.

### From Dex

Reference this extension when discussing Pi capabilities:
- ${usageExamples || `The ${extension.name} extension provides specialized functionality`}

### From Pi

The tools are natively available:
${extension.tools.map(t => `- \`${t.name}\``).join('\n') || '- (no tools registered)'}

${extension.commands.length > 0 ? `### Commands\n\nRun these in Pi:\n${extension.commands.map(c => `- \`/${c.name}\``).join('\n')}` : ''}

---

*Auto-synced from Pi extensions on ${new Date().toLocaleDateString()}*
`;
}

/**
 * Main sync function
 */
function syncExtensions() {
  // Check if Pi extensions directory exists
  if (!fs.existsSync(PI_EXTENSIONS_DIR)) {
    // No extensions yet - that's fine
    return {
      status: 'no_extensions_dir',
      extensions: []
    };
  }

  // Ensure pi-generated skills directory exists
  if (!fs.existsSync(PI_SKILLS_DIR)) {
    fs.mkdirSync(PI_SKILLS_DIR, { recursive: true });
  }

  // Load existing registry for comparison
  let existingRegistry = { extensions: [], lastSync: null };
  if (fs.existsSync(PI_REGISTRY_FILE)) {
    try {
      existingRegistry = JSON.parse(fs.readFileSync(PI_REGISTRY_FILE, 'utf-8'));
    } catch (e) {
      // Corrupted registry, will rebuild
    }
  }

  // Scan for .ts files
  const files = fs.readdirSync(PI_EXTENSIONS_DIR)
    .filter(f => f.endsWith('.ts'));

  if (files.length === 0) {
    return {
      status: 'no_extensions',
      extensions: []
    };
  }

  const extensions = [];
  const updated = [];
  const added = [];

  for (const file of files) {
    const filePath = path.join(PI_EXTENSIONS_DIR, file);
    const extension = parseExtension(filePath);

    if (!extension) continue;

    extensions.push(extension);

    // Check if this extension is new or updated
    const existing = existingRegistry.extensions.find(e => e.id === extension.id);
    if (!existing) {
      added.push(extension.id);
    } else if (existing.lastModified !== extension.lastModified) {
      updated.push(extension.id);
    } else {
      // No change, skip regenerating skill
      continue;
    }

    // Generate skill stub
    const skillDir = path.join(PI_SKILLS_DIR, `pi-${extension.id}`);
    if (!fs.existsSync(skillDir)) {
      fs.mkdirSync(skillDir, { recursive: true });
    }

    const skillContent = generateSkillStub(extension);
    fs.writeFileSync(path.join(skillDir, 'SKILL.md'), skillContent);
  }

  // Remove skills for deleted extensions
  const currentIds = extensions.map(e => e.id);
  const removed = [];

  if (fs.existsSync(PI_SKILLS_DIR)) {
    const existingSkills = fs.readdirSync(PI_SKILLS_DIR)
      .filter(d => d.startsWith('pi-'))
      .map(d => d.replace('pi-', ''));

    for (const skillId of existingSkills) {
      if (!currentIds.includes(skillId)) {
        // Extension was removed, delete skill
        const skillPath = path.join(PI_SKILLS_DIR, `pi-${skillId}`);
        fs.rmSync(skillPath, { recursive: true, force: true });
        removed.push(skillId);
      }
    }
  }

  // Update registry
  const registry = {
    lastSync: new Date().toISOString(),
    extensions: extensions.map(e => ({
      id: e.id,
      name: e.name,
      description: e.description,
      tools: e.tools,
      commands: e.commands,
      lastModified: e.lastModified
    }))
  };

  fs.writeFileSync(PI_REGISTRY_FILE, JSON.stringify(registry, null, 2));

  return {
    status: 'synced',
    extensions,
    added,
    updated,
    removed,
    totalTools: extensions.reduce((sum, e) => sum + e.tools.length, 0),
    totalCommands: extensions.reduce((sum, e) => sum + e.commands.length, 0)
  };
}

/**
 * Format sync result for session context
 */
function formatOutput(result) {
  if (result.status === 'no_extensions_dir' || result.status === 'no_extensions') {
    return null; // Silent - no Pi extensions to report
  }

  const lines = [];

  // Header
  lines.push('--- Pi Extensions ---');

  // Summary
  const extCount = result.extensions.length;
  lines.push(`${extCount} extension${extCount !== 1 ? 's' : ''} synced (${result.totalTools} tools, ${result.totalCommands} commands)`);

  // Changes
  if (result.added.length > 0) {
    lines.push(`  New: ${result.added.join(', ')}`);
  }
  if (result.updated.length > 0) {
    lines.push(`  Updated: ${result.updated.join(', ')}`);
  }
  if (result.removed.length > 0) {
    lines.push(`  Removed: ${result.removed.join(', ')}`);
  }

  // Quick reference for available tools
  if (result.extensions.length > 0) {
    lines.push('');
    lines.push('Available Pi tools:');
    for (const ext of result.extensions) {
      for (const tool of ext.tools) {
        lines.push(`  • ${tool.name} (${ext.id})`);
      }
    }
  }

  lines.push('---');

  return lines.join('\n');
}

// Main execution
try {
  const result = syncExtensions();
  const output = formatOutput(result);

  if (output) {
    // Output session context
    const hookOutput = {
      continue: true,
      hookSpecificOutput: {
        hookEventName: "SessionStart",
        additionalContext: '\n' + output + '\n'
      }
    };
    console.log(JSON.stringify(hookOutput));
  } else {
    // No output needed
    process.exit(0);
  }
} catch (e) {
  // Silently fail - don't block session start
  console.error('Pi extensions sync error:', e.message);
  process.exit(0);
}
