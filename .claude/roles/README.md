# Roles

**Purpose:** Role-specific configurations that adapt Dex's behavior and structure for different professional contexts.

---

## What Are Roles?

**Roles** customize Dex for your specific job. Tell Dex you're a CMO, and you get content pipelines and marketing folders. Say you're a Sales VP, and you get deal tracking and account management. Instead of starting with generic folders, your structure is ready from day one.

### Why Roles Matter

Different jobs need different structures. Compare:

| Aspect | Product Manager | Sales VP | Engineering Manager |
|--------|----------------|----------|---------------------|
| **Key entities** | Features, customers, roadmap | Deals, accounts, pipeline | Projects, PRs, sprints |
| **Folder structure** | `Features/`, `Customer_Feedback/` | `Deals/`, `Accounts/` | `04-Projects/`, `Technical_Debt/` |
| **Terminology** | "Sprint goals", "roadmap" | "Pipeline", "quota" | "Sprint", "velocity" |
| **Main workflows** | Product briefs, customer research | Deal tracking, forecasting | Sprint planning, 1:1s |

Without roles, you'd start with generic folders and rename everything. With roles, your structure is ready from day one.

### How Roles Work

**During onboarding:**
1. Dex asks: "What's your role?"
2. You select from 31+ options (PM, CMO, Engineer, etc.)
3. Dex configures:
   - Folder structure in `Active/`
   - Strategic pillars in `System/pillars.yaml`
   - Relevant skills and templates
   - Example data appropriate for your role

**After setup:**
- Your role is stored in `System/user-profile.yaml`
- Commands adapt language to your context
- Skills surface role-appropriate workflows
- You can change your role anytime by running `/setup` again

### Role-Specific Customization

Each role defines:

**Folder Structure:**
```yaml
folders:
  - Features         # What work gets organized into
  - Customers        # Who you track
  - Content          # What you create
```

**Strategic Pillars:**
```yaml
pillars:
  - Product Quality
  - Customer Satisfaction
  - Go-to-Market
```

**Terminology:**
- CEO: "Strategic initiatives", "Board meetings"
- Engineer: "Pull requests", "Technical debt"
- Sales: "Pipeline", "Deals"

**Relevant Features:**
- PM: Product briefs, roadmap planning
- Sales: Deal tracking, account management
- CEO: Executive summaries, board prep

---

## What Goes Here

Role definition files (`.md` format) that:
- Define role-specific folder structures
- Customize language and terminology
- Configure relevant features and workflows
- Tailor example data and templates

## When to Use

Create a role when:
- **Different context** - Job function has unique needs (CEO vs IC engineer)
- **Custom structure** - Folder organization differs from default
- **Domain language** - Terminology varies by role (OKRs vs sprint goals)
- **Feature set** - Some features more relevant than others

## Structure

Role files define:
- **Folder structure** - What Active/ subfolders to create
- **Terminology** - Role-appropriate language (initiatives vs projects)
- **Features** - Which workflows are most relevant
- **Examples** - Sample data and use cases

## Examples

- **ceo.md** - Leadership role (strategic initiatives, exec team, board)
- **engineering.md** - IC engineer (projects, PRs, sprint goals)
- **customer-success.md** - CS manager (accounts, health scores, renewals)
- **product-manager-v2.md** - PM role (features, roadmap, customer feedback)

## Usage

Roles are:
- Selected during onboarding (`.claude/flows/onboarding.md`)
- Stored in user profile (`System/user-profile.yaml`)
- Referenced throughout skills and agents
- Can be changed later

## Related

- **Onboarding** (`.claude/flows/onboarding.md`) - Role selection flow
- **User Profile** (`System/user-profile.yaml`) - Active role configuration
- **Templates** (`System/Templates/`) - Role-specific note templates
