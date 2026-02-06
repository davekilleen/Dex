#!/usr/bin/env python3
"""
Notion Integration Setup

Guides users through connecting Notion to Dex using the official MCP.
"""

import json
import os
from pathlib import Path
from typing import Optional, Tuple

PACKAGE = "@notionhq/notion-mcp-server"
MCP_CONFIG_KEY = "notion"

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
    """Check if Notion MCP is already configured."""
    config = load_claude_config()
    return MCP_CONFIG_KEY in config.get("mcpServers", {})

def get_setup_instructions() -> str:
    """Return setup instructions for the user."""
    return """
## Setting Up Notion Integration

### Step 1: Create a Notion Integration

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click **"+ New integration"**
3. Name it "Dex" (or whatever you like)
4. Select your workspace
5. Click **Submit**

### Step 2: Copy Your Integration Token

After creating the integration:
1. You'll see an **"Internal Integration Secret"** (starts with `ntn_`)
2. Click **"Copy"** to copy it

### Step 3: Share Pages with Your Integration

**Important:** Notion integrations can only access pages explicitly shared with them.

1. Open any Notion page you want Dex to access
2. Click **"Share"** in the top right
3. Click **"Invite"**
4. Search for your integration name ("Dex")
5. Click **"Invite"**

Repeat for all pages/databases you want Dex to access.

### Step 4: Paste Your Token

Once you have your token, paste it here and I'll configure everything.
"""

def install(token: str) -> Tuple[bool, str]:
    """Install Notion MCP with the provided token."""
    if not token or not token.startswith(("ntn_", "secret_")):
        return False, "Invalid token. Notion tokens start with 'ntn_' or 'secret_'"
    
    config = load_claude_config()
    
    # Add Notion MCP configuration
    config.setdefault("mcpServers", {})[MCP_CONFIG_KEY] = {
        "command": "npx",
        "args": ["-y", PACKAGE],
        "env": {
            "NOTION_API_KEY": token
        }
    }
    
    save_claude_config(config)
    
    # Save to Dex integrations config
    dex_config_path = Path(os.environ.get("DEX_VAULT", ".")) / "System" / "integrations" / "notion.yaml"
    dex_config_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(dex_config_path, "w") as f:
        f.write(f"""# Notion Integration Config
# Configured: {__import__('datetime').datetime.now().isoformat()}

enabled: true
package: {PACKAGE}
# Token stored in Claude Desktop config for security

# Pages shared with integration (update as you add more)
shared_pages: []

# Integration hooks
hooks:
  meeting_prep: true      # Pull Notion docs for meeting attendees
  person_pages: true      # Link Notion pages to person pages
  project_pages: true     # Link Notion docs to projects
""")
    
    return True, f"""
✅ **Notion Integration Configured!**

**What's set up:**
- MCP Server: `{PACKAGE}`
- Token: Securely stored in Claude Desktop config

**What you can do now:**
- Ask me to search your Notion workspace
- I'll automatically pull relevant Notion docs during meeting prep
- Person and project pages will show linked Notion content

**Remember:** I can only access pages you've shared with the integration.

**Restart Claude Desktop** to activate the integration.
"""

def uninstall() -> Tuple[bool, str]:
    """Remove Notion MCP configuration."""
    config = load_claude_config()
    
    if MCP_CONFIG_KEY in config.get("mcpServers", {}):
        del config["mcpServers"][MCP_CONFIG_KEY]
        save_claude_config(config)
        return True, "Notion integration removed. Restart Claude Desktop to apply."
    
    return False, "Notion integration was not configured."

def test_connection() -> Tuple[bool, str]:
    """Test if Notion connection is working."""
    # This would require actually running the MCP - for now, just check config
    if is_installed():
        return True, "Notion MCP is configured. Restart Claude Desktop if you haven't already."
    return False, "Notion MCP is not configured. Run /integrate-notion to set up."
