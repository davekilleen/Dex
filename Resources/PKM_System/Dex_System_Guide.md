# Dex System Guide

Your comprehensive guide to using and customizing your Dex PKM system.

---

## Quick Reference

### Essential Commands

| Command | When to Use |
|---------|-------------|
| `/daily-plan` | Start your day — reviews calendar, suggests priorities |
| `/daily-review` | End your day — capture wins, lessons, tomorrow's setup |
| `/triage` | Process your inbox items |
| `/process-meetings` | Import meetings from Granola |

### File Locations

| What | Where |
|------|-------|
| Your tasks | `Tasks.md` |
| Week priorities | `Inbox/Week Priorities.md` |
| Strategic pillars | `System/pillars.yaml` |
| Your preferences | `System/user-profile.yaml` |

---

## The Pillar System

Everything in Dex aligns to your strategic pillars — the 2-4 main focus areas that matter most.

### How Pillars Work

1. **Task categorization** — Every task is tagged with a pillar
2. **Balance checking** — Dex warns if you're neglecting a pillar
3. **Priority limits** — P0 (max 3), P1 (max 5), P2 (max 10) keep you focused

### Configuring Pillars

Edit `System/pillars.yaml`:

```yaml
pillars:
  - id: product_dev
    name: "Product Development"
    description: "Building and shipping features"
    keywords:
      - roadmap
      - sprint
      - feature
      - launch
```

---

## Task Management

### Task Format

```markdown
- [ ] [P1] Task description [[Related Page]] #pillar
```

- `[ ]` — Checkbox (incomplete)
- `[x]` — Checkbox (complete)
- `[P0-P3]` — Priority level
- `[[Page]]` — Links to related pages
- `#pillar` — Pillar tag

### Priority Levels

| Level | Meaning | Limit |
|-------|---------|-------|
| P0 | Critical/urgent — needs attention today | Max 3 |
| P1 | Important — this week | Max 5 |
| P2 | Normal — soon | Max 10 |
| P3 | Low priority / someday | No limit |

### The Cracks Detector

Run `/cracks` to find:
- Tasks without recent updates
- Stale projects
- People you haven't contacted
- Promises you might have forgotten

---

## Meeting Intelligence

### With Granola

If you use Granola for meeting transcription:

1. **Process today's meetings:** `/process-meetings today`
2. **Process all unprocessed:** `/process-meetings`
3. **Find specific meeting:** `/process-meetings "client name"`

### What Gets Extracted

- Summary (2-3 sentences)
- Key discussion points
- Decisions made
- Action items (for you and others)
- Person page updates

### Without Granola

You can still capture meetings manually:
1. Create note in `Inbox/Meetings/`
2. Use template from `System/Templates/Meeting_Notes.md`
3. Run `/triage` to process

---

## Person Pages

### Automatic Updates

Person pages in `People/` are updated automatically when:
- You mention someone in meeting notes
- You create tasks involving them
- You capture context about them

### Manual Creation

Use the template at `System/Templates/Person_Page.md`:

```markdown
---
name: Jane Smith
company: Acme Corp
role: VP Product
type: external
---

# Jane Smith

## Context
- Met at conference 2024
- Interested in our roadmap

## Meeting History
<!-- Auto-populated -->

## Related Tasks
<!-- Auto-populated -->
```

---

## Templates

Templates live in `System/Templates/`. Key ones:

| Template | Purpose |
|----------|---------|
| Meeting_Notes.md | Structured meeting capture |
| Person_Page.md | Relationship tracking |
| Project.md | Project planning |
| Daily_Note.md | Daily capture |
| Weekly_Journal.md | Weekly reflection |

### Using Templates

1. Copy from `System/Templates/`
2. Fill in the sections
3. Save to appropriate folder

---

## Agents

Agents in `.claude/agents/` are specialized reviewers that check your work:

| Agent | Purpose |
|-------|---------|
| cracks-detector | Finds things falling through |
| pillar-balance | Checks strategic alignment |
| project-health | Reviews project status |
| meeting-prep | Prepares for meetings |

Agents are invoked automatically by commands or can be run manually.

---

## Customization

### Adding Commands

Create `.claude/commands/my-command.md`:

```markdown
---
name: my-command
description: What this does
---

# My Command

Instructions for Claude to follow...
```

### Modifying Behavior

Edit `CLAUDE.md` to change:
- Core behaviors
- Writing style
- File conventions

### Role-Specific Setup

Role definitions in `.claude/roles/` configure:
- Default pillars
- Folder structure
- Recommended templates

---

## Troubleshooting

### Commands Not Working

1. Check `.claude/commands/` exists
2. Restart Cursor
3. Verify you're in the dex folder

### Tasks Not Syncing

1. Check `Tasks.md` format
2. Verify `System/pillars.yaml` is valid
3. Run `/triage` to reprocess

### MCP Server Issues

```bash
# Test task server
VAULT_PATH=/path/to/dex python core/mcp/task_server.py
```

---

## Backup & Sync

### Git Recommended

```bash
git init
git add .
git commit -m "Initial Dex setup"
```

### What to Exclude

Already in `.gitignore`:
- `.env` (secrets)
- `node_modules/`
- `.obsidian/workspace.json`

---

*For more help, browse the `.claude/` folder or ask Claude directly.*
