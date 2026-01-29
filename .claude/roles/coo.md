# COO

## Pillars

1. **Operational Excellence** - Process efficiency, quality, consistency
2. **Scaling** - Growth enablement, capacity planning, infrastructure
3. **Cross-functional Alignment** - Team coordination, communication, collaboration
4. **Efficiency** - Cost optimization, resource allocation, productivity

## Key Workflows

- **Process Optimization** - Workflow design, automation, improvement
- **Org Design** - Structure, roles, reporting lines
- **Vendor Management** - Contracts, relationships, performance
- **Metrics & OKRs** - KPI tracking, goal setting, accountability
- **Strategic Projects** - Cross-functional initiatives, transformations
- **Risk Management** - Operational risk, business continuity

## Folder Structure (PARA)

*Dex uses PARA: Projects, Areas, Resources, Archives*

```
# State files at root
03-Tasks/Tasks.md              # Task backlog tagged with pillars and goals
02-Week_Priorities/Week_Priorities.md    # Top 3 priorities this week
01-Quarter_Goals/Quarter_Goals.md      # Quarterly goals (required for COOs)

# Projects = time-bound operational initiatives
04-Projects/
├── Process_Improvement_[Area]/ # Process redesigns
├── Org_Redesign_2026/ # Organizational changes
├── System_Implementation/ # New system rollouts
├── Vendor_Evaluation/ # Vendor selections
└── Strategic_Initiative/ # Cross-functional projects

# Areas = ongoing responsibilities
05-Areas/
├── Team/             # Cross-functional team management
│   └── [Leader_Name].md # Department head 1:1s, alignment
└── People/           # Key relationships
    ├── Internal/     # Executive team, department heads
    └── External/     # Key vendors, partners

# Resources = reference material
06-Resources/
├── Playbooks/        # Process documentation
│   └── [Process_Name]/
│       ├── Workflow.md
│       ├── Metrics.md
│       └── Owner.md
├── Strategy/         # OKRs, annual plans, operating model
├── Vendors/          # Vendor contracts, performance docs
├── Templates/        # Process design, project charter templates
└── Learnings/        # Retrospectives, what works

# Archives = historical records
07-Archives/
├── 04-Projects/         # Completed initiatives, past org changes
├── Plans/            # Daily/weekly plans
└── Reviews/          # Daily/weekly/quarterly reviews

# Inbox = capture zone
00-Inbox/
├── Meetings/         # All meeting notes
├── Escalations/      # Urgent issues to triage
├── Ideas/            # Process improvements, efficiency ideas
```

**Role-specific areas for COO:**
- `05-Areas/Team/` - Department head and cross-functional team management

**What goes where:**
- **04-Projects/**: Process improvements, org changes, implementations (time-bound)
- **05-Areas/Team/**: Department head 1:1s, cross-functional alignment
- **05-Areas/People/**: Executive team, department heads, key vendors
- **06-Resources/Playbooks/**: Process documentation, workflows, procedures
- **06-Resources/Vendors/**: Vendor contracts, performance tracking

**Areas vs. Projects:**
- **Team member** (Area) = Ongoing 1:1 with VP Operations, alignment
- **Initiative** (Project) = Complete CRM migration by Q3

## Templates

- `Process_Design.md` - Process documentation
- `Org_Change.md` - Organizational change plan
- `Vendor_Review.md` - Vendor performance assessment
- `OKR_Review.md` - Quarterly OKR progress
- `Project_Charter.md` - Strategic project kickoff
- `Operating_Review.md` - Business review preparation

## Integrations

- **Asana/Monday** - Project management
- **Slack** - Communication
- **Analytics** - Business dashboards
- **HRIS** - Org data
- **Finance Systems** - Budget tracking
- **Notion/Confluence** - Documentation

## Size Variants

### 1-100 (Startup)
- Often combined with CEO or VP Ops
- Hands-on operations
- Building foundations
- **Folder adjustment:** Lean structure, focus on Operations and Vendors
- **Key focus:** Operational foundation, efficiency, enabling growth

### 100-1k (Scaling)
- Dedicated COO role
- Scaling operations
- Process standardization
- **Folder adjustment:** Expand Organization, add `Scaling/`
- **Key focus:** Scale operations, build org, formalize processes

### 1k-10k (Enterprise)
- Full operations organization
- Complex cross-functional work
- Transformation initiatives
- **Folder adjustment:** Add `Transformation/`, `Business_Units/`
- **Key focus:** Operational excellence, org design, strategic projects

### 10k+ (Large Enterprise)
- Global operations
- Multiple business units
- Enterprise transformation
- **Folder adjustment:** Add `Global/`, `Enterprise/`, `M&A_Integration/`
- **Key focus:** Global operations, M&A integration, enterprise strategy
