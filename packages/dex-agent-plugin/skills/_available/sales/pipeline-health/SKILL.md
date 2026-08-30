---
name: pipeline-health
description: Analyze pipeline coverage and forecast confidence from configured sales definitions
role_groups: [sales, leadership]
jtbd: |
  You need to understand whether the current pipeline can support a target without
  turning missing data or generic sales conventions into a confident forecast.
time_investment: "10-15 minutes per review"
---

<!-- Generated from `.claude/skills/_available/sales/pipeline-health/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

## Purpose

Produce a dated, evidence-backed view of pipeline coverage, velocity, conversion,
concentration, and forecast confidence. The skill calculates what the supplied data
supports and leaves policy judgments unknown when the team's definitions are absent.

## Usage

- `/pipeline-health` — review the current confirmed reporting period
- `/pipeline-health [period]` — review a named month, quarter, or date range
- `/pipeline-health forecast` — focus on explicit forecast categories and gaps

## Evidence, authority, and recovery

Set a report `as-of` timestamp before reading data. Attach field provenance to every
target, deal value, stage, probability, forecast category, date, benchmark, and
calculated claim: source path or record ID, source event date, and read as-of time.
A file modified time is only a discovery clue, never a substitute for a business
event date.

- Use only configured and confirmed stages, targets, probabilities, forecast
  categories, thresholds, and benchmarks for the requested period. Record the
  applicable configuration source and effective date. If one is absent, stale,
  contradictory, or unconfirmed, mark it `Unknown`; never invent a replacement or
  import a generic sales convention.
- Missing differs from zero. A blank, unreadable, absent, or conflicting value is
  `Unknown`; zero is valid only when the authoritative source explicitly records
  zero.
- A benchmark needs a source and date. Without one, show the factual metric and
  `Assessment: Unknown — no sourced benchmark`.
- Show denominator coverage for every percentage and rate. Verify arithmetic from
  raw numerators, denominators, stage subtotals, and deal-level contributions.
- Keep analysis read-only. A recommendation is not human authority. Preview any
  requested change, require explicit confirmation, then read back the result.
  If a write or read-back fails, report possible partial state, re-read the
  authoritative record, and wait for fresh human direction.

## Method

### 1. Confirm scope and policy

Confirm:

- reporting period, timezone, and as-of time;
- authoritative deal source and included pipeline;
- target and currency/units;
- stage map and stage-entry event;
- explicit forecast-category definitions;
- probability source, if weighted pipeline is requested;
- health, velocity, concentration, and conversion policies, if labels are requested.

Do not calculate across currencies or units without a sourced conversion rule. Do not
merge duplicate records until identity has been reconciled.

### 2. Build the source ledger

For each discovered deal, record:

| Field | Required evidence |
|---|---|
| Identity | stable deal ID and source |
| Value | amount, currency, source date |
| Stage | configured stage and canonical stage-entry date |
| Forecast | explicit category from the authoritative source |
| Probability | configured value and effective date |
| Close date | dated source or `Unknown` |
| Activity | canonical event date and source |

Keep an `Unchecked deals` section for unreadable, duplicate, or incomplete rows.
Do not silently remove them from the apparent pipeline.

### 3. Normalize without guessing

- Map a stage only through the confirmed stage configuration.
- Preserve contradictions side by side; do not choose the convenient value.
- Exclude unknown values from value totals and disclose the excluded count.
- Exclude deals with unknown probability from weighted totals.
- Keep explicitly recorded zero values in the eligible cohort.
- Use the canonical stage-entry event for velocity. If absent, velocity is unknown
  for that deal.

### 4. Calculate supported metrics

- **Coverage ratio:** known eligible pipeline value / confirmed target. This is a
  factual ratio, not a health label. Apply a label only when a configured or cited
  policy defines one.
- **Weighted pipeline:** sum of each known value multiplied by its configured,
  confirmed probability. Show included and excluded deal counts.
- **Stage conversion:** confirmed transitions / eligible prior-stage cohort for the
  same sourced period. State the cohort and exclusions.
- **Velocity:** elapsed time from canonical stage-entry events. Compare against a
  configured threshold or a clearly described historical distribution; otherwise
  show age without calling it slow.
- **Concentration:** show deal-level shares and the chosen cohort. Label a
  concentration risk only when a sourced policy defines that judgment.
- **Forecast totals:** use explicit source categories such as commit or best case.
  Never infer a forecast category from stage or probability.

Cross-check total pipeline against stage subtotals, percentage sums against eligible
denominators, and every gap sign against `target - forecast`.

### 5. Separate facts, judgments, and actions

For each finding, show:

1. observed metric and source coverage;
2. configured policy or benchmark used for any judgment;
3. unknowns and contradictory evidence;
4. recommended human action and why it follows;
5. evidence that would change the conclusion.

Never invent causes for a low conversion rate, silence from a buyer, or a likely close.
Offer questions to investigate instead.

## Output contract

```markdown
# Pipeline health

**Period:** [confirmed range and timezone]
**As of:** [timestamp]
**Target:** [value, currency, source/date or Unknown]
**Deals discovered / checked / unchecked:** [N / n / u]

## Forecast
| Category | Amount | Eligible coverage | Definition source |
|---|---:|---:|---|
| Commit | [amount or Unknown] | [n/N] | [source/date] |
| Best case | [amount or Unknown] | [n/N] | [source/date] |
| Weighted pipeline | [amount or Unknown] | [n/N] | [probability source/date] |

## Coverage and flow
| Metric | Result | Numerator / denominator | Assessment policy |
|---|---:|---|---|
| Coverage | [ratio or Unknown] | [raw values] | [source/date or Unknown] |
| Conversion | [rate or Unknown] | [n/N and period] | [benchmark or Unknown] |
| Velocity | [distribution or Unknown] | [eligible n/N] | [policy or Unknown] |

## Risks and unknowns
- [Evidence-backed risk, or Unknown with missing evidence]
- [Contradiction with both sources]
- [Unchecked deal and reason]

## Recommended questions or actions
1. [Action tied to a finding; no write performed]
```

Every populated value must trace to the source ledger. Placeholders are output shape,
not assumptions.

## Controlled changes

If the user asks to update a deal, target, probability, or stage configuration:

1. identify the authoritative target and current bytes/record;
2. show the exact before/after diff or API payload;
3. name downstream metrics that will change;
4. get explicit confirmation from the authorized human;
5. perform only that confirmed mutation;
6. read back the saved result and recalculate from the authoritative source.

A timeout, mismatch, or partial response is a failed change, never success.
