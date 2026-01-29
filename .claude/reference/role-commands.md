# Role-Specific Skills

**Implementation Status:** ✅ Fully implemented as opt-in skills

Role-specific skills are available through `/dex-level-up` discovery. Users see which skills apply to their role and choose which to install from `.claude/skills/_available/[role_group]/`.

These skills are pre-built but not installed by default, allowing users to progressively discover and adopt capabilities that match their workflow.

## Universal Commands
*Everyone gets these*

- `/daily-plan` - Context-aware daily planning
- `/review` - End of day review
- `/week` - Weekly synthesis
- `/meeting-prep` - Prepare for meetings
- `/process-meetings` - Process meeting notes
- `/triage` - Process inbox

---

## Product (PM, CPO, Product Ops)

### `/roadmap`
Review roadmap, surface blockers, check alignment with priorities.

**What it does:**
- Scans `04-Projects/` for roadmap-related work
- Surfaces blocked items or stale initiatives
- Checks alignment with strategic pillars
- Suggests updates based on recent customer feedback

**Output:**
- Current state of roadmap items
- Blockers and dependencies
- Recommendations for updates

---

### `/customer-intel`
Synthesize recent customer feedback and pain points.

**What it does:**
- Searches meetings, notes, feedback for customer mentions
- Groups by theme (pain points, feature requests, competitive)
- Surfaces patterns across multiple customers
- Links to relevant person pages and meeting notes

**Output:**
- Themed insights
- Frequency of mentions
- Actionable recommendations

---

### `/feature-decision`
Framework for making feature prioritization decisions.

**What it does:**
- Asks key questions (impact, effort, strategic fit)
- Checks recent customer intel
- Reviews roadmap capacity
- Documents the decision with rationale

**Output:**
- Decision doc saved to `04-Projects/`
- Links to supporting context

---

## Sales & Revenue (Sales, AE, CRO, RevOps)

### `/deal-review`
Review active deals and surface risks.

**What it does:**
- Scans `04-Projects/` for deal pages
- Identifies stale deals (no recent activity)
- Flags missing next steps or commitments
- Checks for upcoming deadlines

**Output:**
- Deal health summary
- Risk flags (ghosting, delays, missing stakeholders)
- Recommended actions

---

### `/pipeline-health`
Analyze pipeline coverage and forecast accuracy.

**What it does:**
- Reviews deal pages and stages
- Checks velocity (time in stage)
- Identifies forecast gaps
- Suggests actions to move deals forward

**Output:**
- Pipeline snapshot
- Forecast confidence assessment
- Gaps and recommendations

---

### `/account-plan [account]`
Create or update strategic account plan.

**What it does:**
- Gathers all context on the account
- Identifies key stakeholders and relationships
- Maps opportunities and risks
- Creates structured account plan

**Output:**
- Account plan doc in `04-Projects/`
- Stakeholder map
- Action items

---

### `/call-prep [person/account]`
Prepare for upcoming call with full context.

**What it does:**
- Pulls person page and account history
- Surfaces recent interactions and open items
- Identifies key topics to cover
- Suggests questions based on deal stage

**Output:**
- Call prep doc
- Context summary
- Suggested agenda

---

## Marketing (Marketing, CMO)

### `/content-calendar`
Review upcoming content and identify gaps.

**What it does:**
- Scans `05-Areas/Content/` for scheduled content
- Checks alignment with campaigns and priorities
- Identifies gaps in content pipeline
- Suggests topics based on recent customer intel

**Output:**
- Content pipeline view
- Gap analysis
- Topic suggestions

---

### `/campaign-review [campaign]`
Post-mortem on recent campaign.

**What it does:**
- Gathers campaign materials and notes
- Prompts for results and learnings
- Documents what worked/didn't work
- Saves to `06-Resources/Learnings/`

**Output:**
- Campaign post-mortem doc
- Key learnings
- Recommendations for next time

---

### `/messaging-audit`
Review positioning and messaging across content.

**What it does:**
- Scans `05-Areas/Content/` for positioning
- Checks consistency across materials
- Identifies gaps or conflicts
- Suggests refinements

**Output:**
- Messaging audit report
- Consistency check
- Recommendations

---

### `/audience-intel`
Synthesize what we're learning about our audience.

**What it does:**
- Reviews customer conversations and feedback
- Identifies persona patterns
- Surfaces pain points and motivations
- Updates audience understanding

**Output:**
- Audience insights summary
- Persona updates
- Messaging implications

---

## Finance (Finance, CFO)

### `/close-status`
Month-end close checklist and blockers.

**What it does:**
- Shows close checklist for current period
- Flags incomplete items
- Surfaces blockers from recent meetings
- Tracks dependencies on other teams

**Output:**
- Close status dashboard
- Blocker list with owners
- Timeline to completion

---

### `/variance-analysis`
Compare actuals vs budget with narrative.

**What it does:**
- Prompts for key variances
- Helps document explanations
- Links to supporting context
- Prepares board-ready narrative

**Output:**
- Variance analysis doc
- Executive summary
- Backup details

---

### `/board-prep`
Compile financial narrative for board meeting.

**What it does:**
- Gathers recent variance analyses
- Pulls key decisions and context
- Structures board-ready narrative
- Identifies questions board might ask

**Output:**
- Board materials draft
- Supporting context
- Q&A prep

---

## Engineering (Engineering, CTO)

### `/tech-debt`
Review and prioritize technical debt.

**What it does:**
- Scans projects and notes for tech debt mentions
- Groups by impact/effort
- Checks age of items
- Suggests prioritization

**Output:**
- Tech debt inventory
- Prioritization framework
- Recommendations

---

### `/incident-review [incident]`
Post-mortem on incidents.

**What it does:**
- Gathers incident notes and timeline
- Prompts for root cause analysis
- Documents action items
- Saves to `06-Resources/Learnings/`

**Output:**
- Incident post-mortem
- Action items
- Prevention measures

---

### `/architecture-decision [topic]`
Document architectural choices.

**What it does:**
- Provides ADR template
- Prompts for context, options, decision
- Links to related projects
- Saves to `06-Resources/`

**Output:**
- Architecture Decision Record
- Tradeoff analysis
- Implementation notes

---

## Customer Success (Customer Success, CCO)

### `/health-score`
Review account health across portfolio.

**What it does:**
- Scans customer account pages
- Identifies at-risk accounts (no recent contact, open issues)
- Flags upcoming renewals
- Suggests proactive outreach

**Output:**
- Portfolio health dashboard
- At-risk accounts
- Recommended actions

---

### `/renewal-prep [account]`
Prepare for upcoming renewal.

**What it does:**
- Gathers account history and value delivered
- Identifies expansion opportunities
- Flags risks or concerns
- Creates renewal strategy

**Output:**
- Renewal prep doc
- Value summary
- Risk mitigation plan

---

### `/expansion-opportunities`
Identify upsell/cross-sell opportunities.

**What it does:**
- Reviews active accounts
- Identifies product usage patterns
- Suggests expansion based on needs expressed
- Prioritizes by likelihood

**Output:**
- Expansion pipeline
- Account-specific recommendations
- Outreach templates

---

## Leadership (CEO, Founder, C-Suite)

### `/weekly-reflection`
Weekly synthesis of progress and priorities.

**What it does:**
- Reviews week's meetings and decisions
- Checks progress against pillars
- Identifies wins and challenges
- Sets focus for next week

**Output:**
- Weekly reflection doc
- Pillar alignment check
- Next week priorities

---

### `/decision-log [decision]`
Document major decisions made.

**What it does:**
- Provides decision template
- Prompts for context, options, rationale
- Links to supporting materials
- Saves to searchable decision log

**Output:**
- Decision record
- Context and rationale
- Follow-up actions

---

### `/delegate-check`
Review what should be delegated.

**What it does:**
- Scans recent activities and time spent
- Identifies low-leverage work
- Suggests delegation opportunities
- Checks team capacity

**Output:**
- Delegation opportunities
- Recommended owners
- Transition plan

---

## Operations (Product Ops, RevOps, BizOps)

### `/process-audit [process]`
Review process health and bottlenecks.

**What it does:**
- Gathers feedback on process
- Identifies bottlenecks or friction
- Suggests improvements
- Documents current vs. desired state

**Output:**
- Process audit report
- Improvement recommendations
- Implementation plan

---

### `/metrics-review`
Review key metrics and anomalies.

**What it does:**
- Checks recent metric mentions in meetings
- Identifies trends or anomalies
- Prompts for context and analysis
- Documents insights

**Output:**
- Metrics summary
- Anomaly analysis
- Action items

---

## Design (Design)

### `/design-review [project]`
Prepare for or document design review.

**What it does:**
- Gathers project context and requirements
- Surfaces customer feedback related to design
- Prompts for key decisions and rationale
- Documents outcomes

**Output:**
- Design review doc
- Decision rationale
- Action items

---

### `/design-system-audit`
Review design system usage and gaps.

**What it does:**
- Scans projects for design system mentions
- Identifies inconsistencies or gaps
- Suggests components to build
- Tracks adoption

**Output:**
- Design system health check
- Gap analysis
- Roadmap suggestions

---

## Implementation Notes

### Command Discovery

Commands are role-aware. When a user runs `/` in Cursor, the autocomplete shows:
1. Universal commands (everyone sees these)
2. Role-specific commands (based on their user-profile.yaml)

### Command Variations

Some universal commands adapt behavior based on role:
- `/daily-plan` asks different questions for sales vs. product
- `/meeting-prep` surfaces different context for finance vs. marketing
- `/triage` routes content differently based on role

### Role Groups

Roles are grouped in `System/user-profile.yaml`:

```yaml
role: "Product Manager"
role_group: "product"  # Groups: product, sales, marketing, finance, engineering, customer_success, operations, leadership, design
```

Commands can check either specific role or role group.
