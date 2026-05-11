# Gmail Reader for Dex — Design Plan

> **Companion script:** [`gmail_client.py`](./gmail_client.py) provides the modify-scope (read + write) version — label management, archive, mark read/unread. Same OAuth project, separate token storage, same CLI style.

## Purpose

Read-only, multi-account Gmail access for Dex. Enables per-attendee email intelligence in daily plans without trusting third-party MCP servers.

## Design Principles

1. **Read-only** — `gmail.readonly` scope only. Cannot send, modify, or delete.
2. **Zero trust in third parties** — Uses only Google's official Python libraries.
3. **User controls their credentials** — OAuth via user's own Google Cloud project.
4. **Not user-specific** — Generic enough for any Dex user. Contributable to upstream.
5. **Follows existing patterns** — Same CLI style as `reminders_eventkit.py`.

## File Location

```
core/mcp/scripts/gmail_reader.py    # The script
core/mcp/scripts/gmail_reader.md    # This file (design plan + setup guide)
```

## CLI Interface

```bash
# Setup
python3 gmail_reader.py authenticate <email>
python3 gmail_reader.py list_accounts
python3 gmail_reader.py remove_account <email>

# Reading
python3 gmail_reader.py search <email> "<gmail query>" [--max-results 10]
python3 gmail_reader.py get_thread <email> <thread_id>
python3 gmail_reader.py get_message <email> <message_id>
```

All output is JSON (consistent with reminders_eventkit.py).

## OAuth Credentials

Passed via environment variables:
```
GMAIL_CLIENT_ID      — from Google Cloud Console
GMAIL_CLIENT_SECRET  — from Google Cloud Console
```

Never hardcoded. User creates their own Google Cloud project and Desktop OAuth credentials.

## Token Storage

Tokens stored in `~/.config/dex/gmail/` directory:
- `accounts.json` — list of authenticated email addresses
- `token_<email_hash>.json` — per-account OAuth token

**Security measures:**
- Directory created with `0700` permissions
- Token files created with `0600` permissions
- SHA-256 hash of email for filenames (no email in filename)
- Tokens auto-refresh on expiry
- `remove_account` deletes token file

**Why not Keychain:** Cross-platform compatibility. Keychain is macOS-only. The `keyring` Python package adds a dependency and has reliability issues. File-based with strict permissions is what `gcloud` CLI, `gh` CLI, and Google's own auth libraries use.

## Dependencies

```
google-auth
google-auth-oauthlib
google-api-python-client
```

All official Google packages. No third-party MCP frameworks.

## Scope — What It Can Do

| Command | What it does |
|---------|-------------|
| `search` | Search threads by Gmail query syntax (from:, to:, subject:, newer_than:, etc.) |
| `get_thread` | Get full thread with all messages, snippets, headers |
| `get_message` | Get a single message with full body |

## Scope — What It Cannot Do

- Send email
- Modify email (labels, read status, archive)
- Delete email
- Access drafts
- Access contacts

This is intentional. Read-only means read-only.

## Dex Integration

The daily-plan skill's Step 5.3 (Meeting Intelligence) calls:

```bash
python3 core/mcp/scripts/gmail_reader.py search "you@example.com" "from:attendee@example.com OR to:attendee@example.com newer_than:14d" --max-results 5
```

Falls back gracefully if:
- Script not installed (skip silently)
- Account not authenticated (skip with note)
- No threads found (skip)
- Environment variables missing (skip with setup hint)

## Setup Flow

1. Create Google Cloud project at [console.cloud.google.com](https://console.cloud.google.com/)
2. Enable Gmail API (APIs & Services > Library > search "Gmail API" > Enable)
3. Configure OAuth consent screen:
   - Choose **External** as user type
   - App name: anything (e.g., "Dex Gmail Reader")
   - Add all email addresses as **test users**
   - Leave app in **Testing mode** (do not publish)
4. Create OAuth credentials:
   - APIs & Services > Credentials > Create Credentials > OAuth client ID
   - Application type: **Desktop app**
   - Copy Client ID and Client Secret
5. Set environment variables:
   ```bash
   export GMAIL_CLIENT_ID="your-client-id"
   export GMAIL_CLIENT_SECRET="your-client-secret"
   ```
6. Authenticate each account:
   ```bash
   python3 core/mcp/scripts/gmail_reader.py authenticate your@email.com
   python3 core/mcp/scripts/gmail_reader.py authenticate your@workspace.com
   ```
7. Verify: `python3 core/mcp/scripts/gmail_reader.py list_accounts`

### Google Workspace Accounts

Testing mode OAuth apps allow up to 100 test users without admin approval. This works for most Workspace accounts.

**If authentication fails with "Access blocked":** The Workspace admin has restricted third-party app access. Send them this:

> **Subject: Quick approval needed — Gmail read-only API access for my account**
>
> I'm setting up a local read-only tool that searches my Gmail through a script on my machine. It uses Google's standard OAuth2 with `gmail.readonly` scope — it cannot send, modify, or delete anything. No data leaves my machine.
>
> Could you add this OAuth Client ID to the allowed apps list?
> Client ID: `[paste your Client ID]`
> Scope: `gmail.readonly`
>
> Admin path: admin.google.com > Security > Access and data control > API controls > App access control

## Estimated Build Time

- Script: ~150 lines of Python
- Setup guide: included in this file
- Skill integration: small edit to daily-plan SKILL.md
- Total: ~1 hour
