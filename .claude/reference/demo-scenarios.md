# Demo Scenarios Reference

12 validated scenarios demonstrating Dex capabilities using Alex Chen's demo content.

---

## Daily Workflow (Scenarios 1-4)

### 1. Morning Journal - Start Day with Intention

**What it demonstrates:**
- Morning reflection prompts (gratitude, intention, energy)
- Connection between journaling and daily planning
- How writing surfaces clarity before the workday starts

**Commands to run:**
```
/journal morning
```

**Expected outcome:**
- Guided prompts for gratitude, intention, and energy check
- Entry saved to `07-Archives/Journals/Daily/Morning/YYYY-MM-DD.md`
- Natural lead-in to daily planning

**Talking points:**
- "Journaling is optional but integrated - notice how it connects to planning"
- "Alex's existing morning journals show the reflection pattern over time"
- "The system asks what matters today before showing you the task list"

**Demo files to reference:**
- Existing journals in `07-Archives/Journals/Daily/Morning/2026-01-*.md`

---

### 2. Daily Planning - Context-Aware Daily Plan

**What it demonstrates:**
- Calendar integration (shows meetings)
- Task surfacing (from `Tasks.md` based on priorities and pillars)
- Week priorities context (Top 3 this week)
- Morning journal integration (if enabled)
- Automatic archiving to dated files

**Commands to run:**
```
/daily-plan
```

**Expected outcome:**
- Plan generated with calendar, tasks, and focus areas
- Saved to `07-Archives/Plans/Daily/YYYY-MM-DD.md`
- Clear connection between quarterly goals → weekly priorities → today's work

**Talking points:**
- "Notice how tasks are prioritized by pillar and linked to weekly goals"
- "Calendar context prevents overcommitting"
- "Alex has 5 days of plans showing the rhythm - scroll through them"

**Demo files to reference:**
- Week priorities: `02-Week_Priorities/Week_Priorities.md`
- Existing plans: `07-Archives/Plans/Daily/2026-01-*.md`
- Tasks: `Tasks.md`

---

### 3. Daily Review - Capture Learnings and Reflect

**What it demonstrates:**
- End-of-day reflection (what got done, what's learned)
- Learning capture workflow (scans session for mistakes, preferences, documentation gaps)
- Evening journal integration (if enabled)
- Automatic archiving

**Commands to run:**
```
/review
```

**Expected outcome:**
- Reflection prompts for the day
- Learning capture to `System/Session_Learnings/YYYY-MM-DD.md`
- Evening journal prompts if enabled
- Saved to `07-Archives/Reviews/Daily/YYYY-MM-DD.md`

**Talking points:**
- "The review actively looks for learnings - system improvements, preferences, mistakes"
- "These learnings feed into weekly reviews for pattern recognition"
- "Alex's existing review shows the reflection structure"

**Demo files to reference:**
- Existing review: `07-Archives/Reviews/Daily/Daily_Review_2026-01-24.md`
- Session learnings: `System/Session_Learnings/2026-01-20.md`

---

### 4. Inbox Triage - Process Scattered Notes

**What it demonstrates:**
- Task extraction from meeting notes and ideas
- Strategic routing (meetings to People pages, ideas to Resources or Projects)
- Orphan file detection (files that should be moved/linked)
- Bulk processing workflow

**Commands to run:**
```
/triage
```

**Expected outcome:**
- Scans `00-Inbox/` for meetings, ideas, unrouted files
- Extracts tasks and shows routing suggestions
- Offers bulk processing with confirmation

**Talking points:**
- "Inbox is a capture zone - triage routes content to the right place"
- "Tasks scattered in meeting notes get surfaced and moved to central backlog"
- "Alex has meeting notes and ideas in the inbox ready to triage"

**Demo files to reference:**
- Meetings: `00-Inbox/Meetings/2026-01-*/`
- Ideas: `00-Inbox/Ideas/*.md`
- Tasks after triage: `03-Tasks/Tasks.md`

---

## People & Context (Scenarios 5-6)

### 5. Person Lookup - Relationship Tracking

**What it demonstrates:**
- Person page structure (role, context, meeting history)
- Internal vs External routing
- Meeting history aggregation
- Action items involving people
- Company page linking

**Commands to show:**
```
Read: 05-Areas/People/Internal/Jordan_Lee.md
Read: 05-Areas/People/External/Sarah_Chen.md
```

**Expected outcome:**
- Rich person pages with relationship context, working style, meeting history
- Clear distinction between internal (colleagues) and external (customers/partners)
- Links to related meetings and companies

**Talking points:**
- "Person pages aggregate everything about a relationship in one place"
- "Jordan Lee is Alex's engineering partner - see meeting history and working style notes"
- "Sarah Chen is at Acme Corp - see how person page links to company page"
- "These pages become your institutional memory"

**Demo files to reference:**
- Internal: `05-Areas/People/Internal/Jordan_Lee.md`, `Maya_Patel.md`, `Mike_Rodriguez.md`
- External: `05-Areas/People/External/Sarah_Chen.md`, `Tom_Wilson.md`, `Lisa_Park.md`
- Company: `05-Areas/Companies/Acme_Corp.md`

---

### 6. Company Intelligence - Organization-Level Rollup

**What it demonstrates:**
- Company page structure (all contacts, meetings, tasks for an organization)
- Account-level context aggregation
- Strategic relationship tracking
- Revenue/expansion tracking (for customer-facing roles)

**Commands to show:**
```
Read: 05-Areas/Companies/Acme_Corp.md
```

**Expected outcome:**
- Company page showing all contacts at Acme (Sarah, Tom, Lisa)
- Meeting history across all contacts
- Tasks and opportunities related to the account
- Relationship health tracking

**Talking points:**
- "Company pages roll up all activity with an organization"
- "See all your contacts at Acme, every meeting, all related tasks"
- "Perfect for account planning or customer success work"
- "External people automatically link to their company page"

**Demo files to reference:**
- Company page: `05-Areas/Companies/Acme_Corp.md`
- Related people: Sarah, Tom, Lisa in External/
- Related meetings: Several meetings with Acme contacts

---

## Planning & Review (Scenarios 7-9)

### 7. Weekly Planning - Set Top 3 Priorities

**What it demonstrates:**
- Weekly priority setting (Top 3 for the week)
- Connection to quarterly goals
- Pillar balance checking
- Task promotion workflow
- Automatic archiving

**Commands to run:**
```
/week-plan
```

**Expected outcome:**
- Guided workflow to set Top 3 priorities for the week
- Pillar balance check (ensure all pillars are represented)
- Task promotion from backlog to week priorities
- Saved to `02-Week_Priorities/Week_Priorities.md` and archived

**Talking points:**
- "Weekly planning forces prioritization - only 3 things matter most this week"
- "Notice how priorities ladder up to quarterly goals"
- "Alex's current week priorities show product focus (mobile launch) with career development"
- "Pillar balance check ensures you're not neglecting key areas"

**Demo files to reference:**
- Current priorities: `02-Week_Priorities/Week_Priorities.md`
- Pillars: `System/pillars.yaml`
- Tasks: `03-Tasks/Tasks.md`

---

### 8. Weekly Review - Synthesize the Week

**What it demonstrates:**
- Week synthesis (meetings, progress, learnings)
- Pattern recognition from session learnings
- Working preferences and mistake pattern documentation
- Weekly journal integration (if enabled)
- Automatic archiving

**Commands to run:**
```
/week-review
```

**Expected outcome:**
- Review of the week's meetings, tasks completed, and learnings
- Pattern detection (recurring mistakes or preferences)
- Prompt to update `Working_Preferences.md` or `Mistake_Patterns.md`
- Weekly journal prompts if enabled
- Saved to `07-Archives/Reviews/Weekly/Week_NN_YYYY.md`

**Talking points:**
- "Weekly review looks across all session learnings from the week"
- "System detects patterns - 2+ similar learnings trigger documentation prompts"
- "Alex's W03 review shows comprehensive synthesis"
- "This is where tactical learnings become strategic knowledge"

**Demo files to reference:**
- Existing review: `07-Archives/Reviews/Weekly/Week_03_2026.md`
- Working Preferences: `06-Resources/Learnings/Working_Preferences.md`
- Mistake Patterns: `06-Resources/Learnings/Mistake_Patterns.md`
- Session learnings: `System/Session_Learnings/*.md`

---

### 9. Task Management - Strategic Task Organization

**What it demonstrates:**
- Task structure with pillar tags, goal links, and priority levels
- Career skill tagging (linking tasks to skill development)
- Task completion workflow (natural language → MCP tool)
- Task surfacing in daily plans
- Week/Quarter promotion system

**Commands to show:**
```
Read: 03-Tasks/Tasks.md
```

**Commands to run (optional):**
```
"I finished reviewing portal wireframes"
(System will find task, extract ID, mark complete via MCP)
```

**Expected outcome:**
- Rich task backlog with metadata (pillars, goals, skills)
- Task completion via natural language
- Tasks organized by priority (P0-P3)
- Clear connection between tasks and quarterly goals

**Talking points:**
- "Tasks aren't just to-dos - they're tagged with strategic context"
- "Notice career skill tags - 'Ship mobile app # Career: System Design'"
- "Task completion is natural language - just say what you finished"
- "The Work MCP automatically syncs completions across all related pages"

**Demo files to reference:**
- Tasks: `03-Tasks/Tasks.md`
- Quarterly goals: `01-Quarter_Goals/Quarter_Goals.md`
- Pillars: `System/pillars.yaml`

---

## Career Development (Scenarios 10-11)

### 10. Career System - Role, Ladder, Goals, Evidence

**What it demonstrates:**
- Career folder structure (Current_Role, Career_Ladder, Growth_Goals, Review_History)
- Evidence capture system (Achievements, Feedback, Skills)
- Career skill tagging workflow
- Connection between daily work and growth goals

**Commands to show:**
```
Read: 05-Areas/Career/Current_Role.md
Read: 05-Areas/Career/Career_Ladder.md
Read: 05-Areas/Career/Growth_Goals.md
Read: 05-Areas/Career/Evidence/Achievements/2026_Mobile_App_Launch.md
```

**Expected outcome:**
- Complete career development infrastructure
- Alex's L4→L5 promotion path clearly documented
- Evidence accumulating in structured folders
- Career skill tags on tasks demonstrating skill development

**Talking points:**
- "Career development is integrated, not bolted on"
- "Alex is an L4 PM working toward L5 - ladder shows the gap"
- "Evidence folder accumulates over time - achievements, feedback, skills"
- "Career skill tags on tasks link daily work to promotion readiness"
- "Set up via `/career-setup` - fully guided"

**Demo files to reference:**
- Career folder: `05-Areas/Career/`
- All subfolders: Current_Role, Ladder, Goals, Review_History, Evidence/
- Tasks with career tags: `03-Tasks/Tasks.md`

---

### 11. Career Coach - Weekly Reports and Reflections

**What it demonstrates:**
- Career coaching modes (weekly, monthly, self-review, promotion prep)
- Personalized coaching based on career ladder and goals
- Evidence-driven guidance
- Manager communication support

**Commands to run:**
```
/career-coach
```

**Expected outcome:**
- Menu of 4 coaching modes
- User selects mode (try "weekly" or "monthly")
- Personalized guidance based on Alex's L4→L5 path
- Actionable recommendations with evidence capture prompts

**Talking points:**
- "Career coach adapts to your specific ladder and goals"
- "Weekly mode gives targeted advice for the week ahead"
- "Monthly mode helps with bigger reflections and manager conversations"
- "Self-review and promotion modes help with performance cycles"
- "All advice is evidence-based, tied to Alex's actual career trajectory"

**Demo files to reference:**
- Career ladder: `05-Areas/Career/Career_Ladder.md`
- Growth goals: `05-Areas/Career/Growth_Goals.md`
- Evidence folder: `05-Areas/Career/Evidence/`

---

## System Evolution (Scenario 12)

### 12. Learning & Backlog - Continuous Improvement

**What it demonstrates:**
- System learning capture (session learnings)
- AI-powered backlog ranking (5 dimensions: impact, alignment, token efficiency, memory/learning, proactivity)
- Idea capture via MCP tool
- Learning review prompts
- Changelog monitoring (Claude updates)

**Commands to run:**
```
/dex-backlog
/dex-whats-new
```

**Commands to show:**
```
Read: System/Dex_Backlog.md
Read: System/Session_Learnings/2026-01-20.md
Read: 06-Resources/Learnings/Mistake_Patterns.md
```

**Expected outcome:**
- AI-ranked backlog showing High/Medium/Low priority ideas
- Session learnings capturing system improvements
- Mistake patterns and working preferences documented
- Changelog updates from Anthropic

**Talking points:**
- "The system learns from your usage patterns"
- "Session learnings capture mistakes, preferences, documentation gaps"
- "Backlog AI ranks ideas on 5 dimensions - effort intentionally excluded"
- "Pattern recognition turns session learnings into mistake patterns"
- "`/dex-whats-new` checks for Claude updates and pending learnings"
- "Capture improvement ideas anytime via Work MCP `capture_idea` tool"

**Demo files to reference:**
- Backlog: `System/Dex_Backlog.md` (10 ranked ideas)
- Session learnings: `System/Session_Learnings/2026-01-20.md`
- Mistake patterns: `06-Resources/Learnings/Mistake_Patterns.md`
- Working preferences: `06-Resources/Learnings/Working_Preferences.md`

---

## Demo Flow Recommendations

### For Self-Exploration
Start with scenarios 2, 5, 7 (daily plan, person lookup, weekly planning) to see core workflow.

### For Demoing to Colleagues (15-20 minutes)
**Recommended order:**
1. Scenario 2 (Daily Planning) - Show context-aware planning
2. Scenario 5 (Person Lookup) - Show relationship tracking
3. Scenario 9 (Task Management) - Show strategic task organization
4. Scenario 10 (Career System) - Show career development integration
5. Scenario 12 (Learning & Backlog) - Show system evolution

### For Demoing to Colleagues (30-45 minutes)
Run through all 12 scenarios in order, spending 3-4 minutes per scenario.

---

## Interactive Menu Workflow

When user runs `/dex-demo on`, the system:
1. Enables demo mode flag in `System/user-profile.yaml`
2. Displays Alex Chen persona introduction
3. Presents numbered list of 12 scenarios
4. Waits for user to select a number (1-12)
5. Executes that scenario with guided walkthrough
6. Offers to return to menu or try another scenario

User can return to menu anytime with `/dex-demo menu`.
