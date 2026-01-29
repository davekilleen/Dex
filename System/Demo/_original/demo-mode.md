# Demo Mode Reference

Dex includes a demo mode with pre-populated content so you can explore the system before adding your own data.

## Toggling Demo Mode

- `/dex-demo on` - Enable demo mode (uses sample data)
- `/dex-demo off` - Disable demo mode (use your real vault)
- `/dex-demo status` - Check current mode
- `/dex-demo reset` - Restore demo content to original state

## What Demo Mode Provides

Demo mode uses content from `System/Demo/` which includes:

**Demo Persona:** Alex Chen, Senior Product Manager (L4) at TechCorp, working toward L5 promotion

**Sample Content:**

### Projects & Tasks (Job 6)
- 3 active projects in various stages (Mobile App Launch, Customer Portal Redesign, API Partner Program)
- Pre-populated tasks across P0-P3 priorities with pillar tags
- Career skill tags demonstrating skill development tracking
- Week Priorities snapshot

### People & Companies (Job 3)
- 5 person pages (internal and external contacts)
- 1 company page (Acme Corp) aggregating contacts, meetings, and tasks
- Meeting history and relationship context

### Meeting Intelligence
- A week of meeting notes (Jan 20-24, 2026)
- Scattered tasks in notes for `/triage` to extract
- Meeting prep examples

### Planning & Reflection (Jobs 2 & 5)
- Full week of daily plans (Monday-Friday)
- Weekly plan (W04)
- Morning and evening journal entries (5 days)
- Weekly journal (W04)
- Daily review example
- Weekly review (W03)

### Learning System (Job 5)
- Working Preferences documented (collaboration style, communication patterns)
- Mistake Patterns logged (4 patterns with prevention rules)
- Session Learnings examples (2026-01-20)
- Pattern recognition in weekly reviews

### Career Development (Job 7)
- Current_Role.md (L4 Senior PM)
- Career_Ladder.md (L4 → L5 progression framework)
- Review_History.md (2025 annual review)
- Growth_Goals.md (3 priority development areas)
- Evidence folder with achievements, feedback, and skill tracking
- Career skill tags on tasks linking daily work to growth

### System Evolution (Job 8)
- Dex_Backlog.md with 10 ranked improvement ideas (AI-scored)
- usage_log.md tracking feature adoption
- Ideas folder with unprocessed thoughts for `/triage`

## When to Use Demo Mode

- **New users:** Explore how Dex works before adding your own content
- **Demoing to colleagues:** Show the PKM system with realistic data
- **Testing commands:** Experiment without affecting your real vault

When demo mode is ON, all commands read from and write to the demo folder. Your real vault data is untouched.
