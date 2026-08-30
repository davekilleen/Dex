---
name: metrics-review
description: Use when a business or operational metric needs definition and source provenance checked, freshness and comparability validated, or an anomaly reviewed against a baseline and target.
role_groups: [operations, leadership]
jtbd: |
  Metric reviews can confuse stale, incomparable, or unexplained values with insight.
  This method preserves metric definitions and provenance, validates anomalies before
  interpretation, and separates evidence-backed observations from causal speculation.
time_investment: "10-15 minutes per review"
---

<!-- Generated from `.claude/skills/_available/operations/metrics-review/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

# Metrics review

## When to use

Use this skill for a dated review of one or more business or operational metrics when
the definition, unit, time window, baseline, target, freshness, comparability, or
anomaly status needs to be made explicit.

Do not use it to change a metric definition, target, dashboard, alert, or data source,
or to explain a result causally from correlation alone. Not for publishing a number
whose source, denominator, window, or as-of point is unknown.

## Inputs and source discipline

For each metric, identify the canonical metric definition, formula or counting rule,
unit, denominator or population, time window and timezone, source, source date, and
as-of date/time. Record freshness expectations, extraction time, revision policy, and
known exclusions. If a definition or unit is missing, report unknown rather than
substituting a familiar one.

Use a source ledger for the current value, comparison values, baseline, and target.
Link the query, report, dashboard, or export and record its source date and as-of
provenance. Do not mix values from different definitions, units, populations, windows,
or timezone cutoffs without marking them non-comparable.

## Method

1. Inventory the metric definition and scope in read-only mode. Confirm that the
   requested period is closed or label it provisional; record missing data and source
   freshness.
2. Validate freshness, completeness, and comparability before describing a trend.
   Check data cutoffs, late arrivals, revisions, missing denominators, definition or
   pipeline changes, unit conversions, population changes, and timezone boundaries.
3. Establish a baseline and target only from cited values with matching definitions,
   units, populations, and time windows. State whether each is observed, supplied, or
   unknown; never manufacture a baseline, target, or threshold.
4. Validate an anomaly before interpreting it. Re-read or rerun the source, compare
   with an independent source when available, inspect missingness and pipeline health,
   and record whether the deviation persists. A flagged anomaly is not a confirmed
   business event.
5. Interpret the validated observation with confidence and explicit alternatives.
   Make no causal claim without evidence that supports the causal link; correlation
   is not causation. List unknowns and contradictions instead of choosing a convenient
   explanation.
6. Offer recommendations for follow-up measurement or human review. A
   recommendation is not a human decision, and no target or action changes as a side
   effect of this review.

## Truth and uncertainty rules

Label metric values, comparisons, and explanations as observed, inferred, unknown,
stale, or contradictory. Mark a value stale when its freshness limit has passed or
the source is known to lag; mark comparability unknown when definitions or windows
cannot be reconciled. Keep an anomaly separate from its hypothesis about cause.

Never invent dates, metrics, owners, intent, money, percentages, causes, status, or
evidence. Do not round away a material unit or denominator difference, and do not make
causal claims without evidence merely because two series move together.

## Output contract

Return a review with, for every metric:

- metric definition, formula/counting rule, unit, population, time window/timezone,
  source, source date, and as-of date/time;
- freshness, completeness, and comparability checks with their evidence;
- current value, baseline, and target with matching provenance or explicit unknown;
- anomaly description, validation steps, persistence result, and confidence;
- observed facts, inferred explanations, unknowns, stale inputs, and contradictions;
- any correlation or causal interpretation clearly labelled and evidence-backed; and
- recommendations and follow-up checks clearly labelled as not human decisions.

## Safety and write boundaries

The default is read-only. Do not edit source data, definitions, targets, dashboards,
alerts, or reporting periods. For a requested write or notification, preview the exact
change, destination, and audience; obtain explicit confirmation from the human
authority; then perform only that confirmed action. Preserve the original value and
source when correcting a report.

## Verification and recovery

Read back the report and reconcile every displayed value, unit, denominator, time
window, timezone, baseline, target, and anomaly result against the source ledger. Re-
check freshness and comparability after any source refresh; verify that an explanation
did not become a causal claim without evidence.

If a source read, refresh, write, or reconciliation check fails, stop and report the
failed check, affected metric, and as-of point. Do not retry blindly or fill the gap
with a prior number. Re-read the source, mark the result stale or unknown as applicable,
and recover only through a human-confirmed correction with the failed check recorded.
