'use strict';

const fs = require('fs');
const path = require('path');

const DEFAULT_VAULT_ROOT = path.resolve(__dirname, '../../..');

function getGranolaApiKey({ env = process.env, vaultRoot = DEFAULT_VAULT_ROOT } = {}) {
  if (env.GRANOLA_API_KEY && env.GRANOLA_API_KEY.trim()) {
    return env.GRANOLA_API_KEY.trim();
  }

  try {
    const envPath = path.join(vaultRoot, '.env');
    if (!fs.existsSync(envPath)) return null;
    const raw = fs.readFileSync(envPath, 'utf-8');
    for (const line of raw.split('\n')) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith('#')) continue;
      const match = trimmed.match(/^GRANOLA_API_KEY\s*=\s*(.*)$/);
      if (match) {
        let value = match[1].trim();
        if ((value.startsWith('"') && value.endsWith('"')) ||
            (value.startsWith("'") && value.endsWith("'"))) {
          value = value.slice(1, -1);
        }
        return value.trim() || null;
      }
    }
  } catch (error) {
    // An unreadable .env means Granola is not configured for this run.
  }
  return null;
}

if (require.main === module) {
  process.exit(getGranolaApiKey({ vaultRoot: process.argv[2] }) ? 0 : 1);
}

module.exports = { getGranolaApiKey };
