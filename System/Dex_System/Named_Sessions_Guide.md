# Named Sessions

Pick up exactly where you left off. Named sessions keep full conversation history so you never re-explain context.

---

## Naming a Session

During any conversation, run:

```
/rename Acme Deal Prep
```

The name persists across restarts. Name sessions early -- easier to find later.

## Resuming a Session

```
claude --resume "Acme Deal Prep"
```

You get full conversation history, all files previously read, and any agent memory from prior runs.

## Naming Conventions

Consistent names make sessions easy to find:

| Pattern | When | Example |
|---------|------|---------|
| `[Account] Deal Prep` | Deal-specific work | `Acme Deal Prep` |
| `[Project] Build` | Implementation | `Dex Memory Build` |
| `Weekly Planning` | Recurring rituals | `Weekly Planning` |
| `Content: [Topic]` | Content creation | `Content: AI Strategy Post` |
| `[Person] 1:1 Prep` | Meeting prep | `Paul 1:1 Prep` |

## Compounding Intelligence

Named sessions combined with agent memory get smarter over time:

- **First session** -- Agent scans everything from scratch
- **Second session** -- Remembers what it flagged, surfaces trends
- **Third session** -- Knows your patterns, anticipates needs

Each session builds on the last. No re-scanning. No re-explaining.

## Tips

- One session per project or account keeps context focused
- Ritual sessions (`/daily-plan`, `/week-review`) can be reused across weeks
- Sessions are local to your machine -- private and secure

## Auto-Naming (Planned)

Sessions will auto-name based on the first skill invoked:

- `/daily-plan` -> "Daily Plan -- 2026-02-19"
- `/meeting-prep Acme` -> "Meeting Prep -- Acme"
- `/week-review` -> "Week Review -- W08"

Removes the manual naming step for ritual sessions.
