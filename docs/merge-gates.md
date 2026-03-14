# Merge Gates Setup

## Required Status Check
Configure GitHub branch protection on `main` to require:
- `Dex CI / quality`

`quality` includes:
- PR governance enforcement
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
