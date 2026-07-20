# Handoff — Dex-core SR1 Task 1: Credential Containment

This is a **private WIP handoff repo** mirroring `davekilleen/Dex` (Dex-core) plus the
in-progress credential-containment branch. Complete the remaining verification here, then
the branch can be pushed to the real `davekilleen/Dex` and a PR opened.

- Base repo: `davekilleen/Dex` (public), base branch `main`, base SHA `b7c74d87`.
- Working branch: `vorflux/sr1-credentials`, current HEAD **`c74a0c2`**.
- **Do not make this repo public** until SR1 ships — the branch documents unshipped
  credential-exposure attack surfaces and guards.

## Current state of HEAD `c74a0c2`

`c74a0c2` resolves the four review/simplify findings raised against the prior commit `de7c0e4`.
All changes touch four files:

- `core/utils/credential_remediation.py`
- `core/utils/credential_workflow.py`
- `core/tests/test_credential_remediation.py`
- `core/tests/test_credential_workflow.py`

### Findings resolved in c74a0c2 (verified present)

1. **HIGH — temp inode journaled as published before `os.replace()`.** Now uses explicit
   per-target `PublicationState` (`pending`/`prepared`/`published`). Temp identity is recorded
   only as *prepared*; durable transition to *published* happens only after `os.replace()` +
   directory fsync/readback. Restart distinguishes named-preimage / prepared / published /
   independent-mutation states and is death-safe at every publication and rollback boundary.
2. **MEDIUM — permissive numeric parsing.** `_exact_int` now requires `type(value) is int`
   (no coercion of numeric strings, bools, floats, nulls, negatives, oversized) for mode/uid/gid
   and every identity integer; exact string/hash-length validation before `bytes.fromhex()`.
3. **Simplification — removed unshipped tuple-based `evidence_codes` compatibility path;**
   production now requires `CredentialEvidence` directly.
4. **Simplification — consolidated migration inspection** into one read-only typed authority
   `inspect_credential_migration()` in `credential_remediation.py`, shared by status/workflow and
   migration. Cross-module private imports (`_legacy_values`, `_active_mcp_raw_residual`) removed
   from `credential_workflow.py`.

### Reviewer-mandated inverse/mutation tests present (in test_credential_remediation.py)

- `test_restart_recovers_process_death_at_every_initial_publication_boundary` — forked
  `os.fork()` death injection at before-prepared / after-prepared / after-replace / after-readback /
  between-targets, for both config and env targets.
- `test_restart_recovers_process_death_throughout_initial_migration_rollback`
- `test_permissive_numeric_parser_mutant_reaches_rewind` — asserts rewind BREAKS when
  `_exact_int` is monkeypatched back to permissive `int()`.
- `test_rewind_prevalidation_guard_removal_recreates_rejected_raw_yaml_mutant`
- `test_status_renderer_rejects_removed_tuple_evidence_compatibility`
- `test_migration_consumes_the_public_typed_inspection_authority_once` — finding #4 parity.
- Numerous `test_journal_rejects_noncanonical_*` parametrized rejection tests.

### Verification already run on c74a0c2

- `ruff check` on all four files: **All checks passed**.
- `py_compile` of all four files: OK.
- Focused suite `pytest core/tests/test_credential_remediation.py core/tests/test_credential_workflow.py -q`: **306 passed** (~20s).

## What still owes (do NOT skip — trust-engine discipline)

Because `c74a0c2` is a brand-new exact SHA/tree, prior approvals on `6df3f46`/`de7c0e4` do
**NOT** carry forward. Before this is shippable:

1. **Wider gates on the full tree** (not just the two credential test files): full non-fuzz
   Python suite, ruff on the repo, the repo's security gate (`scripts/security-gate.sh`),
   path-contract, and distribution gates.
2. **Fresh simplification pass** against `c74a0c2`.
3. **TWO independent adversarial code reviews** against `c74a0c2` — the trust-engine rule
   (`docs/solutions/architecture-patterns/trust-engine-and-verification-methodology.md`) requires
   two materially-independent adversarial reviews for security-sensitive changes; a split verdict =
   do-not-ship. Passing tests are not proof; removing a claimed guard must fail a paired test.
4. **Immutable-fixture acceptance run** covering all prior blocker families + paired guard-removal
   + full gates + non-publishing stable/beta/vault-bundle + credential/digest output scans +
   zero provider/network/fetch/push proof. **Synthetic credentials only.**

## Known intentional blocker — do NOT fabricate

Missing required file `build/release-evidence/sr1-native-capability-evidence.json` is an EXTERNAL
release-certification blocker (macOS 14/15 case-insensitive APFS, real iCloud Drive APFS, Windows
11/NTFS). Ubuntu/Linux results must NOT be generalized to those platforms. Source-approval is
separate from release-certification. Leave native evidence absent unless genuine immutable records
are supplied.

## Security model (authoritative, unchanged)

- Vault-root `.env` is the sole raw Todoist/Trello credential source; tracked
  `System/integrations/config.yaml` stores only `api_key_env_var` / `token_env_var` references;
  `.mcp.json` stays byte-identical + scan/report-only. Credentials reach adapters over stdin only —
  never in logs/state/results/argv/tracked-YAML/diagnostics.
- Migration states: `not-needed`, `migrated-local-config`, `partial`, `refused`, `rewound`.
- Security states: `remediated`, `rotation-pending`, `unknown`.

## Environment notes for running tests

- System `python3` (3.12) has no pytest/yaml. Create a venv and `pip install pytest pyyaml`
  (the original machine used a `.venv` with pytest + pyyaml).
- Fork-based death tests require a POSIX `os.fork` (Linux/macOS ok; skipped elsewhere).
