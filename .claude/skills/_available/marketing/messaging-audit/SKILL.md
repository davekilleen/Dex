---
name: messaging-audit
description: Use when comparing product or campaign messaging across content against a cited canonical baseline and its supporting evidence.
role_groups: [marketing, product, leadership]
jtbd: |
  Your messaging drifts over time as different people write content. This scans
  05-Areas/Content/, checks consistency across materials, identifies conflicts or gaps,
  and suggests refinements so your positioning stays tight and consistent.
time_investment: "15-20 minutes per audit"
---

# Messaging audit

## When to use

Use this skill when multiple artifacts need comparison for positioning, value proposition,
audience, terminology, or product claims and a canonical baseline can be cited. It also
handles an audit that discovers no usable baseline, provided that limitation is explicit.

Do not use it to invent positioning, approve legal or factual claims, or silently rewrite
brand copy. Not for publishing edits, changing the canonical baseline, or deciding that a
variation is intentional without evidence and human authority.

## Inputs and source discipline

- Identify the canonical baseline by source path or ID, version, source date, and as-of
  date/time. If no authority or version is available, record “no canonical baseline” as an
  unknown rather than choosing the most polished artifact.
- Build a source/date matrix for every compared artifact: title or ID, version, source,
  publication or update date, retrieval/as-of date, audience/channel, and scope.
- Extract claims, value propositions, audience descriptions, problem statements, benefits,
  and terms verbatim. Attach a source and date to each extracted item.
- Normalize terms only through an explicit, cited mapping. Preserve the original wording
  and do not treat similar words as equivalent when the source does not support that.

## Method

1. Confirm the audit question, scope, canonical baseline, versions, timezone if relevant,
   and as-of boundary.
2. Populate the source/date matrix and exclude inaccessible or out-of-scope artifacts from
   conclusions while reporting them as coverage limits.
3. Extract the baseline's claims and terminology, then extract the same fields from each
   artifact without paraphrasing away meaningful qualifiers.
4. Apply only cited term normalization and compare each artifact with the canonical
   baseline and with other in-scope artifacts.
5. Classify each difference as aligned, an intentional variation only when its purpose and
   authority are evidenced, contradictory, stale copy, missing, or an unsupported claim.
   Do not call a difference intentional merely because it sounds appropriate.
6. Trace every finding to its source/date entry, mark observed versus inferred meaning,
   state confidence, and surface unknowns and contradictions side by side.
7. Offer proposed refinements or questions. Show a preview before any edit, baseline change,
   or saved report and obtain explicit confirmation from the human authority.

## Truth and uncertainty rules

- **Observed:** exact copy, term, claim, baseline version, or source date present in an
  artifact or canonical source.
- **Inferred:** a semantic relationship or likely audience effect derived from observed
  wording; explain the inference and confidence.
- **Unknown:** intent, authority, claim support, version, or equivalence not evidenced.
- **Stale:** copy based on an older dated baseline or artifact outside the requested as-of
  boundary; do not call it a current contradiction without checking versions.
- **Contradictory:** sources make incompatible claims or definitions; preserve both wording,
  sources, dates, and any known scope difference.

An unsupported claim means “support was not found in the permitted sources”; it does not
prove the claim false. Never invent dates, metrics, percentages, owners, intent, money,
causes, status, or evidence. Recommendations are not human decisions.

## Output contract

Return an audit with:

- canonical baseline citation, version, source/date, as-of date/time, and authority status;
- the complete source/date matrix and declared artifact coverage;
- a normalized-terms table that preserves original wording and cited mappings;
- findings classified as aligned, intentional variation, contradiction, stale copy, missing,
  or unsupported claim, each with source, date, evidence, and confidence;
- unknowns, contradictions, coverage limits, and recommendations clearly separated from
  approved messaging decisions.

## Safety and write boundaries

Default to read-only. Do not rewrite, publish, approve, or replace canonical messaging;
do not edit content systems or claim authority over legal, product, or brand decisions. A
requested write requires a precise preview, explicit confirm, and human authority. Apply
only that confirmed scope; a recommendation remains a recommendation.

## Verification and recovery

Read back every finding against the cited artifact and reconcile wording, version, source,
date, and classification before delivery. After an authorized edit or saved report, read
back the destination and reconcile it with the confirmed preview and canonical baseline.
If a baseline or artifact cannot be read, mark dependent findings unknown; if a newer version
appears, mark prior comparisons stale and re-check. If a write fails or is partial, stop,
preserve the draft and error, report what changed, and wait for human authority before
retrying or recovering.
