# Salesforce Analysis Learnings

Reusable patterns for pulling and analyzing Chris's Salesforce data (pipeline reviews, relationship analysis, outreach targeting).

---

## Scope every account query to Chris-owned (Customer record type) — June 26, 2026

**Context:** Building ALLtra/Randy outreach and an EDA plasma cross-reference, then a full pipeline relationship analysis.

**Challenge:** Asset/EDA searches and "my accounts" lists silently pulled colleagues' customer accounts. An entire 23-shop conquest list turned out to be 19 colleagues' accounts; the ALLtra "owner" outreach included 5 colleagues' accounts.

**What Worked:**
- Filter Customer-record-type queries with `OwnerId = '0055Y00000GU69oQAD'` (Chris) or post-filter results against his owned-account set before presenting.
- Pull **Vendor** record types regardless of owner (different rule).
- For asset/EDA work: intersect on `account_id` against Chris's owned accounts locally before drafting anything.

**Key Insight:**
> Every plasma owner in the 2,000-asset EDA report is already assigned to a MAM rep — there are almost no orphan accounts. So "find prospects" really means "find *my* accounts with aging equipment," not "find anyone with old equipment." Always scope to ownership first. See [[feedback_account_ownership_scope]] in memory.

**See Also:** Mistake_Patterns.md → "Salesforce query pulls colleagues' accounts"

---

## Data model: weekly sync to a local working dataset — Salesforce is the system of record, not the system of analysis — June 26, 2026

**Context:** Chris owns 1,164 accounts and 215 open opps; activity Descriptions contain full email bodies (1.2 MB for 200 tasks). Almost every useful query exceeds the tool's token limit and spills to a saved file, and ad-hoc questions kept re-pulling the same data live.

**The approach (target state):**
- **Pull large Salesforce datasets on a weekly sync** into a local working dataset (accounts, opportunities, activities/Tasks+Events incl. Description & Comments). The goal is to reduce repeated live querying, allow analysis off-platform, keep trend reviews consistent over time, and avoid re-processing the same data on every ad-hoc question.
- Once the local dataset exists, **Salesforce = system of record; local = system of analysis.** Most queries run against the local data. Only hit Salesforce live when something **truly needs real-time validation** (e.g. confirming a stage/PO just changed today).

**Processing mechanics (when working the local data):**
- Process with **Python** (not jq — not installed on this Windows box).
- Always open saved JSON with `io.open(path, encoding="utf-8", errors="replace")` and `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` — SF data has smart quotes, em dashes, and a UTF-8 BOM (`﻿`) that crash default cp1252 print.
- For ownership/geography breakdowns across thousands of IDs, use SOQL `GROUP BY Owner.Name, Owner.IsActive` per ~400-ID chunk — compact output, catches inactive (orphan) owners.

**Implementation (live):**
- Pull script: `.scripts/sf-pull-sync.py --group {full|frequent}` → writes `.scripts/salesforce-data/` (opportunities, quotes, tasks, events, accounts, contacts, manifest). Scoped to OwnerId = Chris; auth reuses `~/.claude/sf_tokens.json` with creds from `.mcp.json`. Manifest tracks per-object `synced_at` so a frequent run doesn't stale-stamp the weekly objects.
- **Two-tier schedule** (high-velocity data stays near-live):
  - `frequent` = opportunities, quotes, tasks → Windows Task "Dex SF Frequent Sync", daily at 6:00 AM.
  - `full` = everything incl. accounts, contacts, events → "Dex SF Weekly Sync", Sundays 6:00 AM.
- Activity scope: activities on Chris's accounts by **any** owner, plus Chris's own activities anywhere (`Account.OwnerId = Chris OR OwnerId = Chris`). Contacts scoped to `Account.OwnerId = Chris`; quotes to `Opportunity.OwnerId = Chris`.
- The dataset is **gitignored** (customer PII + email bodies — never commit). Read these files for analysis; only query SF live for real-time validation.

**Key Insight:**
> Don't re-query Salesforce for every ad-hoc analysis. Sync weekly to local, analyze off-platform, and treat live SF calls as the exception reserved for real-time validation.

**See Also:** Working_Preferences.md (outreach drafting), [[salesforce-conventions]]

---

## Interpreting account & pipeline data — narrative beats dates — June 26, 2026

**Context:** Powering personalized follow-ups and a stalled-deal review from activity + opp history.

**Description and Comments are a primary source of truth.** They are the account narrative over time — intent, objections, timing, internal notes. Treat them as the main context layer when figuring out what's actually happening inside an account, not as an afterthought to structured fields.

**Pipeline analysis priority order:**
1. Activity history (Tasks/Events)
2. `LastActivityDate`
3. `Next Step` field
4. Narrative in `Description` / `Comments`

**Active-until-closed rule:** Until an opportunity is **explicitly marked closed, lost, or dead in Salesforce**, treat it as active pipeline intelligence — even if the stage or close date looks stale. Overdue close date is a scheduling signal, not a death signal:
- Overdue **+ no recent activity** = likely at-risk / stale (re-engage or qualify out)
- Overdue **+ recent activity** = still active; likely just needs date alignment or a next-step update

**Key Insight:**
> Pipeline health is not determined by dates alone. The most reliable indicators are activity level, next-step clarity, and the written narrative inside the account record. A deal is dead only when Salesforce says it's dead.

---

## Pipeline relationship analysis — what makes the output useful — June 26, 2026

**Context:** Analyzing activity + opp history to power personalized follow-up emails.

**What Worked:**
- Activity `Description` holds the real narrative (logged emails/calls). Group tasks by `WhatId` (opp), sort by `ActivityDate` desc, trim to recent ~6.
- Per deal, surface: relationship snapshot, themes (needs/pain/objection/buying-signal/timing), unresolved follow-up, momentum, suggested angle, then the draft.
- Flag data-quality issues inline: bounced/Undeliverable emails = dead contacts (ASGCO), "said No Purchase" notes = don't re-pitch, activity >1.5 yrs = likely dead.
- Spot synergy: when a stalled deal's account is already on an active outreach (e.g. Kelly Iron on the Randy 7/2 plasma trip), bundle the re-engagement into that visit instead of a cold touch.

**Key Insight:**
> The highest-leverage re-engagement isn't the biggest dollar amount — it's a stalled whale at an account you already have a *reason to visit*. Always cross-reference the stalled list against in-flight outreach before drafting cold.
