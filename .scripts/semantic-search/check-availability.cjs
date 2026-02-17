#!/usr/bin/env node
/**
 * Check if semantic search is available and functional.
 * 
 * Used by skills and hooks to decide search strategy:
 * - If available: use qmd for semantic search
 * - If not: fall back to grep/file search
 * 
 * Usage:
 *   node check-availability.cjs              # JSON output
 *   node check-availability.cjs --quiet      # Exit code only (0=available, 1=not)
 * 
 * As module:
 *   const { checkSemanticSearch } = require('./check-availability.cjs');
 *   const status = checkSemanticSearch();
 *   if (status.available) { ... }
 */

const { execSync } = require('child_process');

function checkSemanticSearch() {
  try {
    // Check if qmd binary exists
    execSync('which qmd', { stdio: 'pipe' });
  } catch {
    return {
      available: false,
      reason: 'qmd not installed. Run /enable-semantic-search to set up.',
      fallback: 'grep',
      collections: [],
      pendingEmbeddings: 0
    };
  }

  try {
    // Check if index exists and has content
    const output = execSync('qmd status', { stdio: 'pipe', encoding: 'utf-8' });

    // Parse collection names
    const collections = [];
    const collRegex = /^\s{2}(\w+)\s+\(qmd:\/\/\w+\/\)/gm;
    let match;
    while ((match = collRegex.exec(output)) !== null) {
      collections.push(match[1]);
    }

    // Parse document count
    const docsMatch = output.match(/Total:\s+(\d+)\s+files/);
    const totalDocs = docsMatch ? parseInt(docsMatch[1]) : 0;

    // Parse vector count
    const vecMatch = output.match(/Vectors:\s+(\d+)/);
    const totalVectors = vecMatch ? parseInt(vecMatch[1]) : 0;

    // Parse pending count
    const pendMatch = output.match(/Pending:\s+(\d+)/);
    const pendingEmbeddings = pendMatch ? parseInt(pendMatch[1]) : 0;

    if (totalDocs === 0) {
      return {
        available: false,
        reason: 'qmd installed but no files indexed. Run /enable-semantic-search.',
        fallback: 'grep',
        collections: [],
        pendingEmbeddings: 0
      };
    }

    return {
      available: true,
      message: `Semantic search ready: ${totalDocs} files, ${totalVectors} vectors, ${collections.length} collections`,
      collections,
      totalDocs,
      totalVectors,
      pendingEmbeddings,
      hasCollections: collections.length > 0,
      fallback: null
    };
  } catch (e) {
    return {
      available: false,
      reason: `qmd status failed: ${e.message}`,
      fallback: 'grep',
      collections: [],
      pendingEmbeddings: 0
    };
  }
}

// If run directly, output result
if (require.main === module) {
  const quiet = process.argv.includes('--quiet');
  const status = checkSemanticSearch();

  if (quiet) {
    process.exit(status.available ? 0 : 1);
  } else {
    console.log(JSON.stringify(status, null, 2));
  }
}

module.exports = { checkSemanticSearch };
