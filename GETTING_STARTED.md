# Your First Month with Dex

You're set up. Now what? This guide walks you through building Dex into your daily workflow over 4 weeks — starting with the basics and layering in more as it becomes natural.

**How to use commands:** Type any `/command` directly into your Claude conversation. That's it.

---

## Week 1: The Daily Basics

Your goal this week is just two commands, every workday.

### Morning: `/daily-plan`

Run this first thing. It pulls your calendar, open tasks, and weekly priorities into a plan for the day. It'll show you:
- What meetings you have and who you're meeting
- Which tasks need attention (sorted by priority)
- How much free time you actually have

### End of day: `/daily-review`

Run this before you close up. It walks you through:
- What got done vs. what was planned
- Action items from today's meetings
- What to carry forward to tomorrow

### When someone shares meeting notes: just paste them

No command needed. Paste meeting notes into the chat and Dex will extract action items, identify people mentioned, and suggest updates to person pages and projects.

### If meetings auto-sync from Granola: `/process-meetings`

This batch-processes any meetings that synced from Granola — extracts tasks, updates person pages, and organises notes into your vault.

**That's it for week 1.** `/daily-plan` in the morning, `/daily-review` at the end of the day.

---

## Week 2: People and Meetings

Now that you have a daily rhythm, start getting value from people context.

### Before important meetings: `/meeting-prep`

Tell it who you're meeting and it pulls together:
- Everything you know about each person (role, last interaction, open items)
- Related projects and recent decisions
- Suggested talking points

Especially useful before 1:1s, external calls, and board meetings.

### Build person pages naturally

You don't need to create person pages manually. They get created automatically when:
- You process meeting notes that mention someone
- You run `/meeting-prep` for someone new
- You paste notes that reference people

Each person page tracks: role, company, meeting history, action items involving them.

### Ask Dex questions about people

Just ask naturally:
- "When did I last meet with Sarah?"
- "What are my open action items with the finance team?"
- "What do I know about [company name]?"

---

## Week 3: The Weekly Rhythm

### Monday morning: `/week-plan`

Sets your priorities for the week. It looks at:
- Your strategic pillars (Hiring, Offsite Planning, Finance Function, Systems & Ops)
- Calendar load for the week
- Carry-over tasks from last week
- Quarterly goals (if you've set them)

Produces a focused list of what actually matters this week.

### Friday afternoon: `/week-review`

Synthesises what happened this week with real data:
- Tasks completed vs. planned
- Which pillars got attention (and which didn't)
- Key decisions and outcomes
- Patterns worth noting

This is where Dex starts becoming genuinely useful — it spots things like "you've spent 3 weeks not touching the Finance Function pillar."

---

## Week 4: Power Features

By now you have a rhythm. These are the tools that make Dex more than a planner.

### `/project-health`

Scans all your active projects and flags:
- Stalled projects with no recent activity
- Missing next actions
- Blockers that haven't been addressed

Good to run weekly or when you feel like things are slipping.

### `/triage`

Got a messy inbox? Files in the wrong place? Scattered tasks? Triage routes everything to where it belongs using your pillars and priorities as context.

### `/scrape [url]`

Need to pull information from a website — job postings, competitor pages, event details? This handles it, including sites with anti-bot protection.

### `/health-check`

Something not working? MCP servers down? Run this and it'll diagnose and fix itself.

---

## Command Cheat Sheet

### Daily (use these every day)
| Command | When | What it does |
|---------|------|-------------|
| `/daily-plan` | Morning | Plan your day with calendar + tasks |
| `/daily-review` | End of day | Reflect, capture follow-ups, prep tomorrow |

### Weekly
| Command | When | What it does |
|---------|------|-------------|
| `/week-plan` | Monday | Set weekly priorities aligned to pillars |
| `/week-review` | Friday | Review the week with real metrics |

### Meetings
| Command | When | What it does |
|---------|------|-------------|
| `/meeting-prep` | Before a meeting | Gather context on attendees |
| `/process-meetings` | After Granola sync | Batch-process meeting notes |

### As needed
| Command | What it does |
|---------|-------------|
| `/project-health` | Scan projects for blockers and stalled work |
| `/triage` | Route orphaned files and scattered tasks |
| `/product-brief` | Generate a PRD through guided questions |
| `/scrape` | Extract data from websites |
| `/save-insight` | Capture a learning from completed work |
| `/compile-research` | Turn raw research into a structured wiki |
| `/health-check` | Diagnose and fix Dex system issues |
| `/prompt-improver` | Sharpen a vague prompt into something specific |

### Strategic (monthly/quarterly)
| Command | What it does |
|---------|-------------|
| `/quarter-plan` | Set 3-5 quarterly goals |
| `/quarter-review` | Review quarter completion and learnings |
| `/identity-snapshot` | Generate a profile of your working patterns |

### System
| Command | What it does |
|---------|-------------|
| `/getting-started` | Interactive tour of Dex (good to run now!) |
| `/dex-update` | Update Dex to latest version |
| `/dex-level-up` | Discover features you haven't tried yet |

---

## Your Pillars

Everything in Dex organises around your strategic pillars:

1. **Hiring** — Sourcing, interviewing, offers, onboarding
2. **Offsite Planning** — Team offsites and in-person events
3. **Finance Function** — Finance processes, reporting, controls
4. **Systems & Ops** — Internal tooling, processes, infrastructure

When you create tasks, Dex infers which pillar they belong to. Weekly and quarterly reviews show how your time distributes across these.

---

## Folder Structure (if you're browsing the vault)

You don't need to navigate these manually — Dex handles it. But if you're curious:

```
00-Inbox/          <- Where new stuff lands (meetings, ideas)
01-Quarter_Goals/  <- Quarterly goals
02-Week_Priorities/<- This week's focus
03-Tasks/          <- Work and personal task backlogs
04-Projects/       <- Active projects
05-Areas/          <- People, companies, career
06-Resources/      <- Reference material, system docs
07-Archives/       <- Completed work
System/            <- Config (don't edit unless you know what you're doing)
```

---

## Tips

- **You don't need to remember commands.** Just describe what you want ("prep me for my 2pm meeting", "what's stalled this week?") and Dex will figure it out.
- **Person pages accumulate over time.** The more meetings you process, the richer the context gets. After a few weeks, `/meeting-prep` becomes genuinely useful.
- **Start small.** `/daily-plan` and `/daily-review` every day for a week is enough. Layer in weekly rhythms when that feels natural.
- **Ask for help.** Type "what can you do?" or `/dex-level-up` to see features you haven't tried.
