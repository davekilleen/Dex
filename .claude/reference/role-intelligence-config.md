# Role Intelligence Configuration

How to populate `System/user-profile.yaml` during onboarding based on role.

## Role Groups

Map roles to groups for command filtering:

```yaml
# Product roles
Product Manager → product
CPO → product
Product Operations → product
Fractional CPO → product

# Sales & Revenue roles
Sales / Account Executive → sales
CRO → sales
RevOps → revenue_ops

# Marketing roles
Marketing → marketing
CMO → marketing

# Engineering roles
Engineering → engineering
CTO → engineering

# Customer-facing roles
Customer Success → customer_success
Solutions Engineering → customer_success
CCO → customer_success

# Finance roles
Finance → finance
CFO → finance

# Operations roles
Product Operations → operations
RevOps → operations
BizOps → operations
Data / Analytics → operations

# Design roles
Design → design

# Leadership roles
CEO → leadership
Founder → leadership
COO → leadership

# Support functions
People (HR) → support
Legal → support
IT Support → support
CHRO → support
CLO → support
CIO → support
CISO → support

# Advisory roles
Consultant → advisory
Coach → advisory
Fractional CPO → advisory
Venture Capital / Private Equity → advisory
```

## Meeting Intelligence Flags

Set these based on role to control what gets extracted from meetings:

```yaml
meeting_intelligence:
  extract_customer_intel: bool       # Customer pain points, feedback
  extract_competitive_intel: bool    # Competitive mentions
  extract_action_items: true         # Always true
  extract_decisions: true            # Always true
  extract_stakeholder_dynamics: bool # Stakeholder relationships, influence
  extract_budget_timeline: bool      # Budget, authority, need, timeline (BANT)
  extract_technical_decisions: bool  # Technical decisions and tradeoffs
```

### By Role

**Product Roles (PM, CPO, Product Ops):**
```yaml
extract_customer_intel: true
extract_competitive_intel: true
extract_stakeholder_dynamics: true
extract_budget_timeline: false
extract_technical_decisions: false
```

**Sales & Revenue (Sales, CRO, RevOps):**
```yaml
extract_customer_intel: true
extract_competitive_intel: true
extract_stakeholder_dynamics: true
extract_budget_timeline: true
extract_technical_decisions: false
```

**Customer Success (CS, Solutions Eng, CCO):**
```yaml
extract_customer_intel: true
extract_competitive_intel: true
extract_stakeholder_dynamics: true
extract_budget_timeline: false
extract_technical_decisions: false
```

**Engineering (Eng, CTO):**
```yaml
extract_customer_intel: false
extract_competitive_intel: false
extract_stakeholder_dynamics: false
extract_budget_timeline: false
extract_technical_decisions: true
```

**Marketing (Marketing, CMO):**
```yaml
extract_customer_intel: true
extract_competitive_intel: true
extract_stakeholder_dynamics: false
extract_budget_timeline: false
extract_technical_decisions: false
```

**Finance (Finance, CFO):**
```yaml
extract_customer_intel: false
extract_competitive_intel: false
extract_stakeholder_dynamics: false
extract_budget_timeline: false
extract_technical_decisions: false
```

**Leadership (CEO, Founder, COO):**
```yaml
extract_customer_intel: true
extract_competitive_intel: true
extract_stakeholder_dynamics: true
extract_budget_timeline: false
extract_technical_decisions: false
```

**Design:**
```yaml
extract_customer_intel: true
extract_competitive_intel: false
extract_stakeholder_dynamics: false
extract_budget_timeline: false
extract_technical_decisions: false
```

**Operations (Product Ops, RevOps, BizOps, Data):**
```yaml
extract_customer_intel: false
extract_competitive_intel: false
extract_stakeholder_dynamics: false
extract_budget_timeline: false
extract_technical_decisions: false
```

**Support Functions (HR, Legal, IT):**
```yaml
extract_customer_intel: false
extract_competitive_intel: false
extract_stakeholder_dynamics: false
extract_budget_timeline: false
extract_technical_decisions: false
```

**Advisory (Consultant, Coach, VC/PE):**
```yaml
extract_customer_intel: true
extract_competitive_intel: false
extract_stakeholder_dynamics: true
extract_budget_timeline: false
extract_technical_decisions: false
```

## Implementation in Onboarding

During Step 6 (Generate Structure):

```python
# Pseudocode for onboarding
role = user_selected_role  # e.g., "Product Manager"

# 1. Map to role group
role_group = map_role_to_group(role)  # → "product"

# 2. Determine meeting intelligence flags
intel_flags = get_meeting_intelligence_for_role(role)

# 3. Check if additional areas needed
additional_areas = check_role_areas_mapping(role)  # → [] for PM, ["Accounts"] for Sales

# 4. Create folders
create_universal_para_structure()
for area in additional_areas:
    create_area_folder(area)

# 5. Update user-profile.yaml
update_user_profile(
    role=role,
    role_group=role_group,
    meeting_intelligence=intel_flags
)
```

## Usage in Commands

Commands check role group and intelligence flags:

### `/process-meetings`

```python
# Check what to extract
profile = read_user_profile()
if profile.meeting_intelligence.extract_customer_intel:
    extract_customer_pain_points(meeting)
if profile.meeting_intelligence.extract_stakeholder_dynamics:
    extract_stakeholder_map(meeting)
# ... etc
```

### `/daily-plan`

```python
# Adapt questions based on role
profile = read_user_profile()
if profile.role_group == "sales":
    ask("Any deal reviews today? At-risk accounts need attention?")
elif profile.role_group == "product":
    ask("Any customer feedback to review? Roadmap items blocked?")
elif profile.role_group == "finance":
    ask("Close cycle status? Any variance explanations needed?")
```

### Role-Specific Commands

Commands can check role_group to determine availability:

```python
# /deal-review command
if user.role_group not in ["sales", "revenue_ops"]:
    suggest_alternative_command()
```

## Future: Role Context Section

In future iterations, we can add a `role_context` section to user-profile.yaml with richer intelligence:

```yaml
role_context:
  focus_areas:
    - Product strategy and roadmap
    - Customer insight synthesis
    - Stakeholder alignment
  
  project_types:
    - name: "Product Initiative"
      description: "Time-bound feature development"
      triggers: ["roadmap", "feature", "launch"]
  
  questions_to_ask:
    - "What customer problem does this solve?"
    - "What's the engineering effort vs. impact?"
```

For now, keep it simple with just role_group and meeting_intelligence flags.
