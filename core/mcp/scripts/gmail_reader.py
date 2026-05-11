#!/usr/bin/env python3
"""
Gmail Reader for Dex — Read-only multi-account Gmail access.

Security-first design:
- gmail.readonly scope ONLY — cannot send, modify, or delete
- Tokens stored with 0600 permissions in ~/.config/dex/gmail/
- OAuth credentials via environment variables, never hardcoded
- Uses only Google's official Python libraries
- All output as JSON for programmatic consumption

Usage:
    gmail_reader.py authenticate <email>
    gmail_reader.py list_accounts
    gmail_reader.py remove_account <email>
    gmail_reader.py search <email> "<query>" [--max-results 10]
    gmail_reader.py get_thread <email> <thread_id>
    gmail_reader.py get_message <email> <message_id>

Environment:
    GMAIL_CLIENT_ID     — OAuth 2.0 Client ID (from Google Cloud Console)
    GMAIL_CLIENT_SECRET — OAuth 2.0 Client Secret

See gmail_reader.md for full setup guide.
"""

import argparse
import base64
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
CONFIG_DIR = Path.home() / ".config" / "dex" / "gmail"
ACCOUNTS_FILE = CONFIG_DIR / "accounts.json"


def ensure_config_dir():
    """Create config directory with secure permissions."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, stat.S_IRWXU)  # 0700


def token_path(email: str) -> Path:
    """Get token file path for an email (hashed filename)."""
    email_hash = hashlib.sha256(email.lower().encode()).hexdigest()[:16]
    return CONFIG_DIR / f"token_{email_hash}.json"


def load_accounts() -> list:
    """Load list of authenticated email addresses."""
    if not ACCOUNTS_FILE.exists():
        return []
    return json.loads(ACCOUNTS_FILE.read_text())


def save_accounts(accounts: list):
    """Save account list with secure permissions."""
    ensure_config_dir()
    ACCOUNTS_FILE.write_text(json.dumps(accounts, indent=2))
    os.chmod(ACCOUNTS_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 0600


def get_client_config() -> dict:
    """Build OAuth client config from environment variables."""
    client_id = os.environ.get("GMAIL_CLIENT_ID")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET")

    if not client_id or not client_secret:
        print(
            json.dumps(
                {
                    "error": "Missing environment variables",
                    "detail": "Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET. See gmail_reader.md for setup.",
                }
            )
        )
        sys.exit(1)

    return {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def get_credentials(email: str):
    """Load and refresh OAuth credentials for an account."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    path = token_path(email)
    if not path.exists():
        print(
            json.dumps(
                {
                    "error": f"Account not authenticated: {email}",
                    "detail": f"Run: python3 gmail_reader.py authenticate {email}",
                }
            )
        )
        sys.exit(1)

    creds = Credentials.from_authorized_user_file(str(path), SCOPES)

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_token(email, creds)

    return creds


def save_token(email: str, creds):
    """Save OAuth token with secure permissions."""
    ensure_config_dir()
    path = token_path(email)
    path.write_text(creds.to_json())
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600


def build_service(email: str):
    """Build Gmail API service for an account."""
    from googleapiclient.discovery import build

    creds = get_credentials(email)
    return build("gmail", "v1", credentials=creds)


# --- Commands ---


def cmd_authenticate(email: str):
    """Run OAuth flow for an email account."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_config = get_client_config()
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    creds = flow.run_local_server(port=0, login_hint=email)

    save_token(email, creds)

    accounts = load_accounts()
    if email.lower() not in [a.lower() for a in accounts]:
        accounts.append(email)
        save_accounts(accounts)

    print(
        json.dumps(
            {
                "success": True,
                "email": email,
                "status": "authenticated",
                "scope": "gmail.readonly",
                "token_path": str(token_path(email)),
            }
        )
    )


def cmd_list_accounts():
    """List all authenticated accounts."""
    accounts = load_accounts()
    valid = []
    for email in accounts:
        path = token_path(email)
        valid.append({"email": email, "token_exists": path.exists()})
    print(json.dumps({"accounts": valid}, indent=2))


def cmd_remove_account(email: str):
    """Remove an authenticated account and delete its token."""
    path = token_path(email)
    if path.exists():
        path.unlink()

    accounts = load_accounts()
    accounts = [a for a in accounts if a.lower() != email.lower()]
    save_accounts(accounts)

    print(json.dumps({"success": True, "email": email, "status": "removed"}))


def cmd_search(email: str, query: str, max_results: int = 10):
    """Search Gmail threads matching a query."""
    service = build_service(email)

    results = (
        service.users()
        .threads()
        .list(userId="me", q=query, maxResults=max_results)
        .execute()
    )

    threads = results.get("threads", [])
    if not threads:
        print(json.dumps({"email": email, "query": query, "threads": []}))
        return

    output = []
    for thread_stub in threads:
        thread = (
            service.users()
            .threads()
            .get(userId="me", id=thread_stub["id"], format="metadata",
                 metadataHeaders=["Subject", "From", "To", "Date"])
            .execute()
        )

        messages = []
        for msg in thread.get("messages", []):
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            messages.append(
                {
                    "id": msg["id"],
                    "date": headers.get("Date", ""),
                    "from": headers.get("From", ""),
                    "to": headers.get("To", ""),
                    "subject": headers.get("Subject", ""),
                    "snippet": msg.get("snippet", ""),
                }
            )

        output.append(
            {
                "thread_id": thread["id"],
                "message_count": len(messages),
                "messages": messages,
            }
        )

    print(json.dumps({"email": email, "query": query, "threads": output}, indent=2))


def cmd_get_thread(email: str, thread_id: str):
    """Get a full thread with message bodies."""
    service = build_service(email)

    thread = (
        service.users()
        .threads()
        .get(userId="me", id=thread_id, format="full")
        .execute()
    )

    messages = []
    for msg in thread.get("messages", []):
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        body = extract_body(msg.get("payload", {}))
        messages.append(
            {
                "id": msg["id"],
                "date": headers.get("Date", ""),
                "from": headers.get("From", ""),
                "to": headers.get("To", ""),
                "subject": headers.get("Subject", ""),
                "snippet": msg.get("snippet", ""),
                "body": body,
            }
        )

    print(json.dumps({"thread_id": thread_id, "messages": messages}, indent=2))


def cmd_get_message(email: str, message_id: str):
    """Get a single message with full body."""
    service = build_service(email)

    msg = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )

    headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
    body = extract_body(msg.get("payload", {}))

    print(
        json.dumps(
            {
                "id": msg["id"],
                "thread_id": msg.get("threadId", ""),
                "date": headers.get("Date", ""),
                "from": headers.get("From", ""),
                "to": headers.get("To", ""),
                "subject": headers.get("Subject", ""),
                "snippet": msg.get("snippet", ""),
                "body": body,
            },
            indent=2,
        )
    )


def extract_body(payload: dict) -> str:
    """Extract plain text body from a Gmail message payload."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain" and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
        if part.get("parts"):
            result = extract_body(part)
            if result:
                return result

    return ""


# --- CLI ---


def main():
    parser = argparse.ArgumentParser(
        description="Gmail Reader for Dex — read-only multi-account Gmail access"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # authenticate
    p_auth = subparsers.add_parser("authenticate", help="Authenticate a Gmail account")
    p_auth.add_argument("email", help="Email address to authenticate")

    # list_accounts
    subparsers.add_parser("list_accounts", help="List authenticated accounts")

    # remove_account
    p_rm = subparsers.add_parser("remove_account", help="Remove an authenticated account")
    p_rm.add_argument("email", help="Email address to remove")

    # search
    p_search = subparsers.add_parser("search", help="Search Gmail threads")
    p_search.add_argument("email", help="Account to search")
    p_search.add_argument("query", help="Gmail search query")
    p_search.add_argument("--max-results", type=int, default=10, help="Max threads to return")

    # get_thread
    p_thread = subparsers.add_parser("get_thread", help="Get a full thread")
    p_thread.add_argument("email", help="Account")
    p_thread.add_argument("thread_id", help="Thread ID")

    # get_message
    p_msg = subparsers.add_parser("get_message", help="Get a single message")
    p_msg.add_argument("email", help="Account")
    p_msg.add_argument("message_id", help="Message ID")

    args = parser.parse_args()

    if args.command == "authenticate":
        cmd_authenticate(args.email)
    elif args.command == "list_accounts":
        cmd_list_accounts()
    elif args.command == "remove_account":
        cmd_remove_account(args.email)
    elif args.command == "search":
        cmd_search(args.email, args.query, args.max_results)
    elif args.command == "get_thread":
        cmd_get_thread(args.email, args.thread_id)
    elif args.command == "get_message":
        cmd_get_message(args.email, args.message_id)


if __name__ == "__main__":
    main()
