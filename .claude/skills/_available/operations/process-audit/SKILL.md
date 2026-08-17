---
name: process-audit
description: Use when an operational process needs its start, end, owner, outcome, representative sample, measured queues or handoffs, bottleneck evidence, or controlled improvement experiment made explicit.
role_groups: [operations]
jtbd: |
  Process reviews often rely on anecdotes and skip the queue or rework evidence needed
  to improve them. This defines measurable boundaries, samples representative work,
  finds bottlenecks from observations, and frames controlled experiments with success
  measures while keeping human authority explicit.
time_investment: "20-30 minutes per process"
---

# Process audit

## When to use

Use this skill when a repeatable process needs an evidence-backed health audit,
measured handoff and rework analysis, bottleneck diagnosis, or a controlled improvement
experiment.

Do not use it to change a live process, assign blame, impose a policy, or declare an
improvement successful from opinions alone. Not for a process with no explicit start,
end, owner, outcome, or observable sample unless those gaps are reported as unknown.

## Inputs and source discipline

Define the process boundary with an explicit start event, end event, owner, and desired
outcome. Record the review window, timezone, scope, as-of date/time, and source date
for the process definition. If ownership or outcome is not evidenced, use `TBD` or
unknown; do not infer it from a job title or the person who supplied notes.

Build a source ledger from representative records, timestamps, queue views, handoff
logs, rework records, support or operational data, and participant observations. For
each observation record the source, source date, as-of date/time, locator, timestamp
and timezone, sampling frame, and freshness. Separate directly observed measures from
participant interpretation.

## Method

1. State the start, end, owner, outcome, population, and review window. Make the
   intended outcome testable without assuming that the current process achieves it.
2. Select a representative sample. Document the sampling frame, inclusion and
   exclusion rules, time window, selection method, sample count, and known coverage
   gaps. Include normal and exceptional cases when the frame supports them; do not
   cherry-pick anecdotes. Record observations with citations and confidence.
3. Map the observed path from start to end. Measure active time, waiting time, queue
   size or age, handoff count and delay, rework count and reason, and outcome status
   using consistent units and timezone treatment. Keep missing measurements visible.
4. Apply a bottleneck method: compare stage throughput and capacity with queue volume,
   wait time, handoff delay, and rework. Call a bottleneck only when the measured
   constraint explains the observed delay or accumulation; otherwise label it a
   hypothesis and state what would test it.
5. Separate observed friction from inferred causes and list alternatives. Quantify
   impact only from the sample and source data; do not extrapolate beyond its coverage.
6. Frame a controlled experiment before action: hypothesis, proposed change, baseline
   or comparison, population, duration, owner or `TBD`, guardrails, stop condition,
   follow-up date, and a defined success measure with unit and time window. Human
   authority must approve the experiment; a recommendation is not a human decision.

## Truth and uncertainty rules

Label each boundary, observation, measure, and explanation as observed, inferred,
unknown, stale, or contradictory. A queue measure is evidence of queue state, not by
itself proof of cause; a participant opinion is not an observation. Preserve
contradictory records and explain sampling or instrumentation limits.

Never invent dates, metrics, owners, intent, money, percentages, causes, status, or
evidence. Do not invent a sample denominator, use an anecdote as representative, or
claim an experiment succeeded before its success measure is observed and reconciled.

## Output contract

Return an audit containing:

- explicit start, end, owner, outcome, scope, timezone, review window, and as-of
  provenance;
- sampling frame and representative-sample method, sample count, coverage limits, and
  cited observations;
- an observed flow with measured queues, waits, handoffs, rework, units, and source
  dates;
- bottleneck method, evidence, confidence, alternatives, unknowns, stale inputs, and
  contradictions;
- a controlled experiment proposal with baseline/comparison, owner or `TBD`,
  guardrails, duration, and a measurable success measure; and
- recommendations, clearly labelled as recommendations rather than human decisions,
  with sources, confidence, unknowns, and contradictions exposed.

## Safety and write boundaries

The default is read-only. Do not alter workflow rules, queues, assignments, policies,
records, or communications from an audit. For a requested experiment or other action,
preview the exact change, scope, owner, audience, and success measure; obtain explicit
confirmation from the human authority; then perform only the confirmed action. Do not
represent a proposed experiment as approved or active.

## Verification and recovery

Read back the audit and reconcile the start/end boundaries, owner, outcome, sample
count, denominator, measured queue/handoff/rework totals, source dates, timezone, and
success measure with the evidence ledger. After an experiment, read back its measured
result and reconcile it with the baseline, comparison, window, and guardrails before
claiming success.

If sampling, measurement, read, write, or reconciliation fails, stop and report the
failed check and affected stage. Do not retry blindly, discard inconvenient records,
or alter the denominator to make a result pass. Re-read the source and destination,
mark the result unknown or stale as appropriate, and recover through a human-confirmed
correction or a new controlled run with the failure retained.
