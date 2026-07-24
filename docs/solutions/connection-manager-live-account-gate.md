# Connection-manager live-account gate — runbook + first-run results (2026-07-24)

The shipping gate for the connections engine (`core/integrations/connection-manager/`): prove
connect → use → break → detect → reconnect against REAL provider accounts. The first run passed
2026-07-24 with tester-owned accounts on the PR #209 engine. Re-run this after any change to the
OAuth flow, refresh path, token store, or health judgment. The post-Phase-2/3 Google + Linear rerun
is still outstanding and must pass against the exact engine intended to ship.

The engine code ships in Core, but the product doorway does not: `/connect` is not implemented or
published. This runbook is a maintainer gate, not user-facing setup.

## Setup

- Dedicated gate vault (never the live vault): `DEX_VAULT=/path/to/dedicated/cm-live-gate-vault`
- A Google OAuth client (type Desktop app) in any project the tester controls; Calendar API enabled;
  tester's account added as test user. Register via `connect.cjs register-app google`: an
  interactive terminal visibly asks for the client id and hides the secret. Automation may pipe
  id + secret on separate lines.
- A Linear personal API key for Class B.

## The battery (Class A — OAuth, run the loop TWICE)

1. `connect google --scopes .../calendar.readonly` → browser PKCE flow (5-min callback window).
2. `status` → 🟢 connected.
3. `get-token.cjs google` → default output must contain ONLY access_token + expires_at (exit 0).
4. `dex-call.cjs google /calendar/v3/users/me/calendarList` → real data.
5. `refresh google --force` → network refresh succeeds.
6. Encrypted-at-rest: token file is a v2 envelope `{v:2, aad:"token:google", iv, tag, data}`,
   no plaintext token substrings.
7. BREAK: revoke the grant. UI path: myaccount.google.com/connections → the app (named by the
   project's CONSENT SCREEN, not the client — see trap below). Deterministic path:
   `curl -X POST https://oauth2.googleapis.com/revoke -d "token=<refresh_token>"` (HTTP 200).
8. `refresh google --force` → must FAIL with `invalid_grant` (exit 1);
   `status` → 🔴 needs_reauth (invalid_grant); `get-token` → exit 3.
9. `dex-call` while broken → refuses with "needs re-authentication. Run: connect google".
10. RECONNECT: `connect google` again → 🟢, data flows.

## Class B (paste-a-key — Linear)

1. `set-key linear` (stdin only) → probe → 🟢.
2. `dex-call.cjs linear /graphql POST --body '{"query":"{ viewer { name } }"}'` → real identity.
3. Encrypted-at-rest: v2 envelope, aad `token:linear`, no `lin_api` substring.
4. `get-token.cjs linear` → rendered request envelope (kind api_key + headers), never the raw key.
5. BREAK: delete the key in Linear → API returns 401 AUTHENTICATION_ERROR.
6. RECONNECT: new key via `set-key linear` → data flows.

## First-run results (2026-07-24)

- Class A: full loop passed TWICE consecutively. Break detection exact: forced refresh → 400
  invalid_grant → needs_reauth stamped → get-token exit 3 → honest refusal downstream.
- Class B: loop passed once (creation probe + live read + break + reconnect).
- Multi-account live test SKIPPED — isolation is covered by the offline suite
  (`connection-manager.test.cjs` multi-account tests); exercise live when a second real account
  is convenient.

## Current Phase 2/3 state

1. **Resolved in Phase 2:** Google, Slack, and Linear use bounded live probes with durable,
   secret-free evidence. A stored credential remains visibly unverified until a probe succeeds;
   Doctor does not report it healthy.
2. **TRAP: Google's third-party-access list shows the CONSENT-SCREEN app name, not the OAuth
   client name.** A tester revoking "the app they created today" can revoke a different grant
   (we hit this: a June-era grant under the same name). The curl revoke endpoint is deterministic;
   prefer it for the break step.
3. **Resolved in the maintainer CLI:** `register-app` and `set-key` now show clear terminal
   prompts and hide secrets. Non-interactive stdin remains available for automation.
4. Callback window is 5 minutes; a missed browser tab times out cleanly and is safely retryable.
5. **Still outstanding:** repeat the complete Google loop twice and the Linear loop once against
   the post-Phase-2/3 engine. Do not use the earlier #209 result as evidence for later judgment code.
6. **Still held:** `/connect` is not shipped or claimable until its complete product doorway is
   implemented and tested separately.
