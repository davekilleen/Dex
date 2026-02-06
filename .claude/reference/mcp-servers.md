# MCP Servers Reference

## What is MCP?

**Model Context Protocol (MCP)** is an open standard for connecting AI assistants to external data sources and tools. Think of it as a universal adapter that lets AI read from and write to your systems—calendars, databases, APIs, local files—without custom integration for each LLM.

### Why MCP Servers?

Traditional approach: AI directly parses raw files/APIs every time (slow, inconsistent, expensive tokens).

**MCP approach:** Specialized servers handle data aggregation and formatting → AI receives clean, structured data → faster, more consistent, cheaper.

**Example:** Instead of Claude reading 50 career evidence files individually (expensive, slow), the Career MCP scans them all in milliseconds and returns structured stats: "8 competencies, 42 evidence files, Technical Depth: 2 examples (weak), Product Strategy: 8 examples (strong)." Claude then coaches based on structured insights.

**Key benefits:**
- **Speed** - Pre-processed data vs raw file reads
- **Consistency** - Same input → same output (deterministic)
- **Token efficiency** - Structured summaries vs full documents
- **Reusability** - One server, many AI agents can use it
- **Separation of concerns** - Data layer vs reasoning layer

---

## Built-in MCP Servers

Dex includes eight custom MCP servers in `core/mcp/`:

### Work MCP (`work_server.py`)

**What it does:**  
Central nervous system for task and priority management. Prevents duplicate tasks, enforces priority limits (max 3 P0s), aligns work to strategic pillars, and auto-syncs tasks to person/company pages.

**Why it's an MCP:**  
Tasks live in multiple files (`03-Tasks/Tasks.md`, meeting notes, person pages). The Work MCP maintains a unified index with automatic deduplication and bidirectional sync. Without it, you'd have scattered, duplicate tasks and manual updates.

**Power:**
- **Intelligent deduplication** - Detects "Fix login bug" and "Resolve auth issue" as duplicates using semantic similarity
- **Priority enforcement** - Refuses to create 4th P0 task, forcing prioritization
- **Pillar alignment** - Auto-tags tasks with `#Growth`, `#Platform`, etc. based on content
- **Ambiguity detection** - Flags vague tasks like "Improve dashboard" and prompts for specifics
- **Cross-reference sync** - Task created in meeting note auto-appears on person pages and `03-Tasks/Tasks.md`

**Real-world example:**  
You create task "Ship payments redesign" in meeting with Sarah. Work MCP:
1. Tags it `#Platform` (matches pillar keywords)
2. Detects similarity to existing "Rebuild payment flow" (70% match), asks if duplicate
3. Assigns unique ID `^task-20260128-001`
4. Updates `03-Tasks/Tasks.md`, meeting note, and Sarah's person page with backlinks
5. Surfaces during `/daily-plan` as part of Platform work

**Configuration:** Reads `System/pillars.yaml` for strategic alignment.

---

### Calendar MCP (`calendar_server.py`)

**What it does:**  
Apple Calendar integration via AppleScript. Reads events, attendees, and meeting context without leaving Cursor.

**Why it's an MCP:**  
Calendar data changes frequently. Having an MCP means `/daily-plan` always gets live meeting data without manually exporting/importing CSVs or leaving the editor.

**Power:**
- **Universal sync** - Works with any calendar in Calendar.app (Google, Exchange, iCloud, etc.)
- **Attendee context** - Returns full attendee lists for meeting prep
- **Day-at-a-glance** - Instant view of today's schedule with times and locations
- **No API keys** - Uses native macOS calendar access

**Real-world example:**  
You run `/daily-plan` at 8am. Calendar MCP fetches today's meetings:
- 10am: Product Review (Sarah, Mike, Alex)
- 2pm: Customer Call - Acme Corp (John from external contacts)

Dex automatically:
- Pulls person pages for Sarah, Mike, Alex, John
- Surfaces recent meeting notes with each
- Shows outstanding action items
- Suggests prep based on recent interactions

**Tools:** `calendar_list_calendars`, `calendar_get_today`, `calendar_get_events_with_attendees`

---

### Granola MCP (`granola_server.py`)

**What it does:**  
Reads meeting transcripts from Granola's local cache. No API, no cloud—just direct file access to your local meeting notes.

**Why it's an MCP:**  
Granola stores meetings in a SQLite database with proprietary schema. The MCP abstracts that complexity, providing simple queries like "get last 5 meetings" or "search meetings mentioning 'roadmap'".

**Power:**
- **Zero-config** - Works immediately if Granola is installed
- **Full-text search** - Find specific topics across all meeting transcripts
- **Recency-based retrieval** - "What did we discuss with Sarah this week?"
- **Integration with person pages** - Automatically links meeting transcripts to attendees

**Real-world example:**  
You're preparing for tomorrow's meeting with Sarah. You say: "What did Sarah and I discuss last week?"

Granola MCP:
1. Searches local transcript database for meetings with Sarah
2. Returns 2 meetings from last week
3. Extracts key topics: roadmap planning, hiring timeline, Q1 goals
4. Dex summarizes: "Last week you discussed Q1 roadmap priorities. Sarah mentioned hiring concerns for the design team. Follow up on design headcount."

**Tools:** `granola_get_recent_meetings`, `granola_search_meetings`, `granola_get_meeting_details`

---

### Career MCP (`career_server.py`)

**What it does:**  
Data aggregation engine for career development. Scans evidence files, parses career ladder, maps evidence to competencies, tracks growth trends over time.

**Why it's an MCP:**  
Career assessments require reading 20-50 evidence files, parsing a career ladder doc, and performing fuzzy matching. Doing this with raw LLM reads is slow, expensive, and inconsistent. The Career MCP pre-processes everything into structured stats.

**Power:**
- **10x faster assessments** - Scans all evidence in milliseconds vs 10+ seconds reading each file
- **Competency coverage analysis** - Maps your evidence to career ladder requirements automatically
- **Trend tracking** - "You captured 8 achievements in Q4 vs 3 in Q3 (growth velocity: accelerating)"
- **Gap identification** - "Strong evidence for Product Strategy (8 examples), weak for Technical Depth (2 examples)"
- **Staleness detection** - Flags competencies with no evidence in 90+ days
- **Work integration** - Scans completed goals/priorities as evidence candidates
- **Promotion readiness scoring** - Calculates 0-100 score based on evidence coverage, work delivery, skills, and time in role

**Real-world example:**  
You run `/career-coach` → Promotion Assessment.

Career MCP:
1. Calls `scan_evidence()` → "42 files, 15 in last quarter"
2. Calls `parse_ladder()` → "8 competencies for Senior → Staff transition"
3. Calls `analyze_coverage()` → Generates coverage map:
   - Product Strategy: 8 examples (strong)
   - Technical Depth: 2 examples (weak)
   - Team Leadership: 5 examples (moderate)
4. Calls `timeline_analysis()` → "Evidence velocity increasing, competency trends stable"
5. Calls `promotion_readiness_score()` → "67/100 - Nearly Ready"

Claude receives structured data and coaches: "You're close to promotion readiness (67/100). Your Product Strategy evidence is strong, but Technical Depth needs more documentation. Let's capture 2-3 examples from your recent system design work..."

**Tools:** `scan_evidence`, `parse_ladder`, `analyze_coverage`, `timeline_analysis`, `scan_work_for_evidence`, `skills_gap_analysis`, `generate_evidence_from_work`, `promotion_readiness_score`

**Documentation:** See `core/mcp/CAREER_MCP_README.md` for architecture details.

---

### Resume MCP (`resume_server.py`)

**What it does:**  
Stateful resume building engine with validation, formatting, and career evidence integration. Manages resume sessions, enforces 2-page limit, validates achievement metrics, generates LinkedIn profiles.

**Why it's an MCP:**  
Resume building requires multi-step state (add roles → add achievements → generate bullets → compile resume). Without MCP, the LLM would lose context between steps. The Resume MCP maintains session state and enforces constraints automatically.

**Power:**
- **Session management** - Pause and resume resume building across multiple conversations
- **Metric validation** - Enforces quantifiable metrics: "Improved performance by 40%", "Reduced costs by $50K"
- **Career evidence integration** - Auto-pulls achievements from your Career Evidence files
- **2-page enforcement** - Calculates estimated pages and prevents bloat
- **Bullet quality scoring** - Rates each bullet on impact, specificity, and metrics (0-100 score)
- **ATS optimization** - Checks keyword density for applicant tracking systems
- **LinkedIn generation** - Creates headline (220 char) and about section (2600 char) with character limits enforced

**Real-world example:**  
You run `/resume-builder`.

Resume MCP workflow:
1. `start_session()` → Creates session `resume_20260128_143022`
2. You add role: "Senior PM at Acme Corp, 2023-01 to present"
3. `add_role()` → Validates dates, assigns `role_001`
4. `pull_career_evidence()` → Finds 12 achievements from Career Evidence matching this timeframe
5. You select 5 achievements → `extract_achievements()` validates metrics (must have numbers!)
6. `generate_role_writeup()` → Formats bullets, scores each (avg quality: 87/100)
7. `compile_resume()` → Generates full resume, estimates 1.8 pages, calculates ATS score: 92/100
8. `generate_linkedin()` → Creates LinkedIn content with enforced character limits
9. `export_resume()` → Saves to `05-Areas/Career/Resume/2026-01-28 - Resume.md`

Sessions auto-save after each step. You can resume later with `load_session()`.

**Tools:** `start_session`, `list_sessions`, `load_session`, `add_role`, `extract_achievements`, `pull_career_evidence`, `generate_role_writeup`, `compile_resume`, `generate_linkedin`, `validate_metrics`, `export_resume`

---

### Dex Improvements MCP (`dex_improvements_server.py`)

**What it does:**  
Capture and track Dex system improvement ideas with automatic duplicate detection. Powers the `/dex-backlog` workflow.

**Why it's an MCP:**  
You want to capture improvement ideas from any context (during reviews, while planning, mid-conversation) without context switching. The Dex Improvements MCP provides instant capture with automatic ID generation and similarity checking.

**Power:**
- **Quick capture** - One command, idea stored with unique ID and metadata
- **Duplicate prevention** - Fuzzy matching detects similar ideas before creating duplicates
- **Category organization** - Auto-organizes by workflows, automation, tasks, projects, etc.
- **Implementation tracking** - Mark ideas as implemented and archive them
- **Backlog statistics** - View ideas by category, priority, and implementation status

**Real-world example:**  
During `/review`, you realize: "I keep forgetting to check task dependencies. We should auto-suggest blocked-by relationships."

You mention this → Dex Improvements MCP:
1. Generates ID `idea-042`
2. Checks for similar ideas → finds `idea-019: "Link related tasks together"` (65% similarity)
3. Asks: "Similar to idea-019. Is this different or an extension?"
4. You confirm it's different
5. Saves to `System/Dex_Backlog.md` with category: `tasks`
6. Next time you run `/dex-backlog`, AI ranks it against other ideas

Later, when you implement it, call `mark_implemented(idea-042)` and it moves to the archive.

**Tools:** `capture_idea`, `list_ideas`, `get_idea_details`, `mark_implemented`, `get_backlog_stats`

---

### Onboarding MCP (`onboarding_server.py`)

**What it does:**  
Stateful onboarding system with validation enforcement. Manages new user setup with session state, step validation, and automatic vault creation.

**Why it's an MCP:**  
Onboarding requires bulletproof validation (email domain is mandatory), session persistence (resume if interrupted), and complex dependencies (Python packages, Calendar.app, Granola). An MCP enforces these requirements systematically vs. ad-hoc validation in prompts.

**Power:**
- **Session management** - Resume onboarding if interrupted without starting over
- **Validation enforcement** - Cannot skip required fields (especially Step 4: email domain)
- **Dependency checking** - Verifies Python packages and Calendar.app before finalization
- **Automatic configuration** - Creates PARA folders and generates MCP configs with VAULT_PATH substitution
- **Pre-analysis** - Analyzes calendar and Granola data during setup for dramatic reveal

**Real-world example:**  
New user runs onboarding → provides name, role, company size → **tries to skip email domain** → Onboarding MCP blocks progression: "Email domain is required for Internal/External person routing." → User provides domain → continues → finalization creates vault structure, configures MCPs, analyzes existing calendar/Granola data → reveals insights: "Found 47 meetings, 12 unique people, 3 external companies. Already created person pages for your top 3 contacts."

**Tools:** `start_onboarding_session`, `validate_and_save_step`, `get_onboarding_status`, `verify_dependencies`, `finalize_onboarding`, `check_onboarding_complete`

---

### Update Checker MCP (`update_checker.py`)

**What it does:**  
GitHub update detection for `/dex-update` and `/dex-rollback`. Checks Dex repository for new releases, parses changelogs, and manages version comparison.

**Why it's an MCP:**  
Update checking requires structured version tracking, git operations, changelog parsing, and rollback state management. MCP provides consistent interface for update workflows vs. shell scripts with unpredictable outputs.

**Power:**
- **Version comparison** - Detects if updates are available from GitHub
- **Changelog parsing** - Extracts release notes and breaking changes
- **Safe updates** - One-command updates with automatic backups
- **Rollback support** - Undo last update if something goes wrong
- **Breaking change detection** - Flags releases requiring user action

**Real-world example:**  
User runs `/dex-update` → Update Checker MCP checks GitHub → finds v2.1.0 with new features → shows changelog with "Added Obsidian integration, improved onboarding" → user confirms → creates backup → pulls updates → installs dependencies → success message with "Run `/getting-started` to explore new features."

**Tools:** `check_for_updates`, `get_changelog`, `perform_update`, `create_backup`, `rollback_update`

---

### Supported Integrations

| Integration | MCP Server | Status |
|-------------|------------|--------|
| Apple Calendar | `calendar_server.py` | Built-in |
| Granola | `granola_server.py` | Built-in |
| Work | `work_server.py` | Built-in (always enabled) |
| Dex Improvements | `dex_improvements_server.py` | Built-in |
| Career | `career_server.py` | Built-in |
| Resume | `resume_server.py` | Built-in |
| Onboarding | `onboarding_server.py` | Built-in |
| Update Checker | `update_checker.py` | Built-in |
| Dex Improvements | `dex_improvements_server.py` | Built-in |
| Pendo | Hosted (OAuth) | External (optional) |

### Setting Up Integrations

Run `/daily-plan --setup` to configure integrations interactively, or add MCP servers manually to Claude Desktop config at `~/Library/Application Support/Claude/claude_desktop_config.json`.

See `System/.mcp.json.example` for a complete config with all built-in servers:
- `work_server.py` - Task management (always enabled)
- `calendar_server.py` - Apple Calendar integration
- `granola_server.py` - Meeting notes integration
- `career_server.py` - Career development tracking
- `resume_server.py` - Resume building
- `dex_improvements_server.py` - System improvement backlog
- `onboarding_server.py` - Stateful onboarding with validation
- `update_checker.py` - GitHub update detection

**External integrations (optional):**
- Pendo MCP - Hosted by Pendo with OAuth (https://support.pendo.io/hc/en-us/articles/41102236924955)

Example config:

```json
{
  "mcpServers": {
    "work-mcp": {
      "command": "python",
      "args": ["/path/to/dex/core/mcp/work_server.py"],
      "env": { "VAULT_PATH": "/path/to/dex" }
    },
    "dex-improvements-mcp": {
      "command": "python",
      "args": ["/path/to/dex/core/mcp/dex_improvements_server.py"],
      "env": { "VAULT_PATH": "/path/to/dex" }
    }
  }
}
```

### Creating Custom Integrations

Run `/create-mcp` to create a new MCP server integration through a guided wizard. No coding required — describe what you want to connect, and the wizard will:
1. Design the integration with you
2. Generate the MCP server code
3. Update CLAUDE.md and System Guide
4. Provide setup instructions

### Naming Your Custom MCP Servers (Important for Updates)

When creating custom MCP servers, **use the `user-` or `custom-` prefix** in the server name:

```json
{
  "mcpServers": {
    "user-gmail": { ... },
    "custom-notion": { ... },
    "user-salesforce": { ... }
  }
}
```

**Why this matters:**

When you run `/dex-update`, Dex preserves any MCP entries named `user-*` or `custom-*`. Your custom integrations will never be overwritten by updates.

If you name an MCP server without this prefix (e.g., `gmail-mcp`) and a future Dex update adds a server with the same name, you'll be asked which version to keep. Using the prefix avoids this conflict entirely.

---

## Background Automation

Dex includes background automation that runs independently of Claude/Cursor, enabling the system to learn continuously.

### Anthropic Changelog Monitoring

**Script:** `.scripts/check-anthropic-changelog.cjs`  
**Frequency:** Every 6 hours (via Launch Agent)  
**Purpose:** Monitor Anthropic's changelog for new Claude Code features

**How it works:**
1. Reads `System/claude-code-state.json` to get last check date
2. Fetches Anthropic changelog via HTTPS
3. Detects new versions or updates since last check
4. If changes found:
   - Writes alert to `System/changelog-updates-pending.md`
   - Updates `claude-code-state.json` with latest version and check date
5. Session start hook displays prompt to run `/dex-whats-new`

**Manual testing:**
```bash
node .scripts/check-anthropic-changelog.cjs --force    # Force check
node .scripts/check-anthropic-changelog.cjs --dry-run  # Preview mode
```

### Learning Review Prompts

**Script:** `.scripts/learning-review-prompt.sh`  
**Frequency:** Daily at 5pm (via Launch Agent)  
**Purpose:** Remind user to review accumulated session learnings

**How it works:**
1. Scans `System/Session_Learnings/` for files from past 7 days
2. Counts learnings with `**Status:** pending`
3. If 5+ pending learnings:
   - Writes reminder to `System/learning-review-pending.md`
   - Session start hook displays count and suggests `/dex-whats-new --learnings`
4. If <5 pending, removes any existing reminder file

**Manual testing:**
```bash
bash .scripts/learning-review-prompt.sh
```

### Installation

Install both background automations:

```bash
bash .scripts/install-learning-automation.sh
```

This installs two macOS Launch Agents:
- `com.dex.changelog-checker.plist` - Runs every 6 hours
- `com.dex.learning-review.plist` - Runs daily at 5pm

**Verify installation:**
```bash
launchctl list | grep com.dex
```

**View logs:**
```bash
tail -f .scripts/logs/changelog-checker.log
tail -f .scripts/logs/learning-review.log
```

**Uninstall:**
```bash
bash .scripts/install-learning-automation.sh --uninstall
```

### Architecture Pattern

These background scripts follow the same pattern as Granola automation (`.scripts/meeting-intel/sync-from-granola.cjs`):
- No LLM/API required - pure data processing
- Deterministic, fast execution
- Write alert files that session hooks detect
- Extensive logging for debugging
- Safe: Only reads/writes within vault, no external side effects
