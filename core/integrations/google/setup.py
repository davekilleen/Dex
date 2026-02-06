#!/usr/bin/env python3
"""
Google Workspace Integration Setup

Guides users through connecting Google Workspace (Gmail, Calendar, Contacts) to Dex.
Uses mcp-google package with OAuth flow.
"""

import json
import os
import webbrowser
from pathlib import Path
from typing import Optional, Tuple

PACKAGE = "mcp-google"
MCP_CONFIG_KEY = "google"

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
    """Check if Google MCP is already configured."""
    config = load_claude_config()
    return MCP_CONFIG_KEY in config.get("mcpServers", {})

def get_oauth_credentials_path() -> Path:
    """Get path for OAuth credentials."""
    return Path.home() / ".config" / "dex" / "google-oauth.json"

def get_setup_instructions() -> str:
    """Return setup instructions for the user."""
    return """
## Setting Up Google Workspace Integration

This connects Gmail, Calendar, and Contacts to Dex. Setup takes ~5 minutes.

### Step 1: Create a Google Cloud Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Click the project dropdown (top left) → **"New Project"**
3. Name it "Dex" → Click **Create**
4. Wait for project creation, then select it

### Step 2: Enable APIs

In your new project:
1. Go to **"APIs & Services"** → **"Library"**
2. Search and enable each of these:
   - **Gmail API**
   - **Google Calendar API**
   - **People API** (for Contacts)

### Step 3: Configure OAuth Consent Screen

1. Go to **"APIs & Services"** → **"OAuth consent screen"**
2. Choose **"External"** → Click **Create**
3. Fill in:
   - App name: "Dex"
   - User support email: (your email)
   - Developer contact: (your email)
4. Click **Save and Continue**
5. On Scopes page, click **"Add or Remove Scopes"**
6. Add these scopes:
   - `https://www.googleapis.com/auth/gmail.readonly`
   - `https://www.googleapis.com/auth/calendar.readonly`
   - `https://www.googleapis.com/auth/contacts.readonly`
7. Click **Save and Continue** through remaining steps

### Step 4: Create OAuth Credentials

1. Go to **"APIs & Services"** → **"Credentials"**
2. Click **"+ Create Credentials"** → **"OAuth client ID"**
3. Application type: **"Desktop app"**
4. Name: "Dex Desktop"
5. Click **Create**
6. Click **"Download JSON"** (saves as `client_secret_xxx.json`)

### Step 5: Provide Your Credentials

Either:
- **Paste the JSON content** from the downloaded file, OR
- **Tell me the path** to where you saved it

I'll handle the OAuth flow from there!

---

### Why This Setup?

Google requires OAuth for security. This is a one-time setup:
- Your credentials stay on your machine
- Only you can authorize access
- You can revoke access anytime at [myaccount.google.com/permissions](https://myaccount.google.com/permissions)
"""

def install(credentials_json: str, credentials_path: Optional[str] = None) -> Tuple[bool, str]:
    """Install Google MCP with the provided OAuth credentials."""
    
    oauth_path = get_oauth_credentials_path()
    oauth_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Handle both JSON content and file path
    if credentials_path:
        # Copy from provided path
        src = Path(credentials_path).expanduser()
        if not src.exists():
            return False, f"Credentials file not found: {credentials_path}"
        credentials_json = src.read_text()
    
    # Validate JSON
    try:
        creds = json.loads(credentials_json)
        if "installed" not in creds and "web" not in creds:
            return False, "Invalid credentials JSON. Expected OAuth client credentials from Google Cloud Console."
    except json.JSONDecodeError:
        return False, "Invalid JSON. Please paste the full contents of the downloaded credentials file."
    
    # Save credentials
    oauth_path.write_text(credentials_json)
    
    config = load_claude_config()
    
    # Add Google MCP configuration
    config.setdefault("mcpServers", {})[MCP_CONFIG_KEY] = {
        "command": "npx",
        "args": ["-y", PACKAGE],
        "env": {
            "GOOGLE_CLIENT_ID": creds.get("installed", creds.get("web", {})).get("client_id", ""),
            "GOOGLE_CLIENT_SECRET": creds.get("installed", creds.get("web", {})).get("client_secret", ""),
            "GOOGLE_REDIRECT_URI": "http://localhost:3000/oauth/callback"
        }
    }
    
    save_claude_config(config)
    
    # Save to Dex integrations config
    dex_config_path = Path(os.environ.get("DEX_VAULT", ".")) / "System" / "integrations" / "google.yaml"
    dex_config_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(dex_config_path, "w") as f:
        f.write(f"""# Google Workspace Integration Config
# Configured: {__import__('datetime').datetime.now().isoformat()}

enabled: true
package: {PACKAGE}
credentials_path: {oauth_path}

# Enabled services
services:
  gmail: true
  calendar: true
  contacts: true

# Integration hooks
hooks:
  meeting_prep: true      # Pull email threads with meeting attendees
  person_pages: true      # Show email history on person pages
  daily_plan: true        # Surface emails needing response

# Privacy settings
gmail:
  max_results: 50         # Max emails to fetch per query
  skip_labels:            # Labels to skip
    - SPAM
    - TRASH
    - CATEGORY_PROMOTIONS
""")
    
    return True, f"""
✅ **Google Workspace Integration Configured!**

**What's set up:**
- MCP Server: `{PACKAGE}`
- Services: Gmail, Calendar, Contacts
- Credentials: Saved to `{oauth_path}`

**Next Step: Authorize Access**

When you first use a Google feature, you'll see an OAuth prompt in your browser.
Click "Allow" to grant Dex read-only access to your Google data.

**What you can do after authorization:**
- "What emails am I behind on with [person]?" → Searches Gmail
- Meeting prep includes email thread context
- Person pages show email communication history
- Calendar events are enriched with attendee context

**Restart Claude Desktop** to activate the integration.

**Note:** You only authorize once. To revoke access later, visit:
[myaccount.google.com/permissions](https://myaccount.google.com/permissions)
"""

def uninstall() -> Tuple[bool, str]:
    """Remove Google MCP configuration."""
    config = load_claude_config()
    
    if MCP_CONFIG_KEY in config.get("mcpServers", {}):
        del config["mcpServers"][MCP_CONFIG_KEY]
        save_claude_config(config)
        
        # Also remove credentials
        oauth_path = get_oauth_credentials_path()
        if oauth_path.exists():
            oauth_path.unlink()
        
        return True, """Google integration removed. Restart Claude Desktop to apply.

To also revoke Google's authorization:
Visit [myaccount.google.com/permissions](https://myaccount.google.com/permissions)
and remove "Dex" from the list."""
    
    return False, "Google integration was not configured."

def test_connection() -> Tuple[bool, str]:
    """Test if Google connection is working."""
    if is_installed():
        return True, "Google MCP is configured. Restart Claude Desktop if you haven't already."
    return False, "Google MCP is not configured. Run /integrate-google to set up."
