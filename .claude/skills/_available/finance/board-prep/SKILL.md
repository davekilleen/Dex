---
name: board-prep
description: Use when preparing a finance draft for a board or leadership review from dated actuals, budgets, forecasts, cash data, and decision context. Not for detailed line-item variance analysis; use variance-analysis.
role_groups: [finance, leadership]
jtbd: |
  Board meetings require pulling together financial narrative from multiple sources. 
  This gathers recent variance analyses, pulls key decisions and context, structures 
  a board-ready narrative, and identifies questions the board might ask so you're 
  fully prepared.
time_investment: "30-45 minutes per board meeting"
---

## When to use

Use for a named board or leadership meeting when the requester needs a traceable financial
snapshot, variance narrative, forecast limits, and questions for human review. Confirm the
reporting period and meeting scope before gathering data.

Do not use this skill to close the books, post or alter accounting entries, certify an audit,
approve a forecast, make a board decision, or send materials externally. Not for tax, legal,
fundraising, or investor filings that require an authorized professional process.

## Inputs and source discipline

1. Record the requested period, meeting date if supplied, reporting timezone/fiscal calendar,
   and an explicit `as-of` date. Never invent a missing date; mark it unknown and ask for it.
   For every input record the source, source date, date checked, scope, unit, and currency.
2. Prefer reconciled ledger or close-package actuals, then an approved budget or forecast,
   then dated management reports, then dated meeting notes or user statements. Treat meeting
   context as context, not as proof of a financial number. Keep conflicting sources visible.
3. Keep actuals, budget, forecast, and scenario values in separate fields. Normalize units or
   currency only with an explicit conversion source, rate, and date; otherwise report them as
   incomparable. Do not turn a missing value into zero.

## Method

1. Start read-only with a source inventory. Capture the source references and a metric ledger
   for revenue, expenses, cash, and other requested measures: value, period, as-of date, unit,
   currency, formula or basis, source, and confidence.
2. Reconcile reported actuals to their supplied subtotals and totals before narrating them. Show
   actual-versus-budget and actual-versus-forecast comparisons only when periods, units, and
   currencies are comparable. Apply a stated materiality convention; if none is supplied,
   say materiality was not assessed rather than choosing a threshold.
3. Describe only evidenced changes. Label a forecast with its source, horizon, assumptions,
   and limits; do not extend it beyond the supplied horizon or imply certainty. Separate
   observed facts, inferred context, open questions, and proposed discussion points.
4. Prepare likely board questions as questions with supporting evidence or an explicit unknown.
   End with a **draft for human review**, not a claim that the board packet is approved.

## Truth and uncertainty rules

Use `observed` for a value directly supported by a cited source, `inferred` for an
interpretation, `unknown` when evidence is missing, `stale` when the source is outside the
requested freshness or period, and `contradictory` when credible sources disagree. State
confidence and the reason for it. Never invent dates, metrics, owners, intent, money,
percentages, causes, status, or evidence. A recommendation remains a recommendation, not a
human decision.

## Output contract

Return a draft with:

- scope, reporting period, meeting context, and `as-of` date (or an explicit unknown);
- a financial snapshot whose every number carries unit, currency, period, source, and confidence;
- reconciled actuals, comparison formulas, forecast horizon and forecast unknowns/limits;
- material changes, evidenced context, inferred explanations, open questions, and board Q&A;
- a source register with source dates, checked dates, confidence, unknowns, stale inputs, and
  every unresolved contradiction; and
- a clear **draft for human review** marker plus decisions that require human authority.

## Safety and write boundaries

Remain read-only by default. Do not edit source files, accounting systems, board documents, or
send communications. If a write, export, shared artifact, or other action is requested, show a
preview naming the exact target, content, and side effects; check for and redact secrets or
unapproved personal/confidential content; wait for explicit `confirm` from the responsible human
authority; then perform only the approved action through an authorized path. Never treat the
draft or its recommendations as approval.

## Verification and recovery

Read back the assembled draft and compare each figure to its cited source. Reconcile line items
to totals, check formulas, units, currency, period, and `as-of` scope, and fail closed when any
check cannot be completed. If a source is unavailable or two sources remain contradictory,
preserve the draft, mark the affected result unknown or blocked, record the failure, and rerun
after the source is refreshed; do not silently overwrite or resolve the discrepancy.
