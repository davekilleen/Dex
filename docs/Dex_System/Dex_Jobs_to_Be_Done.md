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

Everything in this system aligns to your strategic priorities. Pillars are **ongoing focus areas**, not time-bound goals. Think 'Pipeline generation' (ongoing) vs 'Close Q1 deals' (goal). These are configured during onboarding and stored in `System/pillars.yaml`. Tasks without pillar connection prompt you to think about strategic alignment.

---

## The Six Jobs

Each job represents something that needs to happen reliably. The system exists to make these jobs easier or automatic.

---

### Job 1: Capture Without Friction

**The Problem**: Ideas die between having them and recording them. Meeting notes get lost. Quick thoughts evaporate. Deciding where things belong kills momentum. The best capture system is the one you actually use, and complex workflows get abandoned.

**How Dex Handles It**:

| Component | What It Does |
|-----------|--------------|
| Conversational capture | Just tell Claude things naturally - "Sarah worried about timeline but interested in Q2 pilot" |
| Strategic routing | Uses your Week Priorities and Quarterly Goals to suggest routing in real-time |
| Immediate suggestions | Claude: "Should I add this to Sarah's person page and Q2 Planning project?" |
| Work MCP for tasks | "Create task to finalize pricing" → validates, checks duplicates, writes to Tasks.md |
| `/triage` for cleanup | Finds orphaned files and scattered tasks, routes strategically |

**Example Flow**: You mention "Sarah seemed worried about timeline but interested in Q2 pilot". Claude immediately suggests: "I see you have 'Sarah's team onboarding' and 'Q2 Planning' in your Week Priorities. Should I add this to Sarah's person page and the Q2 Planning project?" You approve, it's filed. One decision, instant routing.

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

**v1.11.0**: Agent-powered with memory. Morning briefings surface trends across days instead of repeating yesterday's flags. Daily plan includes a quickref summary for glanceable priorities. Context isolation keeps sessions clean all day.

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

**v1.11.0**: Person pages auto-update when meetings are processed. No manual step to link meetings to people — it happens as part of the capture flow.

**Example Flow**: Before a call with Sarah, Dex looks up `People/External/Sarah_Chen.md`. Shows: last conversation topics, what she cares about, any open action items involving her. After the meeting, her page updates with today's discussion points.

For organization-level context, check company pages in `05-Areas/Companies/`. Shows: all contacts at the company, every meeting with anyone there, all tasks related to the account. You never have to remember - the system remembers for you.

---

### Job 4: Manage Tasks Reliably

**The Problem**: Tasks written down aren't tasks managed. They get duplicated across lists, fall through cracks, lose context, and pile up without prioritization. Vague tasks like "follow up" never get done.

**How Dex Handles It**:

| Component | What It Does |
|-----------|--------------|
| Work MCP Server | Deterministic task operations with validation |
| Deduplication | 60% similarity threshold catches duplicates before creation |
| Ambiguity detection | Flags vague tasks, generates clarifying questions |
| Priority limits | P0: max 3, P1: max 5, P2: max 10 - can't overcommit |
| Pillar alignment | Every task connects to strategic priorities |
| `/triage tasks` | Extracts tasks from notes, routes them properly |

**v1.11.0**: Triage and inbox processing tuned for speed. Quick routing decisions feel instant — less friction between capture and action.

**Example Flow**: You try to add "fix the bug" as a task. The MCP server flags it as ambiguous and asks: "Which bug? What system? What's the expected outcome?" You clarify to "Fix login timeout bug in auth module" and it creates cleanly. Later, you try to add a similar task - the server catches it as 78% match to existing, prompts you to review.

---

### Job 5: Reflect & Improve Continuously

**The Problem**: Without structured reflection, you repeat mistakes, miss patterns, and never compound learning. Days blur together. Growth happens by accident rather than design. Software updates constantly, but you only discover new features weeks later.

**How Dex Handles It**:

| Component | What It Does |
|-----------|--------------|
| `/journal` command | Morning, evening, or weekly reflection prompts |
| `/review` command | End-of-day synthesis of what happened, captures learnings |
| `/week` command | Weekly pattern recognition and planning |
| Background changelog monitor | Checks every 6 hours for Claude updates, alerts you automatically |
| Learning review prompts | Daily check: when 5+ learnings pending, reminds you to review |
| `Mistake_Patterns.md` | Logged mistakes become rules that prevent repetition |
| `Working_Preferences.md` | Collaboration style captured and applied consistently |
| Session learnings capture | Automatic logging in `System/Session_Learnings/` |

**v1.11.0**: Learning heartbeat now focused on operational knowledge only. Preferences are handled by Claude's built-in memory, so session learnings are cleaner and less noisy.

**Example Flow**: Friday afternoon, run `/week`. Dex synthesizes the week: themes that emerged, energy patterns (what energized vs drained you), progress by project, questions that came up. You spot a pattern - every meeting with Team X drains energy. That's useful data for next week's planning.

During the week, you mentioned "I prefer summaries in bullet points." Dex captured this in Session_Learnings and now asks: "You've mentioned this preference 3 times. Add to Working_Preferences.md so all future summaries use bullets?"

**Why automation matters**: Next week, when you start a session at 5pm, Dex notices: "📚 You have 7 pending learnings from this week" and prompts a review. You also see: "🆕 New Claude Code features detected!" because background monitoring found updates. The system improves itself quietly.

---

### Job 6: Keep Projects On Track

**The Problem**: Projects drift without checkpoints. Status goes stale. Blockers fester. You lose visibility into what's actually moving and what's stuck.

**How Dex Handles It**:

| Component | What It Does |
|-----------|--------------|
| `04-Projects/` folder | Time-bound initiatives live here |
| `/project-health` command | Reviews all projects for stalls and blockers |
| Project template | Consistent structure: status, stakeholders, timeline, decisions |
| Task linking | Tasks connect to projects for context |

**v1.11.0**: Project-health agent remembers previous health status. Only surfaces projects that changed status, not the full list every time — less noise, faster signal.

**Example Flow**: Run `/project-health`. Dex scans your projects: "Website Redesign hasn't been updated in 12 days. Q1 Planning has 3 blocked tasks. Product Launch is on track." You know immediately where to focus attention.

---

### Job 7: Track Career Growth

**The Problem**: Career progress is invisible without documentation. When review time comes, you can't remember what you shipped 6 months ago. Promotion discussions lack evidence. Growth feels reactive instead of intentional.

**How Dex Handles It**:

| Component | What It Does |
|-----------|--------------|
| `/career-setup` command | One-time setup: capture your role, career ladder, and goals |
| `/career-coach` command | Your on-call career coach: weekly check-ins, monthly reviews, promotion assessments |
| `/resume-builder` command | Guided interview to build your resume and LinkedIn profile |
| Career evidence capture | During reviews, Dex asks "Worth capturing for your career folder?" |
| Skill tracking tags | Tag work with skills (`# Career: System Design`) to connect daily work to growth |
| Evidence folders | Organized storage: Achievements/, Feedback/, Skills/ |

**v1.11.0**: Career coaching auto-captures evidence when achievements with metrics are discussed. Your evidence log builds automatically over time without manual prompts.

**Example Flow**: During `/daily-review`, Dex notices you completed "Ship payments redesign." It asks: "This looks like career evidence. What competencies did this demonstrate?" You say: "System design and cross-functional leadership." Dex saves it to your Career folder with full context.

Three months later, you run `/career-coach` → Promotion Assessment. Dex analyzes all your evidence against your career ladder and reports: "67/100 promotion readiness. Strong evidence for Product Strategy (8 examples), weak for Technical Depth (2 examples). Let's capture 2-3 examples from your recent system design work."

**Why it matters**: Career development requires compound evidence collection. One-off performance reviews don't capture the full story. Dex makes evidence capture a daily habit, so when opportunity comes, you're ready.

---

### Job 8: Evolve the System Itself

**The Problem**: Personal knowledge systems ossify. You discover inefficiencies but forget to fix them. Good ideas for improvements get lost. The system stops adapting to how you actually work.

**How Dex Handles It**:

| Component | What It Does |
|-----------|--------------|
| Idea capture | Mention an improvement idea → Dex saves it to your backlog |
| `/dex-backlog` command | Shows all ideas ranked by impact (which ones would help you most) |
| `/dex-improve` command | Takes an idea and creates an implementation plan |
| Duplicate detection | Checks if you've suggested something similar before |
| Usage tracking | Quietly tracks which features you use (all local, nothing shared) |
| `/dex-level-up` command | Discovers unused features based on what you actually use |
| Learning capture | During `/review`, captures what you learned for future improvements |

**v1.11.0**: Vault maintenance tool for system hygiene. Memory ownership is documented (what Dex stores vs what Claude remembers). Named sessions guide for project continuity across conversations.

**Example Flow**: During `/review`, you realize: "I keep forgetting to check task dependencies. We should auto-suggest blocked-by relationships."

You mention this → Dex:
1. Saves it to your improvement backlog
2. Checks for similar ideas (finds "Link related tasks together" which is similar)
3. Asks: "Similar to another idea. Is this different or an extension?"
4. You confirm it's different
5. Saves it properly categorized

Next week, you run `/dex-backlog`. Dex analyzes all ideas based on how much time they'd save you, how well they fit your workflow, and other factors. Your idea ranks High (87/100). When you have time, `/dex-improve` walks you through building it.

**Why it matters**: Static systems decay. Dex treats itself as a product you're continuously improving. Ideas compound, usage patterns inform feature discovery, and the system gets better over time.

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
        mcp[Work MCP]
    end
    
    subgraph storage [Storage]
        inbox[00-Inbox/]
        projects[04-Projects/]
        areas[05-Areas/]
        resources[06-Resources/]
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
    triage --> projects
    triage --> areas
    triage --> resources
    
    mcp --> projects
    projects --> plan
    areas --> plan
    
    plan --> dailyplan
    projects --> review
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
| **Templates** | Capture (#1), Projects (#6), Career (#7) |
| **Plan Command** | Focus (#2), Tasks (#4) |
| **Journal Command** | Focus (#2), Reflect (#5) |
| **People System** | Relationships (#3) |
| **Company Pages** | Relationships (#3), Projects (#6) |
| **Meeting Prep** | Relationships (#3), Focus (#2) |
| **Work MCP Server** | Tasks (#4), Focus (#2) |
| **Career MCP Server** | Career (#7), Reflect (#5) |
| **Resume MCP Server** | Career (#7) |
| **Dex Improvements MCP** | Evolution (#8) |
| **Review Command** | Reflect (#5), Career (#7), Evolution (#8) |
| **Week Command** | Reflect (#5), Projects (#6) |
| **Project Health** | Projects (#6) |
| **Career Commands** | Career (#7) |
| **Dex Backlog** | Evolution (#8) |
| **Usage Tracking** | Evolution (#8) |
| **Learnings Library** | Reflect (#5), Evolution (#8) |
| **Background Changelog Monitor** | Reflect (#5) |
| **Learning Review Prompts** | Reflect (#5) |
| **Session Learnings Capture** | Reflect (#5), Evolution (#8) |

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
- `06-Resources/Dex_System/Dex_System_Guide.md` - How to use every feature
- `System/pillars.yaml` - Your strategic priorities

---

*This document explains why the system exists. For how to use it, see the Dex System Guide.*
