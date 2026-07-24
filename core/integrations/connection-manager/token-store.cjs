'use strict';
/**
 * token-store.cjs — On-device, encrypted credential store. Local-first: tokens
 * never leave the machine and never hit a relay.
 *
 * Layout (under {DEX_VAULT}/System/credentials/, which is gitignored):
 *   tokens/<connId>.json    AES-256-GCM v2 envelope { v, aad, iv, tag, data } (binary fields base64)
 *   connections.json        plaintext registry: status/scopes/timestamps (NO secrets)
 *   oauth-apps.json         plaintext client ids + encrypted client-secret envelopes
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
const { TOKEN_ENVELOPE_VERSION, LOCK_PROTOCOL } = require('./contract.cjs');

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

/** Live token files only (excludes quarantined *.corrupt-* / *.keyloss-* and .tmp leftovers). Read-only: never creates dirs. */
function listTokenFiles() {
  const dir = path.join(credentialsDir(), 'tokens');
  if (!fs.existsSync(dir)) return [];
  return fs.readdirSync(dir).filter((f) => f.endsWith('.json') && !f.startsWith('.'));
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

/**
 * Thrown when the encryption key is missing/unreadable while encrypted token
 * files exist. This is an EXPLICIT, recoverable-by-reauth state: the store
 * must never mint a fresh key behind the user's back (that would silently
 * orphan every saved token while everything looked fine).
 */
class KeyLossError extends Error {
  constructor(credentialCount, keyFoundButInvalid) {
    const n = `${credentialCount} saved encrypted credential${credentialCount === 1 ? '' : 's'}`;
    super(
      `Dex's encryption key is ${keyFoundButInvalid ? 'unreadable' : 'missing'} but ${n} exist. ` +
        'Saved credentials cannot be unlocked without it, so those connections need to be reconnected. ' +
        'Dex will not create a replacement key on its own; reconnecting any tool issues a fresh key ' +
        'and preserves the old encrypted files as *.keyloss-* for inspection.'
    );
    this.name = 'KeyLossError';
    this.code = 'DEX_CM_KEY_LOST';
    this.credentialCount = credentialCount;
  }
}

let _cachedKey = null;
/**
 * Get-or-create the 32-byte AES key. Prefers OS keychain; falls back to a 0600 file.
 *
 * Key loss is explicit: if no usable key can be found while encrypted token
 * files exist, this throws KeyLossError (code DEX_CM_KEY_LOST) instead of
 * generating a new key (the old behaviour, which orphaned every existing
 * token with no visible signal). A fresh key is only minted when there are no
 * tokens the old key protected, or via recoverFromKeyLoss().
 */
function getKey() {
  if (_cachedKey) return _cachedKey;
  let found = null;
  let lookupFailed = false;
  try {
    found = keyFromMacKeychain() || keyFromFile();
  } catch {
    lookupFailed = true; // unreadable key source counts as loss, not as "fresh start"
  }
  if (found && found.length === 32) {
    _cachedKey = found;
    return found;
  }
  const tokenCount = listTokenFiles().length;
  let encryptedAppFileCount = 0;
  const appsPath = oauthAppsPath();
  if (fs.existsSync(appsPath)) {
    try {
      const apps = JSON.parse(fs.readFileSync(appsPath, 'utf8'));
      encryptedAppFileCount = Object.values(apps).some((app) => app && app.clientSecret && app.clientSecret.v) ? 1 : 0;
    } catch {
      /* a corrupt app registry is not evidence that the missing key protected it */
    }
  }
  const credentialCount = tokenCount + encryptedAppFileCount;
  if (credentialCount > 0) throw new KeyLossError(credentialCount, Boolean(found) || lookupFailed);
  const key = crypto.randomBytes(32);
  const b64 = key.toString('base64');
  if (!storeKeyInMacKeychain(b64)) writeKeyFile(b64);
  _cachedKey = key;
  return key;
}

/**
 * Explicit recovery from key loss, invoked when the user RECONNECTS a tool
 * while the key is gone (never on a read path). Preserves every old token
 * file as *.keyloss-<timestamp> (they are undecryptable without the lost
 * key), quarantines an invalid key file if present, stamps every registry
 * entry needs_reauth with reason encryption_key_lost, and clears the key
 * cache so the next getKey() mints a fresh key. Returns how many connections
 * now need reconnecting.
 */
function recoverFromKeyLoss() {
  return withStoreLock(() => {
    const files = listTokenFiles();
    for (const f of files) quarantineFile(path.join(credentialsDir(), 'tokens', f), 'keyloss');
    const keyPath = path.join(credentialsDir(), '.dex-cm.key');
    if (fs.existsSync(keyPath)) quarantineFile(keyPath, 'keyloss');
    const appsPath = oauthAppsPath();
    if (fs.existsSync(appsPath)) quarantineFile(appsPath, 'keyloss');
    const reg = readRegistry();
    let stamped = 0;
    for (const k of Object.keys(reg)) {
      if (k === '_defaults' || k === '_meta' || !reg[k] || !reg[k].service) continue;
      reg[k] = { ...reg[k], status: 'needs_reauth', error: 'encryption_key_lost' };
      stamped++;
    }
    writeRegistry(reg);
    _cachedKey = null;
    return Math.max(stamped, files.length);
  });
}

/**
 * encrypt() for the save paths: a save is an explicit (re)connect, so if the
 * key is lost this recovers LOUDLY (preserve old token files, flag every
 * connection, print why once) and then proceeds with a fresh key, instead of
 * leaving the user wedged or doing anything silently.
 */
function encryptForSave(plaintext, aad) {
  try {
    return encrypt(plaintext, aad);
  } catch (err) {
    if (err && err.code === 'DEX_CM_KEY_LOST') {
      const n = recoverFromKeyLoss();
      console.error(
        `Dex's encryption key was missing, so a fresh one was created. ${n} previously saved connection(s) ` +
          'cannot be unlocked and need reconnecting (their token files were preserved as *.keyloss-*). ' +
          'Run: node connect.cjs status'
      );
      return encrypt(plaintext, aad);
    }
    throw err;
  }
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
  return withLock(refreshLockPath(connId), fn, { timeoutMs: LOCK_PROTOCOL.refreshTimeoutMs });
}

// ---- Encrypt / decrypt ------------------------------------------------------

class EnvelopeBindingError extends Error {
  constructor() {
    super('Encrypted credential belongs to a different account.');
    this.name = 'EnvelopeBindingError';
    this.code = 'DEX_CM_ENVELOPE_BINDING';
  }
}

function encrypt(plaintext, aad = '') {
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv('aes-256-gcm', getKey(), iv);
  cipher.setAAD(Buffer.from(aad, 'utf8'));
  const data = Buffer.concat([cipher.update(plaintext, 'utf8'), cipher.final()]);
  const tag = cipher.getAuthTag();
  return { v: TOKEN_ENVELOPE_VERSION, aad, iv: iv.toString('base64'), tag: tag.toString('base64'), data: data.toString('base64') };
}

function decrypt(envelope, aad = '') {
  if (!envelope || envelope.v !== TOKEN_ENVELOPE_VERSION) throw new Error('Unsupported encrypted credential envelope version.');
  if (envelope.aad !== aad) throw new EnvelopeBindingError();
  const decipher = crypto.createDecipheriv('aes-256-gcm', getKey(), Buffer.from(envelope.iv, 'base64'));
  decipher.setAAD(Buffer.from(aad, 'utf8'));
  decipher.setAuthTag(Buffer.from(envelope.tag, 'base64'));
  const out = Buffer.concat([decipher.update(Buffer.from(envelope.data, 'base64')), decipher.final()]);
  return out.toString('utf8');
}

// ---- Connection ids (multi-account) -----------------------------------------

/**
 * A connection id is `provider` or `provider:alias`. Bare `provider` is the
 * DEFAULT account for that provider (back-compat: existing tokens keep their id).
 * Aliases are lowercased; charset [a-z0-9_-]. Nango provider ids never contain ':'.
 *
 * The provider segment is charset-validated too: connection ids become token
 * FILENAMES (and the registry rebuild derives ids back from filenames), so a
 * hostile id like '../x' must never reach tokenPath and escape the tokens dir.
 */
function parseConnectionId(id) {
  const s = String(id);
  const i = s.indexOf(':');
  const provider = i === -1 ? s : s.slice(0, i);
  if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/.test(provider)) {
    throw new Error(`Invalid provider in connection id '${id}'. Use letters, digits, '.', '-' or '_' (must start with a letter or digit).`);
  }
  if (i === -1) return { provider: s, alias: null, connId: s };
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
    const matches = Object.keys(reg).filter((k) => k !== '_defaults' && k !== '_meta' && reg[k] && reg[k].provider === provider);
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
  // Encrypt BEFORE touching the registry: if the key is lost this triggers the
  // loud recovery first, so the entry we then upsert stays 'connected'.
  const envelope = JSON.stringify(encryptForSave(JSON.stringify(token), `token:${connId}`), null, 2);
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
    writeFileAtomic(tokenPath(connId), envelope, { mode: 0o600 });
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
  const envelope = JSON.stringify(encryptForSave(JSON.stringify(stored), `token:${service}`), null, 2); // key-loss recovery before registry writes; see saveToken
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
    upsertConnection(service, fields); // registry first; see saveToken
    writeFileAtomic(tokenPath(service), envelope, { mode: 0o600 });
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
 * deletes; the bytes are preserved for inspection/recovery. Returns the new
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
    return JSON.parse(decrypt(envelope, `token:${connId}`));
  } catch (err) {
    // Key loss is store-wide, not a damaged file: keep the (intact) token file
    // where it is and surface the explicit state to the caller instead.
    if (err && err.code === 'DEX_CM_KEY_LOST') throw err;
    withStoreLock(() => {
      const bindingMismatch = err && err.code === 'DEX_CM_ENVELOPE_BINDING';
      const quarantined = quarantineFile(p, bindingMismatch ? 'mismatch' : 'corrupt');
      const existing = readRegistry()[connId] || {};
      upsertConnection(connId, {
        provider: existing.provider || parseConnectionId(connId).provider,
        status: 'needs_reauth',
        error: bindingMismatch ? 'token_envelope_account_mismatch' : 'token_file_corrupt',
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

function hasServiceEntries(reg) {
  return Object.keys(reg).some((k) => k !== '_defaults' && k !== '_meta' && reg[k] && reg[k].service);
}

function isPlainObject(v) {
  return Boolean(v) && typeof v === 'object' && !Array.isArray(v);
}

/**
 * Read the connection registry. A damaged registry must NEVER silently reset
 * to empty (the old behaviour: every connection looked "not connected" and the
 * next write permanently discarded all other entries). Instead:
 *   - unparseable / non-object content, or a registry that lost its entries
 *     while token files still exist, or a missing file with tokens on disk,
 *     all trigger recovery: quarantine the damaged file (never delete) and
 *     rebuild entries from the surviving encrypted token files
 *   - the rebuilt registry carries a visible `_meta` warning that `status`
 *     surfaces to the user
 */
function readRegistry() {
  const p = registryPath();
  if (fs.existsSync(p)) {
    try {
      const reg = JSON.parse(fs.readFileSync(p, 'utf8'));
      if (isPlainObject(reg) && (hasServiceEntries(reg) || !listTokenFiles().length)) return reg;
    } catch {
      /* unparseable: fall through to recovery */
    }
  } else if (!listTokenFiles().length) {
    return {}; // genuine first run: nothing saved yet
  }
  return recoverRegistry();
}

/** Quarantine a damaged registry and rebuild it from the token files on disk. Idempotent and cross-process safe. */
function recoverRegistry() {
  return withStoreLock(() => {
    // Re-check inside the lock: another process may have recovered it already.
    const p = registryPath();
    let reason = 'registry_missing';
    let quarantinedName = null;
    if (fs.existsSync(p)) {
      try {
        const reg = JSON.parse(fs.readFileSync(p, 'utf8'));
        if (isPlainObject(reg)) {
          if (hasServiceEntries(reg) || !listTokenFiles().length) return reg;
          reason = 'registry_empty_with_tokens';
        } else {
          reason = 'registry_corrupt';
        }
      } catch {
        reason = 'registry_corrupt';
      }
      quarantinedName = quarantineFile(p, 'corrupt');
    }
    const rebuilt = rebuildRegistryFromTokens(reason, quarantinedName);
    writeRegistry(rebuilt);
    return rebuilt;
  });
}

/**
 * Rebuild registry entries from the encrypted token files (the tokens are the
 * source of truth; the registry is derivable metadata). Recovers provider,
 * alias, scopes, expiry and auth mode from each decryptable token; quarantines
 * undecryptable ones as corrupt. `_defaults` cannot be recovered (the user may
 * need to re-pick a default account for multi-account providers).
 * NOTE: reads token files directly; loadToken/resolveConnId would recurse into
 * readRegistry.
 */
function rebuildRegistryFromTokens(reason, quarantinedName) {
  const rebuilt = {};
  let recovered = 0;
  let unreadable = 0;
  for (const f of listTokenFiles()) {
    let parsed;
    try {
      parsed = parseConnectionId(f.replace(/\.json$/, '').replace(/__/g, ':'));
    } catch {
      continue; // foreign or hostile filename: leave the file alone, add no entry
    }
    const fp = path.join(credentialsDir(), 'tokens', f);
    const base = { service: parsed.connId, provider: parsed.provider, ...(parsed.alias ? { alias: parsed.alias } : {}) };
    let token;
    try {
      token = JSON.parse(decrypt(JSON.parse(fs.readFileSync(fp, 'utf8')), `token:${parsed.connId}`));
    } catch (err) {
      unreadable++;
      if (err && err.code === 'DEX_CM_KEY_LOST') {
        // The key is gone, not the file: keep the file untouched and mark the state.
        rebuilt[parsed.connId] = { ...base, status: 'needs_reauth', error: 'encryption_key_lost', recoveredAt: nowIso() };
      } else {
        const bindingMismatch = err && err.code === 'DEX_CM_ENVELOPE_BINDING';
        const q = quarantineFile(fp, bindingMismatch ? 'mismatch' : 'corrupt');
        rebuilt[parsed.connId] = {
          ...base,
          status: 'needs_reauth',
          error: bindingMismatch ? 'token_envelope_account_mismatch' : 'token_file_corrupt',
          corruptedAt: nowIso(),
          ...(q ? { corruptFile: q } : {}),
        };
      }
      continue;
    }
    let st = null;
    try {
      st = fs.statSync(fp);
    } catch {
      /* stat is best-effort */
    }
    const entry = {
      ...base,
      status: 'connected',
      scopes: token.scope ? String(token.scope).split(/[ ,]+/).filter(Boolean) : [],
      expiresAt: token.expires_at || token.expiry_date || null,
      connectedAt: token.obtained_at ? new Date(token.obtained_at).toISOString() : st ? st.birthtime.toISOString() : nowIso(),
      lastRefreshedAt: st ? st.mtime.toISOString() : nowIso(),
      error: null,
      recoveredAt: nowIso(),
    };
    if (token.kind === 'api_key') entry.authMode = token.username && token.password ? 'BASIC' : 'API_KEY';
    rebuilt[parsed.connId] = entry;
    recovered++;
  }
  rebuilt._meta = {
    notice: 'registry_rebuilt',
    reason,
    rebuiltAt: nowIso(),
    ...(quarantinedName ? { quarantinedRegistry: quarantinedName } : {}),
    recovered,
    unreadable,
  };
  return rebuilt;
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
    .filter(([k, v]) => k !== '_defaults' && k !== '_meta' && v && v.service)
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
  const app = apps[provider];
  if (!app) return null;
  return {
    clientId: app.clientId,
    clientSecret: decrypt(app.clientSecret, `oauth-app:${provider}`),
  };
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
  const encryptedSecret = encryptForSave(clientSecret, `oauth-app:${provider}`);
  return withStoreLock(() => {
    const p = oauthAppsPath();
    const apps = fs.existsSync(p) ? JSON.parse(fs.readFileSync(p, 'utf8')) : {};
    apps[provider] = { clientId, clientSecret: encryptedSecret };
    writeFileAtomic(p, JSON.stringify(apps, null, 2), { mode: 0o600 });
    return { clientId, clientSecret };
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
  KeyLossError,
  EnvelopeBindingError,
  recoverFromKeyLoss,
};
