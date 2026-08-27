# Dex Everywhere — Codex evidence (unreleased)

**Date:** 27 August 2026  
**Programme state:** unreleased; do not merge  
**Sequence:** Codex exact-head native CI is green. Claude Cowork exact-head CI is green. Pi and BB Core proof is in progress.

## What “Codex done” means

Dex works in **Codex CLI and Codex desktop**. The Codex editor add-on does not load this plugin; that limit is recorded in the Codex host profile and is intentional.

This file records proof so far. Ubuntu in Cursor Cloud is not a Codex desktop or Cowork desktop UI journey. Native Mac and Windows proof is the GitHub jobs named below.

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

Proven on `cbfc81692809dd78ce74779bc8291514b9fdfdf6`:

- Dex CI: https://github.com/davekilleen/Dex/actions/runs/33098144565 — **success**
  - quality
  - tests 1–3 and test-results
  - native macOS portable runtime
  - native Windows portable runtime
  - Lens catalog dry-run
- Twelve-journey Mac fleet canary: https://github.com/davekilleen/Dex/actions/runs/33098144559 — **success**
- Earlier canary on the pre-fix SHA `76ab765a`: https://github.com/davekilleen/Dex/actions/runs/33097749727 — success
- Formal historic-fleet-darwin job stays skipped on pull requests (workflow_dispatch only)

The first Dex CI run on this work, merge-only SHA `99632651`, failed: https://github.com/davekilleen/Dex/actions/runs/33092456685. Those failures are fixed on this branch.

A later commit that records this proof or starts Cowork is a new head and must earn its own green run.

## Claude Cowork (started after Codex CI was green)

Proven on `ff2a24ba81d05beacb3e4bfe936d0d57a21908b7` after Codex CI was green:

- Dex CI: https://github.com/davekilleen/Dex/actions/runs/33102943819 — **success**
- Twelve-journey Mac fleet canary: https://github.com/davekilleen/Dex/actions/runs/33102943828 — **success**
- Local detection + Doctor public-endpoint tests: 9 passed, 1 skipped

Ubuntu still cannot click Cowork’s desktop folder permission or prove a live public connector. Those stay named limits, not silent gaps.

## Pi and BB (started after Cowork CI was green)

Core proof only. This does not claim a live Pi checkout or a live BB install.

- Detects Pi from `PI_CLI` / `PI_CODING_AGENT` and a `/.pi/` path
- Detects BB from `BB_HARNESS` / `BB_RUNNER` and a `/.bb/` path
- Doctor names Pi’s missing built-in MCP door and BB’s macOS-only unreleased limit
- The Pi source-byte check stays skipped unless a pinned checkout is present. `DEX_PI_REQUIRE_CONFORMANCE=1` still fails closed
- The BB plugin stays private and unreleased. WSL2 and Windows stay deferred

This later-host commit must earn its own green exact-head Dex CI and fleet canary.

## Deliberately not started

- Live Pi checkout byte-match, live BB install, or publishing `dex-bb-plugin`
- Copilot CLI and other remaining later hosts
- Capability-exchange privacy repairs in Dex Lens
- Final genuine Fable reviews (wait until heads are frozen and native CI is green)
- Merge, publish, marketplace, user install, or release
