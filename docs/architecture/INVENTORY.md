<!-- GENERATED FILE — DO NOT EDIT BY HAND. -->
<!-- Generator: scripts/generate-architecture-inventory.py -->
<!-- Content SHA-256: 19a344ab1b393748af635a584dca34e400c0ca7ba1ec8df440a8d13829918cae -->

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

**Skill count:** 72<br>
**Discoverability-risk count:** 4

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
| `atlassian-setup` | `.claude/skills/atlassian-setup/SKILL.md` | Connect Jira and Confluence for project tracking and knowledge search. Use when the user says 'connect Jira', 'hook up Confluence', 'my tickets/board'. Not for a personal task app like Todoist/Things/Trello; use `todoist-setup`/`things-setup`/`trello-setup`. | 258 | when |
| `calendar-setup` | `.claude/skills/calendar-setup/SKILL.md` | Grant Python calendar access for ~30x faster calendar queries. Use when the user says 'connect my calendar', 'calendar is slow', 'set up calendar access'. Not for connecting Google Workspace as a whole; use `google-workspace-setup`. | 232 | when |
| `create-mcp` | `.claude/skills/create-mcp/SKILL.md` | Build a brand-new MCP integration from scratch with a guided wizard. Use when the user wants Dex to talk to a tool that has no existing server — 'build an integration for X', 'Dex can't connect to Y yet'. Not for installing an MCP that already exists; use `integrate-mcp`. Not for a prompt-only workflow with no external tool; use `create-skill`. | 346 | when |
| `create-skill` | `.claude/skills/create-skill/SKILL.md` | Author a new Dex skill — a reusable `/command` — that actually fires and passes the quality bar. Runs a collision check, classifies the shape, writes a router-grade description, generates the real package (SKILL.md + evals), and grades it with `skill-score` before calling it done. Use when the user says 'make a skill', 'I want a /command for X', 'turn this into a skill'. A skill the user builds for themselves is saved as `-custom` (protected from updates) and coached, never blocked; a first-party skill is held to the hard gate. Not for connecting an external tool; use `create-mcp`. Not for grading a skill that already exists; use `skill-score`. | 652 | when |
| `daily-plan` | `.claude/skills/daily-plan/SKILL.md` | Build today's plan from calendar, tasks, priorities and commitments, with smart scheduling suggestions. Use when the user says 'plan my day', 'what's on today', 'help me focus', or starts the morning. Also use proactively at the first session of the day. Not for reviewing a finished day; use `daily-review`. | 308 | when |
| `daily-review` | `.claude/skills/daily-review/SKILL.md` | Close out the day: what got done vs planned, meeting follow-ups, learnings, and tomorrow's focus. Use when the user says 'review my day', 'wrap up', 'end of day', or it's evening. Also use proactively when the day's work is clearly done. Not for setting up the morning; use `daily-plan`. | 287 | when |
| `decision-log` | `.claude/skills/decision-log/SKILL.md` | Capture an important decision with its context, options, rationale, and review date, then find it again when it matters. | 120 | when |
| `delegate-check` | `.claude/skills/delegate-check/SKILL.md` | Review open delegations — what you handed off, to whom, its status, and the next useful nudge. Use when the user says 'what did I delegate', 'who owes me', 'check my handoffs', 'follow up with someone'. Not for prepping a meeting; use meeting-prep. | 248 | when |
| `dex-add-mcp` | `.claude/skills/dex-add-mcp/SKILL.md` | Add a known MCP server to config using Dex-safe user scope. Use when the user has server details in hand and says 'add this MCP', 'register this server'. Not for discovering/installing from a marketplace; use `integrate-mcp`. Not for building one; use `create-mcp`. | 265 | when |
| `dex-backlog` | `.claude/skills/dex-backlog/SKILL.md` | Show the AI-ranked backlog of Dex system-improvement ideas. Use when the user says 'show my Dex ideas', 'what's in the backlog', 'what should we build next'. Not for workshopping one idea into a plan; use `dex-improve`. Not for discovering existing features; use `dex-level-up`. | 278 | when |
| `dex-doctor` | `.claude/skills/dex-doctor/SKILL.md` | Whole-system checkup: verifies every Dex feature honestly (working/off/broken/couldn't-check), self-heals what's provably safe, guides the rest. Use when the user says 'is Dex healthy', 'something's broken', 'check my setup', 'run diagnostics'. Not for discovering unused *features*; use `dex-level-up`. Not for applying an update; use `dex-update`. | 349 | when |
| `dex-improve` | `.claude/skills/dex-improve/SKILL.md` | Workshop one improvement idea into an implementation plan. Use when the user says 'let's flesh out idea-X', 'turn this into a plan', 'improve Dex's Y'. Not for ranking the whole backlog; use `dex-backlog`. Not for a PRD for the user's own product; use `product-brief`. | 268 | when |
| `dex-level-up` | `.claude/skills/dex-level-up/SKILL.md` | Surface Dex features the user isn't using yet, based on their usage patterns. Use when the user says 'what am I missing', 'show me new features', 'level up my Dex'. Not for diagnosing what's broken; use `dex-doctor`. Not for what changed in a release; use `dex-whats-new`. | 272 | when |
| `dex-obsidian-setup` | `.claude/skills/dex-obsidian-setup/SKILL.md` | Turn on Obsidian mode and migrate the vault to wiki links. Use when the user says 'I use Obsidian', 'enable wiki links', 'make this work in Obsidian'. Not for connecting an external tool/API; use `create-mcp`/`integrate-mcp`. | 225 | when |
| `dex-orient` | `.claude/skills/dex-orient/SKILL.md` | Orient in the Dex Core codebase: prints the released version, what's merged-but-not-released, and where the architecture map + inventory live. Use at the start of any dex-core development or investigation, or whenever you're unsure what's shipped vs built-locally vs prototype. | 277 | when |
| `dex-rollback` | `.claude/skills/dex-rollback/SKILL.md` | Rewind one receipt-backed Dex adoption through the frozen lifecycle service. Use when the user says 'undo the update', 'go back', 'that broke something after updating'. Not for applying an update; use `dex-update`. | 214 | when |
| `dex-update` | `.claude/skills/dex-update/SKILL.md` | Preview and safely adopt a Dex update through the receipt-backed lifecycle (look → back up → apply → verify → rewindable). Use when the user says 'update Dex', 'install the new version', or a release notice appeared. Not for undoing an update; use `dex-rollback`. Not just seeing what changed; use `dex-whats-new`. | 314 | when |
| `dex-whats-new` | `.claude/skills/dex-whats-new/SKILL.md` | Show recent system improvements — captured learnings plus new Claude capabilities. Use when the user says 'what's new', 'any updates to how Dex works'. Not for previewing and applying a version update; use `dex-update`. Not for unused existing features; use `dex-level-up`. | 273 | when |
| `diff-adopt` | `.claude/skills/diff-adopt/SKILL.md` | Adopt one shared DexDiff methodology — reads a workflow description, adapts it to your role and vault, and walks you through setup. Use when the user says 'adopt this workflow', 'set me up like this doc'. Not for a full published profile by handle; use `diff-adopt-profile`. | 274 | when |
| `diff-adopt-profile` | `.claude/skills/diff-adopt-profile/SKILL.md` | Adopt a full published Heydex profile by handle ('set me up like @davekilleen'). Use when the user says 'set me up like <person>', or names a handle. Not for a single workflow doc; use `diff-adopt`. Not for creating your own profile; use `diff-profile`. | 253 | when |
| `diff-generate` | `.claude/skills/diff-generate/SKILL.md` | Package one workflow — how you use Dex for a specific job — into a shareable DexDiff methodology doc. Use when the user says 'share how I do X', 'package this workflow'. Not for packaging your *entire* system; use `diff-profile`. Not for adopting someone else's; use `diff-adopt`. | 280 | when |
| `diff-list` | `.claude/skills/diff-list/SKILL.md` | Show all adopted DexDiff workflows — what's installed, when it was adopted, and what it includes | 96 | when |
| `diff-profile` | `.claude/skills/diff-profile/SKILL.md` | Package your entire Dex system into a shareable DexDiff profile so others can replicate how you work. Use when the user says 'share my whole setup', 'publish my profile'. Not for a single workflow; use `diff-generate`. Not for adopting a whole profile; use `diff-adopt-profile`. | 278 | when |
| `diff-remove` | `.claude/skills/diff-remove/SKILL.md` | Remove a previously adopted DexDiff workflow — deletes its generated skills and config, leaves your data untouched. Use when the user says 'remove that workflow', 'undo the adoption'. Not for listing what's installed; use `diff-list`. | 234 | when |
| `enable-semantic-search` | `.claude/skills/enable-semantic-search/SKILL.md` | Turn on local AI-powered semantic (meaning-based) search over the vault, with smart collection discovery. Use when the user says 'enable semantic search', 'search by meaning', 'set up QMD', or search keeps missing obvious matches. Not for scraping the web; use `scrape`. | 270 | when |
| `getting-started` | `.claude/skills/getting-started/SKILL.md` | Interactive post-onboarding tour that adapts to whatever data exists (calendar, Granola, or none). Use right after onboarding, or when the user says 'show me around', 'how do I start'. Also use proactively when the vault is < 7 days old. Not for the initial setup itself; use `setup`. | 284 | when |
| `google-workspace-setup` | `.claude/skills/google-workspace-setup/SKILL.md` | Connect Google Workspace (Gmail, Calendar, Docs) for email-aware planning and meeting prep. Use when the user says 'connect Gmail/Google', 'hook up my work email'. Not for local macOS calendar speed only; use `calendar-setup`. Not for Microsoft; use `ms-teams-setup`. | 267 | when |
| `granola-setup` | `.claude/skills/granola-setup/SKILL.md` | Connect Granola via its official API for automatic meeting sync and transcripts. Use when the user says 'connect Granola', 'my meetings aren't syncing', 'set up meeting notes'. Not for Zoom recordings; use `zoom-setup`. Not for processing meetings already synced; use `process-meetings`. | 287 | when |
| `identity-snapshot` | `.claude/skills/identity-snapshot/SKILL.md` | Generate a living profile of the user's working patterns, decision tendencies and quality preferences from their Dex data. Use when the user says 'what are my patterns', 'how do I work', or during `week-review`. Also use proactively when the model (older than 7 days) is stale. Not for planning a week; use `week-plan`. | 319 | when |
| `industry-truths` | `.claude/skills/industry-truths/SKILL.md` | Define time-horizoned assumptions about your industry (today / 6mo / 12mo) that ground strategic thinking. Use when the user is making roadmap, positioning or investment calls, or says 'what am I assuming about the market'. Also use proactively before a big strategic recommendation. Not for capturing a single decision; use `decision-log`. | 340 | when |
| `initiative-kickoff` | `.claude/skills/initiative-kickoff/SKILL.md` | Turn a decision to start something new — a hire, a partnership, a go-to-market push, an internal bet — into a real initiative: the outcome and why now, what success looks like, who's involved, the first concrete steps, and a project page that ladders to your pillars and goals. Use when the user says 'let's kick off X', 'I'm starting a new initiative', 'set up a project for this', or 'we've decided to do Y'. Also use proactively when the user commits to a new effort mid-conversation. Not for spec'ing a product feature or writing a PRD; use `product-brief`. Not for checking the status of projects already underway; use `project-health`. | 641 | when |
| `integrate-mcp` | `.claude/skills/integrate-mcp/SKILL.md` | Install and wire up an existing MCP server from Smithery.ai or a GitHub repo. Use when the user names a tool that already has a server — 'add the Notion MCP', 'install this Smithery server'. Not for building a new integration from nothing; use `create-mcp`. Not for adding one already-known server safely; use `dex-add-mcp`. | 324 | when |
| `journal` | `.claude/skills/journal/SKILL.md` | Toggle journaling or start a morning/evening/weekly journal entry. Use when the user says 'journal', 'morning pages', 'evening reflection'. Also use proactively when a journaling-enabled user starts/ends the day. Not for a structured end-of-day work review; use `daily-review`. | 277 | when |
| `manage-capabilities` | `.claude/skills/manage-capabilities/SKILL.md` | Turn optional Dex rooms/features on or off without deleting any content. Use when the user says 'turn off X', 'enable the career room', 'hide a feature I don't use'. Not for diagnosing breakage; use `dex-doctor`. Not for a full role restructure; use `reset`. | 258 | when |
| `meeting-closeout` | `.claude/skills/meeting-closeout/SKILL.md` | Close out the meeting you just had while it's fresh — lock the decisions, the action items and who owns each, what you personally committed to, and the single next step — then capture it and, only with your OK, turn the actions into tracked tasks. Use when the user says 'wrap up this meeting', 'close out my 3pm', 'here are my notes from the call', or right after a meeting ends. Also use proactively when the user pastes raw notes from a meeting that just happened. Not for bulk-processing many already-synced meetings; use `process-meetings`. Not for prepping a meeting that hasn't happened yet; use `meeting-prep`. | 618 | when |
| `meeting-prep` | `.claude/skills/meeting-prep/SKILL.md` | Prepare for a specific upcoming meeting by gathering attendee context, history and related topics. Use when the user says 'prep me for my meeting with X', 'what do I need for the 2pm', or before a calendar event. Also use proactively when a meeting is imminent. Not for writing up a meeting that already happened; use `process-meetings`. | 337 | when |
| `ms-teams-setup` | `.claude/skills/ms-teams-setup/SKILL.md` | Connect Microsoft Teams for cross-channel context awareness. Use when the user says 'connect Teams', 'hook up Microsoft'. Not for Google email/calendar; use `google-workspace-setup`. | 182 | when |
| `process-meetings` | `.claude/skills/process-meetings/SKILL.md` | Turn synced meetings into updated person pages, extracted tasks and organized notes. Use when the user says 'process my meetings', 'catch up my notes', or after Granola/Otter syncs. Also use proactively when unprocessed meetings exist. Not for prepping an upcoming meeting; use `meeting-prep`. | 293 | when |
| `product-brief` | `.claude/skills/product-brief/SKILL.md` | Extract a product idea through guided questions and generate a PRD. Use when the user says 'write a PRD', 'spec this feature', 'turn this idea into a brief'. Not for a non-product initiative like hiring or partnerships (use `initiative-kickoff` once shipped); not for checking existing projects' status (use `project-health`). | 326 | when |
| `project-health` | `.claude/skills/project-health/SKILL.md` | Scan active projects for status, blockers and next actions. Use when the user says 'how are my projects', 'what's stuck', 'project status'. Also use proactively when projects have gone quiet. Not for writing a spec for a new product idea; use `product-brief`. | 259 | when |
| `prompt-improver` | `.claude/skills/prompt-improver/SKILL.md` | Rewrite a vague prompt into a rich, structured one, with automatic fallback. Use when the user says 'improve this prompt', 'make this prompt better', or hands over a thin instruction. Not for creating a reusable skill; use `create-skill`. | 238 | when |
| `reset` | `.claude/skills/reset/SKILL.md` | Restructure an existing Dex vault for a new role or changed preferences, without losing data. Use when the user says 'I changed jobs', 'restructure my Dex', 'my role is different now'. Not for first-time setup; use `setup`. Not for just toggling one feature; use `manage-capabilities`. | 285 | when |
| `review` | `.claude/skills/review/SKILL.md` | End of day review with learning capture. Integrates with evening journaling if enabled. | 87 | **discoverability-risk** |
| `save-insight` | `.claude/skills/save-insight/SKILL.md` | Capture a reusable learning from completed work so future similar work is easier. Use when the user says 'save this learning', 'capture this insight', or finishes something tricky. Also use proactively after non-routine work. Not for recording a *decision* and its rationale; use `decision-log`. | 295 | when |
| `scrape` | `.claude/skills/scrape/SKILL.md` | Scrape web pages via Scrapling — stealth fetching, anti-bot bypass, CSS selectors, no API key. Use when the user says 'scrape', 'pull data from this URL', 'extract from this site'. Not for meaning-based search of the user's own vault; use `enable-semantic-search`. | 264 | when |
| `setup` | `.claude/skills/setup/SKILL.md` | Run first-time Dex onboarding: build the vault structure, capture the user profile and configure MCPs. Use when `04-Projects/` doesn't exist yet or the user says 'set up Dex', 'start onboarding'. Not for the post-onboarding tour; use `getting-started`. Not for a mid-life role change; use `reset`. | 297 | when |
| `skill-score` | `.claude/skills/skill-score/SKILL.md` | Grade a Dex skill against the shape-aware quality rubric and report a ship/revise/no verdict with the exact fixes. Use when you finish writing or editing a skill, when create-skill hands off a new package, before shipping a first-party skill, or when the user asks "is this skill any good / will it fire / score my skill". Also use proactively right after any SKILL.md is created or its description changes. Not for authoring a new skill from scratch (use create-skill) or fixing broken YAML frontmatter alone (create-skill's validator does that); skill-score judges architecture and routing, not just format. | 609 | when |
| `things-setup` | `.claude/skills/things-setup/SKILL.md` | Connect Things 3 (macOS only) so Dex reads and updates your Things tasks. Use when the user says 'I use Things', 'sync my Things inbox', or pastes a `things://` link. Not for Todoist (`todoist-setup`) or Trello (`trello-setup`). | 228 | when |
| `todoist-setup` | `.claude/skills/todoist-setup/SKILL.md` | Connect Todoist so Dex reads and updates your Todoist tasks two ways. Use when the user says 'I use Todoist', 'sync Todoist', or pastes a todoist.com link. Not for Things 3 (`things-setup`) or Trello (`trello-setup`); not for Jira tickets (`atlassian-setup`). | 259 | when |
| `trello-setup` | `.claude/skills/trello-setup/SKILL.md` | Connect Trello so Dex reads your boards and manages cards. Use when the user says 'I use Trello', 'my Trello board', or pastes a trello.com link. Not for Todoist (`todoist-setup`) or Things (`things-setup`). | 207 | when |
| `triage` | `.claude/skills/triage/SKILL.md` | Route orphaned inbox files and pull scattered `- [ ]` tasks into the right project/person/goal using current priorities. Use when the user says 'clean up my inbox', 'triage', 'sort out these notes'. Also use proactively when `00-Inbox/` is piling up. Not for updating notes from meetings; use `process-meetings`. | 312 | when |
| `week-plan` | `.claude/skills/week-plan/SKILL.md` | Set the week's priorities against goals, calendar shape and task effort. Use when the user says 'plan my week', 'what should I focus on this week', or on Monday. Also use proactively at the first session of a new week. Not for reviewing the week just past; use `week-review`. | 275 | when |
| `week-review` | `.claude/skills/week-review/SKILL.md` | Review the week with concrete accomplishments (not fake percentages), pattern detection and goal tracking. Use when the user says 'how was my week', 'week review', or it's Friday/end of week. Also use proactively when a week's priorities are largely resolved. Not for planning the coming week; use `week-plan`. | 310 | when |
| `weekly-reflection` | `.claude/skills/weekly-reflection/SKILL.md` | A short guided reflection on what energized you, what drained you, and one change for next week. Use when the user wants to reflect on how work *felt*, not what got done — 'reflect on my week', 'what's draining me'. Not for progress-and-goals tracking; use `week-review`. | 271 | when |
| `xray` | `.claude/skills/xray/SKILL.md` | Explain what just happened under the hood — the context, MCP tools, and hooks behind Dex's last response — as AI education. Use when the user says 'how did you do that', 'what just happened', 'explain the mechanics'. Not for a system health check; use `dex-doctor`. | 265 | when |
| `zoom-setup` | `.claude/skills/zoom-setup/SKILL.md` | Connect Zoom for meeting recordings, scheduling and transcript context. Use when the user says 'connect Zoom', 'pull my Zoom recordings'. Not for Granola-sourced notes; use `granola-setup`. Not for Teams; use `ms-teams-setup`. | 226 | when |

## MCP-to-skill connectedness

References are exact tool-name matches in skill bodies (frontmatter excluded). Under-surfaced means 0 referencing skills; over-surfaced means more than 10.

| Server | Referencing skill count | Surface status | Skills (referenced tools) |
| --- | ---: | --- | --- |
| `dex-analytics` | 27 | **over-surfaced** | `create-mcp` (`track_event`); `create-skill` (`track_event`); `daily-plan` (`track_event`); `daily-review` (`track_event`); `dex-add-mcp` (`track_event`); `dex-backlog` (`track_event`); `dex-improve` (`track_event`); `dex-level-up` (`track_event`); `dex-obsidian-setup` (`track_event`); `dex-whats-new` (`track_event`); `getting-started` (`track_event`); `initiative-kickoff` (`track_event`); `integrate-mcp` (`track_event`); `journal` (`track_event`); `meeting-closeout` (`track_event`); `meeting-prep` (`track_event`); `process-meetings` (`track_event`); `product-brief` (`track_event`); `project-health` (`track_event`); `prompt-improver` (`track_event`); `reset` (`track_event`); `review` (`track_event`); `save-insight` (`track_event`); `triage` (`track_event`); `week-plan` (`track_event`); `week-review` (`track_event`); `xray` (`track_event`) |
| `dex-calendar-mcp` | 5 | normal | `daily-plan` (`calendar_get_events_with_attendees`, `calendar_get_today`, `reminders_clear_completed`, `reminders_complete_item`, `reminders_create_item`, `reminders_ensure_lists`, `reminders_find_and_complete`, `reminders_list_completed`, `reminders_list_items`); `daily-review` (`calendar_get_today`, `reminders_clear_completed`, `reminders_find_and_complete`, `reminders_list_completed`, `reminders_list_items`); `getting-started` (`calendar_get_events`); `week-plan` (`calendar_get_events_with_attendees`); `week-review` (`calendar_get_events_with_attendees`, `reminders_list_items`) |
| `dex-career-mcp` | 0 | **under-surfaced** | — |
| `dex-granola-mcp` | 4 | normal | `daily-plan` (`granola_get_recent_meetings`); `getting-started` (`granola_check_available`, `granola_get_recent_meetings`); `week-plan` (`granola_get_today_meetings`); `zoom-setup` (`granola_check_available`) |
| `dex-improvements-mcp` | 7 | normal | `daily-plan` (`list_ideas`, `synthesize_changelog`, `synthesize_learnings`); `daily-review` (`list_ideas`); `dex-backlog` (`capture_idea`, `mark_implemented`); `dex-doctor` (`capture_idea`); `dex-level-up` (`capture_idea`); `dex-whats-new` (`synthesize_changelog`, `synthesize_learnings`); `week-review` (`list_ideas`) |
| `dex-onboarding-mcp` | 1 | normal | `getting-started` (`check_onboarding_complete`) |
| `dex-resume-mcp` | 0 | **under-surfaced** | — |
| `dex-session-memory` | 0 | **under-surfaced** | — |
| `dex-work-mcp` | 9 | normal | `create-mcp` (`create_task`, `list_tasks`); `daily-plan` (`analyze_calendar_capacity`, `build_people_index`, `confirm_goal_link`, `create_task`, `get_commitments_due`, `get_meeting_context`, `get_week_progress`, `list_tasks`, `process_inbox_with_dedup`, `record_external_task_mapping`, `suggest_task_scheduling`, `update_task_status`); `daily-review` (`analyze_calendar_capacity`, `create_task`, `get_commitments_due`, `get_meeting_context`, `get_skill_ratings`, `get_week_progress`, `list_tasks`, `update_task_status`); `initiative-kickoff` (`confirm_goal_link`, `create_task`, `get_quarterly_goals`, `lookup_person`); `meeting-closeout` (`create_task`, `get_meeting_context`, `lookup_person`); `process-meetings` (`create_person`, `create_task`, `lookup_person`); `triage` (`create_task`); `week-plan` (`analyze_calendar_capacity`, `classify_task_effort`, `create_weekly_priority`, `get_commitments_due`, `get_goal_status`, `get_quarterly_goals`, `list_tasks`, `suggest_task_scheduling`); `week-review` (`get_goal_status`, `get_quarterly_goals`, `get_skill_ratings`, `get_week_progress`, `list_tasks`) |

### Under-surfaced servers

- `dex-career-mcp` — 0 skills reference its 8 tools.
- `dex-resume-mcp` — 0 skills reference its 12 tools.
- `dex-session-memory` — 0 skills reference its 8 tools.

### Over-surfaced servers

- `dex-analytics` — 27 skills reference its tools.

## Portable ownership classes

Derived from `core/portable_contract.py` `RULES` and `MUTATION_POLICY`.

| Class | Rule count | Update action |
| --- | ---: | --- |
| `brain` | 43 | `replace` |
| `seed` | 38 | `write-if-absent` |
| `generated` | 8 | `regenerate` |
| `vault` | 17 | `never` |
| `runtime` | 13 | `never` |

<details><summary><code>brain</code> declared paths (43)</summary>

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

<details><summary><code>generated</code> declared paths (8)</summary>

- `CLAUDE.md` (file; `generated-claude-md`)
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
