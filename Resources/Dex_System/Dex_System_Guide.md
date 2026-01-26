# Dex System Guide

**Personal Reference** — Full documentation for your Dex knowledge system.

---

## Quick Start (30 Seconds to Value)

```
Morning    → Run /daily-plan for context-aware daily planning
During day → Capture notes in Inbox/
After mtgs → Dex extracts action items and updates person pages
End of day → Run /review
End of week → Run /week
```

---

## Daily Workflows

### Morning Routine

1. Run `/daily-plan` for your daily plan (integrates calendar, meetings, tasks)
2. Check `Inbox/Week Priorities.md` for the week's commitments
3. Review any notes captured yesterday

### During the Day

| Capture Method | Where It Goes | Processing |
|----------------|---------------|------------|
| Meeting notes | `Inbox/Meetings/` | `/triage` extracts action items |
| Quick thoughts | `Inbox/Ideas/` | Review during weekly synthesis |
| Tasks | Tell Claude or add to `Tasks.md` | MCP validates and creates |

### End of Day

```
/review
```

Creates reflection on:
- What got done
- What's carrying over
- Quick wins and blockers
- Tomorrow's priorities

### End of Week

```
/week
```

Creates weekly synthesis:
- Themes across the week
- Energy patterns
- Project progress
- Connections discovered
- Questions that emerged

---

## Command Reference

All commands live in `.claude/commands/`. Run them by typing the command name.

### Core Workflow Commands

| Command | What It Does | When to Use |
|---------|--------------|-------------|
| `/daily-plan` | Context-aware daily plan with calendar and meeting integration | Morning ritual |
| `/daily-plan tomorrow` | Evening planning for next day | Night before |
| `/daily-plan --setup` | Configure integrations (calendar, Granola) | First run or reconfigure |
| `/review` | End-of-day reflection and synthesis | 5pm daily |
| `/week` | Weekly pattern recognition and planning | Friday or Monday |
| `/journal` | Morning, evening, or weekly reflection | Anytime for reflection |
| `/triage` | Structure-aware inbox processing (files + tasks) | Weekly cleanup |
| `/triage files` | Organize files with entity matching | When inbox is full |
| `/triage tasks` | Extract and route tasks to projects/people | After meeting-heavy days |

### Project & Meeting Commands

| Command | What It Does | When to Use |
|---------|--------------|-------------|
| `/project-health` | Review all projects for stalls/blockers | Weekly or when feeling lost |
| `/meeting-prep` | Prepare for upcoming meetings | Before important calls |
| `/process-meetings` | Process unprocessed Granola meetings | After meetings, or batch at end of day |
| `/process-meetings today` | Process only today's meetings | Quick daily catchup |

### System Commands

| Command | What It Does | When to Use |
|---------|--------------|-------------|
| `/dex-improve` | Design partner for system enhancements | When you have improvement ideas |
| `/create-mcp` | Guided wizard to create MCP server integrations | Connect Dex to external services |
| `/whats-new-claude` | Check Claude Code updates | Periodically for new capabilities |
| `/reset` | Restructure your Dex from scratch | Major reorganization |
| `/demo` | Toggle demo mode on/off/reset | Exploring, demoing |
| `/init-bootstrap` | Initial setup wizard | First time only |
| `/prompt-improver` | Optimize prompts for Claude | Before complex prompts |

---


## Demo Mode

Demo mode lets you explore Dex with pre-populated sample content without affecting your real vault.

### Commands

| Command | Effect |
|---------|--------|
| `/demo on` | Enable demo mode - uses sample data |
| `/demo off` | Disable demo mode - use real vault |
| `/demo status` | Check if demo mode is active |
| `/demo reset` | Restore demo content to original state |

### Demo Content

Located in `System/Demo/`, the demo vault includes:

**Alex Chen** - A fictional PM at TechCorp

**Projects:**
- Mobile App Launch (main focus, in progress, some blockers)
- Customer Portal Redesign (just kicked off)
- API Partner Program (early exploration)

**People:**
- Jordan Lee (Engineering Lead, internal)
- Maya Patel (Designer, internal)
- Sarah Chen (Customer champion at Acme Corp)
- Tom Wilson (Exec sponsor at Acme)
- Lisa Park (Beta customer)

**Pre-populated:**
- Week of meeting notes
- Tasks across P0-P3 priorities
- Week Priorities
- Sample daily plan and review

### How Demo Mode Works

When `demo_mode: true` in `System/user-profile.yaml`:

1. **Commands read from `System/Demo/`** instead of root folders
2. **Writes are sandboxed** to the demo folder
3. **Task MCP uses demo data** (`System/Demo/Tasks.md`, `System/Demo/pillars.yaml`)
4. **Your real vault is untouched**

### Use Cases

1. **Onboarding** - Explore commands before adding your own data
2. **Demoing** - Show colleagues how a PKM works
3. **Testing** - Try new workflows without risk

---

## Task System

### Task MCP Server

Dex includes a Python MCP server (`core/mcp/task_server.py`) providing deterministic task operations.

#### Available Tools

| Tool | Purpose |
|------|---------|
| `list_tasks` | List tasks with filters (pillar, priority, status, source) |
| `create_task` | Create task with validation, dedup check, pillar required |
| `update_task_status` | Change status (n=not started, s=started, b=blocked, d=done) |
| `get_system_status` | Task counts, priority distribution, pillar balance |
| `check_priority_limits` | Verify P0/P1/P2 limits aren't exceeded |
| `process_inbox_with_dedup` | Batch process items with duplicate/ambiguity detection |
| `get_blocked_tasks` | List all blocked tasks |
| `suggest_focus` | Top 3 tasks to focus on based on priorities |
| `get_pillar_summary` | Task distribution across your pillars |
| `sync_task_refs` | Refresh Related Tasks section on a page |
| `create_company` | Create a new company page |
| `refresh_company` | Update all aggregated sections on a company page |
| `list_companies` | List all company pages with contact counts |

#### Priority Limits

Prevent overcommitment with built-in guardrails:

| Priority | Limit | Description |
|----------|-------|-------------|
| P0 | 3 | Critical/urgent - only 3 at a time |
| P1 | 5 | Important - max 5 active |
| P2 | 10 | Normal - suggested limit |
| P3 | No limit | Backlog items |

Configure limits in `System/pillars.yaml`.

#### Pillar Alignment

Every task requires pillar assignment. This enforces strategic alignment - random tasks without pillar connection prompt reflection on whether they belong.

Configure your pillars during onboarding or edit `System/pillars.yaml`:

```yaml
pillars:
  - id: pillar_1
    name: "Your First Priority"
    description: "What this pillar covers"
    keywords: [keyword1, keyword2]
```

#### Deduplication

The MCP server prevents duplicates:
- 60% similarity threshold catches near-matches
- Shows existing similar tasks before creating
- Prompts you to review or rephrase

#### Ambiguity Detection

Vague tasks get flagged:
- Less than 3 words
- Patterns like "fix bug", "follow up", "research X"
- Generates clarifying questions to make task actionable

---

## Structure-Aware Triage

Triage doesn't just sort files into categories—it understands your actual folder structure and routes items to specific entities.

### How Discovery Works

When you run `/triage`, it first scans your vault to build an index:

| What It Scans | What It Extracts |
|---------------|------------------|
| `Active/Projects/` | Project names, descriptions, status |
| `People/External/` + `People/Internal/` | Names, roles, companies |
| `Active/Relationships/` | Account names, domains, contacts |
| `System/pillars.yaml` | Pillar names and keywords |

### Entity-Aware Routing

For each inbox item, triage checks in order:

1. **Project match** — Does this mention an existing project? → Route to that project file
2. **Person match** — Is this about a known person? → Route to their page or suggest linking
3. **Company match** — Does this mention a known company or domain? → Route to company page
4. **Pillar match** — Does content match pillar keywords? → Tag with pillar
5. **Category fallback** — No matches → Use standard category rules

### Example Matches

```
"Q1 Mobile App Notes.md"
  Match: PROJECT → "Mobile App Launch"
  → Active/Projects/Mobile_App_Launch.md

"Call with Sarah.md"
  Match: PERSON → "Sarah Chen"
  → People/External/Sarah_Chen.md

"Random product ideas.md"
  Match: PILLAR → "Product Development"
  → Active/Content/ (category fallback)
```

### Evolves With Your Structure

Because discovery happens at runtime:
- Add a new project → triage recognizes it immediately
- Create a person page → triage can route notes to them
- Add a company → meeting notes with that domain get matched

No configuration needed—triage adapts as your system grows.

---

## Folder Structure

```
Dex/
├── Active/                   # Current work (search here first)
│   ├── Projects/             # Time-bound initiatives
│   ├── Relationships/        # Key accounts, partners, stakeholders
│   └── Content/              # Thought leadership, docs you create
│
├── Inbox/                    # Capture zone (process regularly)
│   ├── Meetings/             # Meeting notes
│   ├── Voice_Notes/          # Quick captures
│   ├── Ideas/                # Fleeting thoughts
│   └── Week Priorities.md    # Current week's tasks
│
├── Resources/                # Reference material
│   ├── Dex_System/           # This documentation
│   ├── Claude_Code_Docs/     # Claude Code capability reference
│   └── Learnings/            # Compound knowledge
│
├── People/                   # Person pages
│   ├── Internal/             # Colleagues
│   └── External/             # Customers, partners, contacts
│
├── Active/Relationships/
│   └── Companies/            # Company pages (aggregated context)
│
├── System/                   # Configuration
│   ├── Templates/            # Note templates
│   ├── Skills/               # Reusable AI behaviors
│   └── pillars.yaml          # Your strategic pillars
│
├── Tasks.md                  # Main task list
└── CLAUDE.md                 # System configuration
```

---

## Templates

19 templates in `System/Templates/` for common note types:

| Template | Use Case |
|----------|----------|
| `Daily_Note.md` | Daily plan structure |
| `Morning_Journal.md` | Morning reflection prompts |
| `Evening_Journal.md` | End-of-day reflection |
| `Weekly_Journal.md` | Weekly reflection prompts |
| `Weekly_Review.md` | Week synthesis structure |
| `Meeting_Notes.md` | Meeting capture format |
| `One_on_One.md` | 1:1 meeting structure |
| `Person_Page.md` | Person page template |
| `Company.md` | Company page template |
| `Project.md` | Project tracking structure |
| `Account_Overview.md` | Key account page |
| `Decision_Log.md` | Decision documentation |
| `Idea_Capture.md` | Idea development |
| `Retrospective.md` | Team/project retro |
| `Quarterly_Review.md` | Quarterly reflection |
| `Deal_Memo.md` | Investment committee memo (VC/PE) |
| `DD_Checklist.md` | Due diligence checklist (VC/PE) |
| `Board_Prep.md` | Board meeting preparation |
| `Portfolio_Company.md` | Portfolio company tracking (VC/PE) |

---

## Skills System

Skills are reusable AI behaviors in `System/Skills/`.

### Current Skills

| Skill | Purpose |
|-------|---------|
| `person-lookup.md` | Protocol for checking People folder before searches |

---

## Company Pages

Company pages aggregate context about organizations you interact with.

### Location

```
Active/Relationships/Companies/
├── Acme_Corp.md
├── BigTech_Inc.md
└── ...
```

### What Gets Aggregated

| Section | Source | How It Works |
|---------|--------|--------------|
| **Key Contacts** | Person pages | People with matching `Company Page` field |
| **Meeting History** | `Inbox/Meetings/` | Meetings where attendee emails match company domains |
| **Related Tasks** | `Tasks.md` | Tasks that reference the company page |

### MCP Tools for Companies

| Tool | Purpose |
|------|---------|
| `create_company` | Create a new company page with basic info |
| `refresh_company` | Update all aggregated sections (contacts, meetings, tasks) |
| `list_companies` | List all company pages with contact counts |

### Linking People to Companies

Add the `Company Page` field to person pages:

```markdown
| **Company Page** | Active/Relationships/Companies/Acme_Corp.md |
```

When you run `refresh_company`, all people with this field will appear in the company's Key Contacts section.

### Domain Matching

Add domains to company pages for automatic meeting detection:

```markdown
| **Domains** | acme.com, acmecorp.com |
```

Meetings with attendees from these email domains will appear in Meeting History.

### Example Workflow

1. Create company: `create_company("Acme Corp", website="acme.com")`
2. Link people: Add `Company Page` field to relevant person pages
3. Refresh: `refresh_company("Acme_Corp")` - pulls in contacts, meetings, tasks
4. Before meetings: Check company page for full context

### How Skills Work

Skills define consistent behaviors Claude follows. When a skill is relevant, Claude applies its protocol automatically.

---

## Learnings Library

Compound knowledge in `Resources/Learnings/`:

| File | Contents |
|------|----------|
| `Mistake_Patterns.md` | Logged mistakes become rules preventing repetition |
| `Working_Preferences.md` | Collaboration style captured across sessions |

### Adding Learnings

When something works well or you discover a preference:
1. Tell Claude what you learned
2. It adds to the appropriate Learnings file
3. Future sessions benefit automatically

---

## File Conventions

### Naming

| Type | Format | Example |
|------|--------|---------|
| Daily notes | `YYYY-MM-DD - Topic` | `2026-01-22 - Weekly Planning` |
| Meeting notes | `YYYY-MM-DD - Meeting Topic.md` | `2026-01-22 - Q1 Review.md` |
| Person pages | `Firstname_Lastname.md` | `Sarah_Chen.md` |

### Date Format

Always use `YYYY-MM-DD` for consistency and sorting.

### File Paths

Use plain paths for references: `People/External/Sarah_Chen.md`

---

## Integration Options

Dex includes built-in MCP servers and can work with additional integrations.

### Built-in Integrations

| Integration | MCP Server | What It Enables |
|-------------|------------|-----------------|
| **Apple Calendar** | `calendar_server.py` | Meeting schedule, attendee context, free time blocks |
| **Granola** | `granola_server.py` | Meeting transcripts, notes, action items |
| **Tasks** | `task_server.py` | Task management, priorities, pillar alignment |

### Integration Status

Configuration is tracked in `System/integration_status.yaml`. On first run of `/daily-plan`, you'll be guided through setup:

1. **Calendar**: Which calendar to use for work meetings
2. **Granola**: Whether you have Granola installed for meeting notes
3. **Tasks**: Built-in, always enabled

Run `/daily-plan --setup` to reconfigure integrations anytime.

### Calendar MCP Tools

| Tool | Purpose |
|------|---------|
| `calendar_list_calendars` | List all available calendars |
| `calendar_get_today` | Get today's meetings |
| `calendar_get_events_with_attendees` | Get events with attendee details and People/ lookup |
| `calendar_create_event` | Create a new calendar event |
| `calendar_search_events` | Search events by title |

### Granola MCP Tools

| Tool | Purpose |
|------|---------|
| `granola_check_available` | Check if Granola is installed |
| `granola_get_recent_meetings` | Get recent meeting notes |
| `granola_get_today_meetings` | Get today's meetings with notes |
| `granola_search_meetings` | Search by title, notes, or attendee |
| `granola_get_meeting_details` | Get full transcript and action items |

### Meeting Intelligence

Dex processes meetings from Granola to extract structured insights, action items, and update person pages. Choose between manual and automatic processing.

#### Manual Processing (Recommended to Start)

Run `/process-meetings` whenever you want to pull in new meetings. Uses Claude directly — no API key required.

| Command | What It Does |
|---------|--------------|
| `/process-meetings` | Process all unprocessed meetings (last 7 days) |
| `/process-meetings today` | Just today's meetings |
| `/process-meetings "Acme"` | Find and process specific meeting |

**What gets extracted:**
- Summary (2-3 sentences)
- Key discussion points
- Decisions made
- Action items (for you and others)
- Customer intelligence (pain points, feature requests, competitive mentions)
- Pillar classification

**Output:**
- Meeting notes: `Inbox/Meetings/YYYY-MM-DD/meeting-slug.md`
- Person pages updated with meeting references

#### Automatic Processing (Background Sync)

For hands-off processing, enable automatic mode during onboarding or configure manually:

1. **Choose API provider:**
   - **Gemini** — Free tier (1500 req/day), best for most users
   - **Anthropic** — Highest quality (~$0.01/meeting)
   - **OpenAI** — Fast and reliable (~$0.01/meeting)

2. **Add API key to `.env`:**
   ```bash
   echo "GEMINI_API_KEY=your-key" >> .env
   # or ANTHROPIC_API_KEY or OPENAI_API_KEY
   ```

3. **Enable automation:**
   ```bash
   npm install
   ./.scripts/meeting-intel/install-automation.sh
   ```

**Automatic mode:**
- Runs every 30 minutes via macOS Launch Agent
- Processes new meetings even when Cursor is closed
- Generates daily digests with cross-meeting themes

**Manual commands for automatic mode:**

| Command | Purpose |
|---------|---------|
| `node .scripts/meeting-intel/sync-from-granola.cjs` | Process now |
| `node .scripts/meeting-intel/sync-from-granola.cjs --dry-run` | Preview |
| `./.scripts/meeting-intel/install-automation.sh --status` | Check status |

#### Configuration

Edit `System/user-profile.yaml` to control:
- Processing mode (manual/automatic)
- API provider for automatic mode
- What intelligence to extract (customer intel, competitive intel, etc.)

Meetings are automatically classified into your pillars from `System/pillars.yaml`.

### Additional Integrations

| Integration | What It Enables |
|-------------|-----------------|
| **Email** | Message search, draft assistance |
| **CRM** | Account context, deal tracking |
| **Slack** | Channel context, message search |

### Creating Custom MCP Integrations

Run `/create-mcp` to create a new MCP server integration. The wizard will:

1. **Educate** — Explain what MCP servers do and their benefits
2. **Gather requirements** — Understand what service you want to connect and how
3. **Design tools** — Define the specific capabilities iteratively with you
4. **Generate code** — Create a working MCP server in `core/mcp/`
5. **Integrate** — Update CLAUDE.md and this guide so Dex knows how to use it
6. **Verify** — Provide setup instructions and help you test

**No coding required** — just describe what you want in plain English.

---

## Claude Code Features

Dex leverages these Claude Code capabilities. For deeper understanding:

| Feature | What It Does | Learn More |
|---------|--------------|------------|
| **Commands** | User-triggered workflows (the `/` commands) | [Slash Commands](https://docs.anthropic.com/en/docs/claude-code/slash-commands) |
| **Hooks** | Auto-trigger actions at specific moments | [Hooks](https://docs.anthropic.com/en/docs/claude-code/hooks) |
| **Skills** | Reusable behaviors available in any session | [Skills](https://docs.anthropic.com/en/docs/claude-code/skills) |
| **Sub-agents** | Parallel workers with focused tasks | [Sub-agents](https://docs.anthropic.com/en/docs/claude-code/sub-agents) |
| **MCP** | Connect to external services | [MCP Introduction](https://modelcontextprotocol.io/introduction) |

### Using `/dex-improve`

When you have ideas for system improvements, `/dex-improve` acts as a capability-aware design partner:

1. Parses your idea and identifies affected areas
2. Checks Claude Code capabilities to find best implementation
3. Suggests related improvements you might not have considered
4. Creates implementation plan in `plans/`

---

## Size-Based Adjustments

Complexity scales with your organization size (set during onboarding):

**1-100 (Startup)**
- Lean structure, fewer folders
- Action-biased, less process
- Generalist focus

**100-1k (Scaling)**
- Cross-functional templates
- Process documentation
- Scaling playbooks

**1k-10k (Enterprise)**
- Stakeholder maps
- Governance docs
- More formal structure

**10k+ (Large Enterprise)**
- Influence tracking
- Political navigation notes
- Strategic focus over tactical

---

## Maintenance

This guide stays current through the Documentation Sync behavior in CLAUDE.md. When significant system changes happen (new commands, behaviors, workflows), this guide updates automatically.

**Rule of thumb**: If someone reading only this guide would miss something important about how to use the system, it needs updating.

---

## Related Documentation

- `CLAUDE.md` — Core system configuration and behaviors
- `Resources/Dex_System/Dex_Jobs_to_Be_Done.md` — Why the system exists (conceptual)
- `System/pillars.yaml` — Your strategic pillars configuration
- `.claude/commands/` — Command definitions

---

*This guide covers how to use Dex. For why it exists, see the Jobs to Be Done document.*
