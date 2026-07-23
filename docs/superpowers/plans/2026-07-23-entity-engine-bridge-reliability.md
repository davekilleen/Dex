# Entity Engine Bridge Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Guarantee that deferred entity enrichment writes are either eventually applied or visibly, actionably failed—never silently discarded.

**Architecture:** Keep the pending store as the source of retry truth, but separate permanent engine rejections from transient infrastructure failures and persist exponential retry timing per operation. Re-materialize declarative mutation intents against a shared identity resolver, execute bounded CLI chunks, and reconcile the meeting lifecycle from applied, pending, and dead-letter outcomes. Surface dead letters and interpreter configuration failures through the existing feature-status vocabulary in sync, verification, and Doctor.

**Tech Stack:** Node.js CommonJS bridge and `node:test`; Python Doctor and `pytest`; canonical Python entity-engine CLI.

---

### Task 1: Failure taxonomy, backoff, and dead-letter ordering

**Files:**
- Modify: `.scripts/lib/entity-engine-client.cjs`
- Modify: `.scripts/lib/tests/entity-engine-client.test.cjs`

- [ ] **Step 1: Write failing taxonomy and timing tests**

Add tests which run more than `MAX_ATTEMPTS` interpreter-missing attempts without a dead letter, prove an immediate retry inside `next_attempt_at` does not invoke the CLI, and advance a deterministic clock through five genuine `conflict` results to prove only `permanent_attempts` reaches the terminal ledger.

- [ ] **Step 2: Run the test file and verify RED**

Run: `node --test .scripts/lib/tests/entity-engine-client.test.cjs`

Expected: the new tests fail because every failure currently increments `attempts` and no retry timestamp is enforced.

- [ ] **Step 3: Implement per-operation retry lifecycle**

Persist `permanent_attempts`, `transient_attempts`, `last_attempt_at`, and `next_attempt_at`. Select only due operations. Classify interpreter absence, process failures, signals, non-zero exits, and invalid CLI output as transient; classify valid per-operation non-applied engine results as permanent. Use exponential backoff for both classes while applying `MAX_ATTEMPTS` only to permanent rejections.

- [ ] **Step 4: Add and run the dead-letter ordering test**

Intercept the append boundary and assert the reduced pending store has already been saved before the JSONL record is appended.

Run: `node --test .scripts/lib/tests/entity-engine-client.test.cjs`

Expected: all taxonomy, backoff, and ordering tests pass.

### Task 2: Identity retargeting and bounded missing-target failure

**Files:**
- Create: `.scripts/lib/entity-identity.cjs`
- Modify: `.scripts/lib/entity-engine-client.cjs`
- Modify: `.scripts/meeting-intel/lib/entity-creation.cjs`
- Modify: `.claude/hooks/post-meeting-person-update.cjs`
- Modify: `.scripts/meeting-intel/lib/gardener.cjs`
- Modify: `.scripts/lib/tests/entity-engine-client.test.cjs`
- Modify: `.scripts/meeting-intel/__tests__/entity-creation.test.cjs`

- [ ] **Step 1: Write a failing rename/replay test**

Queue a mutation intent with a person identity, rename the target page, replay after the due time, and assert the CLI receives the new absolute path and the pending operation is cleared.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `node --test .scripts/lib/tests/entity-engine-client.test.cjs .scripts/meeting-intel/__tests__/entity-creation.test.cjs`

Expected: replay remains pinned to the missing original path.

- [ ] **Step 3: Implement the shared identity resolver**

Resolve people by normalized email first and name second; resolve companies by registrable domain first and name second. Use the same helper in entity creation and deferred mutation materialization. Persist retargeted declarative operations. Count missing-target retries separately and terminally dead-letter after the bounded limit with explicit entity path, meeting, operation type, identity, and reason.

- [ ] **Step 4: Re-run the focused tests**

Run: `node --test .scripts/lib/tests/entity-engine-client.test.cjs .scripts/meeting-intel/__tests__/entity-creation.test.cjs`

Expected: rename replay and creation/adoption lookup tests pass.

### Task 3: Chunked CLI execution

**Files:**
- Modify: `.scripts/lib/entity-engine-client.cjs`
- Modify: `.scripts/lib/tests/entity-engine-client.test.cjs`

- [ ] **Step 1: Write a failing large-batch test**

Submit more operations than the bounded chunk size, record each CLI request and its timeout/max-buffer settings, and return successful results for every chunk.

- [ ] **Step 2: Run and verify RED**

Run: `node --test .scripts/lib/tests/entity-engine-client.test.cjs`

Expected: the bridge invokes one unbounded CLI request.

- [ ] **Step 3: Implement bounded chunks with scaled limits**

Split eligible materialized entries into fixed maximum groups. Scale timeout and buffer with each group’s operation count, classify a failed group transiently, continue independent groups, and settle all outcomes once.

- [ ] **Step 4: Re-run the bridge tests**

Run: `node --test .scripts/lib/tests/entity-engine-client.test.cjs`

Expected: the large batch completes in multiple bounded requests.

### Task 4: Meeting lifecycle reconciliation and sync visibility

**Files:**
- Modify: `.scripts/meeting-intel/lib/entity-phase.cjs`
- Modify: `.scripts/meeting-intel/sync-from-granola.cjs`
- Modify: `.scripts/meeting-intel/lib/entity-creation.cjs`
- Create or modify: `.scripts/meeting-intel/__tests__/entity-phase.test.cjs`

- [ ] **Step 1: Write failing crash-recovery and terminal-failure tests**

Construct a saved processed-meeting entry with `entity_phase: pending` and its minimal entity replay payload, run the per-sync recovery helper, and assert entity creation is invoked without rewriting the note. Feed a write result whose only operation dead-lettered and assert the phase becomes terminal `failed` and the emitted line names the ledger and `/dex-doctor`.

- [ ] **Step 2: Run and verify RED**

Run: `node --test .scripts/meeting-intel/__tests__/entity-phase.test.cjs`

Expected: no per-sync recovery/reconciliation API exists.

- [ ] **Step 3: Implement replayable meeting state**

Persist the note record with a minimal entity payload before entity creation. On every non-dry sync path, rerun pending and retryable-failed payloads idempotently, reconcile completed IDs to `complete`, dead-lettered meeting IDs to terminal `failed`, and persist after every transition. Replace dead-letter-as-pending wording with an actionable permanent-failure line.

- [ ] **Step 4: Re-run meeting-intel tests**

Run: `node --test .scripts/meeting-intel/__tests__/entity-phase.test.cjs .scripts/meeting-intel/__tests__/entity-creation.test.cjs`

Expected: lifecycle recovery and terminal failure tests pass.

### Task 5: Doctor, verification, and interpreter capability status

**Files:**
- Modify: `.scripts/lib/dex-python.cjs`
- Modify: `.scripts/lib/tests/dex-python.test.cjs`
- Modify: `.scripts/meeting-intel/verify-entities.cjs`
- Modify: `.scripts/meeting-intel/__tests__/verify-entities.test.cjs`
- Modify: `core/utils/doctor.py`
- Modify: `core/tests/test_doctor.py`

- [ ] **Step 1: Write failing capability and observability tests**

Use an executable that fails `import yaml`/Python-version probing and assert it is rejected once with a broken configuration feature status. Create one actionable dead-letter JSONL record and assert verification returns `feature_status: broken` plus a count/fix path, and Doctor returns a non-OK entity check with the same actionable information.

- [ ] **Step 2: Run and verify RED**

Run: `node --test .scripts/lib/tests/dex-python.test.cjs .scripts/meeting-intel/__tests__/verify-entities.test.cjs`

Run: `.venv/bin/python -m pytest core/tests/test_doctor.py -q`

Expected: path-only Python validation passes the incapable executable and both probes ignore the ledger.

- [ ] **Step 3: Implement cached capability and feature-status reporting**

Probe an absolute executable once with `import yaml,sys; assert sys.version_info >= (3,10)`. Return structured configuration detail to the bridge without falling back to a system interpreter. Parse the dead-letter ledger in verification and Doctor; report count, `System/.dex/entity-dead-letter.jsonl`, and `/dex-doctor`. Preserve malformed-ledger uncertainty rather than hiding it.

- [ ] **Step 4: Re-run focused JS and Python tests**

Run the commands from Step 2 and confirm all pass.

### Task 6: Full verification

**Files:**
- Verify all modified files and repository gates.

- [ ] **Step 1: Run every requested JavaScript test file directly**

Enumerate test files under `.scripts/lib/tests`, `.scripts/meeting-intel/__tests__`, and `.claude/hooks/tests`, then invoke `node --test "$file"` for each file and aggregate exact pass/fail/skip counts.

- [ ] **Step 2: Run canonical Python engine and CLI suites**

Run the entity-engine Python tests and CLI tests with the capability-approved repository interpreter. Re-run the real CLI byte-parity tests from the JS bridge.

- [ ] **Step 3: Run quality and distribution gates**

Run Ruff because `core/utils/doctor.py` changed, then the portable-contract, distribution, PII, and founder-content gates using their repository scripts/tests. Record exact counts and interpreter path/version.

- [ ] **Step 4: Review the final diff and report physical-machine gaps**

Check every requirement against the diff and fresh test evidence. State that launchd cadence/environment, no-venv-to-venv recovery, and process death in the dead-letter/pending boundary still require real-machine smoke coverage.
