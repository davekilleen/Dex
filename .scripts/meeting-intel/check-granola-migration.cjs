#!/usr/bin/env node

/**
 * Check if user needs Granola MCP migration.
 * Called during session start or /process-meetings to detect upgrade opportunity.
 *
 * Exit codes:
 *   0 = no action needed (already authenticated, or Granola not in use)
 *   1 = migration available (new MCP code exists but no OAuth tokens)
 *   2 = tokens expired (need re-auth)
 */

const fs = require('fs');
const path = require('path');
const os = require('os');

const TOKEN_FILE = path.join(os.homedir(), '.config', 'dex', 'granola-tokens.json');
const MCP_CLIENT = path.join(__dirname, 'granola-mcp-client.cjs');
const GRANOLA_CACHE = (() => {
  const platform = os.platform();
  const home = os.homedir();
  if (platform === 'darwin') return path.join(home, 'Library/Application Support/Granola/cache-v3.json');
  if (platform === 'win32') return path.join(process.env.APPDATA || path.join(home, 'AppData/Roaming'), 'Granola/cache-v3.json');
  return path.join(home, '.config/Granola/cache-v3.json');
})();

// Check if user uses Granola at all
const usesGranola = fs.existsSync(GRANOLA_CACHE);
if (!usesGranola) {
  // Granola not installed — no migration needed
  console.log(JSON.stringify({ status: 'not_applicable', reason: 'Granola not installed' }));
  process.exit(0);
}

// Check if new MCP client code exists
const hasMcpClient = fs.existsSync(MCP_CLIENT);
if (!hasMcpClient) {
  // Old code, hasn't been updated yet
  console.log(JSON.stringify({ status: 'not_applicable', reason: 'MCP client not installed yet' }));
  process.exit(0);
}

// Check if tokens exist
const hasTokens = fs.existsSync(TOKEN_FILE);
if (!hasTokens) {
  // New code exists but no tokens — migration available
  console.log(JSON.stringify({
    status: 'migration_available',
    message: 'Granola now supports mobile recordings. Sign in once to enable.',
    auth_command: 'node .scripts/meeting-intel/granola-auth.cjs --setup'
  }));
  process.exit(1);
}

// Check if tokens are expired
try {
  const tokens = JSON.parse(fs.readFileSync(TOKEN_FILE, 'utf-8'));
  const now = Math.floor(Date.now() / 1000);
  const expiresAt = tokens.expires_at || 0;
  const hasRefresh = !!tokens.refresh_token;

  if (expiresAt < now && !hasRefresh) {
    // Expired with no refresh token
    console.log(JSON.stringify({
      status: 'token_expired',
      message: 'Granola authentication has expired. Sign in again to continue syncing mobile recordings.',
      auth_command: 'node .scripts/meeting-intel/granola-auth.cjs --setup'
    }));
    process.exit(2);
  }

  // All good
  console.log(JSON.stringify({ status: 'authenticated', expires_at: tokens.expires_at }));
  process.exit(0);
} catch (e) {
  console.log(JSON.stringify({
    status: 'token_error',
    message: 'Granola token file is corrupted. Sign in again.',
    auth_command: 'node .scripts/meeting-intel/granola-auth.cjs --setup'
  }));
  process.exit(2);
}
