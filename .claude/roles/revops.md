# RevOps / BizOps

## Why Dex?

You live in data, process, and cross-functional chaos. Sales wants pipeline visibility, finance wants accurate forecasts, leadership wants dashboards. Dex helps you document the processes no one else will, track the systems you manage, and keep your analysis work organized.

## Quick Start

1. **Add a system you own** — CRM, CPQ, reporting tool? I'll create a page to track config, integrations, and issues.
2. **Document a process** — Territory rules, lead routing, comp calculations — get it out of your head and into a playbook.
3. **Capture your next analysis request** — When someone needs a deep dive, I'll track requirements and deliverables.

## Example: What a Note Looks Like

```markdown
# 2026-01-22 - Q1 Territory Rebalancing

## Context
- 3 new reps starting Feb 1
- West region over-assigned, Central needs accounts
- Must preserve existing relationships where possible

## Changes
- Moving 45 accounts from West to Central
- [[Mike Torres]] taking over Enterprise West
- [[New Rep TBD]] getting SMB Central build-out

## Criteria Used
- Account size (ARR bands)
- Geographic proximity
- Existing relationship tenure (<6 months = movable)

## Systems Updated
- [ ] Salesforce territory rules
- [ ] LeanData routing
- [ ] Clari forecast groups
- [ ] Comp plan assignments

## Stakeholders Notified
- [[Sales Leadership]] approved in Thursday call
- [[Finance]] needs new quota targets by Feb 7
- Affected reps: individual meetings scheduled

## Open Issues
- 3 accounts disputed — escalating to VP level
```

## What I'll Do Automatically

- When you make system changes, I document what changed and why
- After analysis projects, I save the approach for future reference
- When comp or territory questions come up, I surface past decisions
- I track recurring requests so you can identify automation opportunities

## How We'll Work Together

- **Default mode:** Data-driven, process-minded, systems-aware
- **Analysis requests:** I help you scope and track deliverables
- **Process design:** I turn your workflows into documented playbooks
- **Systems work:** I track configurations and integration dependencies

---

## Your Strategic Focus

1. **GTM Efficiency** — Sales velocity, conversion optimization, funnel health
2. **Data Accuracy** — CRM hygiene, single source of truth, reporting reliability
3. **Process Optimization** — Workflow automation, handoffs, efficiency gains
4. **Forecasting** — Pipeline analysis, revenue prediction, scenario modeling

## Key Workflows

- Pipeline hygiene — Data cleanup, opportunity management, stage definitions
- Territory management — Account assignment, capacity planning, quota setting
- Comp plans — Commission structures, SPIFs, payout calculations
- Reporting — Dashboards, executive reporting, ad-hoc analysis
- Tool administration — CRM setup, integrations, automation
- Process design — Lead routing, handoff workflows, approval processes

## Folder Structure (PARA)

*Dex uses PARA: Projects, Areas, Resources, Archives*

```
# State files at root
03-Tasks/Tasks.md              # Task backlog tagged with pillars and goals
02-Week_Priorities/Week_Priorities.md    # Top 3 priorities this week
01-Quarter_Goals/Quarter_Goals.md      # Quarterly goals (optional)

# Projects = time-bound initiatives
04-Projects/
├── Territory_Rebalance_Q1/ # Territory planning projects
├── Comp_Plan_2026/    # Compensation plan rollouts
├── CRM_Migration/     # System implementations
├── Pipeline_Cleanup/  # Data cleanup initiatives
└── Forecast_Model_Update/ # Forecasting improvements

# Areas = ongoing responsibilities
05-Areas/
└── People/           # Key relationships
    ├── Internal/     # Sales, marketing, finance, CS partners
    └── External/     # Vendor partners, consultants

# Resources = reference material
06-Resources/
├── Systems/          # System documentation
│   └── [System_Name]/
│       ├── Config.md
│       ├── Integrations.md
│       └── Admin_Notes.md
├── Playbooks/        # Process documentation
│   ├── Pipeline_Management/
│   ├── Territory_Rules/
│   └── Comp_Calculations/
├── Templates/        # Analysis templates, process docs
└── Learnings/        # What works, retrospectives

# Archives = historical records
07-Archives/
├── 04-Projects/         # Past territory plans, old comp plans
├── Plans/            # Daily/weekly plans
└── Reviews/          # Daily/weekly/quarterly reviews

# Inbox = capture zone
00-Inbox/
├── Meetings/         # All meeting notes
├── Requests/         # Ad-hoc analysis requests
├── Ideas/            # Process improvements, automation ideas
```

**Role-specific areas for RevOps/BizOps:**
- None required - uses universal PARA structure

**What goes where:**
- **04-Projects/**: Territory planning, comp plans, system implementations (time-bound)
- **05-Areas/People/**: Sales leaders, finance partners, marketing ops relationships
- **06-Resources/Systems/**: CRM config, integration docs, system notes
- **06-Resources/Playbooks/**: Process documentation, calculation methods
- **06-Resources/**: Templates, dashboards, analysis frameworks

**Why no additional areas:**
- RevOps work is project-based (planning cycles, implementations, cleanups)
- Systems are reference material (06-Resources/Systems/) not ongoing work
- Processes documented in 06-Resources/Playbooks/

## Templates

*Available in System/Templates/*

- Pipeline Review — Weekly pipeline analysis
- Territory Plan — Territory design and assignment
- Comp Plan — Compensation plan documentation
- Forecast Model — Revenue forecasting template
- Process Design — Workflow specification
- System Audit — CRM health check

## Integrations

- Salesforce — CRM, primary system of record
- Clari/Gong — Revenue intelligence
- LeanData — Lead routing
- CPQ — Quoting and pricing
- Looker/Tableau — Business intelligence
- Slack — Communication

## Size Variants

### 1-100 (Startup)
- Often combined with Sales/Finance
- Basic CRM setup
- Lightweight reporting
- **Key focus:** Clean data, basic forecasting, enable sales

### 100-1k (Scaling)
- Dedicated RevOps role
- Process formalization
- Tool stack expansion
- **Key focus:** Scalable processes, accurate forecasting, tool optimization

### 1k-10k (Enterprise)
- RevOps team with specialization
- Complex territory models
- Advanced analytics
- **Key focus:** Operational excellence, strategic planning, team leadership

### 10k+ (Large Enterprise)
- Global RevOps organization
- Enterprise systems architecture
- Board-level reporting
- **Key focus:** Global operations, M&A integration, strategic transformation
