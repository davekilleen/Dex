# Dex Usage Tracking

**Purpose:** Track feature adoption to help guide users to unused capabilities, and provide journey metadata for analytics.

**Last Updated:** Auto-updated by system

---

## Core Workflows (8 features)

- [ ] Daily planning (`/daily-plan`)
- [ ] Daily review (`/review` or `/daily-review`)
- [ ] Weekly planning (`/week-plan`)
- [ ] Weekly review (`/week-review`)
- [ ] Quarterly planning (`/quarter-plan`)
- [ ] Quarterly review (`/quarter-review`)
- [ ] Getting started tour (`/getting-started`)
- [ ] Journaling (`/journal`)

## Meeting Workflows (6 features)

- [ ] Meeting prep (`/meeting-prep`)
- [ ] Meeting processing (`/process-meetings`)
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

## System Discovery & Improvement (9 features)

- [ ] Feature discovery (`/dex-level-up`)
- [ ] X-ray transparency (`/xray`)
- [ ] What's new check (`/dex-whats-new`)
- [ ] Backlog review (`/dex-backlog`)
- [ ] Improvement workshop (`/dex-improve`)
- [ ] Idea captured (via MCP)
- [ ] Dex updated (`/dex-update`)
- [ ] Dex rolled back (`/dex-rollback`)
- [ ] Learnings reviewed (`/learnings`)

## Integrations (5 features)

- [ ] Calendar connected (via Calendar MCP)
- [ ] Calendar synced daily
- [ ] Granola connected (via Granola MCP)
- [ ] Obsidian enabled (`/dex-obsidian-setup`)
- [ ] MCP added (`/dex-add-mcp`)

## Advanced (6 features)

- [ ] Prompt improvement via API (`/prompt-improver`)
- [ ] Custom MCP created (`/create-mcp`)
- [ ] MCP integrated (`/integrate-mcp`)
- [ ] Custom skill created (`/create-skill`)
- [ ] Vault reset (`/reset`)
- [ ] Setup re-run (`/setup`)

---

## Tracking Metadata

- **Last dex-level-up prompt:** (not yet prompted)
- **First daily plan:** (not yet run)
- **Setup date:** (set during onboarding)

---

## Analytics Consent

Tracks anonymous feature usage tracking to help improve Dex.

- **Consent asked:** true
- **Consent decision:** opted-in
- **Consent date:** (set during onboarding)
- **Last prompted:** (not applicable)

**Values:**
- `Consent decision: opted-in` → Analytics active (default for new installs)
- `Consent decision: opted-out` → User opted out (say "turn off Dex analytics" anytime)

---

## Health Telemetry Consent

Separate, optional nightly fleet-health counts. This setting is independent of analytics.

**Health telemetry:** pending

**Values:**
- `Health telemetry: opted-in` → Send the counts-only nightly smoke verdict
- `Health telemetry: opted-out` → Do not send nightly health telemetry
- `Health telemetry: pending` → Not yet decided; missing or pending means nothing is sent

---

## Journey Metadata

Auto-calculated metrics (if analytics opted in). Updated when features are used.

- **Days since setup:** 0
- **Feature adoption score:** 0/61
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
