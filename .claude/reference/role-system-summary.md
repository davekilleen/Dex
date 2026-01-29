# Role System Redesign - Summary

## The Problem We Solved

**Original issue:** Creating elaborate folder structures per role that looked good in demos but didn't actually work because:
- No routing logic to get content into those folders
- Commands didn't know about role-specific folders
- Empty folders created illusion of organization without function

## The Solution

**Make the AI role-aware instead of making folders role-specific.**

### Everyone Gets Simple Structure

```
Active/
├── 04-Projects/      # Universal - works for all roles
├── Relationships/ # Universal - works for all roles
└── Content/       # Universal - works for all roles
```

### Intelligence Lives in Role Context

`System/user-profile.yaml` stores rich context about:
- What the user cares about (focus areas)
- What to extract from meetings (role-specific intel)
- What "projects" mean for their role
- What questions to ask to be helpful

### Commands Adapt to Role

- `/daily-plan` asks different questions for sales vs. product
- `/meeting-prep` surfaces different context per role
- `/process-meetings` extracts role-relevant information
- `/triage` suggests role-appropriate actions

### Role-Specific Commands

New commands for specific role groups:
- **Product:** `/roadmap`, `/customer-intel`, `/feature-decision`
- **Sales:** `/deal-review`, `/pipeline-health`, `/call-prep`, `/account-plan`
- **Marketing:** `/content-calendar`, `/campaign-review`, `/messaging-audit`
- **Finance:** `/close-status`, `/variance-analysis`, `/board-prep`
- **Engineering:** `/tech-debt`, `/incident-review`, `/architecture-decision`
- **Leadership:** `/weekly-reflection`, `/decision-log`, `/delegate-check`
- And more...

---

## What I Created

### 1. Role Template
**File:** `.claude/roles/_ROLE_TEMPLATE.md`

Standard structure for all role definitions. Includes:
- Role context (intelligence profile)
- User-facing content (why Dex, quick start)
- Templates and workflows
- Size variants

### 2. Role Commands Reference
**File:** `.claude/reference/role-commands.md`

Complete catalog of role-specific commands by role group. Shows:
- What each command does
- What it outputs
- Which roles benefit most

### 3. Example Role (Product Manager)
**File:** `.claude/roles/product-manager-v2.md`

Fully implemented example showing how the new system works. Demonstrates:
- Rich role context
- Meeting intelligence settings
- Role-specific commands
- How AI adapts behavior

### 4. User Profile Template
**File:** `System/user-profile-template.yaml`

New schema supporting role intelligence:
- `role_context` section populated from role definition
- `role_group` for command grouping
- `meeting_intelligence` extraction settings
- Working style and pillars

### 5. Design Document
**File:** `.claude/reference/role-intelligence-system.md`

Complete system design including:
- Architecture
- Implementation plan (4 weeks)
- Benefits for users, development, demos
- Migration strategy
- Testing approach
- Concrete examples

---

## Key Benefits

### More Impressive Demos

**OLD:** "Here are folders for your role"
**NEW:** "Watch how it understands your role and adapts"

Examples:
- Show sales person → extracts stakeholder dynamics automatically
- Show PM → surfaces customer patterns from meetings
- Show finance person → prepares board materials intelligently

### Actually Works

**OLD:** Empty folders that don't get used
**NEW:** Smart AI behavior that provides value immediately

The intelligence is in how I work with them, not in folder organization.

### Maintainable

**OLD:** 31 custom folder structures to maintain
**NEW:** One system with 31 data files

Adding a new role = create one role definition file. Everything else just works.

---

## Implementation Phases

### Phase 1: Foundation (Week 1)
- ✅ Role template created
- ✅ User profile schema designed
- ✅ Role commands documented
- Create role intelligence parser
- Update onboarding flow

### Phase 2: Role Migration (Week 2)
- Migrate all 31 roles to new format
- Define role group mappings
- Create templates for each role

### Phase 3: Command Updates (Week 3)
- Update universal commands to be role-aware
- Commands check `role_context` and adapt

### Phase 4: Role-Specific Commands (Week 4)
- Implement top commands per role group
- Add command discovery
- Testing and docs

---

## Decision Log

### Decisions Made

1. **Simplified folder structure** - Three folders for everyone instead of role-specific nesting
2. **Role intelligence in config** - YAML stores role context, not folder structure
3. **Command adaptation** - Universal commands adapt vs. creating role-specific variants
4. **Role groups** - Group similar roles to share commands
5. **Meeting intelligence** - Role-specific extraction settings control what we pull from meetings

### Alternatives Considered

**Option A: Create elaborate folders + build routing**
- Rejected: Too much maintenance, 31 custom implementations

**Option B: No role awareness at all**
- Rejected: Misses opportunity to be genuinely more helpful

**Option C (chosen): Role-aware AI + simple structure**
- Balances sophistication with maintainability

---

## Next Steps

### For Implementation

1. Review and approve this design
2. Create role intelligence parser (reads role files → populates user-profile)
3. Pick one role (PM) as reference implementation
4. Test end-to-end with demo user
5. Iterate based on feedback
6. Roll out to all roles

### For Existing Roles

We need to migrate 31 role files. Prioritize by usage:
1. Product Manager, Sales, Marketing (most common)
2. Engineering, Customer Success (common)
3. Finance, Operations (medium)
4. C-suite, Advisory (less common)

---

## Questions for Review

1. **Folder structure:** Approve simple three-folder approach for all roles?
2. **Command priority:** Which role-specific commands are most critical to build first?
3. **Migration timing:** Aggressive 4-week timeline or more gradual?
4. **Demo strategy:** Which roles to showcase in initial demo videos?

---

## Files Created

- `.claude/roles/_ROLE_TEMPLATE.md` - Standard role definition structure
- `.claude/roles/product-manager-v2.md` - Example fully implemented role
- `.claude/reference/role-commands.md` - Complete command catalog
- `.claude/reference/role-intelligence-system.md` - Full system design
- `System/user-profile-template.yaml` - Updated profile schema
- `.claude/reference/role-system-summary.md` - This document

Ready to proceed with implementation when you approve.
