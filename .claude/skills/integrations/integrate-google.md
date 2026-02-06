# /integrate-google - Connect Google Workspace to Dex

## Purpose
Guide users through setting up Google Workspace integration (Gmail, Calendar, Contacts) with Dex using OAuth.

## When to Use
- User says "connect google", "set up gmail", "integrate google workspace"
- During onboarding when user indicates they use Google Workspace
- When user asks about emails, calendar events, or contacts

## Prerequisites
- Google account
- Ability to create a Google Cloud project (free)
- ~5 minutes for one-time OAuth setup

## Flow

### Step 1: Check Existing Setup
```python
from core.integrations.detect import detect_integration, load_claude_config
from core.integrations.google.setup import is_installed, get_setup_instructions, install

status = detect_integration("google", load_claude_config() or {})

if status["installed"]:
    if status["is_dex_recommended"]:
        print("✅ Google Workspace is already set up!")
    else:
        print(f"⚠️ You have Google configured using: {status['package']}")
        print(f"Recommendation: {status['recommendation']}")
```

### Step 2: Show Instructions (if needed)
```python
print(get_setup_instructions())
```

Walk through:
1. Create Google Cloud project
2. Enable APIs (Gmail, Calendar, People)
3. Configure OAuth consent screen
4. Create OAuth credentials
5. Download credentials JSON

**This is the most complex setup** - be patient and offer to clarify any step.

### Step 3: Collect Credentials
Ask user for their OAuth credentials JSON. Accept either:
- Pasted JSON content
- File path to downloaded JSON

### Step 4: Install
```python
success, message = install(credentials_json)
print(message)
```

### Step 5: OAuth Authorization
Explain that first use will trigger browser OAuth flow:
- User will see Google login
- They'll authorize read-only access
- Access token is cached locally

### Step 6: Confirm and Explain
- Remind to restart Claude Desktop
- Explain what's now possible
- Note how to revoke access if needed

## Key Messages

**Success:**
> ✅ Google Workspace configured!
>
> **What's connected:**
> - 📧 Gmail (read-only)
> - 📅 Calendar (read-only)
> - 👥 Contacts (read-only)
>
> **Next step:** When you first use a Google feature, you'll see an OAuth prompt. Click "Allow" to authorize.
>
> **What you can do after authorization:**
> - "What emails am I behind on with [person]?"
> - "Show my calendar for next week"
> - "What's [person]'s email address?"
>
> **Restart Claude Desktop** to activate.

**Already Configured:**
> Google Workspace is already connected. Want me to:
> 1. **Test the connection**
> 2. **Reconfigure with new credentials**
> 3. **Check which services are enabled**

## Error Handling

| Error | Response |
|-------|----------|
| Invalid JSON | "That doesn't look like valid credentials JSON. Please paste the full contents of the file downloaded from Google Cloud Console." |
| Missing APIs | "Make sure you've enabled the Gmail API, Calendar API, and People API in your Google Cloud project." |
| OAuth failed | "The OAuth flow failed. Try these steps: 1) Make sure you're logged into the correct Google account, 2) Check that your OAuth consent screen is configured, 3) Try creating new credentials." |

## Simplified Alternative

For users intimidated by Google Cloud setup, offer:

> **Finding Google Cloud setup complex?** 
>
> Here are your options:
> 1. **Skip for now** - You can add Google later with `/integrate-google`
> 2. **Follow along** - I'll guide you step by step (takes ~5 min)
> 3. **Watch a video** - [link to setup walkthrough if available]
>
> Many users skip Google and just use Notion + Slack. You can always add it later!

## Analytics Event
```python
fire_event('integration_google_completed', {
    'services': ['gmail', 'calendar', 'contacts'],
    'was_upgrade': status.get("installed", False)
})
```

## Related Skills
- `/integrate-notion` - Connect Notion
- `/integrate-slack` - Connect Slack
- `/meeting-prep` - Uses Google context when available
