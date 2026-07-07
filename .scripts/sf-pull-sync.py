#!/usr/bin/env python3
"""
sf-pull-sync.py -- Weekly pull of Chris's Salesforce data into a local working dataset.

Salesforce = system of record; this local dataset = system of analysis.
Run weekly; ad-hoc pipeline analysis should read these files instead of re-querying SF live
(only hit SF live when something genuinely needs real-time validation).

Pulls (scoped to owned accounts, OwnerId = Chris):
  - opportunities.json   all opportunities owned by Chris (open AND closed -> keeps lost/won context)
  - tasks.json           Tasks owned by Chris, last N days (Description/Comments = the account narrative)
  - events.json          Events owned by Chris, last N days
  - accounts.json        Accounts owned by Chris
  - manifest.json        synced_at timestamp + per-object record counts

Output dir: .scripts/salesforce-data/

Usage:
  python .scripts/sf-pull-sync.py                 # full weekly pull
  python .scripts/sf-pull-sync.py --days 365      # limit activity lookback (default 730)
  python .scripts/sf-pull-sync.py --quiet
"""

import argparse, json, os, sys, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import sflib

VAULT_PATH = Path(os.environ.get("VAULT_PATH", Path(__file__).resolve().parent.parent))
OUT_DIR = VAULT_PATH / ".scripts" / "salesforce-data"

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


# -- Queries --------------------------------------------------------------------

# Each query is tagged with a group:
#   "frequent" -> opportunities, quotes, tasks (high-velocity; pulled often to stay near-live)
#   "full"     -> everything (slower-changing accounts/contacts/events refreshed weekly)
def queries(days):
    owner = OWNER_ID
    return {
        "opportunities": ("frequent",
            "SELECT Id, Name, AccountId, Account.Name, StageName, Amount, CloseDate, Probability, "
            "NextStep, LastActivityDate, LastModifiedDate, CreatedDate, IsClosed, IsWon, "
            "Vendor__r.Name, Opp_Machine_Type__c, LeadSource, TouchNextDate__c "
            f"FROM Opportunity WHERE OwnerId = '{owner}'"
        ),
        "quotes": ("frequent",
            "SELECT Id, Name, QuoteNumber, Status, GrandTotal, TotalPrice, ExpirationDate, "
            "OpportunityId, Opportunity.Name, AccountId, Account.Name, CreatedDate, LastModifiedDate "
            f"FROM Quote WHERE Opportunity.OwnerId = '{owner}'"
        ),
        # Activities on Chris's accounts by ANY owner, plus Chris's own activities anywhere.
        "tasks": ("frequent",
            "SELECT Id, Subject, Description, ActivityDate, Status, Type, WhatId, What.Name, "
            "WhoId, Who.Name, AccountId, Account.Name, OwnerId, Owner.Name, LastModifiedDate "
            f"FROM Task WHERE (Account.OwnerId = '{owner}' OR OwnerId = '{owner}') "
            f"AND LastModifiedDate = LAST_N_DAYS:{days} "
            "ORDER BY ActivityDate DESC NULLS LAST"
        ),
        "events": ("full",
            "SELECT Id, Subject, Description, ActivityDate, ActivityDateTime, DurationInMinutes, "
            "WhatId, What.Name, WhoId, Who.Name, AccountId, Account.Name, OwnerId, Owner.Name, LastModifiedDate "
            f"FROM Event WHERE (Account.OwnerId = '{owner}' OR OwnerId = '{owner}') "
            f"AND LastModifiedDate = LAST_N_DAYS:{days} "
            "ORDER BY ActivityDate DESC NULLS LAST"
        ),
        "accounts": ("full",
            "SELECT Id, Name, BillingStreet, BillingCity, BillingState, BillingPostalCode, "
            "ShippingStreet, ShippingCity, ShippingState, ShippingPostalCode, "
            "Type, Industry, Phone, LastActivityDate, OwnerId, UCC_BuyID__c "
            f"FROM Account WHERE OwnerId = '{owner}'"
        ),
        "contacts": ("full",
            "SELECT Id, FirstName, LastName, Title, Email, Phone, MobilePhone, "
            "AccountId, Account.Name, LastModifiedDate "
            f"FROM Contact WHERE Account.OwnerId = '{owner}'"
        ),
    }


def main():
    ap = argparse.ArgumentParser(description="Pull Chris's Salesforce data into a local working dataset")
    ap.add_argument("--group", choices=["full", "frequent"], default="full",
                    help="'frequent' = opportunities/quotes/tasks (high-velocity); 'full' = everything (default)")
    ap.add_argument("--days", type=int, default=730, help="Activity lookback window (default 730)")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if not OWNER_ID:
        print("ERROR: SF_OWNER_ID not configured.", file=sys.stderr); sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    tokens = get_valid_tokens()

    # Merge into existing manifest so a 'frequent' run doesn't erase 'full' object counts/timestamps.
    mpath = OUT_DIR / "manifest.json"
    manifest = {"owner_id": OWNER_ID, "instance_url": tokens.get("instance_url"),
                "activity_lookback_days": args.days, "synced_at": {}, "counts": {}}
    if mpath.exists():
        try:
            old = json.loads(mpath.read_text())
            manifest["synced_at"] = old.get("synced_at", {}) if isinstance(old.get("synced_at"), dict) else {}
            manifest["counts"] = old.get("counts", {})
        except Exception:
            pass

    now = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    selected = {n: q for n, (grp, q) in queries(args.days).items() if args.group == "full" or grp == "frequent"}

    for name, soql in selected.items():
        try:
            recs = sflib.query_all(tokens, soql)
            (OUT_DIR / f"{name}.json").write_text(
                json.dumps(recs, indent=2, default=str, ensure_ascii=False), encoding="utf-8"
            )
            manifest["counts"][name] = len(recs)
            manifest["synced_at"][name] = now
            if not args.quiet:
                print(f"  {name:14} {len(recs):>6} records")
        except Exception as e:
            manifest["counts"][name] = f"ERROR: {e}"
            print(f"  {name:14} ERROR: {e}", file=sys.stderr)

    manifest["last_run"] = {"at": now, "group": args.group}
    mpath.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if not args.quiet:
        print(f"\nSynced [{args.group}] {now} -> {OUT_DIR}")
        print("Read these files for analysis instead of re-querying Salesforce live.")


if __name__ == "__main__":
    main()
