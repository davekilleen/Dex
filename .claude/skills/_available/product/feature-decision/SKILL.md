---
name: feature-decision
description: Framework for making feature prioritization decisions
role_groups: [product, leadership]
jtbd: |
  Prioritization decisions get made in meetings and forgotten, or worse - made 
  without proper framework. This guides you through key questions (impact, effort, 
  strategic fit), checks recent customer intel, and documents the decision with 
  rationale so you can reference it later.
time_investment: "15-20 minutes per decision"
---

## Purpose

Make and document feature prioritization decisions with a structured framework. Ensures key factors are considered, stakeholders are consulted, and rationale is preserved for future reference.

## Evidence, authority, and recovery

Treat this skill as decision support: a recommendation is analysis, while the decision belongs to an identified human authority.

- Attach a source ID or path, source date, and as-of date to every material claim, quote, estimate, stakeholder input, and roadmap fact. Keep the evidence date separate from the date the human confirms a decision.
- Expose unknown effort and unknown evidence as first-class values. `Unknown` effort is not Small, and missing evidence is not evidence of no impact; name the missing input or assumption instead of choosing a convenient rating. Preserve contradictory evidence with both sources and dates rather than reconciling it silently.
- Never invent absent customer names, user counts, revenue, effort estimates, dates, stakeholder alignment, owners, quotes, or dependencies. If a field is not supported, record `unknown` or `not provided` and explain what would resolve it.
- Keep the recommendation separate from the decision authority: label the output `Recommendation` and `Human decision authority` separately. Recommendations are not human decisions; only the human authority may choose or confirm Go, No-Go, or Defer.
- Before creating or updating a decision document, search for existing decisions for the feature and show an exact preview: target path, create/update operation, and complete proposed contents or diff. Require explicit confirmation from the human authority before any change.
- Preserve each earlier decision. Never overwrite it silently: append a dated decision entry when extending the record, or explicitly supersede the earlier decision with the human authority, reason, and link recorded.
- After an approved write, read back the target and compare it with the confirmed preview. If the write fails or the read-back differs, report the exact failure, leave the earlier decision intact, do not claim the document was created or updated, and recover by re-reading the current file and presenting a new preview for explicit confirmation.

## Usage

- `/feature-decision [feature-name]` - Make a decision on a specific feature
- `/feature-decision` - Start decision process with guided questions

---

## Method

Define the decision question, options, constraints, planning horizon, and named
human decision authority. Gather dated customer, strategic, delivery, design,
commercial, and dependency evidence into a source ledger. Use only a configured
or user-confirmed sizing scale; if no scale or estimate exists, preserve effort
as `Unknown`. Compare options and trade-offs, expose assumptions and conflicting
evidence, and produce a recommendation without converting it into a decision.
Search prior decision records before proposing any save, preserving their history
and requiring separate confirmation for a new or superseding entry.

## Output contract

Return the decision question, authority, scope and evidence coverage, options,
source-backed impact and effort assessment, unknowns, contradictions, trade-offs,
recommendation, and an explicitly separate `Human decision` field. Every rating
must cite its configured scale and evidence; unsupported values remain unknown.
If a decision is confirmed, include its date and rationale. End with the proposed
record operation or verified read-back receipt. Never label a recommendation,
preview, tool response, or unconfirmed draft as an accepted decision.

## Step 1: Define the Feature

Ask the user to clarify:

1. **Feature name:** What are we deciding on?
2. **Feature description:** What does it do? (1-2 sentences)
3. **Origin:** Where did this request come from?
   - Customer request (which customers?)
   - Internal idea (who proposed?)
   - Competitive response
   - Strategic initiative

---

## Step 2: Gather Context

Before asking decision questions, gather relevant intel:

### Customer Intel
- Search for mentions of this feature or related pain points
- Check `/customer-intel` output if recently run
- Look for customer quotes supporting or contradicting this feature

### Roadmap Context
- Check 04-Projects/ for related work
- Verify available capacity
- Identify potential conflicts or dependencies

### Strategic Alignment
- Read System/pillars.yaml
- Read 01-Quarter_Goals/Quarter_Goals.md (if exists)
- Check how this feature maps to strategic priorities

---

## Step 3: Decision Framework Questions

Guide the user through these questions:

### Impact Questions

1. **Customer Impact**
   - Who benefits from this? (Which customers/segments?)
   - How many users does this affect?
   - What problem does it solve for them?
   - Scale: High / Medium / Low

2. **Business Impact**
   - How does this affect revenue? (Enable new sales? Reduce churn? Upsell opportunity?)
   - Does this unblock deals?
   - Competitive positioning impact?
   - Scale: High / Medium / Low

3. **Strategic Fit**
   - Which pillar does this advance?
   - Does it support a quarterly goal?
   - Long-term value vs short-term win?
   - Scale: High / Medium / Low

### Effort Questions

4. **Engineering Effort**
   - Size estimate using the team's configured or user-confirmed sizing scale? If none exists, record `Unknown` rather than supplying generic duration bands.
   - Technical complexity? (Low / Medium / High)
   - Dependencies on other systems?
   - Risk level? (Low / Medium / High)

5. **Design Effort**
   - New patterns needed or existing components?
   - User research required?
   - Estimated design time?

6. **GTM/Support Effort**
   - Training needed?
   - Documentation scope?
   - Support impact?

### Trade-offs

7. **What are we NOT building if we build this?**
   - What gets deprioritized?
   - Opportunity cost?

8. **What's the downside of saying no?**
   - Lost customers?
   - Competitive risk?
   - Team morale?

Keep unsupported answers as `unknown`; do not turn absent evidence into a low impact, low effort, or low risk rating.

---

## Step 4: Consult Stakeholders

Identify who needs to weigh in:

- **Must consult:** [Based on feature type]
  - Engineering (feasibility)
  - Design (user experience)
  - Sales/CS (customer impact)
  - Leadership (strategic fit)

- **Optional consult:** [Nice to have input]

Prompt user: "Have you consulted [stakeholders]? Want me to help prep for those conversations?"

---

## Step 5: Make the Decision

Based on the framework, present a recommendation:

### Impact/Effort Matrix

```
       HIGH IMPACT
            |
    Do Next | Do Now
------------|------------
    Later   | Quick Wins
            |
       LOW IMPACT
```

**Recommendation:** [Do Now / Do Next / Quick Wins / Later / No]

**Rationale:**
- [Key factor 1]
- [Key factor 2]
- [Key factor 3]

State `Recommendation` and `Human decision authority` as separate fields. The recommendation is not the decision; wait for the human authority to explicitly choose Go, No-Go, or Defer.

Ask user: "Does this recommendation make sense? Want to adjust the decision?"

---

## Step 6: Document the Decision

Before creating a decision document, search `04-Projects/` for an existing decision for the feature. Show the exact target path, whether this is a new document or an append/supersede operation, and the complete proposed document or diff. Ask for explicit confirmation from the human authority, then create only the confirmed version.

Create a decision document in 04-Projects/:

```markdown
# Feature Decision: [Feature Name]

**Date:** [Today]
**Decision:** [Go / No-Go / Defer]
**Owner:** [User's name from System/user-profile.yaml]

---

## Overview

**Feature:** [Feature description]
**Origin:** [Where it came from]
**Requested by:** [Customers/stakeholders]

---

## Decision Framework

### Impact Assessment

**Customer Impact:** [High/Medium/Low]
- Who benefits: [Segment/customers]
- Problem solved: [Pain point]
- Users affected: [Count/percentage]

**Business Impact:** [High/Medium/Low]
- Revenue effect: [Details]
- Competitive position: [Details]
- Deal impact: [Details]

**Strategic Fit:** [High/Medium/Low]
- Pillar: [Which pillar]
- Quarterly goal: [Which goal if applicable]
- Long-term value: [Assessment]

### Effort Assessment

**Engineering:** [Small/Medium/Large/XL]
- Size: [Time estimate]
- Complexity: [Low/Medium/High]
- Dependencies: [List]
- Risk: [Low/Medium/High]

**Design:** [Details]
**GTM/Support:** [Details]

---

## Decision Rationale

**Why [Go/No-Go/Defer]:**

1. [Primary reason]
2. [Secondary reason]
3. [Tertiary reason]

**Trade-offs accepted:**
- Deprioritizing: [What]
- Risk: [What]

---

## Supporting Evidence

**Customer quotes:**
- "[Quote 1]" - [Customer], [Date]
- "[Quote 2]" - [Customer], [Date]

**Competitive intel:**
- [Details if applicable]

**Related conversations:**
- [Link to meeting notes]
- [Link to person pages]

---

## Stakeholder Alignment

**Consulted:**
- [Name] (Engineering) - [Their input]
- [Name] (Design) - [Their input]
- [Name] (Sales) - [Their input]

**Concerns raised:**
- [Concern 1 and how addressed]

---

## Next Steps

[If Go:]
- [ ] Create project in 04-Projects/
- [ ] Add to roadmap
- [ ] Schedule kickoff
- [ ] Update stakeholders

[If No-Go:]
- [ ] Communicate decision to requesters
- [ ] Update person pages with rationale
- [ ] Add to "not now" backlog with trigger conditions

[If Defer:]
- [ ] Document trigger conditions for revisiting
- [ ] Set calendar reminder for [when]
- [ ] Communicate timeline to stakeholders

---

## Decision Log

This decision is logged for future reference. Run `/decision-log` to see all major product decisions.
```

If an earlier decision exists, preserve its content and provenance. Append a new dated entry when the decision is revisited, or explicitly mark the earlier decision as superseded with the replacement decision, reason, human authority, and source evidence. Do not replace an earlier decision merely because the latest recommendation differs.

Save to: `04-Projects/Decision_[Feature-Name]_[Date].md`

---

## Step 7: Follow-Up Actions

Offer to help with next steps:

> "Decision documented! Want me to:
> 1. Create a project file if we're building this?
> 2. Draft stakeholder communication?
> 3. Add to roadmap review?
> 4. Update relevant person pages with this decision?"

---

## Integration with Other Skills

- **Before running:** Suggest `/customer-intel` to gather feedback
- **Before running:** Suggest `/roadmap` to check capacity
- **After No-Go decision:** Update person pages so you remember why you said no
- **After Go decision:** Link to `/project-health` for tracking

---

## Example: Evidence-bounded decision template

This is a decision-record schema, not a worked fictional case. A recommendation
must remain separate from the human decision, and missing inputs remain `Unknown`.

```markdown
# Feature Decision: [Feature name]

**As-of date:** [As-of date]
**Status:** Proposed — awaiting human decision
**Decision authority:** [Named human or Unknown]

## Source ledger
| Source ID | Source date | Claim supported | Limits / contradiction |
|---|---|---|---|
| [Source ID] | [Source date] | [Customer need, strategy, effort, or capacity] | [Limit or Unknown] |

## Assessment
- Customer impact: [Evidence and denominator, or Unknown]
- Business impact: [Sourced value, or Unknown — never estimated here]
- Strategic fit: [Goal source and date, or Unknown]
- Engineering effort: [Owner-supplied estimate and confidence, or Unknown]
- Capacity: [Canonical planning source and date, or Unknown]
- Contradictory evidence: [Source IDs, or None observed]

## Recommendation
[Recommend Go / No-Go / More evidence, with cited rationale.]

## Human decision
**Decision:** [Not yet made / human-entered decision]
**Decided by:** [Name]
**Decision date:** [Date]
**Trade-offs accepted:** [Human-confirmed text or Unknown]

## Controlled save
- Exact target and diff: [preview]
- Explicit confirmation: [human / timestamp]
- Read-back: [matched preview or failed; recovery action]
```
