---
name: connect
description: Connect, check and manage your app integrations — Google, Slack and Linear are reviewed and ready; hundreds more connect with an extra confirmation. OAuth or paste-a-key, tokens stored encrypted on your machine.
---

# Connect

Connect Dex to the apps you use, see what's working, and fix anything that's broken — all from one conversational command. Dex owns the OAuth runtime and stores every token **encrypted on your machine, never sent to a relay**.

Your sign-ins are **encrypted and kept on your machine** — never sent to our servers. Like other command-line tools that store logins, they are **not protected from other software running on your Mac as you**: a program running under your account could read them. That's the normal trade-off for a command-line tool, not a Dex-specific weakness. The **Dex desktop app closes this gap** when it ships — it adds a fingerprint check, and only the app can unlock the keys. Be honest about this if a user asks how safe their sign-ins are; never imply the command-line version can stop software already running as them, and never call it "secure", "safe", or "protected from malware".

This skill is a friendly driver over the connection manager CLI. You run the CLI verbs; you translate the output into plain language and clear next actions.

## What This Enables

`/connect` is the front door for every integration:

- **See what's connected** — a health sweep of all your connections, with each one mapped to a next action (reconnect, refresh, or nothing needed)
- **Connect a new app** — two paths:
  - **OAuth (Class A)** — Google, Slack, Atlassian, and most major apps. Authorize once in your browser; Dex remembers the login locally and auto-refreshes the token.
  - **Paste a key (Class B)** — Linear, GitHub PATs, and any API-key service. No OAuth app, no consent screen — just paste the secret.
- **Reconnect** — when a token is revoked or expires beyond refresh, re-run the OAuth flow
- **Disconnect** — remove a connection and delete its local token
- **Find a provider** — fuzzy-search 775 catalog entries by name; 627 can be connected today

The connection manager lives at:
`core/integrations/connection-manager/`

All commands below are run from the dex-core root (paths are relative to it).

## Privacy

- **Tokens are stored AES-256-GCM encrypted on-device** under `{DEX_VAULT}/System/credentials/` (the encryption key lives in macOS Keychain; non-Mac systems and explicitly configured test environments use a local key file).
- That directory is **gitignored** — credentials are never committed.
- **Nothing is sent to a relay.** Dex talks directly to the provider for authorization, token exchange, refresh, and any live check.
- The OAuth catalog (provider URLs, scopes, quirks) is consumed as **config data only** — it carries no credentials.
- `{DEX_VAULT}` means the vault configured by `DEX_VAULT` or `VAULT_PATH`. Dex stops and asks for a vault if neither is set; it does not guess a default folder.

## When to Run

- User types `/connect`
- User asks to connect, link, or set up an app (Gmail, Google Calendar, Slack, Linear, GitHub, Jira, etc.)
- User asks "what's connected?", "is my Google still working?", or "what needs reconnecting?"
- User asks to disconnect or remove an integration
- A `/daily-plan` heads-up nudge surfaced a `needs_reauth` or `expired` connection

---

## Setup Flow

### Step 0: Is It Already Available Through Claude? (Check This First)

**Before sending anyone through a Dex connection flow, check whether the tool is already reachable through Claude's own connectors.** If Dex is running inside Claude, the user (or their company) has very likely already approved connectors there — Calendar, Gmail, Drive, Slack, and more — and Dex can simply *use* them. They show up as available tools (e.g. `Google Calendar`, `Gmail`, `Google Drive`). There's nothing to connect: the consent already happened in Claude, the company already approved it, and no Dex token is needed.

So the best first move is to look at what's already there:

- If the tool the user wants is already available via a Claude connector → **use it directly. Don't run a connection flow.** Just tell them "Good news — your Calendar's already connected through Claude, so I can read it right now. Want me to take a look at your day?"
- If it's *not* available through Claude → that's when Dex's own connection manager earns its place (Steps 1–7 below).

**This Dex flow is for two audiences:** people using Dex **outside** Claude (where there are no Claude connectors), and people who want a tool their **company hasn't given them** through Claude. For everyone else inside Claude, the connectors they already have are the fastest path — lead with those.

When something genuinely needs connecting, use the gaps as a friendly prompt: *"I can see your Calendar and Gmail through Claude already. I can't see Slack — want to connect that one through Dex?"*

### Step 1: Check What's Already Connected

Run the health sweep (this covers Dex's *own* connections — the ones not coming from Claude):

```bash
node core/integrations/connection-manager/connect.cjs status
```

This first says whether the encryption key is in macOS Keychain or in the vault folder, then prints one row per connection with an icon and a status. The statuses are exactly:
`connected` · `expiring` · `expired` · `needs_reauth` · `not_connected`.

**Explain the key line only if it says "vault folder" — and be straight about it.** Keychain is the
normal case and needs no comment; mentioning it just adds noise. If the key is in the vault folder
(non-Mac machines, or where the Keychain isn't available), say what that actually means for them in
one sentence: the key sits in the same folder as the connections it unlocks, so anyone who gets a
copy of that folder — a backup, a synced Dropbox or iCloud copy, a borrowed laptop — can read those
sign-ins. Don't alarm them and don't bury it; it's a real difference and they can only account for
it if they know. If they ask what to do about it, the honest answer today is to keep that folder out
of shared or synced storage.

**Reformat the icon table into prose**, and map each status to its next action:

| Status | What it means | What you tell the user |
|--------|---------------|------------------------|
| `connected` | A saved credential is present and has no known problem | Nothing needed. If no live-check time is shown, say it has not been checked live yet. |
| `expiring` | Token expires soon | Nothing needed — auto-refresh handles it. (Optionally offer `refresh` if they want it now.) |
| `expired` | Token lapsed, refresh available | Offer `refresh`; if that fails permanently it becomes `needs_reauth` and must be reconnected |
| `needs_reauth` | The saved credential can no longer be used | **Reconnect required** — re-run OAuth, or paste the key again for a key-based connection |
| `not_connected` | No token stored | Offer to connect |

If a row says `needs_reauth (encryption_key_lost)`, Dex can still see the connection record but cannot unlock the saved credential. Tell the user to reconnect it. Reconnecting creates a fresh encryption key and keeps the old encrypted files with a `.keyloss-...` name for inspection; the other saved connections will also need reconnecting.

Example of how to render it:

```
Here's where your connections stand:

- Google — connected, checked just now
- Slack — needs reconnect (the token was revoked). Want me to reconnect it?
- Linear — connected (API key)

Everything else looks good.
```

If there are no connections yet, the CLI says so — pivot straight to "Which app would you like to connect?"

Group anything `needs_reauth` / `expired` at the top so the user sees what needs action first.

### Step 2: Figure Out What the User Wants

Branch based on intent:

- **"What's connected?" / status check** → you already answered it in Step 1. Stop here unless they want to act.
- **Connect a new app** → go to Step 3 (resolve the provider), then Step 4 (OAuth) or Step 5 (paste a key).
- **Reconnect a broken one** → use Step 4 for OAuth, or Step 5 to paste a fresh key for a key-based connection.
- **Disconnect** → Step 6.

### Step 3: Resolve the Provider Name (Fuzzy Match)

Users say "Google", "gmail", "my Linear" — resolve that to a real provider id before connecting.

For OAuth providers:

```bash
node core/integrations/connection-manager/connect.cjs providers <filter>
```

For API-key providers, include them too:

```bash
node core/integrations/connection-manager/connect.cjs providers --keys <filter>
```

Show the matches and confirm which one they mean. Each row shows the provider `id`, display name, and auth mode. The `id` is what you pass to `connect` / `set-key`.

Google, Slack, and Linear have passed Dex's security review. Other catalog providers are marked `advanced` and the CLI requires the user's explicit opt-in with `--allow-unvetted`; explain that plainly before using that flag. Browse-only providers cannot be connected yet.

If the match is unambiguous (one obvious hit), just confirm it inline rather than making them pick.

**Deciding the path:**
- If the provider's auth mode is OAuth → **Class A** (Step 4).
- If it's an API-key / basic-auth provider (appears under `--keys`) → **Class B** (Step 5).
- Not sure what a provider takes? `connect.cjs describe <id>` shows its auth mode, the secret it wants, and any required fields (subdomain/region/accountId…) before you start — handy for confirming the path and pre-empting what you'll need to ask the user.

### Step 4: Connect — Class A (OAuth)

OAuth services need an OAuth app (a client id + secret) to drive the flow. Check whether one already exists before asking the user to register anything.

**Google: Calendar is the simpler first scope; Gmail is more involved.** Dex does not ship a pre-registered Google OAuth app, so the user needs to register their own Google client unless they already saved one or supplied it through the environment. Calendar usually has a lighter setup and reading someone's day/week is a useful first connection. Gmail is a "restricted" scope in Google's eyes and carries extra verification steps, so treat it as a deliberate, later step rather than part of a quick first connect.

**4a. Check for an existing OAuth app.**
OAuth app credentials live in `{DEX_VAULT}/System/credentials/oauth-apps.json`, keyed by service. Dex does not bundle provider client credentials. If the user has already registered an app there, or supplied `DEX_OAUTH_<SERVICE>_CLIENT_ID` and `_CLIENT_SECRET`, you can connect straight away — skip to 4c.

**4b. Register an OAuth app (only if none exists) — YOU write the file, the user never edits it.**

The user must **never open or edit a config file**. You capture the two values in chat and save them for them with `register-app`:

1. Walk them through creating an OAuth client in the provider's developer console (pick "Desktop app" / "Installed" where offered). If they're stuck, point them at the provider's "OAuth app" / "API credentials" page — that's the most technical they ever get.
2. If the provider asks for redirect URIs, register the loopback callbacks the engine may choose: `http://127.0.0.1:3847/callback` through `http://127.0.0.1:3855/callback`, plus `http://127.0.0.1:3860/callback`. The engine uses the first free port. The authorization URL printed when connecting shows the exact `redirect_uri` chosen. A provider that requires `localhost` instead of `127.0.0.1` can use `DEX_OAUTH_CALLBACK_HOST=localhost`; register the matching `localhost` callbacks.
3. Ask them to **paste the client id, then the client secret** into the chat (the secret may be blank for public/PKCE clients).
4. **You** save them — read the two values from stdin so they never land in shell history:

   ```bash
   node core/integrations/connection-manager/connect.cjs register-app <service> <<'CREDS'
   <client-id>
   <client-secret>
   CREDS
   ```

   (Headless/dev alternative: `DEX_OAUTH_<SERVICE>_CLIENT_ID` / `_CLIENT_SECRET` env vars.)

If the user already has a usable OAuth app for that provider, capture its id/secret the same way. Then continue to 4c. **Never tell the user to edit `oauth-apps.json` by hand.**

**4c. Run the OAuth flow.**
Pick the scopes the user needs (least-privilege; for read-only context, prefer the `…readonly` scopes), then:

```bash
node core/integrations/connection-manager/connect.cjs connect <service> --scopes scope1,scope2,scope3
# Google example (shorthand is fine — see note):
node core/integrations/connection-manager/connect.cjs connect google --scopes gmail.readonly,calendar.readonly
```

**Scope shorthand:** pass scopes the way the provider names them. For Google you can use the short form (`gmail.readonly`, `calendar.readonly`, `drive.file`) — the connection manager expands them to the full `https://www.googleapis.com/auth/…` URLs Google's auth endpoint requires (`openid`/`email`/`profile` and any value you pass as a full URL are left as-is). Other providers (GitHub, Slack, …) use their bare scope names unchanged.

This opens the browser to the provider's consent screen and waits on the local loopback callback. On success the token is stored encrypted and you'll see a "Connected" confirmation.

**If it fails:**
- Browser didn't open → copy the URL printed in the output and open it manually.
- Consent not granted / wrong scopes → re-run with the right scopes.
- Callback rejected → read the `redirect_uri` in the printed authorization URL, then make sure that exact host, port, and `/callback` path is registered with the provider (4b, step 2).
- No refresh token came back → confirm the auth URL requests offline access:
  ```bash
  node core/integrations/connection-manager/connect.cjs authurl <service> --scopes …
  ```
  (look for `access_type=offline`). Retry up to twice, then offer to come back later.

Re-run `connect.cjs status` to confirm the new connection shows 🟢.

### Step 5: Connect — Class B (Paste a Key)

For API-key / token services there's no OAuth app and no consent screen — the user pastes a secret. But many are **host-scoped** (the API lives at `yourcompany.zendesk.com`, a specific region, a NetSuite account id, …), so find out exactly what the provider needs *before* asking for the key.

**5a. See what the provider needs.**

```bash
node core/integrations/connection-manager/connect.cjs describe <service>
```

`describe` prints the secret's name, the exact connect command to run, and — crucially — any **required fields** (subdomain, hostname, region, accountId…), each with a one-line hint and example. If it says *"Needs fields: none — a single API key is enough,"* go straight to the key.

**5b. Store the key (plus any required fields).**

The secret is read from **stdin** by default (so it never lands in shell history or argv). Pass each required field from `describe` as its own `--<field>` flag:

```bash
# Single-key service (most providers):
node core/integrations/connection-manager/connect.cjs set-key <service>

# Host-scoped service — supply the field(s) describe listed:
node core/integrations/connection-manager/connect.cjs set-key freshdesk --subdomain acme
node core/integrations/connection-manager/connect.cjs set-key active-campaign --hostname acme.api-us1.com
node core/integrations/connection-manager/connect.cjs set-key cin7-core --accountId 1234567
```

Have the user paste their key when prompted (it's read from stdin). For BASIC services like Freshdesk, pass `--username`; the password is read from the hidden prompt or stdin. Secret flags such as `--key` and `--password` are deliberately rejected so credentials do not appear in shell history or process listings.

**If a required field is missing, `set-key` refuses and names it** (e.g. *"ActiveCampaign needs connection detail: hostname"*) rather than saving a dead connection — so always `describe` first, or just read the error and re-run with the field.

On success the key is encrypted and stored exactly like an OAuth token. For security-reviewed providers, Dex runs a **live check** where it can: a reviewed verification endpoint can confirm the key or flag a rejected credential, while a generic check can only confirm and never condemn. Advanced providers are not auto-checked. Confirm with `connect.cjs status` — key connections show as `connected` or `connected (unverified)`; read "(unverified)" to the user as "not checked live yet", never as a safety statement (they don't expire or need refresh).

**Note on how consumers use it:** for an API-key service, the token accessor returns the rendered request recipe so callers don't re-implement the auth scheme:

```bash
node core/integrations/connection-manager/get-token.cjs <service>
# → { kind:'api_key', baseUrl, headers:{…rendered…}, query:{…} }
node core/integrations/connection-manager/get-token.cjs <service> --access-token-only
# → the raw secret
```

You normally don't run `get-token.cjs` during `/connect` — it's what other tools call to actually use the connection. Mention it only if the user asks how the key gets used.

### Step 6: Disconnect

To remove a connection and delete its local token:

```bash
node core/integrations/connection-manager/connect.cjs disconnect <service>
```

Confirm with the user first (this deletes the stored credential from this machine). After it runs, re-run `connect.cjs status` so they can see it's gone, and remind them they can reconnect anytime with `/connect`. Fully revoking the provider's access also requires removing Dex in the provider's own account settings. For a specific account, pass the connection id (`disconnect google:work`).

### Multiple accounts of one provider

A user can connect several accounts of the same provider (e.g. personal + work Gmail). Add `--as <alias>` (and `--default` to make it the one bare `google` resolves to):

```bash
node core/integrations/connection-manager/connect.cjs connect google --as work --default
node core/integrations/connection-manager/connect.cjs set-key linear --as personal
```

Each account is its own connection id — `google` (the default) and `google:work`. Bare `google` keeps resolving to the existing/default account, so nothing a user already connected ever changes. Refer to a specific one as `provider:alias` in `connect` / `set-key` / `get-token` / `disconnect`.

### Step 7: Confirm and Hand Off

After any connect / reconnect / disconnect, close the loop:

- Re-run `connect.cjs status` and report the new state in prose.
- For a fresh connection, say the saved credential is ready for Dex tools that use that provider.
- Remind them they can run `/connect` anytime to check status or manage connections.

---

## Reference: CLI Verbs

All under `core/integrations/connection-manager/`:

| Command | What it does |
|---------|--------------|
| `connect.cjs status` | Health sweep of all connections |
| `connect.cjs connect <svc> --scopes a,b,c [--as <alias>] [--default]` | Run the OAuth flow (Class A); `--as` connects a second account |
| `connect.cjs register-app <svc>` | Save an OAuth app's client id/secret (reads stdin: id then secret) — so the user never edits a file |
| `connect.cjs describe <svc>` | Show what a provider needs: secret, required fields, base URL, docs (run before `set-key`) |
| `connect.cjs set-key <svc> [--<field> v] [--as <alias>] [--default]` | Store a pasted API key (Class B; reads stdin). Host-scoping fields as `--subdomain`, etc.; `--as` for a 2nd account |
| `connect.cjs disconnect <svc>` | Delete a connection's local token (`<svc>` may be `provider` or `provider:alias`) |
| `connect.cjs refresh <svc> [--force]` | Refresh an expired or expiring token; `--force` refreshes even when it is still valid |
| `connect.cjs probe [<svc>]` | Run a bounded live check for one connection, or all connections when omitted |
| `connect.cjs providers [filter]` | List OAuth providers (add `--keys` to include API-key providers) |
| `connect.cjs coverage` | Paste-a-key coverage tiering — how many apps connect with just a key (answers "what can I connect?") |
| `connect.cjs authurl <svc> --scopes …` | Print the auth URL only (dry run, no browser) |
| `get-token.cjs <svc> [--access-token-only]` | Token accessor for consumers (exit 0 ok · 2 not connected · 3 needs re-auth · 1 error) |

**The registry** lives at `{DEX_VAULT}/System/credentials/connections.json` — one entry per service with `{ service, provider, authMode, status, scopes, expiresAt, connectedAt, lastRefreshedAt, lastUsedAt, error }`. You don't edit it by hand; the CLI maintains it.

---

## Troubleshooting

### "'<service>' has no OAuth app registered yet"

The provider needs a client id + secret that isn't saved yet. Do **not** tell the user to edit a file — follow Step 4b: capture the client id + secret in chat and run `register-app <service>` to save them for them.

### A connection flipped to `needs_reauth`

The saved credential can no longer be used. For OAuth this usually means the refresh token was revoked or expired; reconnect via Step 4 with the same scopes. For a key-based connection, follow Step 5 and paste a fresh key.

If the error is `encryption_key_lost`, the saved files are still present but Dex cannot unlock them. Reconnect the tool to create a fresh key; Dex preserves the old encrypted files as `.keyloss-...` instead of deleting them.

### Browser didn't open during connect

Copy the authorization URL printed in the command output and open it manually. Corporate networks sometimes block the loopback redirect — if so, the user may need to try from a personal network.

### Token works but a tool can't use the key

For API-key services, the auth scheme matters (some use `Bearer`, some `x-api-key`, some a query param, some no scheme at all). `get-token.cjs <service>` returns the **rendered headers and query** so consumers use the right scheme automatically — point tool authors at that JSON rather than hand-rolling the header.

---

## Reconfiguration

Running `/connect` again is always harmless — it starts with a status sweep (Step 1), so the user can review everything and choose to connect, reconnect, or disconnect from there. There's no separate "reconfigure" mode; the status-first flow covers it.
