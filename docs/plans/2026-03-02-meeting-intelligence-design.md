# Meeting Intelligence (Granola Sync) Design

**Date:** 2026-03-02
**Status:** Approved for Implementation
**Approach:** Exact Reconstruction

---

## Context

Tom needs to rebuild the meeting intelligence system that automatically syncs meetings from Granola, processes them with AI, and integrates with Notion. The original script was lost when the Dex project was accidentally deleted, but complete implementation details were recovered from conversation history.

**Why this is needed:**
- Automatic meeting capture and processing (30-minute sync cycle)
- Structured meeting notes with action items and insights
- Person relationship tracking across meetings
- Notion integration for team visibility
- Task extraction to daily workflow

**Priority:** This is the highest-priority custom script to rebuild, as it's core to Tom's daily workflow and provides the most value.

---

## Architecture Overview

### Core Design

**Single-file autonomous script** that runs every 30 minutes via macOS LaunchAgent:
- Reads Granola's local cache file directly (no API authentication needed)
- Processes new meetings with LLM analysis (Anthropic/Gemini/OpenAI)
- Creates structured outputs across multiple systems
- Gracefully handles failures and continues processing

### System Integration Points

```
Granola Cache (Local File)
    ↓ (read)
sync-from-granola.cjs
    ↓ (write)
    ├─→ Meeting Notes (00-Inbox/Meetings/)
    ├─→ Person Pages (05-Areas/People/External/)
    ├─→ Tasks (03-Tasks/Tasks.md)
    └─→ Notion (optional)
        ├─→ Meetings DB
        └─→ Triage DB
```

### Key Dependencies

**NPM Packages:**
- `js-yaml` - Parse System/pillars.yaml and System/user-profile.yaml
- `dotenv` - Load environment variables from .env
- `@notionhq/client` - Notion API integration (conditional)

**Internal Modules:**
- `.scripts/lib/llm-client.cjs` - Multi-provider LLM abstraction layer

**Environment Variables:**
- **Required:** One of `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or `OPENAI_API_KEY`
- **Optional:** `NOTION_API_TOKEN`, `NOTION_MEETINGS_DB_ID`, `NOTION_TRIAGE_DB_ID`, `NOTION_SOURCE_OF_TRUTH`

---

## Core Components

### 1. Granola Cache Reader

**Purpose:** Read and parse Granola's local cache file without API calls.

**Cache Location Auto-Detection:**
- macOS: `~/Library/Application Support/Granola/cache-v3.json`
- Windows: `%APPDATA%/Granola/cache-v3.json` or `%LOCALAPPDATA%/Granola/cache-v3.json`
- Linux: `~/.config/Granola/cache-v3.json`

**Data Structure:**
- Nested JSON: `{ cache: JSON_STRING }` where inner JSON contains `state.{documents, transcripts, people}`
- Documents: Meeting metadata and Granola notes
- Transcripts: Time-stamped transcript segments
- People: Participant information

**Filtering Logic:**
- Type must be 'meeting'
- Not deleted (`deleted_at === null`)
- Within lookback window (default 7 days, configurable)
- Has sufficient content (notes ≥ 50 chars OR has transcript)
- Not already processed (unless --force or --reprocess flags)

**Output Format:**
```javascript
{
  id: "uuid",
  title: "Meeting Title",
  createdAt: "2026-03-02T10:00:00Z",
  updatedAt: "2026-03-02T11:00:00Z",
  notes: "Granola markdown notes",
  transcript: "Full transcript text",
  participants: ["Person1", "Person2"],
  company: "Extracted Company Name",
  duration: 60  // minutes (estimated)
}
```

### 2. Meeting Processor (LLM Analysis)

**Purpose:** Generate structured analysis of each meeting using AI.

**LLM Prompt Structure:**
- Provides meeting context: title, date, participants, company
- Includes user profile: name, role, company, pillars
- Sends raw notes + transcript
- Instructs specific markdown format output

**Required Output Format:**
```markdown
## Summary
[2-3 sentence overview]

## Key Discussion Points
### [Topic 1]
[Details]

## Decisions Made
- [Decision]

## Action Items
### For Me
- [ ] [Task] - by [timeframe] ^task-YYYYMMDD-NNN
### For Others
- [ ] @[Person]: [Task]

## Meeting Intelligence
**Pain Points:** [or "None identified"]
**Requests/Needs:** [or "None identified"]
**Competitive Mentions:** [or "None identified"]

## Pillar Assignment
[Pillar Name]
Rationale: [One sentence]
```

**Meeting Note Creation:**
- Filename: `YYYY-MM-DD/{slugified-title}.md` (max 60 chars, alphanumeric + hyphens)
- Directory: `00-Inbox/Meetings/YYYY-MM-DD/`
- YAML frontmatter: date, time, type, source, participants, company, pillar, duration, granola_id, notion_url, processed timestamp
- Wiki-links to person pages: `[[05-Areas/People/External/Person_Name.md]]`
- Raw notes + transcript in collapsible `<details>` sections
- Footer showing processing provider

### 3. Person Page Manager

**Purpose:** Track relationships by maintaining person pages across meetings.

**Person Page Structure:**
```markdown
# Person Name

## Role / Company

[Initially "Unknown", manually updated]

## Meetings

- YYYY-MM-DD — [Meeting Link]
- YYYY-MM-DD — [Meeting Link]
```

**Creation Logic:**
- Directory: `05-Areas/People/External/`
- Filename: `{Name}.md` (spaces → underscores, non-alphanumeric removed)
- Only for participants (excludes meeting owner)
- Appends meeting reference under "## Meetings" heading
- Meeting reference: `YYYY-MM-DD — [Notion URL or [[00-Inbox/Meetings/...]] wikilink]`

### 4. Task Extractor

**Purpose:** Extract action items from meetings into the main task list.

**Extraction Process:**
1. Parse "### For Me" section from LLM analysis
2. Extract checklist items (lines starting with `- [ ]` or `- `)
3. Generate sequential task IDs: `^task-YYYYMMDD-NNN` (001, 002, 003...)
4. Add tags: `#pillar:{slugified-pillar-id}`, `#lno:N` (Neutral), `#granola:{meetingId}`
5. Insert under "## P2 - Normal" section in `03-Tasks/Tasks.md`

**Duplicate Prevention:**
- Checks for existing `#granola:{meetingId}` tags in Tasks.md
- Skips task extraction if meeting already has tasks

**Task Format:**
```markdown
- [ ] Task description - by timeframe ^task-20260302-004 #pillar:enterprise-growth-de-eu #lno:N #granola:uuid-here
```

### 5. Notion Sync (Optional)

**Purpose:** Sync meetings and action items to Notion for team visibility.

**A. Database Schema Auto-Discovery**
- Uses Notion Data Sources API to detect existing properties
- Discovers: Title, Date, Participants (multi_select), Source, Granola ID, Pillar, Company
- Auto-creates missing properties if needed

**B. Meeting Page Sync**
- Checks `notion-mapping.json` for existing page by Granola ID
- If not found, queries Notion by Granola ID property
- If still not found, queries by title + date match
- **Update existing page:** Updates properties + appends action item blocks
- **Create new page:** Full properties + markdown analysis as child blocks
- Saves mapping: `{ "granola-uuid": { "page_id": "...", "url": "..." } }`

**C. Triage DB Sync**
- Creates tasks in Notion Triage database
- Properties: Name (title), Rank (number), Status ("Triage"), Priority (P0-P2), Source ("Granola"), Granola ID, Task ID, Due (date), Pillar, Meeting (url), Company
- Intelligent ranking via `calculateTriageRank()`:
  - Base: 1000
  - Priority: P0 -1000, P1 -500, P2 -100
  - Due date: overdue -2000, today/tomorrow -1500, this week -800, this month -300

**D. Markdown → Notion Block Conversion**
- Headings: `###` → heading_3, `##` → heading_2, `#` → heading_1
- Paragraphs: Regular text → paragraph blocks
- Action items: `- [ ]` → to_do blocks (checked: false)
- Limits: Max 100 blocks per page

### 6. State Management

**Purpose:** Track processing state and prevent duplicates.

**State File:** `.scripts/meeting-intel/processed-meetings.json`
```json
{
  "processedMeetings": {
    "granola-uuid": {
      "title": "Meeting Title",
      "processedAt": "2026-03-02T12:00:00.000Z",
      "filepath": "/Users/tomgreen/Dex/00-Inbox/Meetings/..."
    }
  },
  "lastSync": "2026-03-02T12:00:00.000Z"
}
```

**Queue File:** `00-Inbox/Meetings/queue.md`
- Tracks: Pending, Processing, Processed (last 7 days)
- Auto-cleans entries older than 7 days
- Format: `- [x] Meeting Title | Company | YYYY-MM-DD | [link]`

---

## Data Flow

### Processing Pipeline

```
START
  ↓
1. Initialize
   - Load environment variables
   - Validate LLM API key exists
   - Load user profile and pillars
   - Read state file (processed meetings)
   ↓
2. Read Granola Cache
   - Parse nested JSON structure
   - Extract documents, transcripts, people
   ↓
3. Filter New Meetings
   - Apply type, deleted, date, content filters
   - Check against processed-meetings.json
   - Return list of unprocessed meetings
   ↓
4. For Each Meeting (sequential):
   │
   ├─→ 4a. Generate LLM Analysis
   │    - Construct prompt with context
   │    - Call LLM API
   │    - Parse structured output
   │    ↓
   ├─→ 4b. Create Meeting Note
   │    - Build YAML frontmatter
   │    - Format markdown content
   │    - Write to 00-Inbox/Meetings/YYYY-MM-DD/{slug}.md
   │    ↓
   ├─→ 4c. Update Person Pages
   │    - For each participant (except owner)
   │    - Create page if missing
   │    - Append meeting reference
   │    ↓
   ├─→ 4d. Extract & Add Tasks
   │    - Parse "For Me" action items
   │    - Generate task IDs
   │    - Insert into Tasks.md
   │    ↓
   └─→ 4e. Sync to Notion (if enabled)
        ├─→ Sync Meeting Page
        │    - Check mapping or query
        │    - Create or update
        │    - Save mapping
        └─→ Sync Tasks to Triage DB
             - For each action item
             - Calculate rank
             - Create Notion page
   ↓
5. Update State
   - Save processed meetings to state file
   - Update queue file
   - Clean old queue entries
   ↓
6. Post-Processing
   - Trigger notion-sync-triage-priorities.cjs
   - Log summary (processed count, errors)
   ↓
END
```

### File Locations

| Purpose | Path |
|---------|------|
| Main script | `.scripts/meeting-intel/sync-from-granola.cjs` |
| LaunchAgent plist | `.scripts/meeting-intel/com.dex.meeting-intel.plist` |
| Install script | `.scripts/meeting-intel/install-automation.sh` |
| State file | `.scripts/meeting-intel/processed-meetings.json` |
| Notion mapping | `.scripts/meeting-intel/notion-mapping.json` |
| LLM client | `.scripts/lib/llm-client.cjs` |
| Meeting notes | `00-Inbox/Meetings/YYYY-MM-DD/*.md` |
| Queue file | `00-Inbox/Meetings/queue.md` |
| Person pages | `05-Areas/People/External/*.md` |
| Tasks file | `03-Tasks/Tasks.md` |
| Logs | `.scripts/logs/meeting-intel.log` |

### Command-Line Interface

```bash
# Process new meetings (default)
node .scripts/meeting-intel/sync-from-granola.cjs

# Reprocess today's meetings
node .scripts/meeting-intel/sync-from-granola.cjs --force

# Reprocess all meetings in range
node .scripts/meeting-intel/sync-from-granola.cjs --reprocess

# Override lookback window
node .scripts/meeting-intel/sync-from-granola.cjs --days-back=14

# Dry run (show what would be processed)
node .scripts/meeting-intel/sync-from-granola.cjs --dry-run
```

---

## Error Handling & Edge Cases

### Graceful Degradation

**Philosophy:** Continue processing other meetings even if one fails.

**Error Scenarios:**
- **LLM API failure:** Log error, skip meeting, continue with next
- **Notion sync failure:** Meeting note still created locally, mark Notion as failed
- **Person page update failure:** Log warning, continue processing
- **Task extraction failure:** Meeting still processed, tasks skipped
- **File write failure:** Retry once, log error, continue

### Validation & Safety

**Startup Checks:**
- LLM API key must exist (fail fast if missing)
- Granola cache file must exist and be readable
- Required directories exist (create if missing)

**Processing Validations:**
- Skip meetings with insufficient content (< 50 chars notes, no transcript)
- Prevent duplicate task IDs (sequential per day with collision detection)
- Validate YAML frontmatter before writing
- Sanitize filenames (remove special chars, limit length)

**File Operations:**
- Use atomic writes where possible (temp file → rename)
- Handle concurrent access (state file locking via write-check-write pattern)

### Logging Strategy

**Log Levels:**
- **Info:** Processing start/end, meeting counts, successful operations
- **Warning:** Skipped meetings, missing data, Notion sync issues
- **Error:** API failures, file errors, unexpected exceptions

**Log Destinations:**
- File: `.scripts/logs/meeting-intel.log` (append mode)
- Stdout: Summary for LaunchAgent monitoring
- Stderr: Errors (captured by LaunchAgent)

**Log Format:**
```
[2026-03-02 12:00:00] [INFO] Starting Granola sync...
[2026-03-02 12:00:01] [INFO] Found 3 new meetings
[2026-03-02 12:00:05] [INFO] Processed: Meeting Title (uuid)
[2026-03-02 12:00:05] [WARN] No action items found in meeting
[2026-03-02 12:00:10] [ERROR] Notion sync failed: API_TOKEN_INVALID
[2026-03-02 12:00:15] [INFO] Sync complete: 3 processed, 0 errors
```

### Recovery Mechanisms

**State File Recovery:**
- If corrupted, backup to `.bak` and start fresh
- Allows resume from last successful point
- `--force` flag bypasses state check

**Manual Intervention:**
- Queue file shows stuck meetings
- `--reprocess` flag for bulk reprocessing
- Individual meeting can be reprocessed by deleting from state file

**Notion Sync Recovery:**
- Mapping file persists even if API fails
- Retry logic: exponential backoff for transient errors
- Skip and continue for permanent errors (invalid token, missing DB)

### Edge Cases

| Scenario | Handling |
|----------|----------|
| Meeting with no participants | Use meeting title only, skip person page updates |
| Duplicate meeting titles | Append timestamp to filename slug |
| Missing pillars in user config | Default to "unassigned" pillar, log warning |
| Notion property type mismatch | Auto-create missing properties with correct types |
| Long transcripts (> 50k chars) | Truncate to 5000 chars in notes, full to LLM |
| Company extraction fails | Leave empty, no fallback |
| Task ID collision | Increment counter until unique ID found |
| Participant is meeting owner | Exclude from person page updates |
| Meeting already in Notion | Update existing page, don't create duplicate |
| Granola cache empty | Log info, exit gracefully (no error) |

---

## LaunchAgent Configuration

### Plist File

**Path:** `.scripts/meeting-intel/com.dex.meeting-intel.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.dex.meeting-intel</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/node</string>
    <string>/Users/tomgreen/Dex/.scripts/meeting-intel/sync-from-granola.cjs</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/tomgreen/Dex</string>
  <key>StandardOutPath</key>
  <string>/Users/tomgreen/Library/Logs/dex-meeting-intel.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/tomgreen/Library/Logs/dex-meeting-intel.log</string>
  <key>StartInterval</key>
  <integer>1800</integer>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
</dict>
</plist>
```

**Key Settings:**
- `StartInterval`: 1800 seconds (30 minutes)
- Logs to: `~/Library/Logs/dex-meeting-intel.log`
- Working directory: `/Users/tomgreen/Dex` (important for relative paths)

### Installation Script

**Path:** `.scripts/meeting-intel/install-automation.sh`

```bash
#!/bin/bash
set -e

PLIST_SOURCE="$(dirname "$0")/com.dex.meeting-intel.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.dex.meeting-intel.plist"

echo "Installing Meeting Intel LaunchAgent..."

# Copy plist
cp "$PLIST_SOURCE" "$PLIST_DEST"

# Unload if already loaded
launchctl unload "$PLIST_DEST" 2>/dev/null || true

# Load the agent
launchctl load "$PLIST_DEST"

echo "✅ LaunchAgent installed and loaded"
echo "Check status: launchctl list | grep dex.meeting-intel"
```

### Management Commands

```bash
# Check status
launchctl list | grep dex.meeting-intel

# View logs
tail -f ~/Library/Logs/dex-meeting-intel.log

# Unload (stop)
launchctl unload ~/Library/LaunchAgents/com.dex.meeting-intel.plist

# Load (start)
launchctl load ~/Library/LaunchAgents/com.dex.meeting-intel.plist

# Restart
launchctl unload ~/Library/LaunchAgents/com.dex.meeting-intel.plist
launchctl load ~/Library/LaunchAgents/com.dex.meeting-intel.plist

# Trigger manually
node /Users/tomgreen/Dex/.scripts/meeting-intel/sync-from-granola.cjs
```

---

## Testing Strategy

### Unit Testing (Manual)

Test individual functions by running the script with flags:

```bash
# Test cache reading
node sync-from-granola.cjs --dry-run

# Test single meeting processing
node sync-from-granola.cjs --force --days-back=1

# Test without Notion
NOTION_API_TOKEN="" node sync-from-granola.cjs --force
```

### Integration Testing

**Test Scenarios:**
1. **First run (no state file):** Should process all meetings in lookback window
2. **Incremental run:** Should only process new meetings since last run
3. **Force reprocess:** Should reprocess today's meetings
4. **Notion sync enabled:** Should create/update Notion pages
5. **Notion sync disabled:** Should work without Notion credentials
6. **No new meetings:** Should exit gracefully with log message
7. **LLM API failure:** Should log error and continue with other meetings
8. **Person page already exists:** Should append to existing page, not overwrite

### Verification Checklist

After first successful run, verify:
- [ ] Meeting notes created in `00-Inbox/Meetings/YYYY-MM-DD/`
- [ ] YAML frontmatter is valid and complete
- [ ] Person pages created in `05-Areas/People/External/`
- [ ] Meeting references added to person pages
- [ ] Action items added to `03-Tasks/Tasks.md` with correct tags
- [ ] Task IDs are sequential and unique
- [ ] State file created in `.scripts/meeting-intel/`
- [ ] Queue file created/updated
- [ ] Notion pages created (if enabled)
- [ ] Notion triage tasks created (if enabled)
- [ ] Logs written to `.scripts/logs/meeting-intel.log`
- [ ] LaunchAgent runs automatically every 30 minutes

---

## Success Criteria

**Functional Requirements:**
- ✅ Automatically syncs meetings from Granola every 30 minutes
- ✅ Creates structured meeting notes with AI analysis
- ✅ Extracts action items into task list
- ✅ Updates person pages for all participants
- ✅ Syncs to Notion (meetings + triage)
- ✅ Handles errors gracefully without stopping
- ✅ Prevents duplicate processing
- ✅ Supports manual reprocessing

**Non-Functional Requirements:**
- ✅ Runs autonomously (no user intervention)
- ✅ Completes within 5 minutes per meeting
- ✅ Logs all operations for debugging
- ✅ Handles 10+ meetings per sync without issues
- ✅ Minimal dependencies (3 npm packages)

**User Experience:**
- ✅ Meetings appear in inbox within 30 minutes
- ✅ Action items automatically added to tasks
- ✅ Person pages stay up to date
- ✅ Notion stays in sync with local vault
- ✅ Can manually trigger sync when needed

---

## Implementation Notes

**Key Implementation Details from Original:**
- Script is 1373 lines (well-structured, single file)
- Company extraction uses hardcoded patterns (Premier League, Chapter 2, Aris, etc.)
- Pillar assignment uses keyword matching from `System/pillars.yaml`
- Task IDs are sequential per day (001, 002, 003...)
- Notion mapping file prevents duplicate pages
- Queue file provides visual status tracking
- Post-sync triggers priority sync to Notion Daily Command Center

**Dependencies on Other Scripts:**
- `llm-client.cjs` - Must exist before building this script
- `notion-sync-triage-priorities.cjs` - Called after sync completes (optional)

**Future Enhancements (Not in Scope):**
- Slack notifications for new meetings
- Calendar integration for meeting prep
- Automated follow-up reminders
- Meeting analytics dashboard
- Custom company extraction rules

---

*Design approved: 2026-03-02*
