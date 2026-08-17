---
name: audience-intel
description: Use when synthesizing dated customer conversations, feedback, or behavior evidence into audience or persona insight, especially when sources are numerous, repeated, time-bounded, or disagree.
role_groups: [marketing, product]
jtbd: |
  Understanding your audience requires synthesizing insights from customer conversations,
  feedback, and behavior patterns. This reviews recent interactions, identifies persona
  patterns, surfaces pain points and motivations, and updates your audience understanding
  so marketing stays targeted and relevant.
time_investment: "10-15 minutes per review"
---

# Audience intelligence

## When to use

Use this skill for a defined audience question and a bounded set of customer evidence:
conversations, feedback, support notes, research, or behavior records. It can produce
an evidence-backed view of persona patterns and messaging implications even when the
evidence is incomplete.

Do not use it to invent personas, choose a market, or make a segmentation decision on a
human's behalf. Not for outbound targeting, CRM tagging, customer contact, or changing
source records without a separately confirmed action.

## Inputs and source discipline

- State the question, audience scope, time-box, timezone, and as-of date/time before
  searching. A missing date is unknown; never substitute the current date.
- Keep an evidence ledger with source path or ID, source date, retrieval/as-of date,
  audience context, exact quote or direct observation, and evidence state. Quote customer
  language exactly and attach the source and date to every quote.
- Record the sources searched, excluded, inaccessible, and their date coverage. Treat a
  source's own timestamp separately from the date the source was retrieved.
- Time-box the search. When the window or source budget ends, report what was not searched
  rather than implying complete coverage.
- Deduplicate only repeated references to the same supported interaction or evidence item.
  Keep every supporting source reference and do not merge distinct customers or events
  merely because their wording is similar.

## Method

1. Define the audience question, inclusion rules, time-box, timezone, and as-of boundary.
2. Gather the permitted sources read-only and build the quote/source/date ledger before
   clustering anything.
3. Mark direct statements and behavior as observed. Keep each quote attributable to its
   source without adding intent, emotion, or demographic detail that was not stated.
4. Deduplicate the ledger using available source or interaction identifiers, then count
   unique supported items. Show the deduplication rule and any ambiguous duplicates.
5. Cluster observed pain points, goals, language, roles, and decision criteria by the
   persona or segment actually evidenced. Label a persona pattern inferred when it is a
   synthesis rather than a direct description, and explain which observations support it.
6. Compare segments and sources. Surface contradictory quotes or behaviors side by side;
   do not resolve a contradiction by averaging it away.
7. Separate findings from recommendations. Offer content or research recommendations as
   proposals, not human decisions, and preview any requested save before asking for
   confirmation.

## Truth and uncertainty rules

- **Observed:** directly present in a dated source; cite the source and quote or describe
  the observation without embellishment.
- **Inferred:** a pattern derived from observed items; name the reasoning and confidence.
- **Unknown:** not evidenced, not readable, or outside the time-box; do not fill the gap.
- **Stale:** evidence is outside the requested period or is superseded by a newer source;
  retain it for context but do not present it as current.
- **Contradictory:** credible sources disagree; show the conflict, dates, and possible
  scope difference without inventing a cause.

Never invent dates, metrics, percentages, owners, intent, money, status, causes, or
evidence. Frequency is a count of documented unique items only; do not turn a small or
unknown sample into a population claim.

## Output contract

Return a report containing:

- question, scope, time-box, timezone, as-of date/time, source coverage, and deduplication
  rule;
- a quote/source/date ledger or traceable excerpt list;
- persona patterns with observed and inferred components kept separate, supporting sources,
  and confidence for each finding;
- unknowns, stale evidence, contradictory evidence, and coverage limits;
- recommendations clearly marked as recommendations rather than decisions.

Do not present an unsupported persona label, count, or recommendation as fact. If no
reliable evidence supports a requested conclusion, say so explicitly.

## Safety and write boundaries

Default to read-only. Do not edit customer notes, profiles, CRM fields, tags, audiences,
or outbound systems. A recommendation is not a human decision. For any requested file or
system action, show a preview of the exact destination and content/change, obtain explicit
confirm from the human authority, then perform only that approved action. Never broaden
the source scope or action scope during a write.

## Verification and recovery

Before delivery, read back every material finding against its ledger entry and reconcile
quoted evidence, unique-item counts, dates, and segment labels. If a source cannot be
read, mark the affected item unknown; if a source changes during review, mark the finding
stale and re-check it. After an authorized write, read back the destination and reconcile
it with the confirmed preview. If a read or write fails, stop, preserve the draft and
error details, report the partial state, and ask the human authority whether to retry or
recover; never claim success or retry blindly.
