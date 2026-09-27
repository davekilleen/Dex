# Windows support and security — code-ready specification

**Status:** specification only, no implementation. Written 2026-09-27 against `main` at
`aab02b19` (released: v1.97.15; unreleased on main through v1.97.20).
**Audience:** the implementing agent (phase by phase, with tests) and the security reviewer.
**Scope:** the six areas named in the planning request (A–F). The parallel "safe fix" PRs are
treated as preconditions and are *not* re-specified here except where a design below depends on
them.

> **Grounding note.** The two attachments named in the request (`GS-JOE-WINDOWS-0927.md`, the
> audit, and `joe-windows-install-2026-09-26.md`, the user's report) were not present on disk
> when this spec was written (the upload directory was never created). Everything below is
> grounded in the real code on `main` (file:line citations throughout) plus the descriptions of
> the parallel swarm PRs (#748, #749, #752, #753, #754, #755), which restate the report's facts:
> Windows 11, Git Bash reporting `OSTYPE=cygwin`, python.org Python 3.12, Dex 1.97.15,
> `install.sh` treating the shell as Unix, looking for `.venv/bin/python`, and swallowing the
> real error. Where this spec asserts a fact about the report that the code cannot confirm, it
> says so.

---

## 0. Reading guide

| Section | Answers |
| --- | --- |
| 1 | What is actually wrong on `main` for native Windows (evidence, with citations) |
| 2 (A) | Windows vault hash migration: detection, repair vs refuse, messaging, idempotency, rollback, tests |
| 3 (B) | The three security controls on native Windows: credentials/trust, trusted Git, race-safe directory chain |
| 4 (C) | Exactly which Windows setups are supported, detection, messages |
| 5 (D) | README vs `dex_update_bridge` honesty: exact wording |
| 6 (E) | CI: which Windows jobs become required and when |
| 7 (F) | Ordered PR-sized phases with files, acceptance tests, security gates |
| Appendix | Windows API constants, test fixtures, open decisions for security review |

Conventions used below:

- **CRT text mode.** On Windows, `os.open()` without `os.O_BINARY` yields a C-runtime descriptor
  in *text mode*: `os.write` turns every `\n` into `\r\n`; `os.read` turns `\r\n` into `\n` and
  stops at the first `0x1A` (Ctrl-Z) byte. `Path.read_bytes()`, `open(..., "rb")`,
  `shutil.copyfile` and `tempfile.mkstemp` are *not* affected (they pass `O_BINARY`). Every
  claim of the form "text-mode read/write" below refers to a raw `os.open` site.
- **Byte-canonical record.** A lifecycle record whose reader re-serialises the parsed document
  and requires the on-disk bytes to equal that serialisation exactly. A single trailing `\r\n`
  makes such a record unreadable.
- **Fail closed.** Refuse the operation with a stated reason; never substitute a weaker check.
- "**nt**" means `os.name == "nt"` (native win32 Python). Git Bash launching a python.org Python
  is nt. MSYS2/Cygwin Pythons are not nt and are out of support (section 4).

---

## 1. Findings on `main` (`aab02b19`) that the design depends on

### 1.1 Text-mode raw `os.open` sites that feed hashes or byte-canonical records

| Site | Kind | Windows effect today |
| --- | --- | --- |
| `core/lifecycle/filesystem.py:167` (`_open_beneath`, Windows branch) and `:173`, `:178`, `:184` (POSIX branch, harmless there) | **read**, feeds `bounded_read` → `sha256_file`, inventory digests, snapshot stores, preview `expected_current_sha256`, release-anchor manifest binding | Every hashed vault file is read CRLF→LF-translated and truncated at the first `0x1A`. Binary release files containing `0x1A` classify as modified. Hashes recorded from these reads are hashes of *translated* bytes. |
| `core/transaction/engine.py:639` (`_target_matches_planned_content`) | **read**, recovery evidence | Text-mode read; also `os.O_NOFOLLOW` raises `AttributeError` on nt (`:630-633`) so the function returns `False` for every target — recovery treats every `expected_absent` write as unapplied. |
| `core/transaction/snapshot.py:110-114, 123-125` | **read** via `bounded_read` for capped entries (today only the automation-ownership sidecar) | Snapshot store for those entries is the *translated* content; manifest hash matches the store, so a later rewind would restore altered bytes and pass verification. |
| `core/lifecycle/bridge.py:362` (activation record write) | **write**, byte-canonical (`_validate_activation` `:185`, `_well_formed_activation` `:225`) | First `_prepare()` writes `activation.json` with a `\r\n` tail. Every later lifecycle call fails `raw != _canonical(...)`, is not "stale" (`_stale_activation` also requires canonical bytes), and surfaces as `PlanRejected("this Dex copy's update engine doesn't match its release information — run /dex-doctor")` (`core/lifecycle/service.py:1036-1046`). **This is the durable, self-inflicted lockout a Windows vault hits on its second lifecycle operation.** |
| `core/lifecycle/engine.py:626` (adoption receipt write) | **write**, byte-canonical (`load_adoption_receipt` `:667-668`) | Every Windows receipt is refused at rewind time: "receipt file is valid JSON but not canonical". |
| `core/lifecycle/engine.py:2128` (topology receipt write) | **write**, canonical | Same class; only relevant if a topology migration ever ran on nt. |
| `core/lifecycle/ledger.py:341, 649, 803, 827` | **write**, byte-canonical (`_validate_event` `:263`) | Not reachable today: `_write_lock` (`:766`) and `_read_lock` (`:755`) `import fcntl`, which raises `ModuleNotFoundError` on nt — an exception the engine does **not** catch (`engine.py:270` catches `LedgerError, OSError` only). Once PR #754 lands the lock, these writes would produce permanently non-canonical events **unless PR #748's `O_BINARY` writes land first or together.** |
| `core/transaction/journal.py:89-90, 122` | **write**, tolerant reader (`json.loads` accepts trailing `\r`) | No lockout; covered by #748. |
| `core/utils/integration_credentials.py:69, 278, 367` · `core/utils/credential_remediation.py:631, 674, 706, 737, 977, 1106` · `core/utils/trust_registry.py:334, 513` · `core/utils/credential_scanner.py:68` · `*/protect_trust_registry.py:105-107` | **read/write** in the three security modules | Owned by the draft "credential/trust O_BINARY" PR (awaiting security review). Section 3 depends on it. |

### 1.2 POSIX-only primitives the security modules rely on

- `os.supports_dir_fd` is empty on nt; `os.O_NOFOLLOW` and `os.O_DIRECTORY` do not exist.
  - `trust_registry._open_component_file` (`:124-126`) and `_require_private_directory`
    (`:299-302`) raise `TrustRegistryError("safe no-follow ... unavailable")` → the registry is
    treated as invalid → **no local MCP can be blessed or trusted on Windows today** (fail
    closed, correct, but the feature is absent).
  - `integration_credentials._open_vault` (`:236-243`) raises `OSError` → `read_vault_env`
    fails → **no `.env` credential can be resolved on Windows**, and
    `inspect_vault_env_authority` (`:314-330`) tells the user to `chmod 0600`, which is not a
    Windows concept.
  - `credential_remediation._open_directory_chain` (`:604-625`): `os.open(root, O_RDONLY)` on a
    directory raises `PermissionError` on nt before any `dir_fd` call, so
    `probe_atomic_migration` (`:711-768`) returns all-false capabilities → refused. Note that a
    `dir_fd=` call on nt raises `NotImplementedError`, which is **not** an `OSError`; any future
    Windows path through these functions must catch it explicitly.
- Ownership/permission checks are uid/mode based: `trust_registry.py:314-316, 378-381, 341-343`,
  `integration_credentials.py:266-270`, `credential_remediation.py:1067-1069, 1092-1093`. On nt,
  `st_uid == 0`, `st_mode` is synthesised (`0o666` or `0o444`), so the checks are meaningless.
- Symlink detection uses `stat.S_ISLNK` / `Path.is_symlink()` (`core/path_safety.py:44`,
  `filesystem.py:160`, `ledger.py:101`, `bridge.py:324`). On nt these are `False` for NTFS
  **junctions** and other name-surrogate reparse points; only true symlinks are reported.
  `Path.resolve()` follows junctions. The Windows branch of `_open_beneath` (`:147-171`)
  therefore admits an in-vault junction alias and has a lstat→resolve→open window.
- `core/transaction/fsync.py:26` makes directory fsync a no-op on nt (correct); other sites
  open directories with `os.open` and fsync them (`bridge.py:2996`, `service.py:1096`,
  `credential_remediation.py:618, 686, 746`) → `PermissionError`/`EBADF` on nt. Covered by the
  parallel "directory fsync routing" fix.

### 1.3 Trusted Git resolution

- `core/utils/local_git.py:25-39`: candidates `/usr/bin/git`, `/bin/git`, then
  `shutil.which("git", path=os.defpath)`. On nt `os.defpath` is `.;C:\bin` — the **current
  directory is consulted first**. No Windows candidate exists; `git_env` (`:42-63`) sets a
  POSIX `PATH` and `core.hooksPath=/dev/null`. Draft PR #749 replaces this with a closed
  Windows list; section 3.2 states what that draft must additionally satisfy.
- `scripts/dex_update_bridge.py:51` (`_TRUSTED_EXECUTABLE_DIRECTORIES`), `:1250-1266`,
  `:1306-1327`; the bridge refuses nt outright at `:3250-3251`
  ("this P0 bridge supports macOS and Linux only").
- `core/utils/trust_registry.py:227-240` and the three `protect_trust_registry.py` copies
  (`:20-33`) use `shutil.which("git")` — the ambient `PATH`, including `PATHEXT` shims such as
  `git.cmd`/`git.bat`. Their subprocess environments (`trust_registry.py:250-259`) set
  `HOME=/var/empty` and a POSIX `PATH`; on nt this omits `SYSTEMROOT` and can break process
  creation, which today degrades to "could not verify the registry is user-owned" (fail closed).

### 1.4 What already exists and must be reused

- `core/lifecycle/catalog.py:361-375` `crlf_normalized_sha256` and `:469-482`
  `release_bytes_match` — the one sanctioned CRLF tolerance, used when comparing on-disk bytes
  to *release-declared* hashes (issue #256). `customizations.py:116` normalises the manifest the
  same way. Nothing else may normalise line endings.
- `core/transaction/lock.py:11-14, 77-129` — the mutation lock already has a Windows-aware
  liveness probe (issue #257). Transactions therefore **have** run on Windows vaults; adoption
  receipts and activation records written in text mode exist in the wild.
- `core/lifecycle/service.py:1440-1443` and `core/provision.cjs:714-729, 959-960` already
  rewrite `.venv/bin/python` → `.venv/Scripts/python.exe` on nt.
- `core/utils/doctor.py:2644-2646` `_probe_python_env` checks `.venv/bin/python` only → always
  BROKEN on nt (fix in section 4.6).
- `docs/HARNESS-PORTABILITY.md:19-25` and `core/harnesses/registry.json:20-25` already state
  the honest portable-plugin position: "Native CI required on each review head".
- `.github/workflows/ci.yml:133-159` `portable-plugin-platforms` runs on `windows-latest` and is
  the only Windows job today; it does not run `install.sh`, the transaction engine, or the
  lifecycle suite. PR #752 adds an advisory `windows-install` workflow.

### 1.5 Parallel work this spec treats as preconditions

| Lane | PR | What this spec assumes from it |
| --- | --- | --- |
| a | #755 installer | `install.sh` detects nt via `.venv/Scripts`, `OSTYPE ∈ {msys,cygwin,win32}`, `WINDIR`; Python probe order `python3` → `py -3` → `python`; failures logged to `System/.dex/install.log`; `install.ps1` exists. Section 4 defines the *support policy* the probe must implement; the mechanics stay with #755. |
| b | (JSON escaping in `provision.cjs` / `service.py`) | Not referenced. |
| c | #754 lock helper | `core/utils/file_lock.py`; ledger no longer imports `fcntl`. **Ordering constraint: #748 must land before or together with #754** (1.1). |
| d1 | #748 `binary_write_flags` | Write sites listed in its audit are binary. It explicitly leaves `filesystem.py`, `transaction/engine.py` reads, and the security modules alone — those are sections 2 and 3 here. |
| d2 | draft "credential/trust O_BINARY" | The read/write sites in the three security modules pass `O_BINARY`. Section 3.1 builds on it. |
| e | #749 trusted Git candidates (draft, security review) | Section 3.2 lists the deltas required before approval. |
| f | #752 advisory `windows-install` workflow | Section 6 promotes it. |
| g | #753 Granola paths | Not referenced. |
| — | fsync-before-chmod, `fsync_file`, fchmod fallback, directory fsync routing, Windows permission comparison | Section 3.1 replaces the *permissive* Windows permission comparison with an ACL check; until then the permissive comparison stands. |

---

## 2. (A) Windows vault hash migration

### 2.1 Problem statement

Landing `O_BINARY` on the hash-bearing reads (1.1 row 1–3) and on the byte-canonical writes
(already in #748) changes two things for a vault that has already run lifecycle operations on
Windows:

1. **Recorded bytes.** `activation.json`, `System/.dex/adoptions/*.receipt.json`,
   `System/.dex/topology-migrations/*.receipt.json` (and, defensively, ledger files) carry a
   `\r\n` tail and are refused by their own readers. This is not a hash *change*; it is a
   record that was never readable. It blocks `/dex-update`, `/dex-rollback`, plan, state and
   Doctor's lifecycle checks.
2. **Recorded digests.** `baseline_inventory_sha256` (activation), `inventory_sha256` and
   `preview_sha256` (receipts), `expected_current_sha256` for capped entries (journals), and the
   snapshot stores of capped entries were computed from translated bytes. After the fix,
   recomputation yields different values.

### 2.2 Decision: repair byte form; never rewrite evidence digests; refuse lossy rewinds

| Record | Finding | Action | Why |
| --- | --- | --- | --- |
| `System/.dex/lifecycle/activation.json` | bytes == canonical(document) with `\n`→`\r\n`; or recorded on nt before the marker existed | **Re-record**: quarantine the file, delete it, let `activate_vault` write a fresh record (binary reads → new baseline). | Activation is runtime state whose design already says "absent means activate on next use" (`bridge.py:257-261`). Re-recording is the documented safety net. |
| `System/.dex/adoptions/<tx>.receipt.json` | bytes == canonical + CRLF tail | **Normalise bytes**: parse with `AdoptionReceipt.from_dict`, re-serialise with `canonical_adoption_receipt_bytes`, atomic replace. Document identity is provably unchanged (assert `from_dict(json.loads(old)) == from_dict(json.loads(new))`). `inventory_sha256` / `preview_sha256` values are **left exactly as recorded**. | They are evidence of what was approved, never recomputed against the vault later (`engine.py:1246-1272` compares preview vs rebuilt *within one run*). Rewriting them would forge provenance. |
| `System/.dex/topology-migrations/<tx>.receipt.json` | same | same as receipts | same |
| `System/.dex/ledger/events/*.json`, `state.json`, `commitments/*.sha256` | bytes == canonical + CRLF tail | **Normalise bytes under the write lock**, preserving `event_sha256` (computed over the document, `ledger.py:233-234`) and the commitment. Expected to be empty on every vault (1.1: the ledger never wrote on nt). | Identity-preserving; the "never rewrite an event" rule is about *content*; content is unchanged and the chain re-verifies. |
| `System/.dex/tx/<id>/journal.jsonl` | trailing `\r` per line | **No action** (tolerant reader). | — |
| `System/.dex/tx/<id>/snapshot/NNNNNN.bin` for a relative that has a read cap, captured on nt before the marker | lossy store (cannot be proven either way — the original bytes are gone) | **Mark `rewind_unsafe`** in the marker; `rewind_adoption` on nt refuses receipts whose `snapshot_ref` is listed, with the message in 2.6. | Restoring translated bytes would silently alter a user file. keep=3 retention makes this short-lived. |
| `System/trusted-mcps.yaml` digests | none can exist on nt today (1.2) | **No migration.** Trust digests stay exact-bytes; a file whose bytes differ (including line endings) requires re-blessing via `/create-mcp`. | Consent is for exact bytes; never widen it. |
| `System/.dex/adoption/credential-journals/*` | none can exist on nt today (readback compare at `credential_remediation.py:1114-1116` refuses text-mode output) | **Report only** if present. | — |
| `System/.dex/release-anchor.json` | `bindings.manifest_sha256` may be the LF digest of a CRLF manifest | **No action**: `parse_release_anchor` compares with `release_bytes_match` (`release_anchor.py:270-274`). Phase 1 changes generation to bind `catalog.release.manifest.sha256` (the release's canonical digest) instead of the on-disk digest so future anchors are line-ending independent. | — |

**Never:** touch any file outside `System/.dex/` (and the two receipt classes above); never
recompute and overwrite a digest field; never run on POSIX except in "report" mode.

### 2.3 Marker and provenance

Path: `System/.dex/lifecycle/byte-mode.json` (runtime class in `core/portable_contract.py`;
`System/.dex/**` is already runtime). Canonical JSON (same `_canonical` as `bridge.py:82-92`):

```json
{
  "byte_mode_version": 1,
  "hash_read_mode": "binary",
  "platform": "win32",
  "migrated_at": "2026-10-01T09:12:03Z",
  "quarantine": "System/.dex/lifecycle/byte-mode-quarantine/20261001T091203Z",
  "actions": [
    {"record": "System/.dex/lifecycle/activation.json", "finding": "crlf-tail",
     "action": "re-recorded", "previous_bytes_sha256": "…"},
    {"record": "System/.dex/adoptions/<tx>.receipt.json", "finding": "crlf-tail",
     "action": "bytes-normalised", "previous_bytes_sha256": "…", "new_bytes_sha256": "…",
     "document_identity_unchanged": true}
  ],
  "rewind_unsafe": ["System/.dex/tx/<id>/snapshot"],
  "ledger_seq_at_migration": 0,
  "committed_tx_ids_at_migration": ["<id>", "…"]
}
```

- `hash_read_mode` is the only field consulted by the fast path. `"binary"` + `platform ==
  sys.platform` ⇒ skip detection. Any other state ⇒ run detection (a vault synced from macOS to
  Windows has no marker; a marker written on win32 and read on darwin is ignored).
- `actions` is the provenance the user and Doctor can read. Receipts themselves are not
  annotated (their schemas are closed; `engine.py:311`).

### 2.4 Detection algorithm (read-only; identical on every OS)

```
def detect(vault_root) -> ByteModeReport:
    findings = []
    # 1. activation
    raw = read_bytes(activation)               # Path.read_bytes → binary everywhere
    if raw is present and _well_formed_activation(raw) is None:
        doc = strict_json(raw)                  # tolerant parse
        if doc is a 4-field activation and raw == _canonical(doc).replace(b"\n", b"\r\n"):
            findings.append(crlf_tail(activation))
    elif raw is present and marker absent and sys.platform == "win32":
        findings.append(text_mode_baseline(activation))   # re-record anyway on first nt run
    # 2. receipts (adoption + topology): same CRLF-variant test with their canonical serialisers
    # 3. ledger: events/state/commitments — CRLF-variant test; each event's recomputed
    #    event_sha256 must equal both the embedded field and its commitment, else STOP (not ours)
    # 4. snapshots: for each committed tx dir (journal has COMMITTED) whose BEGIN plan lists a
    #    relative present in `max_read_bytes_by_relative` and whose journal `at` predates the
    #    marker (or marker absent) → rewind_unsafe
    return ByteModeReport(findings, rewind_unsafe, blocking=[…anything unexpected…])
```

Exact-variant test is deliberate: a record that differs from canonical in any way *other* than
`\n`→`\r\n` is **not** repaired; it is reported as `blocking` with reason "record is
non-canonical for a reason the Windows byte-mode migration does not explain" and the migration
stops before writing anything.

### 2.5 Apply algorithm (the one safe door)

Implement as `core/lifecycle/byte_mode.py` with `detect(vault_root)`, `apply(vault_root,
report)`, `rollback(vault_root)`. Wire-up:

1. `core/lifecycle/service.py::_prepare` — on nt only, before `recover_committed_adoption_evidence`:
   `byte_mode.ensure(vault_root)`; if the report has `blocking`, raise `PlanRejected` with 2.6-M3.
2. `python -m core.lifecycle.cli --vault-root X byte-mode {status|apply|rollback}` (`cli.py`
   gains three subcommands; `status` prints the report JSON; `apply` and `rollback` print
   actions).
3. Doctor quick check `lifecycle.byte-mode` (2.7).

Apply order and atomicity:

1. Acquire the mutation lock (`core/transaction/lock.py::acquire_owned_lock(vault, "byte-mode")`)
   and, if the ledger directory exists, the ledger write lock (via #754's helper).
2. Create the quarantine directory (0o700 semantics on POSIX; on nt ACL is inherited — the
   directory lives under `System/.dex`, already user-private) and copy **every file that will be
   modified or deleted** into it, preserving relative paths, plus `manifest.json` listing
   `{relative, sha256_before}`.
3. For each receipt/ledger finding: write the canonical bytes to a same-directory temporary
   file opened with `binary_write_flags(O_WRONLY|O_CREAT|O_EXCL)`, fsync, `os.replace`.
   Re-read with `Path.read_bytes()` and assert (a) the reader now accepts it
   (`load_adoption_receipt` / `_validate_event`), (b) parsed identity equals the quarantined
   original's parsed identity.
4. Delete `activation.json` (after quarantine). Do **not** call `activate_vault` here;
   `_prepare` continues to `prepare_vault`, which re-records it through the existing path.
5. Write the marker last (canonical JSON, binary, atomic). A crash before step 5 leaves the
   quarantine plus partially normalised records; every normalised record is still valid and
   detection on the next run finds only the remainder. Idempotent by construction.
6. Release locks.

### 2.6 User-facing messaging

House style: plain words, no jargon in headlines; technical detail only where the user must act.

- **M1 — apply (stderr, once):**
  "Dex is putting right some of its own bookkeeping files that were written with Windows line
  endings. Your notes are not touched. A copy of each file before the change is kept in
  System/.dex/lifecycle/byte-mode-quarantine."
- **M2 — nothing to do:** silent in `_prepare`; `byte-mode status` prints
  `{"state": "binary", "findings": []}`.
- **M3 — blocking finding (PlanRejected):**
  "Dex found a bookkeeping file it cannot safely repair on its own: <relative>. Nothing was
  changed. Run /dex-doctor, or `python -m core.lifecycle.cli --vault-root <vault> byte-mode
  status` to see the detail."
- **M4 — rewind refused (`rewind_adoption`):**
  "This update was recorded before Dex fixed how it reads files on Windows, so its undo copy
  may have altered line endings. Dex will not restore it. Your current files are untouched;
  to go back, restore from your own backup."
- **M5 — rollback refused:**
  "The bookkeeping repair cannot be undone because Dex has recorded newer updates since. The
  pre-repair copies are still in <quarantine path> if you need them."
- **CHANGELOG entry (headline):** "Dex on Windows can update again after its first update" —
  body explains that Dex's own record-keeping files had been saved with Windows line endings,
  which made Dex refuse its next update and every undo; Dex now repairs those files once, keeps
  a copy, and reads every file byte-for-byte. Credit the reporter by first name.

### 2.7 Doctor check `lifecycle.byte-mode` (quick)

- `OK` — marker `binary` for this platform and detection finds nothing (detection runs at most
  once per Doctor invocation; it is read-only).
- `BROKEN` + Heal tier 2 ("Repair Dex's bookkeeping files (a copy is kept first).") — findings
  present, no `blocking`. Tier 2 because it rewrites runtime files; it never touches user data.
- `BROKEN` + tier 3 — `blocking` present: "Repair by hand or report with /feedback."
- `UNKNOWN` — detection raised.
- On POSIX: `OK` with detail "not applicable on this platform" unless CRLF-tailed records are
  found (a synced vault) — then `BROKEN` tier 2 exactly as on nt.

### 2.8 Rollback

`byte-mode rollback`:

1. Refuse unless the marker exists and `ledger_seq_at_migration` equals the current ledger
   `last_seq` **and** the set of committed tx ids equals `committed_tx_ids_at_migration` (M5).
2. Under the same locks, copy each quarantined file back over its target (atomic replace),
   verifying `sha256_before` from the quarantine manifest.
3. Delete the marker; leave the quarantine in place (it is the only remaining copy of the
   post-repair state now — record `rolled_back_at` in `manifest.json`).
4. Print the restored list. The vault is now back in the pre-repair (unreadable) state by the
   user's explicit choice; `_prepare` will offer the repair again.

Retention: keep the newest quarantine set only; `apply` removes older sets after the new one is
complete (never before).

### 2.9 Read-side changes that trigger the migration (Phase 1)

- `core/utils/os_flags.py`: add `binary_read_flags(base_flags: int) -> int` beside #748's
  `binary_write_flags` (both are `base | getattr(os, "O_BINARY", 0)`; two names keep audits
  greppable).
- `core/lifecycle/filesystem.py::_open_beneath`: apply to `:167` and `:184`. Do **not** add it to
  directory opens (`:173`, `:178`). Keep the Windows branch's `getattr(os, "O_NOFOLLOW", 0)`
  until Phase 4 replaces the branch with the handle-verified open.
- `core/transaction/engine.py::_target_matches_planned_content`: on nt, `os.O_NOFOLLOW` is
  absent; replace the `AttributeError → False` with: nt ⇒ call the Phase-4 helper when
  available, else refuse the *shortcut* (return `False`) **and** log once at debug level why.
  Add `binary_read_flags`.
- `core/update/anchor_generation.py:428`: `manifest_sha256=catalog.release.manifest.sha256`.
  `release_anchor.py` unchanged (`release_bytes_match` still verifies the installed bytes).
- `core/transaction/snapshot.py`: no change beyond #748 (its stores now hold exact bytes once
  `bounded_read` is binary).

### 2.10 Tests (A)

Platform-independent (run everywhere; bytes are bytes):

- `core/tests/test_lifecycle_byte_mode_detects_crlf_tail.py`: for each record class, write a
  canonical record, then the `\r\n` variant; `detect` reports exactly one finding of the right
  class; an *interior* CRLF variant and a record with a changed field are `blocking`.
- `test_lifecycle_byte_mode_apply_preserves_identity.py`: after `apply`, `load_adoption_receipt`
  succeeds; parsed receipt equals the original's parsed form; `inventory_sha256` string is
  byte-identical to before; quarantine manifest hashes match; marker canonical.
- `test_lifecycle_byte_mode_idempotent.py`: `apply` twice → second run writes nothing (mtime and
  bytes unchanged, `actions == []`).
- `test_lifecycle_byte_mode_rollback_guard.py`: rollback succeeds when no new tx; refused after
  one committed tx (M5).
- `test_lifecycle_byte_mode_rewind_unsafe.py`: a committed tx with a capped relative predating
  the marker → `rewind_adoption` refuses with M4 on nt (monkeypatch `os.name`), proceeds on
  POSIX.
- `test_lifecycle_activation_re_recorded_after_byte_mode.py`: CRLF-tailed activation → `_prepare`
  → new canonical activation, old one in quarantine, marker present.
- `test_lifecycle_filesystem_binary_read_flags.py`: monkeypatch `os.open` to record flags;
  assert `O_BINARY` (a fake attribute set on `os` during the test) is present on file opens and
  absent on directory opens.
- `test_update_anchor_binds_release_manifest_digest.py`: anchor generated from a CRLF manifest
  binds the catalog's declared digest.

Windows-only (`windows-core-tests`, section 6): the same suite plus an end-to-end: create a
vault, run one adoption with the **pre-fix writer simulated** (write the CRLF-tailed records
directly), then call `build_inventory_and_plan` → succeeds after repair; `rewind` of that
receipt is accepted (no capped entries) and restores exact bytes; a binary file containing
`0x1A` classifies as `stock`.

---

## 3. (B) The three security controls on native Windows

Shared threat model (applies to 3.1–3.3):

- **In scope:** an attacker who can place or swap *reparse points* (junctions need no
  privilege; symlinks need Developer Mode or `SeCreateSymbolicLinkPrivilege`) or files inside
  the vault or beside a trusted binary; a hostile vault checkout (git cannot check out
  junctions, but a ZIP/sync client can deliver them); PATH/cwd/`PATHEXT` hijack; TOCTOU between
  our check and our use; a same-machine *other* user with a foothold on the disk.
- **Out of scope (documented, not enforced):** an attacker running as the same user with write
  access to the user profile — they can already replace Dex's own code in the vault; an
  administrator; kernel/driver compromise; Windows Defender or a sync client rewriting files
  between check and use (we detect and refuse, we do not prevent).
- **Windows cannot give us:** uid/mode semantics; `dir_fd` for `os.*`; `O_NOFOLLOW`. It **can**
  give us: handle-relative certainty via `GetFinalPathNameByHandleW`, per-handle reparse
  attributes via `GetFileInformationByHandleEx(FileAttributeTagInfo)`, file identity via
  `FileIdInfo` (128-bit id + volume serial; surfaced by Python as `st_ino`/`st_dev` on a fstat
  of the handle's fd), and owner/DACL via `GetSecurityInfo`. All are reachable with `ctypes`
  from the standard library; **pywin32 must not become a requirement**.

### 3.1 (B1) `credential_remediation`, `integration_credentials`, `trust_registry` (+ three `protect_trust_registry.py` copies)

#### 3.1.1 Windows "private file" definition (replaces uid/0600 checks on nt)

A path is **private** on nt when, read from an open handle:

1. Owner SID ∈ {current process token user SID} — for *user data* (`.env`, registry, snapshot
   dir); or ∈ {Administrators `S-1-5-32-544`, SYSTEM `S-1-5-18`, TrustedInstaller
   `S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464`} — for *trusted binaries*
   (3.2).
2. The DACL is present (a NULL DACL = everyone full control ⇒ refuse), and every
   `ACCESS_ALLOWED_ACE` whose trustee SID is **not** in {current user, SYSTEM, Administrators}
   grants none of: `FILE_WRITE_DATA 0x2`, `FILE_APPEND_DATA 0x4`, `FILE_WRITE_EA 0x10`,
   `FILE_WRITE_ATTRIBUTES 0x100`, `DELETE 0x10000`, `WRITE_DAC 0x40000`, `WRITE_OWNER 0x80000`,
   `GENERIC_WRITE 0x40000000`, `GENERIC_ALL 0x10000000`. Inherit-only ACEs
   (`INHERIT_ONLY_ACE 0x8`) are ignored for the object itself. Deny ACEs are ignored (we only
   need "nobody else may write").
3. For directories additionally: no foreign ACE grants `FILE_ADD_FILE 0x2`,
   `FILE_ADD_SUBDIRECTORY 0x4`, or `FILE_DELETE_CHILD 0x40`.

APIs (`ctypes`, `advapi32`/`kernel32`): `OpenProcessToken`, `GetTokenInformation(TokenUser)`,
`GetSecurityInfo(handle, SE_FILE_OBJECT=1, OWNER_SECURITY_INFORMATION|DACL_SECURITY_INFORMATION)`,
`GetAclInformation(AclSizeInformation)`, `GetAce`, `EqualSid`, `CreateWellKnownSid` (for the
well-known SIDs), `LocalFree`. Implement once in `core/utils/win_security.py`
(`file_is_private(fd_or_handle, *, owner_policy) -> PrivacyVerdict`), with a POSIX shim that
returns the existing uid/mode verdict so callers have one function.

**Repair guidance string (tier 3, user-only):**
"Make `<relative>` private to your account: in PowerShell run
`icacls "<absolute>" /inheritance:r /grant:r "$env:USERNAME:(F)"`. Dex never changes file
permissions on Windows for you."
(Tier 1 heal on nt is *not* offered: `icacls` semantics are not the provably-reversible chmod the
Doctor spec allows.)

#### 3.1.2 `integration_credentials`

- `_open_vault` (`:235-249`): on nt use `win_handles.open_directory(vault_root)` (3.3) → returns a
  `(fd, DirectoryHandle)` pair; metadata via `os.fstat(fd)`.
- `_validate_env_metadata` (`:264-272`): on nt replace `S_IMODE != 0o600` and `st_uid` checks
  with `file_is_private(fd, owner_policy="user")` executed on the **opened** descriptor
  (identity checked before and after exactly as today via `_identity`; `st_nlink == 1` remains
  meaningful on NTFS).
- `_read_env_at` / `update_vault_env` (`:275-297`, `:351-406`): on nt open `.env` and the
  temporary through `win_handles.open_beneath(dir_handle, ".env", write=False|create=True)`
  (3.3), which is the `dir_fd` replacement. `os.replace(temporary, ".env", src_dir_fd=…,
  dst_dir_fd=…)` has no relative form on Windows: perform `os.replace(dir_final_path/temporary,
  dir_final_path/.env)` using the **handle's final path** (obtained once from the directory
  handle), then re-open `.env` beneath the still-open directory handle and re-verify identity
  and bytes (`raw != expected` readback is already there, `:397-399`). The window between
  replace and re-verify is closed by the readback: a swapped-in file fails it and the function
  raises before returning; the temporary is unlinked by final path.
- `inspect_vault_env_authority` (`:314-330`): on nt map reasons to `"acl"` and use the 3.1.1
  repair string.
- `.env` **line endings:** parse is byte-based; a Notepad-created CRLF `.env` is accepted as
  today (`parse_env_assignments` must strip a trailing `\r`; verify, add test).

#### 3.1.3 `credential_remediation`

- `_open_directory_chain` (`:604-625`): on nt delegate to `win_handles.open_chain(root, parts,
  create=…)` (3.3). `create=True` uses `CreateDirectoryW` by final path of the parent handle,
  then re-opens the child beneath the handle and verifies it is not a reparse point and is on
  the same volume.
- `_read_at_with_metadata`, `_atomic_replace_at`, `probe_atomic_migration`,
  `migrate_credentials` (`:627-701`, `:711-768`, `:1040-…`): replace each `dir_fd=` call with the
  helper; replace `os.fsync(directory)` with `fsync_directory` (no-op on nt, per the parallel
  fix); replace uid/gid captures (`:1092-1093`) with the token user SID string (stored in the
  journal as `owner_sid`; the journal schema gains an optional field — bump `schema_version` to
  2, readers accept 1 and 2).
- `probe_atomic_migration` **must** exercise the real Windows primitives (Doctor rule 1): the
  probe creates, replaces and reads back through the handle helper; any `NotImplementedError`
  or `OSError` ⇒ that capability false ⇒ `refused`. Add `except NotImplementedError` wherever
  `except OSError` guards a `dir_fd` call (defensive; the helper never raises it, but the POSIX
  fallback path can if `os.supports_dir_fd` is unexpectedly empty).
- Mode preservation: `postimage.mode` is meaningless on nt; store `0o600` and skip `fchmod`
  (already tolerated by the parallel fchmod-fallback fix); privacy is enforced by the ACL check
  on the destination directory before publish.

#### 3.1.4 `trust_registry`

- `_open_component_file` (`:117-170`): on nt use `win_handles.open_chain` + `open_beneath`; keep
  the `(st_dev, st_ino)` before/after identity check (both populated from `FileIdInfo` by
  `os.fstat` on nt).
- `_require_private_directory` (`:297-320`) and the checks at `:378-381`, `:341-343`: use
  `file_is_private(..., owner_policy="user")`.
- `_registry_is_git_tracked` (`:242-295`): use `local_git.trusted_git_binary()` and
  `local_git.git_env()` instead of the private `_git_executable`/POSIX env (removes the
  `shutil.which` and `/var/empty` paths; on nt `git_env` must include `SYSTEMROOT` — it does,
  `:51`). Timeouts unchanged.
- `_snapshot_local_python_file` (`:477-614`): `os.link` works on NTFS; `os.fchmod(…, 0o400)`
  becomes a no-op on nt (fallback fix); snapshot directory privacy is the ACL check. **Snapshot
  root on nt** must not be a FAT/exFAT volume (no ACLs, no hard links): `win_handles` exposes
  `volume_supports_acls(handle)` via `GetVolumeInformationByHandleW` (`FILE_PERSISTENT_ACLS
  0x8`); refuse otherwise with "the folder is on a drive without file permissions; move the
  vault to an NTFS drive".
- `bless_local_mcp` (`:657-709`): `NamedTemporaryFile(mode="wb")` is binary already;
  `os.fchmod(…, 0o600)` no-op on nt; after `os.replace`, re-open the registry beneath the vault
  handle and run `file_is_private`; if it fails, **delete the just-written registry** and raise
  "the registry folder lets other accounts write; not saving consent" (never leave a consent file
  that the loader will then refuse — that would look like a Dex bug to the user).
- **Digests:** exact bytes only, read through binary descriptors (d2). No CRLF tolerance
  (2.2). Doctor's `customizations.mcp` check on nt gains the hint "if this file was edited on
  Windows its line endings may have changed; re-bless with /create-mcp".

#### 3.1.5 `protect_trust_registry.py` (three copies)

Canonical source: `.claude/skills/dex-update/scripts/protect_trust_registry.py`. The other two
(`.agents/skills/...`, `packages/dex-agent-plugin/skills/...`) are generated by
`scripts/generate-agents-skills.py` and `scripts/generate-portable-plugin.py` — **edit the
canonical file and regenerate; never hand-edit the copies** (add a test that the three are
byte-identical if none exists).

Changes: `_git_executable` (`:20-33`) → the same closed-list resolver as `local_git` (the
script cannot import `core` when run standalone during a merge; vendor the resolver as a small
function with the identical closed list and a test asserting parity with
`local_git.WINDOWS_GIT_CANDIDATES`); `_git` env → include `SYSTEMROOT`, `GIT_CONFIG_NOSYSTEM`,
`GIT_CONFIG_GLOBAL=<devnull>`, closed `PATH`; `restore_registry` write (`:105-119`) →
`binary_write_flags`; `os.fchmod(descriptor, mode)` → skip on nt; `capture_registry` records
`"mode": null` on nt.

#### 3.1.6 What cannot be enforced (document in module docstrings and `docs/credential-remediation.md`)

- No equivalent of "root-owned" for user data — the owner check is "current user".
- Same-user malware is not prevented (as on POSIX).
- ACL evaluation ignores deny ACEs and group membership expansion beyond the three well-known
  SIDs; a custom group with write rights is treated as foreign ⇒ refuse (fail closed, may be
  over-strict on managed machines — the repair string covers it).
- FAT/exFAT/ReFS-without-ACLs volumes and network shares (`\\server\share`) are unsupported for
  credential and trust files: detect via `volume_supports_acls` / `GetDriveTypeW ==
  DRIVE_REMOTE` and refuse with a plain message.

#### 3.1.7 Tests (B1) — Windows-only unless noted

- ACL verdicts: owner=user + no foreign ACE ⇒ private; add `Users:(W)` via `icacls` ⇒ not
  private; NULL DACL (set via `SetSecurityInfo` in test) ⇒ not private; inherit-only foreign ACE
  ⇒ private; directory with foreign `FILE_ADD_FILE` ⇒ not private.
- `.env` read/update through the handle chain: junction in place of `.env` ⇒ refused; junction
  as vault parent component ⇒ refused; `.env` replaced between open and readback ⇒ raises
  "readback mismatch"; CRLF `.env` parses.
- `probe_atomic_migration` on nt returns all-true on NTFS; all-false on a FAT-formatted VHD
  (skip if the runner cannot mount one — record `UNKNOWN` in the test summary, never pass).
- trust registry: bless/inspect/snapshot round trip on nt; registry on a world-writable dir ⇒
  invalid with the ACL reason; blessed file with CRLF edit ⇒ "changed since you blessed it".
- Parity (all OS): three `protect_trust_registry.py` copies byte-identical; vendored resolver
  candidates == `local_git.WINDOWS_GIT_CANDIDATES`.

### 3.2 (B2) Trusted Git binary resolution on Windows

Baseline: draft PR #749. The design below is what the reviewed version must satisfy; deltas
from the draft are marked **Δ**.

**Closed list (nt), in order; nothing else is ever considered:**

1. `C:\Program Files\Git\cmd\git.exe`
2. `C:\Program Files\Git\bin\git.exe`
3. `C:\Program Files (x86)\Git\cmd\git.exe`

Derive the drive and `Program Files` roots from `SHGetKnownFolderPath(FOLDERID_ProgramFiles
{905E63B6-C1BF-494E-B29C-65B732D3D21A})` and `FOLDERID_ProgramFilesX86
{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}`, **not** from `%ProgramFiles%`/`%SystemDrive%`
(environment is attacker-influenced). **Δ** No `LocalAppData\Programs\Git` candidate: that
directory is user-writable by design, which is exactly what the POSIX list excludes
(`~/.local/bin` is not a candidate there either). Per-user Git installs fail closed with:
"Dex needs Git installed for all users (the default 'Install for all users' option of Git for
Windows, which places it under Program Files). Dex found a per-user Git but will not use it."
Doctor check `git.trusted` surfaces the same text with tier 3.

**Resolution steps (each fails closed):**

1. Never consult `PATH`, `os.defpath`, `shutil.which`, `PATHEXT`, or the current directory.
   Never accept a relative path, a `\\?\` / `\\.\` / UNC spelling, or a component containing
   `~` followed by a digit (8.3 alias) in the *input*. Git-Bash (`/c/Program Files/…`) and
   Cygwin (`/cygdrive/c/…`) spellings are mapped to the closed list textually **before** any
   filesystem call (as in #749) — but only when `sys.platform == "win32"`; MSYS/Cygwin Pythons
   are unsupported (section 4) and get `RuntimeError("unsupported Python build")`.
2. Open the candidate with `CreateFileW(GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING,
   FILE_FLAG_OPEN_REPARSE_POINT)`. Query `FileAttributeTagInfo`: if
   `FILE_ATTRIBUTE_REPARSE_POINT` is set ⇒ refuse ("trusted Git path is a link"). **Δ** This
   catches junctions and AppExecLinks, which `Path.is_symlink()`/`resolve()` do not report.
3. `GetFinalPathNameByHandleW(VOLUME_NAME_DOS)` must equal the candidate after
   `os.path.normcase` (case-insensitive compare; the final name is the on-disk long name, so an
   8.3 or differently-cased *input* that nevertheless opened the right file is accepted, while
   any reparse substitution along the path shows up as a different final path ⇒ refuse). **Δ**
   The draft relies on `resolve(strict=True)` then list membership; keep that as a second check
   but the handle-derived final path is the authority.
4. Each **parent directory** of the candidate (`Git\cmd`, `Git`, `Program Files`) is opened with
   `FILE_FLAG_BACKUP_SEMANTICS|FILE_FLAG_OPEN_REPARSE_POINT` and checked: no reparse attribute;
   `file_is_private(owner_policy="admin")` (3.1.1) — owner ∈ {Administrators, SYSTEM,
   TrustedInstaller}, no foreign write ACE. **Δ** This is the Windows analogue of the POSIX
   "system directory" assumption and is the reason `LocalAppData` cannot qualify.
5. The file itself: `file_is_private(owner_policy="admin")`; first two bytes read through the
   handle are `MZ` (PE image) — rejects `.cmd`/`.bat`/shell shims even if someone renamed one
   to `git.exe`. **Δ**
6. Size sanity: 4 KiB ≤ size ≤ 64 MiB.
7. Return the **final path** from step 3 (never the input spelling) and cache it for the
   process; the cache is keyed on `(final_path, FileIdInfo, size, mtime)` and re-verified
   (steps 2–3 only) before every `subprocess.run`, closing the check→exec window to the extent
   Windows allows (the binary's directory is admin-only writable, so a swap requires admin).

**Environment for Git on nt (`git_env`):** `SYSTEMROOT` (from `GetSystemWindowsDirectoryW`, not
env), `PATH` = `<git>\cmd;<git>\mingw64\bin;<SystemRoot>\System32` only, `HOME` unset (Git falls
back to `USERPROFILE`, which we do not pass; `GIT_CONFIG_GLOBAL` already points at the null
device), `GIT_CONFIG_GLOBAL=NUL` (Git for Windows treats `/dev/null` and `NUL` equivalently;
use `os.devnull`), `core.hooksPath=NUL` likewise via `os.devnull`. `pass_fds` must be `()` on nt
(`subprocess` raises otherwise) — callers that pass descriptors must fall back to temp files
on nt.

**`scripts/dex_update_bridge.py`:** keeps refusing nt (section 5 changes only the message).
`scripts/release_fleet_executor.py` reuses the bridge resolver and stays POSIX-only.

**Cannot be enforced (document in `local_git.py` docstring):** an administrator can plant
anything; TOCTOU between the final re-verify and `CreateProcess` is bounded, not eliminated;
Windows has no execute bit so `os.access(X_OK)` is not used as evidence; Git's own
`mingw64\bin\git.exe` (what `cmd\git.exe` launches) is trusted transitively via the directory
ACL check, not hashed.

**Tests (B2):**

- All OS (with `ctypes` calls monkeypatched behind a `win_handles` fake): closed list only;
  PATH/cwd/`LOCALAPPDATA`/`ProgramFiles` env injection ignored; relative, UNC, `\\?\`, 8.3
  inputs refused; Git-Bash and Cygwin spellings mapped; `MZ` check; size bounds; final-path
  mismatch refused; parent reparse refused; non-admin owner refused; POSIX behaviour unchanged.
- Windows-only: real Git for Windows on the runner resolves; a junction `C:\Program Files\Git2
  → Git` is refused; a copy of `git.exe` under `%LOCALAPPDATA%\Programs\Git\cmd` is refused with
  the per-user message; `git_env` runs `git --version` successfully with the closed
  environment.

### 3.3 (B3) Windows equivalent of the `dir_fd` / `O_NOFOLLOW` race-safe chain

**Design: handle-anchored verification, not descriptor-relative opening.** Win32 has no public
`openat`; `NtCreateFile` with `OBJECT_ATTRIBUTES.RootDirectory` does, but it is an undocumented
ABI and a security reviewer cannot sign off `ctypes` structures against it without a large
test surface. The equivalent guarantee is obtained from the *opened handle*:

`core/utils/win_handles.py` (nt-only import; POSIX callers never import it):

```
open_directory(path) -> DirHandle           # CreateFileW(FILE_LIST_DIRECTORY, share R|W|D,
                                            #   OPEN_EXISTING, BACKUP_SEMANTICS|OPEN_REPARSE_POINT)
                                            #   → refuse if FileAttributeTagInfo has REPARSE_POINT
                                            #   → record final_path (GetFinalPathNameByHandleW),
                                            #     volume serial + file id (FileIdInfo)
open_chain(root: DirHandle, parts) -> DirHandle
                                            # for each part: open root.final_path + "\" + part as above;
                                            #   require its final_path == expected (normcase);
                                            #   require same volume serial as root; close the parent
open_beneath(dir: DirHandle, name, *, write=False, create=False) -> int (CRT fd)
                                            # CreateFileW(dir.final_path\name, access, FILE_SHARE_READ|FILE_SHARE_DELETE,
                                            #   CREATE_NEW if create else OPEN_EXISTING, OPEN_REPARSE_POINT)
                                            #   → refuse REPARSE_POINT (any tag whose IsReparseTagNameSurrogate bit
                                            #     0x20000000 is set; cloud-placeholder tags 0x9000xxxA without that bit are
                                            #     allowed so OneDrive-hydrated vaults still work — the file is then read,
                                            #     which hydrates it)
                                            #   → require final_path == dir.final_path\name (normcase) and same volume
                                            #   → msvcrt.open_osfhandle(handle, O_RDONLY|O_BINARY or O_WRONLY|O_BINARY)
                                            #   → os.fstat(fd) gives st_ino/st_dev from FileIdInfo for identity checks
final_path(handle) -> str ; same_volume(a, b) -> bool ; volume_supports_acls(handle) -> bool
```

Why this is race-safe enough: every property we assert is read **from the handle we then
use** (final path, reparse tag, identity, ACL). A path component swapped to a junction between
two of our opens changes the final path of the next open, which we compare; a file swapped after
our open is irrelevant because we read/write through the already-open handle; identity is
re-checked by `fstat` before and after I/O exactly as the POSIX code does today.

**Name comparison policy:** `os.path.normcase` (case-insensitive, backslash-normalised). If a
vault directory is case-sensitive (WSL-created), two names differing only by case would both
match; the inventory already reports case-fold collisions as errors (`filesystem.py:42-51`) and
the lifecycle refuses to plan over them, so this is not a new hole. 8.3 aliases never appear
because inventory paths come from directory listings, and an alias supplied externally fails
the final-path compare.

**Where it is used:**

| Caller | POSIX | nt |
| --- | --- | --- |
| `filesystem._open_beneath` | unchanged | replace the `:147-171` branch with `open_chain` + `open_beneath(write=False)`; fstat regular-file check unchanged |
| `integration_credentials` | unchanged | 3.1.2 |
| `credential_remediation` | unchanged | 3.1.3 |
| `trust_registry` | unchanged | 3.1.4 |
| `transaction/engine._target_matches_planned_content` | unchanged | `open_beneath` on the vault handle |
| `path_safety.unsafe_existing_parent` | unchanged | add: on nt, treat `st_file_attributes & FILE_ATTRIBUTE_REPARSE_POINT` with a name-surrogate `st_reparse_tag` as "symlinked parent" (pure `os.lstat`, no handles — this is advisory pre-check code) |
| `ledger._check_existing_directory`, `bridge.py:324`, `engine.py:610-615` `is_symlink()` sites | unchanged | same `st_reparse_tag` treatment via a shared `path_safety.is_name_surrogate(lstat_result)` |

**Explicit fail-closed policy where no equivalent exists:**

- Any write that today uses `os.replace(src, dst, src_dir_fd=…, dst_dir_fd=…)` or
  `os.link(..., src_dir_fd=…)` is performed by **final path** with readback verification
  (3.1.2). There is no atomic *relative* rename; the readback is the compensating control.
- `os.mkdir(part, dir_fd=…)` ⇒ `CreateDirectoryW(final_path\part)` then re-open and verify.
- Volumes without persistent ACLs, remote drives, and any handle whose final path begins with
  `\\` (UNC) or `\\?\Volume{` (unmounted volume GUID path) ⇒ refuse for security-module files
  with the plain message in 3.1.6.
- If `ctypes` fails to load `kernel32`/`advapi32` (should not happen) ⇒ every nt security
  operation refuses with "Windows security checks are unavailable in this Python build".

**Tests (B3, Windows-only; the fake-backed unit tests run everywhere):**

- Junction as intermediate component ⇒ `open_chain` refuses; symlink (Developer Mode on the
  runner; skip with `UNKNOWN` if unavailable) ⇒ refuses; junction inside the vault pointing to
  another in-vault directory ⇒ refuses (final path mismatch).
- Cloud placeholder tag (simulated via fake) ⇒ allowed.
- Swap race: open dir, replace a child directory with a junction, `open_beneath` ⇒ refused.
- Identity: `os.fstat` on the returned fd yields non-zero `st_ino` and stable `st_dev` across
  two opens; differs across two distinct files.
- Case/8.3: `PROGRA~1`-style component ⇒ refused; differently-cased existing name ⇒ accepted.

---

## 4. (C) Supported Windows setups

### 4.1 Support tiers

| Setup | Tier | Meaning |
| --- | --- | --- |
| Windows 10 22H2+/11, native **PowerShell 5.1 or 7**, python.org **3.12 or 3.13** (win32 build), Git for Windows installed for all users, vault on a local **NTFS** drive | **Supported** (after Phase 7) | Full-vault install, update, rewind, Doctor, MCP servers, hooks. |
| Same, launched from **Git Bash** (`uname -s` = `MINGW64_NT-*` or `MSYS_NT-*`) with the **same win32 Python** | **Supported as a launcher** | `install.sh` runs; everything Dex writes into config uses Windows paths (`.venv\Scripts\python.exe`). The Python found must be win32 (`sys.platform == "win32"`), not MSYS2's `/usr/bin/python`. |
| **`py` launcher** present | Supported as a *locator* | `py -3.13`/`py -3.12 -c "import sys;print(sys.executable)"` resolves the real interpreter; the resolved path is what Dex records. `py.exe` itself is never written into `.mcp.json` or hooks. |
| Python **3.14+** | Allowed with warning | "Dex has not been tested with Python 3.14 yet; 3.12 or 3.13 is recommended." Never refuse on a newer minor. |
| Python **≤ 3.11** on Windows | Unsupported | Refuse: repo targets 3.12 (`pyproject.toml:2`); `install.sh:101` currently allows 3.10+ — raise the Windows floor to 3.12 (macOS/Linux floor stays whatever #755 lands). |
| **Microsoft Store Python** | Unsupported | Detect: `os.path.normcase(sys.base_prefix)` contains `\windowsapps\` or `pythonsoftwarefoundation.python`. Refuse with 4.3-W2. Reason: AppExecLink aliases are reparse points, per-app AppData virtualisation redirects writes, and the interpreter path is not stable for `.mcp.json`. |
| **Cygwin** shell or Cygwin/MSYS2 Python (`uname -s` = `CYGWIN_NT-*`; `sys.platform in {"cygwin","msys"}`) | Unsupported | Refuse with 4.3-W3. Cygwin does not translate `/c/...` arguments for native Python; `fcntl`, uid semantics and paths all diverge from both nt and POSIX. |
| **WSL 1/2**, vault under the Linux filesystem (`/home/...`) | Linux tier (Deferred today per `docs/HARNESS-PORTABILITY.md`) | Treated as Linux; not a Windows setup. |
| **WSL**, vault under `/mnt/<drive>` (DrvFs/9p) | Unsupported | Refuse: `flock` and `chmod` semantics are emulated, hard links may fail, and Windows apps (Cursor, Granola) see a different path. Message 4.3-W4. |
| Vault on **OneDrive/Dropbox-synced** folder | Allowed with warning (all OS) | Placeholder files are hydrated on read (3.3). Warn once: sync clients can rewrite files between Dex's check and use; Dex refuses rather than guesses when that happens. |
| Vault on **FAT/exFAT**, network share, or a case-sensitive (WSL-flagged) directory | Unsupported | Refuse (3.1.6 / 3.3). |
| ARM64 Windows | Supported when the above hold | python.org ships ARM64 builds; Git for Windows runs under emulation or native. No special handling; CI does not cover it (say so in README). |

Background automation (launchd) and Apple Calendar remain macOS-only in every tier; Windows
Task Scheduler support is **not** part of this spec (README says so, section 5).

### 4.2 Detection (`core/utils/platform_support.py`, plus the bash pre-checks in `install.sh`)

`platform_support.probe() -> SupportReport` (stdlib only; safe to import before the venv exists):

```
family        = "windows" | "macos" | "linux" | "wsl" | "cygwin-or-msys" | "unknown"
shell_hint    = OSTYPE, MSYSTEM, `uname -s` when available (informational only)
python_source = "python.org" | "microsoft-store" | "conda" | "other"   (base_prefix heuristics)
python_ok     = sys.platform == "win32" and (3,12) <= sys.version_info[:2] and source != "microsoft-store"
vault_volume  = {"filesystem": "NTFS"|..., "acls": bool, "remote": bool, "sync_client": "onedrive"|"dropbox"|None,
                 "case_sensitive_dir": bool}      # via GetVolumeInformationByHandleW / GetDriveTypeW /
                                                  #   path prefix match against known sync roots / FILE_CS_FLAG via
                                                  #   `fsutil file queryCaseSensitiveInfo` equivalent
                                                  #   (NtQueryInformationFile FileCaseSensitiveInformation; if
                                                  #   unavailable → None, reported as unknown, not a refusal)
verdict       = "supported" | "supported-with-warnings" | "unsupported"
messages      = [W1.. as applicable]
```

`install.sh` (bash, before Python exists): `uname -s` prefix `CYGWIN` ⇒ print W3 and exit 1;
`MINGW*`/`MSYS*` ⇒ Windows launcher mode; `/proc/version` containing `microsoft` and vault path
under `/mnt/` ⇒ W4 and exit 1. After the interpreter is chosen: run
`"$PYTHON_CMD" -m core.utils.platform_support --json`; exit 1 on `unsupported` with its
messages; continue on warnings. `install.ps1` calls the same module. Doctor quick check
`platform.support` (4.6) reuses the report.

### 4.3 User messages (exact text)

- **W1 (Python version):** "Dex needs Python 3.12 or 3.13 on Windows. You have <ver>. Install
  from python.org and tick 'Add python.exe to PATH', then run the installer again."
- **W2 (Store Python):** "This Python came from the Microsoft Store, which keeps its files in
  a sandbox that Dex's tools cannot rely on. Install Python 3.12 or 3.13 from python.org
  instead, then run the installer again. You can keep the Store version; Dex will use the one
  from python.org."
- **W3 (Cygwin/MSYS Python or Cygwin shell):** "Dex on Windows runs in PowerShell or Git Bash
  with a Python from python.org. Cygwin isn't supported. Open Git Bash (installed with Git for
  Windows) or PowerShell in your Dex folder and run the installer there."
- **W4 (WSL on /mnt):** "Your Dex folder is on the Windows side of WSL (/mnt/...). Dex can't
  keep its files safe there. Either keep the folder in Linux (for example ~/Dex) and use Dex
  from WSL, or install Dex natively in Windows PowerShell."
- **W5 (per-user Git):** text in 3.2.
- **W6 (drive without permissions / network drive):** "Your Dex folder is on a drive that
  doesn't keep file permissions (<drive letter>: is <FAT32|exFAT|a network drive>). Dex stores
  keys and trust settings only on an NTFS drive such as C:. Move the folder and run the
  installer again."
- **W7 (sync folder, warning):** "Your Dex folder is inside <OneDrive|Dropbox>. That works, but
  if the sync client changes a file while Dex is updating, Dex stops and asks you to try again
  rather than guessing."
- **W8 (untested Python, warning):** text in 4.1.
- **W9 (ARM64, informational):** "You're on Windows for ARM. Dex should work but isn't tested
  there yet."

### 4.4 Path and interpreter recording rules on nt

- Everything persisted (`.mcp.json`, hooks, `System/.dex/topology.json`, harness profiles)
  records **Windows absolute paths** (`C:\Users\...`) even when installed from Git Bash; the
  installer converts with `cygpath -w` when it has a `/c/...` spelling. `provision.cjs` already
  emits `.venv\Scripts\python.exe` (`:728-729`).
- The interpreter recorded is `sys.executable` of the venv Python, never `py.exe` or a Store
  alias.
- Git Bash `HOME` may differ from `USERPROFILE`; Dex must derive the user profile from
  `SHGetKnownFolderPath(FOLDERID_Profile)` where it needs it (Granola paths in #753 already
  avoid `HOME`).

### 4.5 `install.sh` / `install.ps1` behaviours this policy adds to #755

- Refuse (exit 1) on W1–W4, W6; warn on W7–W9. All refusals also write to
  `System/.dex/install.log` (from #755) and print the log path.
- Python floor on Windows 3.12 (macOS/Linux floor unchanged by this spec).
- After venv creation, verify `.venv\Scripts\python.exe -c "import sys; print(sys.platform)"`
  prints `win32` (catches an MSYS2 `python3` shadowing python.org's).

### 4.6 Doctor on nt

- New quick check `platform.support`: `OK` / `BROKEN` (unsupported verdict, tier 3 with the
  message) / `OK` with warnings listed.
- `python.env` (`doctor.py:2644-2646`): probe `.venv\Scripts\python.exe` on nt.
- `git.trusted` (new): runs `trusted_git_binary()`; `BROKEN` tier 3 with W5 or the
  resolver's reason.
- `.env` authority check (`doctor.py:1444` returns `None` on non-posix): replace with the ACL
  verdict once 3.1 lands; until then report `UNKNOWN` with detail "file permissions are not
  checked on Windows yet" — never `OK`.

### 4.7 Tests (C)

- `core/tests/test_platform_support_probe.py` (all OS, monkeypatched `sys`/`os`/`platform`):
  each tier row yields the specified verdict and message ids; Store Python detected from both
  `WindowsApps` and `PythonSoftwareFoundation` prefixes; 3.14 → warning not refusal; Cygwin
  Python → W3; WSL `/mnt` → W4; sync roots detected from `OneDrive`/`Dropbox` env and path.
- `core/tests/test_install_windows.py` (extends #755): `uname -s CYGWIN_NT` ⇒ W3 exit 1;
  `MINGW64_NT` ⇒ launcher mode; venv Python not `win32` ⇒ fails with the log path.
- Windows CI: `install.ps1` and Git-Bash `install.sh` both succeed on `windows-latest` with
  setup-python 3.12 and 3.13 (matrix), and `python.env`, `git.trusted`, `platform.support`
  report `OK`.

---

## 5. (D) README vs `dex_update_bridge` — say the true support level

Facts: `scripts/dex_update_bridge.py:3250-3251` refuses Windows; it is the **one-time
bootstrap for pre-lifecycle vaults (v1.20-era)** and is not what a new Windows install uses.
The README (`:39-43`) advertises a one-line PowerShell install and (`:206`) Git Bash for the
repository installer, while today a Windows vault locks itself out on its second lifecycle
operation (1.1) and cannot resolve any `.env` credential (1.2). Until Phase 7 lands, the README
must say "preview", and the bridge must stop implying Windows is merely unsupported *by the
bridge*.

### 5.1 README changes (exact)

Replace `README.md:39-43`:

```markdown
**Windows — PowerShell (preview):**

```powershell
irm https://heydex.ai/install.ps1 | iex
```

Windows support is a **preview** while we finish the Windows-specific work
([status](docs/specs/windows-support-and-security.md#windows-support-status)). Install and
first setup work; updating, undoing an update, and connected-service keys are still being
completed. Requirements: Windows 10 22H2 or 11, Python 3.12 or 3.13 from python.org (not the
Microsoft Store), Git for Windows installed for all users, and a Dex folder on your local `C:`
drive. Calendar and background sync remain Mac-only.
```

Replace the Windows bullet at `README.md:206` with:

```markdown
- **Windows (preview):** Use **Git Bash**, supplied by Git for Windows, in that folder, or
  PowerShell with the [Quick install](#quick-install-claude-code-or-cursor) route. Git Bash
  must find the python.org Python (`python --version` prints 3.12 or 3.13); Cygwin and
  Microsoft Store Python are not supported. The installer checks this and tells you what to
  change.
```

Replace `README.md:248`:

```markdown
**On Windows?** Calendar connection is Mac-only (Apple Calendar). Windows calendar support is
not planned in this release; Dex will say so rather than pretend it checked.
```

Add a new section `## Windows support status` after "Help, updates and leaving an app"
(`README.md:72-78`) — this is the anchor the preview note links to; keep it a table, update it
per phase:

```markdown
## Windows support status

| Area | Status today |
| --- | --- |
| Install (`install.ps1`, Git Bash `install.sh`) | Preview — works on a clean Windows 11 with python.org 3.12/3.13 |
| First setup and daily use (notes, tasks, MCP tools) | Preview |
| `/dex-update` and `/dex-rollback` | Not yet — a fix for how Dex read and wrote its own record files on Windows is in progress |
| Connected-service keys (`.env`) and trusted local MCPs | Not yet — Windows file-permission checks are in progress |
| Older vaults (before v1.80) moving to the current update engine | Not on Windows — start from a fresh install |
| Calendar, background meeting sync, launch-at-login jobs | Mac only |
| Supported shells and Pythons | PowerShell or Git Bash; python.org Python 3.12/3.13. Not supported: Cygwin, Microsoft Store Python, WSL folders under `/mnt` |
```

Also change the Windows troubleshooting headers at `README.md:277` and `:293` to name Git
Bash **or PowerShell**, and add one item: "Windows: 'this Dex copy's update engine doesn't
match its release information' — you have hit the record-file line-ending problem above; the
fix arrives with the next release and repairs itself. Nothing in your notes is affected."

### 5.2 `scripts/dex_update_bridge.py:3250-3251` message (exact)

```python
if sys.platform.startswith("win"):
    parser.error(
        "this one-time bridge is for Dex vaults created before v1.80 on macOS or Linux. "
        "A Dex installed on Windows does not need it: run /dex-update instead. "
        "A pre-v1.80 vault cannot be moved to Windows with this tool; start from a fresh "
        "Windows install and copy your notes across."
    )
```

Update `core/tests/test_dex_update_bridge.py` accordingly. The `_installed_python` docstring
(`:1761-1768`) "Windows gets its own reviewed bridge" is replaced by "Windows vaults never
need this bridge (they are created post-foundation)".

### 5.3 Other truth surfaces

- `docs/HARNESS-PORTABILITY.md:23`: unchanged (already honest).
- `CHANGELOG.md`: the README change ships as a docs-only entry, headline "We now say plainly
  what works on Windows" (CFO test: no jargon).
- Each later phase edits only the status table rows it changes.

---

## 6. (E) CI: which Windows jobs become required, and when

Today's required contexts are `quality` and `test-results` (`scripts/configure-branch-protection.sh`
floor; `docs/merge-gates.md` still names `pr-report`, which the script comments say nothing
reports — leave that fix to its owner). `portable-plugin-platforms (windows-latest)` is a
release `needs` dependency, i.e. effectively required for release but not for merge.

| Job | Workflow | Content | Becomes required |
| --- | --- | --- | --- |
| `windows-install` | `.github/workflows/windows-install.yml` (#752) | Git-Bash `install.sh` + `install.ps1` on `windows-latest`, matrix Python 3.12/3.13 | **After Phase 3** has been on `main` with 10 consecutive green scheduled runs: flip `continue-on-error: false`, add to `configure-branch-protection.sh` contexts and `docs/merge-gates.md`, and update `core/tests/test_windows_install_workflow.py` (which today asserts it cannot be required) in the same PR. |
| `windows-core-tests` | new `.github/workflows/windows-core.yml` | `pytest -m windows_supported core/tests core/mcp/tests` on `windows-latest` (marker added to every test in sections 2, 3, 4 plus the transaction/lifecycle suites) | **After Phase 2** is green on main for 10 consecutive runs. Required for merge from then on. |
| `windows-security` | same workflow, second job | The Windows-only tests of 3.1–3.3 (need real junctions, `icacls`, Git for Windows) | **After Phase 6** and the security reviewer's sign-off; required for merge and added to `build-release` `needs`. |
| `portable-plugin-platforms (windows-latest)` | `ci.yml` | unchanged | Already a release gate; add to merge-required set at Phase 7 (it is fast and stable). |
| nightly `windows-fleet` | `nightly-quality.yml` | full `install.sh`/`install.ps1` → `/dex-update` → `/dex-rollback` journey on a fresh runner against the latest tag | Never required for merge; failure opens a `dex-cards` card (private) — never a public issue. |

Rules: all actions SHA-pinned; `permissions: contents: read`; `persist-credentials: false`;
no `pull_request_target`; installer steps blank `GITHUB_TOKEN`/`GH_TOKEN` (as #752 does).
A required Windows job that is *skipped* must fail closed via the same `if: ${{ !cancelled() }}`
+ guard pattern `test-results` uses (`ci.yml:237-250`).

"Green" means: job success **and** the Doctor JSON produced in the job reports no `BROKEN`
for `lifecycle.byte-mode`, `platform.support`, `python.env`, `git.trusted`.

---

## 7. (F) Phases

Every phase: one PR (or one stacked pair where noted), CHANGELOG entry in house voice when
user-visible, `docs/architecture/INVENTORY.md` regenerated if paths change, new tests marked
`windows_supported` where they can run on nt. "Gate" names who must approve beyond normal
review.

### Phase 0 — preconditions (in flight, not this spec)

Land #748 **before or with** #754; land #755, #752, #753; land d2 and #749 after security
review **with the 3.2 deltas applied to #749** (or land #749 as-is and treat Phase 6 as the
hardening — reviewer's call; record it in the PR). Gate: security reviewer for d2/#749.

### Phase 1 — byte-exact reads (A, part 1)

Files: `core/utils/os_flags.py` (+`binary_read_flags`), `core/lifecycle/filesystem.py`,
`core/transaction/engine.py` (`_target_matches_planned_content`), `core/update/anchor_generation.py`,
`core/tests/test_lifecycle_filesystem_binary_read_flags.py`,
`core/tests/test_update_anchor_binds_release_manifest_digest.py`,
`core/tests/test_transaction_engine_planned_content_probe.py`.
Acceptance: tests in 2.10 (platform-independent set for this phase); `windows-install`
advisory run shows the lifecycle suite's CRLF failures gone except those needing Phase 2;
inventory on a Windows autocrlf checkout classifies release files as `stock` via
`crlf_normalized_sha256` (existing test extended with a `0x1A` binary fixture).
Gate: none beyond review. **Must not ship in a release without Phase 2** (it would change
recorded digests without the repair path) — mark the CHANGELOG entry "held until the Windows
record repair lands" or land 1+2 in one release.

### Phase 2 — Windows byte-mode migration (A, part 2)

Files: `core/lifecycle/byte_mode.py` (new), `core/lifecycle/cli.py`, `core/lifecycle/service.py`
(`_prepare`), `core/lifecycle/engine.py` (`rewind_adoption` guard), `core/utils/doctor.py`
(`lifecycle.byte-mode`), `core/portable_contract.py` if a new classified path is needed (it is
not: `System/.dex/**` is runtime), `docs/dex-doctor-spec.md` (check registry),
`docs/Dex_System/Updating_Dex.md` (+ bridge copy under `06-Resources/Dex_System/`, kept
byte-identical), `CHANGELOG.md`, tests in 2.10.
Acceptance: all 2.10 tests; a fixture vault with CRLF-tailed activation + receipt (checked into
`core/tests/fixtures/byte-mode/`) repairs and updates end-to-end on the Windows advisory job;
rollback restores byte-identical originals; idempotency test.
Gate: none beyond review; Doctor owner reviews the check wording.

### Phase 3 — supported setups and truthful docs (C + D)

Files: `core/utils/platform_support.py` (new), `install.sh`, `install.ps1`, `core/utils/doctor.py`
(`platform.support`, `python.env` nt path, `.env` `UNKNOWN`), `README.md` (5.1),
`scripts/dex_update_bridge.py:3250` (5.2), `core/tests/test_dex_update_bridge.py`,
`core/tests/test_platform_support_probe.py`, `core/tests/test_install_windows.py`,
`.github/workflows/windows-install.yml` (Python matrix 3.12/3.13), `CHANGELOG.md`.
Acceptance: 4.7 tests; both installers green on `windows-latest` for 3.12 and 3.13; README
table present; bridge test updated.
Gate: founder reads the README wording (non-technical check).

### Phase 4 — Windows handle-verified open (B3 foundation)

Files: `core/utils/win_handles.py` (new), `core/path_safety.py` (`is_name_surrogate`),
`core/lifecycle/filesystem.py` (nt branch → helper), `core/transaction/engine.py`
(`_target_matches_planned_content` nt path), `core/lifecycle/ledger.py`, `core/lifecycle/bridge.py`,
`core/lifecycle/engine.py` (reparse-aware `is_symlink` sites), `core/tests/test_win_handles_*.py`
(fake-backed, all OS) and `core/tests/windows/test_win_handles_real.py` (nt only),
`docs/transaction-core-design.md` (Windows section).
Acceptance: 3.3 tests; inventory of a vault containing an in-vault junction reports the entry
as `symlink` kind and refuses to hash through it on nt; no behaviour change on POSIX (existing
suite green).
Gate: **security review** of `win_handles.py` (ctypes prototypes, error handling, share modes,
reparse-tag policy including the cloud-placeholder allowance).

### Phase 5 — credentials and trust on Windows (B1)

Stacked pair: 5a `core/utils/win_security.py` (ACL model, 3.1.1) with fake-backed tests;
5b adoption in `integration_credentials.py`, `credential_remediation.py`, `trust_registry.py`,
canonical `protect_trust_registry.py` + regeneration, `core/utils/doctor.py` (`.env` ACL
verdict, `customizations.mcp` hint), `docs/credential-remediation.md` (Windows section: what is
and is not enforced), `CHANGELOG.md` ("Connected-service keys work on Windows").
Depends on: d2 merged; Phase 4.
Acceptance: 3.1.7 tests; `probe_atomic_migration` all-true on the runner's NTFS; a Windows
`.env` key resolves for a real integration test (Todoist mock); trust bless/inspect/snapshot on
nt; three guard copies identical; README table rows updated.
Gate: **security review** (ACL policy, owner policy choice, refusal messages, journal schema v2).

### Phase 6 — trusted Git hardening (B2)

Files: `core/utils/local_git.py` (3.2 deltas over #749), `core/utils/doctor.py` (`git.trusted`),
canonical `protect_trust_registry.py` resolver parity test, `core/tests/test_local_git.py`
(extend), `core/tests/windows/test_local_git_real.py`, `CHANGELOG.md` if the per-user-Git
refusal is user-visible (it is: "Dex asks for Git installed for everyone on Windows").
Acceptance: 3.2 tests; `git.trusted` OK on the runner; per-user copy refused.
Gate: **security review**; founder decision recorded on the `LocalAppData` refusal (4.3-W5)
since it affects who can install.

### Phase 7 — CI promotion and support-level flip (E + D)

Files: `.github/workflows/windows-install.yml` (`continue-on-error: false`, required),
`.github/workflows/windows-core.yml` (new, `windows-core-tests`, `windows-security`),
`.github/workflows/nightly-quality.yml` (`windows-fleet`), `scripts/configure-branch-protection.sh`,
`docs/merge-gates.md`, `core/tests/test_windows_install_workflow.py`,
`core/tests/test_branch_protection_script.py`, `core/harnesses/registry.json` (windows
`release_ready` evidence note), `README.md` (status table → "Supported" rows; drop "(preview)"),
`CHANGELOG.md` ("Dex supports Windows").
Preconditions: Phases 1–6 on main; 10 consecutive green scheduled runs of each promoted job.
Acceptance: branch protection lists the new contexts; a deliberately failing Windows test blocks
a probe PR; README and `docs/specs` status agree.
Gate: founder (support promise), security reviewer (that `windows-security` covers 3.1–3.3).

### Dependency graph

```
#748 ─┬─► #754
      ├─► Phase 1 ─► Phase 2 ─► Phase 3 ─► Phase 7
d2 ───┼─► Phase 4 ─► Phase 5 ─────────────┘
#749 ─┴─► Phase 6 ────────────────────────┘
```

---

## Appendix A — Windows constants used above

```
FILE_FLAG_OPEN_REPARSE_POINT   0x00200000     FILE_FLAG_BACKUP_SEMANTICS   0x02000000
FILE_ATTRIBUTE_REPARSE_POINT   0x00000400     FILE_LIST_DIRECTORY          0x00000001
FILE_SHARE_READ 0x1  FILE_SHARE_WRITE 0x2  FILE_SHARE_DELETE 0x4
OPEN_EXISTING 3      CREATE_NEW 1
GetFileInformationByHandleEx classes: FileBasicInfo 0, FileStandardInfo 1,
  FileAttributeTagInfo 9 (FileAttributes, ReparseTag), FileIdInfo 18 (VolumeSerialNumber, FileId 128-bit)
GetFinalPathNameByHandleW flags: FILE_NAME_NORMALIZED 0 | VOLUME_NAME_DOS 0  (returns \\?\C:\...; strip \\?\)
IsReparseTagNameSurrogate(tag): tag & 0x20000000
IO_REPARSE_TAG_SYMLINK 0xA000000C   IO_REPARSE_TAG_MOUNT_POINT 0xA0000003   IO_REPARSE_TAG_APPEXECLINK 0x8000001B
IO_REPARSE_TAG_CLOUD family 0x9000xxxA (not name surrogates)
GetVolumeInformationByHandleW: FILE_PERSISTENT_ACLS 0x8 ; GetDriveTypeW: DRIVE_REMOTE 4
SE_FILE_OBJECT 1 ; OWNER_SECURITY_INFORMATION 0x1 ; DACL_SECURITY_INFORMATION 0x4
ACCESS_ALLOWED_ACE_TYPE 0 ; INHERIT_ONLY_ACE 0x8
Well-known SIDs: Administrators S-1-5-32-544 ; SYSTEM S-1-5-18 ; TrustedInstaller S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464
FOLDERID_ProgramFiles {905E63B6-C1BF-494E-B29C-65B732D3D21A} ; FOLDERID_ProgramFilesX86 {7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}
FOLDERID_Profile {5E6C858F-0E22-4760-9AFE-EA3317B67173}
msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY) → CRT fd usable with os.read/os.fstat/os.close
Python: os.stat_result.st_reparse_tag (nt, 3.8+), stat.FILE_ATTRIBUTE_REPARSE_POINT, os.path.isjunction (3.12+)
```

## Appendix B — Test fixtures to add

- `core/tests/fixtures/byte-mode/activation.crlf.json`, `receipt.crlf.json`,
  `event.crlf.json` — canonical records with `\r\n` tails (generated by a helper in the test to
  avoid committing CRLF bytes that autocrlf could rewrite: **store them LF in git and add the
  `\r` in the test**).
- A 4 KiB binary blob containing `0x1A` at offset 100 for the Ctrl-Z truncation test.
- `core/tests/windows/` package with `pytest.importorskip("msvcrt")` at module level; every
  test there is also marked `windows_supported`.

## Appendix C — Decisions the security reviewer must confirm

1. Cloud-placeholder reparse tags (non-name-surrogate) are **allowed** through `open_beneath`
   (3.3). Alternative: refuse and require the user to "always keep on this device".
2. Trusted-binary owner policy = {Administrators, SYSTEM, TrustedInstaller}; no per-user Git
   (3.2). Alternative: allow `LocalAppData\Programs\Git` when ACL-private to the user, labelled
   "reduced assurance" in Doctor.
3. Deny ACEs ignored and no group expansion in `file_is_private` (3.1.1).
4. Rewind of pre-migration capped-entry snapshots is refused rather than warned (2.2).
5. Ledger byte-normalisation (2.2) is acceptable under "events are never rewritten" because
   content identity and commitments are unchanged and the action is logged in the marker.
