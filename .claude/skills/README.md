# Skills

**Purpose:** User-facing commands following the [Agent Skills](https://agentskills.io) standard for invoking workflows, tools, and features.

---

## What Are Skills?

**Skills** are commands that extend what Claude can do - like giving Claude new capabilities. Each skill is a set of instructions for a specific workflow.

Think of skills as **expert modes** for Claude. Just like you'd switch to a specialized tool for a specific job, skills equip Claude with domain expertise, workflows, and tooling for particular tasks.

### The Power of Skills

Skills transform Claude from general-purpose assistant into specialized agent:

**Without skills:**
- "Can you help me plan my day?"
- Claude makes educated guesses about what you want
- Results vary, require back-and-forth clarification

**With skills:**
- `/daily-plan`
- Claude knows exactly what to do: check calendar, review tasks, analyze priorities, generate structured plan
- Consistent, reliable, no explanation needed

**Real examples:**
- `/career-coach` - Personal career coaching with 4 specialized modes (weekly reports, monthly reflections, self-reviews, promotion assessments)
- `/anthropic-xlsx` - Create, edit, analyze spreadsheets with formulas and formatting
- `/product-brief` - Extract product ideas through guided questions and generate full PRD
- `/triage` - Process inbox intelligently, extract tasks, update person pages

### How Skills Work

**Simple version:**
1. Skills live in this folder as instruction files
2. You run a skill by typing `/skill-name` (like `/daily-plan`)
3. Claude reads the instructions and follows them
4. You get the result

**Example:** When you type `/daily-plan`, Claude:
- Checks your calendar for today's meetings
- Reviews your task list
- Looks at your weekly priorities
- Generates a focused plan for your day

### Skills Format

Skills follow the [Agent Skills](https://agentskills.io) standard - a universal format that works across AI assistants.

**Two parts:**

**1. Metadata** (at the top, tells Claude about the skill):
```yaml
---
name: daily-plan
description: Generate context-aware daily plan with calendar and tasks
---
```

**2. Instructions** (the rest of the file):
```
## How This Skill Works

1. Check the calendar for today
2. Review 03-Tasks/Tasks.md for high-priority items
3. Create a daily plan...
```

**Structure:**
- Each skill gets its own folder: `.claude/skills/daily-plan/`
- Main file is always called `SKILL.md`
- Can include supporting files (templates, scripts, examples)

**Benefits:**
- **Reusable** - run the same workflow anytime
- **Consistent** - same result every time
- **Organized** - each skill has its own space
- **Shareable** - works across AI assistants following Agent Skills standard

### Skills vs Agents

| Aspect | Skills | Agents |
|--------|--------|--------|
| **Invocation** | You type `/skill-name` or Claude loads it | Claude delegates work to isolated subagent |
| **Context** | Runs in your current conversation | Separate context window |
| **Interaction** | Can be interactive | Autonomous (no interruptions) |
| **Use case** | User-facing workflows | Background analysis/processing |
| **Example** | `/daily-plan` - start your day | `project-health` - analyze all projects |

---

## Creating Your Own Skills

Want to create a custom skill? Run `/anthropic-skill-creator` for comprehensive guidance.

### When to Create a Skill

Create a skill when you have:
- **Repeated workflow** - You do the same multi-step process regularly
- **Domain expertise** - Specialized knowledge Claude doesn't have by default
- **Tool integration** - Need to orchestrate multiple tools in sequence
- **Complex logic** - Business rules, schemas, or procedures that need precision

### Quick Start

1. **Run the skill creator:**
   ```
   /anthropic-skill-creator
   ```

2. **Follow the guided process** to define:
   - Skill name and description
   - When it should be triggered
   - Step-by-step workflow
   - Required tools and resources

3. **Test and refine:**
   - Use your new skill with `/your-skill-name`
   - Iterate on the instructions based on results

### Skill Ideas

**Personal:**
- `/workout-plan` - Generate exercise routines based on goals
- `/recipe-scale` - Scale recipes and adjust cooking times
- `/expense-categorize` - Categorize expenses for budgeting

**Work:**
- `/standup-prep` - Generate daily standup update from recent work
- `/bug-triage` - Prioritize and categorize bug reports
- `/interview-prep` - Prepare for conducting technical interviews

**Content:**
- `/blog-outline` - Convert rough notes into structured blog outline
- `/social-adapt` - Adapt content for different social platforms
- `/newsletter-draft` - Compile recent highlights into newsletter

The best skills solve **your** specific problems. Don't build generic tools - build for your actual workflows.

---

## What Goes Here

Skill definition files (`SKILL.md` format) that:
- Define user-invoked commands (e.g., `/daily-plan`, `/review`)
- Orchestrate tools and workflows
- Provide interactive guidance
- Execute single-purpose tasks

## When to Use

Create a skill when:
- **User-initiated** - Command invoked explicitly by user
- **Clear purpose** - Solves one specific job-to-be-done
- **Reusable** - Used repeatedly, not one-time setup
- **Tool orchestration** - Coordinates multiple tool calls

Don't create a skill for:
- Autonomous background tasks (use agents instead)
- One-time setup flows (use flows instead)
- Internal utilities (use hooks instead)

## Structure

Skills follow Agent Skills standard:

```
skill-name/
└── SKILL.md       # Full skill definition with metadata
```

Invoked with `/skill-name` - automatically discovered by Claude.

## Skill Types in Dex

Dex includes two categories of skills:

### Dex Skills (PKM-Specific)

Built specifically for personal knowledge management and productivity workflows in Dex:

**Getting Started:**
- `/getting-started` - Interactive post-onboarding tour (adaptive to your setup)

**Daily Workflow:**
- `/daily-plan` - Context-aware daily planning
- `/daily-review` - End of day review with learning capture
- `/journal` - Start or manage journaling

**Weekly Workflow:**
- `/week-plan` - Set weekly priorities
- `/week-review` - Weekly synthesis

**Quarterly Workflow:**
- `/quarter-plan` - Set quarterly goals
- `/quarter-review` - Review and capture learnings

**Meetings:**
- `/meeting-prep` - Prepare for meetings
- `/process-meetings` - Process Granola meetings

**Career Development:**
- `/career-setup` - Initialize career system
- `/career-coach` - Career reflections and assessments
- `/resume-builder` - Build resume through guided interview

**Projects:**
- `/project-health` - Review project status
- `/product-brief` - Generate PRD from ideas
- `/triage` - Organize inbox and extract tasks

**AI Configuration:**
- `/ai-setup` - Configure budget cloud models (80% cheaper) and offline mode
- `/ai-status` - Check your AI configuration and credits

**Ambient Intelligence (Beta):**
- `/screenpipe-setup` - Enable screen capture for work context *(requires beta activation)*
- `/screenpipe-disable` - Stop screen capture and optionally delete data

**System Management:**
- `/xray` - AI education: understand what just happened under the hood, learn how context, MCPs, hooks work
- `/prompt-improver` - Transform vague prompts via Anthropic Messages API
- `/dex-level-up` - Discover unused features
- `/dex-backlog` - AI-powered idea ranking
- `/dex-improve` - Workshop improvement ideas
- `/dex-whats-new` - Check for system improvements (learnings + Claude updates)
- `/dex-update` - Update Dex automatically (shows what's new, updates if confirmed, no technical knowledge needed)
- `/dex-rollback` - Undo last update if something went wrong
- `/dex-obsidian-setup` - Enable Obsidian integration and migrate vault to wiki links
- `/integrate-mcp` - Integrate existing MCP servers from Smithery.ai marketplace
- `/integrate-notion` - Connect Notion for workspace search and meeting context
- `/integrate-slack` - Connect Slack for conversation search and people context
- `/integrate-google` - Connect Google Workspace (Gmail, Calendar, Contacts)
- `/create-mcp` - Create new MCP integrations

### Anthropic Skills (General-Purpose)

Provided by Anthropic for broad productivity tasks (prefixed with `anthropic-`):

**Document Creation & Editing:**
- `/anthropic-docx` - Word documents with tracked changes, comments, formatting
- `/anthropic-pptx` - Presentations with layouts and speaker notes
- `/anthropic-xlsx` - Spreadsheets with formulas and data analysis
- `/anthropic-pdf` - PDF manipulation, text extraction, form filling

**Writing & Communication:**
- `/anthropic-doc-coauthoring` - Structured workflow for co-authoring documentation
- `/anthropic-internal-comms` - Internal communications (status reports, updates, FAQs)

**Design & Visual:**
- `/anthropic-algorithmic-art` - Create algorithmic art using p5.js
- `/anthropic-canvas-design` - Visual design and posters
- `/anthropic-frontend-design` - Production-grade frontend interfaces
- `/anthropic-theme-factory` - Style artifacts with pre-set themes
- `/anthropic-slack-gif-creator` - Animated GIFs optimized for Slack
- `/anthropic-brand-guidelines` - Apply Anthropic brand colors/typography

**Development:**
- `/anthropic-mcp-builder` - Create MCP servers for external service integration
- `/anthropic-web-artifacts-builder` - Multi-component HTML artifacts with React
- `/anthropic-webapp-testing` - Test local web applications with Playwright

**Meta:**
- `/anthropic-skill-creator` - Guide for creating new skills

## Related

- **Commands** (`.claude/commands/`) - Legacy location (deprecated)
- **Agents** (`.claude/agents/`) - Autonomous multi-step tasks
- **CLAUDE.md** - Core prompt that lists available skills
