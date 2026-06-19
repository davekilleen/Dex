#!/usr/bin/env python3
"""
sf-activity-sync.py — Sync Dex activity back to Salesforce as Tasks.

Scans project pages in 04-Projects/ for Dex-originated activity entries and
logs them to Salesforce, then marks them synced to prevent duplicates.

Usage:
  python .scripts/sf-activity-sync.py              # sync all projects
  python .scripts/sf-activity-sync.py --dry-run    # preview without writing
  python .scripts/sf-activity-sync.py --project "Rise Construction"  # single project
"""

import argparse
import datetime
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

VAULT_PATH = Path(os.environ.get("VAULT_PATH", Path(__file__).parent.parent))
TOKEN_FILE = Path.home() / ".claude" / "sf_tokens.json"
OWNER_ID = os.environ.get("SF_OWNER_ID", "")
CLIENT_ID = os.environ.get("SF_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SF_CLIENT_SECRET", "")
LOGIN_URL = "https://login.salesforce.com"

# Marker used to tag Dex-originated activity entries so we can find and mark them
DEX_MARKER = "[dex]"
DEX_SYNCED_PATTERN = re.compile(r"<!--\s*sf:(\w+)\s*-->")

# Matches activity log lines: "- **YYYY-MM-DD** — Some text [dex]"
ACTIVITY_LINE_PATTERN = re.compile(
    r"^(\s*-\s+\*\*(\d{4}-\d{2}-\d{2})\*\*\s+[—–-]\s+(.+?))(\s+\[dex\])(\s+<!--\s*sf:\w+\s*-->)?$"
)

# Matches unsynced Dex entries (has [dex] but no <!-- sf:... --> yet)
UNSYNCED_PATTERN = re.compile(
    r"^(\s*-\s+\*\*(\d{4}-\d{2}-\d{2})\*\*\s+[—–-]\s+(.+?))(\s+\[dex\])$"
)


# ── Token / auth ───────────────────────────────────────────────────────────────

def load_tokens():
    if TOKEN_FILE.exists():
        return json.loads(TOKEN_FILE.read_text())
    return None


def save_tokens(tokens):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))


def refresh_access_token(refresh_token):
    data = urlencode({
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token,
    }).encode()
    req = Request(f"{LOGIN_URL}/services/oauth2/token", data=data, method="POST")
    with urlopen(req) as resp:
        return json.loads(resp.read())


def get_valid_tokens():
    tokens = load_tokens()
    if not tokens:
        print("ERROR: Not authenticated. Run sf_authenticate via MCP first.", file=sys.stderr)
        sys.exit(1)
    try:
        refreshed = refresh_access_token(tokens["refresh_token"])
        tokens["access_token"] = refreshed["access_token"]
        if "instance_url" in refreshed:
            tokens["instance_url"] = refreshed["instance_url"]
        save_tokens(tokens)
    except Exception:
        pass
    return tokens


# ── Salesforce API ─────────────────────────────────────────────────────────────

def sf_create_task(tokens, subject, description, activity_date, what_id, who_id=None):
    instance_url = tokens["instance_url"]
    access_token = tokens["access_token"]
    payload = {
        "Subject": subject,
        "Status": "Completed",
        "ActivityDate": activity_date,
        "Description": description or "",
    }
    if what_id:
        payload["WhatId"] = what_id
    if who_id:
        payload["WhoId"] = who_id
    if OWNER_ID:
        payload["OwnerId"] = OWNER_ID
    data = json.dumps(payload).encode()
    req = Request(
        f"{instance_url}/services/data/v59.0/sobjects/Task",
        data=data,
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req) as resp:
        return json.loads(resp.read())


# ── Frontmatter parsing ────────────────────────────────────────────────────────

def parse_frontmatter(text):
    """Return dict of frontmatter key:value from YAML front matter block."""
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    block = text[3:end]
    result = {}
    for line in block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            result[k.strip()] = v.strip()
    return result


# ── Project page scanning ──────────────────────────────────────────────────────

def find_project_pages(filter_name=None):
    projects_dir = VAULT_PATH / "04-Projects"
    if not projects_dir.exists():
        return []
    pages = []
    for md_file in projects_dir.rglob("*.md"):
        if filter_name and filter_name.lower() not in md_file.stem.lower():
            continue
        pages.append(md_file)
    return pages


def get_unsynced_activities(page_path):
    """Return list of (line_index, date, text, full_line) for unsynced [dex] entries."""
    text = page_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    unsynced = []
    in_activity_log = False
    for i, line in enumerate(lines):
        if line.strip().startswith("## Activity Log"):
            in_activity_log = True
            continue
        if in_activity_log and line.startswith("## "):
            break
        if in_activity_log:
            m = UNSYNCED_PATTERN.match(line)
            if m:
                full_prefix = m.group(1)
                date = m.group(2)
                activity_text = m.group(3).strip()
                unsynced.append((i, date, activity_text, line, full_prefix))
    return unsynced, text, lines


def mark_synced(page_path, line_indices_to_task_ids):
    """Append <!-- sf:TASK_ID --> to synced lines in the page."""
    text = page_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    for line_idx, task_id in line_indices_to_task_ids.items():
        line = lines[line_idx]
        if UNSYNCED_PATTERN.match(line):
            lines[line_idx] = line + f" <!-- sf:{task_id} -->"
    page_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── Main sync logic ────────────────────────────────────────────────────────────

def sync_page(tokens, page_path, dry_run=False):
    text = page_path.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    opp_id = fm.get("sf_opportunity_id")
    if not opp_id:
        return 0

    unsynced, _, _ = get_unsynced_activities(page_path)
    if not unsynced:
        return 0

    print(f"\n[PAGE] {page_path.parent.name}")
    print(f"   Opportunity ID: {opp_id}")
    print(f"   {len(unsynced)} unsynced activities found")

    synced_map = {}
    for line_idx, date, activity_text, full_line, _ in unsynced:
        subject = activity_text[:255]  # SF subject max length
        print(f"   >> [{date}] {subject[:80]}{'...' if len(subject) > 80 else ''}")
        if not dry_run:
            try:
                result = sf_create_task(
                    tokens,
                    subject=subject,
                    description=activity_text,
                    activity_date=date,
                    what_id=opp_id,
                )
                task_id = result.get("id")
                if task_id:
                    synced_map[line_idx] = task_id
                    print(f"      OK Created Task {task_id}")
                else:
                    print(f"      WARN No task ID returned: {result}")
            except Exception as e:
                print(f"      ERROR: {e}")

    if synced_map:
        mark_synced(page_path, synced_map)

    return len(synced_map) if not dry_run else len(unsynced)


def main():
    parser = argparse.ArgumentParser(description="Sync Dex activity to Salesforce Tasks")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing to Salesforce")
    parser.add_argument("--project", type=str, help="Filter to projects matching this name")
    args = parser.parse_args()

    if args.dry_run:
        print("DRY RUN -- no tasks will be created in Salesforce\n")
        tokens = None
    else:
        tokens = get_valid_tokens()

    pages = find_project_pages(filter_name=args.project)
    if not pages:
        print("No project pages found.")
        return

    total_synced = 0
    for page in pages:
        count = sync_page(tokens, page, dry_run=args.dry_run)
        total_synced += count

    print(f"\n{'Preview' if args.dry_run else 'Synced'}: {total_synced} activities {'would be sent' if args.dry_run else 'sent'} to Salesforce")


if __name__ == "__main__":
    main()
