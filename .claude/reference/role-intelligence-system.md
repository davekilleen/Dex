# Role Intelligence System Design

**Last Updated:** January 28, 2026

## Implementation Status

**✅ Completed:** Role-specific skills (27 skills across 9 role groups) are implemented and available through opt-in discovery via `/dex-level-up`. Users can see which skills apply to their role and choose which to install.

**✅ Completed:** Universal skills adapt behavior based on role context in `System/user-profile.yaml`.

## Overview

Instead of creating complex role-specific folder structures that don't get used, we make the AI **role-aware** through rich context stored in the user profile. This makes every command smarter without adding organizational complexity.

---

## Design Philosophy

**Make the AI smarter, not the folder structure more complex.**

Everyone gets the same simple structure (04-Projects/, Relationships/, Content/), but rich role context in `System/user-profile.yaml` teaches the AI how to adapt. Commands change behavior based on role, extracting relevant information and making appropriate suggestions.

---

## Architecture

### 1. Role Definition Files

**Location:** `.claude/roles/[role].md`

Each role file contains:

```markdown
## Role Context
- Focus areas (what they care about)
- Meeting intelligence (what to extract)
- Project types (what "projects" mean for this role)
- Content patterns (what they create)

## Role Intelligence Settings
```yaml config block for user-profile.yaml```

## User-Facing Content
- Why Dex? pitch
- Quick start guide
- Example notes
- Templates
- Role-specific commands
```

**See:** `.claude/roles/_ROLE_TEMPLATE.md` for complete structure
**Example:** `.claude/roles/product-manager-v2.md` for fully implemented example

### 2. User Profile

**Location:** `System/user-profile.yaml`

During onboarding, we:
1. Read the role definition file
2. Populate `role_context` section with intelligence from the role file
3. Set `role_group` for command grouping
4. Configure `meeting_intelligence` extraction settings

```yaml
role: "Product Manager"
role_group: "product"

role_context:
  focus_areas:
    - Product strategy and roadmap prioritization
    - Stakeholder alignment
    - Customer insight synthesis
  
  meeting_intelligence:
    key_extractions:
      - Product decisions and rationale
      - Customer pain points
      - Stakeholder concerns
    questions_to_surface:
      - What customer problem does this solve?
      - What's the engineering effort vs. impact?
  
  project_types:
    - name: "Product Initiative"
      description: "Time-bound feature or improvement"
      triggers: ["roadmap work", "feature planning"]
    - name: "Customer Research"
      description: "Discovery or validation work"
      triggers: ["customer interviews", "research"]

meeting_intelligence:
  extract_customer_intel: true
  extract_competitive_intel: true
  extract_decisions: true
  extract_stakeholder_dynamics: true
```

### 3. CLAUDE.md Updates

Add a section that tells me to check the user profile:

```markdown
## Role-Aware Intelligence

I adapt my behavior based on your role. Check `System/user-profile.yaml` for:
- Focus areas that matter to you
- What to extract from meetings
- Types of projects you work on
- Questions to ask to be helpful

When processing meetings, triaging content, or planning your day, I reference your role context to provide relevant suggestions.
```

### 4. Command Adaptations

Commands check role context and adapt:

#### Universal Commands (with role awareness)

**`/daily-plan`:**
- PM: "Any customer feedback to review? Roadmap items blocked?"
- Sales: "Deal reviews today? Any at-risk accounts need attention?"
- Finance: "Close cycle status? Any variance explanations needed?"

**`/meeting-prep [person]`:**
- PM: Surfaces product decisions, feature discussions, stakeholder concerns
- Sales: Surfaces deal status, stakeholder map, competitive intel
- Finance: Surfaces commitments, deadlines, variance context

**`/process-meetings`:**
- PM: Extracts decisions, customer intel, stakeholder dynamics
- Sales: Extracts stakeholder map, BANT qualification, competitive mentions
- Finance: Extracts commitments, close blockers, variance explanations

**`/triage`:**
- PM: "Want to create a project for this feature? Log this customer feedback?"
- Sales: "Create a deal page? Update stakeholder map?"
- Finance: "Add to close checklist? Flag for board prep?"

#### Role-Specific Commands

**Location:** `.claude/commands/[role-group]/`

Commands available only to specific role groups:
- `product/roadmap.md`
- `product/customer-intel.md`
- `sales/deal-review.md`
- `sales/pipeline-health.md`
- `finance/close-status.md`
- `marketing/content-calendar.md`

**See:** `.claude/reference/role-commands.md` for complete list

### 5. Command Discovery

When user types `/` in Cursor, they see:
1. **Universal commands** (everyone)
2. **Role-specific commands** (based on their role_group)
3. Commands sorted by relevance to current context

---

## Benefits

### For Users

1. **Smarter AI:** I understand their role and adapt automatically
2. **Simpler structure:** Three folders instead of 10+, easier to navigate
3. **Better suggestions:** Role-aware recommendations that actually make sense
4. **Less manual work:** I route content intelligently without being told

### For Development

1. **Maintainable:** One system, not 31 custom implementations
2. **Extensible:** New roles just need role definition file
3. **Testable:** Role context is data, can validate it
4. **Scalable:** Commands check role, don't need per-role variants

### For Demo

1. **More impressive:** "Watch how it adapts based on your role"
2. **Shows intelligence:** Not just folders, actual smart behavior
3. **Clear differentiation:** "Here's how it works for sales vs. product"

---

## Examples

### Example 1: Sales Person Processes Meeting

**Meeting:** Discovery call with Acme Corp

**How it works:**
1. Meeting note goes to `00-Inbox/Meetings/`
2. I read it, check user's role_context
3. I see they're Sales, so I extract:
   - Stakeholder map (Jennifer = champion, Marcus = tech evaluator)
   - BANT qualification info
   - Competitive mentions
   - Next steps
4. I suggest: "Want me to create a deal page in 04-Projects/Acme_Corp.md?"
5. If yes, I create it with stakeholder map, qualification, next steps
6. I update person pages for Jennifer and Marcus
7. Future `/meeting-prep Jennifer` surfaces this context automatically

### Example 2: PM Logs Customer Feedback

**Input:** "Just talked to Sarah at Acme. She's frustrated with our reporting - takes 2 days/month to compile data manually. They want real-time dashboards."

**How it works:**
1. I check role_context, see "Customer insight synthesis" is a focus area
2. I suggest: "Want me to log this as customer feedback and check for patterns?"
3. If yes, I:
   - Create/update note in `00-Inbox/Customer_Feedback/2026-01-28-Reporting_Pain.md`
   - Link to Sarah's person page
   - Search for similar feedback ("real-time" OR "reporting" in past meetings)
   - Surface: "3 other customers mentioned reporting pain this month"
4. I suggest: "Seeing a pattern here. Want to create a project to explore this?"

### Example 3: Finance Person Before Board Meeting

**Command:** `/board-prep`

**How it works:**
1. I check role_context, see "Board preparation" is a key workflow
2. I search vault for:
   - Recent variance analyses (from role context: this is important for finance)
   - Major decisions made this month
   - Risk flags or blockers mentioned
   - Commitments made to board last time
3. I compile:
   - Financial narrative (variance explanations with context)
   - Decision log (major moves)
   - Open items (what we said we'd do vs. what got done)
   - Risk flags (things board should know)
4. Output: Draft board materials with all context linked

---

## Role Groups

Roles are grouped for command applicability:

- **product:** PM, CPO, Product Ops, Fractional CPO
- **sales:** Sales, AE, CRO, RevOps
- **marketing:** Marketing, CMO
- **finance:** Finance, CFO
- **engineering:** Engineering, CTO
- **customer_success:** Customer Success, CCO, Solutions Engineering
- **operations:** Product Ops, RevOps, BizOps, Data/Analytics
- **leadership:** CEO, Founder, C-suite roles
- **design:** Design
- **support:** People/HR, Legal, IT Support, CHRO, CLO, CIO, CISO
- **advisory:** Consultant, Coach, VC/PE

---

## Testing Strategy

### Test Cases

For each role:
1. **Onboarding:** Does it populate user-profile correctly?
2. **Meeting processing:** Does it extract role-relevant info?
3. **Suggestions:** Does `/triage` suggest appropriate actions?
4. **Command adaptation:** Does `/daily-plan` ask relevant questions?
5. **Templates:** Are role-specific templates created?

### Validation

```yaml
# test/role-validation.yaml
test_role: "Product Manager"
expected_role_group: "product"
expected_extractions:
  - "Product decisions"
  - "Customer pain points"
expected_commands:
  - "/roadmap"
  - "/customer-intel"
expected_focus_areas:
  - "Product strategy"
```

Run validation against each role definition file to ensure consistency.

