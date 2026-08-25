---
name: call-prep
description: Prepare a sourced, read-only brief for a person or account call
role_groups: [sales, customer_success]
jtbd: |
  You have a call coming up and need current context, commitments, and useful
  questions without invented objectives, objections, or commercial claims.
time_investment: "3-5 minutes per call"
---

<!-- Generated from `.claude/skills/_available/sales/call-prep/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

## Purpose

Build a concise call brief from dated person, account, deal, task, and interaction
evidence. Keep sourced context separate from suggested questions and unknowns.

## Usage

- `/call-prep [person]`
- `/call-prep [company]`

## Evidence, authority, and recovery

Set the call brief's `as-of` timestamp, timezone, participant, and call time. Make
freshness relative to that as-of time. For each interaction, commitment, signal,
account field, objective, and objection, record its source path or record ID and event
date. File modified time is not an event date.

- Treat an unknown objective and unknown objection as unknown. Write
  `Unknown — ask`; do not infer intent, buying stage, sentiment, priority, or likely
  objection from role, company, silence, or a generic sales pattern.
- Separate sourced facts, the user's stated goals, hypotheses, and suggested questions.
  A useful question is not evidence that its premise is true.
- Show contradictory sources and dates side by side. Do not silently choose one.
- Never invent facts, quotes, commitments, dates, outcomes, customer counts, product
  capabilities, prices, ROI, payback, rollout time, or integration claims.
- Keep call prep read-only by default. A recommendation is not permission to update a
  person, account, deal, or task.
- Preview any requested change, require explicit confirmation from the authorized
  human, then read back the saved record. If a write or read-back fails, report
  possible partial state and stop before retrying.

## Method

### 1. Resolve identity and call scope

Confirm the exact person/account and disambiguate duplicate names. Confirm:

- scheduled call time and timezone;
- participants and their sourced roles;
- call type only if supplied or recorded;
- the user's objective, if stated;
- the review window for prior interactions;
- authoritative sources for person, account, deal, and commitments.

If identity remains ambiguous, return the candidates and ask; do not merge records.

### 2. Build a source ledger

Collect only the context needed for this call:

| Item | Evidence rule |
|---|---|
| Person role | dated person/account source |
| Relationship | exact observations; no personality inference |
| Recent interactions | canonical event date and source |
| Commitments | exact owner, due date, status, source |
| Deal/account state | authoritative record and source date |
| Pain or request | quote-safe summary tied to an interaction |
| Product/commercial claim | current authoritative product or commercial source |

Deduplicate repeated meeting or CRM records by stable ID. Preserve materially
different accounts and contradictions.

### 3. Check freshness and completeness

For each source, show event date and read as-of time. Apply a `stale` label only if
the user or account policy defines a freshness rule; otherwise show elapsed time and
`Freshness assessment: Unknown`.

Mark these explicitly when absent:

- `Call objective: Unknown — ask the caller`
- `Customer objective: Unknown — ask on the call`
- `Potential objections: Unknown — no sourced objection`
- `Account health: Unknown — no configured rubric/current result`
- `Next decision: Unknown`

Do not convert missing evidence into a negative assessment.

### 4. Prepare discussion material

Discussion points must trace to a source. Suggested questions may explore an unknown,
but must be phrased without assuming the answer.

Good shape:

- **Observed:** “[dated source summary]”
- **Unknown:** “[specific missing fact]”
- **Question:** “[neutral question to resolve it]”
- **Why now:** “[link to call objective or commitment]”

Commercial responses must use current approved material. If price, ROI, rollout,
customer proof, or product support is not sourced, say `Unknown — verify before use`
and do not improvise.

### 5. Verify the brief

Before presenting:

- reconcile every commitment with its owner and due date;
- check links point to the records actually read;
- ensure dates use one stated timezone;
- ensure every quote is exact or clearly paraphrased;
- ensure no suggested objection appears as a fact;
- ensure desired outcomes are the user's stated goals, not invented intent.

## Output contract

```markdown
# Call prep: [person] — [company]

**Call:** [time and timezone]
**Brief as of:** [timestamp]
**Identity evidence:** [source/date]
**Call objective:** [user-stated source or Unknown]

## What is known
- [Fact] — [source, event date]
- [Fact] — [source, event date]

## Recent interactions
| Date | Interaction | Decisions/commitments | Source |
|---|---|---|---|

## Open commitments
| Owner | Commitment | Due/status | Source/date |
|---|---|---|---|

## Unknowns and contradictions
- [Unknown or both conflicting sources/dates]

## Questions to ask
1. [Neutral question tied to an unknown]
2. [Question tied to a sourced objective]

## Talking points
- [Sourced point, with approved claim source]
- [Unknown — verify before use]

## Desired outcome
- [User-stated goal or Unknown]

## Quick links
- [Only records actually read]
```

Placeholders define structure only; they are not sample facts.

## Controlled follow-up

After the call, offer a separate update plan. For each requested write:

1. identify the exact target;
2. show the complete before/after diff or payload;
3. separate independent writes so one approval does not authorize another;
4. require explicit human confirmation;
5. perform only the confirmed write;
6. read back and reconcile it with the preview.

On failure, keep the brief unchanged, disclose possible partial state, re-read the
target, and require a fresh preview before any retry.
