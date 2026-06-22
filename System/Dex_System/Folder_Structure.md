# Dex Folder Structure (PARA Method)

Dex uses the PARA method for organization: **Projects**, **Areas**, **Resources**, and **Archives**.

## What is PARA?

PARA organizes information by **actionability**:

- **Projects** = time-bound work with clear outcomes (has an end date)
- **Areas** = ongoing responsibilities (never "finish")
- **Resources** = reference material you consult
- **Archives** = inactive items for historical reference

---

## Structure Overview

Dex creates this structure during onboarding (adapted to your role):

```
Dex/
├── 04-Projects/                 # Time-bound initiatives
├── 05-Areas/                    # Ongoing responsibilities
│   ├── People/               # Person pages
│   │   ├── Internal/         # Colleagues (same email domain)
│   │   └── External/         # Customers, partners (different domain)
│   ├── Companies/            # External organizations (universal)
│   ├── Career/               # Career development (via /career-setup)
│   └── [Role-specific]/     # Accounts/, Team/, Content/, etc.
├── 06-Resources/                # Reference material
│   ├── Dex_System/           # System documentation
│   ├── Learnings/            # Compound knowledge
│   └── Quarterly_Reviews/    # Quarterly reflection and strategic reviews
├── 07-Archives/                 # Historical records
│   ├── Projects/             # Completed projects
│   ├── Plans/                # Archived daily/weekly plans
│   └── Reviews/              # Archived reviews
├── 00-Inbox/                    # Capture zone
│   ├── Meetings/             # Meeting notes
│   └── Ideas/                # Quick captures
├── System/                      # Configuration
│   ├── Templates/            # Note templates
│   ├── pillars.yaml          # Strategic pillars
│   ├── user-profile.yaml     # User preferences
│   └── Dex_Backlog.md        # System improvement backlog
├── 03-Tasks/                    # Task management
│   └── Tasks.md              # Main task backlog
├── 01-Quarter_Goals/            # Quarterly planning (optional)
│   └── Quarter_Goals.md      # Current quarter's 3-5 goals
└── 02-Week_Priorities/          # Weekly planning (optional)
    └── Week_Priorities.md    # Current week's Top 3
```

**Note:** The numbered folders (`01-`, `02-`, `03-`) appear after running the respective planning commands (`/quarter-plan`, `/week-plan`, `/triage`). Before then, you'll just see the PARA folders (04-07) plus 00-Inbox/ and System/.

---

## 04-Projects/

**Time-bound initiatives with clear goals and deliverables.**

### What makes something a project?
- Clear outcome (specific deliverable or result)
- End date (defined completion point)
- Active work (you're currently working on it)

### Examples
- Product launches
- Feature development
- Migrations or technical upgrades
- Campaign execution

### When complete
Move to `07-Archives/Projects/` with completion date and learnings.

**Key distinction:**  
Project = has an end ("Ship payments redesign")  
Area = ongoing ("Customer success management")

---

## 05-Areas/

**Ongoing responsibilities that require maintenance but never "finish."**

### Default Areas (Everyone)

- **People/** — Relationships with colleagues, customers, partners
  - `Internal/` — Teammates, managers, cross-functional partners (same email domain)
  - `External/` — Customers, prospects, partners (different email domain)
- **Companies/** — External organizations you interact with

### Role-Specific Areas

Most users only need the universal areas (People and Companies). You can create additional areas as needed for your workflow.

### Career Area (Optional)

Created via `/career-setup` command:
- `Career/` — Career development tracking
  - `Current_Role.md` — Job description and responsibilities
  - `Career_Ladder.md` — Competency framework
  - `Review_History.md` — Performance reviews
  - `Growth_Goals.md` — Long-term career goals
  - `Evidence/` — Achievements, feedback, skills
    - `Achievements/` — Completed work and impact
    - `Feedback/` — Performance feedback received
    - `Skills/` — Skills development tracking

**Key distinction:**  
Area = ongoing ("Manage customer relationships")  
Project = has an end ("Onboard Acme Corp")

---

## 06-Resources/

**Reference material you consult but aren't actively working on.**

```
06-Resources/
├── Dex_System/           # Documentation about how Dex works
│   ├── Dex_Jobs_to_Be_Done.md
│   ├── Dex_System_Guide.md
│   └── Folder_Structure.md (this file)
├── Learnings/            # Compound knowledge (frameworks, lessons learned)
└── Quarterly_Reviews/    # Quarterly reflection and strategic reviews
```

**Note:** Templates are stored in `System/Templates/` for easy access during file creation.

### What belongs here?
- Things you reference repeatedly
- Knowledge that compounds over time
- Context for future decisions
- Lasting value beyond current work

### Examples
- Frameworks and mental models
- Best practices and lessons learned
- Process documentation
- Research and competitive analysis

**Key distinction:**  
Resources = you actively reference this  
Archives = historical record, rarely consulted

---

## 07-Archives/

**Historical records and completed work.**

```
07-Archives/
├── Projects/        # Completed or cancelled projects
├── Plans/           # Daily and weekly plans (auto-archived)
└── Reviews/         # Daily, weekly, and quarterly reviews (auto-archived)
```

### Auto-Archiving

Plans and reviews automatically move here:
- Daily plans → after `/daily-plan` runs
- Daily reviews → after `/daily-review` runs
- Weekly plans → after `/week-plan` runs
- Weekly reviews → after `/week-review` runs
- Quarterly reviews → after `/quarter-review` runs

### Manual Archiving

Projects move here when complete:
- Add completion date and outcome
- Document key learnings
- Keep original filename for searchability

### Retention

Keep archives indefinitely—they're your historical record and learning source for quarterly reviews and career reflections.

---

## 00-Inbox/

**Capture zone for quick notes before you organize them.**

```
00-Inbox/
├── Meetings/        # Meeting notes (auto-created by /process-meetings)
│   └── YYYY-MM-DD/  # Meetings organized by date
└── Ideas/           # Quick captures and random thoughts
```

### Philosophy

Inbox is for **capture, not organization**. Don't worry about structure—just get it down.

### Workflow

1. **Capture** — Drop everything here first
2. **Triage** — Run `/triage` to process and organize
3. **Move** — Files route to Projects/, Areas/, or Resources/

### Inbox Zero

Aim to triage weekly. If something sits 30+ days:
- Not important → delete
- Reference → move to 06-Resources/
- Dormant project → archive

---

## System/

**Configuration and system files.**

```
System/
├── Templates/                # Note templates (5 core templates)
├── Session_Learnings/        # Auto-captured improvements during /review
├── pillars.yaml              # Strategic pillars (your main focus areas)
├── user-profile.yaml         # User preferences and settings
├── claude-code-state.json    # Tracks last changelog check
├── Dex_Backlog.md            # System improvement backlog (AI-ranked)
├── usage_log.md              # Feature adoption tracking (for /dex-level-up)
└── Demo/                     # Demo mode sandbox (if enabled)
```

Most users won't edit this directly—Dex manages it. But when you want to adjust strategic direction or preferences, the key files are here.

**Background automation:** Dex also includes scripts in `.scripts/` that run automatically:
- `check-anthropic-changelog.cjs` — Checks for Claude updates every 6 hours
- `learning-review-prompt.sh` — Daily 5pm check for pending learnings
- These run via macOS Launch Agents and require no user intervention

---

## Planning Hierarchy (Optional)

If you enable quarterly and weekly planning, everything connects from pillars → quarters → weeks → days:

1. **Strategic Pillars** (`System/pillars.yaml`)  
   Your ongoing focus areas—NOT time-bound goals, but the broad themes you'll always focus on (configured during onboarding)

2. **Quarter Goals** (`01-Quarter_Goals/Quarter_Goals.md`)  
   Time-bound outcomes (3 months) advancing pillars (via `/quarter-plan`)

3. **Week Priorities** (`02-Week_Priorities/Week_Priorities.md`)  
   Top 3 this week advancing quarterly goals (via `/week-plan`)

4. **Daily Plan** (`07-Archives/Plans/`)  
   Today's work supporting weekly priorities (auto-archived after `/daily-plan`)

5. **Tasks** (`03-Tasks/Tasks.md`)  
   Backlog tagged with `#pillar [Q1-2] [Week-1]` connecting to goals

**Note:** Weekly planning (`02-Week_Priorities/`) is always available. Quarterly planning (`01-Quarter_Goals/`) is optional and created when you run `/quarter-plan`.

---

## 03-Tasks/ (Task Management)

**Central task backlog managed by Work MCP.**

```
03-Tasks/
└── Tasks.md          # Main task file with priority sections
```

This file is created when you:
- Run `/triage` and extract tasks from meeting notes
- Use Work MCP tools to create tasks
- Run `/daily-plan` (creates if missing)

### Structure

```markdown
# Tasks

## This Week
[Tasks promoted from backlog for this week]

## P0 - Urgent (max 3)
[Critical/urgent tasks]

## P1 - Important (max 5)
[Important tasks]

## P2 - Normal (max 10)
[Normal priority]

## P3 - Backlog
[Lower priority backlog]
```

Tasks sync bidirectionally with person pages, company pages, and meeting notes via task IDs (`^task-YYYYMMDD-XXX`).

---

## Quick Reference

| Folder | Purpose | Lifespan | Created When |
|--------|---------|----------|--------------|
| **04-Projects/** | What you're building | Until project ships | Onboarding |
| **05-Areas/** | Ongoing responsibilities | Indefinite | Onboarding |
| **06-Resources/** | Reference material | Indefinite | Onboarding |
| **07-Archives/** | Historical record | Indefinite | Onboarding |
| **00-Inbox/** | Quick captures | Days (until triaged) | Onboarding |
| **System/** | Configuration | Indefinite | Onboarding |
| **03-Tasks/** | Task backlog | Indefinite | First `/triage` or `/daily-plan` |
| **01-Quarter_Goals/** | Quarterly goals | Per quarter | First `/quarter-plan` |
| **02-Week_Priorities/** | Weekly priorities | Per week | First `/week-plan` |

---

## First Time Setup

New to Dex? Run `/setup` or just ask to start onboarding. The structure will be customized for your role and working style.

The numbered folders (01-, 02-, 03-) appear as you use their respective features. Don't worry if you don't see them immediately—they'll be created when needed.

---

## Demo Mode

Want to explore Dex with sample data before adding your own? Run `/dex-demo on` to work with pre-populated demo content for "Alex Chen," a fictional PM at TechCorp. Demo mode creates a sandboxed `System/Demo/` folder so your real vault stays untouched.

---

## Related Documentation

- `CLAUDE.md` — Core system configuration
- `06-Resources/Dex_System/Dex_Jobs_to_Be_Done.md` — Why the system exists
- `06-Resources/Dex_System/Dex_System_Guide.md` — How to use everything
- `System/pillars.yaml` — Your strategic pillars configuration
