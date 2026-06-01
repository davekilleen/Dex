---
name: granola-setup
description: Connect Granola to Dex via Granola's official API for automatic meeting sync and transcripts
integration:
  id: granola
  name: Granola
  auth: api_key
  category: meetings
  sync_direction: read
  api:
    base_url: https://public-api.granola.ai
    key_env_var: GRANOLA_API_KEY
    key_format: grn_...
    requires_plan: Granola Business or Enterprise
  enhances:
    - skill: process-meetings
      capability: "Granola is the primary meeting source — notes and transcripts sync into 00-Inbox/Meetings/"
    - skill: meeting-prep
      capability: "Surfaces past Granola notes and summaries with each attendee"
    - skill: week-review
      capability: "Meeting counts and topics from Granola notes"
  new_capabilities:
    - name: Automatic Meeting Sync
      trigger: "New Granola notes are pulled into 00-Inbox/Meetings/ for processing"
    - name: Transcript Access
      trigger: "During /process-meetings, fetch full speaker-labelled transcripts per note"
---

# Granola Setup

Connect your Granola account to Dex so your meetings sync automatically. Dex uses **Granola's official API** to read your notes, summaries, attendees, and transcripts — then files them into `00-Inbox/Meetings/` ready for `/process-meetings`.

This integration needs a **Granola Business (or Enterprise) plan**, because API keys can only be created on those plans. Granola **Basic / free** accounts can't create an API key, so this setup won't work on them.

## What This Enables

Once connected, Dex can:

**Read (via the official Granola API):**
- List your Granola notes (title, owner, created/updated dates)
- Fetch each note's summary, attendees, folder membership, and web link
- Fetch full speaker-labelled transcripts per note

**Skill Enhancements:**
- **Process Meetings** (`/process-meetings`) uses Granola as the primary meeting source — notes sync into `00-Inbox/Meetings/`, then get turned into structured meeting notes (decisions, actions, key points)
- **Meeting Prep** (`/meeting-prep`) surfaces your last Granola note and summary with each attendee
- **Week Review** (`/week-review`) includes meeting counts and topics from Granola

**New Capabilities:**
- **Automatic Meeting Sync:** new Granola notes are pulled into `00-Inbox/Meetings/`
- **Transcript Access:** full transcripts are available when processing a meeting

## Privacy

Dex reads your Granola data through Granola's official API using a key you create. The API key is stored locally in a `.env` file at your vault root — it is **gitignored and never committed**. Only YOUR Granola account is accessible (the key is scoped to your login). Nothing is sent anywhere except Granola's own API.

## When to Run

- User types `/granola-setup`
- User asks about connecting Granola
- User wants automatic meeting sync or transcripts
- During `/integrate-mcp` if Granola is mentioned
- During onboarding if the user mentions Granola

---

## Setup Flow

> Throughout this flow, **Dex performs every file action for the user**. Never ask the user to open, create, or hand-edit `.env` or any other file. They only ever paste their key into the chat — Dex does the rest.

### Step 1: Check if Already Connected

1. Read `System/integrations/config.yaml` for a `granola` section.
2. Check whether `GRANOLA_API_KEY` is already configured:
   - First check `process.env.GRANOLA_API_KEY`.
   - If absent, load the vault root `.env` file (at `VAULT_ROOT`) and parse a `GRANOLA_API_KEY=...` line from it.
3. If a key is found, run the verification request from **Step 5** silently.
   - If it succeeds, tell the user they're already connected and skip to **Step 7** (Reconfiguration / what's enabled).
   - If it returns 401, the key is stale — continue to Step 2 to replace it.
4. If no key is found, continue to Step 2.

### Step 2: Explain the New API-Based Sync

Set expectations conversationally:

```
Granola sync now uses Granola's official API.

That means Dex reads your meetings the supported way — your notes, summaries,
attendees, and transcripts — straight from Granola.

One thing to know up front: creating an API key requires a **Granola Business
(or Enterprise) plan**. The Basic / free plan can't create API keys, so if
you're on Basic this won't work yet.

Are you on a Granola Business or Enterprise plan? [Yes / Not sure / I'm on Basic]
```

- **If "I'm on Basic":** let them know kindly that they'd need to upgrade to a Granola Business plan to create an API key, and that they can run `/granola-setup` again once they do. Stop here.
- **If "Not sure":** reassure them — the next step will tell them quickly (if there's no API option in Settings, they're not on a plan that supports it). Continue.
- **If "Yes":** continue.

### Step 3: Walk Them Through Creating an API Key

Guide them, step by step, in plain language:

```
Let's create your Granola API key:

1. Open **Granola** and go to **Settings**.
2. Find the **API** section (the Granola API settings page).
3. Click **Create API key** (or "New API key").
4. Copy the key — it starts with `grn_`.

If there's no API section in Settings, your plan doesn't support API keys yet
(that's the Business-plan requirement). Otherwise, grab that `grn_...` key.
```

### Step 4: Ask Them to Paste the Key

```
Paste your Granola API key here and I'll save it for you securely.
(It starts with grn_ — I'll store it locally and never commit it.)
```

Wait for the user to paste the key.

- Do a light sanity check: it should look like `grn_...`. If it clearly doesn't (e.g. they pasted something else), ask them to re-copy it from Granola's API settings.
- **Never** ask the user to put the key in a file themselves — they only paste it into the chat.

### Step 5: Store and Verify the Key

**Store it (Dex does this — not the user):**

1. Locate the vault root `.env` file (`VAULT_ROOT/.env`). Create it if it doesn't exist.
2. Write or update the line `GRANOLA_API_KEY=<pasted key>` in that file.
   - If a `GRANOLA_API_KEY=` line already exists, replace it; otherwise append it.
3. Confirm `.env` is gitignored (it is by convention — never commit it).

**Verify it with a real request:**

Make a single test call against the official API:

```bash
curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $GRANOLA_API_KEY" \
  "https://public-api.granola.ai/v1/notes?page_size=1"
```

(Equivalently: `GET https://public-api.granola.ai/v1/notes?page_size=1` with header `Authorization: Bearer <key>`.)

- **On success (HTTP 200):**
  ```
  Connected — I can see your Granola notes.
  ```
  Continue to Step 6.

- **On 401 Unauthorized:**
  ```
  That key was rejected by Granola.

  Two common reasons:
  - the key was copied incompletely or has been revoked/expired, or
  - the account isn't on a Granola Business plan (only Business/Enterprise
    can create working API keys).

  Want to paste it again, or create a fresh key in Granola → Settings → API?
  ```
  Offer to retry (back to Step 4). Retry up to 2 times, then offer to come back later.

- **On HTTP 429 (rate limited):** wait a short moment and retry the verification request once. The API has no documented limits, so stay gentle (one request at a time, single retry).

- **On other errors (network/5xx):** report briefly and offer to retry.

### Step 6: Save Configuration

Write to `System/integrations/config.yaml` — update (or add) the `granola` section. Preserve all other integration configs.

```yaml
granola:
  enabled: true
  configured_at: YYYY-MM-DD
  auth_type: api_key
  api_base_url: https://public-api.granola.ai
  key_env_var: GRANOLA_API_KEY   # value lives in VAULT_ROOT/.env, never here
  account: user@example.com        # from the owner.email in the test response
  features:
    meeting_sync: true
    transcripts: true
```

Never write the API key value itself into `config.yaml` or any committed file — only the env var name. The key lives solely in the gitignored `.env`.

### Step 7: Confirm with Capability Cascade

```
Granola is connected!

Here's what just got enabled:

- **Automatic meeting sync** — your Granola notes flow into 00-Inbox/Meetings/,
  ready to be turned into structured notes.
- **Transcripts** — full speaker-labelled transcripts are available per meeting.
- **Meeting Prep** (/meeting-prep) — surfaces your last Granola note and summary
  with each attendee.
- **Week Review** (/week-review) — includes meeting counts and topics from Granola.

Next step: run **/process-meetings** to pull in and organise your recent meetings.

You can re-run /granola-setup anytime to rotate your key or disconnect.
```

---

## Shared Conventions (data source rules)

These rules apply wherever Dex reads Granola data. The skill agent must follow them exactly so every Granola-aware workflow behaves consistently.

- **API key env var:** `GRANOLA_API_KEY`. Read `process.env.GRANOLA_API_KEY` first; if absent, load `VAULT_ROOT/.env` and parse `GRANOLA_API_KEY=...` from it.
- **No key configured → no error.** Log this friendly one-liner and exit cleanly (exit 0 / return empty):
  ```
  Granola not connected — run /granola-setup to add your Granola API key (requires a Granola Business plan).
  ```
- **Official API is the only data source.** There is **no local-file fallback**. Do not read `supabase.json`, `supabase.json.enc`, `cache-v*.json(.enc)`, or use any spoofed `User-Agent` / `X-Client-Version` headers or `granola-crypto`. Use only the documented endpoints below with the `Authorization: Bearer` header.

### API reference (for Granola-aware skills)

- **Base URL:** `https://public-api.granola.ai`
- **Auth header:** `Authorization: Bearer <GRANOLA_API_KEY>`
- **List:** `GET /v1/notes`
  - Query params: `created_after`, `created_before`, `updated_after` (ISO date/datetime), `folder_id`, `cursor` (string), `page_size` (int 1..30, default 10).
  - Response: `{ "notes": [ { "id", "object", "title": string|null, "owner": {name,email}, "created_at", "updated_at" } ], "hasMore": boolean, "cursor": string|null }`.
  - List items contain **no** summary, attendees, or transcript — fetch detail per note.
  - Paginate by passing the returned `cursor` until `hasMore` is `false`.
- **Detail:** `GET /v1/notes/{note_id}?include=transcript`
  - Response includes `web_url`, `calendar_event`, `attendees`, `folder_membership`, `summary_text`, `summary_markdown`, and `transcript` (array of `{speaker, text, start_time, end_time}` or `null`).
- **Rate limits:** not documented. Be gentle — sequential detail fetches, and retry once on HTTP 429 with a short backoff.

---

## Troubleshooting

### 401 Unauthorized

The key was rejected. Either:
- the key is wrong, incomplete, revoked, or expired — create a fresh one in **Granola → Settings → API** and paste it again, or
- the account isn't on a **Granola Business / Enterprise plan** — only those plans can create working API keys. Basic / free can't.

Re-run `/granola-setup` to paste a new key.

### No Notes Returned (empty list, 200 OK)

The key works but Dex sees no notes. Check:
- you're querying the right Granola **workspace/account** (the key is scoped to the account that created it), and
- that account actually has recorded notes, and
- the plan still supports API access.

### "Granola not connected" keeps appearing

That means no `GRANOLA_API_KEY` is configured. Run `/granola-setup` to add one. (Dex never errors out when the key is missing — it just nudges you to set it up.)

### Rate Limiting (429)

Granola doesn't publish rate limits, so Dex fetches gently. If you hit a 429, Dex waits briefly and retries once. Persistent 429s are rare — wait a minute and try again.

---

## Reconfiguration

If the user runs `/granola-setup` when already configured:

1. Verify the current key with the Step 5 test request.
2. Show the current config from `System/integrations/config.yaml`.
3. Offer options:
   - **Rotate the key** — paste a new `grn_...` key; Dex updates `VAULT_ROOT/.env`.
   - **Re-test the connection.**
   - **Disconnect Granola.**

### Disconnect Flow

If the user wants to disconnect:

1. Update `System/integrations/config.yaml`:
   ```yaml
   granola:
     enabled: false
   ```
2. Remove (or comment out) the `GRANOLA_API_KEY=...` line in `VAULT_ROOT/.env` for them.
3. Confirm: "Granola is disconnected. Meeting sync and transcripts will pause. Run `/granola-setup` anytime to reconnect."
