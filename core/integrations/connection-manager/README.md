# Connection Manager (catalog-hybrid)

Local-first OAuth + token management for Dex. **No Docker, no relay, no cloud.**

- **Provider config** comes from Nango's open-source catalog ([`@nangohq/providers`](https://www.npmjs.com/package/@nangohq/providers), ~831 providers) — consumed as *data only*.
- **Runtime** (OAuth2 + PKCE flow, refresh, health) is owned by Dex — plain Node built-ins, no heavy deps.
- **Tokens** live encrypted (AES-256-GCM) on-device under `{DEX_VAULT}/System/credentials/` and never leave the machine.

See the decision record: `Vault/System/PRDs/dex-integrations-suite.md` § Decision Reopened (2026-06-01).

## Files

| File | Role |
|------|------|
| `catalog.cjs` | Normalizes a Nango provider entry → Dex OAuth descriptor (URLs, scopes, PKCE, quirks). |
| `oauth-flow.cjs` | PKCE auth-URL, localhost callback server (dynamic port), code→token exchange, refresh. |
| `token-store.cjs` | Encrypted on-device token store + `connections.json` registry. Keychain-or-file key. |
| `health.cjs` | Connection health (`connected`/`expiring`/`expired`/`needs_reauth`) + refresh state machine. |
| `connect.cjs` | CLI: `connect` / `status` / `refresh` / `disconnect` / `providers` / `authurl`. |
| `get-token.cjs` | Accessor so Python MCP servers read fresh tokens without the encryption key. |

## Quick start (prototype)

1. Register your **own** OAuth app (e.g. Google Cloud → OAuth client, type "Desktop app" or "Web" with redirect `http://127.0.0.1:3847/callback`).
2. Add credentials to `{DEX_VAULT}/System/credentials/oauth-apps.json`:
   ```json
   { "google": { "clientId": "…", "clientSecret": "…" } }
   ```
3. Connect, then watch health:
   ```bash
   node connect.cjs connect google --scopes https://www.googleapis.com/auth/calendar.readonly,https://www.googleapis.com/auth/gmail.readonly
   node connect.cjs status
   node connect.cjs refresh google
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
| Two processes mutating at once | `.dex-cm.lock` (lockfile with PID + staleness: dead-PID steal, 30s unreadable, 10min hard cap; 10s acquire timeout that errors rather than running unlocked). Reads stay lock-free thanks to atomic writes. Same-machine scope only. |
| Two processes refreshing the same OAuth token | `.dex-cm.refresh-<conn>.lock` held across the network call; the loser re-checks freshness after acquiring and reuses the winner's token (safe for refresh-token rotation). |
| Encryption key missing/unreadable with tokens on disk | Explicit state, never silent re-keying: reads throw/report `encryption_key_lost` (computed at read time, nothing persisted, so a transient keychain blip self-heals). The one recovery path is reconnecting a tool, which preserves old token files as `*.keyloss-<timestamp>`, flags every other connection, prints why once, then issues a fresh key. |
| Secrets in logs | No CLI prints token material (refresh prints none; `dex-call` diagnostics are redacted via `auth-context.secretsOf`/`redactSecrets`). Exception by contract: `get-token` IS the credential accessor; consume it via the pp-* env-injection pattern, never echo it. |

Env switches: `DEX_CM_NO_KEYCHAIN=1` forces the file-based key (tests, sandboxes without `security`); `DEX_CM_TEST_CRASH_BEFORE_RENAME=1` is test-only fault injection used by the crash-simulation test.

Tests: `node --test connection-manager.test.cjs connection-manager.hardening.test.cjs` from this directory (40 happy-path/policy + 28 failure-mode tests; offline, throwaway temp vault, fake fixtures only).

## Status

Foundation built and smoke-tested (catalog resolution, PKCE auth-URL, encrypted token round-trip, health), plus the corruption/concurrency/key-loss hardening pass above. **Not yet run against a live provider** — that needs your registered OAuth app. **Do not `dex-push`** until the break→detect→reconnect loop is verified on real accounts.

## License note

`@nangohq/providers` is **Elastic License 2.0** (source-available). It is consumed as an npm dependency (not vendored). Keep the dependency's notices intact and do not re-expose the catalog as a managed service.
