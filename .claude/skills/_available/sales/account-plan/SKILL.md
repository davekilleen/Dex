---
name: account-plan
description: Create or update strategic account plan
role_groups: [sales, customer_success]
jtbd: |
  You need to think strategically about a key account but the context is scattered. 
  This gathers all information on the account - stakeholders, history, opportunities, 
  risks - and creates a structured account plan so you have a clear strategy for 
  growing the relationship.
time_investment: "20-30 minutes per account"
---

## Purpose

Create a comprehensive strategic account plan by gathering all context on an account and structuring it into a clear growth and relationship strategy.

## Usage

- `/account-plan [account-name]` - Create or update account plan for specific company

---

## Method

Define the account, planning horizon, authorized owner, and `as-of` time before
searching. Build a source ledger across company, person, meeting, deal, and prior
plan records; deduplicate copied facts while retaining every source ID and source
date. Classify each material item as observed, customer-stated, inferred,
contradictory, stale, or unknown. Only then map stakeholders, current state,
opportunities, risks, and possible actions. Keep recommendations separate from
the account owner's decisions, and never convert a suggested action into a task
or saved plan without the controlled-write sequence below.

## Output contract

Return the scope and coverage first, followed by the source ledger, known account
facts, unresolved contradictions and unknowns, stakeholder map, evidence-backed
opportunities and risks, and recommendations awaiting human decision. Any count
or total must name its denominator and excluded unknown values. End with a save
status of `not requested`, `awaiting confirmation`, `verified from read-back`, or
`failed`, plus the exact path and receipt when a confirmed write occurred. Never
describe an unverified draft as the current account plan.

## Evidence, authority, and recovery

Treat the account plan as a decision aid, not as a source of truth. Set an
`as-of` timestamp when gathering context. Add per-field provenance to every
material fact or claim: the source path or record, the source date (the date of
the event or assertion, or `undated`), and the `as-of` time when it was read.
Do not silently use a file modified date as the event date. A compact notation
is: `Annual value: £... (source: 04-Projects/..., source date: 2026-08-01,
as-of: 2026-08-12T10:30Z)`.

- Keep absent data as `Unknown — not found`. For any unknown field, do not infer
  a stakeholder role, relationship strength, budget, renewal date, adoption
  number, intent, or outcome from a title, pattern, or template. Never invent
  absent facts. If sources contradict one another, list each source and date,
  show the contradiction, and leave the field unresolved until an authorized
  human resolves it.
- Separate observed facts from customer-stated facts and recommendations.
  Recommendations are not human decisions: do not turn a suggested owner,
  status, priority, or next action into a saved fact or create follow-up work
  without the user's decision.
- Keep gathering read-only. Before creating or updating
  `05-Areas/Companies/[Company-Name]_Account_Plan.md`, show an exact write preview:
  the target path and complete proposed content, or an exact before/after diff,
  including every provenance and `Unknown` label. Require explicit confirmation
  from the authorized human account owner; a recommendation, a prior plan, or
  an implied yes is not authority. Do not write before that confirmation.
- After writing, read back the saved plan from disk and compare it with the
  approved preview, including the path, content, and key field annotations.
  Report the read-back result. If the write fails, times out, or the read-back
  differs, say that the plan is not verified and may be partially changed;
  preserve the prior copy where possible, re-read the file, show the
  discrepancy, and wait for explicit human direction before repairing or
  retrying. Never claim the plan was created or updated from a tool response
  alone.

## Step 1: Gather Account Context

Collect information from multiple sources:

### Company/Account Files
- Check 04-Projects/ for deal files related to this account
- Check 05-Areas/Companies/ for company page
- Look for company pages in 05-Areas/Companies/

### Person Pages
- Search People/ for individuals at this company
- Extract:
  - Names and roles
  - Relationship strength  
  - Key conversations
  - Pain points mentioned
  - Influence level

### Meeting History
- Search 00-Inbox/Meetings/ for meetings with this account (last 12 months)
- Extract:
  - Key topics discussed
  - Decisions made
  - Commitments (theirs and ours)
  - Concerns raised
  - Wins celebrated

### Deal History
- Current deals in pipeline
- Past deals (won/lost)
- Products/services they use
- Contract value and terms
- Renewal dates

---

## Step 2: Analyze Stakeholder Map

Build comprehensive stakeholder analysis:

### For Each Stakeholder:

**Role classification:**
- Champion: Advocates for us internally
- Economic Buyer: Final decision authority
- Technical Buyer: Evaluates product fit
- User: Day-to-day product user
- Blocker: Resistant or hostile

**Influence and Support:**
- High influence, high support = Key Champion
- High influence, low support = Risk / Blocker
- Low influence, high support = User Champion
- Low influence, low support = Monitor

**Relationship Strength:**
- Strong: Regular contact, mutual trust
- Moderate: Occasional contact, professional
- Weak: Minimal contact or new relationship
- None: Haven't connected

---

## Step 3: Identify Opportunities and Risks

### Growth Opportunities

1. **Expansion opportunities:**
   - Additional products/features they don't use
   - Other departments/teams that could benefit
   - Volume/usage growth potential
   
2. **Upsell indicators:**
   - Pain points that premium features solve
   - Budget availability signals
   - Competitive alternatives they're using
   
3. **Relationship opportunities:**
   - Executives we haven't met
   - Teams we're not working with
   - Events/conferences they attend

### Risk Factors

1. **Churn risk:**
   - Product adoption issues
   - Unresolved pain points
   - Competitor activity
   - Budget cuts mentioned
   
2. **Relationship risks:**
   - Key champion leaving
   - Stakeholder concerns unaddressed
   - Reduced engagement
   
3. **Competitive risks:**
   - Competitor mentions
   - Evaluation processes
   - Dissatisfaction signals

---

## Step 4: Generate Account Plan

Create structured account plan document:

```markdown
# Account Plan: [Company Name]

**Plan date:** [Today]
**Account owner:** [User name]
**Annual value:** $[Amount if known]
**Renewal date:** [Date if known]

---

## 📋 Executive Summary

**Account status:** [Strategic / Growing / Stable / At-Risk]
**Primary goal:** [Main objective for this account]
**Top priority:** [Most important action]

**Quick facts:**
- Customer since: [Date]
- Products using: [List]
- Team size: [Number of users]
- Industry: [Vertical]
- Company size: [Employees]

---

## 👥 Stakeholder Map

### Key Champions

**[Name] - [Title]**
- **Role:** Champion
- **Influence:** High
- **Support:** High
- **Relationship:** Strong
- **Last contact:** [Date]
- **Key interests:** [What they care about]
- **How to engage:** [Strategy]

### Economic Buyers

**[Name] - [Title]**
- **Role:** Economic Buyer
- **Influence:** High
- **Support:** Medium
- **Relationship:** Moderate
- **Last contact:** [Date]
- **Key concerns:** [What worries them]
- **How to engage:** [Strategy]

### Users

[List key users with brief context]

### Gaps

- **Missing relationships:** [Roles/departments not yet connected]
- **Weak relationships:** [People we should strengthen ties with]

---

## 📊 Current State

### Product Adoption

**What they're using:**
- [Product/Feature 1] - [Adoption level: High/Medium/Low]
- [Product/Feature 2] - [Adoption level: High/Medium/Low]

**Usage insights:**
- [Key usage pattern]
- [Adoption blockers]
- [Power users]

### Health Indicators

- **Engagement:** [High/Medium/Low] - [Evidence]
- **Satisfaction:** [High/Medium/Low] - [Evidence]
- **Advocacy:** [High/Medium/Low] - [Evidence]

**Recent feedback:**
- [Positive signal 1]
- [Concern 1]

---

## 🎯 Growth Opportunities

### Near-term (This Quarter)

**1. [Opportunity Name]**
- **Type:** Expansion / Upsell / Cross-sell
- **Potential value:** $[Amount]
- **Why now:** [Timing/trigger]
- **Requirements:** [What needs to happen]
- **Owner:** [Who drives this]
- **Timeline:** [Target date]

**2. [Opportunity Name]**
[Same structure]

### Medium-term (2-3 Quarters)

**1. [Opportunity Name]**
- **Type:** [Type]
- **Potential value:** $[Amount]
- **Trigger conditions:** [What would enable this]

---

## 🚨 Risk Factors

### Active Risks

**1. [Risk Description]**
- **Type:** Churn / Competition / Relationship
- **Severity:** High / Medium / Low
- **Evidence:** [What indicates this risk]
- **Mitigation:** [Actions to reduce risk]
- **Owner:** [Who's responsible]
- **Status:** [In progress / Planned / Monitor]

### Risk Indicators to Monitor

- [Indicator 1] - Check monthly
- [Indicator 2] - Check quarterly

---

## 💡 Strategic Initiatives

### This Quarter

**1. [Initiative Name]**
- **Goal:** [What we're trying to achieve]
- **Actions:**
  - [ ] [Action 1] - [Owner] - [Date]
  - [ ] [Action 2] - [Owner] - [Date]
  - [ ] [Action 3] - [Owner] - [Date]
- **Success metrics:** [How we measure success]

**2. [Initiative Name]**
[Same structure]

---

## 📅 Engagement Plan

### Regular Touchpoints

- **Weekly:** [User check-ins, support tickets]
- **Monthly:** [Champion sync, usage review]
- **Quarterly:** [Executive business review, roadmap discussion]
- **Annual:** [Contract renewal, strategic planning]

### Upcoming Events

- **[Date]** - [Event/Meeting] - [Purpose]
- **[Date]** - [Event/Meeting] - [Purpose]

---

## 📚 Account History

### Key Milestones

- **[Date]** - [Milestone: First deal, major expansion, executive engagement, etc.]
- **[Date]** - [Milestone]

### Major Decisions

- **[Date]** - [Decision made and impact]
- **[Date]** - [Decision made and impact]

### Lessons Learned

- [Learning 1] - [What to do differently]
- [Learning 2] - [What worked well]

---

## 🎯 Success Metrics

**Primary metrics:**
- Revenue: $[Current] → $[Target]
- Users: [Current] → [Target]
- Adoption: [Current %] → [Target %]

**Relationship metrics:**
- Executive contacts: [Current] → [Target]
- Meeting frequency: [Current] → [Target]
- Advocacy: [Current state] → [Target state]

---

## 📝 Next Actions

**Immediate (This Week):**
- [ ] [Action 1] - [Owner] - [Date]
- [ ] [Action 2] - [Owner] - [Date]

**Short-term (This Month):**
- [ ] [Action 1] - [Owner] - [Date]
- [ ] [Action 2] - [Owner] - [Date]

**Review date:** [When to revisit this plan]
```

Save to: `05-Areas/Companies/[Company-Name]_Account_Plan.md`

---

## Step 5: Offer Follow-Up Actions

After creating the plan, ask:

> "Account plan created! Want me to:
> 1. Update person pages with strategic context?
> 2. Draft email for stakeholder engagement?
> 3. Create tasks for immediate actions?
> 4. Schedule quarterly business review?"

---

## Existing Plan Updates

If account plan already exists:

1. Read existing plan
2. Ask what's changed:
   - New stakeholders?
   - Updated opportunities?
   - New risks?
   - Progress on initiatives?
3. Update relevant sections
4. Preserve historical context

---

## Integration with Other Skills

- **Before creating:** Run `/customer-intel [company]` for recent feedback
- **After creating:** Use `/meeting-prep` with stakeholders using this context
- **For renewals:** Use `/renewal-prep` with this plan as foundation
- **Quarterly:** Review and update alongside `/pipeline-health`

---

## Example Output

This is a schema example, not a fictional account. Replace bracketed values only
with evidence from the source ledger; leave missing values as `Unknown`.

```markdown
# Account Plan: [Account name or Unknown]

**As-of date:** [As-of date]
**Account owner:** [Owner or Unknown]
**Plan status:** Draft for human review

## Source ledger
| Source ID | Source date | Scope | Freshness / limits |
|---|---|---|---|
| [Source ID] | [Source date] | [Contract, CRM record, meeting, or usage report] | [Limit or Unknown] |

## Account facts
| Field | Value | Source ID | Source date |
|---|---|---|---|
| Contract value | [Exact sourced value or Unknown] | [Source ID] | [Source date] |
| Renewal date | [Exact sourced date or Unknown] | [Source ID] | [Source date] |
| Adoption | [Configured measure or Unknown] | [Source ID] | [Source date] |

## Stakeholders
| Person | Evidence-backed role | Relationship | Last confirmed contact |
|---|---|---|---|
| [Name or Unknown] | [Role or Unknown] | [Observed state or Unknown] | [Date / Source ID / Unknown] |

## Opportunities, risks, and actions
- Opportunity: [Observed need and evidence, or Unknown]
- Risk: [Observed signal and evidence, or Unknown]
- Proposed action: [Owner / due date / evidence needed]
- Decision authority: [Human owner]

## Save boundary
- Exact target: [path]
- Preview confirmed by: [human / timestamp]
- Read-back result: [matched preview or failed; recovery action]
```
