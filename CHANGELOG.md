# Changelog

This file tracks all changes and improvements to your Dex personal knowledge management system. Every time you enhance Dex - new features, workflow refinements, integrations, fixes - it gets documented here.

Use this changelog to:
- **Remember what you've built** - Look back at how your system evolved
- **Query your progress** - Ask Claude "What changed in the career system?" or "Show me changes from last week"
- **Track value delivered** - See the compound improvements to your PKM over time

Changes happen immediately in your local system - there are no "releases" since this is your personal workspace.

---

## How to Use This Changelog

**When making changes:**
1. Add your change under today's date `## [YYYY-MM-DD]` in the appropriate category
2. Create a new date section if one doesn't exist yet
3. Provide enough detail to refresh your memory later: what changed, why it changed, how it works

**Querying the changelog:**
- Ask Claude: "What changed in the career system?" or "Show me changes from last week"
- Search by date: Look for `## [YYYY-MM-DD]` headers
- Search by feature: Look for keywords in Added/Changed sections

**Categories:**
- **Added** - New features, commands, folders, capabilities
- **Changed** - Modifications to existing functionality, renames, behavior updates
- **Fixed** - Bug fixes and corrections
- **Removed** - Deprecated or deleted features

---

## [2026-01-29] - Folder Structure Cleanup

### Fixed
- **Duplicate folders removed**: Cleaned up `Inbox/` and `03-Resources/` duplicates left from refactoring
  - Removed legacy `Inbox/` folder (superseded by `00-Inbox/`)
  - Removed incorrect `03-Resources/` folder (conflicted with `03-Tasks/`, wrong PARA numbering)
  - Standardized on full numeric prefix structure: `00-Inbox/`, `01-Quarter_Goals/`, `02-Week_Priorities/`, `03-Tasks/`, `04-Projects/`, `05-Areas/`, `06-Resources/`, `07-Archives/`, `System/`
- **Documentation consistency**: Updated CLAUDE.md, onboarding flow, skills, and all system documentation to use `00-Inbox/` consistently
- **Verified no data loss**: Confirmed `00-Inbox/` contained active content, `06-Resources/` had all necessary files before deletion

---

## [2026-01-28] - Conversational Capture (Removed Inbox.md Pattern)

### Removed
- **`/capture` skill** - Unnecessary ceremony; just tell Claude things naturally
- **`00-Inbox/Inbox.md`** - Cargo-culted from traditional PKM; conversational capture is simpler
- **`00-Inbox/Archive.md`** - No longer needed

### Changed
- **Capture workflow** - Now purely conversational
  - Tell Claude things naturally: "Sarah worried about timeline but interested in Q2 pilot"
  - Claude suggests routing based on Week Priorities + Quarterly Goals in real-time
  - One conversation, instant filing - no intermediate files or batch processing
- **`/triage` skill** - Repositioned as cleanup tool, not primary workflow
  - Finds orphaned files in `00-Inbox/` (screenshots, PDFs, exports)
  - Extracts scattered `- [ ]` tasks from notes
  - Still uses strategic context (Week Priorities + Goals) for routing
  - No longer processes Inbox.md (doesn't exist)
- **Documentation** - Updated System Guide, Jobs to Be Done, README to reflect conversational pattern

### Philosophy Shift
The Inbox.md pattern made sense before AI assistants. With Claude as Chief of Staff, just have a conversation. The strategic routing intelligence (Week Priorities + Goals) works the same, but happens in real-time during natural dialogue instead of batch processing.

### README Restructured for Conversion

### Changed
- **README.md** - Major restructure focused on conversion and marketing (774 → 408 lines)
  - Moved "Eight Jobs" table immediately after setup instructions to become the conversion hook
  - Expanded to include Job 8: "Evolve Itself" (improvement backlog system)
  - Condensed key differentiator sections (Career: -47%, Task Sync: -41%, Planning: -30%, Feature Discovery: -70%)
  - Removed detailed reference content that belongs in system guides (skills table, PARA deep dive, MCP technical details, hooks reference, automation details)
  - Added Demo Mode section explaining `/dex-demo` commands for exploring with sample data
  - Added "Documentation" section with clear navigation to deep guides (System Guide, Jobs to Be Done, Technical Guide, Folder Structure)
  - Updated "What You Get" table to reflect 8 jobs, mention company pages, and fix skills count (25+ core skills)
  - Added background automation specifics (changelog monitoring every 6 hours, learning review prompts daily at 5pm)
- **Strategy** - README is now pure marketing/onboarding content with complete setup instructions; comprehensive documentation lives in vault guides

### Fixed
- Skills count corrected from "26 universal skills" to "25+ core skills" for accuracy
- Company pages/account intelligence now mentioned in feature list (was missing entirely)

---

## [2026-01-28] - Self-Learning System Enhancements

### Added
- **Automatic Inline Self-Learning** - System now runs self-learning checks automatically during session start and `/daily-plan` with smart throttling (no installation required!)
- **Background Anthropic Changelog Monitoring** - Automated script (`.scripts/check-anthropic-changelog.cjs`) checks for new Claude Code features with 6-hour interval throttling
- **Learning Review Prompts** - Daily automation (`.scripts/learning-review-prompt.sh`) checks for accumulated session learnings (5+ threshold) with daily throttling
- **Launch Agent Installation** - Optional optimization (`.scripts/install-learning-automation.sh`) for background execution instead of inline checks
- **Session Start Inline Checks** - Added inline execution of self-learning checks in `session-start.sh` with interval throttling (fallback when Launch Agents not installed)
- **Daily Plan Self-Learning Integration** - Added Step 3.6 to `/daily-plan` skill to run self-learning checks and surface alerts in context
- **Pattern Detection** - Weekly reviews now detect recurring mistakes and preferences (2+ occurrences) and suggest adding to pattern files
- **Learning File Integration** - Daily reviews prompt to categorize learnings into `Mistake_Patterns.md` or `Working_Preferences.md`
- **Onboarding Integration** - Added optional Launch Agent setup to Step 7 of onboarding flow (`.claude/flows/onboarding.md`)
- **Dex Technical Guide** - New comprehensive guide (`06-Resources/Dex_System/Dex_Technical_Guide.md`) explaining Dex architecture from first principles: why files vs databases, how MCP servers work, context management strategies, state syncing, planning hierarchy design, integrations, self-learning system, and Cursor/Claude Code constraints. Educational and grounded in actual implementation with code references.

### Fixed
- **`/dex-whats-new` State Tracking** - Skill now explicitly updates `claude-code-state.json` after checking changelog (was documented but not executed)
- **Session-End Hook Documentation** - Clarified that hook only logs timestamps, not extract learnings (which happens via `/daily-review`)
- **Learning Review Script** - Fixed arithmetic error in pending learning count calculation (`.scripts/learning-review-prompt.sh`)
- **Folder structure documentation** - Corrected all references to maintain consistent numbering: `00-Inbox/`, `01-Quarter_Goals/`, `02-Week_Priorities/`, `03-Tasks/`, `04-07` for PARA folders

### Changed
- **Self-Learning Architecture** - Changed from "requires Launch Agent installation" to "works automatically with optional Launch Agent optimization"
- **CLAUDE.md** - Updated "Background Self-Learning Automation" section to clarify automatic inline execution with optional Launch Agent optimization
- **`.claude/hooks/README.md`** - Updated Example 4 to reflect reality of session-end hook behavior
- **`.claude/reference/mcp-servers.md`** - Added "Background Automation" section explaining changelog monitoring and learning prompts
- **`.claude/skills/daily-plan/SKILL.md`** - Added Step 3.6 for self-learning checks and context gathering for alerts
- **`.claude/flows/onboarding.md`** - Added Background Learning as optional feature in Step 7

### Documentation
- All documentation now accurately reflects actual implementation (closed gaps between documented behavior and reality)
- Simplified language in `Dex_System_Guide.md` and `Dex_Jobs_to_Be_Done.md` to be less technical and more problem-first
- Added comprehensive coverage of Career Development System and Dex Improvement Backlog in user-facing docs

---

## [2026-01-28] - System ready for GitHub release

### Removed
- Voice Notes feature - removed `00-Inbox/Voice_Notes/` folder (streamlined to Ideas and Meetings only)

### Fixed
- Merged duplicate Inbox folders and removed legacy `Inbox/` structure

### Changed
- Cleaned up changelog for public release with clean slate for users to track their own improvements