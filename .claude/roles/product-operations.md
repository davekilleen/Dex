# Product Operations

## Why Dex?

You're the glue between product, engineering, and go-to-market. Releases, processes, analytics, tools — you keep everything running smoothly. Dex helps you document processes that actually get followed, track releases without dropping balls, and surface insights from the chaos.

## Quick Start

1. **Add an upcoming release** — What's shipping next? I'll create a page to track the checklist and stakeholders.
2. **Document a process** — Got a workflow that's in your head? Tell me how it works and I'll turn it into a playbook.
3. **Log a cross-functional meeting** — Coordination is your job. I'll track who needs what and follow up.

## Example: What a Note Looks Like

```markdown
# 2026-01-22 - Q1 Release Planning

## Release: v2.5 (Analytics Dashboard)
- Target date: Feb 15
- Go/no-go decision: Feb 10
- Owner: [[Sarah Kim]]

## Checklist Status
- [x] Feature complete
- [x] QA sign-off
- [ ] Documentation updated
- [ ] Sales enablement ready
- [ ] Marketing assets approved

## Dependencies
- [[Marketing]] needs 3 days notice for blog post
- [[CS Team]] wants training session before launch
- [[Support]] updating help docs, ETA Feb 12

## Risks
- Docs team at capacity — may need to deprioritize other work
- One critical bug still open, engineering confident in fix

## Action Items
- [ ] Confirm marketing blog date
- [ ] Schedule CS training for Feb 13
- [ ] Follow up on bug fix status Thursday
```

## What I'll Do Automatically

- When releases are planned, I track all the moving pieces and dependencies
- After retros, I capture improvements and make sure they get implemented
- When processes change, I update the relevant playbooks
- I flag when releases are at risk based on checklist status

## How We'll Work Together

- **Default mode:** Organized, systematic, cross-functional aware
- **Release mode:** I help you track every detail and stakeholder
- **Process design:** I turn conversations into documented workflows
- **Analytics support:** I help you spot data quality issues and surface insights

---

## Your Strategic Focus

1. **Process Excellence** — Release management, planning cadences, workflows
2. **Data Integrity** — Analytics accuracy, instrumentation, reporting
3. **Cross-functional Enablement** — Tool adoption, training, documentation
4. **Tool Management** — Product stack optimization, integrations

## Key Workflows

- Release coordination — Launch planning, stakeholder communication, go-live
- Analytics management — Dashboard maintenance, data quality, reporting
- Process documentation — Playbooks, runbooks, best practices
- Tool administration — Product tools setup, permissions, integrations
- Planning support — OKR tracking, roadmap maintenance, capacity planning
- Stakeholder enablement — Training, documentation, self-service

## Folder Structure (PARA)

*Dex uses PARA: Projects, Areas, Resources, Archives*

```
# State files at root
03-Tasks/Tasks.md              # Task backlog tagged with pillars and goals
02-Week_Priorities/Week_Priorities.md    # Top 3 priorities this week
01-Quarter_Goals/Quarter_Goals.md      # Quarterly goals (optional)

# Projects = time-bound initiatives
04-Projects/
├── Release_v2_5/     # Release coordination projects
├── Tool_Migration/   # Tool implementations
├── Process_Improvement/ # Process redesigns
└── Analytics_Cleanup/ # Data quality initiatives

# Areas = ongoing responsibilities
05-Areas/
└── People/           # Key relationships
    ├── Internal/     # Product, engineering, GTM partners
    └── External/     # Vendor partners, tool providers

# Resources = reference material
06-Resources/
├── Playbooks/        # Process documentation
│   ├── Planning/     # Planning processes
│   ├── Development/  # Development workflows
│   └── Launch/       # Launch checklists
├── Tools/            # Tool documentation
│   └── [Tool_Name]/
│       ├── Setup.md
│       ├── Admin.md
│       └── Integrations.md
├── Analytics/        # Dashboard specs, data dictionaries
├── Templates/        # Release plan, process doc templates
└── Learnings/        # Retros, what works

# Archives = historical records
07-Archives/
├── 04-Projects/         # Past releases, completed migrations
├── Plans/            # Daily/weekly plans
└── Reviews/          # Daily/weekly/quarterly reviews

# Inbox = capture zone
---Inbox/
├── Meetings/         # All meeting notes
├── Requests/         # Stakeholder requests
├── Ideas/            # Process improvements, tool ideas
```

**Role-specific areas for Product Operations:**
- None required - uses universal PARA structure

**What goes where:**
- **04-Projects/**: Releases, tool migrations, process improvements (time-bound)
- **05-Areas/People/**: Product managers, engineering partners, GTM stakeholders
- **06-Resources/Playbooks/**: Process documentation, runbooks, checklists
- **06-Resources/Tools/**: Tool configuration, admin guides, integrations
- **06-Resources/Analytics/**: Dashboard specs, data dictionaries, reporting

**Why no additional areas:**
- Product ops work is project-based (releases, implementations, improvements)
- Processes documented in 06-Resources/Playbooks/
- Tools documented in 06-Resources/Tools/

## Templates

*Available in System/Templates/*

- Release Plan — Launch coordination checklist
- Process Doc — Standard operating procedure
- Dashboard Spec — Analytics dashboard requirements
- Tool Evaluation — Tool assessment criteria
- Quarterly Planning — Planning cycle template
- Training Guide — Enablement documentation

## Integrations

- Jira/Linear — Issue tracking, release management
- Amplitude/Mixpanel — Product analytics
- Confluence/Notion — Documentation
- Slack — Communication, workflows
- Productboard — Roadmap management
- Looker/Tableau — Business intelligence

## Size Variants

### 1-100 (Startup)
- Often combined with PM role
- Lightweight processes
- Tool setup and management
- **Key focus:** Enable PMs, set up analytics, minimal viable process

### 100-1k (Scaling)
- Dedicated ProdOps role emerges
- Process standardization
- Cross-team coordination
- **Key focus:** Scale product team, standardize processes, data quality

### 1k-10k (Enterprise)
- ProdOps team
- Governance and compliance
- Portfolio-level operations
- **Key focus:** Operational excellence, portfolio management, team efficiency

### 10k+ (Large Enterprise)
- ProdOps organization
- Enterprise tool strategy
- Cross-org standardization
- **Key focus:** Org-wide enablement, tool consolidation, strategic operations
