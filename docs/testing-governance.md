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

## Exception Labels
- `test-exception-approved`: allows source-only PRs without test changes.
- `docs-exception-approved`: allows source-only PRs without docs updates.

Every exception must include rationale in PR body and reviewer approval.

## Regression Rule
- Bug-fix PRs must include a regression test or explicit reviewer-approved exception.

## Migration Safety
- Breaking-change migrations must support dry-run + apply + rollback.
- Migration tests must cover successful apply and rollback restoration.
