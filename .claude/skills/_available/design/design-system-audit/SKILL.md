---
name: design-system-audit
description: Use when assessing use of named design-system components or tokens across a defined sample of product artifacts, including adoption and deviation questions.
role_groups: [design, product]
jtbd: |
  Design systems drift and gaps appear. This scans projects for design system
  mentions, identifies inconsistencies or gaps, suggests components to build, and
  tracks adoption so your design system stays healthy and useful.
time_investment: "20-30 minutes per audit"
---

# Design-system audit

## When to use

Use this skill when a named design system has a canonical component or token source and
the requester can define the artifact sample and as-of boundary. It can assess adoption,
coverage, repeated patterns, deviations, and documented exceptions without changing them.

Do not use it to define a new system, refactor product work, approve an exception, or
claim organization-wide adoption from an undeclared sample. Not for editing components,
tokens, design files, code, or adoption records without a separately confirmed action.

## Inputs and source discipline

- Identify the canonical component and token sources, version, source date, and as-of
  date/time. Record the rule that makes a component or token canonical; if the source is
  missing or contradictory, keep adoption unknown.
- Declare the sample and coverage: population if known, eligibility rule, included and
  excluded artifacts, artifact/version dates, and inspection method. Do not call a sample
  representative without evidence for that claim.
- Define adoption numerator and denominator before counting. Record the adoption source,
  source date, retrieval/as-of date, and items that are uncountable; never invent a
  denominator or percentage.
- Locate exception records and their rationale, authority, version, and date. Treat a
  local pattern as an observation, not an approved exception, unless the source says so.

## Method

1. Confirm the canonical sources, versions, sample boundary, coverage declaration, timezone
   if relevant, and as-of date/time.
2. Inspect the declared sample read-only. Record exact canonical component/token usage by
   stable artifact and location, and mark unreadable or ambiguous cases unknown.
3. Apply the declared adoption definition. Reconcile numerator and denominator from eligible
   artifacts only; report excluded, duplicate, and uncountable items separately.
4. Compare observed usage with the canonical version. Classify a deviation only when the
   canonical rule supports that classification and no approved exception covers it.
5. Classify an intentional exception only with an explicit rationale, authority, source,
   and date. Otherwise distinguish unsupported deviation, possible equivalence, stale
   documentation, and unknown rather than guessing intent.
6. Identify repeated patterns and coverage gaps, state confidence and evidence, and offer
   recommendations as proposals. Do not approve a component, exception, or roadmap item.
7. Show a complete report preview before any requested save or downstream action and obtain
   explicit confirmation from the human authority.

## Truth and uncertainty rules

- **Observed:** canonical version, component/token usage, artifact membership, exception
  record, or count directly present in a dated source.
- **Inferred:** likely equivalence, adoption barrier, or repeated pattern derived from the
  sample; state the reasoning and confidence.
- **Unknown:** missing canonical rule, unreadable artifact, incomplete sample, denominator,
  exception rationale, or authority.
- **Stale:** usage or exception evidence tied to an older canonical version or outside the
  requested as-of boundary.
- **Contradictory:** canonical sources, artifact records, or exception records disagree;
  show versions and dates instead of resolving the conflict silently.

Never invent dates, metrics, percentages, owners, intent, money, causes, status, or
evidence. A recommendation is not an approval or human decision. Do not report an adoption
percentage when the denominator is not reliable.

## Output contract

Return an audit with:

- canonical component/token sources, versions, source dates, as-of date/time, and authority;
- declared sample, coverage, eligibility rule, exclusions, and inspection limitations;
- component/token usage findings with artifact/version/source/date trace and confidence;
- adoption numerator, denominator, calculation rule, uncountable items, or an explicit
  unknown when calculation is unsupported;
- deviations, documented intentional exceptions, stale evidence, unknowns, contradictions,
  and recommendations separated from approvals or implementation decisions.

## Safety and write boundaries

Default to read-only. Do not change canonical components, tokens, artifacts, code, exception
records, or adoption metrics. Any requested write or downstream action requires a precise
preview, explicit confirm, and human authority; execute only that approved scope. A gap
recommendation does not authorize refactoring or exception approval.

## Verification and recovery

Read back the canonical versions, sample manifest, artifact references, exception records,
and counts, then reconcile duplicate handling, numerator, denominator, and coverage before
delivery. After an authorized save, read back the destination and reconcile it with the
confirmed preview. If a canonical source changes, mark affected findings stale and rerun
the impacted sample; if a source or artifact cannot be read, mark the result unknown. If a
write fails or partially succeeds, stop, preserve the preview and error, report the exact
state, and obtain human authority before retrying or recovering.
