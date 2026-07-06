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
from urllib.parse import quote
from urllib.request import Request, urlopen

VAULT_PATH = Path(os.environ.get("VAULT_PATH", Path(__file__).resolve().parent.parent))
DATA_DIR = VAULT_PATH / ".scripts" / "salesforce-data"
ALERTS_DIR = VAULT_PATH / "Inbox" / "Alerts"
SNAPSHOT_FILE = DATA_DIR / "case_snapshot.json"
TOKEN_FILE = Path.home() / ".claude" / "sf_tokens.json"
LOGIN_URL = "https://login.salesforce.com"
API = "v59.0"


def _load_creds():
    cid = os.environ.get("SF_CLIENT_ID", "")
    csec = os.environ.get("SF_CLIENT_SECRET", "")
    owner = os.environ.get("SF_OWNER_ID", "")
    if not (cid and csec and owner):
        mcp = VAULT_PATH / ".mcp.json"
        if mcp.exists():
            try:
                cfg = json.loads(mcp.read_text(encoding="utf-8"))
                servers = cfg.get("mcpServers", cfg.get("servers", {}))
                for name, s in servers.items():
                    env = s.get("env") or {}
                    if env.get("SF_CLIENT_ID") or env.get("SF_OWNER_ID"):
                        cid = cid or env.get("SF_CLIENT_ID", "")
                        csec = csec or env.get("SF_CLIENT_SECRET", "")
                        owner = owner or env.get("SF_OWNER_ID", "")
                        if cid and csec and owner:
                            break
            except Exception as e:
                print(f"WARN: could not read .mcp.json creds: {e}", file=sys.stderr)
    return cid, csec, owner


CLIENT_ID, CLIENT_SECRET, OWNER_ID = _load_creds()


def get_valid_tokens():
    if not TOKEN_FILE.exists():
        print("ERROR: Not authenticated. Run sf_authenticate via the Salesforce MCP first.", file=sys.stderr)
        sys.exit(1)
    tokens = json.loads(TOKEN_FILE.read_text())
    if not (CLIENT_ID and CLIENT_SECRET):
        print("ERROR: SF_CLIENT_ID / SF_CLIENT_SECRET not found (env or .mcp.json).", file=sys.stderr)
        sys.exit(1)
    from urllib.parse import urlencode
    data = urlencode({
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": tokens["refresh_token"],
    }).encode()
    try:
        with urlopen(Request(f"{LOGIN_URL}/services/oauth2/token", data=data, method="POST")) as r:
            refreshed = json.loads(r.read())
        tokens["access_token"] = refreshed["access_token"]
        if "instance_url" in refreshed:
            tokens["instance_url"] = refreshed["instance_url"]
        TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
    except Exception as e:
        print(f"WARN: token refresh failed ({e}); using existing access_token", file=sys.stderr)
    return tokens


def sf_query_all(tokens, soql):
    inst, tok = tokens["instance_url"], tokens["access_token"]
    url = f"{inst}/services/data/{API}/query?q={quote(soql)}"
    records = []
    while url:
        with urlopen(Request(url, headers={"Authorization": f"Bearer {tok}"})) as r:
            data = json.loads(r.read())
        records.extend(data.get("records", []))
        nxt = data.get("nextRecordsUrl")
        url = f"{inst}{nxt}" if nxt else None
    return records


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
    cases = sf_query_all(tokens, soql)
    for c in cases:
        c.pop("attributes", None)

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
