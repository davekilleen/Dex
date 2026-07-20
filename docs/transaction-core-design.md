# Transaction Core — PR-1 design (authored by orchestrator, 2026-07-20)

The crash-safe back-up → apply → verify → undo substrate shared by the v1→v2
migrator (PR-2), the split updater (PR-3), and the cathedral catalog engine.
Decision A sequences the cathedral snapshot/rollback-core-first: this IS that
core. Consumes the ownership contract (PR-0, merged as #154) for every write
decision via `update_write_verdict`.

## Language decision (settled in the split plan §5 Risk 1)
Python (`core/transaction/`), not CJS: the cathedral's engine is Python, and
building the updater's substrate in Python now avoids a second lifecycle stack.
The one-time migrator (PR-2) keeps its proven CJS internals but acquires THIS
core's lock file and journal directory so the two can never run concurrently.

## Artifacts
| File | Role |
|---|---|
| `core/transaction/__init__.py` | Public API |
| `core/transaction/lock.py` | Owner-safe lock (port of #141 `owned-lock.cjs` semantics: fsynced create-exclusive, PID+start-token liveness, inode+bytes pinned remove-if-unchanged) |
| `core/transaction/journal.py` | Append-only fsynced journal (schema_version 1, one JSON line per entry, parent-dir fsync after append; torn tails detected and truncated on recovery) |
| `core/transaction/snapshot.py` | Content snapshot of a write-plan's target paths (byte-exact copies + mode bits under `System/.dex/tx/<id>/snapshot/`, manifest with sha256) |
| `core/transaction/engine.py` | `Transaction` orchestration: plan → snapshot → apply → verify → commit, `resume()`, `rollback()` |
| `core/tests/test_transaction_core.py` | Unit + fault-injection suite |

## The contract with consumers
```python
tx = Transaction.begin(vault_root, plan)   # plan: [(path, action, content_source)]
# begin(): acquires lock, validates EVERY plan entry through
# portable_contract.update_write_verdict(path, exists=...) — any disallowed
# entry aborts the whole transaction before any write (all-or-nothing gate).
# snapshot(): copies every target's current bytes+mode; fsyncs; journals.
# apply(): temp-file + rename per target; journals per-target completion.
# verify(): re-reads every target, sha256 vs plan expectation; journals.
# commit(): journals COMMITTED; releases lock; retains snapshot for undo.
tx.rollback()   # any time before/after commit: byte-exact restore from
                # snapshot (including deleting files the tx created), fsynced,
                # journaled ROLLED-BACK.
Transaction.resume(vault_root)  # after crash: reads journal, either completes
                                # the apply (if snapshot complete) or rolls
                                # back (if not) — never leaves a half-state.
```

## Invariants (each carries a red-when-removed or fault-injection test)
1. **No write outside the plan; no plan entry unauthorized by the contract.**
   Deny/vault/unclassified → abort before first byte. (Red-when-removed:
   neuter the verdict check → authorization test goes red.)
2. **Snapshot-before-mutate.** No target is modified before its snapshot entry
   is journaled+fsynced. (SIGKILL between snapshot and apply → resume rolls
   back to byte-identical tree.)
3. **Atomic per-file apply.** Temp file in target's directory + rename;
   parent fsync. Interrupted rename → resume converges.
4. **Exact undo.** rollback() restores byte-identical content + mode for every
   target, and removes created files/dirs it introduced. Verified by tree-hash
   comparison in tests.
5. **Single writer.** Second Transaction.begin() under a live lock → clean
   refusal; stale lock (dead PID, pinned inode+bytes) → safe takeover.
   (Port the #141 lock tests' semantics.)
6. **Journal is append-only truth.** Every state transition journaled before
   the action it describes takes effect ("intent before act"); recovery trusts
   only the journal; torn final line is detected (sha per line) and dropped.
7. **Secrets never snapshotted into world-readable state.** tx dir is 0o700,
   files 0o600 — and deny-listed paths can never be in a plan anyway (inv. 1).

## Fault-injection test harness
Env hooks in the style of #141's `DEX_UPDATE_TEST_SIGKILL_*`:
`DEX_TX_TEST_STOP_AFTER=<phase[:index]>` makes the engine `os._exit(137)` at
the exact seam; the test then runs `Transaction.resume()` in a fresh process
and asserts convergence (either fully applied or byte-identical rollback,
never mixed). Seams: after-lock, mid-snapshot, after-snapshot, mid-apply
(per-target), after-apply, mid-verify, after-commit-before-lock-release.

## Non-goals for PR-1
- No release/catalog semantics (what to write comes from callers; PR-3+).
- No folder-paths remapping (documented contract limitation; consumers
  canonicalize).
- No retention policy beyond "keep the last transaction's snapshot" (the
  cathedral's retention rules come with the catalog phases).
- The migrator's own CJS journal stays as-is inside PR-2; it only shares the
  LOCK (one mutator at a time across engines).
