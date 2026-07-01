---
name: adobe-esign-setup
description: Connect Adobe Acrobat Sign to Dex for sending documents out for e-signature, tracking status, and downloading signed PDFs
integration:
  id: adobe_sign
  name: Adobe Acrobat Sign
  mcp_server: adobe
  auth: oauth2
  category: documents
  sync_direction: bidirectional
  enhances:
    - skill: salesforce-quote-email
      capability: "Send the generated quote PDF out for e-signature instead of just emailing it"
    - skill: pipeline-review
      capability: "Surface agreements awaiting signature alongside open opportunities"
  new_capabilities:
    - name: Send for Signature
      trigger: "Upload any PDF (a quote, contract, order form) and send it to one or more signers"
    - name: Status Tracking
      trigger: "Ask 'has Acme signed the quote yet?' to check agreement status and per-signer progress"
    - name: PDF Tools
      trigger: "Local PDF utilities (merge, split, extract pages, read/fill form fields) work immediately, no Adobe account needed"
---

# Adobe eSign & PDF Setup

Connect Adobe Acrobat Sign to Dex so you can send documents out for e-signature, check who still needs to sign, send reminders, and pull down the completed PDF — all without leaving the conversation.

This skill also unlocks local PDF tools (info, text extraction, merge/split, form-field read & fill) that work with **no Adobe account at all** — useful for prepping a document before it goes out for signature.

## What This Enables

**Without any setup (PDF tools only):**
- Get page count, metadata, and form-field info for any PDF
- Extract text from a PDF (e.g. read a contract before sending it out)
- Merge multiple PDFs into one packet, or split one into individual pages
- Extract a page range into a new file
- Read and fill AcroForm fields

**Once connected (Adobe Sign):**
- **Send for Signature:** Upload a PDF and send it to one or more signers, in parallel or in sequence
- **Status Tracking:** Check whether an agreement is out for signature, signed, or still pending — and who specifically hasn't signed yet
- **Reminders:** Nudge signers who haven't completed their part
- **Cancel:** Void an agreement if it's no longer needed
- **Download:** Pull the completed, signed PDF back into the vault

**Skill Enhancements:**
- **Quote emails** (`/salesforce-quote-email`) can send the generated quote out for e-signature instead of (or in addition to) emailing it as an attachment
- **Pipeline review** (`/pipeline-review`) can surface agreements still awaiting a signature alongside open opportunities

## Privacy

Adobe Sign access uses OAuth 2.0 — Dex never sees your Adobe password. The OAuth app's client ID and secret are stored in a gitignored `.env` file at your vault root; the resulting access/refresh tokens are stored outside the repo entirely, at `~/.claude/adobe_sign_tokens.json`. Only documents you explicitly send through Dex are touched — nothing in your existing Adobe Sign account is scanned or imported.

## When to Run

- User types `/adobe-esign-setup`
- User asks about e-signatures, Adobe Sign, or DocuSign-style workflows
- User wants to send a quote or contract out for signature
- During `/integrate-mcp` if Adobe Sign is mentioned

---

## Setup Flow

> Throughout this flow, **Dex performs every file action for the user**. Never ask the user to open, create, or hand-edit `.env` or any other file. They only ever paste values into the chat — Dex does the rest.

### Step 0: Offer the PDF-only Path First

If the user's goal is just PDF manipulation (merge, split, extract, fill a form) and they haven't mentioned e-signatures, tell them they don't need this setup at all:

```
The PDF tools (info, text extraction, merge/split, form fields) work right
now with no setup — just ask. You only need this setup if you want to send
documents out for e-signature through Adobe Acrobat Sign.

Want to connect Adobe Sign, or are the PDF tools enough for now?
```

If they want e-signature, continue below.

### Step 1: Check if Already Connected

1. Check `System/integrations/config.yaml` for an `adobe_sign` section with `enabled: true`.
2. If present, call the `adobe_sign_check_connection` tool.
   - If it reports `connected: true`, skip to **Step 6** (Reconfiguration / what's enabled).
   - If it reports `connected: false`, the token is stale or credentials changed — continue to Step 2.
3. If no config section exists, continue to Step 2.

### Step 2: Explain What We're Setting Up

```
**Let's connect Adobe Acrobat Sign to Dex.**

This needs an Acrobat Sign account with permission to create an integration
("application") — usually available on Individual, Team, or Business/Enterprise
plans. About 5 minutes, most of it in the Adobe Sign admin console.

**What you'll need:**
- An Adobe Acrobat Sign account
- Access to Account Settings > Adobe Sign API > API Applications

**What gets connected:**
- Sending PDFs out for signature
- Checking agreement status and signer progress
- Reminders, cancellation, and downloading signed documents

**Ready to go?**
```

Wait for confirmation.

### Step 3: Walk Them Through Creating an OAuth Application

Guide them step by step:

```
Let's register Dex as an application in Adobe Sign:

1. Sign in to Adobe Acrobat Sign, then go to
   **Account > Adobe Sign API > API Applications**.
2. Click **Add Access** (or "Create New Integration Key" on older accounts)
   and choose **OAuth Application**.
3. Name it something like "Dex".
4. Set the **Redirect URI** to exactly:
   http://localhost:8722/callback
5. Grant these scopes:
   - user_login (self)
   - agreement_read (account)
   - agreement_write (account)
   - agreement_send (account)
6. Save, then copy the **Client ID** and **Client Secret** it generates.

Also note which **data center / shard** your account is on — it's visible
in your Adobe Sign URL, e.g. https://secure.na1.adobesign.com/... means
your shard is "na1". (na1, na2, na3, eu1, eu2, au1, jp1, in1, ca1 are the
common ones.)
```

If the user isn't sure whether their plan supports API applications, let them know that Individual/Solo plans typically don't — Business or Enterprise is required. They can confirm by checking whether "API Applications" appears under Account settings at all.

### Step 4: Collect Credentials

Ask for each value one at a time, or all at once if the user pastes them together:

```
Paste your Adobe Sign Client ID, Client Secret, and shard (e.g. "na1").
I'll store them locally and never commit them.
```

### Step 5: Store Credentials and Authenticate

**Store it (Dex does this — not the user):**

1. Locate the vault root `.env` file (`VAULT_ROOT/.env`). Create it if it doesn't exist.
2. Write or update these lines (replace if they already exist, otherwise append):
   ```
   ADOBE_SIGN_CLIENT_ID=<pasted client id>
   ADOBE_SIGN_CLIENT_SECRET=<pasted client secret>
   ADOBE_SIGN_SHARD=<pasted shard, e.g. na1>
   ```
3. Confirm `.env` is gitignored (it is by convention — never commit it).
4. These same values also need to reach the `adobe` MCP server process. Update the `env` block in `.claude/mcp/adobe.json` only if the user's MCP client doesn't already substitute `${ADOBE_SIGN_CLIENT_ID}` / `${ADOBE_SIGN_CLIENT_SECRET}` / `${ADOBE_SIGN_SHARD}` from the environment — most clients do this automatically once the `.env` is loaded or the vars are exported.

**Authenticate:**

Call the `adobe_sign_authenticate` tool. This opens a browser window for the user to sign in to Adobe and approve access; a short-lived local web server on port 8722 catches the redirect.

```
Opening your browser to sign in to Adobe Sign...
```

- **On success:** the tool returns `connected: true`.
  ```
  Connected — Adobe Sign is linked to Dex.
  ```
  Continue to Step 6.

- **On failure** (timeout, denied, wrong redirect URI): explain the likely cause and offer to retry:
  ```
  That didn't connect. Common causes:
  - The Redirect URI in your Adobe Sign application isn't exactly
    http://localhost:8722/callback
  - The browser window was closed before approving access
  - Client ID/Secret were mistyped

  Want to try again, or re-check the application settings in Adobe Sign?
  ```
  Retry up to 2 times, then offer to come back later.

### Step 6: Save Configuration

Write to `System/integrations/config.yaml` — update (or add) the `adobe_sign` section. Preserve all other integration configs.

```yaml
adobe_sign:
  enabled: true
  configured_at: YYYY-MM-DD
  auth_type: oauth2
  shard: na1
  client_id_env_var: ADOBE_SIGN_CLIENT_ID   # values live in VAULT_ROOT/.env, never here
  client_secret_env_var: ADOBE_SIGN_CLIENT_SECRET
```

Never write the client secret or tokens into `config.yaml` or any committed file — only env var names. Secrets live solely in the gitignored `.env`; OAuth tokens live outside the repo at `~/.claude/adobe_sign_tokens.json`.

### Step 7: Confirm with Capability Cascade

```
Adobe Sign is connected!

Here's what just got enabled:

- **Send for Signature** — upload any PDF and send it to signers
- **Status Tracking** — "has [person] signed yet?" checks live status
- **Reminders & Cancellation** — nudge or void an agreement
- **Download** — pull the completed, signed PDF back into the vault

Try it: "Send [file] to [email] for signature."

You can re-run /adobe-esign-setup anytime to rotate credentials or disconnect.
```

---

## Troubleshooting

### OAuth flow times out or the browser never opens
The tool tries `webbrowser.open()`, which can fail in headless/remote environments. Give the user the printed authorization URL to open manually.

### "invalid_request" during authorization
The scopes or redirect URI requested don't match what's registered on the Adobe Sign application. Re-check Step 3 — the redirect URI must be an exact match, including the port (`8722`).

### 401 on API calls after connecting
The access token expired and the refresh failed — usually because the refresh token itself expired from inactivity, or the client secret was rotated in Adobe Sign. Re-run `/adobe-esign-setup` to reauthenticate.

### "Adobe Sign not connected" keeps appearing
No `ADOBE_SIGN_CLIENT_ID`/`ADOBE_SIGN_CLIENT_SECRET` configured, or `adobe_sign_authenticate` hasn't been run yet. Dex never errors out when credentials are missing — it just nudges the user to run this setup.

### PDF tools say pypdf isn't installed
Run `pip install -r core/mcp/requirements.txt` in the environment the `adobe` MCP server runs in. PDF tools don't need any Adobe credentials — only `pypdf`.

---

## Reconfiguration

If the user runs `/adobe-esign-setup` when already configured:

1. Verify the current connection with `adobe_sign_check_connection`.
2. Show the current config from `System/integrations/config.yaml`.
3. Offer options:
   - **Reauthenticate** — re-run the OAuth flow (useful after a token issue).
   - **Rotate credentials** — paste a new Client ID/Secret; Dex updates `VAULT_ROOT/.env`.
   - **Disconnect Adobe Sign.**

### Disconnect Flow

If the user wants to disconnect:

1. Update `System/integrations/config.yaml`:
   ```yaml
   adobe_sign:
     enabled: false
   ```
2. Remove (or comment out) the `ADOBE_SIGN_CLIENT_ID` / `ADOBE_SIGN_CLIENT_SECRET` / `ADOBE_SIGN_SHARD` lines in `VAULT_ROOT/.env`.
3. Delete `~/.claude/adobe_sign_tokens.json` (outside the repo).
4. Confirm: "Adobe Sign is disconnected. PDF tools still work. Run /adobe-esign-setup anytime to reconnect."
