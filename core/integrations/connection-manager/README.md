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
| `oauth-flow.cjs` | PKCE auth-URL, localhost callback server (dynamic port), and code→token exchange. |
| `token-store.cjs` | Encrypted on-device token store + `connections.json` registry. Keychain-or-file key. |
| `health.cjs` | Connection health (`connected`/`expiring`/`expired`/`needs_reauth`) + the single lifted refresh/probe path. |
| `lib/oauth-refresh.js` | Desktop-proven refresh judgment: permanent/transient split, timeout, one retry, Retry-After clamp, Slack nesting, single-flight. |
| `lib/connector-verify.js` | Five-second Google, Slack, and Linear live probes; only 401/403-class evidence marks reconnect. |
| `lib/connector-ledger.js` | Secret-free per-connection evidence under `System/credentials/ledger/` (500-row cap, atomic rewrite). |
| `connect.cjs` | CLI: `connect` / `status [--json]` / `probe` / `refresh` / `disconnect` / `providers` / `authurl`. |
| `get-token.cjs` | Accessor so Python MCP servers read fresh tokens without the encryption key. |

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
| Credential is replaced after a prior successful probe | The durable ledger retains the historical proof, but verification starts a new connect epoch. The replacement credential is unverified until it passes its own live probe. |
| Encryption key missing/unreadable with encrypted credentials on disk | Explicit state, never silent re-keying: reads throw/report `encryption_key_lost` (computed at read time, nothing persisted, so a transient keychain blip self-heals). The one recovery path is reconnecting a tool, which preserves old token/app files as `*.keyloss-<timestamp>`, flags every other connection, prints why once, then issues a fresh key. |
| Credential file copied to another connection id | AES-GCM additional authenticated data binds every envelope to its connection id. The copied envelope is quarantined, and the target becomes `needs_reauth` with `token_envelope_account_mismatch`. |
| Secrets in logs | No CLI prints token material (refresh prints none; `dex-call` diagnostics are redacted via `auth-context.secretsOf`/`redactSecrets`). Exception by contract: `get-token` IS the credential accessor; consume it via the pp-* env-injection pattern, never echo it. |

Env switches: `DEX_CM_NO_KEYCHAIN=1` forces the file-based key (tests, sandboxes without `security`); `DEX_CM_TEST_CRASH_BEFORE_RENAME=1` is test-only fault injection used by the crash-simulation test.

Tests: `npm run test:integrations` from the repository root (offline, throwaway temp vaults, fake fixtures only).

## Status

The original engine passed its live-account gate on 2026-07-24. Phase 2 adds Desktop's
judgment layer without changing the token accessor or encrypted-envelope
contracts: stored credentials show as connected but unverified until a live
probe succeeds, and only permanent refresh or 401/403-class probe evidence
marks a connection `needs_reauth`. Phase 3 freezes the Desktop consumer
contract and engine manifest. The post-Phase-2/3 Google + Linear rerun remains
the final manual gate before any user-facing doorway can ship.

The held-back consumption surfaces remain outside this shipped engine:
`/connect`, `dex-google`, `gog-mcp-launch`, and `render-dashboard.cjs`. Do not
claim `/connect` until the complete doorway is implemented and tested.

## License note

`@nangohq/providers` is **Elastic License 2.0** (source-available). It is consumed as an npm dependency (not vendored). Keep the dependency's notices intact and do not re-expose the catalog as a managed service.
