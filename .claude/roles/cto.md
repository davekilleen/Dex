# CTO

## Pillars

1. **Technical Vision** - Architecture strategy, technology direction, innovation
2. **Engineering Excellence** - Quality, velocity, best practices
3. **Innovation** - R&D, emerging tech, competitive advantage
4. **Security** - Technical security, compliance, risk management

## Key Workflows

- **Architecture Decisions** - System design, technology choices, technical debt
- **Tech Strategy** - Roadmap, build vs. buy, platform decisions
- **Team Scaling** - Hiring, org design, engineering culture
- **Vendor Evaluation** - Technology partners, tools, infrastructure
- **Security Oversight** - Security posture, compliance, incidents
- **Executive Reporting** - Board updates, technical risk, investment

## Folder Structure (PARA)

*Dex uses PARA: Projects, Areas, Resources, Archives*

```
# State files at root
03-Tasks/Tasks.md              # Task backlog tagged with pillars and goals
02-Week_Priorities/Week_Priorities.md    # Top 3 priorities this week
01-Quarter_Goals/Quarter_Goals.md      # Quarterly goals (required for CTOs)

# Projects = time-bound strategic initiatives
04-Projects/
├── Migration_[System]/ # System migrations
├── Security_Audit_2026/ # Security initiatives
├── Hiring_[Role]/    # Executive/leadership hires
├── Architecture_Redesign/ # Major architecture projects
└── Innovation_POC/   # R&D proof of concepts

# Areas = ongoing responsibilities
05-Areas/
├── Team/             # Engineering organization management
│   └── [Leader_Name].md # 1:1 threads, development plans
└── People/           # Key relationships
    ├── Internal/     # Executive team, eng leadership, product
    └── External/     # Vendors, technology partners

# Resources = reference material
06-Resources/
├── Strategy/         # Tech vision, architecture roadmap
├── Architecture/     # Systems, decisions (ADRs), standards
│   ├── Systems/
│   ├── Decisions/
│   └── Standards/
├── Security/         # Security posture, compliance docs
├── Templates/        # ADR template, strategy doc templates
├── Patterns/         # Engineering patterns, best practices
└── Learnings/        # Post-mortems, retrospectives

# Archives = historical records
07-Archives/
├── 04-Projects/         # Completed migrations, past initiatives
├── Plans/            # Daily/weekly plans
└── Reviews/          # Daily/weekly/quarterly reviews

# Inbox = capture zone
00-Inbox/
├── Meetings/         # All meeting notes
├── Decisions/        # Technical decisions to document
├── Ideas/            # Innovation ideas, R&D
```

**Role-specific areas for CTO:**
- `05-Areas/Team/` - Engineering leadership team management

**What goes where:**
- **04-Projects/**: Migrations, security audits, hiring, architecture redesigns (time-bound)
- **05-Areas/Team/**: Engineering leadership 1:1s, development plans, delegation
- **05-Areas/People/**: Executive team, eng leaders, product partners, vendors
- **06-Resources/Architecture/**: System docs, ADRs, standards (reference material)
- **06-Resources/Strategy/**: Tech vision, roadmap, annual plans

**Areas vs. Projects:**
- **Team member** (Area) = Ongoing 1:1 with VP Engineering, development plan
- **Initiative** (Project) = Complete microservices migration by Q2

## Templates

- `Architecture_Decision.md` - ADR template
- `Tech_Strategy.md` - Technology strategy document
- `Security_Review.md` - Security assessment
- `Vendor_Evaluation.md` - Technology vendor assessment
- `Board_Update.md` - Technical board presentation
- `Team_Review.md` - Engineering org assessment

## Integrations

- **GitHub/GitLab** - Source control
- **Datadog/New Relic** - Observability
- **AWS/GCP/Azure** - Cloud platforms
- **Slack** - Communication
- **Jira/Linear** - Project tracking
- **Notion/Confluence** - Documentation

## Size Variants

### 1-100 (Startup)
- Hands-on CTO
- Coding and architecture
- Building foundations
- **Folder adjustment:** Lean structure, focus on Architecture and Engineering
- **Key focus:** Build product, technical foundation, hire first engineers

### 100-1k (Scaling)
- Transitioning from IC to leader
- Building engineering org
- Platform investment
- **Folder adjustment:** Expand Engineering, add `Platform/`
- **Key focus:** Scale engineering, build leadership, architecture for scale

### 1k-10k (Enterprise)
- Engineering executive
- Multiple teams/domains
- Technical governance
- **Folder adjustment:** Add `Governance/`, `Domains/`
- **Key focus:** Technical strategy, org design, cross-team architecture

### 10k+ (Large Enterprise)
- Enterprise technology leader
- Global engineering
- Digital transformation
- **Folder adjustment:** Add `Global/`, `Transformation/`, `Board/`
- **Key focus:** Enterprise technology, innovation strategy, industry influence
