<!-- GENERATED FILE — DO NOT EDIT BY HAND. -->
<!-- Generator: scripts/generate-architecture-inventory.py -->
<!-- Content SHA-256: dec7170bf1b86c67fd0fdfb2afcc9610cd2d6674728718f268d808b6d9da9307 -->

# Architecture Inventory

This inventory is derived only from repository code and shipped skill files.

## MCP engines

**Engine count:** 9

| Server | Source | Tool count | `feature_status` honesty contract | Exposed tools |
| --- | --- | ---: | :---: | --- |
| `dex-analytics` | `core/mcp/analytics_server.py` | 4 | yes | `check_analytics_status`, `identify_user`, `test_connection`, `track_event` |
| `dex-calendar-mcp` | `core/mcp/calendar_server.py` | 15 | yes | `calendar_create_event`, `calendar_delete_event`, `calendar_get_events`, `calendar_get_events_with_attendees`, `calendar_get_next_event`, `calendar_get_today`, `calendar_list_calendars`, `calendar_search_events`, `reminders_clear_completed`, `reminders_complete_item`, `reminders_create_item`, `reminders_ensure_lists`, `reminders_find_and_complete`, `reminders_list_completed`, `reminders_list_items` |
| `dex-career-mcp` | `core/mcp/career_server.py` | 8 | yes | `analyze_coverage`, `generate_evidence_from_work`, `parse_ladder`, `promotion_readiness_score`, `scan_evidence`, `scan_work_for_evidence`, `skills_gap_analysis`, `timeline_analysis` |
| `dex-granola-mcp` | `core/mcp/granola_server.py` | 6 | yes | `granola_check_available`, `granola_get_extent`, `granola_get_meeting_details`, `granola_get_recent_meetings`, `granola_get_today_meetings`, `granola_search_meetings` |
| `dex-improvements-mcp` | `core/mcp/dex_improvements_server.py` | 9 | no | `capture_idea`, `enrich_idea`, `get_backlog_stats`, `get_idea_details`, `list_ideas`, `mark_implemented`, `synthesize_changelog`, `synthesize_learnings`, `validate_backlog` |
| `dex-onboarding-mcp` | `core/mcp/onboarding_server.py` | 8 | no | `check_onboarding_complete`, `cleanup_qa_session`, `finalize_onboarding`, `get_onboarding_status`, `save_calendar_selection`, `start_onboarding_session`, `validate_and_save_step`, `verify_dependencies` |
| `dex-resume-mcp` | `core/mcp/resume_server.py` | 12 | yes | `add_role`, `compile_resume`, `export_resume`, `extract_achievements`, `generate_linkedin`, `generate_role_writeup`, `list_sessions`, `load_session`, `pull_career_evidence`, `save_session`, `start_session`, `validate_metrics` |
| `dex-session-memory` | `core/mcp/session_memory_server.py` | 8 | no | `get_entity_timeline`, `get_observation_timeline`, `get_recent_decisions`, `get_recent_tool_usage`, `get_session_context`, `get_session_summary`, `search_observations`, `search_sessions` |
| `dex-work-mcp` | `core/mcp/work_server.py` | 43 | yes | `analyze_calendar_capacity`, `build_company_index`, `build_people_index`, `capture_skill_rating`, `check_goal_alignment`, `check_priority_limits`, `classify_task_effort`, `complete_weekly_priority`, `confirm_goal_link`, `create_company`, `create_person`, `create_quarterly_goal`, `create_task`, `create_weekly_priority`, `get_blocked_tasks`, `get_commitments_due`, `get_goal_status`, `get_meeting_context`, `get_pillar_summary`, `get_quarter_velocity`, `get_quarterly_goals`, `get_skill_ratings`, `get_system_status`, `get_week_priorities`, `get_week_progress`, `get_weekly_planning_context`, `get_work_summary`, `list_companies`, `list_tasks`, `lookup_person`, `migrate_quarterly_goals`, `migrate_weekly_priorities`, `process_inbox_with_dedup`, `query_meeting_cache`, `rebuild_meeting_cache`, `record_external_task_mapping`, `refresh_company`, `suggest_focus`, `suggest_task_scheduling`, `sync_external_tasks`, `sync_task_refs`, `update_goal_progress`, `update_task_status` |

## Skills

**Skill count:** 68<br>
**Discoverability-risk count:** 53

A description has a trigger when its frontmatter contains the word `when` or `whenever` (case-insensitive). Length is measured in characters.

| Skill | Source | Description | Length | Trigger status |
| --- | --- | --- | ---: | --- |
| `anthropic-algorithmic-art` | `.claude/skills/anthropic-algorithmic-art/SKILL.md` | Creating algorithmic art using p5.js with seeded randomness and interactive parameter exploration. Use this when users request creating art using code, generative art, algorithmic art, flow fields, or particle systems. Create original algorithmic art rather than copying existing artists' work to avoid copyright violations. | 324 | when |
| `anthropic-brand-guidelines` | `.claude/skills/anthropic-brand-guidelines/SKILL.md` | Applies Anthropic's official brand colors and typography to any sort of artifact that may benefit from having Anthropic's look-and-feel. Use it when brand colors or style guidelines, visual formatting, or company design standards apply. | 236 | when |
| `anthropic-canvas-design` | `.claude/skills/anthropic-canvas-design/SKILL.md` | Create beautiful visual art in .png and .pdf documents using design philosophy. You should use this skill when the user asks to create a poster, piece of art, design, or other static piece. Create original visual designs, never copying existing artists' work to avoid copyright violations. | 289 | when |
| `anthropic-doc-coauthoring` | `.claude/skills/anthropic-doc-coauthoring/SKILL.md` | Guide users through a structured workflow for co-authoring documentation. Use when user wants to write documentation, proposals, technical specs, decision docs, or similar structured content. This workflow helps users efficiently transfer context, refine content through iteration, and verify the doc works for readers. Trigger when user mentions writing docs, creating proposals, drafting specs, or similar documentation tasks. | 428 | when |
| `anthropic-docx` | `.claude/skills/anthropic-docx/SKILL.md` | Comprehensive document creation, editing, and analysis with support for tracked changes, comments, formatting preservation, and text extraction. When Claude needs to work with professional documents (.docx files) for: (1) Creating new documents, (2) Modifying or editing content, (3) Working with tracked changes, (4) Adding comments, or any other document tasks | 362 | when |
| `anthropic-frontend-design` | `.claude/skills/anthropic-frontend-design/SKILL.md` | Create distinctive, production-grade frontend interfaces with high design quality. Use this skill when the user asks to build web components, pages, artifacts, posters, or applications (examples include websites, landing pages, dashboards, React components, HTML/CSS layouts, or when styling/beautifying any web UI). Generates creative, polished code and UI design that avoids generic AI aesthetics. | 399 | when |
| `anthropic-internal-comms` | `.claude/skills/anthropic-internal-comms/SKILL.md` | A set of resources to help me write all kinds of internal communications, using the formats that my company likes to use. Claude should use this skill whenever asked to write some sort of internal communications (status reports, leadership updates, 3P updates, company newsletters, FAQs, incident reports, project updates, etc.). | 329 | when |
| `anthropic-mcp-builder` | `.claude/skills/anthropic-mcp-builder/SKILL.md` | Guide for creating high-quality MCP (Model Context Protocol) servers that enable LLMs to interact with external services through well-designed tools. Use when building MCP servers to integrate external APIs or services, whether in Python (FastMCP) or Node/TypeScript (MCP SDK). | 277 | when |
| `anthropic-pdf` | `.claude/skills/anthropic-pdf/SKILL.md` | Comprehensive PDF manipulation toolkit for extracting text and tables, creating new PDFs, merging/splitting documents, and handling forms. When Claude needs to fill in a PDF form or programmatically process, generate, or analyze PDF documents at scale. | 252 | when |
| `anthropic-pptx` | `.claude/skills/anthropic-pptx/SKILL.md` | Presentation creation, editing, and analysis. When Claude needs to work with presentations (.pptx files) for: (1) Creating new presentations, (2) Modifying or editing content, (3) Working with layouts, (4) Adding comments or speaker notes, or any other presentation tasks | 271 | when |
| `anthropic-skill-creator` | `.claude/skills/anthropic-skill-creator/SKILL.md` | Guide for creating effective skills. This skill should be used when users want to create a new skill (or update an existing skill) that extends Claude's capabilities with specialized knowledge, workflows, or tool integrations. | 226 | when |
| `anthropic-slack-gif-creator` | `.claude/skills/anthropic-slack-gif-creator/SKILL.md` | Knowledge and utilities for creating animated GIFs optimized for Slack. Provides constraints, validation tools, and animation concepts. Use when users request animated GIFs for Slack like "make me a GIF of X doing Y for Slack." | 227 | when |
| `anthropic-theme-factory` | `.claude/skills/anthropic-theme-factory/SKILL.md` | Toolkit for styling artifacts with a theme. These artifacts can be slides, docs, reportings, HTML landing pages, etc. There are 10 pre-set themes with colors/fonts that you can apply to any artifact that has been creating, or can generate a new theme on-the-fly. | 262 | **discoverability-risk** |
| `anthropic-web-artifacts-builder` | `.claude/skills/anthropic-web-artifacts-builder/SKILL.md` | Suite of tools for creating elaborate, multi-component claude.ai HTML artifacts using modern frontend web technologies (React, Tailwind CSS, shadcn/ui). Use for complex artifacts requiring state management, routing, or shadcn/ui components - not for simple single-file HTML/JSX artifacts. | 288 | **discoverability-risk** |
| `anthropic-webapp-testing` | `.claude/skills/anthropic-webapp-testing/SKILL.md` | Toolkit for interacting with and testing local web applications using Playwright. Supports verifying frontend functionality, debugging UI behavior, capturing browser screenshots, and viewing browser logs. | 204 | **discoverability-risk** |
| `anthropic-xlsx` | `.claude/skills/anthropic-xlsx/SKILL.md` | Comprehensive spreadsheet creation, editing, and analysis with support for formulas, formatting, data analysis, and visualization. When Claude needs to work with spreadsheets (.xlsx, .xlsm, .csv, .tsv, etc) for: (1) Creating new spreadsheets with formulas and formatting, (2) Reading or analyzing data, (3) Modify existing spreadsheets while preserving formulas, (4) Data analysis and visualization in spreadsheets, or (5) Recalculating formulas | 445 | when |
| `atlassian-setup` | `.claude/skills/atlassian-setup/SKILL.md` | Connect Jira and Confluence to Dex for project tracking and knowledge search | 76 | **discoverability-risk** |
| `calendar-setup` | `.claude/skills/calendar-setup/SKILL.md` | Grant Python calendar access for 30x faster calendar queries (30s → <1s) | 72 | **discoverability-risk** |
| `create-mcp` | `.claude/skills/create-mcp/SKILL.md` | Create new MCP integration with guided wizard | 45 | **discoverability-risk** |
| `create-skill` | `.claude/skills/create-skill/SKILL.md` | Create a custom skill that's protected from Dex updates. Automatically appends -custom to ensure your skill is never overwritten. | 129 | **discoverability-risk** |
| `daily-plan` | `.claude/skills/daily-plan/SKILL.md` | Generate context-aware daily plan with calendar, tasks, and priorities. Includes midweek awareness, meeting intelligence, commitment tracking, and smart scheduling suggestions. | 176 | **discoverability-risk** |
| `daily-review` | `.claude/skills/daily-review/SKILL.md` | End of day review with learning capture, daily plan completion tracking, and meeting follow-up surfacing. | 105 | **discoverability-risk** |
| `decision-log` | `.claude/skills/decision-log/SKILL.md` | Capture an important decision with its context, options, rationale, and review date, then find it again when it matters. | 120 | when |
| `delegate-check` | `.claude/skills/delegate-check/SKILL.md` | Review open delegations — what you handed off, to whom, its status, and the next useful nudge. | 94 | **discoverability-risk** |
| `dex-add-mcp` | `.claude/skills/dex-add-mcp/SKILL.md` | Add an MCP server using Dex-safe scope (user by default) | 56 | **discoverability-risk** |
| `dex-backlog` | `.claude/skills/dex-backlog/SKILL.md` | AI-powered ranking of Dex system improvement ideas | 50 | **discoverability-risk** |
| `dex-doctor` | `.claude/skills/dex-doctor/SKILL.md` | Rigorous whole-system checkup — verifies every Dex feature honestly (working / off / broken / couldn't-check), self-heals what is provably safe, and guides the user only where Dex cannot fix itself. Replaces /health-check. | 222 | **discoverability-risk** |
| `dex-improve` | `.claude/skills/dex-improve/SKILL.md` | Workshop an improvement idea into implementation plan | 53 | **discoverability-risk** |
| `dex-level-up` | `.claude/skills/dex-level-up/SKILL.md` | Discover unused Dex features based on your usage patterns | 57 | **discoverability-risk** |
| `dex-obsidian-setup` | `.claude/skills/dex-obsidian-setup/SKILL.md` | Enable Obsidian integration and migrate existing vault to wiki links | 68 | **discoverability-risk** |
| `dex-rollback` | `.claude/skills/dex-rollback/SKILL.md` | Rewind one receipt-backed Dex adoption through the frozen lifecycle service | 75 | **discoverability-risk** |
| `dex-update` | `.claude/skills/dex-update/SKILL.md` | Preview and safely adopt Dex updates through the frozen lifecycle service | 73 | **discoverability-risk** |
| `dex-whats-new` | `.claude/skills/dex-whats-new/SKILL.md` | Check for system improvements (learnings + Claude updates) | 58 | **discoverability-risk** |
| `diff-adopt` | `.claude/skills/diff-adopt/SKILL.md` | Adopt a DexDiff methodology — guided onboarding that reads a workflow description, adapts it to your role and vault, and walks you through setup | 144 | **discoverability-risk** |
| `diff-adopt-profile` | `.claude/skills/diff-adopt-profile/SKILL.md` | Set me up like someone - adopt a full Heydex profile by handle (e.g. "set me up like Dave" means /diff-adopt-profile @davekilleen). Fetches the published profile bundle, saves the ordered workflows locally, and guides the user through installing the whole set into Dex | 268 | **discoverability-risk** |
| `diff-generate` | `.claude/skills/diff-generate/SKILL.md` | Generate a DexDiff methodology document from your vault customisations: package how you use Dex so others can replicate it | 122 | **discoverability-risk** |
| `diff-list` | `.claude/skills/diff-list/SKILL.md` | Show all adopted DexDiff workflows — what's installed, when it was adopted, and what it includes | 96 | when |
| `diff-profile` | `.claude/skills/diff-profile/SKILL.md` | Generate a full DexDiff profile — package your entire system so others can replicate how you use Dex | 100 | **discoverability-risk** |
| `diff-remove` | `.claude/skills/diff-remove/SKILL.md` | Remove a previously adopted DexDiff workflow — deletes generated skills and config, leaves your data untouched | 110 | **discoverability-risk** |
| `enable-semantic-search` | `.claude/skills/enable-semantic-search/SKILL.md` | Enable local AI-powered semantic search with smart collection discovery | 71 | **discoverability-risk** |
| `getting-started` | `.claude/skills/getting-started/SKILL.md` | Interactive post-onboarding tour with adaptive pathways based on available data | 79 | **discoverability-risk** |
| `google-workspace-setup` | `.claude/skills/google-workspace-setup/SKILL.md` | Connect Google Workspace (Gmail, Calendar, Docs) to Dex for email-aware planning and meeting prep | 97 | **discoverability-risk** |
| `granola-setup` | `.claude/skills/granola-setup/SKILL.md` | Connect Granola to Dex via Granola's official API for automatic meeting sync and transcripts | 92 | **discoverability-risk** |
| `identity-snapshot` | `.claude/skills/identity-snapshot/SKILL.md` | Generate a living identity model from existing Dex data — working patterns, decision tendencies, quality preferences, and growth areas. | 135 | **discoverability-risk** |
| `industry-truths` | `.claude/skills/industry-truths/SKILL.md` | Define time-horizoned assumptions about your industry/domain that ground strategic thinking and prevent building on quicksand | 125 | **discoverability-risk** |
| `integrate-mcp` | `.claude/skills/integrate-mcp/SKILL.md` | Integrate existing MCP servers from Smithery.ai or GitHub repositories | 70 | **discoverability-risk** |
| `journal` | `.claude/skills/journal/SKILL.md` | Toggle journaling or start a journal entry (morning/evening/weekly) | 67 | **discoverability-risk** |
| `manage-capabilities` | `.claude/skills/manage-capabilities/SKILL.md` | Turn optional Dex rooms on or off without deleting user content | 63 | **discoverability-risk** |
| `meeting-prep` | `.claude/skills/meeting-prep/SKILL.md` | Prepare for meetings by gathering attendee context and related topics | 69 | **discoverability-risk** |
| `ms-teams-setup` | `.claude/skills/ms-teams-setup/SKILL.md` | Connect Microsoft Teams to Dex for cross-channel context awareness | 66 | **discoverability-risk** |
| `process-meetings` | `.claude/skills/process-meetings/SKILL.md` | Process synced Granola meetings to update person pages, extract tasks, and organize meeting notes | 97 | **discoverability-risk** |
| `product-brief` | `.claude/skills/product-brief/SKILL.md` | Extract product ideas through guided questions and generate PRD | 63 | **discoverability-risk** |
| `project-health` | `.claude/skills/project-health/SKILL.md` | Scan active projects for status, blockers, and next steps | 57 | **discoverability-risk** |
| `prompt-improver` | `.claude/skills/prompt-improver/SKILL.md` | Transform vague prompts into rich, structured prompts with automatic fallback | 77 | **discoverability-risk** |
| `reset` | `.claude/skills/reset/SKILL.md` | Restructure Dex system based on new role or preferences | 55 | **discoverability-risk** |
| `review` | `.claude/skills/review/SKILL.md` | End of day review with learning capture. Integrates with evening journaling if enabled. | 87 | **discoverability-risk** |
| `save-insight` | `.claude/skills/save-insight/SKILL.md` | Capture learnings from completed work for future reference | 58 | **discoverability-risk** |
| `scrape` | `.claude/skills/scrape/SKILL.md` | Scrape web pages using Scrapling MCP — stealth fetching, anti-bot bypass, CSS selectors. No API key needed. | 107 | **discoverability-risk** |
| `setup` | `.claude/skills/setup/SKILL.md` | Initial Dex system setup and onboarding | 39 | **discoverability-risk** |
| `things-setup` | `.claude/skills/things-setup/SKILL.md` | Connect Things 3 so Dex can read and update your Things tasks on request | 72 | **discoverability-risk** |
| `todoist-setup` | `.claude/skills/todoist-setup/SKILL.md` | Connect Todoist so Dex can read and update your Todoist tasks on request | 72 | **discoverability-risk** |
| `trello-setup` | `.claude/skills/trello-setup/SKILL.md` | Connect Trello so Dex can read your boards and manage cards on request | 70 | **discoverability-risk** |
| `triage` | `.claude/skills/triage/SKILL.md` | Strategically route orphaned files and extract scattered tasks | 62 | **discoverability-risk** |
| `week-plan` | `.claude/skills/week-plan/SKILL.md` | Set weekly priorities and plan the week ahead with intelligent suggestions based on goals, calendar shape, and task effort. | 123 | **discoverability-risk** |
| `week-review` | `.claude/skills/week-review/SKILL.md` | Review week's progress with concrete accomplishments (not fake percentages), pattern detection, and goal tracking. | 114 | **discoverability-risk** |
| `weekly-reflection` | `.claude/skills/weekly-reflection/SKILL.md` | A short guided reflection on what energized you, what drained you, and one thing to change next week. | 101 | **discoverability-risk** |
| `xray` | `.claude/skills/xray/SKILL.md` | Understand what just happened under the hood - learn AI by seeing it in action | 78 | **discoverability-risk** |
| `zoom-setup` | `.claude/skills/zoom-setup/SKILL.md` | Connect Zoom to Dex for meeting recordings, scheduling, and transcript context | 78 | **discoverability-risk** |

## MCP-to-skill connectedness

References are exact tool-name matches in skill bodies (frontmatter excluded). Under-surfaced means 0 referencing skills; over-surfaced means more than 10.

| Server | Referencing skill count | Surface status | Skills (referenced tools) |
| --- | ---: | --- | --- |
| `dex-analytics` | 25 | **over-surfaced** | `create-mcp` (`track_event`); `create-skill` (`track_event`); `daily-plan` (`track_event`); `daily-review` (`track_event`); `dex-add-mcp` (`track_event`); `dex-backlog` (`track_event`); `dex-improve` (`track_event`); `dex-level-up` (`track_event`); `dex-obsidian-setup` (`track_event`); `dex-whats-new` (`track_event`); `getting-started` (`track_event`); `integrate-mcp` (`track_event`); `journal` (`track_event`); `meeting-prep` (`track_event`); `process-meetings` (`track_event`); `product-brief` (`track_event`); `project-health` (`track_event`); `prompt-improver` (`track_event`); `reset` (`track_event`); `review` (`track_event`); `save-insight` (`track_event`); `triage` (`track_event`); `week-plan` (`track_event`); `week-review` (`track_event`); `xray` (`track_event`) |
| `dex-calendar-mcp` | 5 | normal | `daily-plan` (`calendar_get_events_with_attendees`, `calendar_get_today`, `reminders_clear_completed`, `reminders_complete_item`, `reminders_create_item`, `reminders_ensure_lists`, `reminders_find_and_complete`, `reminders_list_completed`, `reminders_list_items`); `daily-review` (`calendar_get_today`, `reminders_clear_completed`, `reminders_find_and_complete`, `reminders_list_completed`, `reminders_list_items`); `getting-started` (`calendar_get_events`); `week-plan` (`calendar_get_events_with_attendees`); `week-review` (`calendar_get_events_with_attendees`, `reminders_list_items`) |
| `dex-career-mcp` | 0 | **under-surfaced** | — |
| `dex-granola-mcp` | 4 | normal | `daily-plan` (`granola_get_recent_meetings`); `getting-started` (`granola_check_available`, `granola_get_recent_meetings`); `week-plan` (`granola_get_today_meetings`); `zoom-setup` (`granola_check_available`) |
| `dex-improvements-mcp` | 7 | normal | `daily-plan` (`list_ideas`, `synthesize_changelog`, `synthesize_learnings`); `daily-review` (`list_ideas`); `dex-backlog` (`capture_idea`, `mark_implemented`); `dex-doctor` (`capture_idea`); `dex-level-up` (`capture_idea`); `dex-whats-new` (`synthesize_changelog`, `synthesize_learnings`); `week-review` (`list_ideas`) |
| `dex-onboarding-mcp` | 1 | normal | `getting-started` (`check_onboarding_complete`) |
| `dex-resume-mcp` | 0 | **under-surfaced** | — |
| `dex-session-memory` | 0 | **under-surfaced** | — |
| `dex-work-mcp` | 7 | normal | `create-mcp` (`create_task`, `list_tasks`); `daily-plan` (`analyze_calendar_capacity`, `build_people_index`, `confirm_goal_link`, `create_task`, `get_commitments_due`, `get_meeting_context`, `get_week_progress`, `list_tasks`, `process_inbox_with_dedup`, `record_external_task_mapping`, `suggest_task_scheduling`, `update_task_status`); `daily-review` (`analyze_calendar_capacity`, `create_task`, `get_commitments_due`, `get_meeting_context`, `get_skill_ratings`, `get_week_progress`, `list_tasks`, `update_task_status`); `process-meetings` (`create_person`, `create_task`, `lookup_person`); `triage` (`create_task`); `week-plan` (`analyze_calendar_capacity`, `classify_task_effort`, `create_weekly_priority`, `get_commitments_due`, `get_goal_status`, `get_quarterly_goals`, `list_tasks`, `suggest_task_scheduling`); `week-review` (`get_goal_status`, `get_quarterly_goals`, `get_skill_ratings`, `get_week_progress`, `list_tasks`) |

### Under-surfaced servers

- `dex-career-mcp` — 0 skills reference its 8 tools.
- `dex-resume-mcp` — 0 skills reference its 12 tools.
- `dex-session-memory` — 0 skills reference its 8 tools.

### Over-surfaced servers

- `dex-analytics` — 25 skills reference its tools.

## Portable ownership classes

Derived from `core/portable_contract.py` `RULES` and `MUTATION_POLICY`.

| Class | Rule count | Update action |
| --- | ---: | --- |
| `brain` | 44 | `replace` |
| `seed` | 38 | `write-if-absent` |
| `generated` | 7 | `regenerate` |
| `vault` | 17 | `never` |
| `runtime` | 13 | `never` |

<details><summary><code>brain</code> declared paths (44)</summary>

- `.agents` (dir; `brain-agents`)
- `.claude` (dir; `brain-claude`)
- `.cursor` (dir; `brain-cursor`)
- `.distignore` (file; `brain-distignore`)
- `.gitattributes` (file; `brain-gitattributes`)
- `.github` (dir; `brain-github`)
- `.gitignore` (file; `brain-gitignore`)
- `.obsidian` (dir; `brain-obsidian`)
- `.scripts` (dir; `brain-dot-scripts`)
- `06-Resources/Dex_System/Background_Processing_Guide.md` (file; `brain-doc-background-processing`)
- `06-Resources/Dex_System/Calendar_Setup.md` (file; `brain-doc-calendar-setup`)
- `06-Resources/Dex_System/Dex_Jobs_to_Be_Done.md` (file; `brain-doc-jobs-to-be-done`)
- `06-Resources/Dex_System/Dex_System_Guide.md` (file; `brain-doc-system-guide`)
- `06-Resources/Dex_System/Dex_Technical_Guide.md` (file; `brain-doc-technical-guide`)
- `06-Resources/Dex_System/Distribution_Checklist.md` (file; `brain-doc-distribution-checklist`)
- `06-Resources/Dex_System/Distribution_Strategy.md` (file; `brain-doc-distribution-strategy`)
- `06-Resources/Dex_System/Folder_Structure.md` (file; `brain-doc-folder-structure`)
- `06-Resources/Dex_System/Memory_Ownership.md` (file; `brain-doc-memory-ownership`)
- `06-Resources/Dex_System/Named_Sessions_Guide.md` (file; `brain-doc-named-sessions`)
- `06-Resources/Dex_System/Obsidian_Guide.md` (file; `brain-doc-obsidian-guide`)
- `06-Resources/Dex_System/README.md` (file; `brain-doc-dex-system-readme`)
- `06-Resources/Dex_System/Updating_Dex.md` (file; `brain-doc-updating-dex`)
- `AGENTS.md` (file; `brain-agents-md`)
- `CHANGELOG.md` (file; `brain-changelog`)
- `CLAUDE.md` (file; `brain-claude-md`)
- `COMMERCIAL_LICENSE.md` (file; `brain-commercial-license`)
- `CONTRIBUTING.md` (file; `brain-contributing`)
- `DISTRIBUTION_READY.md` (file; `brain-distribution-ready`)
- `LICENSE` (file; `brain-license`)
- `README.md` (file; `brain-readme`)
- `System/Beta_Communications` (dir; `brain-beta-communications`)
- `System/README.md` (file; `brain-system-readme`)
- `core` (dir; `brain-core`)
- `docs` (dir; `brain-docs`)
- `install.sh` (file; `brain-install`)
- `package-lock.json` (file; `brain-package-lock`)
- `package.json` (file; `brain-package-json`)
- `packages` (dir; `brain-packages`)
- `pyproject.toml` (file; `brain-pyproject`)
- `requirements-dev.txt` (file; `brain-requirements-dev`)
- `requirements.txt` (file; `brain-requirements`)
- `scripts` (dir; `brain-scripts`)
- `staging` (dir; `brain-staging`)
- `uv.lock` (file; `brain-uv-lock`)

</details>

<details><summary><code>seed</code> declared paths (38)</summary>

- `00-Inbox/Daily_Plans/README.md` (file; `seed-inbox-daily-plans-readme`)
- `00-Inbox/Ideas/README.md` (file; `seed-inbox-ideas-readme`)
- `00-Inbox/Meetings/README.md` (file; `seed-inbox-meetings-readme`)
- `00-Inbox/README.md` (file; `seed-inbox-readme`)
- `01-Quarter_Goals/Quarter_Goals.md` (file; `seed-quarter-goals-file`)
- `02-Week_Priorities/Week_Priorities.md` (file; `seed-week-priorities-file`)
- `03-Tasks/Tasks.md` (file; `seed-tasks-file`)
- `04-Projects/README.md` (file; `seed-projects-readme`)
- `05-Areas/Career/Evidence/README.md` (file; `seed-career-evidence-readme`)
- `05-Areas/Companies/README.md` (file; `seed-companies-readme`)
- `05-Areas/People/External/README.md` (file; `seed-people-external-readme`)
- `05-Areas/People/Internal/README.md` (file; `seed-people-internal-readme`)
- `05-Areas/People/README.md` (file; `seed-people-readme`)
- `05-Areas/README.md` (file; `seed-areas-readme`)
- `06-Resources/Intel/.gitkeep` (file; `seed-intel-gitkeep`)
- `06-Resources/Intel/Meeting_Intel/.gitkeep` (file; `seed-meeting-intel-gitkeep`)
- `06-Resources/Learnings/Mistake_Patterns.md` (file; `seed-mistake-patterns`)
- `06-Resources/Learnings/README.md` (file; `seed-learnings-readme`)
- `06-Resources/Learnings/Working_Preferences.md` (file; `seed-working-preferences`)
- `06-Resources/Quarterly_Reviews/README.md` (file; `seed-quarterly-reviews-readme`)
- `06-Resources/README.md` (file; `seed-resources-readme`)
- `07-Archives/Plans/README.md` (file; `seed-archives-plans-readme`)
- `07-Archives/Projects/README.md` (file; `seed-archives-projects-readme`)
- `07-Archives/README.md` (file; `seed-archives-readme`)
- `07-Archives/Reviews/README.md` (file; `seed-archives-reviews-readme`)
- `System/.mcp.json.example` (file; `seed-mcp-example`)
- `System/Dex_Backlog.md` (file; `seed-dex-backlog`)
- `System/Dex_Ideas.md` (file; `seed-dex-ideas`)
- `System/Session_Learnings/README.md` (file; `seed-session-learnings-readme`)
- `System/Templates` (dir; `seed-templates`)
- `System/integrations` (dir; `seed-integrations`)
- `System/pillars.example.yaml` (file; `seed-pillars-example`)
- `System/pillars.yaml` (file; `seed-pillars-live`)
- `System/trusted-mcps.example.yaml` (file; `seed-trusted-mcps-example`)
- `System/user-profile-template.yaml` (file; `seed-user-profile-template`)
- `System/user-profile.example.yaml` (file; `seed-user-profile-example`)
- `System/user-profile.yaml` (file; `seed-user-profile-live`)
- `env.example` (file; `seed-env-example`)

</details>

<details><summary><code>generated</code> declared paths (7)</summary>

- `System/.doctor-last-run.json` (file; `generated-doctor-last-run`)
- `System/.installed-files.manifest` (file; `generated-manifest`)
- `System/.local-only-preservation-transition.json` (file; `generated-local-only-transition`)
- `System/.release-catalog.json` (file; `generated-release-catalog`)
- `System/.release-evidence-profile.json` (file; `generated-evidence-profile`)
- `docs/architecture/INVENTORY.md` (file; `generated-architecture-inventory`)
- `packages/dex-contracts/dist` (dir; `generated-contracts-dist`)

</details>

<details><summary><code>vault</code> declared paths (17)</summary>

- `.claude/skills-custom` (dir; `vault-skills-custom`)
- `.env` (file; `vault-env`)
- `.mcp.json` (file; `vault-mcp-json`)
- `00-Inbox` (dir; `vault-inbox`)
- `01-Quarter_Goals` (dir; `vault-quarter-goals`)
- `02-Week_Priorities` (dir; `vault-week-priorities`)
- `03-Tasks` (dir; `vault-tasks`)
- `04-Projects` (dir; `vault-projects`)
- `05-Areas` (dir; `vault-areas`)
- `06-Resources` (dir; `vault-resources`)
- `07-Archives` (dir; `vault-archives`)
- `CLAUDE-custom.md` (file; `vault-claude-custom`)
- `System/credentials` (dir; `vault-credentials`)
- `System/folder-paths.yaml` (file; `vault-folder-paths`)
- `System/trusted-mcps.yaml` (file; `vault-trusted-mcps`)
- `core/mcp-custom` (dir; `vault-mcp-custom`)
- `core/mcp-premium` (dir; `vault-mcp-premium`)

</details>

<details><summary><code>runtime</code> declared paths (13)</summary>

- `.logs` (dir; `runtime-logs`)
- `System/.dex` (dir; `runtime-dex-dir`)
- `System/.dex/adoptions` (dir; `runtime-adoption-receipts`)
- `System/.dex/ledger` (dir; `runtime-lifecycle-ledger`)
- `System/.dex/lifecycle/activation.json` (file; `runtime-lifecycle-activation`)
- `System/.last-learning-check` (file; `runtime-last-learning-check`)
- `System/.onboarding` (dir; `runtime-onboarding`)
- `System/.onboarding-complete` (file; `runtime-onboarding-marker`)
- `System/.onboarding-session.json` (file; `runtime-onboarding-session`)
- `System/Session_Learnings` (dir; `runtime-session-learnings`)
- `System/Session_Memory` (dir; `runtime-session-memory`)
- `System/claude-code-state.json` (file; `runtime-claude-state`)
- `System/usage_log.md` (file; `runtime-usage-log`)

</details>
