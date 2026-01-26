# /daily-plan Command

## Purpose

Generate your daily plan with full context awareness. Automatically gathers information from your calendar, tasks, meetings, and relationships to create a focused plan.

## Usage

- `/daily-plan` — Create today's daily plan
- `/daily-plan tomorrow` — Plan for tomorrow (evening planning)
- `/daily-plan --setup` — Re-run integration setup

---

## Step 0: Demo Mode Check

Before anything else, check if demo mode is active:

1. Read `System/user-profile.yaml`
2. Check `demo_mode` value
3. **If `demo_mode: true`:**
   - Display banner: "Demo Mode Active — Using sample data from System/Demo/"
   - Use these paths instead of normal paths:
     - `System/Demo/Tasks.md` instead of `Tasks.md`
     - `System/Demo/Inbox/` instead of `Inbox/`
     - `System/Demo/People/` instead of `People/`
     - `System/Demo/Active/` instead of `Active/`
   - Skip calendar/Granola integrations (use demo meeting data)
   - Write output to `System/Demo/Inbox/Daily_Plans/`
4. **If `demo_mode: false`:** Proceed normally

---

## Step 0.5: Integration Check

Before generating the plan, check if integrations are configured.

### Check Logic

1. Read `System/integration_status.yaml`
2. If file missing OR `setup_complete: false`:
   - Trigger guided setup (Step 0.5)
3. Otherwise:
   - Proceed to context gathering (Step 1)

---

## Step 0.5: Guided Integration Setup (First Run Only)

> "Before I create your daily plan, let me check what tools you use. This helps me give you better context."

### Question 1: Calendar

> "Which calendar do you use?"
> 1. Apple Calendar (includes synced Google Calendar accounts)
> 2. Google Calendar (direct, requires OAuth)
> 3. Neither / I'll add it later

**If Apple Calendar:**
- Verify Calendar MCP is configured in Claude settings
- Test with `calendar_list_calendars` tool
- Ask: "Which calendar should I check for work meetings?" (list available calendars)
- Save calendar name to integration_status.yaml

**If Google Calendar:**
- Note: Apple Calendar can sync Google accounts - recommend that path
- If user insists on direct: Provide OAuth setup instructions

**If Neither:**
- Mark calendar integration as disabled
- Plan will work without meeting context

### Question 2: Meeting Notes

> "Do you use Granola for meeting notes?"
> 1. Yes, I have Granola installed
> 2. No, I take manual meeting notes
> 3. What's Granola?

**If Granola:**
- Check if Granola cache exists at `~/Library/Application Support/Granola/cache-v3.json`
- If exists: Mark granola as enabled
- If not: Provide guidance on installing Granola

**If Manual:**
- Note that meeting notes can be placed in `Inbox/Meetings/`
- Mark granola as disabled

### Question 3: Tasks

> "Are you using Dex's built-in task system (Tasks.md)?"
> 1. Yes (recommended)
> 2. No, I use an external tool

**If Yes:**
- Confirm Task MCP is working: `list_tasks`

**If No:**
- Ask what tool they use
- Note for future integration possibility

### Save Configuration

After setup, create/update `System/integration_status.yaml`:

```yaml
setup_complete: true
last_setup: YYYY-MM-DD

integrations:
  calendar:
    enabled: true/false
    type: apple  # or google, or none
    calendar_name: "user@example.com"
    mcp_configured: true/false
    
  granola:
    enabled: true/false
    cache_path: "~/Library/Application Support/Granola/cache-v3.json"
    
  tasks:
    enabled: true
    type: dex  # built-in
```

---

## Step 1: Yesterday's Review Check (Soft Gate)

Unlike a hard block, this is a gentle check:

1. Calculate yesterday's date (skip weekends if not a work day)
2. Look for `Inbox/Daily_Reviews/Daily_Review_YYYY-MM-DD.md`
3. **If exists:** Extract context:
   - Open Loops → Items that need attention today
   - Tomorrow's Focus → Today's starting point
   - Blocked items → Check if resolved
4. **If missing:** Warn but continue:
   > "I notice yesterday's review is missing. I can still plan today, but you might want to run `/review` later to capture what you accomplished."

---

## Step 2: Context Gathering

Gather context from all available sources in parallel:

### From Calendar (if enabled)

```
Use: calendar_get_events_with_attendees for today
```

Extract:
- Today's meetings with times
- Attendees (for People/ lookup)
- Back-to-back meeting detection
- Free time blocks

### From Granola (if enabled)

Check for recent meeting notes that might have action items.

### From Tasks.md

```
Use: list_tasks with status filter
```

Extract:
- P0 items (must do)
- P1 items (important)
- Started but not completed
- Overdue items

### From Week Priorities

Read `Inbox/Week Priorities.md`:
- This week's Top 3
- Key meetings
- Pillar balance check

### From People/

For each meeting attendee:
- Look up `People/External/` or `People/Internal/`
- Surface recent context, open items with them

---

## Step 3: Synthesis

Combine all gathered context into recommendations:

### Focus Recommendation

Based on:
- P0 tasks (highest weight)
- Yesterday's "Tomorrow Focus"
- Meeting prep needs
- Week Priorities alignment

Generate 3 recommended focus items.

### Meeting Prep

For each meeting:
- Who's attending (with People/ context)
- Related tasks or projects
- Suggested prep if none exists

### Heads Up

Flag potential issues:
- Back-to-back meetings
- P0 items with no time blocked
- People you owe follow-ups to

---

## Step 4: Generate Daily Plan

Create `Inbox/Daily_Plans/YYYY-MM-DD.md`:

```markdown
---
date: YYYY-MM-DD
type: daily-plan
integrations_used: [calendar, tasks, people]
---

# Daily Plan — {{Day}}, {{Month}} {{DD}}

## TL;DR
- {{1-2 sentence summary}}
- {{X}} meetings today
- {{Key focus area}}

---

## Carried From Yesterday

> From yesterday's review (if exists)

### Open Loops
- [ ] {{Items from yesterday's review}}

### Yesterday's Focus → Today's Starting Point
1. {{Priority 1}}
2. {{Priority 2}}

---

## Today's Focus

**If I only do three things today:**

1. [ ] {{Focus item 1}} — {{Pillar}}
2. [ ] {{Focus item 2}} — {{Pillar}}
3. [ ] {{Focus item 3}} — {{Pillar}}

---

## Schedule

| Time | Meeting/Block | Who | Prep |
|------|---------------|-----|------|
| {{Time}} | {{Meeting}} | {{Attendees}} | {{Prep link or "None needed"}} |
| ... | ... | ... | ... |

### Free Blocks
- {{Time range}}: {{Suggested use}}

---

## Tasks by Priority

### P0 - Must Do Today
- [ ] {{Task}}

### P1 - Important
- [ ] {{Task}}

### P2 - If Time Allows
- [ ] {{Task}}

---

## People Context

### Meeting with {{Name}}
- Role: {{From People/ page}}
- Last interaction: {{Date}}
- Open items: {{Any pending tasks involving them}}

---

## Heads Up

{{Flags and warnings}}

- ⚠️ Back-to-back meetings from X to Y
- ⏰ P0 item "{{task}}" has no time blocked
- 📞 You owe {{Name}} a follow-up from {{Date}}

---

*Generated: {{timestamp}}*
*Integrations: {{list}}*
```

---

## Graceful Degradation

The plan works at multiple levels:

### Full Context (Calendar + Granola + Tasks + People)
- Complete schedule with attendee lookup
- Meeting prep suggestions
- Relationship context

### Partial Context (Tasks + People only)
- Focus recommendations from tasks
- No schedule section
- Still useful for prioritization

### Minimal Context (Tasks only)
- Basic focus list
- Task priorities
- Prompt for manual schedule input

### No Context (Nothing configured)
- Interactive flow asking about priorities
- Creates basic daily note
- Encourages setting up integrations

---

## Evening Planning Variant

`/daily-plan tomorrow`:

1. Check for evening journal (if journaling enabled)
2. Gather tomorrow's calendar
3. Review unfinished tasks from today
4. Generate tomorrow's draft plan
5. Save as `Inbox/Daily_Plans/YYYY-MM-DD-draft.md`

---

## MCP Dependencies

| Integration | MCP Server | Tools Used |
|-------------|------------|------------|
| Calendar | dex-calendar-mcp | `calendar_get_today`, `calendar_get_events_with_attendees` |
| Granola | dex-granola-mcp | `get_recent_meetings` |
| Tasks | dex-task-mcp | `list_tasks`, `suggest_focus` |

---

## Setup Instructions

### Calendar MCP Setup

1. Ensure `core/mcp/calendar_server.py` exists
2. Add to Claude Desktop config at `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "dex-calendar": {
      "command": "python",
      "args": ["/path/to/dex/core/mcp/calendar_server.py"],
      "env": {
        "VAULT_PATH": "/path/to/dex"
      }
    }
  }
}
```

3. Restart Claude Desktop
4. Run `/daily-plan --setup` to configure

### Granola MCP Setup

1. Install Granola app (macOS only)
2. Ensure `core/mcp/granola_server.py` exists
3. Add to Claude Desktop config (same file, similar pattern)
4. Granola will auto-detect from local cache at `~/Library/Application Support/Granola/cache-v3.json`
