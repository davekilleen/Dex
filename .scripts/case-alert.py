#!/usr/bin/env python3
"""
case-alert.py -- Daily diff of open Salesforce Cases against the last-seen snapshot.

Read-only against Salesforce. Detects:
  - New cases on accounts Chris owns
  - Status or Priority changes on cases already seen

Writes:
  - .scripts/salesforce-data/case_snapshot.json  (current state, for next run's diff)
  - Inbox/Alerts/case-alert-YYYY-MM-DD.md        (only when there's something to report)

Prints a one-line summary to stdout for the PowerShell wrapper to relay as a toast:
  ALERT: 2 new case(s), 1 updated case(s)
  OK: no new or changed cases
"""

import json, os, sys, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import sflib

VAULT_PATH = Path(os.environ.get("VAULT_PATH", Path(__file__).resolve().parent.parent))
DATA_DIR = VAULT_PATH / ".scripts" / "salesforce-data"
ALERTS_DIR = VAULT_PATH / "Inbox" / "Alerts"
SNAPSHOT_FILE = DATA_DIR / "case_snapshot.json"

CLIENT_ID, CLIENT_SECRET, OWNER_ID = sflib.resolve_creds(VAULT_PATH)


def get_valid_tokens():
    tokens = sflib.get_valid_tokens()
    if not tokens:
        print("ERROR: Not authenticated. Run sf_authenticate via the Salesforce MCP first.", file=sys.stderr)
        sys.exit(1)
    if not (CLIENT_ID and CLIENT_SECRET):
        print("ERROR: SF_CLIENT_ID / SF_CLIENT_SECRET not found (env, .env, or .mcp.json).", file=sys.stderr)
        sys.exit(1)
    return tokens


def main():
    if not OWNER_ID:
        print("ERROR: SF_OWNER_ID not configured.", file=sys.stderr)
        sys.exit(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tokens = get_valid_tokens()

    soql = (
        "SELECT Id, CaseNumber, Subject, Status, Priority, Type, Reason, "
        "AccountId, Account.Name, ContactId, Contact.Name, CreatedDate, LastModifiedDate "
        f"FROM Case WHERE Account.OwnerId = '{OWNER_ID}' AND IsClosed = false "
        "ORDER BY LastModifiedDate DESC"
    )
    cases = sflib.query_all(tokens, soql)

    prev = {}
    if SNAPSHOT_FILE.exists():
        try:
            prev = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"WARN: could not read previous snapshot ({e}); treating as first run", file=sys.stderr)

    new_cases, changed_cases = [], []
    current = {}
    for c in cases:
        cid = c["Id"]
        entry = {
            "case_number": c.get("CaseNumber"),
            "subject": c.get("Subject"),
            "status": c.get("Status"),
            "priority": c.get("Priority"),
            "type": c.get("Type"),
            "account": (c.get("Account") or {}).get("Name"),
            "contact": (c.get("Contact") or {}).get("Name"),
            "last_modified": c.get("LastModifiedDate"),
        }
        current[cid] = entry

        if cid not in prev:
            new_cases.append(entry)
        else:
            old = prev[cid]
            if old.get("status") != entry["status"] or old.get("priority") != entry["priority"]:
                changed_cases.append({
                    **entry,
                    "old_status": old.get("status"),
                    "old_priority": old.get("priority"),
                })

    SNAPSHOT_FILE.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")

    is_first_run = not prev
    if is_first_run:
        # Nothing to diff against yet -- just establish the baseline, don't alert on
        # every pre-existing case.
        print(f"OK: baseline snapshot created ({len(current)} open case(s)), no alert on first run")
        return

    if not new_cases and not changed_cases:
        print("OK: no new or changed cases")
        return

    today = datetime.date.today().isoformat()
    ALERTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ALERTS_DIR / f"case-alert-{today}.md"

    lines = [f"# Case Alert — {today}", ""]
    if new_cases:
        lines.append(f"## New Cases ({len(new_cases)})")
        lines.append("")
        lines.append("| Case # | Account | Subject | Status | Priority | Type |")
        lines.append("|--------|---------|---------|--------|----------|------|")
        for e in new_cases:
            lines.append(f"| {e['case_number']} | {e['account']} | {e['subject']} | {e['status']} | {e['priority']} | {e['type']} |")
        lines.append("")
    if changed_cases:
        lines.append(f"## Updated Cases ({len(changed_cases)})")
        lines.append("")
        lines.append("| Case # | Account | Subject | Change | Type |")
        lines.append("|--------|---------|---------|--------|------|")
        for e in changed_cases:
            change_parts = []
            if e["old_status"] != e["status"]:
                change_parts.append(f"Status: {e['old_status']} → {e['status']}")
            if e["old_priority"] != e["priority"]:
                change_parts.append(f"Priority: {e['old_priority']} → {e['priority']}")
            lines.append(f"| {e['case_number']} | {e['account']} | {e['subject']} | {'; '.join(change_parts)} | {e['type']} |")
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")

    summary = f"ALERT: {len(new_cases)} new case(s), {len(changed_cases)} updated case(s)"
    print(summary)
    print(f"Written to {out_path}")


if __name__ == "__main__":
    main()
