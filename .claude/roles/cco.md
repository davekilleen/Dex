# CCO (Chief Customer Officer)

## Pillars

1. **Customer Experience** - Journey optimization, touchpoints, satisfaction
2. **Retention** - Churn prevention, renewal rates, customer health
3. **Advocacy** - NPS, references, community, word-of-mouth
4. **Voice of Customer** - Feedback synthesis, insights, product influence

## Key Workflows

- **Customer Health** - Portfolio health, risk identification, intervention
- **Escalations** - Executive engagement, resolution, relationship repair
- **Journey Optimization** - Touchpoint analysis, experience improvement
- **Feedback Loops** - VoC programs, feedback to product, closed-loop
- **Advocacy Programs** - Reference cultivation, community, events
- **Executive Reporting** - Board updates, customer metrics, retention

## Folder Structure (PARA)

*Dex uses PARA: Projects, Areas, Resources, Archives*

```
# State files at root
03-Tasks/Tasks.md              # Task backlog tagged with pillars and goals
02-Week_Priorities/Week_Priorities.md    # Top 3 priorities this week
01-Quarter_Goals/Quarter_Goals.md      # Quarterly goals (required for CCOs)

# Projects = time-bound customer initiatives
04-Projects/
├── CX_Initiative_[Name]/ # Customer experience projects
├── Journey_Optimization/ # Journey mapping projects
├── Advocacy_Program/  # Advocacy program launches
├── VoC_Research/      # Voice of customer research
└── Escalation_[Account]/ # Major escalations

# Areas = ongoing responsibilities
05-Areas/
├── Accounts/         # Strategic customer portfolio oversight
│   └── [Account_Name].md # Strategic customer relationships
└── People/           # Key relationships
    ├── Internal/     # Executive team, CS leadership, product, sales
    └── External/     # Customer executives, community leaders

# Resources = reference material
06-Resources/
├── Strategy/         # CX strategy, retention plans
├── Journey_Maps/     # Customer journey documentation
├── VoC/              # Voice of customer insights, research
├── Playbooks/        # CS playbooks, escalation procedures
├── Templates/        # Health review, escalation brief templates
└── Learnings/        # Customer retrospectives, what works

# Archives = historical records
07-Archives/
├── 04-Projects/         # Completed initiatives, resolved escalations
├── Plans/            # Daily/weekly plans
└── Reviews/          # Daily/weekly/quarterly reviews

# Inbox = capture zone
00-Inbox/
├── Meetings/         # All meeting notes
├── Escalations/      # Customer escalations to triage
├── Ideas/            # CX improvements, program ideas
```

**Role-specific areas for CCO:**
- `05-Areas/Accounts/` - Strategic customer portfolio and executive relationships

**Note on Companies vs Accounts:**
- `05-Areas/Companies/` - Universal company tracking (contacts, meetings, notes)
- `05-Areas/Accounts/` - Sales/CS-specific (includes ARR, health scores, deal tracking)
- Many orgs use just Companies/, others use Accounts/ for strategic customers
- Choose based on your needs during onboarding

**What goes where:**
- **04-Projects/**: CX initiatives, journey projects, advocacy programs (time-bound)
- **05-Areas/Accounts/**: Strategic customer executive relationships, health oversight
- **05-Areas/People/**: CS leadership, executive team, customer executives
- **06-Resources/**: CX strategy, journey maps, VoC insights, playbooks

**Areas vs. Projects:**
- **Account** (Area) = Ongoing strategic relationship with key customer
- **Project** = Launch customer advisory board program by Q3

## Templates

- `CX_Strategy.md` - Customer experience strategy
- `Journey_Map.md` - Customer journey documentation
- `Health_Review.md` - Portfolio health assessment
- `Escalation_Brief.md` - Executive escalation summary
- `Board_Update.md` - Customer board presentation
- `VoC_Report.md` - Voice of customer synthesis

## Integrations

- **Gainsight/ChurnZero** - Customer success platform
- **Pendo/Amplitude** - Product analytics
- **Medallia/Qualtrics** - Experience management
- **Salesforce** - CRM
- **Slack** - Communication
- **Zendesk/Intercom** - Support

## Size Variants

### 1-100 (Startup)
- Customer success lead or VP CS
- Direct customer relationships
- CCO role uncommon at this stage
- **Folder adjustment:** Focus on Customer_Health, lean structure
- **Key focus:** Retention, early customer success, feedback loops

### 100-1k (Scaling)
- First CCO hire
- Building customer org
- Process establishment
- **Folder adjustment:** Expand all sections, add `Team/`
- **Key focus:** Scale CS, formalize health scoring, build programs

### 1k-10k (Enterprise)
- Full CCO role
- Customer organization
- Mature programs
- **Folder adjustment:** Add `Enterprise_Customers/`, `Programs/`
- **Key focus:** Customer excellence, experience optimization, strategic accounts

### 10k+ (Large Enterprise)
- Global customer organization
- Enterprise experience
- Board-level customer focus
- **Folder adjustment:** Add `Global/`, `Strategic/`, `Digital_CX/`
- **Key focus:** Global customer experience, digital transformation, market leadership
