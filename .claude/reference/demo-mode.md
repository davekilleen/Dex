# Demo Mode Reference

Dex includes a demo mode with pre-populated content so you can explore the system before adding your own data.

## Toggling Demo Mode

- `/dex-demo on` - Enable demo mode and launch interactive demo selector
- `/dex-demo off` - Disable demo mode (use your real vault)
- `/dex-demo menu` - Show demo scenario menu (when demo mode is on)
- `/dex-demo status` - Check current mode
- `/dex-demo reset` - Restore demo content to original state

## Interactive Demo Selector

When you run `/dex-demo on`, you'll see a menu of **12 validated demo scenarios** that showcase different aspects of Dex.

**How it works:**
1. Run `/dex-demo on`
2. See Alex Chen persona intro and scenario menu
3. Enter a number (1-12) to launch that scenario
4. Follow the guided walkthrough
5. Return to menu anytime with `/dex-demo menu`

**Scenario categories:**
- **Daily Workflow (1-4):** Morning journal, daily planning, daily review, inbox triage
- **People & Context (5-6):** Person lookup, company intelligence
- **Planning & Review (7-9):** Weekly planning, weekly review, task management
- **Career Development (10-11):** Career system, career coach
- **System Evolution (12):** Learning & backlog

See `.claude/reference/demo-scenarios.md` for detailed scenario descriptions.

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

## Demo Flow Recommendations

### For Self-Exploration (10-15 minutes)
Start with scenarios **2, 5, 7** to see core workflow:
- Scenario 2: Daily Planning (context-aware planning)
- Scenario 5: Person Lookup (relationship tracking)
- Scenario 7: Weekly Planning (strategic prioritization)

### For Demoing to Colleagues (15-20 minutes)
**Recommended order:**
1. Scenario 2: Daily Planning - Show context-aware planning
2. Scenario 5: Person Lookup - Show relationship tracking
3. Scenario 9: Task Management - Show strategic task organization
4. Scenario 10: Career System - Show career development integration
5. Scenario 12: Learning & Backlog - Show system evolution

### For Comprehensive Demo (30-45 minutes)
Run through all 12 scenarios in order, spending 3-4 minutes per scenario.

## Tips for Demoing to Colleagues

- Start with the persona introduction (Alex Chen context) so they understand the role/situation
- For each scenario, reference the "talking points" to highlight what matters
- Show existing demo files first, then run commands to demonstrate the workflow
- Emphasize how daily work connects to strategic priorities (pillars → quarters → weeks → days)
- Point out unique features: career evidence capture, learning system, company intelligence
- End with Q&A about how they'd adapt it to their role

## Resetting Demo Content

If you make changes in demo mode and want to start fresh:
```
/dex-demo reset
```

This restores all demo content from `System/Demo/_original/` backup.
