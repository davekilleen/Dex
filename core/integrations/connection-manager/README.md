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

## Status

Foundation built and smoke-tested (catalog resolution, PKCE auth-URL, encrypted token round-trip, health). **Not yet run against a live provider** — that needs your registered OAuth app. **Do not `dex-push`** until the break→detect→reconnect loop is verified on real accounts.

## License note

`@nangohq/providers` is **Elastic License 2.0** (source-available). It is consumed as an npm dependency (not vendored). Keep the dependency's notices intact and do not re-expose the catalog as a managed service.
