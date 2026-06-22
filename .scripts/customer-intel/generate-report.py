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


def sf_describe(tokens, object_name):
    """Return field metadata for a Salesforce object."""
    instance_url = tokens["instance_url"]
    access_token = tokens["access_token"]
    req = Request(
        f"{instance_url}/services/data/v59.0/sobjects/{object_name}/describe",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    try:
        with urlopen(req) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        if e.code == 401 and tokens.get("refresh_token"):
            refreshed = refresh_tokens(tokens)
            if refreshed:
                return sf_describe(refreshed, object_name)
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


EARLY_TERM = 54   # months — previous standard lease term
STD_TERM   = 60   # months — common standard lease term


def urgency_icon(urgency):
    return {"CRITICAL": "🔴", "HIGH": "🟡", "MEDIUM": "🟠", "LOW": "🟢", "LAPSED": "⚫"}.get(urgency or "", "—")


def replacement_window(close_date_str):
    """Calculate 54/60-month replacement window from sale close date."""
    if not close_date_str:
        return None
    try:
        close = datetime.strptime(close_date_str[:10], "%Y-%m-%d").date()
        today = date.today()
        months_elapsed = (today.year - close.year) * 12 + (today.month - close.month)
        std_end = close + timedelta(days=STD_TERM * 30)
        days_to_std = (std_end - today).days

        if months_elapsed >= STD_TERM:
            status, urgency = "PAST_WINDOW", "CRITICAL"
        elif months_elapsed >= EARLY_TERM:
            status, urgency = "IN_WINDOW", "CRITICAL"
        elif days_to_std <= 180:
            status, urgency = "APPROACHING", "HIGH"
        elif days_to_std <= 365:
            status, urgency = "UPCOMING", "MEDIUM"
        else:
            status, urgency = "ACTIVE", "LOW"

        return {
            "months_elapsed": months_elapsed,
            "std_end_date": std_end.isoformat(),
            "days_to_std_end": days_to_std,
            "status": status,
            "urgency": urgency,
        }
    except Exception:
        return None


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


def get_financed_deals(tokens):
    """Pull all PM records with a close date and calculate replacement windows."""
    soql = """
        SELECT Id, Name, Sale_Close_Date__c, Install_Date__c,
               Updated_Ship_Date__c, OWU_Ship_Date__c,
               Warranty_Length__c, Machine_Type__c, Model__c, Status__c,
               Account_Name__r.Name, Account_Name__c,
               Sales_Rep__r.Name, Vendor__r.Name
        FROM Project_Management__c
        WHERE Sale_Close_Date__c != null
        ORDER BY Sale_Close_Date__c ASC
        LIMIT 2000
    """
    result = sf_query(tokens, soql)
    deals = []
    for r in result.get("records", []):
        w = replacement_window(r.get("Sale_Close_Date__c"))
        if not w:
            continue
        deals.append({
            "id": r["Id"],
            "name": r.get("Name", ""),
            "machine_type": r.get("Machine_Type__c") or "—",
            "model": r.get("Model__c") or "—",
            "status": r.get("Status__c") or "—",
            "close_date": (r.get("Sale_Close_Date__c") or "")[:10],
            "install_date": (r.get("Install_Date__c") or "")[:10] or "—",
            "warranty_length": r.get("Warranty_Length__c") or "—",
            "account": (r.get("Account_Name__r") or {}).get("Name") or "Unknown",
            "account_id": r.get("Account_Name__c") or "",
            "sales_rep": (r.get("Sales_Rep__r") or {}).get("Name") or "—",
            "vendor": (r.get("Vendor__r") or {}).get("Name") or "—",
            "window": w,
        })
    return deals


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


def build_replacement_section(deals):
    """Build the predicted replacement window section from PM records."""
    if not deals:
        return ["*No Project Management records with close dates found.*", ""]

    in_window  = [d for d in deals if d["window"]["status"] in ("IN_WINDOW", "PAST_WINDOW")]
    approaching = [d for d in deals if d["window"]["status"] == "APPROACHING"]
    upcoming   = [d for d in deals if d["window"]["status"] == "UPCOMING"]
    active     = [d for d in deals if d["window"]["status"] == "ACTIVE"]

    lines = []
    lines.append(f"*Based on {STD_TERM}-month standard lease term ({EARLY_TERM}-month early window). "
                 f"Close date used as financing start.*")
    lines.append("")

    lines.append("### Summary")
    lines.append("")
    lines.append("| Status | Count | Description |")
    lines.append("|--------|-------|-------------|")
    lines.append(f"| 🔴 In Window Now | **{len(in_window)}** | Past {EARLY_TERM}mo mark — call now |")
    lines.append(f"| 🟡 Approaching (≤180 days to 60mo) | **{len(approaching)}** | Schedule outreach |")
    lines.append(f"| 🟠 Upcoming (≤365 days to 60mo) | **{len(upcoming)}** | Calendar reminder |")
    lines.append(f"| 🟢 Active | **{len(active)}** | 12+ months remaining |")
    lines.append("")

    if in_window:
        lines.append(f"### 🔴 In Replacement Window Now — {len(in_window)} Deals")
        lines.append("")
        rows = []
        for d in sorted(in_window, key=lambda x: x["window"]["months_elapsed"], reverse=True):
            mo = d["window"]["months_elapsed"]
            status_label = f"{mo}mo elapsed"
            if d["window"]["status"] == "PAST_WINDOW":
                status_label += " ⚠️ past 60mo"
            rows.append([d["account"], d["machine_type"], d["model"],
                         d["close_date"], status_label, d["sales_rep"]])
        lines.append(md_table(
            ["Account", "Machine Type", "Model", "Close Date", "Elapsed", "Sales Rep"],
            rows
        ))

    if approaching:
        lines.append(f"### 🟡 Approaching — {len(approaching)} Deals (Window Opens ≤180 Days)")
        lines.append("")
        rows = [[d["account"], d["machine_type"], d["model"],
                 d["close_date"], d["window"]["std_end_date"],
                 str(d["window"]["days_to_std_end"]) + " days"] for d in approaching]
        lines.append(md_table(
            ["Account", "Machine Type", "Model", "Close Date", "60mo End", "Days Left"],
            rows
        ))

    if upcoming:
        lines.append(f"### 🟠 Upcoming — {len(upcoming)} Deals (Window Opens ≤1 Year)")
        lines.append("")
        rows = [[d["account"], d["machine_type"], d["model"],
                 d["close_date"], d["window"]["std_end_date"]] for d in upcoming]
        lines.append(md_table(
            ["Account", "Machine Type", "Model", "Close Date", "60mo End"],
            rows
        ))

    return lines


def build_report(expiring_assets, new_assets, days_back, months_ahead, generated_at, deals=None):
    today_str = date.today().strftime("%B %d, %Y")
    month_str = date.today().strftime("%B %Y")

    critical = [a for a in expiring_assets if a["urgency"] == "CRITICAL"]
    high = [a for a in expiring_assets if a["urgency"] == "HIGH"]
    medium = [a for a in expiring_assets if a["urgency"] == "MEDIUM"]

    our_new = [a for a in new_assets if not a["is_competitor"]]
    comp_new = [a for a in new_assets if a["is_competitor"]]
    new_accounts = list({a["account_id"]: a["account"] for a in new_assets if a["account_id"]}.values())

    deals = deals or []
    deals_in_window   = [d for d in deals if d["window"]["status"] in ("IN_WINDOW", "PAST_WINDOW")]
    deals_approaching = [d for d in deals if d["window"]["status"] == "APPROACHING"]
    deals_upcoming    = [d for d in deals if d["window"]["status"] == "UPCOMING"]

    lines = []
    lines.append(f"# Customer Intelligence Report — {month_str}")
    lines.append(f"*Generated: {generated_at} | Source: Salesforce Assets (EDA/UCC-1)*")
    lines.append("")

    # Summary box
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Count |")
    lines.append(f"|--------|-------|")
    lines.append(f"| 🔴 In replacement window now ({EARLY_TERM}–{STD_TERM}mo) | **{len(deals_in_window)}** |")
    lines.append(f"| 🟡 Approaching window (≤180 days to 60mo) | **{len(deals_approaching)}** |")
    lines.append(f"| 🟠 Upcoming window (≤365 days to 60mo) | **{len(deals_upcoming)}** |")
    lines.append(f"| EDA — Leases expiring 0–90 days | {len(critical)} |")
    lines.append(f"| New equipment records (last {days_back} days) | {len(new_assets)} |")
    lines.append(f"| New accounts with records | {len(new_accounts)} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Replacement window section (PM-based)
    lines.append("## Predicted Replacement Windows (Your Deals)")
    lines.append("")
    lines.extend(build_replacement_section(deals))
    lines.append("---")
    lines.append("")

    # EDA expiration section
    lines.append("## EDA Asset Lease Expirations")
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
                 a["sale_or_lease"], a["install_date"], a["usage_end_date"] or "—"] for a in our_new]
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
                 a["install_date"], a["usage_end_date"] or "—"] for a in comp_new]
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

def diagnose(tokens, account_name=""):
    """Pull raw field values from a sample of Asset records to see what's populated."""
    account_filter = f"Account.Name LIKE '%{account_name}%' AND" if account_name else ""
    soql = f"""
        SELECT Id, Name, Account.Name,
               Machine_Type_New__c, ModelName__c, Builder__c, SerialNumber,
               InstallDate, PurchaseDate, Purchase_Date__c, UsageEndDate,
               Sale_or_Lease__c, Status, Price,
               UCCID__c, UCC_BuyID__c, UCC_Status__c, UCC_New_or_Used__c,
               UCC_EQT_Code__c, UCC_S_N__c, UCC_Vendor__c,
               IsCompetitorProduct, FollowUpDate__c, Description,
               Close_Date__c, ShippingDate__c
        FROM Asset
        WHERE {account_filter} Id != null
        ORDER BY CreatedDate DESC
        LIMIT 5
    """
    result = sf_query(tokens, soql)
    records = result.get("records", [])
    if not records:
        print("No records found.")
        return

    for r in records:
        print(f"\n{'='*60}")
        print(f"Asset: {r.get('Name')}  |  Account: {(r.get('Account') or {}).get('Name')}")
        print(f"{'='*60}")
        fields = [
            ("Machine Type",    r.get("Machine_Type_New__c")),
            ("Model",           r.get("ModelName__c")),
            ("Builder",         r.get("Builder__c")),
            ("Serial Number",   r.get("SerialNumber")),
            ("Install Date",    r.get("InstallDate")),
            ("Purchase Date",   r.get("PurchaseDate")),
            ("Purchase Date 2", r.get("Purchase_Date__c")),
            ("Usage End Date",  r.get("UsageEndDate")),
            ("Close Date",      r.get("Close_Date__c")),
            ("Shipping Date",   r.get("ShippingDate__c")),
            ("Sale or Lease",   r.get("Sale_or_Lease__c")),
            ("Status",          r.get("Status")),
            ("Price",           r.get("Price")),
            ("UCC ID",          r.get("UCCID__c")),
            ("UCC Buy ID",      r.get("UCC_BuyID__c")),
            ("UCC Status",      r.get("UCC_Status__c")),
            ("UCC New/Used",    r.get("UCC_New_or_Used__c")),
            ("UCC EQT Code",    r.get("UCC_EQT_Code__c")),
            ("UCC Serial",      r.get("UCC_S_N__c")),
            ("UCC Vendor",      r.get("UCC_Vendor__c")),
            ("Is Competitor",   r.get("IsCompetitorProduct")),
            ("Follow Up Date",  r.get("FollowUpDate__c")),
            ("Description",     (r.get("Description") or "")[:80] or None),
        ]
        populated = [(k, v) for k, v in fields if v not in (None, "", False)]
        empty     = [k for k, v in fields if v in (None, "", False)]
        print(f"  POPULATED ({len(populated)}):")
        for k, v in populated:
            print(f"    {k:<20} {v}")
        print(f"  EMPTY ({len(empty)}): {', '.join(empty)}")


def diagnose_pm(tokens):
    """Discover the Project Management object schema and show sample records."""
    print("\n=== Project Management Object — Field Discovery ===\n")

    # 1. Describe the object to get all field names and types
    try:
        meta = sf_describe(tokens, "Project_Management__c")
    except Exception as e:
        print(f"Could not describe Project_Management__c: {e}")
        print("The object may have a different API name. Check Setup > Object Manager in Salesforce.")
        return

    fields = meta.get("fields", [])
    date_fields   = [f for f in fields if f["type"] in ("date", "datetime")]
    lookup_fields = [f for f in fields if f["type"] == "reference"]
    text_fields   = [f for f in fields if f["type"] in ("string", "picklist", "textarea", "currency", "double")]

    print(f"Total fields: {len(fields)}")
    print(f"\nDate/DateTime fields ({len(date_fields)}):")
    for f in date_fields:
        print(f"  {f['name']:<40} {f['label']}")

    print(f"\nLookup/Relationship fields ({len(lookup_fields)}):")
    for f in lookup_fields:
        refs = ", ".join(f.get("referenceTo", []))
        print(f"  {f['name']:<40} {f['label']} → {refs}")

    print(f"\nKey text/picklist/currency fields ({len(text_fields)}):")
    for f in text_fields[:30]:
        print(f"  {f['name']:<40} {f['label']} ({f['type']})")
    if len(text_fields) > 30:
        print(f"  ... and {len(text_fields) - 30} more")

    # 2. Pull 5 sample records with all date fields + name + lookups
    date_field_names = [f["name"] for f in date_fields]
    lookup_field_names = [f["name"] for f in lookup_fields[:5]]
    select_fields = ["Id", "Name"] + date_field_names + lookup_field_names
    soql = f"SELECT {', '.join(select_fields[:25])} FROM Project_Management__c ORDER BY CreatedDate DESC LIMIT 5"

    print(f"\n=== Sample Records (most recent 5) ===")
    try:
        result = sf_query(tokens, soql)
        records = result.get("records", [])
        if not records:
            print("No Project Management records found.")
            return
        for r in records:
            print(f"\n  Name: {r.get('Name')}")
            for fn in date_field_names:
                if r.get(fn):
                    label = next((f["label"] for f in date_fields if f["name"] == fn), fn)
                    print(f"    {label:<35} {r[fn]}")
            for fn in lookup_field_names:
                if r.get(fn):
                    label = next((f["label"] for f in lookup_fields if f["name"] == fn), fn)
                    print(f"    {label:<35} {r[fn]}")
    except Exception as e:
        print(f"Could not query sample records: {e}")
        print(f"Attempted SOQL: {soql}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate Dex Customer Intelligence report")
    parser.add_argument("--days", type=int, default=30, help="Look-back window for new assets (default: 30)")
    parser.add_argument("--months", type=int, default=12, help="Look-ahead for lease expirations (default: 12)")
    parser.add_argument("--output", type=str, default="", help="Override output file path")
    parser.add_argument("--stdout", action="store_true", help="Print to stdout instead of saving")
    parser.add_argument("--diagnose", action="store_true", help="Show raw field values for 5 sample Asset records")
    parser.add_argument("--diagnose-pm", action="store_true", help="Discover Project Management object schema and sample data")
    parser.add_argument("--account", type=str, default="", help="Account name filter for --diagnose mode")
    args = parser.parse_args()

    tokens = get_valid_tokens()
    if not tokens:
        print("ERROR: No Salesforce tokens found. Run sf_authenticate from Dex first.", file=sys.stderr)
        sys.exit(1)

    if args.diagnose:
        diagnose(tokens, account_name=args.account)
        return

    if getattr(args, "diagnose_pm", False):
        diagnose_pm(tokens)
        return

    print("Fetching replacement windows (Project Management)...", file=sys.stderr)
    deals = get_financed_deals(tokens)

    print("Fetching EDA lease expirations...", file=sys.stderr)
    expiring = get_expiring_assets(tokens, months=args.months)

    print(f"Fetching new assets (last {args.days} days)...", file=sys.stderr)
    new = get_new_assets(tokens, days=args.days)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    report = build_report(expiring, new, args.days, args.months, generated_at, deals=deals)

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
        script_dir = Path(__file__).parent
        output_path = script_dir / f"customer-intel-{date.today().strftime('%Y-%m')}.md"

    output_path.write_text(report, encoding="utf-8")
    print(f"Report saved: {output_path}", file=sys.stderr)
    print(str(output_path))


if __name__ == "__main__":
    main()

