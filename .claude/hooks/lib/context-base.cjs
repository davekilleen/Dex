#!/usr/bin/env node
/**
 * Shared base for context injector hooks (person + company).
 * Handles stdin parsing, file validation, binary skip, vault path resolution,
 * index building, reference matching, and output formatting.
 */
const fs = require('fs');
const path = require('path');

const DEBUG_SKIP = process.env.DEX_HOOK_DEBUG === '1';

function skip(reason) {
  if (DEBUG_SKIP) {
    console.error(`[dex-hook-skip] ${reason}`);
  }
  process.exit(0);
}

const SKIP_EXTS = new Set([
  '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.ico', '.svg',
  '.pdf', '.zip', '.tar', '.gz', '.mp3', '.mp4', '.mov', '.wav',
  '.pptx', '.xlsx', '.docx'
]);

/**
 * Parse stdin, validate the file path, and return { filePath, fullFilePath, content, vaultRoot, paths }.
 * Calls process.exit(0) (skip) if the file should not be processed.
 *
 * @param {Object} opts
 * @param {string[]} opts.recursionMarkers - Path segments that indicate recursion (e.g. ['/People/'])
 * @returns {{ filePath: string, fullFilePath: string, content: string, vaultRoot: string, paths: object }}
 */
function parseAndValidate(opts) {
  let input;
  try {
    input = JSON.parse(fs.readFileSync(0, 'utf-8'));
  } catch (e) {
    skip('invalid-json-input');
  }

  const filePath = input.tool_input?.path || input.tool_input?.file_path || '';

  if (!filePath) skip('missing-file-path');

  for (const marker of (opts.recursionMarkers || [])) {
    if (filePath.includes(marker)) skip(`recursive:${marker}`);
  }

  const ext = path.extname(filePath).toLowerCase();
  if (SKIP_EXTS.has(ext)) skip(`unsupported-extension:${ext}`);

  const { loadPaths } = require('../paths.cjs');
  const paths = loadPaths();
  const vaultRoot = paths.VAULT_ROOT || process.env.CLAUDE_PROJECT_DIR || process.env.VAULT_PATH || process.cwd();

  const fullFilePath = filePath.startsWith('/') ? filePath : path.join(vaultRoot, filePath);
  if (!fs.existsSync(fullFilePath)) skip(`target-file-not-found:${fullFilePath}`);

  const content = fs.readFileSync(fullFilePath, 'utf-8');

  return { filePath, fullFilePath, content, vaultRoot, paths };
}

/**
 * Scan directories for .md files and build a name→path index.
 *
 * @param {string[]} dirs - Directories to scan
 * @param {Object} opts
 * @param {boolean} [opts.recursive=false] - Whether to scan subdirectories
 * @returns {Record<string, string>} Map of lowercase name variants to absolute file paths
 */
function buildIndex(dirs, opts = {}) {
  const index = {};

  function scan(dirPath) {
    if (!fs.existsSync(dirPath)) return;
    try {
      const entries = fs.readdirSync(dirPath, { withFileTypes: true });
      for (const entry of entries) {
        const fullPath = path.join(dirPath, entry.name);
        if (entry.isDirectory() && opts.recursive) {
          scan(fullPath);
        } else if (entry.name.endsWith('.md')) {
          const baseName = entry.name.replace('.md', '');
          const normalized = baseName.toLowerCase();
          const spaced = baseName.replace(/_/g, ' ').toLowerCase();
          const dashed = baseName.replace(/-/g, ' ').toLowerCase();
          index[normalized] = fullPath;
          index[spaced] = fullPath;
          if (dashed !== spaced) index[dashed] = fullPath;
        }
      }
    } catch (e) { /* skip unreadable dirs */ }
  }

  for (const dir of dirs) scan(dir);
  return index;
}

/**
 * Find references in content by file path patterns and (optionally) by name matching.
 *
 * @param {string} content - File content to search
 * @param {Record<string, string>} entityIndex - Name→path index
 * @param {Object} opts
 * @param {RegExp} opts.fileRefPattern - Regex to match file path references (capture group 1 = entity name)
 * @param {string[]} [opts.contextKeywords] - If content contains any of these, also do name matching
 * @param {number} [opts.minNameLength=0] - Minimum name length for direct matching
 * @param {boolean} [opts.requireMultiWord=false] - Only match names with spaces/underscores
 * @returns {Set<string>} Set of matched file paths
 */
function findReferences(content, entityIndex, opts) {
  const found = new Set();
  const contentLower = content.toLowerCase();

  // Method 1: File path references
  let match;
  while ((match = opts.fileRefPattern.exec(content)) !== null) {
    const name = match[1].toLowerCase();
    if (entityIndex[name]) found.add(entityIndex[name]);
  }

  // Method 2: Name matching (only in relevant context)
  if (opts.contextKeywords) {
    const hasContext = opts.contextKeywords.some(kw => contentLower.includes(kw));
    if (hasContext) {
      for (const name of Object.keys(entityIndex)) {
        if (opts.minNameLength && name.length <= opts.minNameLength) continue;
        if (opts.requireMultiWord && !name.includes(' ') && !name.includes('_')) continue;
        const spacedName = name.replace(/_/g, ' ').replace(/-/g, ' ');
        if (contentLower.includes(spacedName)) {
          found.add(entityIndex[name]);
        }
      }
    }
  }

  return found;
}

/**
 * Format context lines and output the hook result.
 *
 * @param {string} xmlTag - XML wrapper tag name (e.g. 'person_context')
 * @param {string} label - Header label (e.g. 'Referenced people:')
 * @param {string[]} bodyLines - Formatted context lines for each entity
 */
function outputContext(xmlTag, label, bodyLines) {
  if (bodyLines.length === 0) skip(`${xmlTag}-empty`);

  const contextLines = [`<${xmlTag}>`, label, ...bodyLines, `</${xmlTag}>`];
  const output = {
    continue: true,
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      additionalContext: '\n' + contextLines.join('\n')
    }
  };
  console.log(JSON.stringify(output));
}

module.exports = { skip, parseAndValidate, buildIndex, findReferences, outputContext };
