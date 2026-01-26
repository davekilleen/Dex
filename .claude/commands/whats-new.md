# What's New in Claude Code

Check for new Claude Code capabilities and learn how they could improve your Dex system.

## Usage

```
/whats-new              # Check for updates
/whats-new --full       # Include capability deep-dives
```

## Arguments

$MODE: Optional. `--full` for detailed explanations of each feature.

---

## Process

### Step 1: Read Current State

Load `Resources/Claude_Code_Docs/capability-state.json`:

```json
{
  "last_check": "2026-01-15",
  "last_changelog_version": "1.0.28",
  "capabilities_seen": ["hooks", "sub-agents", "skills", "commands", "mcp"],
  "features_noted": [...]
}
```

If file missing or `last_check` is null, treat as first run.

### Step 2: Fetch Current Changelog

Search the web for the latest Claude Code changelog/release notes:
- Primary: Anthropic's official documentation
- Secondary: GitHub releases, blog posts

Focus on:
- New features and capabilities
- Breaking changes
- Deprecations
- Performance improvements

### Step 3: Compare and Surface Changes

Identify what's new since `last_check`:

**For each new feature:**
1. What it does (plain English, 1-2 sentences)
2. Why it matters for PKM users
3. How you could use it in Dex (concrete example)
4. Effort to adopt (Low/Medium/High)

### Step 4: Present Findings

**If updates found:**

```
📢 Claude Code Updates

Last checked: [date] (X days ago)
Current version: [version]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🆕 NEW FEATURES

1. [Feature Name]
   What: [Plain English description]
   For you: [How this could improve Dex]
   Effort: Low

2. [Feature Name]
   What: [Description]
   For you: [Specific improvement idea]
   Effort: Medium

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 SUGGESTED IMPROVEMENTS

Based on what's new, here are concrete things you could add to Dex:

1. [Improvement name]
   Uses: [Which new feature]
   What it does: [Specific description]
   Pillar: [Which pillar it supports]

Want me to implement any of these? (Enter number)
Or run `/dex-improve` to workshop custom ideas.
```

**If no updates:**

```
✅ You're up to date!

Last checked: Today
Claude Code version: [version]

No new features since your last check.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 DID YOU KNOW?

[Pick one underutilized feature from capability-state and explain it]

Example: "Hooks can automatically load context at session start. 
You're not using any hooks yet — want me to set one up?"
```

### Step 5: Update State

After presenting findings, update `Resources/Claude_Code_Docs/capability-state.json`:

```json
{
  "last_check": "2026-01-23",
  "last_changelog_version": "1.0.32",
  "capabilities_seen": [...updated list...],
  "features_noted": [
    ...existing...,
    {
      "version": "1.0.32",
      "feature": "Parallel sub-agents",
      "date_seen": "2026-01-23",
      "relevance": "high"
    }
  ]
}
```

---

## Full Mode (--full)

When `--full` is provided, include educational deep-dives:

For each feature, add:

```
📚 DEEP DIVE: [Feature Name]

**What it is:**
[2-3 paragraph explanation of the capability]

**How it works:**
[Technical explanation with examples]

**Real-world example:**
[Concrete scenario showing the feature in action]

**In Dex, you could:**
- [Specific application 1]
- [Specific application 2]

**To implement:**
1. [Step 1]
2. [Step 2]
3. [Step 3]
```

---

## Feature Categories

When evaluating relevance, categorize features:

| Category | Relevance to Dex | Examples |
|----------|------------------|----------|
| **Automation** | High | Hooks, triggers, scheduled tasks |
| **Performance** | Medium | Faster models, caching |
| **Context** | High | Memory, skills, knowledge bases |
| **Integration** | High | MCP improvements, new protocols |
| **UI/UX** | Low | IDE features, visual changes |
| **Developer** | Low | API changes, SDK updates |

Focus on High relevance categories. Mention Medium. Skip Low unless asked.

---

## Capability Reference

Current Claude Code features to track:

| Feature | What It Does | Dex Potential |
|---------|--------------|---------------|
| **Commands** | User-triggered workflows | `/plan`, `/review`, etc. |
| **Skills** | Reusable behaviors, always loaded | Person lookup, writing style |
| **Hooks** | Auto-triggers at events | Session start, file changes |
| **Sub-agents** | Parallel workers, isolated context | Research, analysis |
| **MCP** | External service connections | Calendar, tasks, email |
| **Memory** | Cross-session persistence | Preferences, learnings |
| **Tools** | Built-in capabilities | File ops, search, terminal |

---

## Example Output

```
📢 Claude Code Updates

Last checked: 2026-01-15 (8 days ago)
Current version: 1.0.32

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🆕 NEW FEATURES

1. Async Hooks
   What: Hooks can now run without blocking the main conversation
   For you: Faster session starts — load context in background
   Effort: Low

2. Sub-agent Communication
   What: Sub-agents can now pass data back to parent
   For you: Research agent could update your notes directly
   Effort: Medium

3. MCP Resource Subscriptions
   What: MCP servers can push updates, not just respond to queries
   For you: Get notified when calendar changes, tasks update
   Effort: High (requires MCP server changes)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 SUGGESTED IMPROVEMENTS

1. Background Context Loading
   Uses: Async Hooks
   What: Load your learnings and today's plan while you type
   Pillar: Productivity

2. Auto-Research on New Topics
   Uses: Sub-agent Communication
   What: When you mention a new company, auto-research in background
   Pillar: Deal Support

Want me to implement any of these? (Enter 1 or 2)
```

---

## Error Handling

**If web search fails:**
> "Couldn't fetch the latest changelog. Here's what I know was current as of [last_check]:
> [List known capabilities]
> 
> Try again later, or check manually at docs.anthropic.com"

**If state file is corrupted:**
> "Your capability state file has an issue. I'll create a fresh one and do a full scan."

Then proceed with first-run behavior.

---

## Behaviors

### Always Do
- Keep explanations in plain English, not developer jargon
- Tie every feature back to concrete Dex improvements
- Update the state file after every check
- Offer to implement suggestions

### Never Do
- List features without explaining relevance
- Skip the state update
- Overwhelm with every minor change (focus on impactful features)
- Assume user knows Claude Code internals

---

## Related Commands

- `/dex-improve` — Full design partner (includes this + workshopping + audit)
- `/create-mcp` — Build new integrations when new MCP features enable them
