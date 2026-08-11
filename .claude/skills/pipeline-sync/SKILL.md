---
name: pipeline-sync
description: "Live view of your Pipedrive pipeline reconciled against your local pipeline tracker; flags drift, maps focus deals, and pushes confirmed updates to the CRM. Use when the user says 'sync my pipeline', 'show me my pipeline', 'reconcile the CRM'. Not for connecting Pipedrive in the first place; use `pipedrive-setup`."
context: conversation
---

## Purpose

Give the user a **live, reconciled view of their pipeline**. Pipedrive owns the canonical deal *numbers*; the local pipeline tracker note (default `04-Projects/Pipeline_Tracker.md`, or the `tracker_path` set in `System/integrations/pipedrive.yaml`) owns the *strategy* and the *focus list*. This skill pulls the live numbers, diffs them against the tracker, shows where they've drifted, and, only when the user confirms, writes changes back to either side.

Requires the Pipedrive integration. If `System/integrations/config.yaml -> pipedrive.enabled` is not `true`, tell the user to run `/pipedrive-setup` first and stop.

## Usage

- `/pipeline-sync`: pull live pipeline, reconcile against the tracker, show a drift report
- `/pipeline-sync map`: (re)map focus deals to their Pipedrive records (first-run, or after adding a deal)
- `/pipeline-sync discover`: list open Pipedrive deals **not** in the tracker (find what you're missing)

## Operating principles (non-negotiable)

- **Confirm every write.** Never call a Pipedrive write tool (`pipedrive_add_deal_note`, `pipedrive_add_deal_activity`, `pipedrive_update_deal`, `pipedrive_create_deal`, `pipedrive_create_org`) without first showing the exact payload (use `dry_run: true`) and getting the user's explicit yes. CRMs are often shared with colleagues.
- **Never auto-resolve drift.** For each difference, the user chooses the direction. Default to doing nothing.
- **Tracker totals matter.** If a deal value or probability changes on the tracker side, recompute any gross/weighted totals the tracker maintains and update its `last_updated` field if it has one.
- **Re-read before editing.** Re-read the tracker and any company page immediately before editing it; don't trust session memory of file state.
- **Report, don't editorialise.** Drift is information, not a prompt to pressure the user into action. Show the numbers plainly and let them decide.

---

## Step 0: Gate

1. Check `pipedrive.enabled` in `System/integrations/config.yaml`. If not enabled -> "Pipedrive isn't connected yet, run `/pipedrive-setup` first." and stop.
2. Run `pipedrive_status()`. If it does not return `connected: true`, surface the `user_message` and stop.

## Step 1: Delegate the gather (Agent subagent)

Spawn a `general-purpose` Agent using the prompt in `AGENT_INSTRUCTIONS.md` (substitute the mode: reconcile | map | discover). The subagent does the heavy read/diff work in its own context and returns a compact structured report:
- For **reconcile**: a drift list (per deal: field, tracker value, Pipedrive value) + unmapped focus deals + totals check.
- For **map**: candidate Pipedrive matches per unmapped focus deal.
- For **discover**: open Pipedrive deals with no tracker row.

If the Agent fails, fall back to running the instructions inline.

## Step 2: Present + decide (in conversation)

**Reconcile mode**: show a compact table:

```
Deal                       Field        Tracker        Pipedrive
Platform Migration (Acme)  value        £250k          £200k          -> [tracker|pipedrive|skip]
Data Warehouse (Initech)   probability  40%            45%            -> [tracker|pipedrive|skip]
```

For each row ask which way to resolve (or batch: "take Pipedrive for all numbers, leave narrative alone").

**Map mode**: for each unmapped focus deal, show candidate matches and confirm; then `pipedrive_save_mapping(dex_key, deal_id, org_id, title)` and write the ids into the markdown (Step 3).

**Discover mode**: list untracked deals; offer to add any the user wants to the tracker (no Pipedrive write needed). If the user mentions a deal that exists in neither place, offer to create it in Pipedrive **only if** `writes.allow_create: true` in `System/integrations/pipedrive.yaml`; otherwise add it to the tracker only and mention that CRM creation is switched off (they can enable it via `/pipedrive-setup` if they want it).

## Step 3: Apply confirmed changes

- **Tracker <- Pipedrive:** re-read the tracker, edit the row and any matching per-deal detail block, recompute totals if value/probability changed, update `last_updated` if the tracker has one. Reconcile the matching `05-Areas/Companies/<account>.md` page in the same flow so deal data never drifts between files.
- **Pipedrive <- Tracker:** build the payload, call the write tool with `dry_run: true`, show it, get the yes, then send with `dry_run: false`. Map stage phrases -> `stage_id` and owner names -> `user_id` using `pipedrive.yaml` (`stage_mapping`/`owner_mapping`); if a mapping is missing, ask rather than guess.
- **Creating a record** (discover mode, gate on): same discipline. `pipedrive_create_org` first if the organisation doesn't exist, then `pipedrive_create_deal`, each previewed with `dry_run: true` and sent only on an explicit yes.
- **Mapping persisted:** store the Pipedrive deal id in the tracker's per-deal detail (`- **Pipedrive deal:** <id> - synced <timestamp> - stage: <name>`) and `pipedrive_org_id` + `pipedrive_synced_at` in the company page frontmatter.

## Step 4: Summarise

Report what changed and where: "Updated 2 tracker rows from Pipedrive; pushed 1 value change to Pipedrive (confirmed); recomputed totals; logged sync to the company page." Note anything left unresolved.

## Step 5: Rating

After completing, ask: "Quick rating (1-5, 5 = great)?" If a number comes back, `capture_skill_rating(skill_name="pipeline-sync", rating=N)`.

---

## Notes for the assistant

- Names may be dictated by voice; resolve owner names against `owner_mapping` and the People Index before mapping, and don't create duplicates from spelling variants.
- A focus deal owned by a colleague is in scope: the tracker can hold the whole team's book. A 403 on a write means the token can't edit that deal; surface it honestly and offer to note the change on the tracker side only.
