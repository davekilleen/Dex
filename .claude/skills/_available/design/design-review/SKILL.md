---
name: design-review
description: Use when a design artifact or revision needs a prepared review packet or an evidence-backed record of a review outcome, requirements, and decisions.
role_groups: [design, product]
jtbd: |
  Design reviews need context and decisions get lost. This gathers project context
  and requirements, surfaces customer feedback related to design, prompts for key
  decisions and rationale, and documents outcomes so design choices are preserved.
time_investment: "20-30 minutes per review"
---

# Design review

## When to use

Use this skill in one explicitly selected mode:

- **Prepare mode:** assemble an evidence-backed review packet before a review.
- **Document mode:** record an outcome that an authoritative human source says was made.

Do not use it to make a design decision, edit the artifact, or infer approval from a
meeting invite or silence. Not for unscoped aesthetic preference, implementation work,
or publishing requirements and decisions without preview and human confirmation.

## Inputs and source discipline

- Start with the mode, review scope, timezone, and as-of date/time. Identify the artifact
  and exact version, revision, or snapshot; if the version is missing, say so and do not
  merge evidence from different iterations.
- Gather requirements, user stories, constraints, research, feedback, and prior decisions
  from named sources. Record source path or ID, source date, artifact location, and access
  date/as-of for each item.
- In document mode, identify the authoritative review record and decision authority. Do
  not infer participants, owners, intent, or approval from context.
- Keep evidence tied to the artifact version reviewed. A later revision is a new subject,
  not a correction to the old record.

## Method

1. Confirm prepare or document mode and the exact artifact/version under review.
2. Build a requirement-to-evidence trace: requirement, artifact location, supporting source
   and date, and observed/inferred/unknown status. Include contradictory requirements or
   feedback rather than silently choosing one.
3. Inspect the artifact and evidence read-only. Record strengths, risks, open questions,
   and traceable findings with confidence; do not add requirements that are not sourced.
4. In prepare mode, list options, trade-offs, and questions for human reviewers without
   selecting an option. In document mode, record only decisions explicitly stated by the
   authoritative source and label them proposed, accepted, or superseded as supported.
5. Separate recommendations from authorized decisions. A recommendation is not a human
   decision, and an unresolved question stays unresolved.
6. Draft the packet or outcome record with sources, dates, as-of provenance, unknowns, and
   contradictions. Preview the exact save before requesting confirmation.

## Truth and uncertainty rules

- **Observed:** a requirement, design detail, feedback item, or decision directly present in
  the cited artifact or dated source.
- **Inferred:** an interpretation of a design effect or requirement relationship; explain
  the evidence and confidence.
- **Unknown:** missing version, requirement, rationale, participant, authority, or outcome.
- **Stale:** evidence tied to an older artifact/version or outside the requested as-of
  boundary; do not apply it to a newer revision without re-checking.
- **Contradictory:** requirements, feedback, or review sources disagree; preserve the
  conflict and dates and ask the human authority to resolve it.

Never invent dates, metrics, percentages, owners, intent, money, causes, status, or
evidence. Never convert a suggestion into an accepted decision.

## Output contract

Return a review record containing:

- mode, review scope, artifact/version, timezone, as-of date/time, and source coverage;
- the requirement/evidence trace with source/date references and confidence;
- findings, options, trade-offs, unknowns, stale evidence, and contradictions;
- in prepare mode, recommendations and explicit decision questions;
- in document mode, only sourced proposed, accepted, or superseded decisions, with the
  authoritative source and date; never imply a decision where the record is unknown.

## Safety and write boundaries

Default to read-only in both modes. Do not edit design files, requirements, tickets, or
decision records while preparing or reviewing. A document-mode save or other action needs
an exact preview, explicit confirm, and human authority; perform only the confirmed write.
Recommendations do not authorize design changes or decisions.

## Verification and recovery

Read back the artifact/version and every requirement/evidence reference, then reconcile
decision labels, sources, dates, and as-of scope before delivery. After an authorized save,
read back the destination and reconcile it with the confirmed preview. If the artifact
changes, a version is stale, a source is contradictory, or a read fails, stop and mark the
affected item unknown or stale. If a write fails or is partial, preserve the draft and
error, report the exact state, and wait for human authority before retrying or recovering;
do not claim a decision was documented without read-back proof.
