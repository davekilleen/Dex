#!/usr/bin/env python3
"""One-shot batch creator for pipeline sync — creates project pages from pipeline JSON."""

import json
import os
import re
import sys
from datetime import datetime

VAULT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECTS = os.path.join(VAULT, "Projects")

def sanitize(name):
    return re.sub(r'[<>:"/\\|?*]', '', name).strip()

def create_page(opp):
    account = opp["account"] or "Unknown"
    opp_name = opp["name"]
    vendor = opp.get("vendor") or "TBD"

    folder_name = sanitize(f"{account} - {opp_name} - {vendor}")
    md_name = folder_name + ".md"

    folder_path = os.path.join(PROJECTS, folder_name)
    quotes_path = os.path.join(folder_path, "Quotes")
    md_path = os.path.join(folder_path, md_name)

    if os.path.exists(md_path):
        return None  # already exists

    os.makedirs(quotes_path, exist_ok=True)

    now = datetime.now().isoformat()
    amt = f"${opp['amount']:,.2f}" if opp.get("amount") else "TBD"
    prob = f"{int(opp['probability'])}%" if opp.get("probability") is not None else "TBD"
    account_link = account.replace(" ", "_")

    content = f"""---
sf_opportunity_id: pending-sync
sf_account_id: pending-sync
sf_last_synced: {now}
---

# {opp_name}

**Account:** [[{account_link}|{account}]]
**Stage:** {opp['stage']}
**Amount:** {amt}
**Close Date:** {opp.get('close_date', 'TBD')}
**Probability:** {prob}
**Owner:** {opp.get('owner', 'TBD')}
**Vendor:** {vendor}

## Next Steps

— TBD —

## Key Contacts

| Name | Role | Title |
|------|------|-------|
| _Sync with updated MCP to populate_ | | |

## Quotes

| Quote # | Status | Total | Expiration | File |
|---------|--------|-------|------------|------|
| _Sync with updated MCP to populate_ | | | | |

## Correspondence & Files

_Link emails (from Retool email MCP) and OneDrive documents here._

-

## Activity Log

_Recent Salesforce activity synced automatically._

-

## Decisions

-

## Notes

-
"""
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)
    return folder_name


def main():
    data_file = sys.argv[1] if len(sys.argv) > 1 else os.path.join(VAULT, ".scripts", "pipeline-data.json")
    with open(data_file, "r") as f:
        opps = json.load(f)

    created = []
    skipped = 0
    for opp in opps:
        result = create_page(opp)
        if result:
            created.append(result)
        else:
            skipped += 1

    print(f"Created: {len(created)}")
    print(f"Skipped (already exist): {skipped}")
    for name in created:
        print(f"  + {name}")


if __name__ == "__main__":
    main()
