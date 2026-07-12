# Testing Governance

## Purpose
Dex uses repository-enforced quality gates so unsafe changes cannot merge.

## Current Rollout
- Active stack runbook: `docs/testing-hardening-merge-runbook.md`

## Repository Is Source Of Truth
- Decisions belong in `System/PRDs/` or `docs/`.
- Delivery work must link issue -> PR -> docs.
- If behavior changes, documentation must be updated or explicitly exempted.

## Required Merge Gates
- PR governance checklist complete.
- Diff-aware test gate passes or approved exception label exists.
- Path-contract usage gate passes for changed files.
- Documentation drift gate passes or approved exception label exists.
- Lint, test suites, and coverage thresholds pass.
- Hook harness tests pass.
- Security gate passes (secret leakage detection).
- Large-vault performance budget passes.

Release builds also run the shipped smoke runner against an isolated vault. Any
`BROKEN` journey blocks the release; `UNKNOWN` remains visible without being treated as
a pass.

Current coverage thresholds (ratchet baseline):
- Total coverage >= 15%
- Touched source files >= 10%

## Golden User Journeys
These journeys are release-critical and cannot regress:
- onboarding -> profile/pillars creation
- task creation/update -> task index integrity
- meeting sync -> meeting notes/intel writeback
- daily plan generation -> task/goal references
- week review -> cross-file rollups without data loss

## Shipped Smoke Layer

`python core/utils/smoke.py --json` exercises the installed product in fresh subprocesses
with a temporary vault and home directory. Its release journeys are:

- `configs` -> parse and minimally validate profile, pillars, and integration YAML
- `task_lifecycle` -> create and update a task, preserving `03-Tasks/Tasks.md`
- `mcp_startup` -> handshake only pristine Dex-owned local Python servers; validate all
  other entries structurally without executing them
- `skills` -> validate shipped and `-custom` skill frontmatter
- `hooks` -> check presence, executable bits, and syntax without running hooks

The runner has a 30-second global budget, does not contact the network, writes only to
temporary copies, and never executes user-supplied commands. It redacts secret-like config
values before child journeys; executable task and MCP code is loaded only from a read-only
snapshot of the installed release. If that release cannot be verified, the affected
journey is `UNKNOWN` instead of falling back to live code.

## Testing Doctor Inventory

The quick doctor adds three always-visible checks:

- `customizations.skills` validates every skill and identifies user-owned `-custom`
  failures separately from shipped failures.
- `customizations.mcp` validates MCP structure, unresolved placeholders, and custom
  Python syntax without launching custom commands.
- `core.drift` compares shipped files with the installed release while excluding
  sanctioned customization surfaces. Drift is `UNKNOWN`, never automatically broken.

The deep doctor adds `smoke.journeys`, which runs the shipped smoke layer and preserves
each journey's `OK`, `OFF`, `BROKEN`, or `UNKNOWN` result in the report.

## Exception Labels
- `test-exception-approved`: allows source-only PRs without test changes.
- `docs-exception-approved`: allows source-only PRs without docs updates.

Every exception must include rationale in PR body and reviewer approval.

## Regression Rule
- Bug-fix PRs must include a regression test or explicit reviewer-approved exception.

## Migration Safety
- Breaking-change migrations must support dry-run + apply + rollback.
- Migration tests must cover successful apply and rollback restoration.
