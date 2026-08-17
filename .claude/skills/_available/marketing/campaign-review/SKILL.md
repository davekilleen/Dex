---
name: campaign-review
description: Use when a completed or in-flight marketing campaign needs an evidence-backed review of its goal, baseline, targets, actuals, or learnings.
role_groups: [marketing, leadership]
jtbd: |
  Campaigns finish and learnings get lost. This helps you run a post-mortem - gather
  campaign materials, prompt for results and learnings, document what worked and
  what didn't, and save to 06-Resources/Learnings/ so you compound knowledge over time.
time_investment: "20-30 minutes per campaign"
---

# Campaign review

## When to use

Use this skill for a named campaign with a stated measurement window and enough source
material to compare intended outcomes with observed results. It supports a partial review
when some results are pending, as long as the gaps remain visible.

Do not use it to optimize a live campaign, change spend, alter targeting, or declare
causation from a result alone. Not for publishing a post-mortem, changing campaign
records, or contacting customers without a separate preview and human confirmation.

## Inputs and source discipline

- Record the campaign name or identifier, goal, measurement window, timezone, currency and
  metric units where supplied, and the as-of date/time. Never use an unprovided date as
  the campaign date.
- Locate the brief, target definition, channel records, baseline, actual results, spend
  records, and qualitative feedback. Log each source, its source date, retrieval/as-of
  date, metric definition, denominator, unit, and scope.
- Require a comparable baseline: document its period, source, definition, and known limits.
  If no baseline exists, state that comparison is unknown rather than constructing one.
- Treat user-provided targets and platform actuals as separate evidence. Do not silently
  combine currencies, attribution windows, channels, or reporting periods.

## Method

1. Define the campaign goal and the outcome that would count as success. Record the
   baseline before reviewing the actuals.
2. Build a source/date ledger for each target, actual, qualitative observation, and spend
   item. Preserve the original value and definition.
3. Normalize target versus actual only when metric, unit, denominator, attribution window,
   and period match. Show the normalization rule; label non-comparable pairs unknown.
4. Reconcile totals to channel and source records, then describe changes against the
   baseline. Keep descriptive change separate from attribution.
5. Assess attribution limits: identify what the source can and cannot connect to the
   campaign, record competing activity or missing controls, and distinguish correlation
   from causation. Timing or co-occurrence is not proof of causation.
6. Classify each learning as observed, inferred, unknown, stale, or contradictory, with
   confidence and supporting source/date references. Do not turn feedback into an intent
   or cause that the source does not state.
7. Write recommendations and follow-up questions as proposals. If a post-mortem must be
   saved, show its complete preview and wait for explicit confirmation from the human
   authority.

## Truth and uncertainty rules

- **Observed:** a goal, baseline, target, actual, or feedback item directly documented by
  a dated source.
- **Inferred:** an interpretation supported by observed campaign evidence; state the link
  and confidence rather than presenting it as measured fact.
- **Unknown:** missing, inaccessible, non-comparable, or not-yet-final evidence.
- **Stale:** a result or baseline no longer current for the requested as-of boundary, or a
  report superseded by a newer dated report.
- **Contradictory:** sources disagree on a goal, target, actual, or explanation; show both
  values and dates and do not choose one silently.

Never invent dates, metrics, percentages, money, owners, intent, status, causes, or
evidence. A recommendation is not a conclusion about why performance changed, and it is
not a human decision.

## Output contract

Return a review with:

- campaign scope, goal, measurement window, timezone, as-of date/time, and source coverage;
- a baseline and target-versus-actual table with definitions, units, denominators, dates,
  and comparability flags;
- attribution limits and an explicit correlation-versus-causation assessment;
- observed learnings, inferences, unknowns, stale items, contradictions, and confidence;
- recommendations, open questions, and any requested save shown as a draft preview.

Every material number or claim must trace to a source and date. If the denominator or
measurement window is unknown, do not calculate a rate or imply coverage.

## Safety and write boundaries

Default to read-only. Do not edit campaign platforms, budgets, spend, targeting, status,
analytics, or learning records. For a requested save or other action, present the exact
preview, obtain explicit confirm from the human authority, and execute only that approved
scope. Recommendations remain recommendations; they do not authorize budget or campaign
decisions.

## Verification and recovery

Read back each result from its source and reconcile target, actual, baseline, totals,
denominators, units, and attribution windows before delivery. After an authorized save,
read back the destination and reconcile it with the confirmed preview. If a report is
stale, a source is contradictory, or a read fails, mark the affected claim and explain
the limitation. If a write fails or is partial, stop, preserve the draft and error,
report what did and did not change, and wait for human authority before retrying or
recovering; never claim the post-mortem was saved without read-back proof.
