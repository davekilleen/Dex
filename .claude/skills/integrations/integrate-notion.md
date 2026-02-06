# /integrate-notion - Connect Notion to Dex

## Purpose
Guide users through setting up Notion integration with Dex using the official Notion MCP.

## When to Use
- User says "connect notion", "set up notion", "integrate notion"
- During onboarding when user indicates they use Notion
- When user asks to search Notion or access Notion docs

## Prerequisites
- Notion account
- Admin access to create integrations (or ask workspace admin)

## Flow

### Step 1: Check Existing Setup
```python
from core.integrations.detect import detect_integration, load_claude_config
from core.integrations.notion.setup import is_installed, get_setup_instructions, install

status = detect_integration("notion", load_claude_config() or {})

if status["installed"]:
    if status["is_dex_recommended"]:
        print("✅ Notion is already set up with the recommended package!")
        # Offer to test or reconfigure
    else:
        print(f"⚠️ You have Notion configured, but using: {status['package']}")
        print(f"Recommendation: {status['recommendation']}")
        # Offer to upgrade or keep existing
```

### Step 2: Show Instructions (if needed)
```python
print(get_setup_instructions())
```

Display the instructions and wait for user to:
1. Create integration at notion.so/my-integrations
2. Copy the integration token
3. Share pages with the integration

### Step 3: Collect Token
Ask user to paste their Notion integration token.
- Should start with `ntn_` or `secret_`
- Validate format before proceeding

### Step 4: Install
```python
success, message = install(token)
print(message)
```

### Step 5: Confirm and Explain Next Steps
- Remind user to restart Claude Desktop
- Explain what they can now do
- Offer to test the connection

## Key Messages

**Success:**
> ✅ Notion connected! You can now:
> - Search your Notion workspace: "Find my Q1 planning doc"
> - Get context during meetings: "What Notion pages does [person] have?"
> - Link Notion docs to projects and people pages
>
> **Restart Claude Desktop** to activate.

**Already Configured (Dex Package):**
> ✅ Notion is already set up and using the recommended package.
> Want me to test the connection or reconfigure?

**Already Configured (Other Package):**
> You have Notion configured using `{package}`.
> 
> Dex recommends `@notionhq/notion-mcp-server` (official from Notion).
> Benefits: Best maintained, full API coverage, official support.
>
> Would you like to:
> 1. **Keep your current setup** - It's working, stick with it
> 2. **Switch to Dex recommended** - I'll migrate your config
> 3. **Learn more** - Compare the two options

## Error Handling

| Error | Response |
|-------|----------|
| Invalid token format | "That doesn't look like a Notion token. It should start with `ntn_` or `secret_`. Did you copy the full token?" |
| Missing pages access | "Make sure you've shared pages with your integration. Notion integrations can only see pages explicitly shared with them." |
| Config write error | "I couldn't update Claude Desktop config. Check file permissions at `~/Library/Application Support/Claude/`" |

## Analytics Event
```python
fire_event('integration_notion_completed', {
    'was_upgrade': status.get("installed", False),
    'previous_package': status.get("package") if status.get("installed") else None
})
```

## Related Skills
- `/integrate-slack` - Connect Slack
- `/integrate-google` - Connect Google Workspace
- `/meeting-prep` - Uses Notion context when available
