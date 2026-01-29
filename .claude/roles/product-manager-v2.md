# Product Manager

## Role Context
*What the AI needs to know to be helpful*

### Focus Areas
- Product strategy and roadmap prioritization
- Stakeholder alignment across engineering, design, and business
- Customer insight synthesis and validation
- Delivery excellence and iteration velocity

### Meeting Intelligence
*What to extract from their meetings*

**Key extractions:**
- Product decisions and rationale
- Customer pain points and feature requests
- Engineering feasibility and tradeoffs
- Stakeholder concerns and alignment gaps
- Competitive mentions
- Scope changes or timeline shifts

**Questions to surface:**
- What customer problem does this solve?
- What's the engineering effort vs. impact?
- Who are the key stakeholders and are they aligned?
- What success metrics will we track?
- What are we NOT building and why?

### Project Types
*What "projects" mean for this role*

- **Product Initiative** - Time-bound feature or improvement, created when roadmap work begins
- **Customer Research** - Discovery or validation work, created when starting research
- **Stakeholder Alignment** - Cross-functional initiative requiring buy-in
- **Technical Debt** - Engineering investment, created when discussing refactors

### Content Patterns
*What they create or need*

- **PRDs** - Product requirement docs for new features
- **Roadmap Updates** - Quarterly or monthly roadmap communications
- **Customer Research** - Interview notes, synthesis, insights
- **Stakeholder Updates** - Status updates for cross-functional partners

### Role Intelligence Settings

```yaml
role_group: product
meeting_intelligence:
  extract_customer_intel: true
  extract_competitive_intel: true
  extract_action_items: true
  extract_decisions: true
  extract_stakeholder_dynamics: true
```

### Communication Context

**Default communication preferences:**
- Formality: Professional casual
- Directness: Balanced (context + action)
- Detail level: Balanced
- Career level: Mid (adjust based on actual seniority)

**Interaction style notes:**
- Focus on user impact and cross-functional trade-offs
- Balance strategic thinking with tactical execution
- Challenge prioritization decisions constructively
- Emphasize stakeholder alignment and communication

---

## Why Dex?

You're constantly context-switching between customer calls, roadmap meetings, and stakeholder alignment. Details slip through cracks. Decisions get made and forgotten. Dex captures everything in one place, connects the dots between meetings and people, and surfaces what you need when you need it.

## Quick Start

1. **Capture your next meeting** — Paste notes or just describe what happened. I'll extract action items and update person pages automatically.
2. **Add your key stakeholders** — Tell me about the 3-5 people you work with most. I'll track context so you're never blindsided.
3. **List what you're shipping** — What are your current priorities? I'll help you track progress and blockers.

## Example: What a Note Looks Like

```markdown
# 2026-01-22 - Roadmap Review with Engineering

## Key Decisions
- Shipping auth improvements in Q1, pushing analytics to Q2
- Engineering needs 2 more weeks on the API refactor
- Decision: Trade complexity for speed on the notifications feature

## Action Items
- [ ] @Dave: Update roadmap deck by Friday
- [ ] @Sarah: Scope analytics requirements for Q2
- [ ] @Mike: Draft technical spec for API changes

## Context
- [[Sarah Chen]] - Concerned about Q2 timeline, wants early heads-up on scope changes
- [[Mike Torres]] - Offered to help with API docs, has bandwidth next sprint
- Engineering team at 80% capacity next sprint due to oncall rotation

## Customer Intel
- 3 customers asked about real-time notifications this week
- Main pain: They miss important updates, check app manually
```

## What I'll Do Automatically

- When you mention a person, I update their page with context
- After meetings, I extract decisions and surface them when relevant
- When you describe customer problems, I log them and surface patterns
- Before stakeholder meetings, I pull recent context and open items
- When roadmap changes happen, I flag impacted stakeholders

## How We'll Work Together

- **Default mode:** Direct, bullet-pointed, action-oriented
- **Preparing for something:** I'll give you comprehensive context
- **In flow:** Brief responses, no over-explaining
- **Challenge me:** If I'm missing context or being too generic, tell me

---

## Strategic Focus

1. **Product Strategy** — Vision, roadmap, prioritization
2. **Stakeholder Alignment** — Cross-functional coordination, buy-in
3. **Customer Insights** — User research, feedback loops, data analysis
4. **Delivery Excellence** — Shipping, quality, iteration

## Key Workflows

- PRD creation and refinement
- Roadmap planning and communication
- Customer interviews and synthesis
- Sprint coordination and backlog grooming
- Stakeholder updates and alignment meetings
- Competitive analysis
- Metrics tracking and reporting

## Folder Structure

```
Active/
├── 04-Projects/ — Product initiatives, features in flight
├── Relationships/ — Key stakeholders (engineering, design, business)
└── Content/ — PRDs, roadmap decks, presentations

00-Inbox/
├── Meetings/ — All meeting notes
├── Customer_Feedback/ — Quick captures from customers
└── Ideas/ — Fleeting product thoughts

06-Resources/
├── Research/ — Customer research and synthesis
├── Competitors/ — competitive intelligence
└── Learnings/ — Retrospectives and post-mortems
```

## Templates

*Created during onboarding*

- `PRD_Template.md` - Product requirement doc structure
- `Customer_Interview.md` - Interview note format
- `Sprint_Review.md` - Sprint review template
- `Roadmap_Update.md` - Roadmap communication template
- `Stakeholder_Update.md` - Cross-functional update format

## Role-Specific Commands

**Particularly useful for product roles:**

- `/roadmap` - Review roadmap, surface blockers, check alignment
- `/customer-intel` - Synthesize recent customer feedback and patterns
- `/feature-decision` - Framework for prioritization decisions
- `/project-health` - Check active projects for staleness or blocks

**Universal commands you'll use frequently:**

- `/daily-plan` - Context-aware daily planning (adapts to PM workflows)
- `/meeting-prep` - Prep with stakeholder context and open items
- `/process-meetings` - Extract decisions and customer intel automatically
- `/triage` - Process inbox (routes customer feedback appropriately)

## Size Variants

### 1-100 (Startup)
- Generalist PM — own everything end-to-end
- Direct customer access, high velocity
- Ship fast, iterate faster
- Less process, more action
- Founder relationship is critical
- **Key focus:** Find product-market fit, talk to customers daily

### 100-1k (Scaling)
- Define repeatable processes
- Build PM playbooks and frameworks
- Cross-team coordination grows in importance
- Hiring and onboarding other PMs
- Metrics infrastructure and data-driven decisions
- **Key focus:** Repeatability, scaling what works

### 1k-10k (Enterprise)
- Portfolio management across multiple products
- Multiple stakeholder layers to manage
- Governance and approval flows
- Strategic planning cycles
- Platform thinking and reusability
- **Key focus:** Orchestration, strategic alignment

### 10k+ (Large Enterprise)
- Political navigation and influence
- Long planning cycles (annual, quarterly)
- Influence without direct authority
- Executive alignment is critical
- Change management and adoption
- **Key focus:** Strategic impact, organizational effectiveness
