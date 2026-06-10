'use strict';
/**
 * token-store.cjs — On-device, encrypted credential store. Local-first: tokens
 * never leave the machine and never hit a relay.
 *
 * Layout (under {DEX_VAULT}/System/credentials/, which is gitignored):
 *   tokens/<connId>.json    AES-256-GCM envelope { v, iv, tag, data } (base64)
 *   connections.json        plaintext registry: status/scopes/timestamps (NO secrets)
 *   oauth-apps.json         your own OAuth client id/secret per provider (gitignored)
 *   .dex-cm.key             fallback encryption key (0600) if OS keychain unavailable
 *   .gitignore              auto-written ('*') so a git-tracked vault never commits secrets
 *
 * Multi-account: a connection id is `provider` or `provider:alias`. Bare `provider`
 * is that provider's DEFAULT account; aliases let one provider hold several accounts
 * (e.g. google + google:work). Colon → `__` in token filenames.
 *
 * Encryption key resolution: macOS Keychain (`security`) → local key file fallback.
 * The Python MCP servers read tokens via `node get-token.cjs <conn>` rather than
 * decrypting themselves, so the key never has to be shared cross-language.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');
const crypto = require('crypto');
const { execFileSync } = require('child_process');
const { writeFileAtomic, withLockSync, withLock } = require('./fs-safe.cjs');

const KEYCHAIN_SERVICE = 'dex-connection-manager';
const KEYCHAIN_ACCOUNT = 'token-store-key';

/** Resolve the credentials directory: $DEX_VAULT/System/credentials, else ~/Vault/... */
function credentialsDir() {
  const vault = process.env.DEX_VAULT || path.join(os.homedir(), 'Vault');
  return path.join(vault, 'System', 'credentials');
}

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  if (dir === credentialsDir()) ensureCredentialsGitignore(dir);
}

// The credentials dir must ignore EVERYTHING — tokens, the registry, oauth-app secrets, AND the
// fallback AES key `.dex-cm.key` (present on machines without an OS keychain) — wherever DEX_VAULT
// points. A narrower legacy rule like `*.json` misses the key file, so we don't just create-if-absent:
// we UPGRADE any .gitignore that doesn't already ignore everything (a bare `*` line). README.md and
// the .gitignore itself stay tracked.
function ensureCredentialsGitignore(dir) {
  const gi = path.join(dir, '.gitignore');
  let cur = '';
  try {
    cur = fs.existsSync(gi) ? fs.readFileSync(gi, 'utf8') : '';
  } catch {
    /* unreadable — fall through and (re)write */
  }
  if (!/^\*\s*$/m.test(cur)) {
    try {
      writeFileAtomic(gi, '# Dex connection manager — never commit credentials (tokens, keys, OAuth secrets).\n*\n!.gitignore\n!README.md\n', { mode: 0o600 });
    } catch {
      /* best-effort: never block a save on the guard */
    }
  }
}

function tokensDir() {
  const dir = path.join(credentialsDir(), 'tokens');
  ensureDir(credentialsDir()); // ensure the .gitignore guard exists before any token lands
  ensureDir(dir);
  return dir;
}

// ---- Encryption key ---------------------------------------------------------

// DEX_CM_NO_KEYCHAIN=1 forces the file-based key. Used by tests (so they never
// touch the user's real keychain entry) and useful in sandboxes where the
// `security` binary is unavailable or blocked.
function keychainDisabled() {
  return process.env.DEX_CM_NO_KEYCHAIN === '1';
}

function keyFromMacKeychain() {
  if (process.platform !== 'darwin' || keychainDisabled()) return null;
  try {
    const out = execFileSync(
      'security',
      ['find-generic-password', '-s', KEYCHAIN_SERVICE, '-a', KEYCHAIN_ACCOUNT, '-w'],
      { stdio: ['ignore', 'pipe', 'ignore'] }
    )
      .toString()
      .trim();
    return out ? Buffer.from(out, 'base64') : null;
  } catch {
    return null; // not found
  }
}

function storeKeyInMacKeychain(keyB64) {
  if (process.platform !== 'darwin' || keychainDisabled()) return false;
  try {
    execFileSync(
      'security',
      ['add-generic-password', '-s', KEYCHAIN_SERVICE, '-a', KEYCHAIN_ACCOUNT, '-w', keyB64, '-U'],
      { stdio: 'ignore' }
    );
    return true;
  } catch {
    return false;
  }
}

function keyFromFile() {
  const keyPath = path.join(credentialsDir(), '.dex-cm.key');
  if (fs.existsSync(keyPath)) return Buffer.from(fs.readFileSync(keyPath, 'utf8').trim(), 'base64');
  return null;
}

function writeKeyFile(keyB64) {
  ensureDir(credentialsDir());
  const keyPath = path.join(credentialsDir(), '.dex-cm.key');
  writeFileAtomic(keyPath, keyB64, { mode: 0o600 });
}

let _cachedKey = null;
/** Get-or-create the 32-byte AES key. Prefers OS keychain; falls back to a 0600 file. */
function getKey() {
  if (_cachedKey) return _cachedKey;
  let key = keyFromMacKeychain() || keyFromFile();
  if (!key || key.length !== 32) {
    key = crypto.randomBytes(32);
    const b64 = key.toString('base64');
    if (!storeKeyInMacKeychain(b64)) writeKeyFile(b64);
  }
  _cachedKey = key;
  return key;
}

// ---- Cross-process locking ----------------------------------------------------
// See fs-safe.cjs for the full lock semantics (lockfile + PID staleness + timeout).

function storeLockPath() {
  return path.join(credentialsDir(), '.dex-cm.lock');
}

function refreshLockPath(connId) {
  return path.join(credentialsDir(), `.dex-cm.refresh-${String(connId).replace(/:/g, '__')}.lock`);
}

/**
 * Serialize store MUTATIONS (registry read-modify-write + token file writes)
 * across processes. Reads stay lock-free: every file is written atomically, so
 * a reader always sees a complete old or new version. Hold times are
 * milliseconds; acquisition errors out after 10s rather than proceeding unlocked.
 */
function withStoreLock(fn) {
  return withLockSync(storeLockPath(), fn);
}

/**
 * Serialize an OAuth REFRESH for one connection across processes, held across
 * the network round-trip (so providers with refresh-token rotation never see
 * two competing refreshes, which would invalidate one side). Waiters poll
 * without blocking the event loop; after acquiring, callers re-check token
 * freshness so a second process reuses the winner's result instead of
 * refreshing again. 30s timeout covers a slow token endpoint.
 */
function withRefreshLock(connId, fn) {
  return withLock(refreshLockPath(connId), fn, { timeoutMs: 30_000 });
}

// ---- Encrypt / decrypt ------------------------------------------------------

function encrypt(plaintext) {
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', getKey(), iv);
  const data = Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return { v: 1, iv: iv.toString('base64'), tag: tag.toString('base64'), data: data.toString('base64') };
}

function decrypt(envelope) {
  const decipher = crypto.createDecipheriv('aes-256-gcm', getKey(), Buffer.from(envelope.iv, 'base64'));
  decipher.setAuthTag(Buffer.from(envelope.tag, 'base64'));
  const out = Buffer.concat([decipher.update(Buffer.from(envelope.data, 'base64')), decipher.final()]);
  return out.toString('utf8');
}

// ---- Connection ids (multi-account) -----------------------------------------

/**
 * A connection id is `provider` or `provider:alias`. Bare `provider` is the
 * DEFAULT account for that provider (back-compat: existing tokens keep their id).
 * Aliases are lowercased; charset [a-z0-9_-]. Nango provider ids never contain ':'.
 */
function parseConnectionId(id) {
  const s = String(id);
  const i = s.indexOf(':');
  if (i === -1) return { provider: s, alias: null, connId: s };
  const provider = s.slice(0, i);
  const alias = s.slice(i + 1).toLowerCase();
  if (!/^[a-z0-9_-]+$/.test(alias)) throw new Error(`Invalid connection alias in '${id}'. Use letters, digits, '-' or '_'.`);
  return { provider, alias, connId: `${provider}:${alias}` };
}

/**
 * Resolve a caller-supplied id (which may be a bare provider) to a concrete
 * connId in the registry. Exact match ALWAYS wins, so bare `google` keeps hitting
 * the existing default. For a bare id with no exact entry: an explicit default
 * pointer, else the sole account of that provider, else throw on ambiguity.
 * Write paths do NOT resolve — they create the connId verbatim.
 */
function resolveConnId(id) {
  const reg = readRegistry();
  const { provider, alias } = parseConnectionId(id);
  if (reg[id] && reg[id].service) return id; // exact match wins (back-compat)
  if (!alias) {
    const def = reg._defaults && reg._defaults[provider];
    if (def && reg[def]) return def;
    const matches = Object.keys(reg).filter((k) => k !== '_defaults' && reg[k] && reg[k].provider === provider);
    if (matches.length === 1) return matches[0];
    if (matches.length > 1) {
      throw new Error(`Multiple '${provider}' accounts: ${matches.join(', ')}. Pick one (e.g. ${matches[0]}) or set a default: connect ${provider} --as <alias> --default`);
    }
  }
  return parseConnectionId(id).connId; // unknown — loadToken will return null ("not connected")
}

// ---- Token CRUD -------------------------------------------------------------

function tokenPath(connId) {
  // Colon is hostile to some filesystem tooling; map it to a reserved separator.
  return path.join(tokensDir(), `${String(connId).replace(/:/g, '__')}.json`);
}

/** Persist a token object (encrypted) and refresh the registry entry. `connId` may be `provider` or `provider:alias`. */
function saveToken(connId, token, meta = {}) {
  const parsed = parseConnectionId(connId);
  return withStoreLock(() => {
    const fields = {
      provider: meta.provider || parsed.provider,
      status: 'connected',
      scopes: token.scope ? String(token.scope).split(/[ ,]+/).filter(Boolean) : meta.scopes || [],
      expiresAt: token.expires_at || token.expiry_date || null,
      connectedAt: meta.connectedAt || nowIso(),
      lastRefreshedAt: nowIso(),
      error: null,
      ...meta.extra,
    };
    if (parsed.alias) fields.alias = parsed.alias;
    // Registry first, then the token file: a crash in between leaves a registry
    // entry with no token (harmless "not connected"), never a token file with no
    // registry entry (which would look like registry data loss).
    upsertConnection(connId, fields);
    writeFileAtomic(tokenPath(connId), JSON.stringify(encrypt(JSON.stringify(token)), null, 2), { mode: 0o600 });
    return token;
  });
}

/**
 * Persist a Class-B (paste-a-key) secret. Reuses the exact encrypt/saveToken path
 * as OAuth tokens — the encrypted envelope on disk is shape-agnostic. The stored
 * object is tagged { kind:'api_key' } so get-token/health can branch without a
 * network/refresh round-trip.
 *
 * @param service   connection id (provider, or provider:alias for a second account)
 * @param secretObj { apiKey } or { username, password }, plus optional baseUrl/connectionConfig
 * @param meta      { provider, scopes, connectedAt, extra }
 */
function saveApiKey(service, secretObj, meta = {}) {
  const stored = { kind: 'api_key', ...secretObj, obtained_at: Date.now() };
  const parsed = parseConnectionId(service);
  return withStoreLock(() => {
    const fields = {
      provider: meta.provider || parsed.provider,
      authMode: meta.authMode || 'API_KEY',
      status: 'connected',
      scopes: meta.scopes || [],
      expiresAt: null,
      connectedAt: meta.connectedAt || nowIso(),
      lastRefreshedAt: nowIso(),
      error: null,
      ...meta.extra,
    };
    if (parsed.alias) fields.alias = parsed.alias;
    upsertConnection(service, fields); // registry first — see saveToken
    writeFileAtomic(tokenPath(service), JSON.stringify(encrypt(JSON.stringify(stored)), null, 2), { mode: 0o600 });
    return stored;
  });
}

/** Record that a token was just read/used (drives the Connected_Apps lastUsedAt column). */
function touchUsed(id) {
  const connId = resolveConnId(id);
  return withStoreLock(() => {
    if (!readRegistry()[connId]) return null;
    return upsertConnection(connId, { lastUsedAt: nowIso() });
  });
}

/**
 * Quarantine a damaged file: rename it next to its original path with a reason
 * and timestamp (e.g. google.json.corrupt-2026-06-10T12-00-00-000Z). NEVER
 * deletes — the bytes are preserved for inspection/recovery. Returns the new
 * basename, or null if even the rename failed (recovery proceeds regardless).
 */
function quarantineFile(p, reason) {
  try {
    const stamp = new Date().toISOString().replace(/[:.]/g, '-');
    let dest = `${p}.${reason}-${stamp}`;
    if (fs.existsSync(dest)) dest += `-${crypto.randomBytes(2).toString('hex')}`;
    fs.renameSync(p, dest);
    return path.basename(dest);
  } catch {
    return null;
  }
}

/**
 * Load and decrypt a token object, or null if not connected. Resolves bare ids
 * to the default account.
 *
 * A corrupt/truncated/undecryptable token file never throws and never takes
 * anything else down: the file is quarantined (renamed *.corrupt-<timestamp>,
 * never deleted), the connection is stamped needs_reauth with a clear reason,
 * and null is returned. Health reads surface the reason; the rest of the store
 * keeps working.
 */
function loadToken(id) {
  const connId = resolveConnId(id);
  const p = tokenPath(connId);
  if (!fs.existsSync(p)) return null;
  try {
    const envelope = JSON.parse(fs.readFileSync(p, 'utf8'));
    return JSON.parse(decrypt(envelope));
  } catch (err) {
    withStoreLock(() => {
      const quarantined = quarantineFile(p, 'corrupt');
      const existing = readRegistry()[connId] || {};
      upsertConnection(connId, {
        provider: existing.provider || parseConnectionId(connId).provider,
        status: 'needs_reauth',
        error: 'token_file_corrupt',
        corruptedAt: nowIso(),
        ...(quarantined ? { corruptFile: quarantined } : {}),
      });
    });
    return null;
  }
}

function deleteToken(id) {
  const connId = resolveConnId(id);
  return withStoreLock(() => {
    const p = tokenPath(connId);
    if (fs.existsSync(p)) fs.unlinkSync(p);
    const reg = readRegistry();
    delete reg[connId];
    const { provider } = parseConnectionId(connId);
    if (reg._defaults && reg._defaults[provider] === connId) {
      delete reg._defaults[provider];
      if (!Object.keys(reg._defaults).length) delete reg._defaults;
    }
    writeRegistry(reg);
  });
}

// ---- Connection registry (connections.json) ---------------------------------

function registryPath() {
  return path.join(credentialsDir(), 'connections.json');
}

function readRegistry() {
  const p = registryPath();
  if (!fs.existsSync(p)) return {};
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch {
    return {};
  }
}

function writeRegistry(reg) {
  ensureDir(credentialsDir());
  writeFileAtomic(registryPath(), JSON.stringify(reg, null, 2), { mode: 0o600 });
}

function upsertConnection(service, fields) {
  return withStoreLock(() => {
    const reg = readRegistry();
    reg[service] = { ...(reg[service] || {}), service, ...fields };
    writeRegistry(reg);
    return reg[service];
  });
}

function listConnections() {
  return Object.entries(readRegistry())
    .filter(([k, v]) => k !== '_defaults' && v && v.service)
    .map(([, v]) => v);
}

/** Set the default account for a provider (used when a bare id is otherwise ambiguous). */
function setDefault(provider, alias) {
  return withStoreLock(() => {
    const reg = readRegistry();
    reg._defaults = reg._defaults || {};
    reg._defaults[provider] = alias ? `${provider}:${alias}` : provider;
    writeRegistry(reg);
    return reg._defaults[provider];
  });
}

function getDefault(provider) {
  const reg = readRegistry();
  return (reg._defaults && reg._defaults[provider]) || null;
}

/** Resolve an id (bare or aliased) and return its registry entry, or null. */
function getConnection(id) {
  return readRegistry()[resolveConnId(id)] || null;
}

// ---- OAuth app credentials (your own registered apps) -----------------------

function oauthAppsPath() {
  return path.join(credentialsDir(), 'oauth-apps.json');
}

/** Read this user's own OAuth client id/secret for a provider. */
function getOAuthApp(provider) {
  // Env override wins (handy for headless/dev): DEX_OAUTH_<PROVIDER>_CLIENT_ID / _CLIENT_SECRET
  const envId = process.env[`DEX_OAUTH_${provider.toUpperCase().replace(/-/g, '_')}_CLIENT_ID`];
  const envSecret = process.env[`DEX_OAUTH_${provider.toUpperCase().replace(/-/g, '_')}_CLIENT_SECRET`];
  if (envId) return { clientId: envId, clientSecret: envSecret || '' };
  const p = oauthAppsPath();
  if (!fs.existsSync(p)) return null;
  const apps = JSON.parse(fs.readFileSync(p, 'utf8'));
  return apps[provider] || null;
}

/**
 * Write a provider's OAuth client id/secret into oauth-apps.json — so the /connect skill
 * can capture them conversationally and the user NEVER hand-edits the file. Keyed by
 * provider (the OAuth app is shared across that provider's accounts). Public clients
 * (PKCE, no secret) pass clientSecret: ''.
 */
function setOAuthApp(provider, { clientId, clientSecret = '' }) {
  if (!clientId) throw new Error('setOAuthApp requires a clientId.');
  ensureDir(credentialsDir());
  return withStoreLock(() => {
    const p = oauthAppsPath();
    const apps = fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : {};
    apps[provider] = { clientId, clientSecret };
    writeFileAtomic(p, JSON.stringify(apps, null, 2), { mode: 0o600 });
    return apps[provider];
  });
}

function nowIso() {
  // Date is fine in runtime code (only banned inside Workflow scripts).
  return new Date().toISOString();
}

module.exports = {
  credentialsDir,
  parseConnectionId,
  resolveConnId,
  withStoreLock,
  withRefreshLock,
  saveToken,
  saveApiKey,
  touchUsed,
  loadToken,
  deleteToken,
  listConnections,
  setDefault,
  getDefault,
  getConnection,
  upsertConnection,
  readRegistry,
  getOAuthApp,
  setOAuthApp,
  encrypt,
  decrypt,
};
