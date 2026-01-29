# Role-Specific Areas Mapping

**PARA Structure:** Projects, Areas, Resources, Archives

## Universal Areas (All Roles)

- `05-Areas/People/Internal/` - Colleagues, teammates
- `05-Areas/People/External/` - Customers, partners, vendors
- `05-Areas/Career/` - Career development (optional, via `/career-setup`)

## Role-Specific Areas

Only create additional areas if they provide clear value. Most roles use 04-Projects/ for time-bound work.

### Sales & Revenue Roles

**Roles:** Sales, Account Executive, CRO, RevOps
**Additional Area:**
- `05-Areas/Accounts/` - Strategic customer accounts (ongoing relationships)
  - Use for: Key account strategy, stakeholder maps, relationship tracking
  - 04-Projects/ used for: Individual deals, sales plays, contract renewals

### Customer-Facing Roles

**Roles:** Customer Success, Solutions Engineering, CCO
**Additional Area:**
- `05-Areas/Accounts/` - Customer portfolio
  - Use for: Customer health tracking, account strategies, relationship notes
  - 04-Projects/ used for: Onboarding, expansions, renewals, escalations

### Marketing Roles

**Roles:** Marketing, CMO
**Additional Area:**
- `05-Areas/Content/` - Content strategy and asset library
  - Use for: Content themes, messaging frameworks, evergreen assets
  - 04-Projects/ used for: Campaigns, launches, events

### Engineering Leadership

**Roles:** CTO, Engineering Manager
**Additional Area:**
- `05-Areas/Team/` - Engineering team management
  - Use for: Team member pages (beyond People/), 1:1 threads, hiring plans
  - 04-Projects/ used for: Migrations, infrastructure work, hiring sprints

### Product Roles

**Roles:** Product Manager, CPO, Product Operations, Fractional CPO
**Additional Areas:**
- None required
  - Use 04-Projects/ for: Product initiatives, roadmap items, research
  - Use 06-Resources/ for: Research synthesis, competitive intel, metrics
  - Use 05-Areas/People/ for: Stakeholder tracking

**Why no additional areas:**
- Product work is naturally time-bound (fits 04-Projects/)
- Stakeholders tracked in People/
- Reference material goes to 06-Resources/

### Finance Roles

**Roles:** Finance, CFO
**Additional Areas:**
- None required
  - Use 04-Projects/ for: Close cycles, board prep, budget planning
  - Use 06-Resources/ for: Templates, policies, audit docs
  - Use 05-Areas/People/ for: Business partner relationships

### Operations Roles

**Roles:** Product Operations, RevOps, BizOps, Data/Analytics
**Additional Areas:**
- None required
  - Use 04-Projects/ for: Process improvements, system implementations
  - Use 06-Resources/ for: Playbooks, documentation, metrics
  - Use 05-Areas/People/ for: Cross-functional relationships

### Design Roles

**Roles:** Design, Design Leadership
**Additional Areas:**
- None required
  - Use 04-Projects/ for: Design initiatives, system updates, research
  - Use 06-Resources/ for: Design system, patterns, research

### Support Functions

**Roles:** People/HR, Legal, IT Support, CHRO, CLO, CIO, CISO
**Additional Areas:**
- None required
  - Use 04-Projects/ for: Initiatives, implementations, audits
  - Use 06-Resources/ for: Policies, templates, compliance docs
  - Use 05-Areas/People/ for: Internal stakeholders

### Leadership Roles

**Roles:** CEO, Founder, COO
**Additional Area:**
- `05-Areas/Team/` - Executive team and direct reports
  - Use for: 1:1 threads, development plans, delegation tracking
  - 04-Projects/ used for: Strategic initiatives, board work, fundraising

### Advisory Roles

**Roles:** Consultant, Coach, Fractional Roles, VC/PE
**Additional Area:**
- `05-Areas/Clients/` - Client portfolio (for consultants/coaches)
  - Use for: Client strategies, ongoing engagements, relationship notes
  - 04-Projects/ used for: Specific engagements, deliverables

## Summary by Additional Areas

**No additional areas (use universal structure only):**
- Product Manager, Product Operations, Fractional CPO
- Finance, CFO
- RevOps, BizOps, Product Operations, Data/Analytics
- Design
- People/HR, Legal, IT Support, CHRO, CLO, CIO, CISO

**05-Areas/Accounts/** (customer relationship management):
- Sales, Account Executive, CRO, RevOps (sales focus)
- Customer Success, Solutions Engineering, CCO

**05-Areas/Content/** (content strategy):
- Marketing, CMO

**05-Areas/Team/** (team management):
- CTO, Engineering Manager (technical leadership)
- CEO, Founder, COO (executive leadership)

**05-Areas/Clients/** (client portfolio):
- Consultant, Coach, Fractional Roles, VC/PE

## Onboarding Implementation

During onboarding (Step 6 in `.claude/flows/onboarding.md`):

1. Always create universal areas: `05-Areas/People/Internal/`, `05-Areas/People/External/`
2. Check role mapping above
3. Create role-specific area only if listed
4. Update CLAUDE.md folder structure section with created areas
5. Don't create empty subfolders within areas (create on-demand)

## Usage Patterns

### Areas vs. Projects

**Areas are ongoing responsibilities:**
- Customer accounts (sales/CS relationship tracking)
- Content strategy (marketing asset library)
- Team management (1:1 threads, development)
- Client portfolio (consulting relationships)

**Projects are time-bound initiatives:**
- Close a specific deal
- Launch a campaign
- Ship a feature
- Complete a migration
- Finish a client engagement

**Rule of thumb:** If it has an end date, it's a Project. If it's ongoing, it might be an Area.

## Role Intelligence

Even roles without additional areas benefit from role intelligence in `System/user-profile.yaml`:

```yaml
role: "Product Manager"
role_group: "product"

meeting_intelligence:
  extract_customer_intel: true
  extract_competitive_intel: true
  extract_decisions: true
  extract_stakeholder_dynamics: true
```

This makes commands like `/process-meetings` and `/daily-plan` adapt their behavior without needing complex folder structures.
