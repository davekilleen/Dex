# D2 Updater, Doctor, and Vault Auto-Commit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the post-split updater/rollback engine, thin update skills, topology-aware health checks, isolated smoke proof, and default-off vault auto-commit without weakening invariants I1-I8.

**Architecture:** A dependency-free Node updater owns all post-split brain mutations through an fsync'd journal, hard ownership checks, staged Git extraction, backup-first replacement, and installed-history refs. Claude skills become narration/orchestration only; doctor reports topology as feature-status checks; smoke proves the updater inside a system-temp fixture; a standalone SessionEnd hook commits only the vault repo when explicitly enabled.

**Tech Stack:** Node.js stdlib/CommonJS, Python stdlib plus the repository's existing YAML support, shell hooks, Git CLI, `node:test`, pytest through the repository venv.

---

### Task 1: Journaled updater and rollback engine

**Files:**
- Create: `core/update/apply-update.cjs`
- Create: `core/tests/apply-update-unit.test.cjs`
- Create: `core/tests/apply-update-integration.test.cjs`
- Reuse: `core/update/ownership.cjs`
- Reuse: `core/migrations/v1-to-v2-brain-vault-split.cjs`

- [ ] Write unit tests for official-origin authentication, manifest validation/hash, topology refusal, denied-path checks, and status/check output; run them and confirm they fail because the updater is absent.
- [ ] Implement stdlib helpers for safe Git invocation, fsync'd atomic files/directories, safe mutation roots, process lock, journal read/write, staging extraction, blob reads, history/report persistence, and startup reconciliation.
- [ ] Write the aged-fixture integration test that migrates, fabricates a newer official release in `os.tmpdir()`, changes/adds/drops brain files, edits a brain file and seed/PARA files, then checks backup-first apply, safe prune, generated files, installed ref/history, rollback, and kill/resume; run it and confirm the first missing behavior.
- [ ] Implement `--check`, `--apply [--target]`, `--resume`, `--rollback [--to]`, and `--status` as idempotent journal phases: topology/migration, authenticated fetch, staged extract/hash, backup, per-file swap/prune, seeds, CLAUDE composition, paths/excludes/MCP, ref/history, dependency signal.
- [ ] Before every worktree write, call `ownership.isDenied(relative, root)` and refuse denied or symlink-parent paths. Journal and fsync before each mutation; persist per-file completion so resume never relies on ambient Git state.
- [ ] Run updater tests plus `node --test core/tests/*.test.cjs`; commit the updater and tests.

### Task 2: Thin update/rollback skills and session-start wiring

**Files:**
- Modify: `.claude/skills/dex-update/SKILL.md`
- Modify: `.claude/skills/dex-rollback/SKILL.md`
- Modify: `.claude/settings.json`
- Modify: `.claude/hooks/session-start.sh`
- Create/modify: hook/settings contract tests under `core/tests/` or `.claude/hooks/tests/`

- [ ] Write failing contract tests for removal of SessionStart `git pull`, migration-pending additional context, updater-only post-split recovery, BREAKING confirmation, ZIP/manual guidance, and rollback routing.
- [ ] Replace both large legacy skills with short topology-aware orchestration documents using updater/migrator recovery only, plain-English confirmation/narration, dependency install signal handling, doctor/smoke, and one-cycle restore.
- [ ] Add the cheap session-start topology check and remove only the pull hook from settings.
- [ ] Run the focused Node contract tests and commit.

### Task 3: Topology-aware doctor and isolated update smoke journey

**Files:**
- Modify: `core/utils/doctor.py`
- Modify: `core/utils/smoke.py`
- Modify: `core/tests/test_doctor.py`
- Modify: `core/tests/test_smoke.py`

- [ ] Write failing doctor tests for `vault.git`, `brain.git`, `schema.match`, `topology.migration-pending`, archive expiry messaging, and post-split `core.drift` against `refs/dex/installed` while retaining pre-split behavior.
- [ ] Add feature-status-compliant probes with `OK/OFF/BROKEN/UNKNOWN` verdicts and actionable user messages.
- [ ] Write a failing smoke test for an `update_boundary` journey built entirely under the safe system temp parent and with no network access.
- [ ] Add preparation and execution for the synthetic updater fixture; assert a brain path changes while denied/PARA sentinel bytes stay identical.
- [ ] Run focused Python tests through the available project venv (or report the exact unavailable runner), then commit.

### Task 4: Default-off vault auto-commit

**Files:**
- Create: `.claude/hooks/vault-autocommit.cjs`
- Create: `.claude/hooks/tests/vault-autocommit.test.cjs`
- Modify: `.claude/settings.json`
- Modify: `System/user-profile.example.yaml`
- Modify: `System/user-profile-template.yaml`
- Modify: migration report text in `core/migrations/v1-to-v2-brain-vault-split.cjs`

- [ ] Write failing hook tests for default-off, enabled commit, clean tree, local identity fallback, no push/remotes mutation, merge/rebase skip, migration-lock skip, and silent feature-status degradation.
- [ ] Implement a dependency-free YAML scalar reader and guarded `git -c commit.gpgsign=false -C <vault> add -A` / commit flow with local-only identity fallback.
- [ ] Wire the hook into SessionEnd after the existing hook; document `vault.auto_commit: false` and the one-line enablement in the migration report.
- [ ] Run hook tests and migrator tests; commit.

### Task 5: Full verification and invariant audit

- [ ] Run `node --test core/tests/*.test.cjs` and `node --test .claude/hooks/tests/*.test.cjs`.
- [ ] Run focused doctor/smoke pytest commands with `python3` through the project venv if present.
- [ ] Re-read invariants I1-I8 and inspect every updater worktree write for a directly preceding `ownership.isDenied` guard, every mutation for pre-journaling, all Git capture for `core.excludesFile=/dev/null`, and all fixture paths for `os.tmpdir()` isolation.
- [ ] Inspect `git status`, `git diff --check`, and the logical commit list; report exact verification evidence and any deliberate deviation.
