#!/usr/bin/env python3
"""
score-key-accounts.py -- Rank Chris's owned accounts into a tiered H2 target list.

Merges four LOCAL data sources (no live Salesforce calls -- reads the weekly cache
produced by sf-pull-sync.py plus the EDA equipment scrape) and scores every
Chris-owned account 0-100 using the balanced-mix rubric, then writes a tiered
markdown artifact.

Scope rule (memory: feedback_account_ownership_scope): the account universe is
accounts.json, which sf-pull-sync.py already filters to OwnerId = Chris. EDA market
data is joined onto that universe only -- prospects Chris does not own are not ranked.

Scoring rubric (weights sum to 100):
  - Replacement urgency   35  EDA lease-expiry bucket + equipment age vs lifecycle clock
  - Historic buying       25  closed-won frequency + recency from opportunities
  - Open pipeline         25  open-opp stage weight x amount
  - Competitive displace. 15  aging competitor equipment present

Tiers:
  - Tier 1  open opp AND (advanced stage OR replacement signal)  -> work weekly
  - Tier 2  replacement-due OR historic buyer, no open opp       -> convert to discovery
  - Tier 3  any remaining signal                                 -> relationship / radar

Usage:
  python .scripts/customer-intel/score-key-accounts.py [--top N] [--stdout]
"""

import argparse
import csv
import io
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent.parent
SF_DIR = VAULT / ".scripts" / "salesforce-data"
EDA_DIR = VAULT / ".scripts" / "customer-intel" / "eda-data"
OUT_FILE = VAULT / "Planning" / "Key_Accounts_H2-2026.md"
TODAY = date.today()

# Open-opportunity stage weights (probability of working toward a close this half).
STAGE_WEIGHT = {
    "Negotiation": 1.00,
    "Buying": 1.00,
    "Favorable": 0.85,
    "Active Project": 0.70,
    "Quoting": 0.55,
    "Discovery": 0.35,
}
ADVANCED_STAGES = {"Negotiation", "Buying", "Favorable", "Active Project"}

# Equipment Lifecycle Clock (customer-intel SKILL.md) -- replacement window LOW bound, years.
LIFECYCLE_LOW = {
    "co2 laser": 8, "fiber laser": 10, "press brake": 15, "turret": 15,
    "turning": 10, "vmc": 10, "plasma": 8, "tube": 10, "laser": 9, "saw": 12,
}


# ---------- helpers ----------

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def norm_name(n):
    """Aggressive normalization for fuzzy name joins across data sources."""
    if not n:
        return ""
    n = n.lower()
    n = re.sub(r"[,.]", " ", n)
    n = re.sub(r"\b(inc|llc|ltd|corp|corporation|company|co|the|and|&|mfg|"
              r"manufacturing|industries|enterprises|group|services|division)\b", " ", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    # Merge runs of single-character tokens so dotted initials join their
    # undotted form: "J.R. Steel" -> "j r steel" -> "jr steel" == "JR Steel".
    merged, run = [], []
    for token in n.split():
        if len(token) == 1:
            run.append(token)
        else:
            if run:
                merged.append("".join(run))
                run = []
            merged.append(token)
    if run:
        merged.append("".join(run))
    return " ".join(merged)


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def years_since(d):
    return (TODAY - d).days / 365.25 if d else None


def lifecycle_low(machine_type):
    mt = (machine_type or "").lower()
    for key, low in LIFECYCLE_LOW.items():
        if key in mt:
            return low
    return 12  # generic capital equipment default


def scale(value, lo, hi, weight):
    """Linear-clamp value in [lo, hi] -> [0, weight]."""
    if hi <= lo:
        return 0.0
    return max(0.0, min(1.0, (value - lo) / (hi - lo))) * weight


# ---------- load sources ----------

def build():
    accounts = load_json(SF_DIR / "accounts.json")
    opps = load_json(SF_DIR / "opportunities.json")

    # Account universe (Chris-owned), keyed by Id.
    acct = {}
    name_to_id = {}
    for a in accounts:
        aid = a["Id"]
        acct[aid] = {
            "id": aid,
            "name": a.get("Name", ""),
            "city": a.get("BillingCity") or "",
            "state": a.get("BillingState") or "",
            "last_activity": a.get("LastActivityDate"),
            "open_weighted": 0.0,
            "open_amount": 0.0,
            "open_opps": [],
            "won_count": 0,
            "last_won": None,
            "total_opp_count": 0,
            "equipment": [],     # list of (label, age_years, is_competitor)
            "expiry": [],        # list of (label, days_to_expiry)
        }
        nn = norm_name(a.get("Name", ""))
        if nn:
            name_to_id.setdefault(nn, aid)

    # Opportunities -> open pipeline + historic buying.
    for o in opps:
        aid = o.get("AccountId")
        if aid not in acct:
            continue
        a = acct[aid]
        a["total_opp_count"] += 1
        stage = o.get("StageName")
        amt = o.get("Amount") or 0.0
        if o.get("IsWon"):
            a["won_count"] += 1
            cd = parse_date(o.get("CloseDate"))
            if cd and (a["last_won"] is None or cd > a["last_won"]):
                a["last_won"] = cd
        if not o.get("IsClosed"):
            w = STAGE_WEIGHT.get(stage, 0.3)
            a["open_weighted"] += w * amt
            a["open_amount"] += amt
            a["open_opps"].append({
                "name": o.get("Name", ""), "stage": stage, "amount": amt,
                "vendor": ((o.get("Vendor__r") or {}) or {}).get("Name"),
                "next_step": o.get("NextStep"),
            })

    # EDA owned-plasma CSV -> aging signal joined by real account_id.
    csv_path = EDA_DIR / "owned-accounts-plasma.csv"
    if csv_path.exists():
        for r in csv.DictReader(io.open(csv_path, encoding="utf-8")):
            aid = r.get("account_id", "").strip()
            if aid not in acct:
                continue
            year = r.get("year", "").strip()
            age = (TODAY.year - int(year)) if year.isdigit() else (12 if r.get("aging_pre2021", "").upper() == "YES" else None)
            label = f"{(r.get('builder') or '').strip()} {(r.get('model') or '').strip()}".strip() or "Plasma"
            acct[aid]["equipment"].append((f"{label} plasma" + (f" ({year})" if year else ""), age, False))

    # EDA market report -> equipment age + lease expiry + competitor displacement, joined by name.
    eda_path = EDA_DIR / "plasma-eda-report-2026-06-26.json"
    if eda_path.exists():
        for asset in load_json(eda_path).get("assets", []):
            aid = name_to_id.get(norm_name(asset.get("account", "")))
            if not aid:
                continue
            inst = parse_date(asset.get("install_date"))
            age = years_since(inst)
            mt = asset.get("machine_type") or "Plasma"
            builder = asset.get("builder") or asset.get("ucc_vendor") or ""
            label = f"{builder} {asset.get('model') or ''} {mt}".strip()
            acct[aid]["equipment"].append((label, age, bool(asset.get("is_competitor"))))
            dte = asset.get("days_to_expiry")
            if isinstance(dte, (int, float)) and dte is not None:
                acct[aid]["expiry"].append((label, int(dte)))

    return acct


# ---------- scoring ----------

def score_account(a):
    reasons = []

    # Replacement urgency (35): lease-expiry bucket OR equipment age past lifecycle low.
    urgency = 0.0
    soonest = None
    for label, days in a["expiry"]:
        if soonest is None or days < soonest:
            soonest = days
    if soonest is not None:
        if soonest <= 90:
            urgency = max(urgency, 35); reasons.append(f"lease expires in {soonest}d (CRITICAL)")
        elif soonest <= 180:
            urgency = max(urgency, 28); reasons.append(f"lease expires in {soonest}d (HIGH)")
        elif soonest <= 365:
            urgency = max(urgency, 20); reasons.append(f"lease expires in {soonest}d (MEDIUM)")
    oldest_over = 0.0
    for label, age, is_comp in a["equipment"]:
        if is_comp or age is None:
            continue
        low = lifecycle_low(label)
        over = age - low
        if over > oldest_over:
            oldest_over = over
    if oldest_over > 0:
        u = scale(oldest_over, 0, 8, 30)  # up to 8 yrs past window -> near full
        if u > urgency:
            urgency = u
            reasons.append(f"owned equipment ~{oldest_over:.0f}yr past replacement window")
    replacement_signal = urgency >= 18

    # Historic buying (25): won frequency + recency.
    freq = scale(a["won_count"], 0, 6, 15)
    rec = 0.0
    yl = years_since(a["last_won"])
    if yl is not None:
        rec = scale(3 - yl, 0, 3, 10)  # won within last 3 yrs -> up to 10
        if a["won_count"]:
            reasons.append(f"{a['won_count']} prior win(s), last {yl:.1f}yr ago")
    historic = freq + rec
    historic_buyer = a["won_count"] >= 2 or (yl is not None and yl <= 2)

    # Open pipeline (25): weighted stage x amount, log-ish scaled.
    pipe = scale(a["open_weighted"], 0, 250000, 25)
    if a["open_amount"] > 0:
        stages = ", ".join(sorted({o["stage"] for o in a["open_opps"]}))
        reasons.append(f"${a['open_amount']:,.0f} open ({stages})")

    # Competitive displacement (15): aging competitor equipment.
    comp = 0.0
    for label, age, is_comp in a["equipment"]:
        if is_comp and age is not None:
            comp = max(comp, scale(age, 3, 12, 15))
    if comp > 0:
        reasons.append("aging competitor equipment on site")

    total = urgency + historic + pipe + comp

    # Tiers follow the plan: T1 = any active (open) opp -> work weekly;
    # T2 = no open opp but replacement-due or historic buyer -> convert to discovery;
    # T3 = no open opp, only a mild/competitive signal -> relationship / radar.
    has_open = bool(a["open_opps"])
    strong_replacement = urgency >= 25
    if has_open:
        tier = 1
    elif strong_replacement or historic_buyer:
        tier = 2
    else:
        tier = 3

    a.update(dict(score=round(total, 1), urgency=round(urgency, 1),
                  historic=round(historic, 1), pipe=round(pipe, 1), comp=round(comp, 1),
                  tier=tier, reasons=reasons, soonest=soonest,
                  replacement_signal=replacement_signal))
    return a


def next_action(a):
    if a["tier"] == 1:
        if any(o["stage"] in {"Negotiation", "Buying", "Favorable"} for o in a["open_opps"]):
            return "Close push: confirm config, propose demo/visit, drive to PO"
        return "Advance open opp + book demo/visit on territory day"
    if a["tier"] == 2:
        if a["replacement_signal"]:
            return "Replacement discovery: lead with lease/age trigger, offer demo"
        return "Reactivation: historic buyer, open discovery on current needs"
    return "Quarterly relationship touch / event invite"


def equip_summary(a):
    parts = []
    if a["soonest"] is not None:
        parts.append(f"lease ~{a['soonest']}d")
    aged = [(lbl, age) for (lbl, age, c) in a["equipment"] if not c and age is not None]
    aged.sort(key=lambda x: -x[1])
    if aged:
        lbl, age = aged[0]
        parts.append(f"{lbl} ~{age:.0f}yr")
    comp = [lbl for (lbl, age, c) in a["equipment"] if c]
    if comp:
        parts.append(f"competitor: {comp[0]}")
    return "; ".join(parts) or "-"


# ---------- render ----------

def render(scored, top):
    ranked = sorted(scored, key=lambda a: -a["score"])
    # Select per tier so replacement/radar accounts aren't starved by open-pipeline volume.
    def pick(tier, n, floor):
        return [a for a in ranked if a["tier"] == tier and a["score"] >= floor][:n]
    t1 = pick(1, top, 8)
    t2 = pick(2, 15, 6)
    t3 = pick(3, 12, 5)
    keep = t1 + t2 + t3

    L = []
    L.append("# Key Accounts — H2 2026 (Jul–Dec)")
    L.append("")
    L.append(f"*Generated {TODAY.strftime('%B %d, %Y')} by `score-key-accounts.py`. "
             "Source: local Salesforce cache (Chris-owned scope) + EDA equipment data. "
             "Re-run after each weekly sync to refresh.*")
    L.append("")
    L.append("**Scoring (0–100):** Replacement urgency 35 · Historic buying 25 · "
             "Open pipeline 25 · Competitive displacement 15.")
    L.append("")
    L.append("**Tiers:** "
             "**T1** active opp + imminent replacement → work weekly · "
             "**T2** replacement-due or historic buyer, no open opp → convert to discovery · "
             "**T3** relationship / radar → quarterly touch.")
    L.append("")
    L.append(f"**Coverage:** {len(keep)} ranked accounts "
             f"(T1 {len(t1)} · T2 {len(t2)} · T3 {len(t3)}) of "
             f"{len([s for s in scored if s['total_opp_count'] or s['equipment']])} with signal.")
    L.append("")

    def table(rows):
        out = ["| # | Account | Score | Why now | Equipment / Expiry | Open $ | Next action |",
               "|---|---------|-------|---------|--------------------|--------|-------------|"]
        for i, a in enumerate(rows, 1):
            why = "; ".join(a["reasons"][:2]) or "-"
            loc = f" ({a['city']}, {a['state']})" if a["city"] else ""
            opendollar = f"${a['open_amount']:,.0f}" if a["open_amount"] else "-"
            out.append(f"| {i} | **{a['name']}**{loc} | {a['score']:.0f} "
                       f"| {why} | {equip_summary(a)} | {opendollar} | {next_action(a)} |")
        return out

    for tier, rows, head, blurb in [
        (1, t1, "Tier 1 — Work Weekly", "Active opportunities with an advancing stage or a live replacement trigger. These carry the half — touch every week."),
        (2, t2, "Tier 2 — Convert to Discovery", "Replacement-due or proven historic buyers with no open opp. Bi-weekly cadence; lead with the lease/age trigger."),
        (3, t3, "Tier 3 — Relationship / Radar", "On the radar for relationship or event-driven touches. Quarterly cadence."),
    ]:
        L.append(f"## {head}")
        L.append("")
        L.append(f"*{blurb}*")
        L.append("")
        L.extend(table(rows) if rows else ["*No accounts in this tier.*"])
        L.append("")

    L.append("---")
    L.append("")
    L.append("## Score Components (top 15)")
    L.append("")
    L.append("| Account | Total | Replacement (35) | Historic (25) | Pipeline (25) | Comp (15) |")
    L.append("|---------|-------|------------------|---------------|---------------|-----------|")
    for a in keep[:15]:
        L.append(f"| {a['name']} | {a['score']:.0f} | {a['urgency']:.0f} | "
                 f"{a['historic']:.0f} | {a['pipe']:.0f} | {a['comp']:.0f} |")
    L.append("")
    L.append("---")
    L.append("")
    L.append("*Verify every expiry date against Salesforce before acting (Date Accuracy Protocol). "
             "EDA coverage is strongest for plasma equipment; broaden with "
             "`sf_get_account_assets` on any Tier 1 account before a close push.*")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=25, help="Max Tier-1 accounts (T2/T3 capped separately)")
    ap.add_argument("--stdout", action="store_true")
    args = ap.parse_args()

    acct = build()
    scored = [score_account(a) for a in acct.values()]
    report = render(scored, args.top)

    if args.stdout:
        print(report)
        return
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(report, encoding="utf-8")
    ranked = sorted(scored, key=lambda a: -a["score"])
    print(f"Wrote {OUT_FILE}")
    print(f"Top 5: " + ", ".join(f"{a['name']} ({a['score']:.0f}/T{a['tier']})" for a in ranked[:5]))


if __name__ == "__main__":
    main()
