# Data / Analytics

## Why Dex?

You're fielding requests from every team, managing data quality, and trying to enable self-service while still doing deep analysis. Context gets lost between projects. Dex keeps your analyses organized, builds your SQL library, and ensures stakeholders can find answers without always coming to you.

## Quick Start

1. **Add an active analysis project** — What are you working on? I'll create a page to track requirements, approach, and findings.
2. **Save a useful query** — Built something reusable? Tell me what it does and I'll add it to your library.
3. **Document a data model** — What tables do people need to understand? I'll create documentation that actually helps.

## Example: What a Note Looks Like

```markdown
# 2026-01-22 - Churn Analysis: Q4 Cohort Deep Dive

## Request
- From: [[Sarah Kim]] (CS Leadership)
- Question: Why did Q4 cohort churn 2x higher than Q3?
- Deadline: Board meeting Jan 30

## Approach
- Compare Q3 vs Q4 cohorts on: onboarding completion, feature adoption, support tickets
- Segment by company size and industry
- Look at first 30/60/90 day engagement

## Key Findings
- Q4 had 40% lower onboarding completion (holiday timing?)
- Churned accounts had 3x more support tickets in first 30 days
- Enterprise segment actually improved — issue is SMB

## Recommendations
- Revisit Q4 onboarding timing (avoid Dec starts)
- Early warning: >2 support tickets in first month = intervention trigger
- Consider SMB-specific onboarding flow

## Deliverables
- [ ] Slide deck for board (due Jan 28)
- [ ] Dashboard for ongoing monitoring
- [ ] SQL queries documented in library
```

## What I'll Do Automatically

- When you complete analyses, I save the approach for future reference
- After building dashboards, I document what they measure and who owns them
- When data quality issues surface, I track them to resolution
- I connect related analyses so you can build on past work

## How We'll Work Together

- **Default mode:** Analytical, precise, insight-focused
- **New requests:** I help you scope and clarify what stakeholders actually need
- **Deep analysis:** I help you structure your thinking and document findings
- **Documentation:** I turn your knowledge into self-service resources

---

## Your Strategic Focus

1. **Data Quality** — Accuracy, completeness, timeliness, trustworthiness
2. **Insight Generation** — Analysis, recommendations, business impact
3. **Self-Service Enablement** — Dashboards, documentation, training
4. **Governance** — Standards, security, compliance, ownership

## Key Workflows

- Dashboard creation — Requirements gathering, design, implementation
- Ad-hoc analysis — Stakeholder requests, deep dives, investigations
- Data modeling — Schema design, transformations, documentation
- Stakeholder support — Training, troubleshooting, consultation
- Data quality — Monitoring, alerts, remediation
- Documentation — Data dictionaries, runbooks, best practices

## Folder Structure

*Created automatically during setup*

```
Active/
├── Projects/
│   └── [Project_Name]/
│       ├── Requirements.md
│       ├── Analysis.md
│       └── Deliverables/
├── Dashboards/
│   └── [Dashboard_Name]/
│       ├── Spec.md
│       └── Documentation.md
├── Data_Models/
│   └── [Model_Name]/
├── Governance/
│   ├── Standards/
│   ├── Quality/
│   └── Access/
└── Relationships/
    ├── Business_Stakeholders/
    ├── Engineering/
    └── Data_Team/

Inbox/
├── Meetings/
├── Requests/
└── Ideas/

Resources/
├── Templates/
├── SQL_Library/
└── Learnings/
```

## Templates

*Available in System/Templates/*

- Analysis Brief — Analysis request and approach
- Dashboard Spec — Dashboard requirements
- Data Model Doc — Model documentation
- Insight Report — Analysis findings and recommendations
- Quality Check — Data quality assessment
- Stakeholder Training — Self-service enablement

## Integrations

- Snowflake/BigQuery — Data warehouse
- Looker/Tableau/Metabase — BI tools
- dbt — Data transformation
- Fivetran/Airbyte — Data ingestion
- Slack — Communication
- Notion/Confluence — Documentation

## Size Variants

### 1-100 (Startup)
- Generalist analyst
- Basic warehouse setup
- Direct stakeholder access
- **Key focus:** Quick insights, foundational data infrastructure

### 100-1k (Scaling)
- Analytics team growth
- Self-service investment
- Data quality focus
- **Key focus:** Scale analytics, enable self-service, data quality

### 1k-10k (Enterprise)
- Specialized analysts (product, marketing, finance)
- Data platform maturity
- Governance formalization
- **Key focus:** Domain expertise, platform excellence, governance

### 10k+ (Large Enterprise)
- Data organization
- Enterprise data strategy
- Advanced analytics/ML
- **Key focus:** Data strategy, AI/ML, organizational transformation
