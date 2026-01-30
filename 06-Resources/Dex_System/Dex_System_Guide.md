# Dex System Guide

**Personal Reference** — Full documentation for your Dex knowledge system.

---

## Quick Start (30 Seconds to Value)

```
Morning    → Run /daily-plan for context-aware daily planning
During day → Just tell Claude things - it routes them intelligently
After mtgs → Dex extracts action items and updates person pages
As needed  → /triage finds orphaned files and scattered tasks
End of day → Run /daily-review
End of week → Run /week-review
```

---

## Daily Workflows

### Morning Routine

1. Run `/daily-plan` for your daily plan (integrates calendar, meetings, tasks)
2. Check `00-Inbox/Weekly_Plans.md` for the week's commitments
3. Review any notes captured yesterday

### During the Day

**Conversational Capture:**

Just tell Claude things naturally:

| What You Do | What Happens |
|-------------|--------------|
| "Sarah was worried about timeline but interested in Q2 pilot" | Claude suggests: "Add to Sarah's person page and Q2 Planning project?" |
| "Create a task to finalize mobile app pricing" | Work MCP validates, checks duplicates, writes to Tasks.md |
| "Random idea: could we automate weekly reports?" | Claude suggests where to file it based on your priorities |

The system uses your Week Priorities and Quarterly Goals to route intelligently in real-time.

**Optional: `/triage` for cleanup**
- Finds orphaned files in `00-Inbox/`
- Extracts scattered `- [ ]` tasks from notes
- Routes strategically based on current priorities

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

## Skills Quick Reference

All skills are documented in detail in the **Skills System** section below. Here's a quick overview of common workflows:

### Common Workflows

**Morning:**
1. `/daily-plan` — Get today's focus with calendar, tasks, priorities
2. Optional: `/meeting-prep` — Prepare for first meeting

**During Day:**
- Tell Claude things naturally → it routes intelligently based on your priorities
- "Sarah worried about timeline" → Claude suggests person page + project routing
- "Create task to finalize pricing" → Work MCP validates and adds to Tasks.md

**End of Day:**
1. `/daily-review` — Reflect on what happened, capture learnings
2. Optional: `/journal` — Evening reflection prompts (if enabled)

**Weekly:**
1. `/week-plan` (Monday) — Set Top 3 priorities for the week
2. `/week-review` (Friday) — Synthesize patterns and progress
3. `/triage` (as needed) — Find orphaned files and scattered tasks

**As Needed:**
- `/project-health` — Check project status and blockers
- `/process-meetings` — Process Granola meetings for insights
- `/career-coach` — Career reflections and assessments
- `/dex-level-up` — Discover unused features

See the **Skills System** section below for complete documentation of all 42 core skills + 27 role-specific skills.

---


## Demo Mode

Demo mode lets you explore Dex with pre-populated sample content without affecting your real vault.

### Commands

| Command | Effect |
|---------|--------|
| `/dex-demo on` | Enable demo mode and launch interactive demo selector |
| `/dex-demo off` | Disable demo mode - use real vault |
| `/dex-demo menu` | Show demo scenario menu (when demo mode is on) |
| `/dex-demo status` | Check if demo mode is active |
| `/dex-demo reset` | Restore demo content to original state |

### Interactive Demo Selector

When you run `/dex-demo on`, you'll see a menu of **12 validated demo scenarios** that showcase different aspects of Dex:

**How it works:**
1. Run `/dex-demo on` to see Alex Chen persona intro and scenario menu
2. Enter a number (1-12) to launch that scenario
3. Follow the guided walkthrough
4. Return to menu anytime with `/dex-demo menu`

**Scenario categories:**
- **Daily Workflow (1-4):** Morning journal, daily planning, daily review, inbox triage
- **People & Context (5-6):** Person lookup, company intelligence
- **Planning & Review (7-9):** Weekly planning, weekly review, task management
- **Career Development (10-11):** Career system, career coach
- **System Evolution (12):** Learning & backlog

See `.claude/reference/demo-scenarios.md` for detailed scenario descriptions.

### Demo Content

Located in `System/Demo/`, includes:

**Demo Persona:** Alex Chen, Senior Product Manager (L4) at TechCorp, working toward L5 promotion

**Sample content:**
- 3 active projects in various stages (Mobile App Launch, Customer Portal Redesign, API Partner Program)
- 5 person pages (Jordan Lee, Maya Patel, Sarah Chen, Tom Wilson, Lisa Park)
- Company page for Acme Corp aggregating contacts, meetings, and tasks
- Week of meeting notes (Jan 20-24, 2026) with scattered tasks for `/triage`
- Full week of daily plans, weekly plan, journal entries
- Pre-populated tasks across P0-P3 priorities with pillar tags
- Career development system (role, ladder, reviews, goals, evidence)
- Learning system examples (Working Preferences, Mistake Patterns, Session Learnings)
- Dex Backlog with 10 ranked improvement ideas

### How Demo Mode Works

When `demo_mode: true` in `System/user-profile.yaml`:

1. **Commands read from `System/Demo/`** instead of root folders
2. **Writes are sandboxed** to the demo folder
3. **Work MCP uses demo data** (`System/Demo/03-Tasks/Tasks.md`, `System/Demo/pillars.yaml`)
4. **Your real vault is untouched**

### Use Cases

1. **Onboarding** - Explore commands before adding your own data
2. **Demoing to colleagues** - Show the PKM system with realistic data
3. **Testing** - Try new workflows without risk

---

## Task System

### Work MCP Server

Dex includes a Python MCP server (`core/mcp/work_server.py`) providing deterministic work management operations across the complete planning hierarchy.

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

**Pillars are ongoing focus areas, not time-bound goals.** Think 'Product strategy' (ongoing) vs 'Launch mobile app' (goal).

Configure your pillars during onboarding or edit `System/pillars.yaml`:

```yaml
pillars:
  - id: pillar_1
    name: "Product Strategy"  # Ongoing area, not a goal
    description: "Product vision, roadmap, discovery"
    keywords: [product, roadmap, features, discovery]
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

## Strategically-Aware Triage

Triage is a cleanup tool that finds orphaned files and scattered tasks, then routes them intelligently using your current strategic context.

**When to use it:**
- Standalone files dropped in `00-Inbox/` (screenshots, PDFs, exports)
- Scattered `- [ ]` tasks across multiple notes
- Periodic cleanup and routing

**Note:** For most capture, just tell Claude things conversationally. Triage is for cleanup, not primary workflow.

### How It Works

When you run `/triage`, it follows this sequence:

**Step 1: Load Strategic Context**

| What It Reads | What It Extracts |
|---------------|------------------|
| `00-Inbox/Week_Priorities.md` | This week's Top 3 focus items |
| `03-Tasks/Quarterly_Goals.md` | Current quarter's goals |

**Step 2: Structure Discovery**

| What It Scans | What It Extracts |
|---------------|------------------|
| `04-Projects/` | Project names, descriptions, status |
| `05-Areas/People/External/` + `05-Areas/People/Internal/` | Names, roles, companies |
| `05-Areas/Companies/` | Company names, domains, contacts |
| `System/pillars.yaml` | Pillar names and keywords |

**Step 3: Find Orphaned Items**

- Scans `00-Inbox/` for standalone files
- Searches all notes for unchecked `- [ ]` tasks

### Strategic + Entity-Aware Routing

For each inbox entry, triage checks in priority order:

| Check Priority | Match Criteria | Confidence Boost | Result |
|----------------|----------------|------------------|---------|
| 1. **Week Priority match** | Relates to this week's Top 3 | +30 points | HIGH confidence, surfaced first |
| 2. **Quarterly Goal match** | Connects to Q goal | +20 points | HIGH confidence |
| 3. **Project match** | Mentions existing project | +10 if also matches priority | Base confidence |
| 4. **Person match** | About known person | +10 if person in priorities | Base confidence |
| 5. **Company match** | Mentions known company/domain | — | Base confidence |
| 6. **Pillar match** | Content matches pillar keywords | — | Base confidence |
| 7. **Category fallback** | No specific matches | — | Low confidence |

### Example Routing with Strategic Context

```
File: "Q1_Planning_Notes.md" (in 00-Inbox/)
Strategic Context: ✓ Week Priority "Q2 Planning" (related)
Match: PROJECT → "Q2 Planning"
Confidence: MEDIUM (70/100)
→ Merge into 04-Projects/Q2_Planning.md?

Task: "- [ ] Finalize mobile app pricing" (found in random note)
Strategic Context: ✓ Week Priority "Mobile App Launch" + Q1 Goal
Match: PROJECT → "Mobile App Launch"
Confidence: HIGH (92/100)
→ Extract to Week Priorities for visibility?

Task: "- [ ] Follow up with Sarah about timeline" (scattered)
Strategic Context: ✓ Week Priority "Sarah's team onboarding"
Match: PERSON → "Sarah Chen"
Confidence: HIGH (85/100)
→ Add to Sarah's person page action items?
```

### Misalignment Detection

If multiple entries relate to something **NOT** in your priorities or goals:

```
⚠️ INSIGHTS:
• 5 entries about "CRM evaluation" but not in priorities
• Consider adding "CRM Evaluation" to Week Priorities?
```

### Evolves With Your Work

**Priorities change → routing adapts:**
- Update Week Priorities → triage immediately recognizes new focus areas
- Quarterly goals shift → routing confidence adjusts
- Add projects/people → structure discovery includes them

No configuration needed—triage adapts to both your strategic context and system structure in real-time.

---

## Folder Structure

```
Dex/
├── 04-Projects/                 # Time-bound initiatives
│
├── 05-Areas/                    # Ongoing responsibilities
│   ├── People/               # Person pages
│   │   ├── Internal/         # Colleagues
│   │   └── External/         # Customers, partners, contacts
│   ├── Accounts/             # Key accounts (Sales/CS roles only)
│   ├── Team/                 # Team management (Leadership roles only)
│   ├── Content/              # Content strategy (Marketing roles only)
│   └── Career/               # Career development (optional, via /career-setup)
│
├── 06-Resources/                # Reference material
│   ├── Dex_System/           # This documentation
│   ├── Learnings/            # Compound knowledge
│   └── Quarterly_Reviews/    # Quarterly reflection and strategic reviews
│
├── 07-Archives/                 # Historical records
│   ├── 04-Projects/             # Completed projects
│   ├── Plans/                # Daily and weekly plans
│   └── Reviews/              # Daily, weekly, and quarterly reviews
│
├── 00-Inbox/                    # Capture zone (process regularly)
│   ├── Meetings/             # Meeting notes
│   └── Ideas/                # Quick captures and fleeting thoughts
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

4 templates in `System/Templates/` used by Dex automation:

| Template | Use Case |
|----------|----------|
| `Person_Page.md` | Person page structure |
| `Company.md` | Company page template (used by `/process-meetings`) |
| `Career_Evidence_Achievement.md` | Achievement capture (used by `/week-review`, `/resume-builder`) |
| `Career_Evidence_Feedback.md` | Feedback tracking (career system) |

These templates are automatically applied when Dex creates files through skills. You can modify them to match your preferences.

---

## Career Development System

**The Problem:** When review time comes, you can't remember what you accomplished. Promotion discussions lack evidence. Career growth feels reactive instead of intentional.

**What Dex Does:** Helps you capture evidence of your work throughout the year, so when opportunity knocks, you're ready.

### Getting Started (`/career-setup`)

Run `/career-setup` once to set up your career folder. Dex will ask you to share:
- Your current job description
- Your company's career ladder (the document showing what's expected at each level)
- Your latest performance review
- Your long-term career goals

This creates a `Career/` folder where Dex will track your growth over time.

### Your Career Coach (`/career-coach`)

Think of this as having a career coach on call. Four ways to use it:

**Weekly Check-in** — Every Friday, reflect on the week. What went well? What was hard? What did you learn? Dex helps you spot patterns over time.

**Monthly Deep Dive** — Once a month, step back. Are you developing the skills you need? Making progress toward your goals? Dex compares your recent work against your career ladder to show where you're strong and where you need more evidence.

**Before Your Review** — Run this 1-2 weeks before your performance review. Dex compiles everything you've accomplished and maps it to what your company values. You walk into the review with concrete examples ready.

**Promotion Assessment** — Thinking about the next level? Dex analyzes your evidence and tells you honestly: "You're ready" or "Here's what you need to demonstrate first." It looks at four things:
- Do you have examples for most competencies at the next level?
- Have you consistently delivered on your goals?
- Have you demonstrated breadth across different skills?
- Have you been in role long enough?

### Building Your Resume (`/resume-builder`)

When it's time to update your resume or LinkedIn, run `/resume-builder`. It's like a guided interview:

1. Dex walks through your work history, one role at a time
2. It pulls from your Career Evidence folder to remind you what you've accomplished
3. It checks that every bullet has numbers ("increased by 40%", "shipped to 10,000 users")
4. It scores each bullet to help you keep the strongest ones
5. It makes sure everything fits in 2 pages

You can pause and come back later - Dex remembers where you left off.

**Bonus:** Dex also generates your LinkedIn profile (headline and about section) with proper character limits enforced.

### Connecting Daily Work to Career Growth

The magic happens when you tag work with the skills it demonstrates:

```markdown
- [ ] Ship payments redesign # Career: System Design
```

Later, during `/week-review`, Dex notices: "You completed 'Ship payments redesign' this week. Want to capture this as career evidence?"

If you say yes, it saves the details to your Career folder. Over time, this builds a portfolio of your work.

### Why This Matters

Most people lose track of what they accomplished 3-6 months ago. When review time comes, they scramble to remember. Or they undersell themselves because they forgot the big wins.

With Dex, career development becomes a habit, not a crisis. Every week you capture a little bit. By the time you need it, you have a complete picture of your growth.

---

## Improving Dex Itself

**The Problem:** You discover a better way to do something, but forget to implement it. Good ideas for improvements get lost. The system stops adapting to how you actually work.

**What Dex Does:** Captures your improvement ideas as you think of them, then helps you prioritize which ones matter most.

### Capturing Ideas

Anytime you think "Dex should do X differently," just mention it. Dex will:
- Save the idea to your improvement backlog
- Check if you've suggested something similar before (to avoid duplicates)
- Ask if it's related to existing ideas or something new

Your ideas get stored in `System/Dex_Backlog.md` where they won't get lost.

### Prioritizing What Matters (`/dex-backlog`)

When you're ready to work on improvements, run `/dex-backlog`. Dex analyzes all your ideas and tells you which ones would help you most, based on:

- **How much time it would save you daily** (most important)
- **Whether it fits how you actually use Dex** (no point building features you won't use)
- **Whether it makes the system faster** (nobody wants a slow system)
- **Whether it helps Dex learn and remember better**
- **Whether it makes Dex more proactive**

Ideas get ranked as:
- **High priority** (85+ score): Do this soon, it'll make a real difference
- **Medium priority** (60-84): Nice to have when you have time
- **Low priority** (<60): Not worth the effort right now

### Planning Implementation (`/dex-improve`)

Pick an idea and run `/dex-improve [idea]`. Dex becomes your design partner:
- "Here's what this would change in your system"
- "Here's the best way to build it"
- "While we're at it, have you considered these related improvements?"
- Creates a step-by-step implementation plan

### Why This Matters

Most personal systems become rigid over time. You outgrow them, but don't take the time to evolve them. Eventually, you stop using them.

Dex treats itself as a product you're continuously improving. Ideas compound, the system adapts, and it gets better the longer you use it.

---

## How Dex Learns and Improves Itself

**The Problem:** Software updates constantly. New features get added. But you only find out weeks later when someone mentions it. Meanwhile, you keep using outdated workflows.

**What Dex Does:** Automatically monitors for improvements and reminds you when there's something new worth knowing about.

### Background Monitoring

Behind the scenes, Dex runs two quiet background checks:

**Checking for Claude Updates (every 6 hours)**  
Dex checks if Anthropic has released new Claude Code features. When it finds something new, you'll see a heads-up next time you start working: "🆕 New Claude Code features detected! Run `/dex-whats-new` to review."

**Learning Review Prompts (daily at 5pm)**  
As you work, Dex captures learnings in `System/Session_Learnings/`. When you accumulate 5+ learnings that haven't been reviewed yet, Dex reminds you: "📚 You have 7 pending learnings from this week. Worth reviewing?"

Both happen automatically with no action from you. The system stays current on its own.

### Learning Files

Dex maintains two special files that get smarter over time:

**`06-Resources/Learnings/Mistake_Patterns.md`**  
When you make a mistake and fix it, Dex can save that pattern. Next time you face a similar situation, it reminds you what went wrong before.

**Example:** You accidentally broke something by editing the wrong file. Dex logs: "Before editing system files, always check if there's a template version." Later, when you go to edit a system file, Dex surfaces that reminder.

**`06-Resources/Learnings/Working_Preferences.md`**  
Dex learns how you like to work and applies those preferences consistently.

**Example:** You mention "I prefer bullet points over paragraphs in summaries." Dex saves that preference. From then on, all summaries use bullet points without you having to ask.

### How This Integrates

During your daily and weekly reviews:
- **`/daily-review`** captures what you learned today and asks: "This sounds like a mistake pattern. Save it for next time?"
- **`/week-review`** looks for patterns across the week: "You mentioned preferring X approach 3 times. Add to Working Preferences?"

Every session builds on the last. The system remembers so you don't have to.

### Why Automation Matters

Without automation, learning requires discipline. You have to remember to:
- Check for Claude updates
- Review your learnings
- Update your preferences
- Apply past lessons

Most people don't. The learnings sit unused.

With automation, Dex nudges you at the right time. The system improves itself through quiet background work, and only asks for your input when it matters.

---

## How Dex Remembers Context

**The Problem:** You're reading a meeting note that mentions "Sarah." Who is Sarah? What did you discuss last time? What's she working on?

**What Dex Does:** Automatically loads relevant context in the background so you don't have to go hunting for it.

### Smart Context Loading

When you're reading any file that mentions people or companies, Dex quietly:
- Looks up their person page or company page
- Loads recent meeting history, action items, and relationship notes
- Makes that information available to Claude in the background

You don't see any headers or popups - it just works. When you ask "What did Sarah and I discuss last week?", Claude already knows because it loaded her context automatically.

**Example:** You open a meeting note from a customer call. The note mentions "Acme Corp." Dex automatically loads the Acme Corp company page, sees you've had 5 meetings with them in the past month, notices there are 3 open action items, and uses that context to help you prepare better.

### Discovering Unused Features (`/dex-level-up`)

Dex quietly keeps track of which features you've used:
- Have you run `/career-coach`?
- Are you using the career evidence capture?
- If you're in Sales, have you tried the account management features?
- Have you explored weekly planning?

When you run `/dex-level-up`, Dex shows you relevant features you haven't tried yet. It's personalized based on your role and what you're already using.

**Privacy Note:** All tracking happens locally in your vault. Nothing is sent anywhere or shared with anyone.

---

## Role-Specific Skills

**Specialized workflows designed for your specific discipline.**

During onboarding, Dex sets up the core features everyone needs. But depending on your role, there are additional specialized skills available:

- Product managers get tools for roadmap reviews and customer feedback synthesis
- Sales reps get deal reviews and pipeline health checks
- Marketers get campaign reviews and content planning
- Engineers get architecture decision logs and tech debt reviews
- And so on...

These aren't installed by default because not everyone needs them. When you're ready, run `/dex-level-up` to see what's available for your role and choose which ones to add.

### Available by Role

**Product (3 skills):**
- `/roadmap` — Review roadmap, surface blockers, check alignment
- `/customer-intel` — Synthesize recent customer feedback and pain points
- `/feature-decision` — Framework for feature prioritization decisions

**Sales (4 skills):**
- `/deal-review` — Review active deals and surface risks
- `/pipeline-health` — Analyze pipeline coverage and forecast accuracy
- `/account-plan` — Create or update strategic account plan
- `/call-prep` — Prepare for upcoming call with full context

**Customer Success (3 skills):**
- `/health-score` — Review account health across portfolio
- `/renewal-prep` — Prepare for upcoming renewal
- `/expansion-opportunities` — Identify upsell/cross-sell opportunities

**Marketing (4 skills):**
- `/campaign-review` — Post-mortem on recent campaign
- `/content-calendar` — Review upcoming content and identify gaps
- `/audience-intel` — Synthesize what we're learning about our audience
- `/messaging-audit` — Review positioning and messaging across content

**Engineering (3 skills):**
- `/architecture-decision` — Document architectural choices
- `/tech-debt` — Review and prioritize technical debt
- `/incident-review` — Post-mortem on incidents

**Finance (3 skills):**
- `/variance-analysis` — Compare actuals vs budget with narrative
- `/close-status` — Month-end close checklist and blockers
- `/board-prep` — Compile financial narrative for board meeting

**Leadership (3 skills):**
- `/weekly-reflection` — Weekly synthesis of progress and priorities
- `/delegate-check` — Review what should be delegated
- `/decision-log` — Document major decisions made

**Design (2 skills):**
- `/design-review` — Prepare for or document design review
- `/design-system-audit` — Review design system usage and gaps

**Operations (2 skills):**
- `/metrics-review` — Review key metrics and anomalies
- `/process-audit` — Review process health and bottlenecks

### Installation

Skills in `_available/` are not loaded by default. To install:
1. Run `/dex-level-up` to see available skills for your role
2. Select skills you want
3. Dex moves them from `_available/` to active `.claude/skills/`
4. Skill is immediately available with `/skill-name`

---

## Skills System

Skills are reusable AI workflows invoked with `/skill-name`. All skills follow the [Agent Skills standard](https://agentskills.io) format.

### Core Dex Skills (25)

**Daily Workflow:**
- `/daily-plan` — Context-aware daily planning (integrates calendar, tasks, meetings)
- `/daily-review` — End of day review with learning capture
- `/journal` — Morning, evening, or weekly reflection prompts

**Weekly Workflow:**
- `/week-plan` — Set weekly priorities
- `/week-review` — Weekly synthesis and review

**Quarterly Workflow:**
- `/quarter-plan` — Set 3-5 strategic goals for the quarter
- `/quarter-review` — Review quarter and capture learnings

**Meetings:**
- `/meeting-prep` — Prepare for upcoming meetings with attendee context
- `/process-meetings` — Process Granola meetings to extract insights

**Projects:**
- `/project-health` — Review project status, blockers, and next steps
- `/product-brief` — Extract product ideas through guided questions and generate PRD
- `/triage` — Process inbox intelligently with entity matching

**Career Development:**
- `/career-setup` — Initialize career development system
- `/career-coach` — Career reflections and assessments (4 modes)
- `/resume-builder` — Build resume and LinkedIn through guided interview

**System Management:**
- `/prompt-improver` — Transform vague prompts into expert-level prompts via Anthropic Messages API
- `/dex-level-up` — Discover unused features based on usage patterns
- `/dex-backlog` — AI-powered ranking of improvement ideas
- `/dex-improve` — Workshop an idea into implementation plan
- `/dex-whats-new` — Check for system improvements (learnings + Claude updates)
- `/create-mcp` — Create new MCP integration with guided wizard
- `/dex-demo` — Toggle demo mode on/off/reset
- `/setup` — Initial onboarding (one-time)
- `/reset` — Restructure Dex based on role change
- `/save-insight` — Capture learnings from completed work

### Anthropic Skills (17)

**Document Creation & Editing:**
- `/anthropic-docx` — Word documents with tracked changes and comments
- `/anthropic-pptx` — Presentations with layouts and speaker notes
- `/anthropic-xlsx` — Spreadsheets with formulas and data analysis
- `/anthropic-pdf` — PDF manipulation, text extraction, form filling

**Writing & Communication:**
- `/anthropic-doc-coauthoring` — Structured workflow for co-authoring docs
- `/anthropic-internal-comms` — Internal communications (status reports, updates)

**Design & Visual:**
- `/anthropic-algorithmic-art` — Create algorithmic art using p5.js
- `/anthropic-canvas-design` — Visual design and posters
- `/anthropic-frontend-design` — Production-grade frontend interfaces
- `/anthropic-theme-factory` — Style artifacts with pre-set themes
- `/anthropic-slack-gif-creator` — Animated GIFs optimized for Slack
- `/anthropic-brand-guidelines` — Apply Anthropic brand colors/typography

**Development:**
- `/anthropic-mcp-builder` — Create MCP servers for external service integration
- `/anthropic-web-artifacts-builder` — Multi-component HTML artifacts with React
- `/anthropic-webapp-testing` — Test local web applications with Playwright

**Meta:**
- `/anthropic-skill-creator` — Guide for creating new skills

### How Skills Work

Skills define consistent behaviors Claude follows. When you type `/skill-name`, Claude reads the skill file at `.claude/skills/[skill-name]/SKILL.md` and follows its instructions.

---

## Company Pages

Company pages aggregate context about organizations you interact with.

### Location

```
05-Areas/Companies/
├── Acme_Corp.md
├── BigTech_Inc.md
└── ...
```

### What Gets Aggregated

| Section | Source | How It Works |
|---------|--------|--------------|
| **Key Contacts** | Person pages | People with matching `Company Page` field |
| **Meeting History** | `00-Inbox/Meetings/` | Meetings where attendee emails match company domains |
| **Related Tasks** | `03-Tasks/Tasks.md` | Tasks that reference the company page |

### MCP Tools for Companies

| Tool | Purpose |
|------|---------|
| `create_company` | Create a new company page with basic info |
| `refresh_company` | Update all aggregated sections (contacts, meetings, tasks) |
| `list_companies` | List all company pages with contact counts |

### Linking People to Companies

Add the `Company Page` field to person pages:

```markdown
| **Company Page** | 05-Areas/Companies/Acme_Corp.md |
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

**Where Dex stores what it learns about how you work.**

Located in `06-Resources/Learnings/` and `System/Session_Learnings/`:

| File/Folder | Contents | When It Updates |
|-------------|----------|-----------------|
| `Mistake_Patterns.md` | Logged mistakes that become rules | During `/daily-review` or `/week-review` |
| `Working_Preferences.md` | How you like to work (formatting, communication style) | When patterns emerge across multiple sessions |
| `Session_Learnings/` | Daily captured improvements and discoveries | Every `/daily-review` |

### How Learning Happens

**During Your Day:**
- Dex captures learnings in `System/Session_Learnings/` as you work
- Each entry notes what happened, why it matters, and what to fix

**During `/daily-review`:**
- Dex asks: "This sounds like a mistake pattern. Save it for next time?"
- Or: "This seems like a workflow preference. Add to Working_Preferences.md?"

**During `/week-review`:**
- Dex scans the week's session learnings for patterns
- Suggests consolidating repeated lessons into Mistake_Patterns or Working_Preferences

**Automatic Prompts:**
- Daily at 5pm, Dex checks if you have 5+ pending learnings
- Next session start: "📚 You have 7 pending learnings from this week. Worth reviewing?"

### Why This Matters

Most people learn the same lesson multiple times. They fix a mistake, then repeat it three months later because they forgot.

Dex remembers for you. Every session builds on past lessons, and the system gets smarter the longer you use it.

For more on how Dex learns and improves itself, see the **"How Dex Learns and Improves Itself"** section above.

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

### Built-in MCP Servers

Dex includes six custom MCP servers in `core/mcp/`:

| MCP Server | File | What It Does |
|------------|------|--------------|
| **Work** | `work_server.py` | Task/priority management with deduplication, priority limits, pillar alignment |
| **Calendar** | `calendar_server.py` | Apple Calendar integration via AppleScript (Google, Exchange, iCloud) |
| **Granola** | `granola_server.py` | Meeting transcripts from Granola's local cache |
| **Career** | `career_server.py` | Career development tracking, evidence aggregation, competency analysis |
| **Resume** | `resume_server.py` | Resume building with sessions, metric validation, LinkedIn generation |
| **Dex Improvements** | `dex_improvements_server.py` | Improvement idea capture, duplicate detection, backlog management |

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

**Basic commands:**

| Command | What It Does |
|---------|--------------|
| `/process-meetings` | Process all unprocessed meetings (last 7 days) |
| `/process-meetings today` | Just today's meetings |
| `/process-meetings "Acme"` | Find and process specific meeting |

**Granular control flags:**

| Flag | Purpose | Example |
|------|---------|---------|
| `--days-back=N` | Override default 7-day lookback | `--days-back=30` or `--days-back=365` |
| `--people-only` | Create/update person and company pages only | `--people-only --days-back=365` |
| `--no-todos` | Create notes and update people, skip todos | `--no-todos --days-back=30` |

**Common workflows:**

```bash
# Backfill people and companies from all history
/process-meetings --people-only --days-back=365

# Backfill meeting notes from last month without overwhelming todos
/process-meetings --no-todos --days-back=30

# Process last 90 days with full tracking
/process-meetings --days-back=90

# Today's meetings, notes only
/process-meetings today --no-todos
```

**What gets extracted:**
- Summary (2-3 sentences)
- Key discussion points
- Decisions made
- Action items (for you and others, conditionally based on flags)
- Customer intelligence (pain points, feature requests, competitive mentions)
- Pillar classification

**Output:**
- Meeting notes: `00-Inbox/Meetings/YYYY-MM-DD/meeting-slug.md`
- Person pages updated with meeting references (Internal/ or External/ based on email domain)
- Company pages created for external organizations
- Action items added to `03-Tasks/Tasks.md` (unless `--no-todos` flag used)

#### Historical Data Processing

When you first connect Granola (via `/getting-started` or during onboarding), the system analyzes your meeting history:

**Discovery phase (fast):**
- Fetches last 6 months by default for quick initial analysis
- Shows meeting count, date range, people, and companies
- If more data exists beyond 6 months, offers to check full extent
- Optional: Extend to up to 2 years if you have extensive history

Then you get independent control over:

**1. People & Company Pages** (Recommended: All history)
- Builds context for relationships
- Low overhead - just reference pages
- Routes people to Internal/ or External/ based on email domain

**2. Meeting Notes** (Recommended: Last 30 days)
- Searchable record of discussions
- Medium overhead - lots of reading material
- Good for finding past decisions

**3. Action Items / Todos** (Recommended: Last 7 days)
- Actionable recent tasks
- Can be overwhelming if too many
- Old todos often outdated or already done

**Processing strategies:**

| Strategy | People/Companies | Meeting Notes | Todos |
|----------|-----------------|---------------|-------|
| Smart default | All history | Last 30 days | Last 7 days |
| Recent only | 7 days | 7 days | 7 days |
| Full history | All | All | All |
| Custom | You choose | You choose | You choose |
| Forward only | None | None | None |

**Why different time ranges?**

People and company pages are lightweight context that's always useful. Meeting notes help you recall past discussions. But todos from old meetings are often already done or outdated — keeping just the recent ones prevents overwhelm while giving you actionable work.

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
- `06-Resources/Dex_System/Dex_Jobs_to_Be_Done.md` — Why the system exists (conceptual)
- `System/pillars.yaml` — Your strategic pillars configuration
- `.claude/skills/` — Skill definitions following [Agent Skills standard](https://agentskills.io)

---

*This guide covers how to use Dex. For why it exists, see the Jobs to Be Done document.*
