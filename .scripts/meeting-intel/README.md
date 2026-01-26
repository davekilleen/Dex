# Dex Meeting Intel

Autonomous meeting processing from Granola. Runs in the background via macOS Launch Agent, processing your meetings with AI and creating structured notes.

## What It Does

1. **Reads from Granola** - Accesses Granola's local cache (no API needed)
2. **Analyzes with Gemini** - Extracts summaries, decisions, action items
3. **Creates structured notes** - Organized by date in `Inbox/Meetings/`
4. **Updates person pages** - Links meetings to people automatically
5. **Generates daily digests** - Synthesizes themes across meetings

## Quick Start

```bash
# 1. Install dependencies (from vault root)
npm install

# 2. Add Gemini API key
# Get free key at: https://aistudio.google.com/apikey
echo "GEMINI_API_KEY=your-key" >> .env

# 3. Configure your profile
# Edit System/user-profile.yaml with your name and role

# 4. Enable automatic sync
./install-automation.sh
```

## Requirements

- **Node.js** 18+ 
- **Granola app** installed with meeting recordings
- **Gemini API key** (free tier works fine)

## Files

| File | Purpose |
|------|---------|
| `sync-from-granola.cjs` | Main processor - reads cache, analyzes, creates notes |
| `update-person-pages.cjs` | Updates person pages with meeting references |
| `daily-synthesis.cjs` | Creates daily digest with cross-meeting themes |
| `install-automation.sh` | Installs/manages macOS Launch Agent |
| `com.dex.meeting-intel.plist` | Launch Agent configuration |
| `processed-meetings.json` | State tracking (auto-generated) |

## Commands

```bash
# Process new meetings now
node sync-from-granola.cjs

# Preview what would be processed
node sync-from-granola.cjs --dry-run

# Reprocess today's meetings (even if already done)
node sync-from-granola.cjs --force

# Check automation status
./install-automation.sh --status

# Disable automation
./install-automation.sh --remove
```

## Output Structure

```
Inbox/Meetings/
├── 2026-01-22/
│   ├── weekly-team-sync.md
│   └── customer-call-acme.md
├── digest-2026-01-22.md
└── queue.md
```

## Meeting Note Format

Each processed meeting includes:

- **Summary** - 2-3 sentence overview
- **Key Discussion Points** - Main topics covered
- **Decisions Made** - Commitments and choices
- **Action Items** - For you and for others
- **Meeting Intelligence** - Pain points, requests, competitive mentions (configurable)
- **Pillar Assignment** - Which strategic pillar this relates to
- **Raw Content** - Original notes and transcript (collapsed)

## Configuration

### User Profile (`System/user-profile.yaml`)

```yaml
name: "Your Name"
role: "Product Manager"
company: "Your Company"
meeting_intelligence:
  extract_customer_intel: true
  extract_competitive_intel: true
  extract_action_items: true
  extract_decisions: true
```

### Pillars (`System/pillars.yaml`)

Meetings are automatically classified into your configured pillars. The AI chooses the most appropriate one based on meeting content.

## Logs

- `.scripts/logs/meeting-intel.log` - Processing log
- `.scripts/logs/meeting-intel.stdout.log` - Standard output
- `.scripts/logs/meeting-intel.stderr.log` - Errors

View live logs:
```bash
tail -f .scripts/logs/meeting-intel.log
```

## How Automation Works

The Launch Agent (`com.dex.meeting-intel`) runs the sync script:
- Every 30 minutes while laptop is awake
- Immediately at login

State is tracked in `processed-meetings.json` to prevent reprocessing the same meetings.

## Troubleshooting

### No meetings processed

1. Check Granola cache exists: `ls ~/Library/Application\ Support/Granola/cache-v3.json`
2. Ensure meetings have content (notes or transcript)
3. Run with `--dry-run` to see what would be processed

### Gemini errors

1. Verify API key: `grep GEMINI_API_KEY .env`
2. Check quota at https://aistudio.google.com/

### Automation not running

1. Check status: `./install-automation.sh --status`
2. View logs: `tail -50 .scripts/logs/meeting-intel.stderr.log`
3. Reinstall: `./install-automation.sh --remove && ./install-automation.sh`

## Privacy

- All processing happens locally on your machine
- Meeting content is sent to Google's Gemini API for analysis
- No data is stored externally except during API calls
- Granola cache is read-only
