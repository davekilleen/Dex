# D2 Updater Fix Round Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every adversarial-review finding F1–F15 without weakening brain/vault invariants I1–I8, with one red-green regression per finding and both required suites green.

**Architecture:** Make the updater's live-tree mutation boundary positive-authorized first, then harden persisted secret state, locks, and authenticated release provenance before repairing update mechanics and doctor reporting. Keep runtime metadata under `System/.dex/`, route every live worktree byte through the ownership guard, and make resume/rollback derive state from freshly authenticated release tags rather than trusting local journal/history objects.

**Tech Stack:** Dependency-free Node.js CommonJS, Python stdlib/pytest, Git CLI, Node's built-in test runner.

---

### Task 1: Positive authorization and runtime report (F11)

**Files:**
- Modify: `core/update/apply-update.cjs`
- Modify: `core/update/ownership.json`
- Modify: `.claude/skills/dex-update/SKILL.md`
- Modify: `.claude/skills/dex-rollback/SKILL.md`
- Test: `core/tests/apply-update-unit.test.cjs`
- Test: `core/tests/apply-update-integration.test.cjs`
- Test: `.claude/hooks/tests/data-safety-instructions.test.cjs`

- [ ] Add a failing unit test proving `writeWorktreeFile()` refuses a default-`vault` path such as `System/update-report.md`, permits explicit `brain`/`generated`/`runtime` internal swap paths only as required, and never treats absence from the deny list as authorization.
- [ ] Add failing integration/skill tests requiring the report at `System/.dex/update-report.md` and forbidding the old path.
- [ ] Change the guard to require `ownership.classify(relative)` in `{brain, generated, seed}` for live destinations, with a separate narrowly scoped internal-runtime path policy for journals/staging/backups; classify `System/backups/` as runtime and move the report constant/references under `System/.dex/`.
- [ ] Run the targeted Node tests and commit `fix: require positive updater write authorization`.

### Task 2: Persistent secret exclusions and hook isolation (F3, F6)

**Files:**
- Modify: `core/migrations/v1-to-v2-brain-vault-split.cjs`
- Modify: `core/update/ownership.cjs`
- Modify: `core/update/ownership.json`
- Modify: `core/update/apply-update.cjs`
- Modify: `.claude/hooks/vault-autocommit.cjs`
- Modify: `core/doctor.py`
- Test: `core/tests/brain-vault-migrator-integration.test.cjs`
- Test: `core/tests/apply-update-unit.test.cjs`
- Test: `.claude/hooks/tests/vault-autocommit.test.cjs`

- [ ] Add failing migration tests proving content-detected secret paths are persisted in `System/.dex/held-back-paths.json` and `.git/info/exclude`, and update backups are excluded.
- [ ] Add failing hook tests proving held-back/secret paths and secret-shaped staged content are unstaged and reported, and a hostile `post-commit`/configured hooks path cannot run.
- [ ] Persist normalized held-back paths, merge them into machine excludes during migration/update, replace `git add -A` with candidate filtering plus staged-content scanning, and run every Git command with `/dev/null` hooks and isolated global/system configuration.
- [ ] Correct doctor's “never sends data” wording to the operational guarantee that the hook does not push and disables Git hooks/config.
- [ ] Run targeted migration/hook tests and commit `fix: keep secrets and hooks out of vault commits`.

### Task 3: Token-owned stale-lock recovery (F2)

**Files:**
- Modify: `core/update/apply-update.cjs`
- Modify: `core/migrations/v1-to-v2-brain-vault-split.cjs`
- Test: `core/tests/apply-update-unit.test.cjs`
- Test: `core/tests/brain-vault-migrator-unit.test.cjs`

- [ ] Add failing tests that replace a stale lock between inspection/removal or before release and prove neither implementation unlinks a different owner's lock.
- [ ] Implement `openSync('wx')` retry acquisition with random owner tokens; stale removal must re-read the same token/inode immediately before unlink, and release must compare the on-disk token with its own.
- [ ] Run targeted lock tests and commit `fix: make updater locks owner safe`.

### Task 4: Authenticated targets, metadata, resume, and rollback (F7, F8, F14)

**Files:**
- Modify: `core/update/apply-update.cjs`
- Modify: `.claude/skills/dex-update/SKILL.md`
- Test: `core/tests/apply-update-unit.test.cjs`
- Test: `core/tests/apply-update-integration.test.cjs`
- Test: `.claude/hooks/tests/data-safety-instructions.test.cjs`

- [ ] Add failing tests rejecting a full OID not peeled from an official `dist-v*` tag, rejecting tampered resume/rollback journals/history, and requiring an exact-tag refetch before mutation.
- [ ] Add a failing `--check` test requiring one machine-readable record with tag, peeled OID, manifest hash, `breaking=0|1`, and a safe release-note summary.
- [ ] Enumerate official `dist-v*` tags including annotated-tag peeling, map OIDs only to authenticated tags, persist `{tag, oid, manifestHash}` attestations, validate journal arrays/scalars, refetch exact tags on resume/rollback, and rederive target inventories solely from verified staging.
- [ ] Update the skill to parse the authenticated metadata and use `breaking` for its confirmation gate.
- [ ] Run targeted updater/skill tests and commit `fix: authenticate every updater release transition`.

### Task 5: Safe update mechanics (F1, F4, F5, F12, F13, F15)

**Files:**
- Modify: `core/update/apply-update.cjs`
- Modify: `core/migrations/v1-to-v2-brain-vault-split.cjs`
- Test: `core/tests/apply-update-unit.test.cjs`
- Test: `core/tests/apply-update-integration.test.cjs`
- Test: `core/tests/brain-vault-migrator-unit.test.cjs`

- [ ] Add failing tests proving target `core/paths.py` is never executed and trusted updater-generated `core/paths.json` bytes pass through the guarded writer.
- [ ] Add failing journey tests for recreating exactly one absent canonical seed, backing up mode-only drift, backing up a modified dropped brain file, keeping modified dropped files live, and preserving `.mcp.json` bytes across rollback.
- [ ] Add failing composition tests for custom instructions without a trailing newline in both migrator and updater flows.
- [ ] Generate paths JSON in trusted Node code, add an absent-only exact seed allowance, compare Git tree mode plus bytes, back up the previous/target inventory union, skip MCP sync in rollback, and normalize only the rendered CLAUDE separator.
- [ ] Run targeted updater/migrator tests and commit `fix: preserve user changes across update mechanics`.

### Task 6: Doctor identity and repaired safety coverage (F9, F10)

**Files:**
- Modify: `core/doctor.py`
- Modify: `core/tests/test_update_rollback_journey.py`
- Modify: `core/tests/test_doctor.py`
- Modify: `.claude/hooks/tests/data-safety-instructions.test.cjs`

- [ ] Replace the obsolete legacy rollback-shell assertion with v2 updater/rollback behavioral assertions.
- [ ] Restore exact manual/ZIP owned-set assertions for `06-Resources/`, both session stores, `CLAUDE-custom.md`, custom skill/MCP directories, and secret files.
- [ ] Add failing doctor tests for disagreement among `refs/dex/installed`, the brain marker, topology sentinel, and official origin.
- [ ] Make doctor require all three installed OIDs to agree and require both configured/effective origin URLs to be official before declaring brain health.
- [ ] Run targeted Node/Python tests and commit `fix: verify installed brain identity in doctor`.

### Task 7: Full verification and invariant audit

**Files:**
- Review: `docs/plans/2026-07-12-brain-vault-split-plan.md`
- Review: all files changed above

- [ ] Run `node --test core/tests/*.test.cjs .claude/hooks/tests/*.test.cjs` and require exit 0.
- [ ] Run `.venv/bin/python -m pytest core/tests/ core/mcp/tests/ core/migrations/tests/ -q` and require exit 0.
- [ ] Inspect `git diff --check`, `git status --short`, and the commit list; map F1–F15 and I1–I8 to code/tests with no gaps.
- [ ] Commit any final test-only corrections separately and report the exact verification evidence and deliberate deviations (if any).
