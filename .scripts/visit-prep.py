#!/usr/bin/env python3
"""
visit-prep.py -- Build a one-page field visit dossier for an account.

Deterministic data layer for the /visit-prep skill: joins every local source Dex
already maintains into a printable/phone-readable packet. No AI, no live
Salesforce calls -- the skill layer adds conversation strategy on top.

Sources (all local):
  - .scripts/salesforce-data/*.json                 accounts, contacts, opps, quotes,
                                                    tasks, events, case snapshot
  - .scripts/customer-intel/eda-data/*              equipment ages, lease ends, competitors
  - Planning/Key_Accounts_H2-2026.md                tier + score + "why now"
  - People/Companies/<Account>.md                   existing vault intelligence (path only)

Usage:
  python .scripts/visit-prep.py "Galaxy Manufacturing"          # write packet
  python .scripts/visit-prep.py "Galaxy" --stdout               # print instead
  python .scripts/visit-prep.py --match "gal"                   # list matching accounts
  python .scripts/visit-prep.py "A" "B" "C"                     # batch (route day)

Output: Inbox/Visit_Prep/YYYY-MM-DD - <Account>.md
"""

import argparse
import csv
import io
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import sflib

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VAULT = Path(os.environ.get("VAULT_PATH", Path(__file__).resolve().parent.parent))
SF_DIR = VAULT / ".scripts" / "salesforce-data"
EDA_DIR = VAULT / ".scripts" / "customer-intel" / "eda-data"
OUT_DIR = VAULT / "Inbox" / "Visit_Prep"
KEY_ACCOUNTS = VAULT / "Planning" / "Key_Accounts_H2-2026.md"
TODAY = date.today()

# Equipment Lifecycle Clock -- replacement window LOW bound, years
# (kept in sync with score-key-accounts.py / customer-intel SKILL.md).
LIFECYCLE_LOW = {
    "co2 laser": 8, "fiber laser": 10, "press brake": 15, "turret": 15,
    "turning": 10, "vmc": 10, "plasma": 8, "tube": 10, "laser": 9, "saw": 12,
}

MOJIBAKE = {"â€”": "—", "â€“": "–", "â€™": "'", "â€œ": '"', "â€\x9d": '"', "Â": ""}


def fix_text(s):
    if not s:
        return s
    for bad, good in MOJIBAKE.items():
        s = s.replace(bad, good)
    return s


def clean_activity_desc(s):
    """Flatten logged-email descriptions: drop To/CC/BCC/Subject headers, keep the body."""
    if not s:
        return ""
    m = re.search(r"Body:\s*(.+)", s, re.S)
    if m:
        s = m.group(1)
    s = re.sub(r"^(To|CC|BCC|Attachment|Subject):.*$", "", s, flags=re.M)
    return re.sub(r"\s+", " ", s).strip()


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else []


def parse_d(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def fmt_money(v):
    return f"${v:,.0f}" if isinstance(v, (int, float)) else "—"


def norm(s):
    """Loose normalization for account-name matching."""
    s = (s or "").lower()
    s = re.sub(r"[,.'’]", " ", s)
    s = re.sub(r"\b(inc|llc|ltd|corp|corporation|company|co|the)\b", " ", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def lifecycle_low(machine_type):
    mt = (machine_type or "").lower()
    for key, low in LIFECYCLE_LOW.items():
        if key in mt:
            return low
    return 12


# ── Account resolution ────────────────────────────────────────────────────────

def find_account(query, accounts):
    """Exact-normalized match first, then substring, then token overlap."""
    nq = norm(query)
    by_norm = {norm(a["Name"]): a for a in accounts}
    if nq in by_norm:
        return by_norm[nq], []
    subs = [a for a in accounts if nq in norm(a["Name"])]
    if len(subs) == 1:
        return subs[0], []
    if len(subs) > 1:
        return None, subs
    qtok = set(nq.split())
    scored = []
    for a in accounts:
        overlap = len(qtok & set(norm(a["Name"]).split()))
        if overlap:
            scored.append((overlap, a))
    scored.sort(key=lambda t: -t[0])
    if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
        return scored[0][1], []
    return None, [a for _, a in scored[:8]]


# ── Data assembly ─────────────────────────────────────────────────────────────

def gather(acct):
    aid = acct["Id"]
    aname = acct["Name"]

    contacts = [c for c in load_json(SF_DIR / "contacts.json") if c.get("AccountId") == aid]

    opps = [o for o in load_json(SF_DIR / "opportunities.json") if o.get("AccountId") == aid]
    open_opps = sorted([o for o in opps if not o.get("IsClosed")],
                       key=lambda o: -(o.get("Amount") or 0))
    won = sorted([o for o in opps if o.get("IsWon")],
                 key=lambda o: o.get("CloseDate") or "", reverse=True)
    lost = [o for o in opps if o.get("IsClosed") and not o.get("IsWon")]

    quotes = [q for q in load_json(SF_DIR / "quotes.json") if q.get("AccountId") == aid]
    open_quotes = sorted([q for q in quotes if (q.get("Status") or "")
                          not in {"Accepted", "Denied", "Rejected", "Cancelled", "Expired"}],
                         key=lambda q: q.get("ExpirationDate") or "9999", )

    activities = []
    for src in ("tasks.json", "events.json"):
        for t in load_json(SF_DIR / src):
            if t.get("AccountId") == aid and t.get("ActivityDate"):
                activities.append({
                    "date": t["ActivityDate"][:10],
                    "type": t.get("Type") or ("Event" if src == "events.json" else "Task"),
                    "subject": fix_text(t.get("Subject") or ""),
                    "who": ((t.get("Who") or {}) or {}).get("Name") or "",
                    "owner": ((t.get("Owner") or {}) or {}).get("Name") or "",
                    "desc": clean_activity_desc(fix_text(t.get("Description") or "")),
                })
    activities.sort(key=lambda a: a["date"], reverse=True)
    # Collapse email-thread noise: keep only the newest entry per subject.
    seen_subj, deduped = set(), []
    for act in activities:
        key = re.sub(r"^((email|call|re|fwd?):\s*)+", "", act["subject"].lower()).strip()
        if key in seen_subj:
            continue
        seen_subj.add(key)
        deduped.append(act)
    activities = deduped

    cases = [c for c in load_json(SF_DIR / "case_snapshot.json", {}).values()
             if norm(c.get("account", "")) and norm(c.get("account", "")) in norm(aname)
             or norm(aname) in norm(c.get("account", "") or "zzz")]

    # Equipment: EDA report (joined by real account_id) + owned-plasma CSV.
    equipment = []
    reports = sorted(EDA_DIR.glob("*eda-report*.json")) if EDA_DIR.exists() else []
    if reports:
        for a in load_json(reports[-1], {}).get("assets", []):
            if a.get("account_id") != aid:
                continue
            inst = parse_d(a.get("install_date"))
            age = round((TODAY - inst).days / 365.25, 1) if inst else None
            end = parse_d(a.get("usage_end_date"))
            equipment.append({
                "label": " ".join(filter(None, [a.get("builder") or a.get("ucc_vendor"),
                                                a.get("model")])) or a.get("name", ""),
                "type": a.get("machine_type") or "",
                "age": age,
                "lease_end": end.isoformat() if end else None,
                "days_to_end": (end - TODAY).days if end else None,
                "competitor": bool(a.get("is_competitor")),
            })
    csv_path = EDA_DIR / "owned-accounts-plasma.csv"
    if csv_path.exists():
        for r in csv.DictReader(io.open(csv_path, encoding="utf-8")):
            if r.get("account_id", "").strip() != aid:
                continue
            year = r.get("year", "").strip()
            age = (TODAY.year - int(year)) if year.isdigit() else None
            label = f"{(r.get('builder') or '').strip()} {(r.get('model') or '').strip()}".strip()
            if not any(e["label"] == label for e in equipment):
                equipment.append({"label": label or "Plasma", "type": "Plasma",
                                  "age": age, "lease_end": None, "days_to_end": None,
                                  "competitor": False})

    # Key-account tier row.
    tier_line = None
    if KEY_ACCOUNTS.exists():
        for line in KEY_ACCOUNTS.read_text(encoding="utf-8").splitlines():
            if line.startswith("| ") and norm(aname)[:20] in norm(line):
                cells = [c.strip() for c in line.strip("|").split("|")]
                if len(cells) >= 7:
                    tier_line = {"score": cells[2], "why": cells[3], "action": cells[6]}
                break

    # Existing vault company page (for the skill to read/extend).
    stem_guess = re.sub(r"[^A-Za-z0-9]+", "_", aname).strip("_")
    company_page = None
    companies_dir = VAULT / "People" / "Companies"
    if companies_dir.exists():
        for p in companies_dir.glob("*.md"):
            if norm(p.stem.replace("_", " ")) == norm(aname) or \
               norm(aname) in norm(p.stem.replace("_", " ")):
                company_page = p
                break

    return {
        "account": acct, "contacts": contacts, "open_opps": open_opps, "won": won,
        "lost_count": len(lost), "open_quotes": open_quotes, "activities": activities,
        "cases": cases, "equipment": equipment, "tier": tier_line,
        "company_page": company_page, "page_stem": stem_guess,
    }


# ── Data-driven talking points ────────────────────────────────────────────────

def talking_points(d):
    pts = []
    for e in d["equipment"]:
        if e["days_to_end"] is not None and e["days_to_end"] <= 365:
            when = f"{e['days_to_end']}d" if e["days_to_end"] >= 0 else "LAPSED"
            pts.append(f"**Lease trigger:** {e['label']} usage/lease ends {e['lease_end']} ({when}) — freed-up cash flow conversation.")
    for e in d["equipment"]:
        if e["competitor"] and e["age"] and e["age"] >= 5:
            pts.append(f"**Displacement:** competitor {e['label']} on floor, ~{e['age']:.0f}yr old.")
        elif not e["competitor"] and e["age"]:
            low = lifecycle_low(f"{e['label']} {e['type']}")
            if e["age"] >= low:
                pts.append(f"**Replacement window:** {e['label']} is ~{e['age']:.0f}yr old (window opens ~{low}yr for this type).")
    for o in d["open_opps"][:3]:
        nxt = fix_text((o.get("NextStep") or "").strip())
        cd = o.get("CloseDate")
        pts.append(f"**Advance:** {o.get('Name')} ({o.get('StageName')}, {fmt_money(o.get('Amount'))}"
                   + (f", close {cd}" if cd else "") + ")"
                   + (f" — next: {nxt}" if nxt else ""))
    for q in d["open_quotes"][:2]:
        ed = q.get("ExpirationDate")
        if ed:
            pts.append(f"**Quote on the table:** {q.get('QuoteNumber')} {fmt_money(q.get('GrandTotal'))} expires {ed}.")
    for c in d["cases"]:
        pts.append(f"**Service empathy first:** open case {c['case_number']} — {c['subject']} ({c['status']}). Acknowledge before selling.")
    if d["won"]:
        last = d["won"][0]
        pts.append(f"**Relationship anchor:** {len(d['won'])} prior win(s); most recent {last.get('Name')} closed {last.get('CloseDate')}.")
    if not pts:
        pts.append("No hard triggers in the data — relationship visit. Ask about capacity, backlog, and upcoming projects.")
    return pts


# ── Render ────────────────────────────────────────────────────────────────────

def render(d):
    a = d["account"]
    city = ", ".join(filter(None, [a.get("BillingCity"), a.get("BillingState")]))
    addr = ", ".join(filter(None, [a.get("BillingStreet"), a.get("BillingCity"),
                                   a.get("BillingState"), a.get("BillingPostalCode")]))
    L = [f"# Visit Prep — {a['Name']}", ""]
    L.append(f"*Prepared {TODAY.strftime('%A, %B %d, %Y')} · {city or '—'} · {a.get('Phone') or 'no phone on file'}*")
    cache_age = sflib.cache_age_days(VAULT)
    if cache_age is not None and cache_age > 8:
        L.append(f"\n> ⚠️ Salesforce cache is {cache_age:.0f} days old — verify live before committing to numbers.")
    L.append("")

    if d["tier"]:
        L += [f"**Key-account status:** score {d['tier']['score']} — {d['tier']['why']} → *{d['tier']['action']}*", ""]

    L += ["## Why You're Walking In (data-driven)", ""]
    L += [f"- {p}" for p in talking_points(d)]
    L.append("")

    if addr:
        L += ["## Logistics", "", f"- **Address:** {addr}",
              f"- **Industry:** {a.get('Industry') or '—'} · **Type:** {a.get('Type') or '—'}", ""]

    if d["contacts"]:
        L += ["## People", "", "| Name | Title | Phone | Email |", "|------|-------|-------|-------|"]
        for c in d["contacts"][:8]:
            nm = " ".join(filter(None, [c.get("FirstName"), c.get("LastName")]))
            phone = c.get("MobilePhone") or c.get("Phone") or "—"
            L.append(f"| {nm} | {c.get('Title') or '—'} | {phone} | {c.get('Email') or '—'} |")
        L.append("")

    if d["equipment"]:
        L += ["## Equipment Floor (EDA/UCC)", "", "| Equipment | Type | Age | Lease end | Flag |",
              "|-----------|------|-----|-----------|------|"]
        for e in sorted(d["equipment"], key=lambda x: (x["days_to_end"] is None, x["days_to_end"] or 0)):
            age = f"~{e['age']:.0f}yr" if e["age"] else "—"
            end = e["lease_end"] or "—"
            flag = "🏴 competitor" if e["competitor"] else (
                "🔴 expiring" if e["days_to_end"] is not None and e["days_to_end"] <= 180 else "")
            L.append(f"| {e['label']} | {e['type']} | {age} | {end} | {flag} |")
        L += ["", "*Verify expiry dates against Salesforce before quoting (Date Accuracy Protocol).*", ""]

    if d["open_opps"]:
        L += ["## Open Pipeline", "", "| Opportunity | Stage | Amount | Close | Next step |",
              "|-------------|-------|--------|-------|-----------|"]
        for o in d["open_opps"]:
            L.append(f"| {o.get('Name')} | {o.get('StageName')} | {fmt_money(o.get('Amount'))} "
                     f"| {o.get('CloseDate') or '—'} | {fix_text(o.get('NextStep') or '—')} |")
        L.append("")

    if d["open_quotes"]:
        L += ["## Open Quotes", ""]
        for q in d["open_quotes"][:5]:
            L.append(f"- {q.get('QuoteNumber')} — {q.get('Name')} · {fmt_money(q.get('GrandTotal'))} "
                     f"· {q.get('Status')} · expires {q.get('ExpirationDate') or '—'}")
        L.append("")

    if d["cases"]:
        L += ["## Open Service Cases", ""]
        for c in d["cases"]:
            L.append(f"- **{c['case_number']}** {c['subject']} — {c['status']}/{c['priority']}"
                     + (f" (contact: {c['contact']})" if c.get("contact") else ""))
        L.append("")

    hist = f"{len(d['won'])} won"
    if d["lost_count"]:
        hist += f" / {d['lost_count']} lost"
    L += [f"## Recent Activity ({hist} lifetime)", ""]
    for act in d["activities"][:6]:
        who = f" w/ {act['who']}" if act["who"] else ""
        desc = f" — {act['desc'][:140]}" if act["desc"] else ""
        L.append(f"- **{act['date']}** [{act['type']}] {act['subject']}{who}{desc}")
    if not d["activities"]:
        L.append("*No logged activity in the cache window.*")
    L.append("")

    page_rel = f"People/Companies/{d['company_page'].name}" if d["company_page"] else None
    L += ["---", ""]
    if page_rel:
        L.append(f"*Vault intelligence: [[{d['company_page'].stem}]] — read before the visit; log outcome with `/log-meeting`.*")
    else:
        L.append(f"*No company page yet — `/customer-intel {a['Name']}` will create one. Log outcome with `/log-meeting`.*")
    L.append(f"\n*Generated by `visit-prep.py` from the local Salesforce/EDA cache.*")
    return "\n".join(L) + "\n"


def prep_one(query, accounts, stdout=False):
    acct, ambiguous = find_account(query, accounts)
    if not acct:
        if ambiguous:
            print(f"AMBIGUOUS: '{query}' matches multiple accounts:")
            for a in ambiguous:
                print(f"  - {a['Name']} ({a.get('BillingCity') or ''})")
        else:
            print(f"NOT FOUND: no owned account matching '{query}'")
        return None
    packet = render(gather(acct))
    if stdout:
        print(packet)
        return None
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r'[<>:"/\\|?*]', "", acct["Name"]).strip()
    out = OUT_DIR / f"{TODAY.isoformat()} - {safe}.md"
    out.write_text(packet, encoding="utf-8")
    print(f"Wrote {out}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("accounts", nargs="*", help="Account name(s), fuzzy matched")
    ap.add_argument("--match", help="Just list owned accounts matching this string")
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()

    accounts = load_json(SF_DIR / "accounts.json")
    if not accounts:
        print("ERROR: no local Salesforce cache — run .scripts/automation/run-sf-sync.ps1 first.",
              file=sys.stderr)
        sys.exit(1)

    if args.match:
        nq = norm(args.match)
        for a in accounts:
            if nq in norm(a["Name"]):
                print(f"{a['Name']}  ({a.get('BillingCity') or ''}, {a.get('BillingState') or ''})")
        return

    if not args.accounts:
        ap.error("provide at least one account name, or --match")

    for q in args.accounts:
        prep_one(q, accounts, stdout=args.stdout)


if __name__ == "__main__":
    main()
