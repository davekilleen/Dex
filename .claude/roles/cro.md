# CRO

## Pillars

1. **Revenue Growth** - Bookings, ARR/MRR, expansion, new business
2. **GTM Strategy** - Sales motion, market coverage, channel strategy
3. **Sales Excellence** - Methodology, enablement, performance
4. **Customer Expansion** - Upsell, cross-sell, retention revenue

## Key Workflows

- **Pipeline Reviews** - Forecast, deal inspection, risk assessment
- **Forecast Management** - Commit accuracy, board reporting
- **Territory Planning** - Coverage model, quota setting, capacity
- **Sales Enablement** - Training, playbooks, tools
- **GTM Strategy** - Market expansion, segment focus, channel
- **Executive Reporting** - Board updates, investor calls

## Folder Structure (PARA)

*Dex uses PARA: Projects, Areas, Resources, Archives*

```
# State files at root
03-Tasks/Tasks.md              # Task backlog tagged with pillars and goals
02-Week_Priorities/Week_Priorities.md    # Top 3 priorities this week
01-Quarter_Goals/Quarter_Goals.md      # Quarterly goals (required for CROs)

# Projects = time-bound initiatives
04-Projects/
├── Q1_Forecast/      # Quarterly forecasting cycles
├── Territory_Plan_2026/ # Territory planning
├── Market_Expansion_[Region]/ # Market expansion projects
├── Sales_Kickoff/    # Sales kickoff events
└── Hiring_[Role]/    # Sales leadership hires

# Areas = ongoing responsibilities
05-Areas/
├── Accounts/         # Strategic account oversight
│   └── [Account_Name].md # Strategic account relationships
└── People/           # Key relationships
    ├── Internal/     # Executive team, sales leadership, marketing, CS
    └── External/     # Strategic customers, partners

# Resources = reference material
06-Resources/
├── Strategy/         # GTM plan, market strategies
├── Playbooks/        # Sales playbooks, methodologies
├── Enablement/       # Training materials, tools
├── Templates/        # Forecast, QBR, territory plan templates
└── Learnings/        # What works, deal post-mortems

# Archives = historical records
07-Archives/
├── 04-Projects/         # Past forecasts, completed expansions
├── Plans/            # Daily/weekly plans
└── Reviews/          # Daily/weekly/quarterly reviews

# Inbox = capture zone
00-Inbox/
├── Meetings/         # All meeting notes
├── Deal_Reviews/     # Strategic deal reviews to triage
├── Ideas/            # GTM ideas, sales strategies
```

**Role-specific areas for CRO:**
- `05-Areas/Accounts/` - Strategic account executive relationships

**Note on Companies vs Accounts:**
- `05-Areas/Companies/` - Universal company tracking (contacts, meetings, notes)
- `05-Areas/Accounts/` - Sales/CS-specific (includes ARR, health scores, deal tracking)
- Many orgs use just Companies/, others use Accounts/ for strategic customers
- Choose based on your needs during onboarding

**What goes where:**
- **04-Projects/**: Forecasting cycles, territory planning, market expansion (time-bound)
- **05-Areas/Accounts/**: Strategic account relationships, executive engagement
- **05-Areas/People/**: Sales leadership, executive team, GTM partners
- **06-Resources/**: GTM strategy, playbooks, enablement, methodologies

**Areas vs. Projects:**
- **Account** (Area) = Ongoing strategic relationship with Fortune 500 customer
- **Project** = Close Q1 forecast, expand into EMEA region by Q3

## Templates

- `Forecast_Review.md` - Weekly forecast template
- `QBR_Prep.md` - Quarterly business review
- `Territory_Plan.md` - Territory design
- `Deal_Review.md` - Strategic deal assessment
- `Board_Update.md` - Revenue board presentation
- `GTM_Strategy.md` - Go-to-market planning

## Integrations

- **Salesforce** - CRM
- **Clari/Gong** - Revenue intelligence
- **Outreach/Salesloft** - Sales engagement
- **Slack** - Communication
- **Tableau/Looker** - Analytics
- **Highspot/Seismic** - Enablement

## Size Variants

### 1-100 (Startup)
- VP Sales or founder-led sales
- Building sales motion
- First playbooks
- **Folder adjustment:** Lean structure, focus on Revenue and basic Enablement
- **Key focus:** Find repeatable sales motion, early wins, prove model

### 100-1k (Scaling)
- Full CRO role
- Scaling sales org
- Process formalization
- **Folder adjustment:** Expand Sales_Org, add `Segments/`
- **Key focus:** Scale sales, build team, repeatable process

### 1k-10k (Enterprise)
- Revenue organization
- Multiple segments/regions
- Mature go-to-market
- **Folder adjustment:** Add `Regions/`, `Channels/`
- **Key focus:** Market expansion, segment optimization, team development

### 10k+ (Large Enterprise)
- Global revenue organization
- Enterprise sales motion
- Strategic accounts
- **Folder adjustment:** Add `Global/`, `Strategic_Accounts/`, `Partners/`
- **Key focus:** Global revenue, strategic deals, partner ecosystem
