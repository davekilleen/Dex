# Dex Automation (Windows Task Scheduler)

Scheduled, read-only data refresh for the [[2026-H2_Sales_Plan]]. This is the Windows
replacement for the macOS `launchd` automation in `.scripts/customer-intel/`.

## What gets scheduled

| Task | Schedule | Job |
|------|----------|-----|
| `Dex-Weekly-SF-Sync` | Mondays 06:00 | `sf-pull-sync.py` — refresh local Salesforce cache |
| `Dex-Weekly-Lease-Alert` | Mondays 06:30 | `generate-report.py --days 7 --months 6` — short lease-expiry alert |
| `Dex-Monthly-Intel-Report` | 1st @ 08:00 | `generate-report.py` — full EDA report → `Inbox/Reports/` |
| `Dex-Daily-Case-Alert` | Daily 07:15 | `case-alert.py` — new/status-or-priority-changed open Cases → toast + `Inbox/Alerts/` |

Tasks run as the current user, **only while logged on** (no stored password, no
elevation) — the Windows equivalent of launchd's `Aqua` session guard.

## Guardrail

Every scheduled job **only refreshes data and generates reports/alerts.** Nothing here
sends email or writes to Salesforce. Outreach stays draft-and-approve
(`/outreach-drafts-custom` → Outlook Drafts); activity logging stays manual
(`/pipeline-review` → `sf-activity-sync.py`).

## Case Alert details

`Dex-Daily-Case-Alert` queries open Cases on your owned accounts and diffs them
against yesterday's snapshot (`.scripts/salesforce-data/case_snapshot.json`). It only
alerts on:
- A **brand-new** case
- An existing case whose **Status or Priority changed** (e.g. New → Escalated, Medium → High)

Minor edits (description tweaks, etc.) are ignored to keep the signal high. On a hit,
it writes `Inbox/Alerts/case-alert-YYYY-MM-DD.md` and pops a Windows balloon-tip
notification (no extra module required — uses `System.Windows.Forms.NotifyIcon`, same
session-only constraint as the other jobs). The next `/daily-plan` run also surfaces
that day's alert file if present.

The **first time it ever runs**, there's no prior snapshot to diff against — it just
records a baseline silently (no false "everything is new" alert).

## Install / manage

```powershell
# Install or update the three tasks (idempotent)
pwsh .scripts/automation/register-automation.ps1

# See what's registered + next/last run times
pwsh .scripts/automation/register-automation.ps1 -Status

# Preview the task XML without registering
pwsh .scripts/automation/register-automation.ps1 -WhatIf

# Remove everything
pwsh .scripts/automation/unregister-automation.ps1
```

## Run a job by hand (test)

```powershell
. .scripts/automation/run-sf-sync.ps1                 # refresh cache now
. .scripts/automation/run-customer-intel-report.ps1   # generate report now
. .scripts/automation/run-case-alert.ps1               # check for new/updated cases now
```

Logs append to `.scripts/logs/sf-sync.log`, `.scripts/logs/customer-intel.log`, and
`.scripts/logs/case-alert.log`.

## How it works

`_env.ps1` (dot-sourced by the wrappers) resolves the vault root, loads
`SF_CLIENT_ID` / `SF_CLIENT_SECRET` / `SF_OWNER_ID` from `.mcp.json`, sets `VAULT_PATH`,
and finds Python — so the headless Python scripts run identically whether launched by
Task Scheduler or by hand. Requires Salesforce to have been authenticated once
(`sf_authenticate` via the Salesforce MCP) so `~/.claude/sf_tokens.json` exists.
