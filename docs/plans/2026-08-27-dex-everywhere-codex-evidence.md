# Dex Everywhere — Codex evidence (unreleased)

**Date:** 27 August 2026  
**Programme state:** unreleased; do not merge  
**Sequence:** Codex first. Claude Cowork and later hosts have not started.

## What “Codex done” means

Dex works in **Codex CLI and Codex desktop**. The Codex editor add-on does not load this plugin; that limit is recorded in the Codex host profile and is intentional.

This file records proof so far. Ubuntu in Cursor Cloud is not macOS or Windows proof.

## Exact head

Branch `cursor/dex-everywhere-codex-first-c346`. Confirm the exact SHA with `git rev-parse HEAD` after pull. The evidence body first landed in `8ea5cb310a361e2269ecdaa850b542fafd15aa06`.

- Isolated branch: `cursor/dex-everywhere-codex-first-c346`
- Draft PR: https://github.com/davekilleen/Dex/pull/620
- Related parked draft: https://github.com/davekilleen/Dex/pull/619 (same work, older branch name)
- Older Everywhere draft, left open: https://github.com/davekilleen/Dex/pull/594
- Merged public main through **v1.97.3** (`2599ebe1`) with a normal merge, not a rebase

## Local Codex / Core proof (Ubuntu runner)

Isolated interpreter: `/tmp/dex-everywhere-phase1a/venv/bin/python`  
Private temp: `/tmp/dex-everywhere-phase1a/tmp`

After merging current main and regenerating the Lens preview:

| Check | Result |
| --- | --- |
| Codex + Doctor + keep-both + Lens + provision focused pytest | **448 passed, 1 skipped** |
| Portability manifest `--check` | current |
| Harness registry `--check` | current (11 files) |
| `.agents/skills` `--check` | current (270 files) |
| Portable plugin `--check` | current (322 files) |
| Architecture inventory drift gate | current |
| Ruff on touched harness/Lens/feedback tests | passed |

Earlier on the pre-v1.97.3 head (still this branch):

| Check | Result |
| --- | --- |
| Codex golden journeys + onboarding receipt + portability + safety | 36 passed, 1 skipped |
| Doctor / detection / plugin | 43 passed, 1 skipped |
| `npm run test:hooks` | 221 passed |
| `npm run test:scripts` | 168 passed |
| `npm run test:integrations` | 224 passed, 1 skipped |
| Connections contract | passed |
| Portable contract | 2084 paths |
| PII + founder-content | passed |

Codex profile truth checked in tests:

- Detects Codex
- Hooks: native / guided (user must trust them)
- Editor add-on limitation present
- Onboarding writes a durable receipt
- Doctor reports host truth from that receipt

## Environment-only exclusions (not product defects)

- This VM’s Git config rewrites GitHub URLs with an embedded token. Historic topology tests that require the official `https://github.com/davekilleen/Dex.git` remote pass when run with `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null`. The official-history check must not accept tokenized URLs.
- Trusted Node for some historic tests is not in the default PATH; `/exec-daemon/node` is present. A local `/usr/local/bin/node` symlink was used only on this runner.
- `python3-venv` had to be installed on this runner before `python3 -m venv` worked.

## Exact-head GitHub CI

**Not yet proven on this head.**

Required for Codex acceptance:

- Dex CI quality
- Dex CI test shards 1–3 and test-results
- Native macOS portable runtime job
- Native Windows portable runtime job
- Twelve-journey macOS fleet canary (`historic-fleet-darwin-pr-canary`)

What we know:

- The only Dex CI run on this work was merge-only SHA `99632651` (PR #619): https://github.com/davekilleen/Dex/actions/runs/33092456685 — **failed** for stale adapters, keep-both, safety-hook `DROP` text, Lens schema pin, catalog tool total 151 vs 146, provision preview paths, and Ruff import order. Those are fixed on this branch.
- Native portable jobs on that **old** SHA were already green. That is not this head.
- Fleet canary on that **old** SHA was green: https://github.com/davekilleen/Dex/actions/runs/33092456455
- SHA `f4a0fde6` and later had **zero** GitHub Actions check-runs. Workflow dispatch returns 403 for this token. Empty commit, close/reopen, and a second draft PR did not start Actions.
- This branch still changes `.github/workflows/ci.yml` to add the portable macOS/Windows jobs. Other PRs without workflow edits get CI on every push. That difference is the leading explanation for the silent skip.

Ubuntu results are not a substitute for those native jobs.

## Deliberately not started

- Claude Code / Cowork (Phase 1B)
- Pi, Copilot CLI, and other later hosts (Phase 1C)
- Capability-exchange privacy repairs in Dex Lens
- BB revisit
- Final genuine Fable reviews (wait until heads are frozen and native CI is green)
- Merge, publish, marketplace, user install, or release
