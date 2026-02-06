# /integrate-slack - Connect Slack to Dex

## Purpose
Guide users through setting up Slack integration with Dex. Supports easy cookie auth (no bot required) or traditional bot token auth.

## When to Use
- User says "connect slack", "set up slack", "integrate slack"
- During onboarding when user indicates they use Slack
- When user asks to search Slack or access Slack messages

## Prerequisites
- Slack account
- Browser access to Slack (for cookie auth) OR workspace admin access (for bot auth)

## Flow

### Step 1: Check Existing Setup
```python
from core.integrations.detect import detect_integration, load_claude_config
from core.integrations.slack.setup import is_installed, get_setup_instructions, install

status = detect_integration("slack", load_claude_config() or {})

if status["installed"]:
    if status["is_dex_recommended"]:
        print("✅ Slack is already set up with the recommended package!")
    else:
        print(f"⚠️ You have Slack configured using: {status['package']}")
        print(f"Recommendation: {status['recommendation']}")
```

### Step 2: Show Instructions (if needed)
```python
print(get_setup_instructions())
```

Present both options:
- **Cookie auth** (recommended for most users) - No setup required, uses browser session
- **Bot token auth** - More control, requires creating Slack app

### Step 3: Collect Credential
Ask user for their credential:
- `xoxd-...` = Browser cookie (from developer tools)
- `xoxb-...` = Bot token (from Slack app)
- `xoxp-...` = User token (from Slack app)

### Step 4: Install
```python
success, message = install(credential)
print(message)
```

### Step 5: Confirm and Explain
- Remind to restart Claude Desktop
- Explain cookie refresh if using cookie auth
- Show what they can now do

## Key Messages

**Success (Cookie Auth):**
> ✅ Slack connected using your browser session!
> 
> You can now:
> - Search Slack: "What did Sarah say about the Q1 budget?"
> - Get meeting context: "Show me recent Slack with [person]"
> - Track commitments: "What did I promise in Slack this week?"
>
> **Restart Claude Desktop** to activate.
>
> **Note:** You may need to refresh the cookie when you re-login to Slack in your browser.

**Success (Bot Token):**
> ✅ Slack connected using bot token!
> 
> Your Slack app has been configured. You can now search messages and get meeting context.
>
> **Restart Claude Desktop** to activate.

**Already Configured:**
> Slack is already connected. Want me to:
> 1. **Test the connection**
> 2. **Reconfigure with new credentials**
> 3. **Switch auth method** (cookie ↔ bot)

## Error Handling

| Error | Response |
|-------|----------|
| Invalid credential | "That doesn't look like a Slack credential. Expected: `xoxd-` (cookie), `xoxb-` (bot), or `xoxp-` (user token)" |
| Cookie expired | "Your Slack cookie may have expired. Log into Slack in your browser and grab a fresh cookie." |
| Insufficient permissions | "Your bot token may not have the required scopes. Ensure it has: channels:history, groups:history, im:history, search:read" |

## Cookie Auth Quick Reference

For users who need help finding their cookie:

```
1. Open slack.com in Chrome/Firefox/Safari
2. Log into your workspace
3. Open Developer Tools (F12 or Cmd+Option+I)
4. Go to Application → Cookies → https://app.slack.com
5. Find the cookie named "d"
6. Copy the entire value (starts with xoxd-)
```

## Analytics Event
```python
fire_event('integration_slack_completed', {
    'auth_type': 'cookie' | 'bot' | 'user',
    'was_upgrade': status.get("installed", False)
})
```

## Related Skills
- `/integrate-notion` - Connect Notion
- `/integrate-google` - Connect Google Workspace
- `/meeting-prep` - Uses Slack context when available
