---
name: content-calendar
description: Use when inventorying content commitments, ideas, and schedule coverage for a specified period and timezone.
role_groups: [marketing]
jtbd: |
  Your content pipeline is scattered across files and you're not sure if you have
  gaps. This scans 05-Areas/Content/, checks alignment with campaigns and priorities,
  identifies gaps in the pipeline, and suggests topics based on recent customer intel.
time_investment: "10-15 minutes per review"
---

<!-- Generated from `.claude/skills/_available/marketing/content-calendar/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

# Content calendar

## When to use

Use this skill when the requester supplies, or the source canonically defines, a review
period and timezone for content inventory. It distinguishes what is committed from what
is merely an idea, and reports scheduled, undated, duplicate, and colliding items.

Do not use it to invent a publishing schedule, fill missing dates, assign owners, publish
content, or change status. Not for creating calendar events or claiming complete coverage
from an unbounded or partial source set.

## Inputs and source discipline

- Require an explicit period start and end, timezone, and as-of date/time. If any is
  missing, ask for it or report the boundary as unknown; never infer a date from the
  request or use the current date.
- Identify the status source and its authority, plus content artifacts, campaign/goal
  sources, and any calendar export. Record each source, source date, retrieval/as-of date,
  title or stable ID, status, scheduled date/time, and original timezone.
- Preserve source wording and timestamps. Convert dates for comparison only when the
  source timezone is known, and show the conversion rule.
- Record excluded, inaccessible, and undated items so the report does not imply that the
  scan covered content it could not inspect.

## Method

1. Establish the period, timezone, as-of boundary, source scope, and status source before
   reading items.
2. Inventory each item read-only. Record its status only when the source states it. Mark
   an explicit commitment separately from an idea, draft, or suggestion; do not infer
   commitment from a filename, tone, or presence in a folder.
3. Normalize known scheduled timestamps into the declared timezone while retaining the
   original value. Put items without a supported date in an undated section rather than
   placing them in a week or month.
4. Detect exact duplicates using stable IDs or matching source records. Flag possible
   duplicates when identity is uncertain. Detect a date collision only when two distinct
   items have supported overlapping dates/times; do not resolve the collision yourself.
5. Calculate coverage only from dated items inside the declared period and a declared
   denominator. Report excluded, undated, inaccessible, and duplicate items separately;
   do not invent dates, percentages, or coverage.
6. Compare content to stated campaign or strategic sources, marking alignment as observed
   or inferred. Offer gap and topic recommendations without converting them into calendar
   commitments.
7. Show a complete draft before any requested save, status change, reschedule, or calendar
   action, and wait for human confirmation.

## Truth and uncertainty rules

- **Observed:** status, commitment, idea, date, time, or alignment directly stated in a
  dated source.
- **Inferred:** a proposed grouping, likely theme, or possible alignment derived from
  observed fields; state the reasoning and confidence.
- **Unknown:** missing status, date, timezone, source authority, or inaccessible content.
- **Stale:** a status or schedule whose source date is outside the requested as-of boundary
  or is superseded by a newer status source.
- **Contradictory:** sources disagree about status, commitment, date, or ownership; show
  each source and date rather than selecting one silently.

Never invent dates, metrics, percentages, owners, intent, money, causes, status, or
evidence. A recommendation is not a commitment and is not a human decision.

## Output contract

Return a calendar review containing:

- period, timezone, as-of date/time, status source, source coverage, and exclusions;
- separate tables for committed items, ideas, in-progress/published items only when sourced,
  and undated items;
- original and normalized date/time, source/date trace, duplicate flags, and collision flags;
- a declared coverage denominator and reconciliation notes, or an explicit unknown when it
  cannot be supported;
- stale statuses, contradictions, unknowns, confidence, and recommendations clearly
  separated from commitments.

## Safety and write boundaries

Default to read-only. Do not create events, publish content, move dates, change status,
assign owners, edit campaign records, or rewrite source files. Any requested write or
external action requires an exact preview, explicit confirm, and human authority. Apply
only the approved change; recommendations do not authorize scheduling decisions.

## Verification and recovery

Read back the source records and reconcile item IDs, dates, timezone conversions, statuses,
duplicate flags, collision flags, and coverage counts before delivering. After an authorized
write, read back the destination and reconcile it with the confirmed preview. If a status
source changes, a date is ambiguous, or a read fails, mark the item stale or unknown and
do not continue as though it were current. If a write fails or partially succeeds, stop,
preserve the preview and error details, report the exact partial state, and obtain human
authority before retrying or recovering.
