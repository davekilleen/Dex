#!/usr/bin/env node
'use strict';

const fs = require('node:fs');
const path = require('node:path');

const START_MARKER = '## USER_EXTENSIONS_START';
const END_MARKER = '## USER_EXTENSIONS_END';
const JOURNAL_RELATIVE = path.join('System', '.dex', 'migration-v2-state.json');

function extensionBlock(source) {
  const startPattern = /^## USER_EXTENSIONS_START[^\r\n]*(?:\r?\n|$)/m;
  const start = startPattern.exec(source);
  if (!start) throw new Error(`CLAUDE.md is missing ${START_MARKER}`);

  const afterStart = start.index + start[0].length;
  const endPattern = /^## USER_EXTENSIONS_END[^\r\n]*(?:\r?\n|$)/m;
  const end = endPattern.exec(source.slice(afterStart));
  if (!end) throw new Error(`CLAUDE.md is missing ${END_MARKER}`);
  const endIndex = afterStart + end.index;
  return {
    before: source.slice(0, start.index),
    startLine: start[0],
    content: source.slice(afterStart, endIndex),
    endLine: end[0],
    after: source.slice(endIndex + end[0].length),
  };
}

function extractLegacyExtensions(source) {
  return extensionBlock(source).content;
}

function emptyLegacyExtensionBlock(source) {
  const block = extensionBlock(source);
  return `${block.before}${block.startLine}${block.endLine}${block.after}`;
}

function regenerateClaude(template, customContent) {
  const block = extensionBlock(template);
  return `${block.before}${customContent}${block.after}`;
}

function fsyncDirectory(directory) {
  let descriptor;
  try {
    descriptor = fs.openSync(directory, 'r');
    fs.fsyncSync(descriptor);
  } finally {
    if (descriptor !== undefined) fs.closeSync(descriptor);
  }
}

function writeFileFsynced(destination, content, mode = 0o600) {
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  const temporary = `${destination}.writing-${process.pid}`;
  let descriptor;
  try {
    descriptor = fs.openSync(temporary, 'w', mode);
    fs.writeFileSync(descriptor, content);
    fs.fsyncSync(descriptor);
  } finally {
    if (descriptor !== undefined) fs.closeSync(descriptor);
  }
  fs.renameSync(temporary, destination);
  fsyncDirectory(path.dirname(destination));
}

function journalPath(root) {
  return path.join(root, JOURNAL_RELATIVE);
}

function writeJournal(root, state) {
  const destination = journalPath(root);
  const previous = `${destination}.previous`;
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  if (fs.existsSync(destination)) {
    const current = fs.readFileSync(destination);
    writeFileFsynced(previous, current);
  }
  writeFileFsynced(destination, `${JSON.stringify(state, null, 2)}\n`);
}

function readJournal(root) {
  const destination = journalPath(root);
  for (const [candidate, recovered] of [[destination, false], [`${destination}.previous`, true]]) {
    try {
      const state = JSON.parse(fs.readFileSync(candidate, 'utf8'));
      if (recovered) state.recoveredFromPrevious = true;
      return state;
    } catch (error) {
      if (!['ENOENT', 'EISDIR'].includes(error.code) && !(error instanceof SyntaxError)) throw error;
    }
  }
  return null;
}

function topologyDecision(topology) {
  const {
    rootGit,
    vaultStaging,
    brainGit,
    archiveGit,
    rootIsVault,
  } = topology;

  if (!rootGit && !vaultStaging && !brainGit && !archiveGit) return 'zip';
  if (archiveGit) {
    if (brainGit && vaultStaging) return 'continue-swap';
    if (rootGit && rootIsVault && brainGit) return 'post-split';
    return 'restore-archive';
  }
  if (rootGit) return 'pre-split';
  return 'invalid';
}

module.exports = {
  emptyLegacyExtensionBlock,
  extractLegacyExtensions,
  readJournal,
  regenerateClaude,
  topologyDecision,
  writeJournal,
};

if (require.main === module) {
  console.error('The migration phase runner is not available yet.');
  process.exitCode = 2;
}
