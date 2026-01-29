# Role System Implementation Status

**Last Updated:** January 28, 2026

## ✅ Completed

### 1. Role Areas Mapping
**File:** `.claude/reference/role-areas-mapping.md`

- Defined which roles get additional areas beyond universal People/
- Sales/CS → `05-Areas/Accounts/`
- Marketing → `05-Areas/Content/`
- Leadership → `05-Areas/Team/`
- Advisory → `05-Areas/Clients/`
- Most roles use universal structure only

### 2. Role Intelligence Configuration
**File:** `.claude/reference/role-intelligence-config.md`

- Role group mappings for all 31 roles
- Meeting intelligence flags by role
- Implementation guidance for onboarding
- Usage examples for commands

### 3. Updated Role Files (Examples)
**Files:**
- `.claude/roles/_ROLE_TEMPLATE.md` - Updated to PARA structure
- `.claude/roles/product-manager.md` - Example with no additional areas
- `.claude/roles/sales.md` - Example with `05-Areas/Accounts/`
- `.claude/roles/finance.md` - Example with no additional areas
- `.claude/roles/ceo.md` - Example with `05-Areas/Team/`

### 4. Updated User Profile Schema
**File:** `System/user-profile.yaml`

Added:
- `role_group` field for command filtering
- Additional meeting intelligence flags:
  - `extract_stakeholder_dynamics`
  - `extract_budget_timeline`
  - `extract_technical_decisions`

### 5. Updated Onboarding Flow
**File:** `.claude/flows/onboarding.md`

- References role areas mapping
- Creates PARA structure
- Conditionally creates role-specific areas
- Populates role_group and meeting_intelligence in user-profile

### 6. Design Documents
**Files:**
- `.claude/reference/role-intelligence-system.md` - Original comprehensive design (archived as reference)
- `.claude/reference/role-commands.md` - Catalog of role-specific commands to build

---

## 🚧 Still To Do

### Phase 1: Complete Role File Migration (High Priority)

Migrate remaining 26 role files to PARA structure:

**Customer-Facing:**
- [ ] customer-success.md
- [ ] solutions-engineering.md
- [ ] cco.md

**Operations:**
- [ ] product-operations.md
- [ ] revops.md
- [ ] data-analytics.md

**Engineering:**
- [ ] engineering.md
- [ ] cto.md

**Marketing:**
- [ ] marketing.md
- [ ] cmo.md

**Design:**
- [ ] design.md

**Support Functions:**
- [ ] people.md (HR)
- [ ] legal.md
- [ ] it-support.md
- [ ] chro.md
- [ ] clo.md
- [ ] cio.md
- [ ] ciso.md

**Leadership:**
- [ ] founder.md
- [ ] cfo.md
- [ ] coo.md
- [ ] cro.md
- [ ] cpo.md

**Advisory:**
- [ ] fractional-cpo.md
- [ ] consultant.md
- [ ] coach.md
- [ ] venture-capital.md

### Phase 2: Update Commands for Role Awareness (Medium Priority)

Update existing universal commands to check role_group and adapt:

**High-value adaptations:**
- [ ] `/daily-plan` - Ask role-specific questions
- [ ] `/meeting-prep` - Surface role-relevant context
- [ ] `/process-meetings` - Extract based on meeting_intelligence flags
- [ ] `/triage` - Suggest role-appropriate actions

**Implementation approach:**
Each command checks `System/user-profile.yaml`:
```python
profile = read_user_profile()
if profile.role_group == "sales":
    # Sales-specific behavior
elif profile.role_group == "product":
    # Product-specific behavior
```

### Phase 3: Build Role-Specific Commands (Lower Priority)

Create new commands that are valuable for specific role groups.

**Start with highest-impact commands:**

**Product commands (`.claude/commands/product/`):**
- [ ] `/roadmap` - Review roadmap, surface blockers
- [ ] `/customer-intel` - Synthesize customer feedback
- [ ] `/feature-decision` - Prioritization framework

**Sales commands (`.claude/commands/sales/`):**
- [ ] `/deal-review` - Review active deals, flag risks
- [ ] `/pipeline-health` - Analyze pipeline coverage
- [ ] `/call-prep` - Prepare for calls with full context

**Marketing commands (`.claude/commands/marketing/`):**
- [ ] `/content-calendar` - Review upcoming content
- [ ] `/campaign-review` - Campaign post-mortem
- [ ] `/audience-intel` - Synthesize audience insights

**Finance commands (`.claude/commands/finance/`):**
- [ ] `/close-status` - Month-end close checklist
- [ ] `/variance-analysis` - Budget vs actual analysis
- [ ] `/board-prep` - Compile board materials

**Full list in:** `.claude/reference/role-commands.md`

### Phase 4: Testing (Ongoing)

For each role:
- [ ] Test onboarding creates correct structure
- [ ] Verify role_group and meeting_intelligence set correctly
- [ ] Test adapted command behavior
- [ ] Validate role-specific commands (when built)

---

## Implementation Priority

### Immediate (This Week)
1. ✅ Complete design and documentation
2. Migrate remaining 26 role files to PARA
3. Test onboarding flow with 3-4 different roles

### Short-term (Next 2 Weeks)
4. Update 4 universal commands for role awareness
5. Build top 3 commands for Product, Sales, Marketing roles
6. Documentation and testing

### Medium-term (Next Month)
7. Build remaining role-specific commands
8. Advanced role intelligence features (if needed)
9. Comprehensive testing across all roles

---

## Success Metrics

**User-facing:**
- Commands feel tailored to role (ask relevant questions, surface right context)
- Folder structure is clean and understandable
- Meeting processing extracts role-relevant information

**Development:**
- One system, not 31 custom implementations
- Easy to add new roles (just create role file)
- Commands check role, don't need per-role variants

**Demo:**
- Can show same system adapting to different roles
- Demonstrates AI intelligence, not just folder organization
- Clear differentiation between role behaviors

---

## Migration Notes

### For Existing Vaults

If user already has complex folder structure from old system:
1. Don't delete existing folders
2. Add role_group and meeting_intelligence to user-profile.yaml
3. Commands start using new role-aware behavior
4. User can gradually migrate to simpler PARA structure

### For New Onboarding

Fresh installs get:
1. Clean PARA structure
2. Only role-specific areas that provide value
3. Role intelligence in user-profile from day one
4. Commands adapt automatically

---

## Questions / Decisions Needed

1. **Command organization:** Keep role-specific commands in `.claude/commands/[role-group]/` or flatten to `.claude/commands/`?
   - Recommendation: Keep in role-group folders for organization

2. **Role command discovery:** Show role-specific commands in autocomplete automatically or require explicit enablement?
   - Recommendation: Show automatically based on role_group

3. **Migration timeline:** Aggressive (all roles in 1 week) or gradual (prioritize by usage)?
   - Recommendation: Migrate high-usage roles first (PM, Sales, Marketing, Engineering, CS)

4. **Testing strategy:** Test each role manually or build automated validation?
   - Recommendation: Manual testing for high-priority roles, automated checks for structure

---

## Next Steps

1. **Review this status doc** - Confirm approach and priorities
2. **Migrate remaining role files** - Start with high-usage roles
3. **Test onboarding** - Pick 3 roles, run through onboarding, verify structure
4. **Update one command** - `/process-meetings` as proof of concept for role awareness
5. **Build one role-specific command** - `/customer-intel` for Product as example
6. **Iterate based on feedback**
