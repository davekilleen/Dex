---
name: commitments
description: "Reconcile the promises you made and the asks you received across meetings and notes into a clear owner/due/source list, then — only with your confirmation — turn the real ones into tracked tasks. Use when the user says 'what did I promise', 'what am I on the hook for', 'anything I owe people', 'loose ends', or after a run of meetings. Also use proactively during daily-plan/daily-review when uncaptured commitments surface. Not for tracking work you handed off to others; use `delegate-check`. Not for recording a decision you made; use `decision-log`."
---

# /commitments

Small interpersonal promises are where trust is won or lost — "I'll send that over," "can you review this?" — and they evaporate because they never become tracked commitments. This skill surfaces them from what you already captured, and turns the real ones into tasks **only when you say so**.

Governing rule: **do not rebuild the data layer.** The Work MCP already ships the scanner — `get_commitments_due` reads recent meeting notes and person-page action items and returns them bucketed by due date. This skill is a thin **present → confirm → create** layer on top of it. It does not re-scan, add a store, or touch the extraction logic.

---

## Arguments

`$RANGE`: optional — `today` (default), `this-week`, or `all`. Maps to the tool's `date_range`.

## Step 1 — Scan (existing tool, don't reinvent)

Call `get_commitments_due(date_range=$RANGE)`. It returns `commitments_due_today`, `commitments_due_this_week`, and `commitments_no_date` — each item carries `commitment`, `due_date`, `source` (the meeting file or person page), and, for person-page items, `to_person`.

If `get_commitments_due` returns a `feature_status` other than `ok`, follow the standard contract (surface the tool's `user_message`; never invent a result). If it errors or the Work MCP is unavailable, say so plainly and stop — do not fabricate a commitments list.

**Optional enrichment (degrades silently):** if ScreenPipe is active and opted-in, you may also fold in the `commitment-scan` (agent skill) results as an extra source. If ScreenPipe is absent — the normal case — skip it entirely and say nothing about it. The shipped skill must never depend on the beta.

## Step 2 — Dedup against existing tasks

For each candidate, check it isn't already a task before showing it (Work MCP's `create_task` similarity gate is the backstop, but pre-filtering means the user isn't asked about things already captured). Drop obvious duplicates; keep near-matches but mark them "possibly already tracked."

## Step 3 — Present, grouped by direction

Show two short lists so the user sees both sides of the ledger:

- **Promises you made** (outbound — you owe someone)
- **Asks you received** (inbound — someone owes you, or asked you to do something)

Direction is **inferred** from phrasing and `to_person`, not a field the scanner provides — so when a commitment's direction is genuinely unclear, put it under a third **Unclear** heading rather than guessing wrong. Each row shows: the commitment, the person (by name), the `source` (meeting or person page, by name), and the `due_date` (or "no date"). Refer to people and sources by name, never by id or file path noise.

If nothing is found, say so plainly ("No open commitments surfaced from the last two weeks of meetings and your person pages") — do not pad the list.

## Step 4 — Confirm before creating (hard gate — never auto-create)

Nothing is written without the user's say-so. Offer, per item, three choices: **create a task** / **already handled** / **not a real commitment**. Only the items the user picks become tasks. This is the no-write-without-authority discipline — do not batch-create, and do not create anything the user didn't confirm.

## Step 5 — Create, then inspect before claiming done

For each confirmed item, call Work MCP `create_task` (infer the pillar per the CLAUDE.md pillar-inference rules; carry the `source` into the task context so the commitment stays traceable). Then **read back what was created** — confirm each task ID and title — before reporting. Say exactly what you made: "Created 3 tasks: [task-…] …, [task-…] …". Never report "done / captured" without the created task IDs in hand. If a `create_task` call fails or is deduped as an existing task, say that honestly for that item rather than counting it as created.

---

## Quality bar

A good run reflects **only real, still-open commitments**, splits them into what the user owes vs is owed, creates **exactly** the tasks the user confirmed, and reports them back by their real task IDs. The user should never be surprised by a task they didn't approve, nor told something was captured that wasn't.

## Anti-patterns (do not do these)

- **Auto-creating tasks** from the scan without per-item confirmation.
- **Guessing direction** (made vs received) when the phrasing is ambiguous — use the Unclear group instead.
- **Re-implementing the scan** — inventing a new commitment store or extraction logic instead of calling `get_commitments_due`.
- **Depending on ScreenPipe** — the skill must work fully without it; enrichment is optional and silent when absent.
- **Claiming "captured / done"** without reading back the created task IDs.
- Padding an empty result with vague "maybe follow up on…" filler.

## Degradation

- `get_commitments_due` unavailable / errors → say so and stop; never fabricate commitments.
- ScreenPipe / `commitment-scan` absent → skip silently; the vault scan alone is the product.
- A `create_task` call fails → report that item as not created; do not silently count it.

---

## Track Usage (Silent)

Update `System/usage_log.md` to mark commitments review as used. **Analytics (Silent):** call `track_event` with event_name `commitments_reviewed` and property `created_count` (the number of tasks actually created — no commitment text, no names). Fires only if the user opted into analytics; no action if it returns "analytics_disabled".
