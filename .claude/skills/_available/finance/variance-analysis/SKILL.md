---
name: variance-analysis
description: Use when explaining a dated actual-versus-budget or actual-versus-forecast variance for a comparable finance period. Not for tracking close checklist completion; use close-status.
role_groups: [finance, leadership]
jtbd: |
  Variances happen every month but documenting them takes time. This prompts for 
  key variances, helps you document explanations with context, links to supporting 
  materials, and prepares a board-ready narrative so you're ready for leadership 
  reviews.
time_investment: "20-30 minutes per analysis"
---

## When to use

Use when a finance or leadership user needs an evidence-backed explanation of actuals against
an approved budget or forecast for a named period, category, or total. Confirm the comparison
period and basis before calculating.

Do not use this skill to post or reclassify ledger entries, change a budget or forecast, approve
corrective action, or provide audit sign-off. Not for close-status tracking, tax advice, or a
financial decision made on behalf of a human owner.

## Inputs and source discipline

1. Capture the period, comparison basis, metric definition, actual source, budget/forecast source,
   source dates, date checked, and explicit `as-of` date. Record unit, currency, sign convention,
   and time window for every input; never invent a missing date or denominator.
2. Prefer reconciled ledger or close-package actuals, then an approved budget or forecast, then
   dated operational reports, then dated context in meeting notes. A narrative explanation is
   not evidence of a number. Preserve source hierarchy and contradictory inputs.
3. Validate that actual and comparison values measure the same category, period, unit, currency,
   accounting basis, and aggregation. Convert only with a cited rate or rule and date; otherwise
   mark the comparison not comparable rather than forcing a result.

## Method

1. Work read-only and state the formula before computing: for example, dollar variance as
   `actual - comparison`, and percentage variance as `variance / absolute comparison` only when
   the denominator is non-zero and that convention is authorized. Preserve the sign and state
   how favorable/unfavorable is determined for revenue versus expense; never flip signs to make
   a result look better.
2. Recalculate each category and reconcile the category variances to the supplied total,
   allowing only documented rounding. Investigate missing categories, scope differences, and
   duplicate rows; if totals cannot reconcile, report the total as unknown or contradictory.
3. Apply the supplied materiality threshold in both amount and percentage terms when available.
   If no threshold is supplied, state that materiality was not assessed; do not invent a cutoff
   or call a result material solely because it is visually large.
4. For each material or requested variance, classify the cause as `timing` or `permanent` only
   when dated evidence supports it. Label a plausible but unverified explanation hypothesized,
   and use unknown when evidence does not establish a cause. Keep corrective actions as
   recommendations for human review.

## Truth and uncertainty rules

Use `observed` for a value or event directly supported by a cited source, `inferred` for an
interpretation, `unknown` for missing evidence or an untestable cause, `stale` for evidence
outside the requested period or freshness, and `contradictory` when credible sources disagree.
Show confidence and its basis. Never invent dates, metrics, owners, intent, money, percentages,
causes, status, or evidence. A recommendation is not a human decision.

## Output contract

Return an analysis containing:

- period, comparison basis, `as-of` date, units, currency, formula, denominator, and sign rule;
- a category table with actual, comparison, dollar variance, percentage when valid, source/date,
  confidence, and comparability status;
- the materiality rule or an explicit not-assessed state;
- reconciled totals with rounding/scope differences called out;
- each cause labeled observed, inferred/hypothesized, timing, permanent, unknown, stale, or
  contradictory, with supporting source evidence; and
- source register, unknowns, contradictions, limits, and recommendations clearly separate from
  facts. Do not present an unverified cause as the explanation.

## Safety and write boundaries

Remain read-only by default. Do not edit ledgers, budgets, forecasts, source notes, or reports.
If a write, export, shared artifact, or other action is requested, preview the exact target,
changes, and side effects; redact secrets or unapproved personal/confidential content; wait for
explicit `confirm` from the responsible human authority; then perform only the approved action.

## Verification and recovery

Read back every input and calculated row, recompute the formula independently, and reconcile
category totals to the supplied total. Check sign, units, currency, period, denominator, source
dates, and `as-of` scope; fail closed on any mismatch. If a source read or calculation fails,
preserve the draft, mark the affected result unknown or blocked, record the failure, and rerun
after correction. Never silently overwrite a contradictory total or promote a hypothesis to fact.
