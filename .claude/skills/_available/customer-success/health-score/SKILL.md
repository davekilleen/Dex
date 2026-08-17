---
name: health-score
description: Use when reviewing customer-account health with a configured scoring rubric and dated inputs, or when reporting why a portfolio cannot yet be scored. Not for finding expansion opportunities; use expansion-opportunities.
role_groups: [customer_success]
jtbd: |
  You manage many accounts and can't track them all manually. This scans customer
  account pages, identifies at-risk accounts (no recent contact, open issues),
  flags upcoming renewals, and suggests proactive outreach so you prevent churn before
  it happens.
time_investment: "10-15 minutes per review"
---

## When to use

Use for a named account segment or portfolio health review when the user supplies, or the account
system contains, a configured scoring rubric and dated inputs. If the rubric or required inputs
are absent, still use this skill to return `not scored` and a review of signals only.

Do not use this skill to infer churn from silence, replace customer-success judgment, assign a
health rating without its rubric, update CRM records, or contact a customer. Not for expansion
qualification, renewal pricing, or commercial commitments.

## Inputs and source discipline

1. Identify the account scope and `as-of` date. Require a configured scoring rubric with a named
   version/effective date, factors, weights, thresholds, freshness window, and missing-data rule;
   record its source, source date, date checked, and confidence. If it is missing, ambiguous, or
   stale, the result is `not scored`.
2. For each factor, capture a dated input, source, source date, date checked, unit if relevant,
   and freshness relative to the rubric. Prefer system records, dated customer outcomes, support
   events, and explicit account notes over assumptions. Preserve unknown, stale, and contradictory
   inputs rather than filling them from silence.
3. Treat no recent contact as an absence of evidence, not evidence of churn or risk. A silence
   signal may be listed for human review only when its date and source are clear.

## Method

1. Work read-only. Validate the rubric before reading scores: confirm factors, weights, thresholds,
   effective date, and missing-data behavior are complete and internally consistent.
2. Match each required factor to a dated input within the configured freshness window. Apply a
   partial-data rule only when the configured rubric explicitly permits it. Otherwise any required
   unknown, stale, or contradictory factor makes that account `not scored`; unknown is never red
   or green and must not be coerced to a favorable or unfavorable value.
3. When all required inputs are valid, calculate the score exactly as configured and preserve the
   rubric version with the result. Do not substitute an intuitive threshold or infer a score from
   engagement, silence, sentiment, renewal date, or a single event.
4. Produce a portfolio distribution only over accounts with valid scores and a stated denominator.
   Keep unscored accounts and their review signals in a separate list; recommendations remain for
   human review.

## Truth and uncertainty rules

Use `observed` for a dated input directly supported by a source, `inferred` for a review
interpretation, `unknown` for missing or insufficient data, `stale` for data outside the rubric's
freshness, and `contradictory` when sources disagree. State confidence and the rubric basis.
Never infer churn from silence. Never invent dates, metrics, owners, intent, money, percentages,
causes, status, or evidence. Recommendations are not human decisions.

## Output contract

Return a review containing:

- account scope, rubric source/version/effective date, `as-of` date, freshness rule, and sources;
- `not scored` at portfolio or account level whenever the rubric or required inputs are absent;
- scores and red/yellow/green labels only when the configured rubric and dated inputs support them;
- for each account, factor inputs with source/date, freshness, confidence, unknowns, stale data,
  contradictions, and the reason for any unscored result;
- a distribution with an explicit eligible-account denominator, or no distribution when unscored;
  and
- review signals and non-binding outreach recommendations clearly separate from score evidence.

## Safety and write boundaries

Remain read-only by default. Do not update health fields, CRM, account notes, tasks, or customer
communications. If a write, export, shared artifact, outreach, or other action is requested,
preview the exact target, content, audience, and side effects; redact secrets or unapproved
personal/confidential content; wait for explicit `confirm` from the authorized human owner; then
perform only that approved action. A score or recommendation is not human authorization.

## Verification and recovery

Read back the rubric, every scored input, formula, and output label. Recalculate each score,
reconcile scored-account counts and distribution totals to the eligible denominator, and check
source dates, freshness, units, and `as-of` scope; fail closed on any mismatch. If rubric or data
retrieval fails, preserve the review, return `not scored`, record the failure and affected signals,
and rerun after refresh. Never silently turn unknown into red or green.
