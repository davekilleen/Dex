---
name: expansion-opportunities
description: Use when reviewing customer accounts for evidence-backed expansion hypotheses based on current usage, product fit, and expressed needs. Not for renewal strategy or negotiation; use renewal-prep.
role_groups: [customer_success, sales]
jtbd: |
  You're focused on retention and miss expansion opportunities. This reviews active 
  accounts, identifies product usage patterns, suggests expansion based on needs 
  expressed, and prioritizes by likelihood so you systematically grow accounts.
time_investment: "15-20 minutes per review"
---

## When to use

Use for a portfolio or named-account review when the requester wants possible upsell, cross-sell,
or seat-expansion opportunities grounded in account evidence and a customer-expressed need.
Confirm the account scope and review `as-of` date before scanning.

Do not use this skill to edit CRM records, create pipeline commitments, contact a customer, quote
pricing, promise an expansion, or decide commercial strategy. Not for renewal negotiation or a
health-score decision; use renewal-prep or health-score for those jobs.

## Inputs and source discipline

1. Establish account identity, scope, and `as-of` date. Record each source, source date, date
   checked, unit/currency, and account identifier. Prefer current customer statements and signed
   entitlements, then CRM/account facts, product telemetry, support records, and dated internal
   notes. Do not merge conflicting accounts by name alone.
2. Keep four evidence lanes separate:
   - **account evidence:** observed product, seat, usage, contract, or organizational facts;
   - **expressed need:** a dated customer request, pain point, or desired outcome, quoted or cited;
   - **product fit:** a source-backed mapping from that need to an available product capability;
   - **speculation:** an untested hypothesis, never presented as customer intent.
3. Show potential value only when price, quantity, currency, and calculation basis are sourced
   and comparable. Otherwise write `unknown` and explain the missing input; never invent potential
   value, likelihood, budget, percentage, owner, or urgency.

## Method

1. Work read-only and deduplicate account records before ranking. Preserve account-level source
   references and label whether each statement is observed, expressed, fit-checked, or speculative.
2. For each candidate, test product fit against a dated, authoritative capability or entitlement
   source. A usage gap can be evidence for investigation but is not an expressed need. If the
   capability or eligibility is not verified, mark fit unknown.
3. Classify the candidate as upsell, cross-sell, or seat expansion only when the account evidence
   supports that category. Rank by evidence completeness and sourced timing signals, not by an
   invented probability. Treat any suggested next step as a recommendation for human review.
4. Calculate an aggregate only when all included values share a documented unit, currency,
   period, and basis. If any value is unknown or incomparable, report the aggregate as unavailable
   rather than filling the gap.

## Truth and uncertainty rules

Use `observed` for account evidence directly supported by a source, `inferred` for a fit
interpretation, `unknown` for missing or unverified need/fit/value, `stale` for evidence outside
the relevant freshness or `as-of` period, and `contradictory` when sources disagree. Keep
speculation visibly separate from evidence, state confidence, and never infer intent from silence
or usage alone. Never invent dates, metrics, owners, intent, money, percentages, causes, status,
or evidence. Recommendations are not human decisions.

## Output contract

Return a review containing:

- account scope, `as-of` date, source register, source dates, and account identifiers;
- one row per candidate with separate account evidence, expressed need, product fit, and
  speculation fields;
- sourced potential value and calculation basis, or explicit `unknown`/unavailable value;
- category, evidence completeness, confidence, stale inputs, unknowns, and contradictions;
- human-review questions and non-binding recommendations, with no invented pipeline total; and
- a clear statement of what was not checked or cannot be concluded.

## Safety and write boundaries

Remain read-only by default. Do not change CRM, account pages, opportunities, pricing, forecasts,
or customer records. If a CRM change, outreach, quote, pricing action, or other commercial action
is requested, preview the exact target, fields/content, audience, and side effects; redact secrets
or unapproved personal/confidential content; wait for explicit `confirm` from the authorized
human owner; then perform only that approved action. A recommendation never authorizes a human
or commercial decision.

## Verification and recovery

Read back account identifiers, evidence citations, product-fit references, and any value formula.
Reconcile duplicate accounts, category counts, units, currency, period, and aggregate totals;
fail closed on mismatches. If a source or CRM read fails, preserve the review, mark the affected
candidate unknown or blocked, record the failure, and rerun after refresh. Never silently merge
accounts or turn speculation into a CRM fact.
