# Dex System TODOs

Deferred work from plan reviews. Each item has context for pickup in 3+ months.

---

## P1 — Important

### /daily-plan reads confirmed priorities
**What:** Update the `/daily-plan` skill to check `.scripts/slack-dex-bot/state/confirmed-priorities.json` and pre-populate the day's plan.
**Why:** Closes the EOD-to-morning loop — commitments made at 17:30 flow into the next morning's plan automatically.
**Start here:** Read `.claude/skills/daily-plan/SKILL.md`, add a step that checks for the confirmed-priorities file and surfaces those items first.
**Depends on:** Slack EOD bot hardening (state file writes).
**Effort:** S

---

## P2 — Normal

### Socket Mode heartbeat monitoring
**What:** Socket Mode bot writes a heartbeat timestamp to state file every 5 minutes. EOD trigger or `/daily-plan` checks staleness.
**Why:** Detects zombie processes where Socket Mode disconnects but the process doesn't exit (KeepAlive won't restart these).
**Start here:** Add a `setInterval` in the Socket Mode startup that writes `{ lastHeartbeat: ISO }` to `state/heartbeat.json`.
**Depends on:** State directory (done).
**Effort:** S

### Notion writeback for confirmed items
**What:** When user confirms EOD items, update their Notion status to "Committed" or add a date property.
**Why:** Keeps Notion as single source of truth instead of a local JSON file alongside it.
**Start here:** Use `notion.pages.update()` to set a "Committed" status on each confirmed item's page ID (stored in pending-checkin.json).
**Depends on:** Notion SDK v5 page update API, confirmed-priorities flow.
**Effort:** M

---

## P3 — Backlog

### Log rotation for LaunchAgent logs
**What:** Add a weekly cron or LaunchAgent that truncates/rotates `dex-slack-bot.log` and `dex-slack-eod.log`.
**Why:** Logs at `/Users/tomgreen/Library/Logs/dex-slack-*.log` grow unboundedly. At ~50 lines/day, takes months to matter.
**Start here:** Create a `com.dex.log-rotate.plist` LaunchAgent that runs weekly and truncates logs over 10K lines.
**Depends on:** Nothing.
**Effort:** S
