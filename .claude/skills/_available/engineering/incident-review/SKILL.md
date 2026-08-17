---
name: incident-review
description: Use when a service or operational incident needs a cited, timezone-aware timeline, blameless learning review, or prevention actions with accountable follow-up.
role_groups: [engineering, operations]
jtbd: |
  Incidents happen and learnings get lost without disciplined review. This separates
  cited facts from hypotheses and contradictions, preserves a timezone-aware timeline,
  and turns prevention ideas into evidence-backed follow-up without assigning blame.
time_investment: "30-45 minutes per incident"
---

# Incident review

## When to use

Use this skill after or during a contained incident when people need a trustworthy
timeline, impact record, contributing-conditions analysis, and prevention follow-up.

Do not use it as a substitute for live containment, paging, emergency escalation, or
security/legal reporting. Not for attributing personal blame, filling gaps with a
plausible root cause, or reviewing an event without cited evidence.

## Inputs and source discipline

Collect an incident identifier, review scope, start and end bounds, affected systems,
and the review as-of date/time. Use a named IANA timezone when available and preserve
each source's original timestamp and timezone or offset.

Create an evidence ledger for logs, alerts, deploy records, traces, tickets, support
reports, communications, and interviews. For every event or impact claim record the
source, source date, as-of date/time, locator, timestamp precision, and freshness.
Record missing sources and access limits as unknown rather than compensating with
memory. Keep raw evidence separate from analysis.

## Method

1. Define the incident boundary and affected service or users from cited evidence.
   Do not invent severity, duration, counts, percentages, or business impact.
2. Build a timezone-aware timeline. Preserve the reported timestamp and timezone,
   add a normalized timestamp only when conversion is valid, and cite the source for
   every row. If two credible sources disagree, retain both rows and mark the point
   contradictory instead of forcing an order.
3. Separate **facts** (directly observed or cited), **hypotheses** (inferred
   explanations), **unknowns**, **stale evidence**, and **contradictions**. Test a
   hypothesis against available evidence; do not call it a cause or root cause until
   the evidence supports that wording.
4. Use a blameless method: describe system conditions, incentives, interfaces,
   safeguards, detection, response, and recovery. Name actions and controls, not
   people as the cause. Explain what was reasonable to know at the time.
5. Define prevention and detection actions with the failure mode they address, a
   proof or acceptance measure, a follow-up date only when evidenced, and an owner.
   Use `TBD` for an unassigned owner or date; never guess an owner or make a status
   claim from an unchecked task list.
6. Present recommendations and follow-up choices to the human authority. A
   recommendation is not a human decision, and prevention work is not complete until
   its proof is read back.

## Truth and uncertainty rules

Use the labels observed, inferred, unknown, stale, and contradictory on the timeline
and analysis. A fact is not a hypothesis; a hypothesis is not a confirmed cause.
When evidence is missing or timestamps cannot be reconciled, say so, preserve the
conflict, and state what would resolve it.

Never invent dates, metrics, owners, intent, money, percentages, causes, status, or
evidence. Do not turn a plausible narrative into a fact, and do not use silence in a
log as proof that an event did not happen. Make confidence proportional to cited
evidence.

## Output contract

Return a review containing:

- incident scope, as-of time, timezone, systems, and impact claims with citations;
- a timezone-aware fact timeline with original timestamps, source/date provenance,
  confidence, and contradictory rows retained;
- separate Facts, Hypotheses, Unknowns, Stale evidence, and Contradictions sections;
- a blameless account of contributing system conditions and detection/response gaps;
- prevention and detection actions with owner or `TBD`, proof measure, follow-up, and
  current status only when observed; and
- source links, confidence, unknowns, contradictions, and a recommendation clearly
  labelled as non-decision guidance.

## Safety and write boundaries

The default is read-only. Preview the exact report or task changes, obtain explicit
confirmation from the human authority, and only then write or initiate an action.
Do not page people, change production systems, close incident records, assign owners,
or send external communications from an unconfirmed recommendation. Preserve raw
incident evidence and avoid exposing sensitive details beyond the review need.

## Verification and recovery

Read back the completed review and reconcile every timeline row's timezone, ordering,
source citation, impact statement, action owner, proof measure, and status with the
source ledger. Re-check that hypotheses remain labelled and that no unsupported cause
or date entered the document.

If a read or write fails, stop, report the failure and any partial output, and retain
the raw evidence. Re-read the destination before retrying; do not overwrite a partial
review or silently drop contradictions. Recovery consists of an append-only correction
or follow-up update after human confirmation, with the failed check and new evidence
recorded.
