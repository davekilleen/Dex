---
name: roadmap
description: Review roadmap status, evidence freshness, blockers, and alignment
role_groups: [product, operations]
jtbd: |
  You need an honest roadmap view that separates current status from stale or missing
  evidence and does not turn silence into a blocker or a health score.
time_investment: "10-15 minutes per review"
---

<!-- Generated from `.claude/skills/_available/product/roadmap/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

## Purpose

Produce a dated, source-backed roadmap review across the confirmed project cohort.
Surface explicit blockers, alignment gaps, evidence freshness, and unknown status
without inventing an aggregate health judgment.

## Usage

- `/roadmap` — review the confirmed roadmap cohort
- `/roadmap [pillar]` — filter by an exact configured pillar

## Evidence, authority, and recovery

Treat the review as an evidence report, not a projection.

- Use the canonical status source and status date from each project record. Record the
  path/ID, status date, and review as-of time. Filesystem modified time is only a
  discovery clue, never a replacement status date.
- Cite source evidence for every status, blocker, milestone, pillar, alignment claim,
  and feedback item. If sources contradict, show both source dates and leave the field
  `Unknown`.
- Unknown is distinct from blocked. Use `Blocked` only when the canonical source
  explicitly identifies an unresolved dependency preventing progress.
- Define every denominator and disclose excluded projects. If the cohort or status is
  incomplete, report counts and coverage rather than a percentage or health score.
- Never invent status, dates, blockers, dependencies, milestones, tags, feedback,
  counts, or health scores.
- Keep analysis read-only. Preview requested changes, require explicit human authority,
  read back the target, and fail honestly on any mismatch.

## Method

### 1. Confirm scope

Confirm:

- review as-of date and timezone;
- canonical project locations;
- which project states belong on the roadmap;
- requested pillar filter;
- strategic pillar and quarterly-goal sources;
- review window for stakeholder feedback;
- configured freshness policy, if the user wants freshness labels.

Without a confirmed freshness policy, show the status age but label the assessment
`Unknown — no confirmed freshness policy`.

### 2. Build the project ledger

For every discovered project capture:

| Field | Required evidence |
|---|---|
| Project identity | stable path/ID |
| Status | explicit value, status date, source |
| Milestone | exact dated source or `Unknown` |
| Blocker | explicit dependency and source, or `Unknown` |
| Pillar | exact configured tag and source |
| Goal alignment | cited relationship, not name similarity |
| Feedback | dated speaker/source and quote-safe summary |

Keep an `Unchecked projects` section for unreadable, duplicate, or contradictory
records. Do not silently remove them from totals.

### 3. Classify without inference

- `In progress`, `Completed`, and `Blocked` require an explicit canonical status.
- An old status remains the last observed status plus a freshness caveat; age alone
  does not prove a blocker.
- A keyword match is a lead. Read the surrounding source and distinguish an actual
  dependency from discussion or historical text.
- Missing pillar means `Unknown alignment`, not automatically misaligned.
- Meeting feedback corroborates a project record; it does not silently replace it.

Apply a freshness or alignment label only through a configured or cited rule. Record
the rule's source and effective date.

### 4. Reconcile the roadmap

Verify:

- discovered = checked + unchecked;
- status counts reconcile to eligible checked projects;
- pillar counts reconcile to projects with known valid pillars;
- unknown-status and unknown-alignment projects are disclosed;
- every blocker count points to explicit blocker evidence;
- every percentage shows numerator, denominator, timeframe, and exclusions.

### 5. Recommend questions and actions

Separate:

1. observed facts;
2. contradictions and unknowns;
3. policy-backed assessments;
4. read-only recommendations;
5. human decisions.

Do not infer priority from recency, meeting volume, or the number of mentions. If a
priority source is missing, ask which source governs it.

## Output contract

```markdown
# Roadmap review

**As of:** [timestamp and timezone]
**Cohort:** [definition and source]
**Projects discovered / checked / unchecked:** [N / n / u]
**Freshness policy:** [source/date or Unknown]

## Active initiatives
### [Project]
- Canonical status: [value + source/status date or Unknown]
- Evidence freshness: [elapsed time; policy-backed label or Unknown]
- Next milestone: [value/source or Unknown]
- Pillar and goal alignment: [evidence or Unknown]
- Explicit blockers: [evidence or None observed; never inferred from silence]

## Attention and unknowns
- [Contradiction, missing status, explicit blocker, or unknown alignment]
- Evidence needed: [specific source or human decision]

## Stakeholder feedback
- [dated source and quote-safe summary; relationship to project]

## Evidence summary
Render one row per observed canonical status, including `Completed` when it is
observed. Do not force projects into a fixed list. Add `Unknown` for projects
without canonical status evidence, and reconcile every row to the checked cohort.

| Status | Count | Eligible denominator | Exclusions |
|---|---:|---:|---|
| [Observed canonical status, for example Completed] | [n] | [n/N] | [unknown/unchecked] |
| Unknown | [n] | [N] | [reasons] |

## Recommended actions
1. [Evidence-backed question or action; no write performed]
```

The output has no aggregate health score unless the user supplies a configured,
source-backed rubric and explicitly asks for it.

## Controlled changes

Before updating a project or creating a roadmap document:

1. identify the authoritative target and current content;
2. preview the exact operation and complete diff;
3. name any linked project, goal, or pillar records that will remain unchanged;
4. require explicit human confirmation;
5. perform only the approved write;
6. read back the target and compare it with the confirmed preview.

If writing fails or read-back differs, preserve prior content, report possible partial
state, re-read the target, and present a corrected preview for fresh confirmation.
