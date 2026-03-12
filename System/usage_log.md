# Dex Usage Tracking

**Purpose:** Track feature adoption to help guide users to unused capabilities, and provide journey metadata for analytics.

**Last Updated:** Auto-updated by system

---

## Core Workflows (8 features)

- [x] Daily planning (`/daily-plan`)
- [ ] Daily review (`/review` or `/daily-review`)
- [ ] Weekly planning (`/week-plan`)
- [x] Weekly review (`/week-review`)
- [ ] Quarterly planning (`/quarter-plan`)
- [ ] Quarterly review (`/quarter-review`)
- [ ] Getting started tour (`/getting-started`)
- [ ] Journaling (`/journal`)

## Meeting Workflows (7 features)

- [ ] Meeting prep (`/meeting-prep`)
- [ ] Meeting processing (`/process-meetings`)
- [ ] Commitment scan (`/commitment-scan`)
- [ ] Person page created
- [ ] Person page updated
- [ ] Company page created
- [ ] Granola connected

## Task Management (6 features)

- [ ] Task created (via Work MCP)
- [ ] Task completed (via Work MCP)
- [ ] Task updated (via Work MCP)
- [ ] Priority set (P0/P1/P2)
- [ ] Goal created
- [ ] Pillar alignment used

## Organization (5 features)

- [ ] Inbox triage (`/triage` or `/process-inbox`)
- [ ] Learning capture (`/save-insight`)
- [ ] Project tracking (`/project-health`)
- [ ] Product brief (`/product-brief`)
- [ ] Project page created

## Journaling (4 features)

- [ ] Journaling setup (`/journal`)
- [ ] Morning journal entry
- [ ] Evening journal entry
- [ ] Weekly journal entry

## Career Development (6 features)

- [ ] Career setup (`/career-setup`)
- [ ] Career coaching (`/career-coach`)
- [ ] Resume builder (`/resume-builder`)
- [ ] Career evidence captured
- [ ] Promotion readiness checked
- [ ] Skills gap analysis

## System Discovery & Improvement (10 features)

- [ ] Feature discovery (`/dex-level-up`)
- [ ] X-ray transparency (`/xray`)
- [ ] What's new check (`/dex-whats-new`)
- [ ] Backlog review (`/dex-backlog`)
- [ ] Improvement workshop (`/dex-improve`)
- [ ] Idea captured (via MCP)
- [ ] Dex updated (`/dex-update`)
- [ ] Dex rolled back (`/dex-rollback`)
- [ ] Learnings reviewed (`/learnings`)
- [ ] Beta feature activated (`/beta-activate`)

## Integrations (8 features)

- [ ] Calendar connected (via Calendar MCP)
- [ ] Calendar synced daily
- [ ] Granola connected (via Granola MCP)
- [ ] Obsidian enabled (`/dex-obsidian-setup`)
- [ ] ScreenPipe enabled (`/screenpipe-setup`)
- [ ] ScreenPipe used (`/screen-recall` or `/screen-summary`)
- [ ] MCP added (`/dex-add-mcp`)
- [ ] Pi used (`/pi`)

## AI Configuration (5 features)

- [ ] AI setup started (`/ai-setup`)
- [ ] Budget cloud configured (OpenRouter)
- [ ] Offline mode configured (Ollama)
- [ ] Smart routing enabled
- [ ] AI status checked (`/ai-status`)

## Advanced (7 features)

- [ ] Prompt improvement via API (`/prompt-improver`)
- [ ] Custom MCP created (`/create-mcp`)
- [ ] MCP integrated (`/integrate-mcp`)
- [ ] Custom skill created (`/create-skill`)
- [ ] Demo mode used (`/dex-demo`)
- [ ] Vault reset (`/reset`)
- [ ] Setup re-run (`/setup`)

---

## Tracking Metadata

- **Last dex-level-up prompt:** (not yet prompted)
- **First daily plan:** 2026-03-02
- **Setup date:** (set during onboarding)

---

## Analytics Consent

Tracks whether user has been asked about anonymous feature usage tracking.

- **Consent asked:** false
- **Consent decision:** pending
- **Consent date:** (not yet decided)
- **Last prompted:** (not yet prompted)

**Values:**
- `Consent decision: pending` → Not yet decided (will be asked each session until they choose)
- `Consent decision: opted-in` → User agreed to help improve Dex
- `Consent decision: opted-out` → User declined (never ask again)

---

## ScreenPipe Consent

Tracks whether user has been asked about ScreenPipe ambient intelligence.

- **Consent asked:** false
- **Consent decision:** pending
- **Consent date:** (not yet decided)

**Values:**
- `Consent decision: pending` → Not yet asked
- `Consent decision: opted-in` → User wants ScreenPipe features
- `Consent decision: opted-out` → User declined ScreenPipe

**What ScreenPipe enables (when opted in):**
- `/commitment-scan` - Detect uncommitted asks/promises from Slack, Email, etc.
- Daily review commitment check - Surface items during `/daily-review`
- Time audit - Breakdown of time by app
- Screen recall - "What was I doing at 2pm?"

**Privacy:**
- All data stored locally (never sent anywhere)
- Work apps only (browsers, banking, social blocked by default)
- Auto-deletes after 30 days
- User can disable anytime

---

## Journey Metadata

Auto-calculated metrics (if analytics opted in). Updated when features are used.

- **Days since setup:** 0
- **Feature adoption score:** 0/66
- **Journey stage:** new
- **Most active area:** (not yet determined)
- **Last active date:** (not yet active)

**Journey stages:**
- `new` (days 0-7): Just onboarded, learning basics
- `exploring` (days 8-30): Trying different features
- `established` (days 31-90): Regular usage patterns
- `power_user` (90+ days): Deep feature adoption

---

## AI Education Progress

Track your understanding of the underlying system (via `/xray`):

- [ ] Understands context windows (how AI "sees" information)
- [ ] Understands tokens (the currency of context)
- [ ] Understands system prompts (CLAUDE.md)
- [ ] Understands tools/MCPs (how AI takes action)
- [ ] Understands session hooks (the boot sequence)
- [ ] Understands vault architecture (where everything lives)
- [ ] Created first CLAUDE.md customization
- [ ] Created first custom skill
- [ ] Created first custom hook
- [ ] Created first MCP server

---

## Notes

This file is automatically updated as you use Dex features:
- Checkboxes get checked when you use a feature
- Journey metadata updates based on checked features
- Run `/dex-level-up` anytime to discover capabilities you haven't explored yet
