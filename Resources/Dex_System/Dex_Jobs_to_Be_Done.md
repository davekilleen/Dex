# Dex: Jobs to Be Done

**What this system actually does, and why each piece exists.**

This document explains the purpose behind your Dex system. If you're new to the system, start here to understand what problems it solves. As you customize and extend Dex, this document evolves with you.

---

## What This Is

### The Short Version

A personal knowledge system that handles the cognitive overhead of professional life. Notes find their home. Tasks don't slip through cracks. People stay tracked. Your days start focused and end with reflection.

The AI (Claude) acts as your knowledge assistant - helping you capture, organize, and act on information without drowning in process.

### What Makes It Different

Traditional note systems are passive filing cabinets. Dex is active:

- **AI-augmented**: Claude helps process, organize, and surface information
- **Workflow-driven**: Commands guide you through daily and weekly rhythms
- **Task-aware**: MCP server ensures tasks are validated, deduplicated, and prioritized
- **Adaptable**: Pillars and structure customize to your role and priorities

### Your Strategic Pillars

Everything in this system aligns to your strategic priorities. These are configured during onboarding and stored in `System/pillars.yaml`. Tasks without pillar connection prompt you to think about strategic alignment.

---

## The Six Jobs

Each job represents something that needs to happen reliably. The system exists to make these jobs easier or automatic.

---

### Job 1: Capture Without Friction

**The Problem**: Ideas die between having them and recording them. Meeting notes get lost. Quick thoughts evaporate. The best capture system is the one you actually use, and complex workflows get abandoned.

**How Dex Handles It**:

| Component | What It Does |
|-----------|--------------|
| `Inbox/` folder | Universal capture zone - anything goes here first |
| `/triage` command | Processes inbox items, suggests destinations, routes automatically |
| Templates | 14 ready-to-use templates reduce friction for common note types |
| Meeting capture behavior | Extract key points, decisions, action items from notes |

**Example Flow**: During a call, you jot quick notes in `Inbox/Meetings/`. Later, you run `/triage`. Dex analyzes each file, suggests where it belongs (Project? Person page? Archive?), extracts any tasks, and moves things with your approval.

---

### Job 2: Start Each Day Focused

**The Problem**: Without a forcing function, mornings get lost to email triage, calendar anxiety, and context-switching. The urgent wins over the important. You end the day wondering what you actually accomplished.

**How Dex Handles It**:

| Component | What It Does |
|-----------|--------------|
| `/plan` command | Morning ritual that creates a focused daily plan |
| Journal integration | Optional 5-minute reflection before planning |
| Calendar check | Surfaces today's meetings and prep needed |
| Task review | Shows open tasks, priorities, deadlines |
| Must/Should/Could structure | Forces prioritization rather than flat lists |

**Example Flow**: Run `/plan` at 8am. If journaling is enabled, Dex guides you through a quick reflection: energy level, what matters most, what might derail you. Then it checks your calendar, reviews open tasks, and creates a daily note with your top priority highlighted, schedule mapped out, and potential derailers flagged.

---

### Job 3: Track People & Relationships

**The Problem**: Remembering context about dozens of people across hundreds of interactions is impossible. Without system support, you walk into meetings cold or ask questions you've asked before. And when you're dealing with organizations, context is scattered across multiple people.

**How Dex Handles It**:

| Component | What It Does |
|-----------|--------------|
| `People/` folder | One page per person with aggregated context |
| `Companies/` folder | Organization-level aggregation of people, meetings, tasks |
| Person lookup skill | Claude checks People folder first before any search |
| Meeting capture | Identifies people mentioned, updates their pages |
| `/meeting-prep` command | Surfaces context about attendees before calls |
| `refresh_company` tool | Pulls all related context into company page |

**Example Flow**: Before a call with Sarah, Dex looks up `People/External/Sarah_Chen.md`. Shows: last conversation topics, what she cares about, any open action items involving her. After the meeting, her page updates with today's discussion points.

For organization-level context, check `Active/Relationships/Companies/Acme_Corp.md`. Shows: all contacts at Acme, every meeting with anyone there, all tasks related to the account. You never have to remember - the system remembers for you.

---

### Job 4: Manage Tasks Reliably

**The Problem**: Tasks written down aren't tasks managed. They get duplicated across lists, fall through cracks, lose context, and pile up without prioritization. Vague tasks like "follow up" never get done.

**How Dex Handles It**:

| Component | What It Does |
|-----------|--------------|
| Task MCP Server | Deterministic task operations with validation |
| Deduplication | 60% similarity threshold catches duplicates before creation |
| Ambiguity detection | Flags vague tasks, generates clarifying questions |
| Priority limits | P0: max 3, P1: max 5, P2: max 10 - can't overcommit |
| Pillar alignment | Every task connects to strategic priorities |
| `/triage tasks` | Extracts tasks from notes, routes them properly |

**Example Flow**: You try to add "fix the bug" as a task. The MCP server flags it as ambiguous and asks: "Which bug? What system? What's the expected outcome?" You clarify to "Fix login timeout bug in auth module" and it creates cleanly. Later, you try to add a similar task - the server catches it as 78% match to existing, prompts you to review.

---

### Job 5: Reflect & Improve Continuously

**The Problem**: Without structured reflection, you repeat mistakes, miss patterns, and never compound learning. Days blur together. Growth happens by accident rather than design.

**How Dex Handles It**:

| Component | What It Does |
|-----------|--------------|
| `/journal` command | Morning, evening, or weekly reflection prompts |
| `/review` command | End-of-day synthesis of what happened |
| `/week` command | Weekly pattern recognition and planning |
| `Resources/Learnings/` | Compound knowledge that persists across sessions |
| Mistake patterns | Logged mistakes become rules that prevent repetition |
| Working preferences | Collaboration style captured and applied |

**Example Flow**: Friday afternoon, run `/week`. Dex synthesizes the week: themes that emerged, energy patterns (what energized vs drained you), progress by project, questions that came up. You spot a pattern - every meeting with Team X drains energy. That's useful data for next week's planning.

---

### Job 6: Keep Projects On Track

**The Problem**: Projects drift without checkpoints. Status goes stale. Blockers fester. You lose visibility into what's actually moving and what's stuck.

**How Dex Handles It**:

| Component | What It Does |
|-----------|--------------|
| `Active/Projects/` folder | Time-bound initiatives live here |
| `/project-health` command | Reviews all projects for stalls and blockers |
| Project template | Consistent structure: status, stakeholders, timeline, decisions |
| Task linking | Tasks connect to projects for context |

**Example Flow**: Run `/project-health`. Dex scans your projects: "Website Redesign hasn't been updated in 12 days. Q1 Planning has 3 blocked tasks. Product Launch is on track." You know immediately where to focus attention.

---

## System Map

How information flows through Dex:

```mermaid
%%{init: {'theme': 'neutral'}}%%
flowchart TB
    subgraph inputs [Inputs]
        notes[Quick Notes]
        meetings[Meeting Notes]
        ideas[Ideas]
        tasks[Task Capture]
    end
    
    subgraph processing [Processing]
        triage[/triage]
        plan[/plan]
        review[/review]
        mcp[Task MCP]
    end
    
    subgraph storage [Storage]
        inbox[Inbox/]
        active[Active/]
        people[People/]
        resources[Resources/]
    end
    
    subgraph outputs [Outputs]
        dailyplan[Daily Plan]
        dailyreview[Daily Review]
        weeklysynth[Weekly Synthesis]
        focus[Suggested Focus]
    end
    
    notes --> inbox
    meetings --> inbox
    ideas --> inbox
    tasks --> mcp
    
    inbox --> triage
    triage --> active
    triage --> people
    triage --> resources
    
    mcp --> active
    active --> plan
    people --> plan
    
    plan --> dailyplan
    active --> review
    review --> dailyreview
    review --> weeklysynth
    mcp --> focus
```

---

## Component-to-Job Index

Quick reference: which components serve which jobs.

| Component | Jobs Served |
|-----------|-------------|
| **Inbox System** | Capture (#1), Tasks (#4) |
| **Triage Command** | Capture (#1), Tasks (#4) |
| **Templates** | Capture (#1), Projects (#6) |
| **Plan Command** | Focus (#2), Tasks (#4) |
| **Journal Command** | Focus (#2), Reflect (#5) |
| **People System** | Relationships (#3) |
| **Company Pages** | Relationships (#3), Projects (#6) |
| **Meeting Prep** | Relationships (#3), Focus (#2) |
| **Task MCP Server** | Tasks (#4), Focus (#2) |
| **Review Command** | Reflect (#5) |
| **Week Command** | Reflect (#5), Projects (#6) |
| **Project Health** | Projects (#6) |
| **Learnings Library** | Reflect (#5) |

---

## For AI Assistants

When working in this system:

1. **Jobs first**: Before acting, consider which job you're serving. If an action doesn't serve a job, question whether it belongs.

2. **Check existing structures**: The system has patterns. People pages, pillar alignment, priority limits - use them rather than inventing new approaches.

3. **Capture learnings**: When something works well or a mistake happens, update the appropriate Learnings file. Each session should leave the system better.

4. **Respect the user's pillars**: Every task should connect to their strategic priorities. Help them see that connection.

5. **Keep it proportional**: Dex is a starter system. Don't over-engineer solutions. Simple > complex.

---

## Evolution

This document evolves as your Dex grows. When you:
- Add new commands, consider if they create or serve new jobs
- Build automations, document what job they address
- Discover workflow gaps, that might be a job waiting to be served

The Documentation Sync behavior in CLAUDE.md ensures this stays current.

---

## Related Documents

- `CLAUDE.md` - Core system configuration
- `Resources/Dex_System/Dex_System_Guide.md` - How to use every feature
- `System/pillars.yaml` - Your strategic priorities

---

*This document explains why the system exists. For how to use it, see the Dex System Guide.*
