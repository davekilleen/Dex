#!/usr/bin/env python3
"""Batch-update pipeline project pages with full Salesforce opportunity details."""

import json
import os
import re
import sys
from datetime import datetime

VAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS = os.path.join(VAULT, "Projects")

def find_project_page(opp_name, account):
    """Find existing project page by matching opp name in folder names."""
    for folder in os.listdir(PROJECTS):
        folder_path = os.path.join(PROJECTS, folder)
        if not os.path.isdir(folder_path):
            continue
        if opp_name.replace("'", "’") in folder or opp_name.replace("/", "") in folder:
            for f in os.listdir(folder_path):
                if f.endswith(".md") and f != "README.md":
                    return os.path.join(folder_path, f)
    # Fallback: try matching account + partial opp name
    opp_parts = opp_name.split(" - ")
    for folder in os.listdir(PROJECTS):
        if account.split(" -")[0] in folder and any(p in folder for p in opp_parts if len(p) > 3):
            folder_path = os.path.join(PROJECTS, folder)
            if os.path.isdir(folder_path):
                for f in os.listdir(folder_path):
                    if f.endswith(".md") and f != "README.md":
                        return os.path.join(folder_path, f)
    return None

def build_contacts_table(contacts):
    if not contacts:
        return "| _No contacts linked in Salesforce_ | | |"
    rows = []
    for c in contacts:
        contact = c.get("Contact", {})
        name = contact.get("Name", "Unknown")
        name_link = name.replace(" ", "_")
        role = c.get("Role") or "—"
        title = contact.get("Title") or "—"
        rows.append(f"| [[{name_link}|{name}]] | {role} | {title} |")
    return "\n".join(rows)

def build_quotes_table(quotes):
    if not quotes:
        return "| _No quotes in Salesforce_ | | | | |"
    rows = []
    for q in quotes:
        qnum = q.get("QuoteNumber", "—")
        status = q.get("Status", "—")
        total = f"${q['GrandTotal']:,.2f}" if q.get("GrandTotal") else "—"
        exp = q.get("ExpirationDate") or "—"
        rows.append(f"| {qnum} | {status} | {total} | {exp} | |")
    return "\n".join(rows)

def build_activity_log(activities):
    if not activities:
        return "_No recent activity_"
    lines = []
    for a in activities[:5]:
        subject = a.get("Subject", "—")
        date = a.get("ActivityDate", "—")
        who = a.get("Who", {})
        who_name = who.get("Name", "") if who else ""
        status = a.get("Status", "")
        lines.append(f"- **{date}** — {subject}" + (f" ({who_name})" if who_name else ""))
    return "\n".join(lines)

def update_page(md_path, opp_data):
    """Rewrite the project page with full SF data."""
    opp = opp_data["opportunity"]
    contacts = opp_data.get("contacts", [])
    quotes = opp_data.get("quotes", [])
    activities = opp_data.get("recent_activity", [])

    now = datetime.now().isoformat()
    opp_id = opp["Id"]
    account = opp.get("Account", {})
    account_id = account.get("Id", "pending-sync")
    account_name = account.get("Name", "Unknown")
    account_link = account_name.replace(" ", "_")

    amt = f"${opp['Amount']:,.2f}" if opp.get("Amount") else "TBD"
    prob = f"{int(opp['Probability'])}%" if opp.get("Probability") is not None else "TBD"
    next_step = opp.get("NextStep") or "— TBD —"
    lead_source = opp.get("LeadSource") or "—"
    opp_type = opp.get("Type") or "—"

    contacts_table = build_contacts_table(contacts)
    quotes_table = build_quotes_table(quotes)
    activity_log = build_activity_log(activities)

    content = f"""---
sf_opportunity_id: {opp_id}
sf_account_id: {account_id}
sf_last_synced: {now}
---

# {opp['Name']}

**Account:** [[{account_link}|{account_name}]]
**Stage:** {opp['StageName']}
**Amount:** {amt}
**Close Date:** {opp['CloseDate']}
**Probability:** {prob}
**Owner:** {opp['Owner']['Name']}
**Lead Source:** {lead_source}
**Type:** {opp_type}

## Next Steps

{next_step}

## Key Contacts

| Name | Role | Title |
|------|------|-------|
{contacts_table}

## Quotes

| Quote # | Status | Total | Expiration | File |
|---------|--------|-------|------------|------|
{quotes_table}

## Correspondence & Files

_Link emails (from Retool email MCP) and OneDrive documents here._

-

## Activity Log

{activity_log}

## Decisions

-

## Notes

-
"""
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)
    return True

def main():
    data = json.loads(sys.stdin.read())
    updated = 0
    skipped = 0
    errors = []

    for item in data:
        opp = item["opportunity"]
        opp_name = opp["Name"]
        account_name = opp.get("Account", {}).get("Name", "Unknown")

        md_path = find_project_page(opp_name, account_name)
        if not md_path:
            errors.append(f"NOT FOUND: {opp_name}")
            continue

        try:
            update_page(md_path, item)
            updated += 1
            print(f"  Updated: {opp_name}")
        except Exception as e:
            errors.append(f"ERROR: {opp_name} - {e}")

    print(f"\nDone: {updated} updated, {len(errors)} errors")
    for e in errors:
        print(f"  {e}")

if __name__ == "__main__":
    main()
