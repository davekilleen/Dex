# Connection Manager (catalog-hybrid)

Local-first OAuth + token management for Dex. **No Docker, no relay, no cloud.**

- **Provider config** comes from Nango's open-source catalog ([`@nangohq/providers`](https://www.npmjs.com/package/@nangohq/providers), ~831 providers) — consumed as *data only*.
- **Runtime** (OAuth2 + PKCE flow, refresh, health) is owned by Dex — plain Node built-ins, no heavy deps.
- **Tokens** live encrypted (AES-256-GCM) on-device under `{DEX_VAULT}/System/credentials/` and never leave the machine.

The engine code ships in Dex Core, but remains product-inert: no user-facing
`/connect` doorway is shipped or enabled.

## Files

| File | Role |
|------|------|
| `catalog.cjs` | Normalizes a Nango provider entry → Dex OAuth descriptor (URLs, scopes, PKCE, quirks). |
| `pinned-providers.cjs` | Frozen, Dex-reviewed HTTPS destination policy for vetted providers. |
| `oauth-flow.cjs` | PKCE auth-URL, localhost callback server (dynamic port), and code→token exchange. |
| `token-store.cjs` | Encrypted on-device token store + `connections.json` registry. Keychain-or-file key. |
| `health.cjs` | Connection health (`connected`/`expiring`/`expired`/`needs_reauth`) + the single lifted refresh/probe path. |
| `lib/oauth-refresh.js` | Desktop-proven refresh judgment: permanent/transient split, timeout, one retry, Retry-After clamp, Slack nesting, single-flight. |
| `lib/connector-verify.js` | Five-second Google, Slack, and Linear live probes; only 401/403-class evidence marks reconnect. |
| `lib/connector-ledger.js` | Secret-free per-connection evidence under `System/credentials/ledger/` (500-row cap, atomic rewrite). |
| `connect.cjs` | CLI: `connect` / `status [--json]` / `probe` / `refresh` / `disconnect` / `providers` / `authurl`. |
| `broker.cjs` / `broker-client.cjs` | Machine-local Unix-socket broker and client. Accessors request rendered or explicitly privileged credential views here instead of decrypting the store in their own process. |
| `presence.cjs` | B1 user-presence gate for raw exports and first connect, with a short in-process grant cache. |
| `get-token.cjs` | Contract-frozen accessor for Python MCP servers; all credential reads go through the broker. |
| `dex-call.cjs` | Generic authenticated caller; obtains rendered auth from the broker, then sends and redacts its own outbound request. |

## User-presence provider (B1)

Rendered authentication, default token access, and status checks never prompt,
so unattended sync keeps working. Raw `access-token` / `full` exports and the
first successful connect require verified user presence.

Real Touch ID is not implemented by a dialog or by JavaScript in this repo.
macOS requires an OS-signed app/helper for a genuine biometric prompt. The Dex
desktop app supplies that helper through `DEX_CM_PRESENCE_CMD`; the value is
argv-split and spawned directly without a shell. Exit 0 grants presence;
non-zero or timeout denies it.

Without a usable helper, the built-in macOS provider is honestly
`unavailable`, and privileged operations fail closed. Headless/CI environments
may explicitly set `DEX_CM_PRESENCE_OPTIONAL=1` to bypass an *unavailable*
provider; this prints a warning that presence was not verified. It never turns
an explicit denial into approval. Successful grants are cached in the broker
process per connection for 60 seconds by default
(`DEX_CM_PRESENCE_TTL_MS`; helper timeout:
`DEX_CM_PRESENCE_TIMEOUT_MS`, default 30 seconds).

## Maintainer smoke path

1. Register your **own** OAuth app (e.g. Google Cloud → OAuth client, type "Desktop app" or "Web" with redirect `http://127.0.0.1:3847/callback`).
2. Run `node connect.cjs register-app google` in a terminal. Dex visibly asks
   for the client id and hides the client secret while it is pasted. Automation
   can still pipe two lines (client id, then client secret). Never type a secret
   as part of the shell command itself.
3. Connect, then watch health:
   ```bash
   node connect.cjs connect google --scopes https://www.googleapis.com/auth/calendar.readonly,https://www.googleapis.com/auth/gmail.readonly
   node connect.cjs status
   node connect.cjs status --json
   node connect.cjs probe google
   node connect.cjs refresh google --force
   ```
4. From Python (MCP server):
   ```python
   import json, subprocess
   tok = subprocess.check_output(["node", "get-token.cjs", "google"])
   access_token = json.loads(tok)["access_token"]
   ```

## Failure modes (hardened 2026-06-10)

The store is designed so that nothing fails silently and nothing user-recoverable is ever destroyed:

| Failure | Behaviour |
|---------|-----------|
| Corrupt/truncated token file | Quarantined as `<name>.json.corrupt-<timestamp>` (never deleted), connection becomes `needs_reauth` with `error: token_file_corrupt`, the health sweep keeps going, `get-token`/`dex-call` exit 3 with a reconnect message. |
| Corrupt/missing/wiped registry | Quarantined as `connections.json.corrupt-<timestamp>` and rebuilt from the encrypted token files (provider, alias, scopes, expiry, auth mode recovered). `status` prints a visible warning with counts. `_defaults` is not recoverable; multi-account users may need to re-pick a default. |
| Crash mid-write | All writes (registry, tokens, key, oauth-apps, gitignore guard) are atomic temp+rename in the same directory via `fs-safe.cjs`; readers see old or new content, never a torn file. Permissions are re-applied on every write (0600 files / 0700 dirs). Leftover `.tmp` files are inert. |
| Never-commit guard cannot be installed or verified | Credential storage fails before writing a fallback key, token, registry, or OAuth secret. The guard is mandatory, not best-effort. |
| Two processes mutating at once | `.dex-cm.lock` (lockfile with PID + staleness: dead-PID steal, 30s unreadable, 10min hard cap; 10s acquire timeout that errors rather than running unlocked). Reads stay lock-free thanks to atomic writes. Same-machine scope only. |
| Two processes refreshing the same OAuth token | `.dex-cm.refresh-<conn>.lock` held across the network call; the loser re-checks freshness after acquiring and reuses the winner's token (safe for refresh-token rotation). |
| Provider redirects a credential-bearing request | OAuth exchange, OAuth refresh, verification probes, and generic authenticated calls reject redirects. Codes, refresh tokens, client secrets, and API-key headers are never replayed to a redirect target. |
| Catalog destination drifts away from a reviewed origin | Google and Linear credential-bearing requests fail closed before sending. Other catalog providers require explicit `--allow-unvetted` or `DEX_CM_ALLOW_UNVETTED=1` consent and are never auto-probed. |
| Registry or ledger trust data is edited or replayed | Registry entries, the store counter, and every ledger row are MAC-authenticated with a key derived from the credential master key. Entries with a missing/invalid MAC or a mismatched encrypted-credential digest are reported as `needs_reauth` / `trust_unverified`; unauthenticated or pre-reconnect probe rows cannot verify a credential. |
| Upgrade from an older unsigned `connections.json` | The unsigned entry is deliberately treated as `trust_unverified` and needs one reconnect. Reconnecting writes authenticated state; registry rebuilds from decryptable token files also create authenticated entries. |
| Credential is replaced after a prior successful probe | The durable ledger retains the historical proof, but verification starts a new connect epoch. The replacement credential is unverified until it passes its own live probe. |
| Encryption key missing/unreadable with encrypted credentials on disk | Explicit state, never silent re-keying: reads throw/report `encryption_key_lost` (computed at read time, nothing persisted, so a transient keychain blip self-heals). The one recovery path is reconnecting a tool, which preserves old token/app files as `*.keyloss-<timestamp>`, flags every other connection, prints why once, then issues a fresh key. |
| Credential file copied to another connection id | AES-GCM additional authenticated data binds every envelope to its connection id. The copied envelope is quarantined, and the target becomes `needs_reauth` with `token_envelope_account_mismatch`. |
| Secrets in logs | No CLI prints token material (refresh prints none; `dex-call` diagnostics are redacted via `auth-context.secretsOf`/`redactSecrets`). Exception by contract: `get-token` IS the credential accessor; consume it via the pp-* env-injection pattern, never echo it. |

The broker is an honest hardening boundary, not a same-user malware sandbox:
another process running as the same OS user can read user-owned `0600` files or
scrape a blessed consumer's memory. The broker removes routine in-process
decryption from accessors, centralises pinned-origin and trust checks, and puts
privileged `--full` / `--access-token-only` exports behind the Phase 5d
`assertPresence` seam. The default `get-token` operation remains unprivileged
and returns only the frozen OAuth or rendered Class-B contract shape.

Env switches: `DEX_CM_NO_KEYCHAIN=1` forces the file-based key (tests, sandboxes without `security`); `DEX_CM_RUNTIME_DIR` selects the machine-local broker runtime directory (tests use a unique temp directory); `DEX_CM_TEST_CRASH_BEFORE_RENAME=1` is test-only fault injection used by the crash-simulation test.

Tests: `npm run test:integrations` from the repository root (offline, throwaway temp vaults, fake fixtures only).

## Status

The original engine passed its live-account gate on 2026-07-24. Phase 2 adds Desktop's
judgment layer without changing the token accessor or encrypted-envelope
contracts: stored credentials show as connected but unverified until a live
probe succeeds, and only permanent refresh or 401/403-class probe evidence
marks a connection `needs_reauth`.

`status` and `verified` answer different questions in `status --json`:

- `verified: true` is durable evidence that the current credential epoch passed
  a live probe at least once. A later failure does not erase that historical proof.
- `status` is the connection's current health. A previously verified credential
  can therefore correctly show `verified: true` alongside
  `status: "needs_reauth"`.
- Consumers must gate credential use on `status`, not `verified`.

Phase 3 freezes the Desktop consumer contract and engine manifest. The
post-Phase-2/3 Google + Linear live rerun passed on 2026-07-24 (recorded on
PR #221); the remaining gate before any user-facing doorway ships is the
Phase 5 security review.

The held-back consumption surfaces remain outside this shipped engine:
`/connect`, `dex-google`, `gog-mcp-launch`, and `render-dashboard.cjs`. Do not
claim `/connect` until the complete doorway is implemented and tested.

## License note

`@nangohq/providers` is **Elastic License 2.0** (source-available). It is consumed as an npm dependency (not vendored). Keep the dependency's notices intact and do not re-expose the catalog as a managed service.
