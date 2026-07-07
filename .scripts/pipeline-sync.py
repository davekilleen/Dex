#!/usr/bin/env python3
"""
pipeline-sync.py -- Deterministic pipeline sync from the local Salesforce cache.

Agentic-OS pattern: this script does the gathering/diffing/writing for zero tokens.
AI only handles the judgment layer (quote file downloads via MCP, narrative review).

Reads .scripts/salesforce-data/ (produced by sf-pull-sync.py) and:
  - creates project pages for open opps with no page (Projects/{Account}/{Opp}.md)
  - creates/updates account hub pages
  - updates header fields (stage/amount/close date/probability/next step) on existing pages
  - refreshes the Quotes table (metadata only -- files are the AI's job)
  - fills placeholder Key Contacts tables from account contacts
  - flags archive candidates (page exists but opp is closed)
  - prints a summary table + a DOWNLOAD-LIST of quotes needing file pulls

Never touches: Activity Log, Notes, Decisions, Correspondence sections.

Usage:
  python .scripts/pipeline-sync.py                 # full sync
  python .scripts/pipeline-sync.py --filter Acme   # only opps/accounts matching
  python .scripts/pipeline-sync.py --dry-run       # report without writing

Sentinels: STALE_CACHE (>8 days), NO_CACHE.
"""

import argparse, json, re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime, timedelta
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
DATA = VAULT / ".scripts" / "salesforce-data"
PROJECTS = VAULT / "Projects"

DOWNLOAD_STAGES = {"Favorable", "Negotiation", "Buying"}
SKIP_STAGES_CLOSED = True  # closed opps never get pages created

def load(name):
    p = DATA / f"{name}.json"
    if not p.exists():
        print(f"NO_CACHE: {p} missing. Run: python .scripts/sf-pull-sync.py")
        sys.exit(2)
    return json.loads(p.read_text(encoding="utf-8"))

def sanitize(name):
    return re.sub(r'[<>:"/\\|?*]', '', (name or "").replace("&", "and")).strip().rstrip(". ")

def fmt_amount(a):
    return f"${a:,.2f}" if a is not None else "TBD"

def acct_name(o):
    return (o.get("Account") or {}).get("Name") or "Unknown"

def vendor(o):
    v = o.get("Vendor__r")
    return (v or {}).get("Name") if v else None

def wiki(name):
    return f"[[{sanitize(name).replace(' ', '_')}|{name}]]"

def find_pages_by_sfid():
    """Map sf_opportunity_id -> Path for all project pages."""
    out = {}
    for md in PROJECTS.rglob("*.md"):
        try:
            head = md.read_text(encoding="utf-8", errors="ignore")[:400]
        except OSError:
            continue
        m = re.search(r"^sf_opportunity_id:\s*(\S+)", head, re.M)
        if m and m.group(1) not in ("pending-sync",):
            out[m.group(1)] = md
    return out

def page_body(o, quotes, contacts):
    now = datetime.now().isoformat(timespec="seconds")
    an = acct_name(o)
    return f"""---
sf_opportunity_id: {o['Id']}
sf_account_id: {o.get('AccountId', '')}
sf_last_synced: {now}
---

# {o['Name']}

**Account:** {wiki(an)}
**Stage:** {o.get('StageName', '—')}
**Amount:** {fmt_amount(o.get('Amount'))}
**Close Date:** {o.get('CloseDate') or 'TBD'}
**Probability:** {int(o['Probability'])if o.get('Probability') is not None else '—'}%
**Owner:** Chris Barsanti
**Vendor:** {vendor(o) or '—'}
**Lead Source:** {o.get('LeadSource') or '—'}

## Next Steps

{o.get('NextStep') or '— TBD —'}

## Key Contacts

{contacts_table(contacts)}

## Quotes

{quotes_table(quotes)}

## Correspondence & Files

_Link emails (from Retool email MCP) and OneDrive documents here._

-

## Activity Log

_Add entries as `- **YYYY-MM-DD** — Call/Meeting/Email/Note: summary [dex]` to sync to Salesforce._

## Decisions

-

## Notes

-
"""

def contacts_table(contacts):
    if not contacts:
        return "| Name | Role | Title |\n|------|------|-------|\n| _No contacts linked in Salesforce_ | | |"
    rows = "\n".join(
        f"| {wiki((c.get('FirstName') or '') + ' ' + (c.get('LastName') or ''))} | — | {c.get('Title') or '—'} |"
        for c in contacts[:6])
    return "| Name | Role | Title |\n|------|------|-------|\n" + rows

def quotes_table(quotes):
    if not quotes:
        return "| Quote # | Status | Total | Expiration | File |\n|---------|--------|-------|------------|------|\n| _No quotes in Salesforce_ | | | | |"
    rows = "\n".join(
        f"| {q.get('QuoteNumber','—')} | {q.get('Status','—')} | {fmt_amount(q.get('GrandTotal'))} | {q.get('ExpirationDate') or '—'} | |"
        for q in quotes)
    return "| Quote # | Status | Total | Expiration | File |\n|---------|--------|-------|------------|------|\n" + rows

HEADER_FIELDS = ["Stage", "Amount", "Close Date", "Probability", "Vendor", "Lead Source"]

def update_page(path, o, quotes, dry=False):
    """Update header fields + Quotes table + sf_last_synced. Returns list of changed fields."""
    text = path.read_text(encoding="utf-8")
    orig = text
    changed = []
    new_vals = {
        "Stage": o.get("StageName", "—"),
        "Amount": fmt_amount(o.get("Amount")),
        "Close Date": o.get("CloseDate") or "TBD",
        "Probability": f"{int(o['Probability'])}%" if o.get("Probability") is not None else "—",
        "Vendor": vendor(o) or "—",
        "Lead Source": o.get("LeadSource") or "—",
    }
    for field, val in new_vals.items():
        pat = re.compile(rf"^(\*\*{re.escape(field)}:\*\*) (.*)$", re.M)
        m = pat.search(text)
        if m and m.group(2).strip() != str(val).strip():
            text = pat.sub(rf"\1 {val}", text, count=1)
            changed.append(f"{field.lower()}: {m.group(2).strip()} → {val}")
    # Next Steps: only replace if still placeholder
    ns = o.get("NextStep")
    if ns:
        pat = re.compile(r"(## Next Steps\n\n)(— TBD —|—)\n")
        if pat.search(text):
            text = pat.sub(rf"\g<1>{ns}\n", text, count=1)
            changed.append("next steps filled")
    # Quotes table: regenerate section body between '## Quotes' and next '##'
    qt = quotes_table(quotes)
    pat = re.compile(r"(## Quotes\n\n)(.*?)(\n\n## )", re.S)
    m = pat.search(text)
    if m:
        # preserve any file links already recorded in the File column
        existing_links = dict(re.findall(r"^\| (\S+) \|.*\| (\[\[[^\]]+\]\]|\S*\.pdf\S*) \|$", m.group(2), re.M))
        if existing_links:
            qt = "\n".join(
                re.sub(r"\| $", f"| {existing_links[line.split(' | ')[0].strip('| ')]} ", line)
                if line.split(" | ")[0].strip("| ") in existing_links else line
                for line in qt.split("\n"))
        if m.group(2).strip() != qt.strip():
            text = pat.sub(lambda mm: mm.group(1) + qt + mm.group(3), text, count=1)
            changed.append("quotes table refreshed")
    if changed:
        text = re.sub(r"^sf_last_synced: .*$",
                      f"sf_last_synced: {datetime.now().isoformat(timespec='seconds')}", text, count=1, flags=re.M)
        if text != orig and not dry:
            path.write_text(text, encoding="utf-8")
    return changed

def hub_page(account, opps):
    rows = "\n".join(
        f"| [[{sanitize(o['Name'])}]] | {o.get('StageName','—')} | {fmt_amount(o.get('Amount'))} | {o.get('CloseDate') or 'TBD'} | {vendor(o) or ''} |"
        for o in opps)
    return f"""# {account}

## Open Opportunities ({len(opps)})

| Opportunity | Stage | Amount | Close Date | Vendor |
|-------------|-------|--------|------------|--------|
{rows}

## Contacts

_See [[People/External]] for contact pages._

## Notes

-
"""

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--filter", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    manifest = load("manifest")
    synced = manifest.get("synced_at", {}).get("opportunities")
    if synced:
        age = datetime.now().astimezone() - datetime.fromisoformat(synced)
        if age > timedelta(days=8):
            print(f"STALE_CACHE: opportunities last synced {synced} ({age.days} days ago). "
                  f"Run .scripts/automation/run-sf-sync.ps1 first.")

    opps = load("opportunities")
    quotes = load("quotes")
    contacts = load("contacts")

    by_opp_quotes = {}
    for q in quotes:
        by_opp_quotes.setdefault(q.get("OpportunityId"), []).append(q)
    by_acct_contacts = {}
    for c in contacts:
        by_acct_contacts.setdefault(c.get("AccountId"), []).append(c)

    open_opps = [o for o in opps if not o.get("IsClosed")]
    if args.filter:
        f = args.filter.lower()
        open_opps = [o for o in open_opps if f in o["Name"].lower() or f in acct_name(o).lower()]

    pages = find_pages_by_sfid()
    created, updated, unchanged, download_list = [], [], [], []

    for o in open_opps:
        an = sanitize(acct_name(o))
        oq = sorted(by_opp_quotes.get(o["Id"], []), key=lambda q: q.get("QuoteNumber") or "")
        page = pages.get(o["Id"])
        if page is None:
            folder = PROJECTS / an
            slug = sanitize(o["Name"])
            v = vendor(o)
            fname = f"{slug} - {sanitize(v)}.md" if v and sanitize(v) not in slug else f"{slug}.md"
            path = folder / fname
            if not args.dry_run:
                folder.mkdir(parents=True, exist_ok=True)
                path.write_text(page_body(o, oq, by_acct_contacts.get(o.get("AccountId"), [])), encoding="utf-8")
            created.append((o, path))
        else:
            ch = update_page(page, o, oq, dry=args.dry_run)
            (updated if ch else unchanged).append((o, page, ch))
        if o.get("StageName") in DOWNLOAD_STAGES and oq:
            for q in oq:
                download_list.append((acct_name(o), o["Name"], q.get("QuoteNumber"), q.get("Id")))

    # hub pages for accounts with created/changed opps
    touched_accts = {acct_name(o) for o, *_ in created}
    if not args.dry_run:
        by_acct_open = {}
        for o in open_opps:
            by_acct_open.setdefault(acct_name(o), []).append(o)
        for an in touched_accts:
            hub = PROJECTS / sanitize(an) / f"{sanitize(an)}.md"
            if not hub.exists():
                hub.write_text(hub_page(an, by_acct_open.get(an, [])), encoding="utf-8")

    # archive candidates: pages whose opp is now closed
    closed_ids = {o["Id"]: o for o in opps if o.get("IsClosed")}
    archive = [(closed_ids[i], p) for i, p in pages.items()
               if i in closed_ids and "Archive" not in str(p)]

    print("### Pipeline Sync Complete" + (" (dry run)" if args.dry_run else ""))
    print()
    print("| Opportunity | Account | Stage | Action |")
    print("|-------------|---------|-------|--------|")
    for o, p in created:
        print(f"| {o['Name']} | {acct_name(o)} | {o.get('StageName')} | Created |")
    for o, p, ch in updated:
        print(f"| {o['Name']} | {acct_name(o)} | {o.get('StageName')} | Updated ({'; '.join(ch)}) |")
    for o, p in archive[:20]:
        print(f"| {o['Name']} | {acct_name(o)} | {o.get('StageName')} | Archive candidate |")
    print()
    print(f"**Created:** {len(created)} | **Updated:** {len(updated)} | "
          f"**Unchanged:** {len(unchanged)} | **Archive candidates:** {len(archive)}")
    if download_list:
        print()
        print("DOWNLOAD-LIST (quote files to pull via sf_get_quotes/sf_download_quote_file):")
        for an, on, qn, qid in download_list:
            print(f"- {an} / {on} — Quote {qn} ({qid})")

if __name__ == "__main__":
    main()
