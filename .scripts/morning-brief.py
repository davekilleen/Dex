#!/usr/bin/env python3
"""
morning-brief.py -- One daily note that joins every signal Dex already collects.

Sources (all local-first; no live Salesforce calls):
  - .scripts/salesforce-data/opportunities.json   pipeline needing attention
  - .scripts/salesforce-data/quotes.json          quotes expiring soon
  - .scripts/salesforce-data/case_snapshot.json   open service cases
  - Inbox/Alerts/case-alert-YYYY-MM-DD.md         today's case diff (if any)
  - .scripts/customer-intel/eda-data/*.json       lease/replacement radar
  - Planning/Key_Accounts_H2-2026.md              Tier-1 focus accounts
  - Planning/Tasks.md                             next tasks
  - mam-email-triage worker (optional, HTTP)      urgent + awaiting-reply emails

Output: Inbox/Daily_Brief/YYYY-MM-DD.md
Prints a "BRIEF: ..." summary line for the PowerShell wrapper's toast.

Usage:
  python .scripts/morning-brief.py            # write today's brief
  python .scripts/morning-brief.py --stdout   # print instead of writing
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import sflib

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

VAULT = Path(os.environ.get("VAULT_PATH", Path(__file__).resolve().parent.parent))
SF_DIR = VAULT / ".scripts" / "salesforce-data"
EDA_DIR = VAULT / ".scripts" / "customer-intel" / "eda-data"
OUT_DIR = VAULT / "Inbox" / "Daily_Brief"
TODAY = date.today()

# Tunables
QUOTE_EXPIRY_DAYS = 14      # surface quotes expiring within this window
CLOSE_DATE_DAYS = 21        # surface opps closing within this window
STALE_ACTIVITY_DAYS = 14    # advanced-stage opps untouched this long need a touch
LEASE_RADAR_DAYS = 180      # surface leases/usage ends within this window
ADVANCED_STAGES = {"Negotiation", "Buying", "Favorable", "Active Project", "Quoting"}
DEAD_QUOTE_STATUSES = {"Accepted", "Denied", "Rejected", "Cancelled", "Expired"}


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


MOJIBAKE = {"â€”": "—", "â€“": "–", "â€™": "'", "â€œ": '"', "â€\x9d": '"', "Â": ""}

def fix_text(s):
    """Repair common UTF-8-as-latin1 mojibake that comes through from Salesforce."""
    if not s:
        return s
    for bad, good in MOJIBAKE.items():
        s = s.replace(bad, good)
    return s


def load_dotenv():
    env_path = VAULT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ── Sections ──────────────────────────────────────────────────────────────────

def sec_freshness():
    age = sflib.cache_age_days(VAULT)
    if age is None:
        return ["> ⚠️ **No Salesforce cache found** — run `.scripts/automation/run-sf-sync.ps1`.", ""], True
    if age > 8:
        return [f"> ⚠️ **Salesforce cache is {age:.0f} days old** — numbers below may be stale. "
                "Run `.scripts/automation/run-sf-sync.ps1`.", ""], True
    return [f"*Salesforce data as of {age:.1f} day(s) ago. EDA radar from latest scrape.*", ""], False


def sec_cases():
    lines = [f"## 🔧 Service Cases", ""]
    alert_file = VAULT / "Inbox" / "Alerts" / f"case-alert-{TODAY.isoformat()}.md"
    snapshot = load_json(SF_DIR / "case_snapshot.json", {})
    n_alert = 0
    if alert_file.exists():
        body = alert_file.read_text(encoding="utf-8")
        # embed everything below the title line
        content = "\n".join(body.splitlines()[1:]).strip()
        lines.append(content)
        lines.append("")
        n_alert = body.count("| 0")  # rough; summary comes from counts below
    else:
        lines.append("No new or changed cases today.")
        lines.append("")
    if snapshot:
        oldest = min(snapshot.values(), key=lambda c: c.get("last_modified") or "9999")
        lines.append(f"*{len(snapshot)} open case(s) total. Longest-stale: "
                     f"{oldest.get('account')} — {oldest.get('subject')}.*")
        lines.append("")
    return lines, len(snapshot), 1 if alert_file.exists() else 0


def last_touch_map():
    """Latest activity date per WhatId, computed from the tasks cache.

    Opportunity.LastActivityDate is unreliable in the pull (often null), so we
    derive the real last touch from Task records instead.
    """
    touched, acct_touched = {}, {}
    for t in load_json(SF_DIR / "tasks.json"):
        d = parse_d(t.get("ActivityDate")) or parse_d(t.get("LastModifiedDate"))
        if not d:
            continue
        wid, aid = t.get("WhatId"), t.get("AccountId")
        if wid and (wid not in touched or d > touched[wid]):
            touched[wid] = d
        if aid and (aid not in acct_touched or d > acct_touched[aid]):
            acct_touched[aid] = d
    return touched, acct_touched


def sec_pipeline():
    opps = [o for o in load_json(SF_DIR / "opportunities.json") if not o.get("IsClosed")]
    touched, acct_touched = last_touch_map()
    closing, stale = [], []
    for o in opps:
        cd = parse_d(o.get("CloseDate"))
        la = max(filter(None, [parse_d(o.get("LastActivityDate")),
                               touched.get(o.get("Id")),
                               acct_touched.get(o.get("AccountId"))]), default=None)
        amt = o.get("Amount") or 0
        stage = o.get("StageName") or ""
        acct = (o.get("Account") or {}).get("Name") or "—"
        row = {"acct": acct, "name": o.get("Name", ""), "stage": stage, "amt": amt,
               "close": cd, "last": la, "next": fix_text((o.get("NextStep") or "").strip())}
        if cd and TODAY <= cd <= TODAY + timedelta(days=CLOSE_DATE_DAYS):
            closing.append(row)
        elif stage in ADVANCED_STAGES and (la is None or (TODAY - la).days > STALE_ACTIVITY_DAYS):
            stale.append(row)
    closing.sort(key=lambda r: (r["close"], -r["amt"]))
    stale.sort(key=lambda r: -r["amt"])  # biggest neglected deals first

    lines = ["## 📈 Pipeline Needing Attention", ""]
    if closing:
        lines += [f"**Closing within {CLOSE_DATE_DAYS} days:**", "",
                  "| Account | Opportunity | Stage | Amount | Close | Next step |",
                  "|---------|-------------|-------|--------|-------|-----------|"]
        for r in closing[:10]:
            lines.append(f"| {r['acct']} | {r['name']} | {r['stage']} | {fmt_money(r['amt'])} "
                         f"| {r['close']} | {r['next'] or '—'} |")
        lines.append("")
    if stale:
        lines += [f"**Advanced stage, no activity in {STALE_ACTIVITY_DAYS}+ days "
                  f"(top 10 by amount, {len(stale)} total):**", "",
                  "| Account | Opportunity | Stage | Amount | Last activity | Next step |",
                  "|---------|-------------|-------|--------|---------------|-----------|"]
        for r in stale[:10]:
            last = r["last"].isoformat() if r["last"] else "never"
            lines.append(f"| {r['acct']} | {r['name']} | {r['stage']} | {fmt_money(r['amt'])} "
                         f"| {last} | {r['next'] or '—'} |")
        lines.append("")
    if not closing and not stale:
        lines += ["Nothing urgent — no opps closing soon or going stale.", ""]
    return lines, len(closing), len(stale)


def sec_quotes():
    quotes = load_json(SF_DIR / "quotes.json")
    expiring = []
    for q in quotes:
        if (q.get("Status") or "") in DEAD_QUOTE_STATUSES:
            continue
        ed = parse_d(q.get("ExpirationDate"))
        if ed and TODAY <= ed <= TODAY + timedelta(days=QUOTE_EXPIRY_DAYS):
            expiring.append((ed, q))
    expiring.sort(key=lambda t: t[0])
    lines = []
    if expiring:
        lines += [f"## 💰 Quotes Expiring Within {QUOTE_EXPIRY_DAYS} Days", "",
                  "| Quote | Account | Total | Expires | Status |",
                  "|-------|---------|-------|---------|--------|"]
        for ed, q in expiring[:10]:
            acct = (q.get("Account") or {}).get("Name") or "—"
            lines.append(f"| {q.get('QuoteNumber')} — {q.get('Name')} | {acct} "
                         f"| {fmt_money(q.get('GrandTotal'))} | {ed} | {q.get('Status')} |")
        lines.append("")
    return lines, len(expiring)


def sec_lease_radar():
    """Assets whose usage/lease end lands within the radar window (recomputed today)."""
    reports = sorted(EDA_DIR.glob("*eda-report*.json")) if EDA_DIR.exists() else []
    if not reports:
        return [], 0
    assets = load_json(reports[-1], {}).get("assets", [])
    hot = []
    for a in assets:
        end = parse_d(a.get("usage_end_date"))
        if not end:
            continue
        days = (end - TODAY).days
        if -30 <= days <= LEASE_RADAR_DAYS:  # include just-lapsed ones too
            label = f"{a.get('builder') or a.get('ucc_vendor') or ''} {a.get('model') or ''}".strip() or a.get("name", "")
            hot.append((days, a.get("account", "—"), label, a.get("machine_type") or ""))
    hot.sort(key=lambda t: t[0])
    lines = []
    if hot:
        lines += [f"## ⏳ Lease / Usage-End Radar (next {LEASE_RADAR_DAYS} days)", "",
                  "| Account | Equipment | Type | Days to end |",
                  "|---------|-----------|------|-------------|"]
        for days, acct, label, mt in hot[:12]:
            flag = "**OVERDUE**" if days < 0 else ("🔴" if days <= 90 else "🟡")
            lines.append(f"| {acct} | {label} | {mt} | {flag} {days} |")
        lines += ["", "*Verify every expiry against Salesforce before acting (Date Accuracy Protocol).*", ""]
    return lines, len(hot)


def sec_key_accounts():
    ka = VAULT / "Planning" / "Key_Accounts_H2-2026.md"
    if not ka.exists():
        return [], 0
    text = ka.read_text(encoding="utf-8")
    m = re.search(r"## Tier 1[^\n]*\n(.*?)(?=\n## |\Z)", text, re.S)
    if not m:
        return [], 0
    rows = [l for l in m.group(1).splitlines() if l.startswith("| ") and not l.startswith("| #") and "---" not in l]
    lines = []
    if rows:
        lines += ["## 🎯 Tier-1 Focus (from Key Accounts)", ""]
        for row in rows[:3]:
            cells = [c.strip() for c in row.strip("|").split("|")]
            if len(cells) >= 7:
                acct = re.sub(r"\*\*", "", cells[1])
                lines.append(f"- **{acct}** — {cells[3]} → *{cells[6]}*")
        lines += ["", "*Full list: [Key Accounts](../../Planning/Key_Accounts_H2-2026.md)*", ""]
    return lines, min(len(rows), 3)


def sec_emails():
    """Urgent inbound + sent-awaiting-reply, from the email-triage worker. Optional."""
    load_dotenv()
    base = os.environ.get("EMAIL_TRIAGE_URL", "https://mam-email-triage.cbarsanti.workers.dev")
    key = os.environ.get("EMAIL_TRIAGE_KEY", "")

    def get(params):
        url = base + "/emails?" + urllib.parse.urlencode(params)
        headers = {"User-Agent": "dex-morning-brief/1.0"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    lines, n = [], 0
    try:
        urgent = (get({"label": "urgent", "status": "new", "limit": 10}) or {}).get("emails", [])
        awaiting = (get({"direction": "sent", "reply_status": "awaiting_reply", "limit": 100}) or {}).get("emails", [])
        # only nag about sent mail older than 3 days with no reply
        cutoff = (TODAY - timedelta(days=3)).isoformat()
        awaiting = [e for e in awaiting if (e.get("received_at") or e.get("sent_at") or "9999") <= cutoff]
        n = len(urgent) + len(awaiting)
        if urgent:
            lines += ["**Urgent inbound:**"]
            for e in urgent[:5]:
                lines.append(f"- {e.get('from_name') or e.get('from_address')} — {e.get('subject')}")
            lines.append("")
        if awaiting:
            lines += [f"**Sent, awaiting reply 3+ days ({len(awaiting)}):**"]
            for e in awaiting[:8]:
                to = e.get("to_address") or e.get("account") or "—"
                lines.append(f"- {to} — {e.get('subject')}")
            lines.append("")
        if lines:
            lines = ["## 📧 Email Follow-Ups", ""] + lines
    except Exception as e:
        lines = ["## 📧 Email Follow-Ups", "",
                 f"*Email triage unavailable ({e}) — skipped. "
                 "If this persists, the EMAIL_TRIAGE_KEY in .env/.mcp.json may no longer match "
                 "the deployed worker secret (`wrangler secret put API_KEY` in extensions/mam-email-triage).*", ""]
    return lines, n


def sec_tasks():
    tf = VAULT / "Planning" / "Tasks.md"
    if not tf.exists():
        return [], 0
    open_tasks = []
    for line in tf.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*- \[ \] \*\*(.+?)\*\*", line)
        if m:
            open_tasks.append(m.group(1))
    lines = []
    if open_tasks:
        lines += [f"## ✅ Open Tasks ({len(open_tasks)})", ""]
        for t in open_tasks[:8]:
            lines.append(f"- {t}")
        if len(open_tasks) > 8:
            lines.append(f"- *…and {len(open_tasks) - 8} more in [Tasks](../../Planning/Tasks.md)*")
        lines.append("")
    return lines, len(open_tasks)


# ── Assemble ──────────────────────────────────────────────────────────────────

def build():
    fresh_lines, stale_warn = sec_freshness()
    case_lines, n_open_cases, n_case_alerts = sec_cases()
    pipe_lines, n_closing, n_stale = sec_pipeline()
    quote_lines, n_quotes = sec_quotes()
    lease_lines, n_leases = sec_lease_radar()
    ka_lines, n_ka = sec_key_accounts()
    email_lines, n_emails = sec_emails()
    task_lines, n_tasks = sec_tasks()

    L = [f"# Morning Brief — {TODAY.strftime('%A, %B %d, %Y')}", ""]
    L += fresh_lines
    L += ka_lines
    L += pipe_lines
    L += quote_lines
    L += lease_lines
    L += case_lines
    L += email_lines
    L += task_lines
    L += ["---", "",
          "*Calendar and meeting prep: run `/daily-plan`. Account deep-dive before a visit: `/customer-intel [account]`.*",
          "", f"*Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} by `morning-brief.py`.*"]

    bits = []
    if n_closing:
        bits.append(f"{n_closing} closing soon")
    if n_stale:
        bits.append(f"{n_stale} stale opp(s), top 10 in brief")
    if n_quotes:
        bits.append(f"{n_quotes} quote(s) expiring")
    if n_leases:
        bits.append(f"{n_leases} lease(s) on radar")
    if n_emails:
        bits.append(f"{n_emails} email follow-up(s)")
    summary = "BRIEF: " + (", ".join(bits) if bits else "quiet morning — nothing urgent")
    return "\n".join(L) + "\n", summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()
    report, summary = build()
    if args.stdout:
        print(report)
    else:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        out = OUT_DIR / f"{TODAY.isoformat()}.md"
        out.write_text(report, encoding="utf-8")
        print(f"Wrote {out}")
    print(summary)


if __name__ == "__main__":
    main()
