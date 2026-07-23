# Consumption layer — how Dex *uses* a connected app

**Status:** active design, two threads building to it (2026-06-03).
**Audience:** anyone working on the connection manager, Printing Press CLIs, or `/connect`.

The connection manager's job ends at **"here's a fresh, authenticated way to call this app"** (`get-token.cjs`). What turns that into Dex actually reading/writing data is the **consumption layer**. There are two tiers, and the whole design is **floor + upgrade with graceful degradation**.

```
                       /connect <service>
                              │
                   ┌──────────┴───────────┐
                   │  pp-generate <service> │   ← try to build the rich tool
                   └──────────┬───────────┘
                   success ✓  │  fail ✗ (retries exhausted /
                              │         quality-gate fail / no API shape)
              ┌───────────────┴────────────┐
   UPGRADE →  │  Printing Press CLI         │   FLOOR → dex-call (generic caller)
              │  + MCP server + cache+search│          authenticated HTTP to ANY
              │  (rich, agent-native)       │          connected app, instantly
              └─────────────┬───────────────┘          └──────────┬─────────────┘
                            └──────── both pull a fresh token from ┘
                                      get-token.cjs (auto-refresh)
```

## The two tiers

**Upgrade — Printing Press (the primary, when it works).** `pp-generate <service>` runs Printing Press, which manufactures a dedicated CLI **plus an MCP server** (structured agent-native tools), with local SQLite caching and search. This is a first-class integration. It's a *build-time* pipeline (fetch/infer the API shape → generate → compile → verify → score), takes minutes, and can fail. Worth it for apps users lean on. Proven end-to-end: `pp-gmail` (live, reads Gmail via a connection-manager token each run).

**Floor — `dex-call` (the always-on fallback).** One thin tool that makes an authenticated request to **any** connected app, using `get-token`'s fresh token + the catalog's auth scheme. Shallow (raw HTTP/JSON), but **every connected app works through it the instant it's connected**, with zero per-app build. Covers the ~348 paste-key long tail and is the safety net for any app where Printing Press can't (yet) build a clean tool.

## The rules

1. **Nothing is ever stuck.** A `/connect` can't fail to produce *something usable*. If `pp-generate` fails after N retries — or can't pass the quality gate, or the app has no discoverable API shape — the service is registered against the **floor** and works immediately. (This is also the release-quality pressure valve: never ship an ungated Printing Press binary just to have *something* — ship the floor instead and keep the gate honest.)
2. **Prefer the upgrade.** To use service X, route to a built `pp-<X>` if one exists; otherwise use `dex-call X`. Routing happens at the *tool* level, not by retrying a failing build mid-request — generation is build-time, calls are run-time. Don't make a user wait on a compile to read data.
3. **One doorway.** Dex should always reach a connected app the same way; only the richness behind it differs. The floor is therefore also exposed as **one small generic MCP tool** ("call this connected app"), so an app on the floor and an app with a full Printing Press MCP server are both reachable through MCP — you just get more power when the rich version exists. *(MCP wrapper is a thin follow-on; the `dex-call` CLI is the core.)*
4. **One auth seam.** Both tiers get credentials the same way — `get-token.cjs` (paste-key → rendered `{baseUrl, headers, query}`; OAuth → fresh auto-refreshed token). Shared helper: `auth-context.cjs` `resolveAuthContext(service)`. Neither tier re-implements per-provider auth.

## Ownership (so the two threads don't collide)

| Piece | Owner |
|---|---|
| Printing Press + `pp-generate <service>` + the `/connect → generate` flow + per-app CLIs (Gmail, …) | the Printing Press thread |
| `dex-call` generic floor + `auth-context.cjs` + the graceful-degrade contract | the connection-manager thread |
| `get-token.cjs` (the shared seam) | shared — change deliberately, keep both tiers working |

## Open follow-ons
- Wrap the floor as a generic MCP tool (rule 3).
- `pp-generate` (PARKED, Printing Press thread): one-command "point at a spec → emit a `pp-<svc>` CLI". When it lands, verify it (a) takes a spec, (b) emits a thin `get-token`-injecting wrapper matching `~/.local/bin/pp-gmail`, (c) falls back to `dex-call` on build failure (rule 1).
  - **Verified quality-gate fix:** generation fails its `govulncheck` gate on go1.26.3. Fix = `go mod edit -go=1.26.4` + `go get golang.org/x/net@v0.55.0` + `go mod tidy`. Durable fix = bump the two template constants in Printing Press (`go.mod.tmpl`: `go 1.26.4`, `golang.org/x/net v0.55.0`) so a regenerate doesn't re-bake the old versions.

## Done (2026-06-03, before-dex-push handoff)
- **Multi-account** (provider / provider:alias, exact-match-wins, `_defaults`, `--as`/`--default`) — a second account never clobbers the first; refresh looks up the OAuth app by provider. (token-store, health, auth-context, dex-call, connect, render-dashboard.)
- **Credentials never committed** — store drops a `*` `.gitignore` into the credentials dir on first use (wherever DEX_VAULT points), plus `System/credentials/` in dex-core `.gitignore`.
- **Conversational OAuth-app onboarding** — `register-app` verb + `setOAuthApp` write `oauth-apps.json` from chat; `/connect` SKILL + `cmdConnect` error rewritten so the user never edits a file.
