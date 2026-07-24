# Connection-manager live-account gate — runbook + first-run results (2026-07-24)

The shipping gate for the connections engine (`core/integrations/connection-manager/`): prove
connect → use → break → detect → reconnect against REAL provider accounts. First run passed
2026-07-24 (Dave's accounts, engine at PR #209). Re-run this after any change to the OAuth flow,
refresh path, or token store — and always after Phase 2 of the one-brain program (the gate must
pass against the engine that actually ships).

## Setup

- Dedicated gate vault (never the live vault): `DEX_VAULT=~/dex/artifacts/cm-live-gate-vault`
- A Google OAuth client (type Desktop app) in any project the tester controls; Calendar API enabled;
  tester's account added as test user. Registered via `connect.cjs register-app google`
  (stdin only — the prompt is silent; type id ⏎ secret ⏎ Ctrl-D).
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

## Findings

1. **KNOWN GAP (scheduled — Phase 2 of the one-brain program): Class B has no ongoing health
   probe.** A dead Linear key keeps showing 🟢 connected until something calls it; `probeKey`
   honestly returns "skipped" (no Nango-authored verification endpoint for linear). Desktop's
   `connector-verify.js` probes (401/403-only-disconnect) are the fix; add a linear probe when
   they land. Until then, Class B status means "a key is stored", not "the key works".
2. **TRAP: Google's third-party-access list shows the CONSENT-SCREEN app name, not the OAuth
   client name.** A tester revoking "the app they created today" can revoke a different grant
   (we hit this: a June-era grant under the same name). The curl revoke endpoint is deterministic;
   prefer it for the break step.
3. **UX papercut (fix before Phase 5 ships /connect): `register-app`/`set-key` prompt silently.**
   A first-time user sees a blinking cursor, no instructions, and must know to press Ctrl-D.
   The /connect skill flow must wrap this (or the CLI should print prompts when stdin is a TTY).
4. Callback window is 5 minutes; a missed browser tab times out cleanly and is safely retryable.
