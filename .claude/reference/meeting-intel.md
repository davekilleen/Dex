# Meeting Intelligence Reference

Process meetings from Granola to extract structured insights, action items, and update person pages.

## How It Works

Meetings sync **automatically in the background** every 30 minutes via Granola's API.

```
Granola App (desktop + mobile) → Granola Cloud → API → Background Sync (every 30 min) → Synced Files → /process-meetings → Person Pages, Tasks
```

**Key features:** Mobile phone recordings are captured alongside desktop meetings. No separate OAuth setup needed — uses the token Granola's desktop app already stores on your machine.

## Setup (One-Time)

### 1. Install automation (30 seconds)

```bash
cd .scripts/meeting-intel && ./install-automation.sh
```

This will:
- Check prerequisites (Node.js, Granola, LLM API key)
- Install the 30-minute background sync via macOS Launch Agent

### 2. Authentication

Dex uses the same credentials Granola's desktop app stores locally. As long as you're signed into Granola on your computer, meeting sync works automatically. No separate sign-in step needed.

**Requirements:**
- Granola app installed ([granola.ai](https://granola.ai)) with a paid plan
- An LLM API key in `.env` (GEMINI_API_KEY, ANTHROPIC_API_KEY, or OPENAI_API_KEY)

## Data Sources

| Source | What it captures | When used |
|--------|-----------------|-----------|
| **Granola API** (primary) | Desktop + mobile recordings, notes, transcripts | When Granola is signed in |
| **Local cache** (fallback) | Desktop recordings only | When API unavailable |

## Using /process-meetings

After setup, `/process-meetings` reads synced files and updates your vault:

```
/process-meetings           # Process all synced meetings (last 7 days)
/process-meetings today     # Just today's meetings
/process-meetings "Acme"    # Find meetings by title/attendee
/process-meetings --setup   # Install/check background automation
```

**Flags:**
- `--people-only` — Only update person/company pages (skip tasks)
- `--no-todos` — Create notes but don't extract tasks
- `--days-back=N` — Override default 7-day lookback

**What gets updated:**
- Person pages (05-Areas/People/) — meeting references, last interaction dates
- Company pages (05-Areas/Companies/) — key contacts, meeting history
- Tasks (03-Tasks/Tasks.md) — action items extracted from meetings

## What Gets Extracted

The background sync uses your LLM API to extract:

- **Summary** (2-3 sentences)
- **Key discussion points** with context
- **Decisions made**
- **Action items** (for you and others, with task IDs for sync)
- **Customer intelligence** (pain points, feature requests, competitive mentions)
- **Pillar classification** based on your `System/pillars.yaml`

**Output location:** `00-Inbox/Meetings/YYYY-MM-DD/meeting-slug.md`

## Configuration

Meeting intelligence is configured in `System/user-profile.yaml`:

```yaml
meeting_intelligence:
  extract_customer_intel: true    # Pain points, requests
  extract_competitive_intel: true # Competitor mentions
  extract_action_items: true      # Always recommended
  extract_decisions: true         # Always recommended
```

Internal vs external classification uses your `email_domain` setting.

## Manual Sync (Optional)

To force a sync outside the 30-min schedule:

```bash
node .scripts/meeting-intel/sync-from-granola.cjs           # Process now
node .scripts/meeting-intel/sync-from-granola.cjs --dry-run # Preview
node .scripts/meeting-intel/sync-from-granola.cjs --force   # Reprocess today
```

## Stopping Background Sync

```bash
.scripts/meeting-intel/install-automation.sh --stop
```

## Logs

- `.scripts/logs/meeting-intel.log` - Processing log
- `.scripts/logs/meeting-intel.stdout.log` - Standard output
- `.scripts/logs/meeting-intel.stderr.log` - Errors

## Troubleshooting

**No meetings showing up?**
1. Check if Granola is installed and you're signed in
2. Check if background sync is set up: `./install-automation.sh --status`
3. Check logs for errors: `tail -50 .scripts/logs/meeting-intel.stderr.log`

**Mobile recordings not syncing?**
1. Ensure you have a paid Granola plan
2. Check that the Granola iOS app is syncing to cloud
3. Sign out and back in to the Granola desktop app to refresh credentials

**Background sync not running?**
```bash
cd .scripts/meeting-intel && ./install-automation.sh
```

**Want to re-process meetings?**
```bash
node .scripts/meeting-intel/sync-from-granola.cjs --force
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│ Granola Cloud (desktop + mobile recordings)          │
└──────────────────────┬──────────────────────────────┘
                       │ API (api.granola.ai, structured JSON)
                       ▼
┌─────────────────────────────────────────────────────┐
│ Background Sync (launchd, every 30 min)              │
│  - sync-from-granola.cjs → API fetch + LLM analysis │
│  - Auth: reads Granola's local supabase.json         │
│  - Fallback: local cache-v*.json (desktop only)      │
└──────────────────────┬──────────────────────────────┘
                       │ LLM extraction (Gemini/Claude/GPT)
                       ▼
┌─────────────────────────────────────────────────────┐
│ Vault Files                                          │
│  - 00-Inbox/Meetings/YYYY-MM-DD/slug.md             │
│  - processed-meetings.json (state)                  │
└──────────────────────┬──────────────────────────────┘
                       │ /process-meetings
                       ▼
┌─────────────────────────────────────────────────────┐
│ Person Pages, Company Pages, Tasks                   │
└─────────────────────────────────────────────────────┘
```
