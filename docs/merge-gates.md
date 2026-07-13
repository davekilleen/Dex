# Merge Gates Setup

## Required Status Check
Configure GitHub branch protection on `main` to require:
- `Dex CI / quality`
- `Dex CI / pr-report`

`quality` includes:
- PR governance enforcement
- blocking PII / personal-config gate over added PR lines
- diff-aware test gate
- path-contract usage gate (changed files)
- docs drift gate
- hook harness tests
- linting
- `core/tests` + `core/mcp/tests` + `core/migrations/tests`
- coverage thresholds
- security gate
- large-vault performance budget
- distribution/path safety checks

The PII gate compares the pull request with its merge base and inspects only added
lines. It blocks real email addresses, filled-in tracked identity/config files, and
personal vault content before it can merge. Test fixtures may use fake email addresses,
but fixture paths are still checked for real-config-shaped additions.

`pr-report` maps changed paths to plain-English product areas, the user journeys they
feed, and the gates that apply. Its sticky `<!-- dex-pr-report -->` comment is updated on
each run. GitHub gives fork pull requests a read-only token even when the workflow asks
for `pull-requests: write`; in that case the job writes the identical report to its job
summary and exits successfully instead of using the less-safe `pull_request_target`
event.

## Branch Protection Settings
- Require a pull request before merging.
- Require approvals.
- Require conversation resolution.
- Require status checks to pass before merging.
- Restrict bypass to administrators only.

## Optional API Setup
Use `scripts/configure-branch-protection.sh` with a GitHub token that can administer repository settings.

## Active Stack Execution
For the current staged rollout and closeout sequence, use:
- `docs/testing-hardening-merge-runbook.md`
