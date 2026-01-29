# CPO

## Pillars

1. **Product Vision** - Strategy, direction, market positioning
2. **Customer Value** - User outcomes, satisfaction, adoption
3. **Portfolio Strategy** - Product lines, investments, trade-offs
4. **Product Excellence** - Quality, craft, innovation

## Key Workflows

- **Roadmap Strategy** - Portfolio planning, investment allocation
- **Product Strategy** - Vision, positioning, competitive differentiation
- **Customer Engagement** - Executive customer relationships, feedback synthesis
- **Team Development** - PM org building, hiring, coaching
- **Executive Reporting** - Board updates, product metrics, strategy
- **Cross-functional Leadership** - Engineering, design, GTM alignment

## Folder Structure (PARA)

*Dex uses PARA: Projects, Areas, Resources, Archives*

```
# State files at root
03-Tasks/Tasks.md              # Task backlog tagged with pillars and goals
02-Week_Priorities/Week_Priorities.md    # Top 3 priorities this week
01-Quarter_Goals/Quarter_Goals.md      # Quarterly goals (required for CPOs)

# Projects = time-bound product initiatives
04-Projects/
├── [Product_Launch]/ # Product launches
├── Portfolio_Review_Q1/ # Portfolio planning cycles
├── Customer_Research_[Topic]/ # Research projects
├── Roadmap_Planning_2026/ # Annual roadmap planning
└── Hiring_[Role]/    # PM leadership hires

# Areas = ongoing responsibilities
05-Areas/
└── People/           # Key relationships
    ├── Internal/     # Executive team, PM leadership, eng, design, GTM
    └── External/     # Customer executives, advisory board

# Resources = reference material
06-Resources/
├── Strategy/         # Product vision, portfolio strategy
├── Products/         # Product documentation
│   └── [Product_Name]/
│       ├── Strategy.md
│       ├── Roadmap.md
│       └── Metrics.md
├── Customer/         # Research synthesis, feedback analysis
├── Frameworks/       # Decision frameworks, prioritization
├── Templates/        # Strategy doc, board update templates
└── Learnings/        # Product retrospectives, lessons

# Archives = historical records
07-Archives/
├── 04-Projects/         # Completed launches, past roadmap cycles
├── Plans/            # Daily/weekly plans
└── Reviews/          # Daily/weekly/quarterly reviews

# Inbox = capture zone
00-Inbox/
├── Meetings/         # All meeting notes
├── Ideas/            # Product ideas, opportunities
├── Decisions/        # Major product decisions to document
```

**Role-specific areas for CPO:**
- None required - uses universal PARA structure

**What goes where:**
- **04-Projects/**: Product launches, research studies, roadmap planning (time-bound)
- **05-Areas/People/**: PM leadership, executive team, customer executives
- **06-Resources/Products/**: Product strategies, roadmaps, metrics (reference docs)
- **06-Resources/Strategy/**: Product vision, portfolio strategy, frameworks

**Why no additional areas:**
- Product work is naturally time-bound (launches, research, planning cycles)
- Product docs are reference material (06-Resources/Products/)
- Team management tracked in People/ (PM leadership relationships)

## Templates

- `Product_Strategy.md` - Product strategy document
- `Portfolio_Review.md` - Portfolio assessment
- `Board_Update.md` - Product board presentation
- `Customer_Advisory.md` - Customer advisory board notes
- `Team_Review.md` - PM org assessment
- `Investment_Decision.md` - Product investment analysis

## Integrations

- **Productboard/Aha** - Product management
- **Amplitude/Mixpanel** - Product analytics
- **Figma** - Design collaboration
- **Jira/Linear** - Development tracking
- **Slack** - Communication
- **Dovetail** - Research repository

## Size Variants

### 1-100 (Startup)
- VP Product or Head of Product
- Hands-on product work
- Small PM team or solo
- **Folder adjustment:** Lean structure, focus on Products and Customer
- **Key focus:** Product-market fit, customer obsession, ship fast

### 100-1k (Scaling)
- Full CPO role
- Building PM team
- Process establishment
- **Folder adjustment:** Expand Team, add `Processes/`
- **Key focus:** Scale product org, repeatable processes, portfolio management

### 1k-10k (Enterprise)
- Product organization
- Multiple product lines
- Governance and strategy
- **Folder adjustment:** Expand Governance, add `Product_Lines/`
- **Key focus:** Portfolio strategy, product org excellence, market expansion

### 10k+ (Large Enterprise)
- Enterprise product leader
- Global product organization
- Strategic product decisions
- **Folder adjustment:** Add `Global/`, `M&A/`, `Innovation/`
- **Key focus:** Product strategy at scale, M&A product integration, market leadership
