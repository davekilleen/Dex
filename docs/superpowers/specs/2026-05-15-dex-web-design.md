# Dex Web Design

Date: 2026-05-15

## Summary

Dex Web is the first public, non-terminal product surface for Dex. It should start as a local browser app and later be portable into a desktop shell. The product uses the existing Dex GitHub repository as the base layer: Dex Core remains the engine and source of truth, while Dex Web becomes a React workspace for setup, vault navigation, Markdown editing, day logs, contextual chat, connection health, and next-best-action guidance.

The central product problem is that current Dex usage expects comfort with a terminal, raw files, and hidden slash commands. Dex Web should make the same local Markdown operating system visible and approachable for public users without weakening the local-first, user-owned file model.

## Approved Direction

- Build a separate `product/dex-web` surface instead of folding the UI directly into `product/dex-core`.
- Run as a local browser app first; design the surface so it can move into a desktop app later.
- Treat `product/dex-core` as the runtime engine for setup, vault structure, path contracts, MCP servers, skills, Granola processing, and Markdown/YAML truth.
- Use MagicPath to explore UI directions and generate React components, then adapt those components into production Dex Web code.
- Make Granola the first supported meeting transcript source for v1.
- Keep integrations optional after core setup, but make missing or broken connections visible and repairable.

## Goals

- Let non-technical public users complete Dex setup without living in the terminal.
- Make the Dex vault navigable through a file tree and Markdown editor/preview.
- Provide calendar-based day logs that can hold daily plans, notes, meetings, diary entries, and progress.
- Provide contextual chat that focuses on the selected file, folder, or day log.
- Restore the returning user's last workspace state.
- Show connection health for MCPs and integrations with green, amber, red, and not-added states.
- Use existing feature adoption data to suggest 2-3 high-signal next actions.
- Preserve local Markdown and YAML files as the durable source of truth.

## Non-Goals

- Do not build a hosted cloud product in v1.
- Do not turn Dex Web into a replacement knowledge database.
- Do not make v1 provider-neutral for all meeting transcript systems; Granola is the v1 path.
- Do not build a terminal transcript inside a web view. Setup should become native UI.
- Do not expose private founder-only context or assumptions in public product code.
- Do not make MagicPath-generated components write directly to arbitrary Dex internals.

## Architecture

Dex Web should live as its own product surface, likely `product/dex-web`.

The architecture has three layers:

1. MagicPath as the design source.
   MagicPath explores layouts and generates React components for setup, workspace, day logs, vault navigation, chat, connection health, and recommendation surfaces.

2. Dex Web as the product surface.
   Dex Web owns UI state, routing, layout, setup presentation, workspace restore, chat presentation, Markdown editor/preview, and user interactions.

3. Dex Core as the engine.
   Dex Core owns vault structure, setup/onboarding logic, MCP servers, skills, path contracts, Granola processing, daily planning behavior, and the Markdown/YAML files that hold user truth.

Dex Web should communicate with Dex Core through an explicit local action/API boundary. It should not reach into random internals. The local API should expose stable operations such as reading the vault tree, saving Markdown, creating day logs, running setup steps, checking connection health, and processing lightweight Granola context.

## First-Run Experience

First run opens guided setup, not the workspace.

The setup flow should wrap the existing `/setup` and onboarding logic as native UI. It should collect:

- name
- role
- company size
- email domain
- strategic pillars
- communication preferences

It should then create the Dex vault structure and write the same canonical files used today:

- `System/user-profile.yaml`
- `System/pillars.yaml`
- `.claude/vault-config.json`
- MCP configuration
- PARA folder structure and initial task/planning files

Setup completion should be a hard gate for entering the main workspace. Integrations are not a hard gate, but the UI should strongly recommend the high-value ones.

## Granola-First Activation

V1 should make Granola the primary meeting transcript source.

After setup, Dex Web should detect whether Granola is available. If it is available, the product should create lightweight meeting context automatically after consent:

- meeting index
- people pages where obvious
- company pages where obvious
- meeting references
- day-log links where useful

Dex Web should not silently create a backlog of meeting-derived tasks. It should ask before extracting or syncing tasks, with controls such as recent-window choice and review-before-add.

If Granola is unavailable, the user can continue into the workspace. The UI should explain what Granola unlocks and keep a clear path back to connect it later.

## Returning Workspace

Returning users should restore their last workspace state. If they last opened a file, Dex Web reopens that file. If they last opened a folder, it restores that folder. If they last worked in a day log with a chat sidecar, it restores that pairing.

The calendar/day log is a major surface, but not a forced home for every session.

The main workspace includes:

- Vault explorer: browse folders/files, create Markdown files, create folders, archive/delete safely.
- Main work surface: Markdown editor/preview and calendar day logs.
- Contextual chat: chat focused on the selected file, folder, or day, with history, pinned chats, ordering, and archive.

## Day Logs

Day logs should map calendar dates to Markdown files. A day file can include:

- the daily plan
- notes captured during the day
- meeting context
- diary/reflection content
- progress and completion notes

Users should be able to move forward or backward in time, create a day file if it does not exist, edit it directly, and run the daily-plan equivalent from the UI.

## Data Model

Durable user truth remains in the Dex vault:

- Markdown files for notes, day logs, meetings, people, companies, projects, tasks, and reviews.
- YAML/JSON files for profile, pillars, onboarding markers, MCP config, and path contracts.
- Dex Core generated artifacts such as daily plans, lightweight Granola context, and meeting references.

Dex Web may store UI/product metadata:

- last opened file, folder, date, and chat
- panel layout
- active workspace view
- pinned chat order
- archived chat status
- setup progress presentation
- context pointers linking chats to files, folders, or days

Dex Web metadata should never become the canonical knowledge store.

## Local Action API

The local API should support these action families:

- Vault: list tree, read file, save file, create file, create folder, archive/delete.
- Day log: resolve date file, create date file, attach meetings, run daily plan.
- Setup: start/resume onboarding, validate step, finalize, check dependencies.
- Granola: detect cache, summarize availability, create lightweight context, review tasks before sync.
- Connections: check health, repair auth, re-run permissions checks, add integration.
- Recommendations: read usage state and return 2-3 next best actions.
- Chat context: open chat, attach context, pin, reorder, archive, and restore.

File writes must be scoped to the user's Dex vault. Delete should default to reversible archive or trash behavior.

## Connection Health

Dex Web should show a lightweight persistent connection status indicator. It should avoid feeling like an admin console.

Connection states:

- Green: fully working.
- Amber: partially working, permission-limited, stale, or missing an optional capability.
- Red: not working, missing auth, expired auth, failed health check, or broken config.
- Not added: available but never connected.

Clicking the indicator opens a Connections page. The page should show:

- connected MCPs and integrations
- current status and last check
- what still works when a connection is degraded
- repair or re-authentication actions
- available integrations to add
- features affected by broken connections

V1 should support at least Granola and Calendar health. The model should extend to Gmail, Slack, Google Workspace, Teams, Todoist, Things, Trello, and custom MCPs.

## Next Best Actions

Dex Web should turn `/dex-level-up` into a native coaching layer.

The UI should show 2-3 high-signal cards instead of a full command catalog. Each card should explain why it is relevant now, estimate time required, and include an action button.

Inputs:

- `System/usage_log.md`
- `System/user-profile.yaml`
- setup progress
- connection health
- vault state
- role-specific available skills

Example cards:

- Set quarterly goals: you have pillars, but no quarter goals yet.
- Process your first Granola meeting: Granola is connected, but no meetings have been processed.
- Enable Obsidian links: make people, projects, and meetings clickable.
- Try weekly review: you are planning daily, but not closing the loop weekly.
- Repair Calendar: daily plans improve once calendar access is green.

Cards should support dismissal and snooze so guidance feels helpful, not nagging.

## MagicPath Brief

MagicPath should receive requirements, not a fixed wireframe.

Brief:

Design a local-first Dex workspace for non-technical public users. Dex Web replaces terminal-first setup and makes the user's Markdown vault visible, editable, and chat-addressable. It should include first-run setup, returning-state restore, vault explorer, Markdown editor/preview, calendar day log, contextual chat, chat history/pinning/archive, connection health, next-best-action guidance, and Granola-first meeting setup.

Constraints:

- serious product workspace, not a landing page
- approachable for users who do not want the terminal
- Markdown files feel visible and user-owned
- chat is contextual, not a generic blank assistant
- Granola and meeting memory feel like the highest-value unlock
- layouts must support future desktop packaging

Ask MagicPath to explore three directions:

1. Daybook-centered.
   Calendar/day log is the emotional center, with file tree and chat as persistent side surfaces.

2. Workspace-centered.
   Vault/file workspace is primary, with day log as one view and chat as a contextual panel.

3. Setup-to-reveal.
   Onboarding and activation are the hero flow, then users land in a simpler workspace.

## Error States

Design and implement explicit states for:

- setup incomplete or interrupted
- vault read/write permission issues
- missing or unavailable Granola cache
- degraded or broken integrations
- expired or missing authentication
- unsaved edits
- file conflicts
- local action failure
- unavailable MCP server

Every error should explain what happened, what still works, and what the user can do next.

## Trust Rules

- Show exactly where generated files are written.
- Review meeting-derived tasks before adding them.
- Default destructive actions to archive/trash.
- Keep generated content editable as Markdown.
- Let users skip integrations and return later.
- Do not hide user data in a separate app-only database.

## Verification Plan

Testing should cover:

- vault tree parsing
- safe file read/write/create/archive operations
- date-to-day-file resolution
- setup start/resume/finalize flow
- local API contracts against Dex Core path/onboarding contracts
- Granola lightweight-context flow
- task-review-before-sync flow
- connection health green/amber/red states
- returning workspace restore
- contextual chat pointers
- Next Best Actions recommendation logic
- MagicPath-derived component responsiveness and layout fit

## Definition Of Done For V1

A non-technical public user can:

- complete setup without using the terminal
- optionally connect Granola
- enter a local browser workspace
- browse the Dex vault
- create, open, edit, and archive Markdown files
- create and open calendar day logs
- run the daily-plan equivalent from the UI
- see connection health and repair degraded integrations
- see useful next-best-action guidance
- chat with selected-file, selected-folder, or selected-day context

The user's durable system remains plain local Markdown and YAML in the Dex vault.
