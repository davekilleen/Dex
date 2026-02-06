# Dex Skill Development - Analytics Checklist

**When creating or modifying any Dex skill, MCP tool, or capability, complete this checklist.**

This ensures all new features are tracked for product analytics (if user has opted in).

---

## 1. Define the Event

**Event name:** `{skill_name}_completed` or `{action}_performed`

**When to fire:** At the end of successful skill execution

**Properties to include:**
- Counts (items processed, tasks created, etc.)
- Duration if relevant
- Categorical outcomes (mode used, type selected)

**Never include:**
- Personal content (names, task titles, meeting notes, conversations)
- What users DID with the feature (only that they used it)
- Free-form text input
- PII
- User customizations or additions (only Dex built-in features)

---

## 2. Update Event Strategy

Add your event to `System/PRDs/dex-analytics-events.md`:

```markdown
| `/your-skill` | `your_skill_completed` | `property1`, `property2` | What insight this provides |
```

Find the right section:
- Core Skills → daily workflows
- Task Management → Work MCP operations
- People & Meetings → meeting/person related
- Career → career development
- Projects → project tracking
- System Evolution → meta/improvement skills
- Integrations → external tool connections

---

## 3. Update usage_log.md

Add a checkbox in the appropriate section of `System/usage_log.md`:

```markdown
- [ ] Your feature name (`/your-skill`)
```

This enables:
- Journey metadata calculation
- Feature adoption tracking
- `/dex-level-up` feature discovery

---

## 4. Wire Up Event Firing

Add to your skill's SKILL.md (at the end of the workflow):

```markdown
## Analytics

At completion, if analytics is enabled:

1. Fire event: `fire_event('your_skill_completed', {'items': count, 'mode': selected_mode})`
2. Mark feature used: `mark_feature_used('Your feature name')`
```

Or for MCP tools, add to the Python handler:

```python
from analytics_helper import fire_event, mark_feature_used

# At end of tool execution
fire_event('tool_name_used', {'property': value})
mark_feature_used('Feature name')
```

---

## 5. Privacy Check

Before finalizing, verify:

- [ ] **Dex-only** - Only tracking built-in Dex features (not user customizations)
- [ ] **Usage not content** - Tracking THAT feature was used, not what they did with it
- [ ] No personal content (names, task titles, meeting content, conversations)
- [ ] Only categorical or numeric values (counts, categories)
- [ ] Event only fires if user opted in (`check_consent()`)

---

## Quick Reference

**Event naming patterns:**
| Type | Pattern | Example |
|------|---------|---------|
| Skill completion | `{skill}_completed` | `daily_plan_completed` |
| MCP tool | `{tool}_used` | `task_created` |
| Feature enabled | `{feature}_enabled` | `obsidian_enabled` |
| Integration | `{service}_connected` | `granola_connected` |
| Discovery | `feature_first_use` | with `feature_name` property |

**Files to update:**
1. `System/PRDs/dex-analytics-events.md` - Event definition
2. `System/usage_log.md` - Feature checkbox
3. Skill SKILL.md or MCP Python file - Event firing code

---

## Example: New Skill `/my-workflow`

**1. Event definition:**
- Name: `my_workflow_completed`
- Properties: `items_processed`, `duration_seconds`, `mode`

**2. dex-analytics-events.md entry:**
```markdown
| `/my-workflow` | `my_workflow_completed` | `items_processed`, `mode` | Workflow adoption |
```

**3. usage_log.md entry:**
```markdown
- [ ] My workflow (`/my-workflow`)
```

**4. SKILL.md addition:**
```markdown
## Analytics

Fire `my_workflow_completed` with properties:
- `items_processed`: number of items handled
- `mode`: which mode was selected
- `duration_seconds`: time taken

Mark feature used: "My workflow"
```

---

*This checklist ensures Dex can track feature adoption while respecting user privacy.*
