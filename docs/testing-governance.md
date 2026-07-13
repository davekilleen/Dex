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
- PII / personal-config gate passes over added pull-request lines.
- Plain-English PR report identifies touched product areas, connected user journeys, and applicable gates.
- Diff-aware test gate passes or approved exception label exists.
- Path-contract usage gate passes for changed files.
- Documentation drift gate passes or approved exception label exists.
- Lint, test suites, and coverage thresholds pass.
- Hook harness tests pass.
- Security gate passes (secret leakage detection).
- Large-vault performance budget passes.

The PII gate is merge-base-aware and diff-scoped. Fake email addresses under
`core/tests/fixtures/**` are allowed, but tracked personal-config shapes remain blocked
there as they are everywhere else. Approved placeholders outside that directory must be
documented narrowly in `scripts/pii-allowlist.txt`.

The PR report runs only for `pull_request`, never `pull_request_target`. It requests
comment permission, upserts one marked comment when GitHub grants it, and always writes
the same report to the job summary so fork token restrictions cannot turn reporting into
a failed contribution.

Ordinary pull-request tests run with `-m "not fuzz"`. Fast property tests remain in that
suite; deliberately slow or large cases use `@pytest.mark.fuzz` and run in
`nightly-quality.yml`.

Release builds also run the shipped smoke runner against an isolated vault. Any
`BROKEN` journey blocks the release; `UNKNOWN` remains visible without being treated as
a pass.

Current coverage thresholds (ratchet baseline):
- Total coverage >= 15%
- Touched source files >= 10%

## Public Release Health Page

After the main-branch release build and release-branch push both succeed, CI publishes
`health.html` through the repository's GitHub Pages site. It is labelled **Last successful
release build** and follows these honesty rules:

- The page describes one exact package version, source commit, and generated release commit.
- Its gate matrix distinguishes `passed`, `skipped`, `not-applicable`, and `unknown` evidence.
- Gates that run only on pull requests are labelled `not run on release build (PR-only)`;
  they are never presented as passed by a main-push release.
- Missing JUnit, coverage, provenance, or changelog input stays `unknown` rather than becoming
  an inferred pass.
- Publication happens only after the release branch is built and pushed successfully. If a
  later build fails, the previous page remains available and still describes only its own
  last green release, not current `HEAD`.

Repository maintainers can enable publication once under **Settings → Pages → GitHub
Actions**. Until then, the health deployment steps skip cleanly after the release build.

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
- `mcp_startup` -> handshake pristine Dex-owned local Python servers plus exact user-blessed
  custom local Python snapshots; validate all other entries structurally without executing
  them
- `skills` -> validate shipped and `-custom` skill frontmatter
- `hooks` -> check presence, executable bits, and syntax without running hooks

The runner has a 30-second global budget, writes only to temporary copies, and executes no
user-supplied command unless the user explicitly records the exact custom local Python name,
vault-relative file, and SHA-256 in `System/trusted-mcps.yaml`. Python-level network access
is blocked; blessed/custom code you approve runs with your user permissions and could start
a subprocess that bypasses that Python monkeypatch. The runner redacts secret-like config
values before child journeys and ignores each trusted entry's configured `env`. Dex-owned
executable task and MCP code is loaded only from a read-only snapshot of the installed
release. A trusted user script is opened component-by-component without following links,
hashed and copied from each chunk in one pass, and only the private copy is executed. At
launch, that private file is opened without following links, re-hashed against its
content-addressed filename, and executed from the verified bytes. If any identity check or
release verification fails, the affected journey is `UNKNOWN` instead of falling back to
live code.

The one-off token prevents the automatic/recurring health checks from ever launching a
one-off custom server and makes each explicit approval single-use. It is not protection
against another program running as you, which could run your code directly regardless.

### Nightly smoke ledger and attribution

The macOS Launch Agent installed by `.scripts/install-smoke-automation.sh` runs the five
smoke journeys every night at 03:15. Successful worker completion updates the heartbeat
at `.scripts/logs/smoke-nightly.log`; `/dex-doctor` treats a heartbeat older than 26 hours
as stale.

Passing `--ledger` leaves the complete latest report at
`System/.smoke-last-run.json` and appends a versioned entry to
`System/.dex/smoke-history.jsonl`. History is capped at 120 runs and both files are
replaced atomically, so readers never observe partial JSON. Plain `--json` runs remain
read-only.

The quick doctor's `smoke.history` check compares the last passing entry with the first
broken entry after it. Attribution reports only facts inside that window: modification
times for profile, pillar, integration, MCP, and custom-skill files, plus a Dex version
change. When no listed fact changed, the doctor says so and points to the deep check; it
does not guess at a cause.

## Testing Doctor Inventory

The quick doctor adds three always-visible checks:

- `customizations.skills` validates every skill and identifies user-owned `-custom`
  failures separately from shipped failures.
- `customizations.mcp` validates MCP structure, unresolved placeholders, custom Python
  syntax, and the same registry name/path/hash state without launching custom commands.
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
