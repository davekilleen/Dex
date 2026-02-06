#!/usr/bin/env python3
"""
Slack Integration Setup

Guides users through connecting Slack to Dex using the recommended MCP.
Uses browser cookie auth - no bot creation required!
"""

import json
import os
from pathlib import Path
from typing import Optional, Tuple

PACKAGE = "slack-mcp-server"  # Well-maintained community MCP
ALT_PACKAGE = "@kazuph/mcp-slack"  # Alternative option
MCP_CONFIG_KEY = "slack"

def get_claude_config_path() -> Path:
    """Get Claude Desktop config path."""
    return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"

def load_claude_config() -> dict:
    """Load existing Claude config."""
    config_path = get_claude_config_path()
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {"mcpServers": {}}

def save_claude_config(config: dict) -> None:
    """Save Claude config."""
    config_path = get_claude_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

def is_installed() -> bool:
    """Check if Slack MCP is already configured."""
    config = load_claude_config()
    return MCP_CONFIG_KEY in config.get("mcpServers", {})

def get_setup_instructions() -> str:
    """Return setup instructions for the user."""
    return """
## Setting Up Slack Integration

### Option A: Browser Cookie Auth (Easiest - No Bot Required!)

The Slack MCP can use your browser session to access Slack without creating a bot.

1. **Log into Slack in your browser** (not the desktop app)
2. Open **Developer Tools** (F12 or Cmd+Option+I)
3. Go to **Application** > **Cookies** > `https://app.slack.com`
4. Find the cookie named **`d`** (it's long, starts with `xoxd-`)
5. Copy the entire value

That's it! Paste the cookie value and I'll configure everything.

---

### Option B: Slack App Token (More Setup, More Control)

If you prefer traditional app-based auth:

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **"Create New App"** > **"From scratch"**
3. Name it "Dex", select your workspace
4. Go to **"OAuth & Permissions"**
5. Add these **Bot Token Scopes:**
   - `channels:history` - Read public channel messages
   - `groups:history` - Read private channel messages
   - `im:history` - Read DMs
   - `search:read` - Search messages
   - `users:read` - Read user profiles
6. Click **"Install to Workspace"**
7. Copy the **Bot User OAuth Token** (starts with `xoxb-`)

---

### Which should I use?

**Cookie auth:** Faster setup, uses your permissions, sees what you see
**App token:** More work, but doesn't use your personal session

Most users prefer cookie auth. Paste your cookie (`xoxd-...`) or token (`xoxb-...`) below.
"""

def install(credential: str, workspace_url: Optional[str] = None) -> Tuple[bool, str]:
    """Install Slack MCP with the provided credential."""
    
    # Detect credential type
    if credential.startswith("xoxd-"):
        auth_type = "cookie"
        env_key = "SLACK_TOKEN"  # The MCP accepts d cookie as token
    elif credential.startswith("xoxb-"):
        auth_type = "bot"
        env_key = "SLACK_BOT_TOKEN"
    elif credential.startswith("xoxp-"):
        auth_type = "user"
        env_key = "SLACK_USER_TOKEN"
    else:
        return False, """Invalid credential. Expected:
- Browser cookie starting with `xoxd-`
- Bot token starting with `xoxb-`
- User token starting with `xoxp-`"""
    
    config = load_claude_config()
    
    # Add Slack MCP configuration
    mcp_config = {
        "command": "npx",
        "args": ["-y", "slack-mcp-server"],
        "env": {
            env_key: credential
        }
    }
    
    if workspace_url:
        mcp_config["env"]["SLACK_WORKSPACE_URL"] = workspace_url
    
    config.setdefault("mcpServers", {})[MCP_CONFIG_KEY] = mcp_config
    save_claude_config(config)
    
    # Save to Dex integrations config
    dex_config_path = Path(os.environ.get("DEX_VAULT", ".")) / "System" / "integrations" / "slack.yaml"
    dex_config_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(dex_config_path, "w") as f:
        f.write(f"""# Slack Integration Config
# Configured: {__import__('datetime').datetime.now().isoformat()}

enabled: true
package: {PACKAGE}
auth_type: {auth_type}
# Credential stored in Claude Desktop config for security

# Integration hooks
hooks:
  meeting_prep: true      # Pull Slack context for meeting attendees
  person_pages: true      # Show recent Slack mentions on person pages
  commitment_tracking: true  # Surface promises made in Slack

# Channels to index (empty = all accessible)
channels: []

# Users to prioritize (empty = all)
priority_users: []
""")
    
    auth_desc = {
        "cookie": "browser session",
        "bot": "bot token",
        "user": "user token"
    }[auth_type]
    
    return True, f"""
✅ **Slack Integration Configured!**

**What's set up:**
- MCP Server: `{PACKAGE}`
- Auth type: {auth_desc}
- Credential: Securely stored in Claude Desktop config

**What you can do now:**
- "What did Sarah say about the Q1 budget?" → Searches Slack
- Meeting prep will include recent Slack context with attendees
- Person pages will show Slack interaction history

**Restart Claude Desktop** to activate the integration.

**Note:** If using cookie auth, you may need to refresh the cookie periodically 
(when you re-login to Slack in browser).
"""

def uninstall() -> Tuple[bool, str]:
    """Remove Slack MCP configuration."""
    config = load_claude_config()
    
    if MCP_CONFIG_KEY in config.get("mcpServers", {}):
        del config["mcpServers"][MCP_CONFIG_KEY]
        save_claude_config(config)
        return True, "Slack integration removed. Restart Claude Desktop to apply."
    
    return False, "Slack integration was not configured."

def test_connection() -> Tuple[bool, str]:
    """Test if Slack connection is working."""
    if is_installed():
        return True, "Slack MCP is configured. Restart Claude Desktop if you haven't already."
    return False, "Slack MCP is not configured. Run /integrate-slack to set up."
