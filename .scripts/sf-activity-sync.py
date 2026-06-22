#!/usr/bin/env python3
"""
sf-activity-sync.py -- Sync Dex activity back to Salesforce as Tasks.

Scans project pages in Projects/ for Dex-originated activity entries and
logs them to Salesforce, then marks them synced to prevent duplicates.

Usage:
  python .scripts/sf-activity-sync.py              # sync all projects
  python .scripts/sf-activity-sync.py --dry-run    # preview without writing
  python .scripts/sf-activity-sync.py --project "Rise Construction"  # single project

Activity line format in project pages:
  - **YYYY-MM-DD** -- Prefix: Summary text [dex]

Supported prefixes and their Salesforce Type mapping:
  Call:             -> Call
  Email:            -> Email
  Text:             -> Text
  Meeting:          -> Virtual Meeting
  Visit:            -> Visit
  Appointment:      -> Appointment
  Demo:             -> Demo
  Demo Truck:       -> Demo Truck Visit
  Install:          -> Install
  Attempt:          -> Attempt
  Vendor:           -> Vendor Rep Travel
  Note:             -> Other
  Task:             -> Other
  (anything else)   -> Other
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

VAULT_PATH = Path(os.environ.get("VAULT_PATH", Path(__file__).parent.parent))
TOKEN_FILE = Path.home() / ".claude" / "sf_tokens.json"
OWNER_ID = os.environ.get("SF_OWNER_ID", "")
CLIENT_ID = os.environ.get("SF_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SF_CLIENT_SECRET", "")
LOGIN_URL = "https://login.salesforce.com"

# Maps activity line prefix (lowercase) to Salesforce Type picklist value
PREFIX_TO_TYPE = {
    "call":        "Call",
    "email":       "Email",
    "text":        "Text",
    "meeting":     "Virtual Meeting",
    "visit":       "Visit",
    "appointment": "Appointment",
    "demo truck":  "Demo Truck Visit",
    "demo":        "Demo",
    "install":     "Install",
    "attempt":     "Attempt",
    "vendor":      "Vendor Rep Travel",
    "note":        "Other",
    "task":        "Other",
}

# Matches unsynced Dex entries (has [dex] but no <!-- sf:... --> yet)
# The separator can be an em dash (—), en dash (–), or hyphen (-)
UNSYNCED_PATTERN = re.compile(
    r"^(\s*-\s+\*\*(\d{4}-\d{2}-\d{2})\*\*\s+[—–-]\s+(.+?))(\s+\[dex\])$"
)

# Extracts "Prefix: rest of text" from activity text
PREFIX_PATTERN = re.compile(r"^([^:]{2,30}):\s+(.+)$")


# -- Token / auth ---------------------------------------------------------------

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


# -- Salesforce API -------------------------------------------------------------

def sf_query(tokens, soql):
    instance_url = tokens["instance_url"]
    access_token = tokens["access_token"]
    encoded = quote(soql)
    req = Request(
        f"{instance_url}/services/data/v59.0/query?q={encoded}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urlopen(req) as resp:
        return json.loads(resp.read())


def sf_create_task(tokens, subject, description, activity_date, sf_type, what_id, who_id=None):
    instance_url = tokens["instance_url"]
    access_token = tokens["access_token"]
    payload = {
        "Subject": subject,
        "Status": "Completed",
        "ActivityDate": activity_date,
        "Description": description,
        "Type": sf_type,
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


# -- Activity text parsing ------------------------------------------------------

def short_summary(text, word_count=5):
    """Return first N words of text."""
    words = text.split()
    return " ".join(words[:word_count]).rstrip(",")


def parse_activity(activity_text):
    """
    Parse 'Prefix: Full description' into (sf_type, subject, description).
    Subject format: 'Type - First few words...'
    Description: full clean text without prefix.
    """
    m = PREFIX_PATTERN.match(activity_text.strip())
    if m:
        prefix_raw = m.group(1).strip()
        rest = m.group(2).strip()
        prefix_lower = prefix_raw.lower()
        sf_type = None
        for key in sorted(PREFIX_TO_TYPE, key=len, reverse=True):
            if prefix_lower.startswith(key):
                sf_type = PREFIX_TO_TYPE[key]
                break
        if sf_type:
            subject = f"{sf_type} - {short_summary(rest)}"[:255]
            return sf_type, subject, rest
    subject = f"Other - {short_summary(activity_text)}"[:255]
    return "Other", subject, activity_text


# -- Frontmatter parsing --------------------------------------------------------

def parse_frontmatter(text):
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


# -- Contact SF ID lookup via Opportunity.Contact__c (cached per run) -----------

_contact_cache = {}

def lookup_contact_from_opportunity(tokens, opp_id):
    """Return the Contact Id stored in Opportunity.Contact__c, or None."""
    if opp_id in _contact_cache:
        return _contact_cache[opp_id]
    try:
        soql = f"SELECT Contact__c FROM Opportunity WHERE Id = '{opp_id}' LIMIT 1"
        result = sf_query(tokens, soql)
        records = result.get("records", [])
        contact_id = records[0].get("Contact__c") if records else None
        _contact_cache[opp_id] = contact_id
        return contact_id
    except Exception as e:
        print(f"      WARN Contact__c lookup failed for opp {opp_id}: {e}")
        _contact_cache[opp_id] = None
        return None


# -- Project page scanning ------------------------------------------------------

def find_project_pages(filter_name=None):
    projects_dir = VAULT_PATH / "Projects"
    if not projects_dir.exists():
        return []
    pages = []
    for md_file in projects_dir.rglob("*.md"):
        if filter_name and filter_name.lower() not in md_file.stem.lower():
            continue
        pages.append(md_file)
    return pages


def get_unsynced_activities(page_path):
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
                date = m.group(2)
                activity_text = m.group(3).strip()
                unsynced.append((i, date, activity_text, line))
    return unsynced, text, lines


def mark_synced(page_path, line_indices_to_task_ids):
    text = page_path.read_text(encoding="utf-8")
    lines = text.splitlines()
    for line_idx, task_id in line_indices_to_task_ids.items():
        line = lines[line_idx]
        if UNSYNCED_PATTERN.match(line):
            lines[line_idx] = line + f" <!-- sf:{task_id} -->"
    page_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# -- Main sync logic ------------------------------------------------------------

def sync_page(tokens, page_path, dry_run=False):
    text = page_path.read_text(encoding="utf-8")
    fm = parse_frontmatter(text)
    opp_id = fm.get("sf_opportunity_id")
    account_id = fm.get("sf_account_id")

    # Need at least one ID to link the task
    what_id = opp_id or account_id
    if not what_id:
        return 0

    unsynced, _, _ = get_unsynced_activities(page_path)
    if not unsynced:
        return 0

    what_label = f"Opp {opp_id}" if opp_id else f"Account {account_id}"
    print(f"\n[PAGE] {page_path.parent.name}")
    print(f"   Linked to: {what_label}")
    print(f"   {len(unsynced)} unsynced activities found")

    # Resolve WhoId from Opportunity.Contact__c
    who_id = None
    if opp_id and not dry_run:
        who_id = lookup_contact_from_opportunity(tokens, opp_id)
        if who_id:
            print(f"   Contact__c: {who_id}")
        else:
            print(f"   Contact__c: not set on opportunity, WhoId skipped")
    elif opp_id and dry_run:
        print(f"   Contact__c: lookup skipped in dry run")

    synced_map = {}
    for line_idx, date, activity_text, full_line in unsynced:
        sf_type, subject, description = parse_activity(activity_text)
        print(f"   >> [{date}] [{sf_type}] {subject[:70]}{'...' if len(subject) > 70 else ''}")
        if not dry_run:
            try:
                result = sf_create_task(
                    tokens,
                    subject=subject,
                    description=description,
                    activity_date=date,
                    sf_type=sf_type,
                    what_id=what_id,
                    who_id=who_id,
                )
                task_id = result.get("id")
                if task_id:
                    synced_map[line_idx] = task_id
                    print(f"      OK  Task {task_id}")
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

    print(f"\n{'Preview' if args.dry_run else 'Synced'}: {total_synced} {'activities would be sent to' if args.dry_run else 'activities sent to'} Salesforce")


if __name__ == "__main__":
    main()
