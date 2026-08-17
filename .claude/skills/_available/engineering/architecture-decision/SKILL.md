---
name: architecture-decision
description: Use when a system or design choice needs an evidence-backed ADR, explicit alternatives and trade-offs, or review of proposed, accepted, or superseded decision history.
role_groups: [engineering, leadership]
jtbd: |
  Architecture decisions get made in meetings and lost. This provides an ADR method,
  prompts for evidence-backed alternatives and trade-offs, preserves decision history,
  and keeps human authority explicit before a decision is recorded.
time_investment: "20-30 minutes per decision"
---

# Architecture decision

## When to use

Use this skill when a material architecture choice, constraint, or reversal needs a
traceable Architecture Decision Record (ADR), or when an existing ADR's state and
rationale need review.

Do not use it for live incident response, implementation instructions that do not
require a design decision, or a decision that has no identifiable evidence or human
decision authority. Not for silently choosing on behalf of the team or rewriting
historical ADRs.

## Inputs and source discipline

Start with the decision question, scope, constraints, affected systems, decision
authority, and intended decision window. Treat a missing authority, constraint, or
date as unknown; ask for it or mark it TBD.

Build a source ledger before comparing options. For every material claim record the
source, source date, as-of date/time, locator, and freshness or access limitation.
Prefer directly inspected code, configuration, tests, measured operations, and dated
requirements; label meeting recollections and interpretations accordingly. Keep
conflicting sources linked rather than silently choosing one.

## Method

1. Read the relevant context in read-only mode. State the problem, desired outcome,
   non-negotiable constraints, decision deadline if evidenced, and what is outside
   scope.
2. Enumerate the status quo and credible alternatives. For each option capture
   supporting evidence, fit to constraints, benefits, costs, risks, reversibility,
   migration or operational burden, trade-offs, and unresolved unknowns.
3. Compare options with the same criteria. Record confidence for each material
   assessment and retain contradictions; do not manufacture a score, percentage, or
   cost when the source does not provide one.
4. Draft the ADR with one explicit state:
   - **Proposed** means the evidence-backed draft is awaiting human authority.
   - **Accepted** means the human decision authority explicitly approved the stated
     option and trade-offs; a recommendation is not approval.
   - **Superseded** means a later accepted ADR replaces it, with links in both
     directions. Preserve the earlier record as immutable history.
5. Present a recommendation as an option for the human decision authority. Do not
   change a proposed ADR to accepted, or create the canonical ADR, until that human
   authority confirms the action and the exact decision text.

## Truth and uncertainty rules

Label each claim as observed, inferred, unknown, stale, or contradictory. Observed
means the cited source directly supports it; inferred means reasoning from cited
facts; unknown means the evidence is absent; stale means the source may no longer
represent the decision context; contradictory means credible sources disagree.

Never invent dates, metrics, owners, intent, money, percentages, causes, status, or
evidence. Do not turn an inference into a constraint or an unknown into a risk score.
State which source would resolve each material unknown and do not hide disagreement
behind a single confidence number.

## Output contract

Return a decision brief or ADR containing:

- decision question, scope, constraints, as-of date/time, and decision authority;
- a source ledger with source, source date, citations, and freshness;
- alternatives, consistent comparison criteria, evidence-backed trade-offs, and
  confidence;
- state as Proposed, Accepted, or Superseded, with the approval or successor link
  required by that state;
- unknowns and contradictions, including their effect on the recommendation;
- implementation consequences and follow-up evidence, if known; and
- a clearly labelled recommendation that is not a human decision.

## Safety and write boundaries

The default is read-only. A write requires a preview of exact destination and content,
then explicit confirmation from the human decision authority before creation or
modification. Do not edit source code, configuration, tickets, or an accepted or
superseded ADR as part of this review. Do not claim that a proposed option is adopted
or send implementation instructions as if they were approval.

Keep ADR history append-only. If a historical record is wrong, preserve it and
propose a correction or successor for human review; never erase the evidence of the
earlier state. Recommendations are not human decisions, and no external action is
authorized by this skill alone.

## Verification and recovery

Before writing, read back the preview and reconcile the state, decision text,
authority, source citations, option links, and destination. After a confirmed write,
read back the persisted ADR and reconcile it with the approved preview and its
successor or predecessor links. Check that no unsupported date, status, or evidence
appeared.

If a read, write, or reconciliation check fails, stop and report the exact failure,
partial state, and missing evidence. Do not retry blindly or overwrite history.
Recover by re-reading the destination and source ledger; only a human-authorized
append, correction, or superseding ADR may resolve a partial or contradictory record.
