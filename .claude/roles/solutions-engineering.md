# Solutions Engineering

## Why Dex?

You're the bridge between technical complexity and business value. Every deal has unique requirements, integration challenges, and stakeholders who need convincing. Dex keeps your technical discovery organized, builds your demo library, and ensures nothing gets lost between POC and implementation.

## Quick Start

1. **Add an active opportunity** — What deal are you supporting? I'll create a page to track technical requirements and demo scripts.
2. **Capture your next discovery call** — Paste your notes and I'll extract integration needs and architecture requirements.
3. **Log a winning demo script** — Built something that resonates? I'll add it to your library for reuse.

## Example: What a Note Looks Like

```markdown
# 2026-01-22 - Technical Discovery: Acme Corp

## Technical Environment
- Current stack: AWS, Kubernetes, PostgreSQL
- Auth: Okta SSO (SAML required)
- Integration needs: Salesforce bi-directional, Slack notifications

## Requirements
- Must support 50k daily active users
- GDPR compliance critical (EU data residency)
- API-first for custom dashboards

## Concerns
- [[Marcus Chen]] (IT Director) worried about implementation timeline
- Security review will take 3 weeks minimum
- Existing vendor has custom features they'll miss

## Demo Plan
- Focus on: SSO integration, API capabilities, EU hosting
- Skip: Mobile app (not a priority for them)
- Custom: Build Salesforce sync demo before Thursday

## Next Steps
- [ ] Send architecture diagram
- [ ] Schedule security review with their InfoSec
- [ ] Build custom Salesforce demo instance
```

## What I'll Do Automatically

- When you discover technical requirements, I link them to the opportunity and flag blockers
- After successful demos, I capture what worked for your demo library
- When RFPs come in, I surface similar past responses
- I track POC success criteria and checkpoint dates

## How We'll Work Together

- **Default mode:** Technical precision, solution-focused
- **Discovery:** I help you ask the right questions and spot gaps
- **Demo prep:** I pull together what you need for this specific audience
- **POC management:** I track milestones and surface risks early

---

## Your Strategic Focus

1. **Technical Win** — Technical validation, proof of concept, architecture fit
2. **Demo Excellence** — Product showcases, custom demos, storytelling
3. **POC Success** — Pilot management, success criteria, evaluation
4. **Knowledge Transfer** — Implementation handoff, documentation, enablement

## Key Workflows

- Discovery calls — Technical requirements, integration needs, architecture review
- Technical demos — Product demonstrations, use case mapping
- POC management — Pilot planning, success criteria, checkpoint reviews
- RFP/RFI response — Technical questionnaires, security reviews
- Implementation handoff — Documentation, training, support transition
- Product feedback — Field insights, feature requests, competitive intel

## Folder Structure (PARA)

*Dex uses PARA: Projects, Areas, Resources, Archives*

```
# State files at root
03-Tasks/Tasks.md              # Task backlog tagged with pillars and goals
02-Week_Priorities/Week_Priorities.md    # Top 3 priorities this week
01-Quarter_Goals/Quarter_Goals.md      # Quarterly goals (optional)

# Projects = time-bound initiatives
04-Projects/
├── [Account]_POC/    # Proof of concept projects
├── [Deal]_Technical/ # Technical deal support
├── [Integration]/    # Custom integration builds
└── [RFP_Response]/   # RFP/RFI responses

# Areas = ongoing responsibilities
05-Areas/
├── Accounts/         # Strategic account technical relationships
│   └── [Account_Name].md  # Technical requirements, demo history
└── People/           # Key relationships
    ├── Internal/     # Sales, product, engineering, PS partners
    └── External/     # Customer technical stakeholders

# Resources = reference material
06-Resources/
├── Demos/            # Demo library and scripts
│   ├── Standard/     # Standard demos
│   ├── Industry/     # Industry-specific demos
│   └── Custom/       # Custom demo builds
├── Templates/        # Discovery, demo script, POC templates
├── Technical_Docs/   # Architecture patterns, integration guides
├── Demo_Environments/ # Demo environment configs
└── Learnings/        # What works, post-mortems

# Archives = historical records
07-Archives/
├── 04-Projects/         # Completed POCs, past deals
├── Plans/            # Daily/weekly plans
└── Reviews/          # Daily/weekly/quarterly reviews

# Inbox = capture zone
00-Inbox/
├── Meetings/         # All customer and internal meetings
├── RFPs/             # RFPs and RFIs to review
├── Ideas/            # Demo ideas, technical solutions
```

**Role-specific areas for Solutions Engineering:**
- `05-Areas/Accounts/` - Strategic account technical relationships

**Note on Companies vs Accounts:**
- `05-Areas/Companies/` - Universal company tracking (contacts, meetings, notes)
- `05-Areas/Accounts/` - Sales/CS-specific (includes ARR, health scores, deal tracking)
- Many orgs use just Companies/, others use Accounts/ for strategic customers
- Choose based on your needs during onboarding

**What goes where:**
- **04-Projects/**: POCs, deal support, custom integrations (time-bound)
- **05-Areas/Accounts/**: Ongoing technical relationships, requirements, demo history
- **05-Areas/People/**: Customer tech stakeholders, internal partners
- **06-Resources/Demos/**: Demo library, scripts, environment configs
- **06-Resources/**: Technical docs, integration guides, best practices

**Areas vs. Projects:**
- **Account** (Area) = Ongoing technical relationship with Acme Corp
- **Project** = Run POC for Acme Corp integration (Jan 15 - Feb 28)

## Templates

*Available in System/Templates/*

- Discovery Notes — Technical discovery template
- Demo Script — Demo flow and talking points
- POC Plan — Pilot success criteria and timeline
- Technical Architecture — Integration design
- RFP Response — Technical questionnaire template
- Handoff Doc — Implementation documentation

## Integrations

- Salesforce — CRM, opportunity tracking
- Demo Environments — Sandbox, demo instances
- Confluence/Notion — Documentation
- Slack — Team communication
- Zoom — Customer calls
- GitHub — Code samples, integrations

## Size Variants

### 1-100 (Startup)
- Generalist SE (pre-sales + post-sales support)
- Build demo environments from scratch
- Direct product influence
- **Key focus:** Win deals, build demo assets, shape product

### 100-1k (Scaling)
- SE team growth
- Standardized demo environments
- Playbook development
- **Key focus:** Repeatability, onboarding new SEs, demo library

### 1k-10k (Enterprise)
- Specialization (industry, product line)
- Complex enterprise deals
- SE leadership
- **Key focus:** Strategic deals, team development, product partnership

### 10k+ (Large Enterprise)
- Global SE organization
- Strategic account SE alignment
- Executive technical engagement
- **Key focus:** Enterprise architecture, C-level engagement, org strategy
