---
name: close-status
description: Use when reporting the evidence-backed status of a named month-end or quarter-end close, its blockers, counted completion, and dependency path. Not for explaining budget variances; use variance-analysis.
role_groups: [finance, leadership]
jtbd: |
  Month-end close has many moving parts and dependencies. This shows the close 
  checklist for the current period, flags incomplete items, surfaces blockers from 
  recent meetings, and tracks dependencies on other teams so you know exactly where 
  you stand.
time_investment: "10-15 minutes per check"
---

<!-- Generated from `.claude/skills/_available/finance/close-status/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

## When to use

Use when a finance or leadership user asks where a specified close period stands, what evidence
supports completion, what is blocked, or which dependencies determine the sequence. Confirm the
period, close deadline, and checklist scope before counting.

Do not use this skill to post journal entries, change the close checklist, certify completion,
assign owners, or approve an accounting treatment. Not for budget-versus-actual explanation,
forecasting, or audit sign-off.

## Inputs and source discipline

1. Identify the period, fiscal calendar/timezone, checklist version, and deadline. Use the
   controller- or process-owner-approved **authoritative checklist** as the denominator source;
   record its source, source date, date checked, and `as-of` date. Never invent a deadline or
   silently substitute a remembered checklist.
2. For each checklist row, capture its stable label, required evidence, current evidence source,
   source date, date checked, named owner only if explicitly recorded, and confidence. Prefer
   system/close evidence and dated owner confirmation over meeting notes; use notes to locate
   evidence, not to override it. Preserve contradictory sources.
3. Keep the checklist's scope and exclusions explicit. If the authoritative checklist is
   missing, partial, or stale, report the denominator as unknown rather than calculating a
   completion percentage.

## Method

1. Work read-only from the authoritative checklist and build one row per required item. Count an
   item complete only when its required evidence is present, dated, in scope, and reconciled;
   a statement that work is probably done is not completion evidence.
2. Assign mutually exclusive states from evidence: `complete`, `in progress`, `blocked`,
   `not started`, or `unknown`. Use `blocked` only for a known impediment or dependency; use
   `unknown` when evidence is absent, stale, or contradictory; use `not started` only when the
   source supports that state. Never convert missing evidence into not started.
3. Report completed rows as a counted numerator over the checklist denominator. Show a percentage
   only when both are known and the counting rule is stated. Calculate days remaining only from a
   supplied deadline and the stated `as-of` date.
4. Build the dependency graph from explicit row dependencies, deadlines, and evidence. Call a
   chain the **critical path** only when the dependency evidence supports that claim; without
   durations or ordering evidence, report a dependency chain and say criticality is unknown.

## Truth and uncertainty rules

Use `observed` for a row state supported by dated evidence, `inferred` for a suggested dependency
or interpretation, `unknown` for missing or insufficient evidence, `stale` for evidence outside
the relevant freshness or period, and `contradictory` when sources disagree. State confidence,
source, date, and `as-of` for each conclusion. Never invent dates, metrics, owners, intent,
money, percentages, causes, status, or evidence. Recommendations are not human decisions.

## Output contract

Return a status snapshot containing:

- period, checklist source/version, close deadline, `as-of` date, and scope;
- a row-level authoritative checklist with state, counted evidence, source/date, confidence,
  and explicitly sourced owner/dependency fields;
- numerator/denominator and completion percentage only when valid;
- separate blocked, unknown, and not-started lists, with the evidence or missing evidence;
- the dependency-derived critical path or an explicit unknown; and
- source register, stale inputs, unresolved contradictions, and read-only recommendations for
  human review. Do not label the close complete unless the counted evidence supports it.

## Safety and write boundaries

Remain read-only by default. Do not edit the checklist, statuses, owners, accounting systems, or
close records. If a write, export, or other action is requested, preview the exact target,
changes, and side effects; redact secrets or unapproved personal/confidential content; wait for
explicit `confirm` from the responsible human authority; then perform only that approved action.

## Verification and recovery

Read back the status output and reconcile every row state and counted numerator to the checklist
denominator. Re-check deadline arithmetic, dependency edges, source dates, and `as-of` scope; fail
closed when a check cannot be performed. If a checklist or evidence source fails, preserve the
last draft, mark affected rows unknown or blocked, record the failure, and rerun after refresh.
Do not overwrite evidence or silently promote an inferred state to complete.
