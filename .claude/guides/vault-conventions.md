# Vault File Conventions

**Reference document for file naming, task formats, and movement rules.**

---

## File Naming

| Type | Format | Example |
|------|--------|---------|
| Daily notes | `YYYY-MM-DD - Topic` | `2026-01-22 - Week Review` |
| Meeting notes | `YYYY-MM-DD - [Topic].md` | `2026-01-22 - Q1 Planning.md` |
| Weekly priorities | `Week Priorities.md` | Single rolling file |
| Person pages | `Firstname_Lastname.md` | `Sarah_Chen.md` |
| Projects | `Project_Name.md` | `Mobile_App_Launch.md` |

---

## Folder Structure

```
Active/                   # Current work
├── Projects/             # Time-bound initiatives
├── Relationships/        # Key accounts, partners, stakeholders
└── Content/              # Thought leadership, docs you create

Inbox/                    # Capture zone
├── Meetings/             # Meeting notes
├── Voice_Notes/          # Quick captures (if used)
├── Ideas/                # Fleeting thoughts
└── Week Priorities.md    # This week's focus

Resources/                # Reference material
├── Claude_Code_Docs/     # Cached Claude Code documentation
└── Learnings/            # Compound knowledge (preferences, patterns)

People/                   # Person pages
├── Internal/             # Colleagues
└── External/             # Customers, partners, contacts

System/                   # Configuration
├── Templates/            # Reusable note templates
├── Skills/               # Reusable AI behaviors
└── pillars.yaml          # Your strategic pillars config
```

---

## Task Format

Standard task format:

```markdown
- [ ] Task description
```

With metadata (optional):

```markdown
- [ ] Task title
  - **Due:** Friday
  - **Context:** Additional info
```

With file references:

```markdown
- [ ] Follow up with John | People/External/John_Doe.md
```

---

## File References

Use plain file paths when referencing other notes:

```markdown
See People/External/Sarah_Chen.md for context.
Related: Active/Projects/Mobile_App_Launch.md
```

This works across all markdown editors (VS Code, Cursor, Obsidian, etc.) without requiring special syntax.

For person pages, the hooks will automatically inject context when you reference them in meeting notes.

---

## Movement Rules

- Use `mv` not `cp` to avoid duplicates
- Verify destination folders exist
- Update internal links after moves
- Add YAML frontmatter when organizing

---

## Pillar Tagging

Use YAML frontmatter to indicate strategic alignment:

```yaml
---
pillar: [pillar-1, pillar-2]
status: active
created: 2026-01-22
---
```

**Status values:** `active`, `paused`, `archived`

Pillars are configured in `System/pillars.yaml` during setup.

---

## Claude Code File Locations

| Type | Location | Purpose |
|------|----------|---------|
| Slash commands | `.claude/commands/` | Executable commands |
| Skills | `System/Skills/` | Reusable behavior prompts |
| Guides | `.claude/guides/` | Reference documentation for Claude |
| Hooks | `.claude/hooks/` | Event-driven context injection |
| Settings | `.claude/settings.json` | Project settings (committed) |
| Local settings | `.claude/settings.local.json` | Local settings (not committed) |

---

## Active Hooks

Dex includes these automatic context injectors:

| Hook | Trigger | What it does |
|------|---------|--------------|
| `person-context-injector.cjs` | Reading files with person references | Injects role, company, last interaction, open items |
| `company-context-injector.cjs` | Reading files with company references | Injects contacts, recent meetings, open tasks |
| `session-start.sh` | Session start | Injects learnings, preferences, urgent items |

---

## Templates

Templates live in `System/Templates/` and include:

- `Daily_Note.md` - Daily planning/review
- `Meeting_Notes.md` - Meeting capture
- `Person_Page.md` - Person tracking
- `Project.md` - Project tracking
- `Weekly_Review.md` - Weekly synthesis

Use templates by copying them to the appropriate folder and filling in the content.
