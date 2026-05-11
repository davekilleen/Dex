#!/usr/bin/env python3
"""
Gmail Client for Dex — Read + Write multi-account Gmail management.

Companion to gmail_reader.py (which stays read-only by design).
This script grants Dex the ability to manage labels, archive, and triage
between Inbox / @To Do / @Waiting For across multiple accounts.

Security posture:
- gmail.modify scope (read + label + archive + mark; CANNOT send mail)
- Separate token storage from gmail_reader.py — modify-scope tokens are
  stored as token_<hash>_modify.json so they can coexist with the
  readonly tokens used by gmail_reader.py without clobbering.
- Tokens stored with 0600 permissions in ~/.config/dex/gmail/
- OAuth credentials via the same GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET
  env vars used by gmail_reader.py — one GCP project, two scopes.

Usage:
    # Auth (per account, one time — gmail_reader auth does NOT count here)
    gmail_client.py authenticate <email>

    # Account management
    gmail_client.py list_accounts
    gmail_client.py remove_account <email>

    # Label discovery
    gmail_client.py list_labels <email>

    # Read (mirrors gmail_reader for convenience)
    gmail_client.py search <email> "<query>" [--max-results 10]
    gmail_client.py get_thread <email> <thread_id>

    # Label management (primitive — takes label IDs)
    gmail_client.py add_label <email> <thread_id> <label_id> [<label_id> ...]
    gmail_client.py remove_label <email> <thread_id> <label_id> [<label_id> ...]

    # Triage convenience (takes label NAMES; resolves to IDs internally)
    gmail_client.py move <email> <thread_id> --from "<label_name>" --to "<label_name>"
    gmail_client.py to_waiting <email> <thread_id>      # @To Do -> @Waiting For
    gmail_client.py to_todo <email> <thread_id>         # @Waiting For -> @To Do, or just add @To Do
    gmail_client.py to_inbox <email> <thread_id>        # add INBOX (system label)
    gmail_client.py archive <email> <thread_id>         # remove INBOX

    # Read state
    gmail_client.py mark_read <email> <thread_id>       # remove UNREAD
    gmail_client.py mark_unread <email> <thread_id>     # add UNREAD

Environment:
    GMAIL_CLIENT_ID     — OAuth 2.0 Client ID (from Google Cloud Console)
    GMAIL_CLIENT_SECRET — OAuth 2.0 Client Secret

See gmail_reader.md for GCP project setup. Same project / credentials
are reused here; only the requested OAuth scope differs.
"""

import argparse
import base64
import hashlib
import json
import os
import stat
import sys
from pathlib import Path

# gmail.modify = read + write labels + archive + mark read/unread.
# Does NOT include send (gmail.send) or full settings (gmail.settings.*).
SCOPES = ["https://www.googleapis.com/auth/gmail.modify"]
CONFIG_DIR = Path.home() / ".config" / "dex" / "gmail"
ACCOUNTS_FILE = CONFIG_DIR / "accounts_modify.json"


def ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, stat.S_IRWXU)


def token_path(email: str) -> Path:
    """Modify-scope tokens are stored separately from readonly tokens."""
    email_hash = hashlib.sha256(email.lower().encode()).hexdigest()[:16]
    return CONFIG_DIR / f"token_{email_hash}_modify.json"


def load_accounts() -> list:
    if not ACCOUNTS_FILE.exists():
        return []
    return json.loads(ACCOUNTS_FILE.read_text())


def save_accounts(accounts: list):
    ensure_config_dir()
    ACCOUNTS_FILE.write_text(json.dumps(accounts, indent=2))
    os.chmod(ACCOUNTS_FILE, stat.S_IRUSR | stat.S_IWUSR)


def get_client_config() -> dict:
    client_id = os.environ.get("GMAIL_CLIENT_ID")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET")

    if not client_id or not client_secret:
        print(
            json.dumps(
                {
                    "error": "Missing environment variables",
                    "detail": "Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET. See gmail_reader.md for GCP project setup.",
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
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    path = token_path(email)
    if not path.exists():
        print(
            json.dumps(
                {
                    "error": f"Account not authenticated for modify scope: {email}",
                    "detail": f"Run: python3 gmail_client.py authenticate {email}",
                    "note": "A readonly token from gmail_reader.py does NOT grant modify access.",
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
    ensure_config_dir()
    path = token_path(email)
    path.write_text(creds.to_json())
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def build_service(email: str):
    from googleapiclient.discovery import build

    creds = get_credentials(email)
    return build("gmail", "v1", credentials=creds)


# --- Label resolution helpers ---


def fetch_labels(service) -> list:
    """Return all labels (user + system) for the authenticated account."""
    return service.users().labels().list(userId="me").execute().get("labels", [])


def resolve_label_id(service, name: str) -> str:
    """Resolve a label display name (case-insensitive) to its label ID.

    System labels (INBOX, UNREAD, STARRED, etc.) are matched directly.
    User labels are matched against the `name` field returned by the API.
    """
    name_norm = name.strip()
    # System labels are conventionally uppercase
    upper = name_norm.upper()
    system_labels = {
        "INBOX", "UNREAD", "STARRED", "IMPORTANT", "SENT", "DRAFT",
        "SPAM", "TRASH", "CHAT",
    }
    if upper in system_labels:
        return upper

    labels = fetch_labels(service)
    for lbl in labels:
        if lbl["name"].lower() == name_norm.lower():
            return lbl["id"]

    print(
        json.dumps(
            {
                "error": f"Label not found: {name}",
                "available_labels": [lbl["name"] for lbl in labels],
            }
        )
    )
    sys.exit(1)


# --- Commands: auth + accounts ---


def cmd_authenticate(email: str):
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
                "scope": "gmail.modify",
                "token_path": str(token_path(email)),
            }
        )
    )


def cmd_list_accounts():
    accounts = load_accounts()
    valid = []
    for email in accounts:
        path = token_path(email)
        valid.append({"email": email, "token_exists": path.exists(), "scope": "gmail.modify"})
    print(json.dumps({"accounts": valid}, indent=2))


def cmd_remove_account(email: str):
    path = token_path(email)
    if path.exists():
        path.unlink()

    accounts = load_accounts()
    accounts = [a for a in accounts if a.lower() != email.lower()]
    save_accounts(accounts)

    print(json.dumps({"success": True, "email": email, "status": "removed"}))


# --- Commands: read (mirrors gmail_reader) ---


def cmd_list_labels(email: str):
    service = build_service(email)
    labels = fetch_labels(service)
    out = [{"id": l["id"], "name": l["name"], "type": l.get("type", "user")} for l in labels]
    print(json.dumps({"email": email, "labels": out}, indent=2))


def cmd_search(email: str, query: str, max_results: int = 10):
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
                "label_ids": thread.get("messages", [{}])[0].get("labelIds", []),
                "messages": messages,
            }
        )
    print(json.dumps({"email": email, "query": query, "threads": output}, indent=2))


def cmd_get_thread(email: str, thread_id: str):
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
                "label_ids": msg.get("labelIds", []),
            }
        )
    print(json.dumps({"thread_id": thread_id, "messages": messages}, indent=2))


def extract_body(payload: dict) -> str:
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


# --- Commands: label management (primitive — takes label IDs) ---


def cmd_add_label(email: str, thread_id: str, label_ids: list):
    service = build_service(email)
    body = {"addLabelIds": label_ids, "removeLabelIds": []}
    result = service.users().threads().modify(userId="me", id=thread_id, body=body).execute()
    print(
        json.dumps(
            {
                "success": True,
                "thread_id": thread_id,
                "added": label_ids,
                "current_label_ids": _thread_label_ids(result),
            }
        )
    )


def cmd_remove_label(email: str, thread_id: str, label_ids: list):
    service = build_service(email)
    body = {"addLabelIds": [], "removeLabelIds": label_ids}
    result = service.users().threads().modify(userId="me", id=thread_id, body=body).execute()
    print(
        json.dumps(
            {
                "success": True,
                "thread_id": thread_id,
                "removed": label_ids,
                "current_label_ids": _thread_label_ids(result),
            }
        )
    )


def _thread_label_ids(thread_response: dict) -> list:
    """Pull the union of labelIds across messages in a thread response."""
    seen = set()
    for msg in thread_response.get("messages", []):
        for lid in msg.get("labelIds", []):
            seen.add(lid)
    return sorted(seen)


# --- Commands: convenience (takes label NAMES; resolves) ---


def _move_by_name(service, thread_id: str, from_name: str = None, to_name: str = None):
    add_ids = []
    remove_ids = []
    if to_name:
        add_ids.append(resolve_label_id(service, to_name))
    if from_name:
        remove_ids.append(resolve_label_id(service, from_name))
    body = {"addLabelIds": add_ids, "removeLabelIds": remove_ids}
    result = service.users().threads().modify(userId="me", id=thread_id, body=body).execute()
    return {
        "thread_id": thread_id,
        "added": add_ids,
        "removed": remove_ids,
        "current_label_ids": _thread_label_ids(result),
    }


def cmd_move(email: str, thread_id: str, from_name: str, to_name: str):
    service = build_service(email)
    out = _move_by_name(service, thread_id, from_name=from_name, to_name=to_name)
    out["success"] = True
    out["from"] = from_name
    out["to"] = to_name
    print(json.dumps(out, indent=2))


def cmd_to_waiting(email: str, thread_id: str):
    """Convenience: remove @To Do, add @Waiting For."""
    service = build_service(email)
    out = _move_by_name(service, thread_id, from_name="@To Do", to_name="@Waiting For")
    out["success"] = True
    out["action"] = "to_waiting"
    print(json.dumps(out, indent=2))


def cmd_to_todo(email: str, thread_id: str):
    """Convenience: remove @Waiting For (if present), add @To Do."""
    service = build_service(email)
    out = _move_by_name(service, thread_id, from_name="@Waiting For", to_name="@To Do")
    out["success"] = True
    out["action"] = "to_todo"
    print(json.dumps(out, indent=2))


def cmd_to_inbox(email: str, thread_id: str):
    """Convenience: add INBOX label (un-archive)."""
    service = build_service(email)
    body = {"addLabelIds": ["INBOX"], "removeLabelIds": []}
    result = service.users().threads().modify(userId="me", id=thread_id, body=body).execute()
    print(
        json.dumps(
            {
                "success": True,
                "thread_id": thread_id,
                "action": "to_inbox",
                "current_label_ids": _thread_label_ids(result),
            }
        )
    )


def cmd_archive(email: str, thread_id: str):
    """Convenience: remove INBOX label."""
    service = build_service(email)
    body = {"addLabelIds": [], "removeLabelIds": ["INBOX"]}
    result = service.users().threads().modify(userId="me", id=thread_id, body=body).execute()
    print(
        json.dumps(
            {
                "success": True,
                "thread_id": thread_id,
                "action": "archive",
                "current_label_ids": _thread_label_ids(result),
            }
        )
    )


def cmd_mark_read(email: str, thread_id: str):
    service = build_service(email)
    body = {"addLabelIds": [], "removeLabelIds": ["UNREAD"]}
    result = service.users().threads().modify(userId="me", id=thread_id, body=body).execute()
    print(
        json.dumps(
            {
                "success": True,
                "thread_id": thread_id,
                "action": "mark_read",
                "current_label_ids": _thread_label_ids(result),
            }
        )
    )


def cmd_mark_unread(email: str, thread_id: str):
    service = build_service(email)
    body = {"addLabelIds": ["UNREAD"], "removeLabelIds": []}
    result = service.users().threads().modify(userId="me", id=thread_id, body=body).execute()
    print(
        json.dumps(
            {
                "success": True,
                "thread_id": thread_id,
                "action": "mark_unread",
                "current_label_ids": _thread_label_ids(result),
            }
        )
    )


# --- CLI ---


def main():
    parser = argparse.ArgumentParser(
        description="Gmail Client for Dex — read + write multi-account Gmail management"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # auth + accounts
    p_auth = subparsers.add_parser("authenticate", help="OAuth flow (gmail.modify scope)")
    p_auth.add_argument("email")
    subparsers.add_parser("list_accounts", help="List authenticated accounts")
    p_rm = subparsers.add_parser("remove_account", help="Remove an authenticated account")
    p_rm.add_argument("email")

    # label discovery
    p_ll = subparsers.add_parser("list_labels", help="List all labels (id + name) for an account")
    p_ll.add_argument("email")

    # read
    p_search = subparsers.add_parser("search", help="Search threads (includes label IDs)")
    p_search.add_argument("email")
    p_search.add_argument("query")
    p_search.add_argument("--max-results", type=int, default=10)

    p_thread = subparsers.add_parser("get_thread", help="Get full thread with labels + bodies")
    p_thread.add_argument("email")
    p_thread.add_argument("thread_id")

    # primitive label ops
    p_add = subparsers.add_parser("add_label", help="Add labels to a thread (label IDs)")
    p_add.add_argument("email")
    p_add.add_argument("thread_id")
    p_add.add_argument("label_ids", nargs="+")

    p_rmv = subparsers.add_parser("remove_label", help="Remove labels from a thread (label IDs)")
    p_rmv.add_argument("email")
    p_rmv.add_argument("thread_id")
    p_rmv.add_argument("label_ids", nargs="+")

    # convenience (label NAMES)
    p_move = subparsers.add_parser("move", help="Move thread: remove one label, add another (by name)")
    p_move.add_argument("email")
    p_move.add_argument("thread_id")
    p_move.add_argument("--from", dest="from_name", required=True)
    p_move.add_argument("--to", dest="to_name", required=True)

    p_tw = subparsers.add_parser("to_waiting", help="Convenience: @To Do -> @Waiting For")
    p_tw.add_argument("email")
    p_tw.add_argument("thread_id")

    p_tt = subparsers.add_parser("to_todo", help="Convenience: @Waiting For -> @To Do")
    p_tt.add_argument("email")
    p_tt.add_argument("thread_id")

    p_ti = subparsers.add_parser("to_inbox", help="Add INBOX label (un-archive)")
    p_ti.add_argument("email")
    p_ti.add_argument("thread_id")

    p_ar = subparsers.add_parser("archive", help="Remove INBOX label")
    p_ar.add_argument("email")
    p_ar.add_argument("thread_id")

    p_mr = subparsers.add_parser("mark_read", help="Remove UNREAD label")
    p_mr.add_argument("email")
    p_mr.add_argument("thread_id")

    p_mu = subparsers.add_parser("mark_unread", help="Add UNREAD label")
    p_mu.add_argument("email")
    p_mu.add_argument("thread_id")

    args = parser.parse_args()

    if args.command == "authenticate":
        cmd_authenticate(args.email)
    elif args.command == "list_accounts":
        cmd_list_accounts()
    elif args.command == "remove_account":
        cmd_remove_account(args.email)
    elif args.command == "list_labels":
        cmd_list_labels(args.email)
    elif args.command == "search":
        cmd_search(args.email, args.query, args.max_results)
    elif args.command == "get_thread":
        cmd_get_thread(args.email, args.thread_id)
    elif args.command == "add_label":
        cmd_add_label(args.email, args.thread_id, args.label_ids)
    elif args.command == "remove_label":
        cmd_remove_label(args.email, args.thread_id, args.label_ids)
    elif args.command == "move":
        cmd_move(args.email, args.thread_id, args.from_name, args.to_name)
    elif args.command == "to_waiting":
        cmd_to_waiting(args.email, args.thread_id)
    elif args.command == "to_todo":
        cmd_to_todo(args.email, args.thread_id)
    elif args.command == "to_inbox":
        cmd_to_inbox(args.email, args.thread_id)
    elif args.command == "archive":
        cmd_archive(args.email, args.thread_id)
    elif args.command == "mark_read":
        cmd_mark_read(args.email, args.thread_id)
    elif args.command == "mark_unread":
        cmd_mark_unread(args.email, args.thread_id)


if __name__ == "__main__":
    main()
