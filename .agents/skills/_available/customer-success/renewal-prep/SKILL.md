---
name: renewal-prep
description: Use when preparing an evidence-backed brief for an upcoming customer renewal from contract, ARR, dated outcomes, usage, and risk evidence. Not for health scoring; use health-score.
role_groups: [customer_success, sales]
jtbd: |
  Renewals sneak up and you're not prepared. This gathers account history and value 
  delivered, identifies expansion opportunities, flags risks or concerns, and creates 
  a renewal strategy so you maximize retention and growth.
time_investment: "20-30 minutes per renewal"
---

<!-- Generated from `.claude/skills/_available/customer-success/renewal-prep/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

## When to use

Use for a named account and upcoming renewal when the requester needs a traceable summary of
contract terms, ARR, value delivered, risk, unknowns, and preparation questions. Confirm the
account identity, renewal scope, and `as-of` date before gathering evidence.

Do not use this skill to renew or terminate a contract, set pricing, promise commitments, approve
strategy, update CRM, or communicate with the customer. Not for health scoring, legal contract
interpretation, or a commercial decision made on behalf of a human authority.

## Inputs and source discipline

1. Record account identity, contract/order form and amendments, renewal date/term, ARR or other
   commercial measure, currency, source dates, date checked, and explicit `as-of` date. Prefer
   the latest signed contract and amendments, then billing/ARR evidence, then CRM facts, then
   dated customer-success notes and customer communication. Cite every source; never invent a
   missing date, value, owner, or term.
2. Keep contract value, billed ARR, estimated value, usage, support events, and outcomes in
   separate fields. Reconcile units, currency, period, and account identity before comparing.
   Treat a CRM field as a lead to evidence, not proof when it conflicts with a signed source.
3. For value delivered, collect each **dated outcome** with its source, date, and relationship
   to the product. Do not turn activity, a positive sentiment, or an unverified claim into an
   outcome or ROI metric.

## Method

1. Work read-only and build an evidence ledger for contract/ARR/renewal facts, adoption and
   support context, and dated outcomes. State whether each item is observed, inferred, or a
   recommendation.
2. Verify the renewal date, term, notice conditions, and ARR from cited contract or billing
   evidence. Calculate any time-to-renewal only from the supplied reference date and state the
   date basis; if dates conflict, show the contradiction rather than selecting one silently.
3. Separate `risk` from `unknown`: call something a risk only when dated evidence shows a
   concern, exposure, or likelihood of an adverse renewal outcome; call it unknown when the
   evidence needed to assess it is missing, stale, or contradictory. Do not infer risk from
   silence alone.
4. Present pricing, commitments, packaging, strategy, and customer communication as options and
   approval questions. Include expansion ideas only when need and fit are sourced; never invent
   a value or imply that a recommendation is approved.

## Truth and uncertainty rules

Use `observed` for a contract fact, ARR value, or dated outcome directly supported by a source,
`inferred` for an interpretation, `unknown` for missing evidence, `stale` for evidence outside
the relevant period or freshness, and `contradictory` when credible sources disagree. State
confidence and its basis. Never invent dates, metrics, owners, intent, money, percentages,
causes, status, or evidence. Recommendations are not human decisions.

## Output contract

Return a renewal brief containing:

- account, contract/order form/amendment citations, ARR and currency, renewal date/term, `as-of`,
  source dates, and confidence;
- a value-delivered ledger of dated outcomes with evidence, plus clearly marked unknown ROI or
  unsupported claims;
- adoption/support context, risks with evidence, and unknowns kept in separate sections;
- pricing, commitments, strategy approval, and customer communication questions explicitly marked
  for human authorization;
- non-binding options and next checks with an owner only when that owner is sourced; and
- a source register, stale inputs, unresolved contradictions, and a clear list of evidence not
  found. Do not present the brief as an approved renewal plan.

## Safety and write boundaries

Remain read-only by default. Do not edit contracts, billing, ARR, CRM, pricing, commitments, or
customer records, and do not send customer communication. If a write, export, pricing change,
commercial action, or other communication is requested, preview the exact target, content,
audience, and side effects; redact secrets or unapproved personal/confidential content; wait for
explicit `confirm` from the authorized human owner; then perform only that approved action.

## Verification and recovery

Read back the contract, latest amendment, ARR evidence, renewal dates, and every cited dated
outcome. Reconcile ARR and currency to the contract/billing basis, check date arithmetic and
account identity, and fail closed when a check cannot be completed. If a source read fails or
evidence conflicts, preserve the brief, mark the affected conclusion unknown or blocked, record
the failure, and rerun after refresh. Never silently resolve a contract contradiction or promote
an inferred risk to fact.
