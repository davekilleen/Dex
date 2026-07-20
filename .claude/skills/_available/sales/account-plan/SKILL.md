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

```markdown
# Account Plan: Acme Corp

**Plan date:** 2026-01-28
**Account owner:** You
**Annual value:** $180,000
**Renewal date:** July 15, 2026

---

## 📋 Executive Summary

**Account status:** Strategic (Top-tier customer, high growth potential)
**Primary goal:** Expand from Product team (current) to Engineering + Marketing (3x ARR potential)
**Top priority:** Build relationship with CTO (Jennifer) to unlock Engineering adoption

**Quick facts:**
- Customer since: Aug 2024
- Products using: Core Platform, Analytics Module
- Team size: 45 users (Product + Data teams)
- Industry: B2B SaaS
- Company size: 250 employees

---

## 👥 Stakeholder Map

### Key Champions

**Sarah Chen - VP Product**
- **Role:** Champion (Power User)
- **Influence:** High (reports to CEO)
- **Support:** Very High (vocal advocate)
- **Relationship:** Strong (monthly calls, quick Slack responses)
- **Last contact:** Yesterday (Contract review call)
- **Key interests:** Product strategy, customer insights, data-driven decisions
- **How to engage:** Quarterly roadmap previews, beta access to new features

### Economic Buyers

**Tom Martinez - CFO**
- **Role:** Economic Buyer
- **Influence:** Very High (budget authority)
- **Support:** Medium (neutral, data-driven)
- **Relationship:** Moderate (met once at QBR)
- **Last contact:** Oct 15 (Quarterly business review)
- **Key concerns:** ROI, cost efficiency, tool consolidation
- **How to engage:** Show usage metrics, cost savings from efficiency gains

### Potential Champions (Not Yet Engaged)

**Jennifer Park - CTO**
- **Role:** Technical Buyer for Engineering expansion
- **Influence:** Very High (peer to Sarah)
- **Support:** Unknown (no relationship yet)
- **Relationship:** None
- **Key interests:** [Need to discover] Likely: developer experience, API quality, integrations
- **How to engage:** **PRIORITY** - Intro from Sarah, technical deep-dive

### Users

- Product team (30 users) - High adoption
- Data team (15 users) - Medium adoption
- Engineering team (50+ potential users) - Not yet using

### Gaps

- **Missing relationships:** CTO (Jennifer), CMO (unidentified), Engineering leadership
- **Weak relationships:** CFO (Tom) - only formal QBR interactions

---

## 📊 Current State

### Product Adoption

**What they're using:**
- Core Platform - High adoption (40/45 seats active daily)
- Analytics Module - Medium adoption (25/45 users monthly)
- API - Low usage (Dev team not engaged yet)

**Usage insights:**
- Sarah's team are power users - using advanced features
- Data team struggling with custom report creation
- Mentioned wanting real-time dashboards (recorded in customer intel)

### Health Indicators

- **Engagement:** High - Daily active usage, regular communication
- **Satisfaction:** High - Positive feedback, vocal advocacy, willing to be reference
- **Advocacy:** High - Referred 2 companies this quarter, case study participant

**Recent feedback:**
- ✅ "Love the product" - Sarah, multiple times
- ✅ "Best tool our team uses" - Data analyst quote
- ⚠️ "Reporting takes too long" - Pain point (opportunity for Analytics upgrade)

---

## 🎯 Growth Opportunities

### Near-term (This Quarter)

**1. Engineering Team Expansion**
- **Type:** Expansion
- **Potential value:** $180,000 (2x current ARR)
- **Why now:** Engineering team growing (10 new hires this quarter), need better workflow tools
- **Requirements:** 
  - Build relationship with CTO Jennifer
  - Technical demo for engineering use cases
  - Integration with their GitHub/Jira setup
- **Owner:** You
- **Timeline:** Target close by end of Q1

**2. Analytics Module Upgrade**
- **Type:** Upsell
- **Potential value:** $36,000/year (+20% ARR)
- **Why now:** Real-time dashboard pain point expressed 3x in last month
- **Requirements:**
  - Show new dashboard capabilities
  - ROI case for time savings
  - Budget approval from Tom (CFO)
- **Owner:** You
- **Timeline:** Proposal by Feb 10

### Medium-term (2-3 Quarters)

**1. Marketing Team Expansion**
- **Type:** Cross-sell
- **Potential value:** $90,000/year
- **Trigger conditions:** Hire new CMO (they're recruiting), marketing team expansion

---

## 🚨 Risk Factors

### Active Risks

**1. Contract renewal in 6 months with no executive relationship**
- **Type:** Relationship Risk
- **Severity:** Medium
- **Evidence:** Only deep relationship is with Sarah (VP Product). CFO is budget-focused, CTO unknown.
- **Mitigation:** 
  - Build relationship with Jennifer (CTO) now
  - Strengthen relationship with Tom (CFO) via ROI storytelling
  - Secure multi-year renewal before July
- **Owner:** You
- **Status:** In progress (Jennifer intro scheduled via Sarah)

**2. Reporting pain point unaddressed**
- **Type:** Churn Risk (low but growing)
- **Severity:** Low (currently) → Medium (if unaddressed)
- **Evidence:** Mentioned 3x in past month, called "frustrating"
- **Mitigation:** Analytics upgrade proposal, show real-time dashboard solution
- **Owner:** You
- **Status:** Planned (proposal in works)

### Risk Indicators to Monitor

- Sarah leaving (she's key champion) - Check quarterly
- Budget cuts at Acme (CFO mindset) - Watch for signals

---

## 💡 Strategic Initiatives

### This Quarter

**1. Unlock Engineering Expansion**
- **Goal:** Build relationship with CTO Jennifer, position for 50+ seat expansion
- **Actions:**
  - [x] Request intro from Sarah - DONE
  - [ ] Coffee meeting with Jennifer - Scheduled Feb 2
  - [ ] Technical deep-dive demo for engineering use case - Feb 9
  - [ ] Proposal for engineering package - Feb 16
- **Success metrics:** Jennifer meeting happens, technical demo goes well, proposal sent

**2. Close Analytics Upgrade**
- **Goal:** Upsell Analytics Module upgrade to address reporting pain
- **Actions:**
  - [ ] Build ROI case (time savings) - By Feb 5
  - [ ] Demo real-time dashboards - Feb 8 (with Sarah)
  - [ ] Present to CFO Tom - Feb 12
  - [ ] Close by Feb 28
- **Success metrics:** $36K upsell closes, reporting pain resolved

---

## 📅 Engagement Plan

### Regular Touchpoints

- **Weekly:** Support tickets (data team), product questions (Slack with Sarah)
- **Monthly:** Sarah sync (product feedback, roadmap preview)
- **Quarterly:** Executive business review (Sarah, Tom, ideally Jennifer)
- **Annual:** Contract renewal (July), strategic planning session

### Upcoming Events

- **Feb 2** - Coffee with Jennifer (CTO) - Build relationship, understand engineering needs
- **Feb 8** - Dashboard demo with Sarah - Show Analytics upgrade
- **Feb 9** - Technical demo for Jennifer - Engineering use case positioning
- **Feb 12** - ROI presentation with Tom (CFO) - Analytics upgrade approval

---

## 📚 Account History

### Key Milestones

- **Aug 2024** - Initial deal closed ($90K) - Product team adoption
- **Oct 2024** - Added Analytics Module ($90K total ARR)
- **Nov 2024** - Sarah became vocal advocate, participated in case study
- **Jan 2025** - Contract expansion conversation, Jennifer intro secured

### Major Decisions

- **Oct 2024** - Chose us over Competitor Y based on ease of use and Sarah's recommendation
- **Jan 2025** - Decided to explore engineering expansion (Sarah's push)

### Lessons Learned

- Sarah is an amazing champion - give her early access to features, she drives internal adoption
- Data team needs more training - they're not using advanced features effectively
- ROI storytelling resonates with Tom (CFO) - lead with metrics, not features

---

## 🎯 Success Metrics

**Primary metrics:**
- Revenue: $180K → $396K (2.2x) by end of Q2
- Users: 45 → 100+ (Product + Engineering + Marketing) by end of year
- Adoption: 89% → 95% (get data team to advanced features)

**Relationship metrics:**
- Executive contacts: 2 (Sarah, Tom) → 4 (add Jennifer, CMO when hired)
- Meeting frequency: Monthly with Sarah → Add monthly with Jennifer
- Advocacy: Case study done → Video testimonial by mid-year

---

## 📝 Next Actions

**Immediate (This Week):**
- [ ] Confirm Feb 2 coffee with Jennifer - You - Jan 29
- [ ] Build Analytics upgrade ROI deck - You - Feb 1

**Short-term (This Month):**
- [ ] Jennifer meeting - You - Feb 2
- [ ] Dashboard demo - You - Feb 8
- [ ] Engineering technical demo - You - Feb 9
- [ ] CFO ROI presentation - You - Feb 12

**Review date:** April 1 (after Q1 initiatives complete)
```
