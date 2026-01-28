# Session Learnings

This folder contains **automatic learning capture** from your daily work with Dex.

## How It Works

As you work with Claude in Dex, the AI silently logs learnings in daily files:
- `2026-01-28.md` - Today's learnings
- `2026-01-27.md` - Yesterday's learnings
- etc.

**No action needed** - this happens automatically when:
- Claude makes a mistake you have to correct
- You mention a preference or pattern
- A gap in documentation is discovered
- A workflow improvement opportunity is spotted

## What Gets Captured

Each entry includes:
- **What happened** - The specific situation
- **Why it matters** - Impact on your workflows
- **Suggested fix** - Concrete improvement with file paths
- **Status** - pending/implemented/dismissed

## Review & Action

Learnings are automatically reviewed during:

1. **Weekly synthesis** (`/week`) - Consolidates patterns from the week
2. **System improvement review** (`/whats-new`) - Suggests concrete changes

You decide what to implement. Nothing changes without your approval.

## Example Entry

```markdown
## 09:23 - User prefers task format clarification

**What happened:** User asked to clarify task with specific details before creating it  
**Why it matters:** Shows preference for upfront clarity over quick task creation  
**Suggested fix:** Update `Resources/Learnings/Working_Preferences.md` under "Task Management" section  
**Status:** pending
```

## Privacy Note

These files stay local in your vault. They're part of your personal knowledge system, not sent anywhere.

---

*This is part of Dex's compound learning system - every session makes the next one better.*
