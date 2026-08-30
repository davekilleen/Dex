---
name: deal-review
description: Review active deals from canonical activity evidence and surface unknowns
role_groups: [sales, leadership]
jtbd: |
  You have several deals in flight and need to know which require attention without
  treating a file timestamp, silence, or missing value as sales truth.
time_investment: "5-10 minutes per review"
---

<!-- Generated from `.claude/skills/_available/sales/deal-review/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

## Purpose

Create a complete, dated review of the requested deal cohort. Surface evidence-backed
risks, missing next steps, deadlines, and unchecked deals while keeping unknowns
visible.

## Usage

- `/deal-review` — review the confirmed active-deal cohort
- `/deal-review [stage]` — filter through the configured stage map
- `/deal-review [period]` — filter by sourced close dates in a confirmed period

## Evidence, authority, and recovery

Set the review `as-of` timestamp and timezone first. Use the canonical activity date:
the actual timestamp on a meeting, call, email, CRM event, or other authoritative
record. Store its source ID/path and source date. A file modified date is only a weak
discovery clue and must not become an activity.

- Keep an explicit **Unchecked deals** section for every discovered record that is
  unreadable, duplicated, contradictory, or missing a required field. Never silently
  drop an unchecked deal or call it healthy.
- Unknown value must be excluded from value totals and amount-share denominators;
  never replace it with zero. An explicit zero remains eligible and is labelled.
- Disclose denominator coverage for every rate, count, or percentage: discovered,
  checked, eligible, and excluded rows.
- Keywords and silence are leads, not facts. Do not infer ghosting, churn, an absent
  buyer, or a blocker without dated source evidence.
- Never invent absent facts, dates, values, next steps, commitments, risks, or
  confidence.
- Keep the review read-only. Before any requested mutation, preview the exact target
  and payload/diff, require confirmation from the authorized human, and read back the
  result. If the write or read-back fails, report possible partial state and stop.

## Method

### 1. Confirm the cohort

Confirm the authoritative deal source, requested period, stage filter, currency/units,
and which states count as active. If active-state policy is absent, show discovered
states and ask rather than silently selecting a cohort.

Search configured deal locations and linked account/person records. Deduplicate only
on a stable deal ID or a human-confirmed mapping; similar names are not proof of
identity.

### 2. Build the deal ledger

For every discovered deal capture:

| Field | Handling |
|---|---|
| Deal ID and account | stable source identity |
| Value | amount, currency, source/date, or `Unknown` |
| Stage | configured value and source/date, or `Unknown` |
| Last activity | canonical event, event date, and source |
| Next step | exact text, owner, due date, and source |
| Close date | date and source, or `Unknown` |
| Stakeholders | sourced roles; do not infer missing roles |
| Risk evidence | exact dated observation, not a keyword alone |

Show contradictory records side by side and leave the field unresolved until a human
with authority decides.

### 3. Assess freshness from policy

Calculate elapsed time only from a canonical activity date. Apply `Fresh`, `Aging`,
`Stale`, or any urgency label only when the user supplies or confirms a dated
freshness policy for this cohort. Record that policy source in the report.

If no policy exists:

- report `Last canonical activity: [date / Unknown]`;
- report factual elapsed time where possible;
- set `Freshness assessment: Unknown — no confirmed policy`;
- offer a question, not a judgment.

### 4. Assess next steps, deadlines, and risk

A next step is complete only when the confirmed policy's required fields are present.
Without a policy, show the exact text and missing owner/date rather than assigning a
red/amber/green label.

For a requested deadline window, use sourced close and due dates. Do not assume a
timeline is realistic from stage alone.

Treat terms such as “blocked,” “competitor,” or “waiting” as search leads. Cite the
underlying sentence/event, distinguish fact from hypothesis, and show contradictions.
A risk classification needs either explicit source evidence or a configured rule.

### 5. Reconcile and verify

- Reconcile checked plus unchecked counts to the discovered cohort.
- Reconcile stage counts to eligible checked deals.
- Reconcile known-value subtotals to the known-value total.
- List all unknown-value exclusions.
- Verify each recommendation points to an observed fact or a named unknown.

## Output contract

```markdown
# Deal review

**As of:** [timestamp and timezone]
**Cohort definition:** [source/policy]
**Discovered / checked / unchecked:** [N / n / u]
**Known-value coverage:** [n/N; currency and exclusions]

## Needs attention
### [Deal]
- Stage: [value + source/date or Unknown]
- Last canonical activity: [event/date/source or Unknown]
- Freshness: [policy-backed label or Unknown]
- Next step: [exact sourced text or Unknown]
- Risk evidence: [fact / hypothesis / contradiction]
- Suggested question or action: [read-only recommendation]

## On track
[Include only when the configured policy is satisfied; cite the policy and evidence.]

## Unchecked deals
| Deal | Reason | Last successful source read |
|---|---|---|

## Pipeline distribution
[Counts and known values with explicit denominators and exclusions.]

## Unknowns and contradictions
- [Both sources/dates and what needs human resolution]

## Recommended actions
1. [Action tied to evidence; no write performed]
```

Placeholders define shape only. Never populate them from generic examples.

## Controlled follow-up

For a requested deal or task update:

1. read the authoritative current target;
2. preview the exact before/after values or payload;
3. identify related records that will not be changed;
4. require explicit human confirmation;
5. write only the confirmed target;
6. read back and compare every field with the preview.

On failure, preserve prior content where possible, re-read current state, disclose any
partial result, and require a fresh preview before retrying.
