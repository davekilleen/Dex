---
name: pipeline-sync
description: "Live view of your Pipedrive pipeline reconciled against your local pipeline tracker; flags drift, maps focus deals, and pushes confirmed updates to the CRM. Use when the user says 'sync my pipeline', 'show me my pipeline', 'reconcile the CRM'. Not for connecting Pipedrive in the first place; use `pipedrive-setup`."
---

<!-- Generated from `.claude/skills/pipeline-sync/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

## Purpose

Give the user a **live, reconciled view of their pipeline**. Pipedrive owns the canonical deal *numbers*; the local pipeline tracker note (default `04-Projects/Pipeline_Tracker.md`, or the `tracker_path` set in `System/integrations/pipedrive.yaml`) owns the *strategy* and the *focus list*. This skill pulls the live numbers, diffs them against the tracker, shows where they've drifted, and, only when the user confirms, writes changes back to either side.

Requires the Pipedrive integration. If `System/integrations/config.yaml -> pipedrive.enabled` is not `true`, tell the user to run `/pipedrive-setup` first and stop.

## Usage

- `/pipeline-sync`: pull live pipeline, reconcile against the tracker, show a drift report
- `/pipeline-sync map`: (re)map focus deals to their Pipedrive records (first-run, or after adding a deal)
- `/pipeline-sync discover`: list open Pipedrive deals **not** in the tracker (find what you're missing)

## Method

Gate the run on the companion skill, integration state, configured tracker path,
and a complete live read. Build a deal-by-deal ledger containing the tracker and
Pipedrive identifiers, values, source update times, retrieval `as-of` time, and
read completeness. Reconcile mappings, fields, totals, and untracked deals
without changing either system. Present each drift direction as a human choice.
For every confirmed mutation, preview the exact payload or file diff, apply only
that choice, then read back both affected authorities before moving to the next
change. Treat ambiguous network outcomes as unresolved, not retryable failures.

## Output contract

Return integration and coverage status, the source ledger, drift rows, unchecked
deals, mapping gaps, totals reconciliation, and decisions still required. The
final change summary must be derived only from read-back receipts and must name
each verified target. Explicitly report zero changes, partial completion, or
failure rather than using a fixed success sentence. Include unresolved and
unknown items, the denominator behind every total, and any ambiguous write that
must be inspected before retry. A tool response alone is never a success receipt.

## Operating principles (non-negotiable)

- **Confirm every write.** Never call a Pipedrive write tool (`pipedrive_add_deal_note`, `pipedrive_add_deal_activity`, `pipedrive_update_deal`, `pipedrive_create_deal`, `pipedrive_create_org`) without first showing the exact payload (use `dry_run: true`) and getting the user's explicit yes. CRMs are often shared with colleagues. The tools preview by default and only send on an explicit `dry_run: false`, so that parameter is the record of the user's yes — never pass it to "get past" a preview the user has not actually seen and approved.
- **A partial read is not a clean read.** `pipedrive_get_pipeline_snapshot` and `pipedrive_list_deals` return a `complete` flag and a `warning` when they could not see everything. When `complete` is false, report the named deals as *unchecked*; never fold them into "no drift" or "nothing else in the CRM".
- **Never auto-resolve drift.** For each difference, the user chooses the direction. Default to doing nothing.
- **Tracker totals matter.** If a deal value or probability changes on the tracker side, recompute any gross/weighted totals the tracker maintains and update its `last_updated` field if it has one.
- **Re-read before editing.** Re-read the tracker and any company page immediately before editing it; don't trust session memory of file state.
- **Report, don't editorialise.** Drift is information, not a prompt to pressure the user into action. Show the numbers plainly and let them decide.

---

## Evidence, authority, and recovery

Treat catalogue-visible companion skills and Pipedrive prerequisites as gates,
not optional context. Before gathering, verify that the catalogue exposes the
`pipedrive-setup` companion, that the Pipedrive integration is enabled and
connected, and that the configured tracker path is readable. If a required
companion or prerequisite is missing, unavailable, or contradictory, name it
and stop or degrade to a clearly labelled local-only report; never fake a live
CRM view.

- Record provenance for every drift row and total: source path or Pipedrive
  record, source date/updated time, and the `as-of` time of the read. Keep
  tracker and CRM values side by side. If they conflict, show both sources and
  dates; keep missing data as `Unknown`, never invent absent facts, or silently
  choose a direction.
- A partial read is an incomplete read. When `complete` is false, a warning is
  present, or a companion returns only part of the catalogue, list every
  unchecked deal and the missing scope, disclose denominator coverage, and do
  not report "no drift" or write based on the partial result.
- Keep reconciliation read-only until an authorized human decides. A mapping,
  recommendation, or drift direction is not a human decision. Before any
  tracker or Pipedrive change, show an exact write preview: target, exact
  before/after content or payload, and all derived total changes. Require the
  authorized human's explicit confirmation; do not rely on implied approval.
- After every confirmed write, read back the changed record and tracker and
  reconcile the read-back with the approved preview. Report success only when
  the values match. If a write fails, times out, or read-back is incomplete or
  differs, state what may have changed, re-read the authoritative source, and
  wait for explicit human direction before repairing or retrying.
- Retry idempotency must be proved rather than assumed. A network error after
  Pipedrive accepts a write is ambiguous; do not silently retry. Check the
  deal's notes/activities or other authoritative record first, then show a
  fresh exact preview and obtain confirmation before sending a new write.

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
Deal                                      Field        Tracker                 Pipedrive
[Deal title] ([account from source])      [field]      [tracker source value]  [Pipedrive source value]  -> [tracker|pipedrive|skip]
[Second sourced deal, if one exists]      [field]      [tracker source value]  [Pipedrive source value]  -> [tracker|pipedrive|skip]
```

Populate every bracket from the reconciliation ledger and retain `[source ID]`,
`[source date]`, and `[as-of date]` for both sides. If a field lacks evidence,
display `Unknown`; do not turn the example shape into deal facts.

For each row ask which way to resolve (or batch: "take Pipedrive for all numbers, leave narrative alone").

**Map mode**: for each unmapped focus deal, show candidate matches and confirm; then `pipedrive_save_mapping(dex_key, deal_id, org_id, title)` and write the ids into the markdown (Step 3).

**Discover mode**: list untracked deals; offer to add any the user wants to the tracker (no Pipedrive write needed). If the user mentions a deal that exists in neither place, offer to create it in Pipedrive **only if** `writes.allow_create: true` in `System/integrations/pipedrive.yaml`; otherwise add it to the tracker only and mention that CRM creation is switched off (they can enable it via `/pipedrive-setup` if they want it).

## Step 3: Apply confirmed changes

- **Tracker <- Pipedrive:** re-read the tracker, edit the row and any matching per-deal detail block, recompute totals if value/probability changed, update `last_updated` if the tracker has one. Reconcile the matching `05-Areas/Companies/<account>.md` page in the same flow so deal data never drifts between files.
- **Pipedrive <- Tracker:** build the payload, call the write tool with `dry_run: true`, show it, get the yes, then send with `dry_run: false`. Map stage phrases -> `stage_id` and owner names -> `user_id` using `pipedrive.yaml` (`stage_mapping`/`owner_mapping`); if a mapping is missing, ask rather than guess.
- **Creating a record** (discover mode, gate on): same discipline. `pipedrive_create_org` first if the organisation doesn't exist, then `pipedrive_create_deal`, each previewed with `dry_run: true` and sent only on an explicit yes.
- **Mapping persisted:** store the Pipedrive deal id in the tracker's per-deal detail (`- **Pipedrive deal:** <id> - synced <timestamp> - stage: <name>`) and `pipedrive_org_id` + `pipedrive_synced_at` in the company page frontmatter.

## Step 4: Summarise

Build the summary from the read-back receipt for each approved target. Name the
verified tracker rows, company pages, mappings, or Pipedrive records and report
their actual counts. If no approved mutation occurred, say `zero changes`. If
some writes failed or could not be read back, report `partial` with each verified
and unverified target. If the gather or every mutation failed, report `failure`
and the authoritative state that remains unknown. Note all unresolved drift.

---

## Notes for the assistant

- Names may be dictated by voice; resolve owner names against `owner_mapping` and the People Index before mapping, and don't create duplicates from spelling variants.
- A focus deal owned by a colleague is in scope: the tracker can hold the whole team's book. A 403 on a write means the token can't edit that deal; surface it honestly and offer to note the change on the tracker side only.

## Known limitation: retry idempotency must be proved, not assumed

If the connection drops after Pipedrive accepts a note or activity but before
its reply arrives, the write succeeded and Dex cannot tell. Pipedrive's API
offers no idempotency key, so there is no way to make a retry provably safe.

**So do not silently retry a write that failed with a network error.** Say what
happened, and offer to check the deal first: `pipedrive_get_deal` lists the
deal's recent notes and activities, so the user can see whether the write
landed before deciding to send it again. A duplicate note in a shared CRM is
cheap to delete and expensive to explain — checking beats guessing.
