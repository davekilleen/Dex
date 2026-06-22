#!/usr/bin/env python3
"""
sf-activity-list.py -- List recent unsynced activity entries across all project pages.

Scans 04-Projects/ Activity Log sections for entries within the past N days
that have not been tagged [dex] or marked with <!-- sf:... -->.

Usage:
  python .scripts/sf-activity-list.py           # past 7 days (default)
  python .scripts/sf-activity-list.py --days 14 # past 14 days
  python .scripts/sf-activity-list.py --all     # all unsynced, no date filter

Output format (machine-readable for skill parsing):
  ACCOUNT | DATE | TEXT | FILE_PATH | LINE_NUM
"""

import argparse
import datetime
import os
import re
import sys
from pathlib import Path

VAULT_PATH = Path(os.environ.get("VAULT_PATH", Path(__file__).parent.parent))

# Matches any activity log line with a date
ACTIVITY_PATTERN = re.compile(
    r"^\s*-\s+\*\*(\d{4}-\d{2}-\d{2})\*\*\s+[—–-]\s+(.+)$"
)
SYNCED_MARKER = re.compile(r"<!--\s*sf:\w+\s*-->")
DEX_TAG = "[dex]"


def parse_frontmatter(text):
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    result = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            result[k.strip()] = v.strip()
    return result


def extract_account_name(page_path):
    """Derive a short account name from the folder name."""
    folder = page_path.parent.name
    # Folder format: "Account Name - OPP - ProductCode"
    parts = folder.split(" - ")
    return parts[0].strip() if parts else folder


def scan_project_pages(days=7, all_entries=False):
    projects_dir = VAULT_PATH / "Projects"
    if not projects_dir.exists():
        return []

    cutoff = None
    if not all_entries:
        cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()

    results = []
    for md_file in sorted(projects_dir.rglob("*.md")):
        text = md_file.read_text(encoding="utf-8")
        fm = parse_frontmatter(text)
        if not fm.get("sf_opportunity_id") and not fm.get("sf_account_id"):
            continue

        account = extract_account_name(md_file)
        lines = text.splitlines()
        in_activity_log = False

        for i, line in enumerate(lines):
            if line.strip().startswith("## Activity Log"):
                in_activity_log = True
                continue
            if in_activity_log and line.startswith("## "):
                break
            if not in_activity_log:
                continue

            m = ACTIVITY_PATTERN.match(line)
            if not m:
                continue

            date_str = m.group(1)
            activity_text = m.group(2).strip()

            # Skip already synced (has sf marker)
            if SYNCED_MARKER.search(line):
                continue

            # Skip already tagged for sync
            if DEX_TAG in line:
                continue

            # Apply date filter
            if cutoff and date_str < cutoff:
                continue

            results.append({
                "account": account,
                "date": date_str,
                "text": activity_text,
                "file": str(md_file),
                "line": i,
            })

    return results


def main():
    parser = argparse.ArgumentParser(description="List recent unsynced Dex activity")
    parser.add_argument("--days", type=int, default=7, help="Look back N days (default 7)")
    parser.add_argument("--all", action="store_true", help="Show all unsynced, no date limit")
    args = parser.parse_args()

    entries = scan_project_pages(days=args.days, all_entries=args.all)

    if not entries:
        print("No unsynced activity found.")
        return

    print(f"Found {len(entries)} unsynced activities:\n")
    current_account = None
    for idx, e in enumerate(entries, 1):
        if e["account"] != current_account:
            if current_account is not None:
                print()
            print(f"  {e['account']}")
            current_account = e["account"]
        text = e["text"]
        display = text[:80] + ("..." if len(text) > 80 else "")
        print(f"    [{idx}] {e['date']} — {display}")

    print(f"\n--- END ({len(entries)} total) ---")
    print("\nPIPE_DATA_START")
    for e in entries:
        safe_text = e["text"].replace("|", "/")
        print(f"{e['account']}|{e['date']}|{safe_text}|{e['file']}|{e['line']}")
    print("PIPE_DATA_END")


if __name__ == "__main__":
    main()
