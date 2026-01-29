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
04-Projects/              # Time-bound initiatives

05-Areas/                 # Ongoing responsibilities
├── People/               # Person pages
│   ├── Internal/         # Colleagues (same email domain)
│   └── External/         # Customers, partners (different email domain)
├── Companies/            # External organizations (universal)
└── Career/               # Career development (optional)

06-Resources/             # Reference material
└── Learnings/            # Compound knowledge (preferences, patterns)

07-Archives/              # Historical records
├── 04-Projects/          # Completed projects
├── Plans/                # Daily and weekly plans
└── Reviews/              # Daily, weekly, and quarterly reviews

00-Inbox/                  # Capture zone
├── Meetings/             # Meeting notes
└── Ideas/                # Quick captures and fleeting thoughts

System/                   # Configuration
├── Templates/            # Reusable note templates
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
Related: 04-Projects/Mobile_App_Launch.md
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

## Domain-Based People Routing

Person pages are automatically routed based on email domain matching:

- **Internal/** - Email matches company domain in `System/user-profile.yaml`
- **External/** - Different email domain, or no email provided

**Configure:** Set `email_domain` in `System/user-profile.yaml` (e.g., "acme.com")

**Multiple domains:** Separate with commas (e.g., "acme.com, acme.io")

**Manual override:** You can always move person pages manually if domain routing is incorrect.

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
| Skills | `.claude/skills/` | Executable skills following [Agent Skills standard](https://agentskills.io) |
| Guides | `.claude/guides/` | Reference documentation for Claude |
| Hooks | `.claude/hooks/` | Event-driven context injection |
| Settings | `.claude/settings.json` | Project settings (committed) |
| Local settings | `.claude/settings.local.json` | Local settings (not committed) |

---

## Active Hooks

Dex includes these automatic context injectors:

| Hook | Trigger | What it does |
|------|---------|--------------|
| `session-start.sh` | Session start | Injects learnings, preferences, urgent tasks, week priorities |
| `person-context-injector.cjs` | Reading files with person references | Injects role, company, last interaction, open items |
| `company-context-injector.cjs` | Reading files with company references | Injects contacts, recent meetings, open tasks |
| `session-end.sh` | Session end | Captures session transcript |

---

## Templates

Templates live in `System/Templates/` and include:

- `Daily_Note.md` - Daily planning/review
- `Meeting_Notes.md` - Meeting capture
- `Person_Page.md` - Person tracking
- `Project.md` - Project tracking
- `Weekly_Review.md` - Weekly synthesis

Use templates by copying them to the appropriate folder and filling in the content.
