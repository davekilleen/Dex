---
name: visit-prep-custom
description: Build a one-page field visit packet for an account — equipment floor with lease/age triggers, open pipeline, quotes, service cases, contacts, recent activity, and an AI conversation strategy. Route mode preps every account on a territory day in one shot.
---

# Visit Prep — Field Packet Generator

Turn everything Dex knows about an account into a one-page packet you can read in the truck: hard data from the local Salesforce/EDA cache (deterministic script — no tokens, no hallucination), plus a conversation strategy layer that only AI can add.

**Design principle (agentic-OS pattern):** the script does the data gathering; Claude only does judgment work — strategy, framing, and cross-linking. Never re-derive by hand what `visit-prep.py` already computes.

## Usage

- `/visit-prep [account]` — full packet for one account
- `/visit-prep route [today|tuesday|...]` — packets for every account on that day of the week's itinerary
- `/visit-prep [account] quick` — script output only, no AI enrichment (fastest)

## Arguments

$ACCOUNT: Account name (fuzzy matched against Chris-owned accounts)
$MODE: `route` for a whole territory day, `quick` to skip enrichment

---

## Step 1: Generate the Data Dossier

Run the deterministic builder:

```bash
python .scripts/visit-prep.py "[ACCOUNT]"
```

- Output lands in `Inbox/Visit_Prep/YYYY-MM-DD - [Account].md`.
- If it prints `AMBIGUOUS`, show the candidate list and ask which one.
- If it prints `NOT FOUND`, try `--match "[shorter fragment]"` and offer the matches. If still nothing, the account may not be Chris-owned — say so and stop (do not fall back to territory-wide data).
- If the dossier warns the cache is stale (>8 days), tell the user and offer to run `.scripts/automation/run-sf-sync.ps1` first.

**Quick mode ends here** — send the file and stop.

## Step 2: Enrich with Vault Intelligence (the compounding-wiki layer)

The dossier's footer says whether a company page exists (`People/Companies/...`). Now add what the cache can't know:

1. **Read the company page** fully if it exists — relationship notes, history, prior visit outcomes.
2. **Read person pages** for the contacts listed in the packet (use `lookup_person`, fall back to `People/External/`). Pull personal context: what they care about, past conversations, commitments.
3. **Semantic search** (`query` tool, QMD) for the account name and its key equipment/deal topics — catches meeting notes and ideas that never made it onto the company page. Fall back to Grep if QMD is unavailable.
4. **Granola meetings** (`granola_search_meetings`) for recent conversations with these people, if available.
5. **Check open commitments**: search `Planning/Tasks.md` for tasks mentioning this account or its contacts — walking in with an unfulfilled promise is worse than not visiting.

## Step 3: Write the Conversation Strategy

Append a section to the packet file (keep the script's sections untouched):

```markdown
## Conversation Strategy (AI)

**Open with:** [service case acknowledgment / personal context / recent thread — whichever the data supports]
**The one thing to accomplish:** [single most valuable outcome for this visit, tied to the "Why You're Walking In" triggers]
**Talk track:** [2-4 bullets sequencing the conversation — empathy first if open cases exist, then the trigger, then the ask]
**Landmines:** [open cases, lost deals, stale promises, competitor equipment they chose over us — anything to NOT stumble into]
**Bring/mention:** [demo days invites, vendor reps in town, financing angles like Section 179 (Q4), relevant used inventory]
```

Rules:
- Ground every claim in the dossier or vault — no invented history.
- Use absolute dates (Date Accuracy Protocol).
- If an open service case exists, empathy ALWAYS comes before selling — this is non-negotiable in the talk track.

## Step 4: Cross-Link (make the knowledge compound)

1. Run the auto-linker so people names become WikiLinks:
   ```bash
   node .scripts/auto-link-people.cjs "Inbox/Visit_Prep/[file].md"
   ```
2. On the company page (create a stub via the `/customer-intel` format if missing), add under a `## Visit Preps` section:
   ```markdown
   - [[YYYY-MM-DD - Account|YYYY-MM-DD visit prep]] — [one-line: the trigger + the goal]
   ```
   This is the point of the exercise: next quarter's prep starts warm, not cold.
3. Do **not** log anything to Salesforce — prep is not activity. After the actual visit, `/log-meeting` closes the loop (and sf-activity-sync pushes it).

## Step 5: Deliver

Send the packet file to the user with a 2-3 sentence TLDR: the one thing to accomplish, the strongest trigger, and any landmine.

---

## Route Mode (`/visit-prep route [day]`)

Prep a whole territory day at once — packets ready before the drive.

1. **Find the day's accounts.** Read this week's itinerary (`Planning/Week XX - Itinerary MM.DD.YYYY.xlsx` — most recent file; use the xlsx skill to read it). Extract account names under the requested day's header rows. If no itinerary exists, fall back to asking which accounts, or offer the top Tier-1/Tier-2 accounts from `Planning/Key_Accounts_H2-2026.md`.
2. **Batch the script** (one call, it accepts multiple names):
   ```bash
   python .scripts/visit-prep.py "Account A" "Account B" "Account C"
   ```
3. **Enrich each packet** (Steps 2-4), but keep strategy sections tighter — 3 bullets max per account.
4. **Write a route summary** at `Inbox/Visit_Prep/YYYY-MM-DD - Route [Day].md`: ordered stop list with city, the one-thing-to-accomplish per stop, and links to each packet.
5. Deliver the route summary with links.

---

## Notes

- Data scope: Chris-owned accounts only (`accounts.json` is pre-filtered). Never present territory-wide EDA records as "my accounts."
- The dossier's equipment table comes from EDA/UCC data — verify lease dates against Salesforce (`sf_get_account_assets`) before quoting anything.
- Usage tracking: check the visit-prep box in `System/usage_log.md` silently.
