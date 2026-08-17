---
name: tech-debt
description: Use when technical debt needs linked code or operational evidence, deduplication, first-seen provenance, or impact, effort, confidence, and cost-of-delay prioritization.
role_groups: [engineering, leadership]
jtbd: |
  Technical debt accumulates in scattered notes and code. This creates a deduplicated,
  evidence-linked inventory, distinguishes first-seen evidence from guessed age,
  assesses impact and effort with confidence, and escalates security concerns without
  pretending a recommendation is a decision.
time_investment: "15-20 minutes per review"
---

# Technical debt review

## When to use

Use this skill when a component, project, or portfolio needs a defensible technical-
debt inventory, duplicate cleanup, cost-of-delay comparison, or security-risk review.

Do not use it to modify code, close tickets, set a sprint commitment, or certify a
security issue as safe. Not for calling ordinary feature requests or unsupported
complaints technical debt without linked evidence.

## Inputs and source discipline

Set the review scope and as-of date/time. Search code, configuration, tests, build
logs, incident reviews, operational measurements, issue discussions, and dated notes.
For every candidate capture a source, source date, as-of date/time, stable locator
(path/line, commit, ticket, or record), and any freshness or access limitation.
Linked code and operational evidence should identify the underlying problem, not just
repeat a label such as "refactor later".

Keep first-seen provenance separate from current discovery. A dated source can support
`first-seen`; an undated mention cannot establish age. Record `first-seen: unknown`
when no dated evidence exists rather than guessing an age or inventing an aging bucket.

## Method

1. Gather candidates read-only and normalize each into one underlying debt item:
   affected component, debt mechanism, observable consequence, evidence links, and
   current scope. Keep a candidate if evidence is incomplete, but mark the gap.
2. Deduplicate by underlying problem, not by similar words. Merge only when the
   linked evidence supports the same failure mode or constraint; preserve every source
   link, alternate wording, and contradictory observation in the merged record.
3. Verify the evidence and first-seen date. Check whether code paths, runbooks,
   incidents, or operational symptoms still exist; mark stale evidence rather than
   deleting it. A first-seen date is not the date the debt began.
4. Assess each item separately for **impact**, **effort**, **confidence**, and **cost
   of delay**. State the basis and unit for any estimate. Impact may cover reliability,
   delivery friction, user harm, or security; effort needs an explicit basis; confidence
   describes evidence quality; cost of delay describes what is likely lost by waiting.
   Use unknown where the evidence cannot support a rating.
5. Check for security signals such as confidentiality, integrity, availability,
   authentication, authorization, or compliance exposure. A potential security issue
   needs security escalation through the approved human security path, with evidence,
   current status, and owner or `TBD`; do not bury it in a normal debt queue or invent
   severity.
6. Group items into decision options and recommendations for human review. A
   recommendation is not a human decision; do not promise prioritization, money,
   staffing, or delivery dates without authority and evidence.

## Truth and uncertainty rules

Label each item and rating as observed, inferred, unknown, stale, or contradictory as
appropriate. An observed code path or incident is not proof of impact magnitude; an
inferred risk is not a vulnerability finding. Preserve conflicting code and operational
signals and state what additional evidence would resolve them.

Never invent dates, metrics, owners, intent, money, percentages, causes, status, or
evidence. Do not use a first-seen date to claim the debt's true age, and do not turn a
missing estimate into zero effort or low impact.

## Output contract

Return an inventory with one stable item per underlying problem and, for each item:

- summary, component, scope, and linked code or operational evidence;
- all source citations with source date, as-of date/time, freshness, and first-seen
  date or `unknown`;
- duplicate group and the evidence for merging or keeping items separate;
- impact, effort, confidence, and cost of delay with basis and unknowns;
- security signal, escalation path/status, and owner or `TBD` when relevant;
- observed, inferred, stale, unknowns, and contradictions kept distinct; and
- recommendation, sequencing option, and explicit statement that it is not a human
  decision.

## Safety and write boundaries

The default is read-only. Do not edit code, create or close tickets, change security
records, alter priorities, or notify an owner from this skill alone. For any requested
write or escalation, preview the exact destination, content, and recipients; obtain
explicit confirmation from the human authority; then perform only that confirmed
action. Preserve source links and raw evidence when deduplicating.

## Verification and recovery

Read back the inventory after a confirmed write and reconcile item count, duplicate
groups, evidence links, first-seen fields, ratings, security flags, and source dates
with the read-only extract. Re-check that stale or contradictory evidence was not
silently removed and that no recommendation became status.

If a source link, read, write, or reconciliation check fails, stop and report the
failed check and affected item. Do not retry blindly, delete a candidate, or merge
records to hide the failure. Re-read the source and destination; recover with an
append-only correction or human-confirmed update, retaining the previous evidence and
marking the unresolved field unknown.
