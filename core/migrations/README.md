# Dex Migration Scripts

**Last Updated:** 2026-07-26

Structural migrations for major version changes to a user's install. **Users never
run anything in this folder by hand** — migrations are owned and driven by the
lifecycle engine, with one break-glass exception noted below.

---

## What's actually live

### `v1-to-v2-brain-vault-split.cjs` — the topology migrator (LIVE)

The one-time move that separates Dex's product files (the "brain") from the user's
content (the "vault") into distinct histories. It is invoked only by:

- **`install.sh`** — fresh installs are set up split from the start.
- **`core/lifecycle/engine.py`** — for existing combined-layout vaults,
  `/dex-update` runs the lifecycle service's topology flow:
  `build_and_preview_topology_migration` (dry-run report) → the user's explicit
  yes to that exact report → `execute_approved_topology_migration` → receipt with
  transaction ID and a local undo archive. The service also owns resume after
  interruption (exit code 75 loop).

**Never run the migrator directly as part of an update.** The `/dex-update` skill
says this in as many words. The sole sanctioned direct use is **recovery**: when
`/dex-doctor` diagnoses a topology stuck mid-migration (or disagreeing split
markers), Doctor's guidance may include running it with `--resume` / `--restore`.
That is break-glass, not a workflow.

Supporting pieces here:
- `sync-folder-detector.cjs` — refuses to convert a vault living inside a
  cloud-synced folder (Dropbox/iCloud), per the v1.75.2 rehearsal findings.
- `preserve_local_only_paths.py` — keeps local-only paths safe across the split.
- `tracked-ignored-policy.yaml` — policy input for what the split tracks vs ignores.
- Tests: `tests/`, `../tests/brain-vault-migrator-*.test.cjs`,
  `../tests/test_lifecycle_topology_migration.py`.

### `migrate_v1_to_v2.py` — ORPHANED (do not instruct anyone to run it)

An earlier, generic v1→v2 migration script from the manual-git-update era. Nothing
in the current install/update system calls it; only its own unit test exercises
it. Previous versions of this README told users to run it by hand and then
`git merge upstream/release` — that entire workflow is dead. Kept for reference
until a deliberate deletion pass; treat it as historical.

---

## For maintainers: adding a future migration

Don't copy the old shell-script template that used to live here — it predates the
safety architecture. A new structural migration must:

1. **Run under the lifecycle service** — surfaced as a previewable, approvable,
   receipt-backed operation (see how `engine.py` wraps the topology migrator via
   `TOPOLOGY_MIGRATOR_RELATIVE`), never as a script users invoke.
2. **Share the transaction core's lock + journal directory** so it can never run
   concurrently with another vault mutation (`core/transaction/`).
3. **Be resumable and undoable** — dry-run first, bounded resume on interruption,
   and a receipt naming the undo path.
4. **Respect the portable ownership contract** — never write `vault`-class paths
   beyond the migration's explicit, previewed scope.
5. **Be rehearsed on real-shaped vaults** before switch-on (large file counts,
   accented filenames, cloud-synced folders, symlinks — all real findings from
   the v1.75.2 rehearsal).

Design references: `docs/transaction-core-design.md`,
`docs/architecture/DEX-CORE-MAP.md` §§1–4.
