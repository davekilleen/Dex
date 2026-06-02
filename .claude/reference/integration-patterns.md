# Integration Patterns — Shared Reference

Reference document for all integration setup skills. Every new integration follows these patterns.

## Integration Manifest (Frontmatter Schema)

Every setup skill includes this in its YAML frontmatter:

```yaml
---
name: [tool]-setup
description: Connect [Tool] to Dex for [one-liner]
integration:
  id: [tool]
  name: [Full Name]
  mcp_server: [mcp-server-name]
  auth: oauth2 | api_key | api_key_token | chrome_session | none
  enhances:
    - skill: daily-plan
      capability: "[What changes in daily plan]"
    - skill: meeting-prep
      capability: "[What changes in meeting prep]"
  new_capabilities:
    - name: [capability-name]
      trigger: "[When this activates]"
  sync:
    direction: read | write | bidirectional
    entities: [what syncs]
---
```

## Trust Level UX (User-Facing)

**NEVER surface tier language (tier 1/2/3) to users.** Present as natural questions:

### For Read-Only Integrations (Email, Chat)
No question needed — reading context is always automatic and transparent.

### For Task Sync Integrations (Todoist, Things, Trello, Jira)
```
How hands-on do you want to be with task sync?

1. **"Show me first"** — I'll preview changes before syncing (recommended to start)
2. **"Keep them in sync"** — Tasks auto-sync both ways, silently
3. **"Only pull in"** — Import tasks from [Tool] but don't push back
```

### For Send/Write Integrations (Email, Chat messages)
```
For sending messages and emails:

1. **"Always preview"** — I'll draft it, you approve before sending (recommended)
2. **"Send routine, confirm important"** — Auto-send follow-ups, confirm new threads
```

Store choice in `System/integrations/config.yaml` under `trust_level`:
- `confirm_each` → Show me first / Always preview
- `autonomous` → Keep them in sync / Send routine
- `read_only` → Only pull in

## Capability Cascade (Post-Connection Moment)

Every setup skill ends with this pattern. This is the **delight moment** — show them exactly what just got better.

```markdown
## After Successful Connection

Read the integration's manifest from this skill's frontmatter. Present:

"**[Tool] is connected!** Here's what just changed:"

### Enhanced (existing skills that got smarter)
For each `enhances` entry:
- **`/[skill]`** → [capability description]

### New Superpowers
For each `new_capabilities` entry:
- [icon] [capability name] — [trigger description]

### How It Works
- **Reading:** [Tool] context appears automatically in your plans and prep
- **Writing:** [trust level description based on user's choice]
- **Privacy:** [integration-specific privacy note]

"These work automatically starting now. Run `/dex-level-up` anytime to see what else you can do."
```

## Graceful Degradation

Skills check integrations at runtime. If an integration is enabled but unhealthy:
1. Skip silently — no error to user
2. Continue with vault-only context
3. Log to debug (only if INTEGRATION_DEBUG env is set)

Pattern in skills:
```markdown
### Integration Context (if available)
Check `System/integrations/config.yaml` for enabled integrations.
For each enabled integration with relevant capabilities:
1. Check if MCP server responds (health check tool or quick test)
2. If healthy: query for context, merge into existing flow
3. If unhealthy: skip silently (graceful degradation)
```

## Config File Rules

`System/integrations/config.yaml` is the single source of truth:
- Only setup skills write to it
- Skills read at runtime to know what's available
- Commented-out sections are templates

## Adding Integrations

Users connect tools with `/integrate-mcp` or the individual setup skills
(`/todoist-setup`, `/things-setup`, etc.). Setup skills write to
`System/integrations/config.yaml`; other skills read it at runtime.
