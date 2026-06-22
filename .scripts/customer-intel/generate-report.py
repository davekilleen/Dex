#!/usr/bin/env python3
"""
Dex Customer Intelligence — Monthly Report Generator

Runs headless (no MCP required). Connects directly to Salesforce using
saved OAuth tokens, generates a markdown report, and saves it to the vault.

Usage:
    python3 generate-report.py [--days N] [--output PATH]

    --days N          Look-back window for new assets (default: 30)
    --months N        Look-ahead for lease expirations (default: 12)
    --output PATH     Override output file path
    --stdout          Print report to stdout instead of saving

Automatically run monthly via the launchd agent. Also called from the
/customer-intel report mode in Dex.
"""

import json
import os
import sys
import argparse
from datetime import datetime, date, timedelta
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError

# ── Config ────────────────────────────────────────────────────────────────────

VAULT_PATH = os.environ.get("VAULT_PATH", "")
TOKEN_FILE = Path.home() / ".claude" / "sf_tokens.json"
LOGIN_URL = "https://login.salesforce.com"
CLIENT_ID = os.environ.get("SF_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("SF_CLIENT_SECRET", "")


# ── Salesforce Auth ────────────────────────────────────────────────────────────

def load_tokens():
    if not TOKEN_FILE.exists():
        return None
    with open(TOKEN_FILE) as f:
        return json.load(f)


def save_tokens(tokens):
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(tokens, f)


def refresh_tokens(tokens):
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return None
    data = urlencode({
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": refresh_token,
    }).encode()
    req = Request(f"{LOGIN_URL}/services/oauth2/token", data=data, method="POST")
    try:
        with urlopen(req) as resp:
            new_tokens = json.loads(resp.read())
            new_tokens["refresh_token"] = refresh_token
            save_tokens(new_tokens)
            return new_tokens
    except Exception:
        return None


def get_valid_tokens():
    tokens = load_tokens()
    if not tokens:
        return None
    return tokens


def sf_query(tokens, soql):
    instance_url = tokens["instance_url"]
    access_token = tokens["access_token"]
    encoded = urlencode({"q": soql})
    req = Request(
        f"{instance_url}/services/data/v59.0/query?{encoded}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        if e.code == 401 and tokens.get("refresh_token"):
            refreshed = refresh_tokens(tokens)
            if refreshed:
                return sf_query(refreshed, soql)
        raise


# ── Asset Parsing ─────────────────────────────────────────────────────────────

def expiry_info(usage_end_str):
    if not usage_end_str:
        return None, None
    try:
        end_date = datetime.strptime(usage_end_str[:10], "%Y-%m-%d").date()
        days = (end_date - date.today()).days
        if days <= 0:
            urgency = "LAPSED"
        elif days <= 90:
            urgency = "CRITICAL"
        elif days <= 180:
            urgency = "HIGH"
        elif days <= 365:
            urgency = "MEDIUM"
        else:
            urgency = "LOW"
        return days, urgency
    except Exception:
        return None, None


def urgency_icon(urgency):
    return {"CRITICAL": "🔴", "HIGH": "🟡", "MEDIUM": "🟠", "LOW": "🟢", "LAPSED": "⚫"}.get(urgency or "", "—")


def parse_record(r):
    days, urgency = expiry_info(r.get("UsageEndDate"))
    return {
        "id": r["Id"],
        "name": r.get("Name", ""),
        "machine_type": r.get("Machine_Type_New__c") or "—",
        "model": r.get("ModelName__c") or "—",
        "builder": r.get("Builder__c") or r.get("UCC_Vendor__c") or "—",
        "serial": r.get("SerialNumber") or "—",
        "sale_or_lease": r.get("Sale_or_Lease__c") or "—",
        "install_date": (r.get("InstallDate") or "")[:10] or "—",
        "usage_end_date": (r.get("UsageEndDate") or "")[:10] or "—",
        "days_to_expiry": days,
        "urgency": urgency,
        "is_competitor": r.get("IsCompetitorProduct", False),
        "account": (r.get("Account") or {}).get("Name") or "Unknown",
        "account_id": (r.get("Account") or {}).get("Id") or "",
        "created_date": (r.get("CreatedDate") or "")[:10] or "",
    }


# ── Salesforce Queries ────────────────────────────────────────────────────────

def get_expiring_assets(tokens, months=12):
    future = (date.today() + timedelta(days=months * 30)).strftime("%Y-%m-%d")
    soql = f"""
        SELECT Id, Name, Machine_Type_New__c, ModelName__c, Builder__c, UCC_Vendor__c,
               Sale_or_Lease__c, UsageEndDate, Status, IsCompetitorProduct,
               Account.Name, Account.Id
        FROM Asset
        WHERE UsageEndDate != null
          AND UsageEndDate >= TODAY
          AND UsageEndDate <= {future}
        ORDER BY UsageEndDate ASC
        LIMIT 500
    """
    result = sf_query(tokens, soql)
    return [parse_record(r) for r in result.get("records", [])]


def get_new_assets(tokens, days=30):
    soql = f"""
        SELECT Id, Name, Machine_Type_New__c, ModelName__c, Builder__c, UCC_Vendor__c,
               Sale_or_Lease__c, InstallDate, UsageEndDate, Status, IsCompetitorProduct,
               Account.Name, Account.Id, CreatedDate
        FROM Asset
        WHERE CreatedDate >= LAST_N_DAYS:{days}
        ORDER BY CreatedDate DESC
        LIMIT 500
    """
    result = sf_query(tokens, soql)
    return [parse_record(r) for r in result.get("records", [])]


# ── Report Generation ─────────────────────────────────────────────────────────

def md_table(headers, rows, alignments=None):
    if not rows:
        return "*No records*\n"
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(cell)))
    sep = "| " + " | ".join("-" * w for w in col_widths) + " |"
    header_row = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"
    data_rows = ["| " + " | ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)) + " |" for row in rows]
    return "\n".join([header_row, sep] + data_rows) + "\n"


def build_report(expiring_assets, new_assets, days_back, months_ahead, generated_at):
    today_str = date.today().strftime("%B %d, %Y")
    month_str = date.today().strftime("%B %Y")

    critical = [a for a in expiring_assets if a["urgency"] == "CRITICAL"]
    high = [a for a in expiring_assets if a["urgency"] == "HIGH"]
    medium = [a for a in expiring_assets if a["urgency"] == "MEDIUM"]

    our_new = [a for a in new_assets if not a["is_competitor"]]
    comp_new = [a for a in new_assets if a["is_competitor"]]
    new_accounts = list({a["account_id"]: a["account"] for a in new_assets if a["account_id"]}.values())

    lines = []
    lines.append(f"# Customer Intelligence Report — {month_str}")
    lines.append(f"*Generated: {generated_at} | Source: Salesforce Assets (EDA/UCC-1)*")
    lines.append("")

    # Summary box
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| 🔴 Leases expiring 0–90 days (CRITICAL) | **{len(critical)}** |")
    lines.append(f"| 🟡 Leases expiring 90–180 days (HIGH) | **{len(high)}** |")
    lines.append(f"| 🟠 Leases expiring 180–365 days (MEDIUM) | **{len(medium)}** |")
    lines.append(f"| New equipment records (last {days_back} days) | {len(new_assets)} |")
    lines.append(f"| New accounts with records | {len(new_accounts)} |")
    lines.append(f"| Competitor equipment added | {len(comp_new)} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Expiration sections
    lines.append("## Lease Expirations")
    lines.append("")

    if critical:
        lines.append("### 🔴 CRITICAL — Expiring in 0–90 Days (Act Now)")
        lines.append("")
        rows = [[a["account"], a["machine_type"], a["model"], a["builder"],
                 a["usage_end_date"], f"{a['days_to_expiry']} days"] for a in critical]
        lines.append(md_table(
            ["Account", "Machine Type", "Model", "Builder", "Lease Ends", "Days Left"],
            rows
        ))
    else:
        lines.append("### 🔴 CRITICAL — Expiring in 0–90 Days")
        lines.append("")
        lines.append("*No critical expirations this period.*")
        lines.append("")

    if high:
        lines.append("### 🟡 HIGH — Expiring in 90–180 Days (Schedule Outreach)")
        lines.append("")
        rows = [[a["account"], a["machine_type"], a["model"], a["builder"],
                 a["usage_end_date"], f"{a['days_to_expiry']} days"] for a in high]
        lines.append(md_table(
            ["Account", "Machine Type", "Model", "Builder", "Lease Ends", "Days Left"],
            rows
        ))
    else:
        lines.append("### 🟡 HIGH — Expiring in 90–180 Days")
        lines.append("")
        lines.append("*No high-priority expirations this period.*")
        lines.append("")

    if medium:
        lines.append("### 🟠 MEDIUM — Expiring in 180–365 Days (Calendar Reminder)")
        lines.append("")
        rows = [[a["account"], a["machine_type"], a["model"],
                 a["usage_end_date"], f"{a['days_to_expiry']} days"] for a in medium]
        lines.append(md_table(
            ["Account", "Machine Type", "Model", "Lease Ends", "Days Left"],
            rows
        ))
    else:
        lines.append("### 🟠 MEDIUM — Expiring in 180–365 Days")
        lines.append("")
        lines.append("*No medium-priority expirations this period.*")
        lines.append("")

    lines.append("---")
    lines.append("")

    # New activity section
    lines.append(f"## New Activity (Last {days_back} Days)")
    lines.append("")

    if our_new:
        lines.append(f"### New Equipment Records — Our Machines ({len(our_new)})")
        lines.append("")
        rows = [[a["account"], a["machine_type"], a["model"], a["builder"],
                 a["sale_or_lease"], a["install_date"], a["usage_end_date"]] for a in our_new]
        lines.append(md_table(
            ["Account", "Machine Type", "Model", "Builder", "S/L", "Install Date", "Lease End"],
            rows
        ))
    else:
        lines.append(f"### New Equipment Records — Our Machines")
        lines.append("")
        lines.append("*No new equipment records this period.*")
        lines.append("")

    if comp_new:
        lines.append(f"### New Competitor Equipment ({len(comp_new)})")
        lines.append("")
        rows = [[a["account"], a["machine_type"], a["model"], a["builder"],
                 a["install_date"], a["usage_end_date"]] for a in comp_new]
        lines.append(md_table(
            ["Account", "Machine Type", "Model", "Competitor", "Install Date", "Lease End"],
            rows
        ))
    else:
        lines.append("### New Competitor Equipment")
        lines.append("")
        lines.append("*No new competitor equipment recorded this period.*")
        lines.append("")

    if new_accounts:
        lines.append(f"### New Accounts with Equipment Records ({len(new_accounts)})")
        lines.append("")
        for acct in sorted(new_accounts):
            lines.append(f"- {acct}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## Quick Actions")
    lines.append("")
    lines.append("- Run `/customer-intel alerts` for the interactive lease dashboard")
    lines.append("- Run `/customer-intel [account]` for a full profile on any account above")
    lines.append("- Run `/customer-intel competitive` for the full competitor equipment map")
    lines.append("")
    lines.append("*Report auto-generated by Dex Customer Intelligence automation.*")
    lines.append(f"*Next report: {(date.today().replace(day=1) + timedelta(days=32)).replace(day=1).strftime('%B 1, %Y')}*")

    return "\n".join(lines) + "\n"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate Dex Customer Intelligence report")
    parser.add_argument("--days", type=int, default=30, help="Look-back window for new assets (default: 30)")
    parser.add_argument("--months", type=int, default=12, help="Look-ahead for lease expirations (default: 12)")
    parser.add_argument("--output", type=str, default="", help="Override output file path")
    parser.add_argument("--stdout", action="store_true", help="Print to stdout instead of saving")
    args = parser.parse_args()

    tokens = get_valid_tokens()
    if not tokens:
        print("ERROR: No Salesforce tokens found. Run sf_authenticate from Dex first.", file=sys.stderr)
        sys.exit(1)

    print("Fetching lease expirations...", file=sys.stderr)
    expiring = get_expiring_assets(tokens, months=args.months)

    print(f"Fetching new assets (last {args.days} days)...", file=sys.stderr)
    new = get_new_assets(tokens, days=args.days)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    report = build_report(expiring, new, args.days, args.months, generated_at)

    if args.stdout:
        print(report)
        return

    # Determine output path
    if args.output:
        output_path = Path(args.output)
    elif VAULT_PATH:
        report_dir = Path(VAULT_PATH) / "Inbox" / "Reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        filename = f"Customer_Intel_{date.today().strftime('%Y-%m')}.md"
        output_path = report_dir / filename
    else:
        # Fallback: write next to this script
        script_dir = Path(__file__).parent
        output_path = script_dir / f"customer-intel-{date.today().strftime('%Y-%m')}.md"

    output_path.write_text(report, encoding="utf-8")
    print(f"Report saved: {output_path}", file=sys.stderr)
    print(str(output_path))  # stdout = path, for the installer to use


if __name__ == "__main__":
    main()
