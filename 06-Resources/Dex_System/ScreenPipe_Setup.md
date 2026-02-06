# ScreenPipe Setup Guide

ScreenPipe turns your computer into a personal AI memory by recording your screen 24/7 locally.

## Quick Start

### 1. Start ScreenPipe

```bash
screenpipe
```

First run will prompt for permissions:
- **Screen Recording** - Required (System Preferences > Privacy > Screen Recording)
- **Microphone** - Optional (for audio transcription)

### 2. Grant Permissions (macOS)

1. Go to **System Preferences > Privacy & Security > Screen Recording**
2. Enable `screenpipe`
3. Restart ScreenPipe if needed

### 3. Verify It's Running

In Claude/Pi, use:
```
/screenpipe-start
```
or check status with the `screenpipe_status` tool.

---

## Available Tools

### In Pi (via screen-orchestrator extension)

| Tool | Description |
|------|-------------|
| `screenpipe_status` | Check if ScreenPipe is running |
| `screenpipe_query` | Search screen history for text/apps |
| `screenpipe_summarize` | Generate narrative summary of activity |
| `screenpipe_time_audit` | Analyze time spent by app |

### Commands

| Command | Description |
|---------|-------------|
| `/screenpipe-start` | Start ScreenPipe in background |
| `/screen-day` | Summarize today's activity to daily note |

### In Claude Desktop (via MCP)

The ScreenPipe MCP provides similar functionality directly in Claude Desktop.

---

## Dex Skills

| Skill | Description |
|-------|-------------|
| `/skill:screen-recall` | Find what you were doing at any time |
| `/skill:screen-summary` | Narrative summary of time period |
| `/skill:time-audit` | Productivity breakdown by app |

---

## Example Queries

```
"What was I doing at 2pm today?"
→ screenpipe_query(query="*", start_time="2026-02-03T13:45:00", end_time="2026-02-03T14:15:00")

"How much time did I spend in Slack?"
→ screenpipe_time_audit(start_time="2026-02-03T09:00:00", end_time="2026-02-03T17:00:00")

"Summarize my morning"
→ screenpipe_summarize(start_time="2026-02-03T09:00:00", end_time="2026-02-03T12:00:00")

"Find when I saw that error message"
→ screenpipe_query(query="error: connection refused")
```

---

## Resource Usage

- **CPU:** ~10%
- **RAM:** 0.5-3GB
- **Storage:** ~15GB/month
- **Works offline:** Yes

---

## Privacy Configuration

Privacy exclusions are configured in `~/.screenpipe/config.json`:

```json
{
  "fps": 0.5,
  "disable_audio": true,
  "use_pii_removal": true,
  "ignored_windows": [
    "1Password",
    "Keychain Access",
    "System Preferences - Security",
    "Bitwarden",
    "LastPass"
  ],
  "ignored_apps": [
    "1Password",
    "Keychain Access",
    "Bitwarden",
    "LastPass"
  ]
}
```

**PII Removal:** Enabled by default - automatically redacts emails, phone numbers, credit cards, SSNs, and API keys from stored data.

---

## Auto-Start on Login

ScreenPipe is configured to start automatically via LaunchAgent:

**Location:** `~/Library/LaunchAgents/com.screenpipe.agent.plist`

**Manage:**
```bash
# Stop auto-start
launchctl unload ~/Library/LaunchAgents/com.screenpipe.agent.plist

# Re-enable auto-start
launchctl load ~/Library/LaunchAgents/com.screenpipe.agent.plist

# Check status
launchctl list | grep screenpipe
```

**Logs:**
- stdout: `~/.screenpipe/screenpipe.log`
- stderr: `~/.screenpipe/screenpipe.error.log`

---

## Troubleshooting

### ScreenPipe not starting
1. Check permissions in System Preferences
2. Try running with verbose: `screenpipe --debug`
3. Check logs: `~/.screenpipe/logs/`

### No data being captured
1. Verify screen recording permission is granted
2. Check that the screenpipe process is running: `pgrep screenpipe`
3. Look at the database: `ls -la ~/.screenpipe/db/`

### API not responding
- Default API runs on `http://localhost:3030`
- Check if port is in use: `lsof -i :3030`

---

## Architecture

```
┌─────────────────────────────────────────┐
│         ScreenPipe (Rust binary)        │
├─────────────────────────────────────────┤
│  Screen Capture → OCR → SQLite          │
│  Audio Capture → Whisper → SQLite       │
├─────────────────────────────────────────┤
│  REST API: localhost:3030               │
│  MCP Server: screenpipe-mcp             │
└─────────────────────────────────────────┘
           ↓
┌─────────────────────────────────────────┐
│              Dex Integration            │
├─────────────────────────────────────────┤
│  screen-orchestrator.ts (Pi extension)  │
│  Skills: screen-recall, time-audit      │
│  Auto-enrichment of daily notes         │
└─────────────────────────────────────────┘
```

---

## Related

- [[ScreenPipe_Multimodal_Integration]] - Project page
- [ScreenPipe Docs](https://docs.screenpi.pe)
- [ScreenPipe GitHub](https://github.com/mediar-ai/screenpipe)
