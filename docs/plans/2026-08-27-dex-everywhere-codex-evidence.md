# Dex Everywhere — Codex evidence (unreleased)

**Date:** 29 August 2026  
**Programme state:** unreleased; do not merge  
**Live successor:** draft PR 620, branch `cursor/dex-everywhere-codex-first-c346`. Do not push to leftover PR 619 / `cursor/dex-everywhere-phase-1a-c346`.  
**Sequence:** Copilot CLI is written and not opened. Codex, Cowork, Pi, and BB stay green. ChatGPT Work vault-folder grant is the only leftover that still needs Dave on a real desktop. Do not invent that grant. Programme stays unreleased.

## What “Codex done” means

Dex works in **Codex CLI and Codex desktop**. The Codex editor add-on does not load this plugin; that limit is recorded in the Codex host profile and is intentional.

This file records proof so far. Ubuntu in Cursor Cloud is not a Codex desktop or Cowork desktop UI journey. Native Mac and Windows proof is the GitHub jobs named below.

## Exact head

Branch `cursor/dex-everywhere-codex-first-c346`. Confirm the exact SHA with `git rev-parse HEAD` after pull. The evidence body first landed in `8ea5cb310a361e2269ecdaa850b542fafd15aa06`.

- Isolated branch: `cursor/dex-everywhere-codex-first-c346`
- Draft PR: https://github.com/davekilleen/Dex/pull/620
- Dead leftover, do not push: https://github.com/davekilleen/Dex/pull/619 (`cursor/dex-everywhere-phase-1a-c346`)
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

Core proof on `616618e45fbe26adc71cc7c3ce5d3bceb090af67` after Cowork CI was green:

- Dex CI: https://github.com/davekilleen/Dex/actions/runs/33106291761 — **success**
  - quality
  - tests 1–3 and test-results
  - native macOS portable runtime
  - native Windows portable runtime
  - Lens catalog dry-run
- Twelve-journey Mac fleet canary: https://github.com/davekilleen/Dex/actions/runs/33106291751 — **success**
- Detects Pi from `PI_CLI` / `PI_CODING_AGENT` and a `/.pi/` path
- Detects BB from `BB_HARNESS` / `BB_RUNNER` and a `/.bb/` path
- Doctor names Pi’s missing built-in tool door and BB’s Mac-only unreleased limit
- Local pinned Pi checkout `5bf33ad7` matched its source-byte test on this Ubuntu runner. GitHub CI still skips that test unless a checkout is present there
- The BB plugin at `e1d704fd` stayed private and unreleased. `npm install` on Linux refused the Mac-only package. That is the named limit, not a defect
- Setup preview now carries those same named limits, and the setup script tells Dex to say them in plain words

A later commit that records this proof is a new head and must earn its own green Dex CI. The fleet canary on `616618e4` keeps running and is not cancelled by a later push.

GitHub did not schedule Dex CI on `42f2ea30` or `6b8cc267` at the time those heads landed. This note records the green fleet on `616618e4` and is a new head that must earn its own Dex CI.

## ChatGPT Work desktop — still being proven

A person cannot open Dex in ChatGPT Work yet. Desktop only. This does not claim ChatGPT in the browser.

Earlier CI and Mac fleet on `498740f2205046243f561bac1ee5a19d86f5ef04` stayed green. That is not a person-can-do-this win. Detection tests and fleet canary do not prove that a person installed the local plugin or opened a local vault.

### What is proven

- ChatGPT Work desktop uses the same plugin package as Codex. Public plugin docs require `.codex-plugin/plugin.json`, and this package already has that layout plus `skills/`, `.codex-mcp.json`, and `hooks/codex.json`.
- The repo marketplace at `.agents/plugins/marketplace.json` lists Dex at `./packages/dex-agent-plugin` under **Dex (unreleased local build)**.
- The adapter now names the real local-plugin + local-vault steps: copy the reviewed package to `~/.codex/plugins/dex`, list it from `~/.agents/plugins/marketplace.json` with `source.path` `./.codex/plugins/dex` (relative to the home marketplace root, not the `.agents/plugins` folder), restart ChatGPT desktop, install Dex, start Work locally, and grant the Dex vault folder.
- Doctor and setup preview name three limits: a person still has to do that desktop journey; ChatGPT on the web needs a separate public HTTPS door; a shared plugin cache on disk is not ChatGPT Work proof.
- Detection still treats `CHATGPT_WORK` / `OPENAI_WORK` / `CHATGPT_WORK_COMPANION` and an explicit `/.chatgpt-work/` marker as ChatGPT Work. A `/.codex/` path still selects Codex, not ChatGPT Work.

### What is still missing

- **Only leftover that still needs Dave:** grant the Dex vault folder on a real desktop after installing the local plugin. This Ubuntu Cloud runner cannot do that and will not invent that grant. Do not treat a later green Dex CI or Mac fleet run as that proof.
- No recorded live ChatGPT Work session exists. Do not invent one.
- ChatGPT on the web stays later. The product lab has no Dex Everywhere programme record; do not guess one there.

A later commit that records this honesty is a new head and must earn its own green Dex CI if CI is run. CI green is still not the desktop journey.

## Copilot CLI — started as the next host story

Copilot CLI in the terminal only. This does not claim Microsoft 365 Copilot, Word, Teams, Outlook, or Windows Copilot. Ubuntu Cloud is not a person opening this terminal. No recorded live session exists. Do not invent one.

Earlier CI and Mac fleet on `28bb192baf05570f9e38f84e07f92b2e78b4a973` stayed green. That freeze is not this journey. Detection tests and fleet canary do not prove that a person installed the local plugin or started the CLI from a Dex folder.

### What a person would do

1. From the Dex checkout, run `copilot plugin install ./packages/dex-agent-plugin`.
2. Confirm Dex appears in `copilot plugin list`.
3. Start the CLI from the Dex folder so the vault is the current working directory.
4. Use Dex skills and the bundled MCP tools. Do not expect automatic hook enforcement.

### What is proven

- The reviewed package is the Open Plugin Spec root: `plugin.json` with the canonical `$schema`, `skills/`, and `mcp.json` using `PLUGIN_ROOT`.
- The adapter, Doctor, setup preview, and install guide now name those exact local-plugin + Dex-folder steps.
- Hooks stay unavailable. Claude's `.mcp.json` in the same folder is not this host's contract.
- Detection still treats `COPILOT_CLI` / `GH_COPILOT` / `GITHUB_COPILOT` and a `/.copilot/` path as Copilot CLI. A cache under `~/.copilot/installed-plugins/` is still Copilot CLI detection, not a recorded live session.
- A local fixture now copies the reviewed package into the named `~/.copilot/installed-plugins/_direct/source/` cache, lists Dex from that layout, starts from a Dex-folder cwd, and launches the installed `mcp.json` (`${PLUGIN_ROOT}`, `--stdio`) without a `copilot` binary. `boot_today` reads; `check_safety_gate` refuses `rm -rf /`. This fixture is not a recorded live session. Doctor, setup, and limitations still say a person has to run the real command.

### What still needs a person

- **Named limit:** a human must run `copilot plugin install` on a real machine and start the CLI from the Dex folder. This Ubuntu Cloud runner cannot do that. A `_direct` fixture is not that journey. Do not treat a later green Dex CI or Mac fleet run as that proof.
- No recorded live Copilot CLI session exists. Do not invent one.

A later commit that records this honesty is a new head and must earn its own green Dex CI if CI is run. CI green is still not the terminal journey.

## Deliberately not started

- A live ChatGPT Work desktop install or recorded vault grant on a real Mac or Windows machine
- Live BB install, or publishing `dex-bb-plugin`
- ChatGPT in the browser, or a public door for a local Dex folder
- Live GitHub Copilot CLI install on this Ubuntu runner
- Microsoft 365 Copilot, Word, Teams, Outlook, or Windows Copilot
- Capability-exchange privacy repairs in Dex Lens
- Final genuine Fable reviews (wait until heads are frozen and native CI is green)
- Merge, publish, marketplace, user install, or release
