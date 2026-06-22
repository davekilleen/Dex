"""Batch-create project pages from pipeline JSON data."""
import json, os, sys, re
from datetime import datetime

VAULT = os.environ.get("VAULT_PATH", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROJECTS = os.path.join(VAULT, "Projects")
NOW = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

def sanitize_folder(name):
    return re.sub(r'[<>:"/\\|?*]', '', name).replace('’', "'").strip()

def format_amount(amt):
    if amt is None:
        return "—"
    return f"${amt:,.2f}"

def build_page(opp):
    amt_str = format_amount(opp.get("amount"))
    prob = opp.get("probability")
    prob_str = f"{int(prob)}%" if prob else "—"
    close = opp.get("close_date", "—")

    return f"""---
sf_opportunity_id: {opp['id']}
sf_account_id: {opp['account_id']}
sf_last_synced: {NOW}
---

# {opp['name']}

**Account:** [[{sanitize_folder(opp['account']).replace(' ', '_')}|{opp['account']}]]
**Stage:** {opp['stage']}
**Amount:** {amt_str}
**Close Date:** {close}
**Probability:** {prob_str}
**Owner:** Chris Barsanti
**Lead Source:** —
**Type:** —

## Next Steps

—

## Key Contacts

| Name | Role | Title |
|------|------|-------|
| _No contacts linked in Salesforce_ | | |

## Quotes

| Quote # | Status | Total | Expiration | File |
|---------|--------|-------|------------|------|
| _No quotes in Salesforce_ | | | | |

## Correspondence & Files

_Link emails (from Retool email MCP) and OneDrive documents here._

-

## Activity Log

_No recent activity_

## Decisions

-

## Notes

-
"""

def main():
    data_file = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "pipeline-new-opps.json")
    with open(data_file, "r", encoding="utf-8") as f:
        opps = json.load(f)

    created = 0
    skipped = 0
    for opp in opps:
        account = sanitize_folder(opp["account"])
        opp_name = sanitize_folder(opp["name"])
        folder_name = f"{account} - {opp_name} - TBD"
        folder_path = os.path.join(PROJECTS, folder_name)
        file_path = os.path.join(folder_path, f"{folder_name}.md")

        if os.path.exists(file_path):
            skipped += 1
            continue

        os.makedirs(folder_path, exist_ok=True)
        content = build_page(opp)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        created += 1
        print(f"  Created: {folder_name}")

    print(f"\nDone. Created: {created} | Skipped (existing): {skipped}")

if __name__ == "__main__":
    main()
