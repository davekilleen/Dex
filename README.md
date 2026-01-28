# Dex — Your AI Chief of Staff

**A starter kit for building your personal operating system with Claude.**

Clone this repo, run the setup wizard, tell it your role — and in 30 minutes you have a working system tailored to how you work. Task management, meeting intelligence, relationship tracking, daily planning. All configured for whether you're a CMO, a sales leader, a PM, or any of 31 other roles.

No coding required. Just [Cursor](https://cursor.com) and conversation.

Companion to [Episode 8 of The Vibe PM Podcast](https://link-tbd) and the [full blog post](https://link-tbd).

---

## Who This Is For

Non-engineers.

Product managers, marketers, sales leaders, designers, executives, HR leaders, consultants, coaches, analysts — anyone who wants the same leverage from AI that technical people have had access to.

**You don't need to know how to code.** Just follow the setup and talk to your AI assistant.

---

## Why This Exists

Most people use AI as a slightly smarter search engine. Dex is fundamentally different.

It's a personal operating system that handles the cognitive overhead of professional life. Think of it as hiring a Chief of Staff whose memory is your file system — who tracks commitments, relationships, and context so you can focus on conversations and decisions that actually matter.

---

## Quick Start

### Prerequisites

- [Cursor](https://cursor.com/) installed
- [Node.js 18+](https://nodejs.org/) installed

### Step 1: Clone in Cursor

1. Open **Cursor**
2. Press `Cmd+Shift+P` (Mac) or `Ctrl+Shift+P` (Windows/Linux) to open the command palette
3. Type **"Git: Clone"** and select it
4. Paste this URL:
   ```
   https://github.com/davekilleen/dex.git
   ```
5. Choose where to save it (e.g., your Documents folder)
6. Click **Open** when Cursor asks if you want to open the cloned repository

### Step 2: Run the installer

Open Cursor's terminal (View → Terminal) and run:

```bash
./install.sh
```

### Step 3: Explore with Demo Mode (Optional)

Want to see Dex in action before adding your own data?

1. Open the Claude chat panel: `Cmd+L` (Mac) or `Ctrl+L` (Windows/Linux)
2. Type: `/demo on`
3. Try commands like `/daily-plan` or `/project-health` with sample data

Skip to Step 4 when ready to set up your own system.

### Step 4: Run the setup wizard

1. In the Claude chat panel, type:
   ```
   /setup
   ```
2. Answer the questions about your role, company size, and priorities

The wizard generates your personalized system in about 2 minutes.

---

## What You Get

| Feature | Description |
|---------|-------------|
| **Role-based scaffolding** | Tell it you're a CMO and get content pipelines. Sales VP gets deal tracking. 31 roles supported. |
| **Task management** | Priority limits, duplicate detection, strategic pillar alignment |
| **Meeting intelligence** | Process Granola transcripts into structured notes with action items |
| **Person pages** | Relationship context that builds over time |
| **Compound learning** | Captures your preferences and mistakes — every session improves the next |
| **17 commands** | Daily planning, reviews, triage, meeting prep — invoke with `/command-name` |

---

## The System That Improves Itself

Here's what makes Dex different from other starter kits: **it learns from how you work.**

Every session, Dex captures context about your preferences, mistakes, and workflows into `Resources/Learnings/`:

- **Mistake Patterns** — Logged mistakes become rules that prevent repetition
- **Working Preferences** — Your communication style, tool preferences, meeting habits
- **Session Learnings** — Silent capture of what works and what doesn't

**Day 1:** Helpful but generic.  
**Week 2:** Knows your preferences, catches your common mistakes.  
**Month 1:** Genuine thought partner that adapts to your style.

This is the compound engineering unlock: instead of your system decaying over time like traditional software, every session makes the next one better.

**Bonus:** Run `/whats-new` to check for new Claude Code capabilities and get upgrade suggestions tailored to your workflows.

---

## The Six Jobs It Does

| Job | What It Solves |
|-----|----------------|
| **Start Each Day Focused** | One command gives you three priorities. Heavy meeting day? Drops to two. The system won't let you overcommit. |
| **Never Miss a Commitment** | Promises made in meetings get extracted automatically. Three days old? Flagged. You can't forget. |
| **Track Relationships** | Before any call: what you discussed last time, open items, what they care about. Never walk in cold. |
| **Connected via MCP** | Calendar, meeting transcripts, analytics — your tools feed the AI automatically. |
| **Compound Learning** | Day one: helpful but generic. Week two: knows your preferences. Month one: genuine thought partner. |
| **Self-Improving System** | Captures preferences and mistakes. Each session makes the next better. Run `/whats-new` for Claude updates. |

---

## Commands

Invoke any command by typing `/command-name` in the Claude chat panel.

**Tip:** Want to know how a command works? Just ask Claude: *"Explain what /daily-plan does"* — it'll walk you through the details.

### Daily Workflow

| Command | What It Does |
|---------|--------------|
| `/daily-plan` | Morning planning — calendar, tasks, meeting context, today's priorities |
| `/daily-review` | End of day — capture wins, lessons, set up tomorrow |
| `/journal` | Morning, evening, or weekly reflection prompts |
| `/week` | Weekly synthesis — patterns, energy mapping, project progress |

### Organization

| Command | What It Does |
|---------|--------------|
| `/triage` | Process inbox — files and tasks with intelligent routing |
| `/save-insight` | Capture learnings from completed work |

### Projects & Meetings

| Command | What It Does |
|---------|--------------|
| `/project-health` | Review all projects for stalls and blockers |
| `/meeting-prep` | Prepare for upcoming meetings with attendee context |
| `/process-meetings` | Process Granola meeting transcripts into structured notes |

### System

| Command | What It Does |
|---------|--------------|
| `/setup` | Initial setup or reconfigure |
| `/reset` | Start fresh — restructure your Dex from scratch |
| `/dex-improve` | Design partner for system improvements |
| `/create-mcp` | Create custom integrations with external tools |
| `/whats-new` | Check Claude Code releases and get suggested upgrades for your system |
| `/prompt-improver` | Turn a basic prompt into a structured, effective one using Anthropic's best practices |

---

## Supported Roles

31 role configurations. The scaffolding changes completely based on your answer.

<details>
<summary>View all roles</summary>

**Core Functions:** Product Manager, Sales, Marketing, Engineering, Design

**Customer-Facing:** Customer Success, Solutions Engineering

**Operations:** Product Operations, RevOps/BizOps, Data/Analytics

**Support Functions:** Finance, People (HR), Legal, IT Support

**Leadership:** Founder

**C-Suite:** CEO, CFO, COO, CMO, CRO, CTO, CPO, CIO, CISO, CHRO, CLO, CCO

**Independent:** Fractional CPO, Consultant, Coach

**Investment:** Venture Capital / Private Equity

</details>

---

## Folder Structure

```
dex/
├── Active/               # Current work
│   ├── Projects/         # Time-bound initiatives
│   ├── Relationships/    # Key accounts and stakeholders
│   └── Content/          # Things you create
├── Inbox/                # Capture zone
│   ├── Meetings/         # Meeting notes
│   └── Voice_Notes/      # Quick captures
├── Resources/            # Reference material
│   └── Learnings/        # Compound knowledge
├── People/               # Person pages
│   ├── Internal/         # Colleagues
│   └── External/         # Customers, partners
├── System/               # Configuration
│   └── pillars.yaml      # Your strategic pillars
├── Tasks.md              # Your task list
└── CLAUDE.md             # AI behavior configuration
```

Role-specific folders are added during onboarding.

---

## MCP Servers (What Makes It Reliable)

MCP (Model Context Protocol) gives Claude structured access to your data and tools. Instead of the AI improvising how to create a task or check your calendar, MCP servers handle these operations reliably with validation and error handling.

**Dex includes 3 MCP servers:**

| Server | What It Does |
|--------|--------------|
| **Task MCP** | Creates, updates, and manages tasks. Enforces priority limits (max 3 P0s). Catches duplicates before you create them. Ensures every task connects to your strategic pillars. |
| **Calendar MCP** | Reads your Apple Calendar. Surfaces today's meetings, prep needed, attendee context. |
| **Granola MCP** | Processes meeting transcripts. Extracts action items, decisions, key points. Updates person pages automatically. |

You don't need to configure these — they work out of the box after running `/setup`.

**Want to add your own?** Run `/create-mcp` for a guided wizard to connect external services (CRM, analytics, etc).

---

## What Runs Automatically

### Hooks (Claude Code only)

Hooks fire automatically when certain events happen. They only work in Claude Code (terminal or desktop app with Claude Code enabled) — not in Cursor's agent mode.

| Hook | When It Fires | What It Does |
|------|---------------|--------------|
| **Session Start** | Every new session | Checks for updates, syncs with GitHub |
| **Person Context** | Reading a person page | Injects related context (meetings, tasks, relationships) |
| **Company Context** | Reading a company page | Pulls cross-deal intelligence |
| **Key Account Enricher** | Creating/editing account pages | Auto-populates with relevant data |
| **Task Context** | Editing task-related files | Ensures pillar alignment |
| **Sound Notification** | Session complete or needs input | Ping sound so you know when to look |

### Background Automation

| Feature | Frequency | Requirement |
|---------|-----------|-------------|
| **Meeting sync** | Every 30 min | Granola + API key (Gemini/Anthropic/OpenAI) |

---

## Meeting Intelligence (Optional)

If you use [Granola](https://granola.ai) for meeting transcription:

- **Manual mode** — Run `/process-meetings` when you want. No API key needed.
- **Automatic mode** — Background sync every 30 minutes. Requires Gemini/Anthropic/OpenAI key.

Don't use Granola? Dex works great without it.

---

## Optional API Keys

**Dex works with your Cursor subscription out of the box.** All core features (daily planning, task management, meeting prep, triage) use Cursor's included Claude access.

**API keys are only needed for:**

| Feature | Key Required | Free Tier? | Get It |
|---------|--------------|------------|--------|
| `/prompt-improver` | Anthropic | No | [console.anthropic.com](https://console.anthropic.com) |
| Automatic meeting sync | Gemini, Anthropic, or OpenAI | Gemini yes | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |

*Note: Manual meeting processing via `/process-meetings` requires no API key.*

Add keys to `.env` (copy from `env.example`).

---

## The Compound Effect

**Day 1:** Set up complete. First command works.

**Week 1:** Daily ritual starts feeling natural. Catching things that would have slipped.

**Week 2:** The system feels like an extension of how you think. Start customizing.

**Beyond:** The AI learns your preferences, your style, mistakes to avoid. Every session makes the next better.

---

## The Voice Tip

Don't type. Talk. 200 words per minute versus 40.

Tools like [Superwhisper](https://superwhisper.com) and [FlowVoice](https://flowvoice.ai) transcribe instantly. Describe what you want — the AI builds it.

See [Episode 1 of The Vibe PM Podcast](https://link-tbd) for more on voice workflows.

---

## What It Costs

| Item | Cost |
|------|------|
| Cursor Pro | $20/month (Claude included) |
| Cursor Free | $0 (limited usage, enough to try it) |
| Time | 30 minutes to set up |
| Coding skills | None required |

---

## Resources

- [Vibe PM Episode 8](https://link-tbd) — Video walkthrough
- [Companion Blog Post](https://link-tbd) — Deep dive on all the concepts
- [Cursor](https://cursor.com) — The AI-powered editor
- [Granola](https://granola.ai) — Meeting transcription (optional)

---

## Share the Vibes

Found this useful? Share with colleagues:

> I've been using an AI personal operating system for my work — handles task management, meeting prep, relationship tracking, and daily planning. Non-engineers can set it up in 30 minutes. Check out the Vibe PM Podcast Episode 8 and the GitHub repo: [link-tbd]

---

## Credits

Built with Claude. Created by [Dave Killeen](https://www.linkedin.com/in/davekilleen/), Field CPO for EMEA at Pendo and host of The Vibe PM Podcast.

Inspired by:
- [Aman Khan's personal-os](https://github.com/amankhan/personal-os)
- [Compound Engineering](https://github.com/EveryInc/compound-engineering-plugin) by Dan Shipper and Every

---

## License

MIT

---

Run `/setup` to get started.
