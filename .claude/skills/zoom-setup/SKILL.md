---
name: zoom-setup
description: "Connect the official Zoom for Claude connector for meeting recordings, transcripts, AI summaries, cloud-recording lists and Zoom Chat/Canvas search. Use when the user says 'connect Zoom', 'pull my Zoom recordings', 'search my Zoom meetings'. Not for Granola-sourced notes; use `granola-setup`. Not for Teams; use `ms-teams-setup`."
integration:
  id: zoom
  name: Zoom
  connector: zoom-for-claude
  directory_url: https://claude.ai/directory/connectors/zoom-for-claude
  auth: oauth2
  category: meetings
  sync_direction: read
  enhances:
    - skill: meeting-prep
      capability: "Surfaces past Zoom recording summaries and transcripts for attendees"
    - skill: process-meetings
      capability: "Zoom cloud recordings and transcripts as a meeting source alongside Granola"
    - skill: week-review
      capability: "Meeting stats from Zoom cloud recordings (count, recent activity)"
  new_capabilities:
    - name: Recording Search
      trigger: "During /meeting-prep, search Zoom recordings and transcripts for past meetings with attendees"
    - name: Canvas Follow-up
      trigger: "Turn Markdown (e.g. action items) into a follow-up Zoom Canvas, with confirmation"
---

# Zoom Setup

Connect the **official Zoom for Claude connector** so your meeting prep, reviews, and
process-meetings workflows can reach your Zoom recordings, transcripts, AI summaries, and
Zoom Chat/Canvas.

**Important — how this actually connects.** Zoom for Claude is a **hosted Claude Connector**
from the [Anthropic Connectors Directory](https://claude.ai/directory/connectors/zoom-for-claude),
authorized with OAuth in your Claude client. It is **not** a locally-run MCP server and there is
**no npm package to install**. You enable it once in Claude (exactly like the Notion or Google
connectors); after that its tools appear in your sessions and Dex uses them. This skill's job is
to walk you through enabling it, verify it responds, and record that Zoom is available so Dex's
meeting workflows switch on.

## What This Enables

Once the connector is enabled, Dex can:

**Read:**
- List your Zoom cloud recordings
- Retrieve meeting assets: AI summaries, docs, recordings, whiteboards
- Access recording resources: transcripts, summaries, next steps, playback links
- Search Zoom meetings, Zoom Chat messages, and Zoom Canvas using natural language

**Create (always with your confirmation):**
- Create a follow-up Zoom Canvas from Markdown (e.g. turn extracted action items into a Zoom Doc)

**Skill Enhancements:**
- **Meeting Prep** (`/meeting-prep`) surfaces past Zoom recording summaries/transcripts for attendees
- **Process Meetings** (`/process-meetings`) can use Zoom cloud recordings and transcripts as a meeting source
- **Week Review** (`/week-review`) can include Zoom cloud-recording activity

> **Not supported by this connector:** meeting *scheduling*. The Zoom for Claude connector reads
> meeting assets and creates Zoom Canvas docs; it does not create or schedule Zoom meetings. Don't
> promise scheduling.

## Requirements

From Zoom's connector documentation:

- A **licensed** user on a Zoom Workplace **Pro, Pro Plus, Business, Business Plus, Enterprise,
  Enterprise Plus, or Enterprise Bundle** account
- A Zoom **account owner or admin** with privileges (connectors may require admin approval)
- A **Claude account**
- **AI Companion Smart Recording** and **Meeting Summary** enabled — without both, the connector
  has limited functionality
- For video/playback features, meetings must be **recorded to the cloud** using Smart Recording

You can only access a meeting's assets/recordings when you **hosted** that meeting or were
**granted access** by the host.

## Privacy

This is an official OAuth connector authorized in your Claude client; access is scoped to your
own Zoom account and to meetings you hosted or were granted. Authorization is handled by
Claude/Zoom OAuth — there is no local token file for Dex to manage. Dex reads assets on demand
during a session; it does not store recordings in your vault. Zoom's
[privacy policy](https://www.zoom.com/en/trust/privacy/privacy-statement/) governs the connector.

## When to Run

- User types `/zoom-setup`
- User asks about connecting Zoom, or pulling/searching Zoom recordings
- User wants Zoom recording context in meeting prep
- During `/integrate-mcp` if Zoom is mentioned

---

## Setup Flow

### Step 1: Check if Already Connected

1. Check `System/integrations/config.yaml` for `zoom.enabled: true`.
2. Check whether Zoom connector tools are present in the session (a Zoom connector exposes tools
   for listing recordings / searching meetings). If they are present and respond, skip to
   **Step 5 (Save Configuration)** and confirm.
3. If the tools are not present, continue to Step 2 — the connector still needs enabling in the
   Claude client.

### Step 2: Smart Granola Detection

Check whether Granola is already connected:

1. Read `System/integrations/config.yaml` for a `granola` section.
2. Check if Granola MCP tools are available (try `granola_check_available()`).

**If Granola IS connected:**

```
You already have Granola connected -- it captures your meeting notes automatically.

The Zoom connector would add:
- Direct access to Zoom cloud recordings, transcripts and AI summaries
- Search across Zoom meetings, Zoom Chat and Zoom Canvas
- Creating follow-up Zoom Canvas docs from Markdown

Still want to connect Zoom? [Yes / Skip for now]
```

If "Skip for now":
> "No problem. Granola has your meeting capture covered. Run `/zoom-setup` anytime if you want
> direct Zoom recording, transcript or Canvas access later."

**If Granola is NOT connected (or user says Yes):** continue.

### Step 3: Enable the Zoom for Claude Connector

This is the whole setup — enabling a hosted connector, not installing anything.

Tell the user:

```
Zoom for Claude is an official Claude Connector. Here's how to turn it on:

1. Open the Zoom for Claude connector directory page:
   https://claude.ai/directory/connectors/zoom-for-claude
2. Click Connect and complete the Zoom OAuth sign-in.
3. Approve the requested access.

Requirements: a licensed Zoom Workplace Pro (or higher) seat, account owner/admin privileges,
and AI Companion Smart Recording + Meeting Summary enabled. Your Zoom admin may need to approve
the connector first.
```

**Do not edit `.mcp.json`, run `npx`, or install any package.** There is no `zoom-mcp` package;
the connector is hosted and enabled through Claude, the same way the Notion and Google connectors
are.

**Session visibility.** A newly enabled connector's tools appear in **new** sessions. If the tools
are not visible immediately after enabling, tell the user to start a fresh Claude session and run
`/zoom-setup` again — Dex will then see the Zoom tools. This is expected connector behavior, not a
failure.

### Step 4: Verify the Connection and Check Asset Permissions

Once the Zoom connector tools are available in the session, run a quick read-only check:

1. List recent cloud recordings, OR
2. Search for a recent meeting the user hosted.

**Then inspect the per-meeting permission flags the connector returns** — for example
`has_transcript`, `has_summary`, `has_transcript_permission`, `has_summary_permission`. These
reveal what *this* account can actually access, which varies by Zoom plan and admin policy.
Recordings, playback links, attendees and topics are commonly available even when transcript and
summary access is not. Do not assume transcripts/summaries are available — check.

Report honestly what is and isn't available:

```
**Quick test:**
- Cloud recordings: found [N]
- Meeting search: working
- Transcripts: available / NOT available (no permission on this account)
- AI summaries: available / NOT available (no permission on this account)

Zoom is connected.
```

**If transcripts/summaries come back without permission** (`has_transcript_permission: false` /
`has_summary_permission: false`): this is a Zoom account/admin setting, not a Dex problem. Tell the
user their account needs AI Companion **Smart Recording** and **Meeting Summary** enabled — often an
admin action — to unlock transcript and summary access. Until then, recordings, playback links,
attendees and topics still work. Do not promise transcript- or summary-based features you have just
observed this account cannot use.

**If it responds but returns nothing at all:** likely no cloud recordings the user hosted, or Smart
Recording is off. Point them at the Requirements rather than reporting a failure.

**If the tools still aren't visible:** the connector isn't enabled yet, or this session predates
enabling it. Ask them to enable it at the directory link and start a new session.

### Step 5: Save Configuration

Write to `System/integrations/config.yaml` — update the `zoom:` section:

```yaml
zoom:
  enabled: true
  configured_at: YYYY-MM-DD
  connector: zoom-for-claude
  directory_url: https://claude.ai/directory/connectors/zoom-for-claude
  auth_type: oauth2
  granola_coexists: true   # or false -- whether Granola was connected at setup time
  features:
    zoom_recordings: true      # cloud recordings, playback links, attendees, topics
    zoom_transcripts: false    # set true ONLY if has_transcript_permission was observed in Step 4
    zoom_summaries: false      # set true ONLY if has_summary_permission was observed in Step 4
    zoom_canvas: true          # allow creating follow-up Zoom Canvas docs (with confirmation)
```

Set `zoom_transcripts` / `zoom_summaries` from the permission flags you actually observed in
Step 4 — not optimistically. If the file already exists, only update the `zoom:` section and
preserve other integration configs. Do **not** write an `mcp_server` key or any local token path
— there is neither.

### Step 6: Confirm with Capability Cascade

```
**Zoom is connected!**

Here's what just got enhanced:

- **Meeting Prep** (`/meeting-prep`) can surface past Zoom recordings, playback links, attendees
  and topics for the people you're meeting — plus transcripts and summaries *if your account has
  permission for them*.
- **Process Meetings** (`/process-meetings`) can pull Zoom cloud recordings as a meeting source;
  it can use transcripts/summaries only where the account grants them.
- **Week Review** (`/week-review`) can include Zoom cloud-recording activity.
- **Follow-ups:** I can turn action items into a follow-up Zoom Canvas doc, with your confirmation.

(The connector reads meeting assets and creates Zoom Canvas docs — it does not schedule meetings.)
```

**Tailor this to what Step 4 actually found.** If transcript/summary permission was absent, say so
plainly instead of listing them as live: meeting prep and process-meetings will use recordings,
playback, attendees and topics until AI Companion Smart Recording + Meeting Summary are enabled on
the account. Then:

```
Adjust anytime by re-running `/zoom-setup`.
```

---

## Troubleshooting

### Zoom tools don't appear in the session

The connector is enabled per Claude client, and its tools load in **new** sessions.

1. Confirm it's enabled at https://claude.ai/directory/connectors/zoom-for-claude
2. Start a fresh Claude session, then run `/zoom-setup` again
3. If it's still missing, your Zoom admin may not have approved the connector for your account

### Limited functionality / no assets returned

The connector depends on Zoom AI Companion features:

1. Enable **Smart Recording** and **Meeting Summary** in Zoom
2. Remember you can only access meetings you **hosted** or were **granted** access to
3. Video/playback features require **cloud** recordings made with Smart Recording

### No cloud recordings found

- **Licensing:** requires a licensed Zoom Workplace Pro (or higher) seat
- **Cloud recording:** local-only recordings aren't accessible; record to the cloud
- **Retention:** your Zoom admin may auto-delete recordings after a period

### Corporate Zoom restrictions

Some organizations require admin approval for connectors:

1. Ask your Zoom admin to approve the Zoom for Claude connector for your account
2. Owner/admin privileges are listed as a requirement by Zoom

---

## Reconfiguration

If the user runs `/zoom-setup` when already connected:

1. Verify via a quick read-only query (list recordings / search).
2. Show current config from `System/integrations/config.yaml`.
3. Offer options:
   - Toggle whether Zoom recordings are used as a `/process-meetings` source
   - Re-verify (if the connector was re-authorized)
   - Disconnect Zoom in Dex

### Disconnect Flow

If the user wants Dex to stop using Zoom:

1. Update `System/integrations/config.yaml`:
   ```yaml
   zoom:
     enabled: false
   ```
2. Confirm: "Zoom is disconnected in Dex. Meeting prep and reviews will no longer include Zoom
   recording context. To fully revoke access, remove the Zoom for Claude connector in your Claude
   connector settings. Run `/zoom-setup` anytime to reconnect."
