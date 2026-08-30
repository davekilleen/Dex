---
name: customer-intel
description: Synthesize recent customer feedback and pain points
role_groups: [product, customer_success, sales]
jtbd: |
  Customer feedback is scattered across meeting notes, person pages, and quick 
  captures. This synthesizes recent feedback by theme, shows frequency of mentions, 
  and surfaces patterns you might miss when looking at conversations individually.
time_investment: "5-10 minutes per review"
---

<!-- Generated from `.claude/skills/_available/product/customer-intel/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

## Purpose

Aggregate and analyze customer feedback from all sources - meeting notes, person pages, feedback captures - to identify patterns, prioritize pain points, and inform product decisions.

## Evidence, authority, and recovery

Treat customer intelligence as an evidence ledger, not as memory or a polished guess.

- For every finding, retain a stable source ID (vault path, note ID, or capture ID), source type, source date (when the customer said or wrote it), and the as-of date (when this review read it). Keep the source ID and source date attached when a finding is summarized.
- Deduplicate repeated copies of the same evidence for frequency counts, but preserve every source ID and source date in the provenance. Distinguish a copied meeting note from an independent mention; duplicate copies are not extra customer mentions.
- Preserve quote fidelity: quoted text must be copied exactly, including wording and meaningful punctuation. Mark omissions or inaudible text explicitly, and label any cleaned-up summary as a paraphrase rather than a quote.
- Keep unknown and contradictory evidence visible. If sources disagree, show each claim with its source ID and date and call out the contradiction; do not silently choose one. If the records do not support a count, customer attribution, urgency, trend, or roadmap status, write `unknown` and return **insufficient evidence** rather than filling the gap.
- Never invent absent facts, including customer names, dates, quotes, counts, sentiment, urgency, trend, or roadmap status. An empty search is not negative feedback.
- Recommendations are not human decisions. Before any create or update, show an exact preview with the target path, operation, and complete proposed content or diff; require explicit confirmation from the human authority before changing anything.
- After an approved change, read back the target and compare it with the confirmed preview before reporting success. If the write fails or the read-back does not match, report the exact failure, preserve the prior content, do not claim completion, and recover by re-reading the source and presenting a corrected preview for fresh human confirmation.

## Usage

- `/customer-intel` - Review last 30 days of feedback
- `/customer-intel [timeframe]` - Specify timeframe (e.g., "last week", "Q1", "last 90 days")
- `/customer-intel [customer-name]` - Deep dive on specific customer

---

## Method

Resolve the requested customer or time window before gathering. Build a dated
source ledger from meeting notes, person pages, feedback captures, and project
records. Preserve exact quotes separately from paraphrases, deduplicate copied
records, and distinguish independent mentions from repetitions. Classify every
theme, frequency, trend, sentiment, and roadmap connection as observed, inferred,
contradictory, stale, or unknown. Compare supporting and disconfirming evidence,
then produce recommendations only where coverage is sufficient. Keep the entire
analysis read-only unless the user separately approves an exact write preview.

## Output contract

Return the resolved scope and coverage, source ledger, deduplication decisions,
themes with independent-source counts, exact quotes with provenance, conflicting
or missing evidence, and recommendations awaiting human judgment. Counts must
state their denominator and exclude unknown or duplicate records. When evidence
cannot support a conclusion, output `insufficient evidence` rather than a weak
theme. End with the save state and, only after a confirmed write, the destination,
byte or diff receipt, and read-back result. Never call a draft saved or current.

## Step 1: Gather Customer Feedback

Search across multiple sources for customer mentions:

### Primary Sources

1. **00-Inbox/Meetings/** - Meeting notes from last 30 days (or specified timeframe)
   - Search for: customer names, company names, "customer said", "feedback", "pain point"
   
2. **People/** - Customer person pages (External/ directory)
   - Check for recent notes, pain points mentioned, feature requests

3. **00-Inbox/Customer_Feedback/** (if exists) - Dedicated feedback captures

4. **04-Projects/** - Customer mentions in project context

Create an evidence ledger before categorizing: one entry per source occurrence with its source ID, source date, as-of date, customer attribution, exact quote or clearly labeled paraphrase, and location. Do not collapse entries yet; this ledger is what preserves provenance through later deduplication.

### Keywords to Search

- Pain points: "frustrated", "pain", "problem", "issue", "struggle"
- Feature requests: "want", "need", "wish", "could we", "feature request"
- Competitive: "competitor", "vs", "compared to", "switching"
- Positive: "love", "great", "works well", "helpful"

---

## Step 2: Categorize and Theme

Group findings into categories:

### Pain Points
- What customers are frustrated with
- What's not working for them
- What's taking too long or too manual

### Feature Requests
- Specific features customers have asked for
- Capabilities they wish existed
- Improvements to existing features

### Competitive Intel
- What competitors are doing better
- Why customers might switch
- What we're missing vs competition

### Wins
- What customers love
- What's working really well
- What differentiates us positively

---

## Step 3: Identify Patterns

For each theme, identify:

1. **Frequency** - How many times this was mentioned
2. **Customers** - Which customers mentioned it
3. **Urgency** - High (blocker), Medium (painful), Low (nice-to-have)
4. **Trend** - Increasing, stable, or decreasing mentions

Count independent source occurrences, not copied text. When deduplicating a repeated capture, retain the full list of source IDs and dates and state how many independent mentions remain. Mark trend as `unknown` when the dated evidence cannot support it.

---

## Step 4: Cross-Reference with Roadmap

Check if pain points or requests are already being addressed:

1. Search 04-Projects/ for related work
2. Note if addressed, planned, or not on roadmap
3. Flag opportunities where demand exists but no work planned

---

## Step 5: Generate Intelligence Report

Present findings in this format:

```markdown
# 🎯 Customer Intelligence Report

**Period:** [Timeframe]
**Sources analyzed:** [Count] distinct source IDs ([Count] meetings, [Count] person pages, [Count] feedback captures; duplicate copies noted separately)
**Customers represented:** [Count]

---

## 🔥 Top Pain Points

### [Pain Point Theme]
**Mentioned by:** [X customers] ([Customer names])
**Frequency:** [X mentions] in last [timeframe]
**Urgency:** High / Medium / Low
**Trend:** ↑ Increasing / → Stable / ↓ Decreasing

**Details:**
- `[Source ID]` — "[Exact quote from customer 1]" — [Customer name], source date [Date], reviewed as of [As-of date]
- `[Source ID]` — "[Exact quote from customer 2]" — [Customer name], source date [Date], reviewed as of [As-of date]

**Roadmap status:** [On roadmap / Planned / Not planned]
**Related project:** [Link to 04-Projects/ file if exists]

---

## ✨ Feature Requests

[Same format as pain points]

---

## 🏆 Competitive Mentions

[Same format]

---

## 💚 What's Working

[Same format]

---

## 🎯 Recommendations

### Immediate Actions
1. [Action based on high-urgency items with increasing trend]
2. [Action based on frequency across multiple customers]

### Product Opportunities
1. [Opportunity where demand exists but no roadmap coverage]
2. [Opportunity where competitive gap is mentioned]

### Customer Follow-Ups
1. [Customer name] - [Why to follow up]
2. [Customer name] - [Why to follow up]

---

## 📊 Summary

**High-urgency items:** [Count]
**Feature requests:** [Count unique requests]
**Competitive threats:** [Count mentions]
**Customers needing follow-up:** [Count]

**Top 3 insights:**
1. [Insight with the strongest signal]
2. [Insight with increasing trend]
3. [Insight with competitive implication]
```

---

## Step 6: Offer Actions

After presenting the report, ask:

> "Want me to:
> 1. Create a feature brief for [top requested item]?
> 2. Update person pages with this intelligence?
> 3. Generate a stakeholder memo on these findings?
> 4. Deep dive on [specific customer or theme]?"

---

## Timeframe Parsing

Support natural language timeframes:
- "last week" = 7 days
- "last month" = 30 days
- "last quarter" = 90 days
- "Q1" = Jan 1 - Mar 31 of current year
- "last 90 days" = 90 days

---

## Customer-Specific Deep Dive

When user specifies a customer:

1. Pull all mentions of that customer across all sources
2. Build chronological timeline of feedback
3. Identify their top pain points and requests
4. Show progression of their sentiment over time
5. Link to their person page for full context

---

## Integration with Other Skills

- **After running this:** Suggest `/feature-decision` for top requested items
- **If competitive gaps found:** Suggest `/roadmap` to check coverage
- **If customer follow-ups needed:** Suggest `/meeting-prep [customer]`

---

## Example Output

This template demonstrates traceability, not sample customer claims. Keep every
unsupported count, trend, quote, and roadmap relationship as `Unknown`.

```markdown
# Customer Intelligence Report

**As-of date:** [As-of date]
**Cohort and timeframe:** [Definition or Unknown]
**Evidence completeness:** [Checked / eligible / Unknown]

## Source ledger
| Source ID | Source date | Customer | Evidence type | Included once? |
|---|---|---|---|---|
| [Source ID] | [Source date] | [Customer ID or redacted] | [Meeting, feedback, person page] | [Yes / duplicate of Source ID / Unknown] |

## Theme
**Theme:** [Evidence-backed label or Unknown]
**Distinct customers:** [Count with denominator, or Unknown]
**Trend:** [Comparable-period calculation, or Unknown]
**Contradictory evidence:** [Source IDs on each side, or None observed]

### Quote-safe evidence
- “[Exact excerpt or faithful summary]” — [Source ID], [Source date]
- Missing context: [Unknown or named gap]

### Product relationship
- Roadmap status: [Canonical source / date / Unknown]
- Related project: [Exact path / source / Unknown]

## Recommendations
1. [Evidence-backed follow-up, owner, and source]
2. [Question required before a conclusion can be made]

**Insufficient-evidence state:** [What cannot yet be concluded and why]
```
