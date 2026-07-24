# PR #141 (brain/vault split) — reconciliation against main

**Date:** 2026-07-23
**Branch analysed:** `feat/brain-vault-split` (PR #141, 49 commits, opened 2026-07-14, held)
**Compared against:** `origin/main` @ `72c4172`, latest release tag **v1.69.0**
**Written on:** `reconcile/brain-vault-split-141` (isolated worktree; no code changed)

---

## The short version (plain English)

**Almost all of PR #141 is already in Dex.** Between 20 and 22 July, five pull requests
(#154, #157, #161, #164, #165) deliberately rebuilt this branch's work on top of everything
that had shipped since — the team called them "PR-0" through "PR-4", and PR #161 says so in
its own description: *"Ported from the proven #141 branch and re-authorized against everything
shipped since."* It went out in releases v1.63.0 and v1.64.0. The rebuilt version is bigger and
safer than the original: the migrator on main is 2,347 lines against the branch's 1,551, and it
has protections the branch never got.

**A second, larger thing also happened.** Dex now has one "safe door" that every change goes
through — the lifecycle engine shipped across v1.65.0–v1.68.0. Preview, back up, apply, check,
receipt, undo. PR #141's own updater was written before that existed and would replace it.
That part of the branch is not behind; it is pointed at an architecture Dex no longer uses.

**So: do not merge this branch, and do not rebase it. Close it.** Merging or rebasing 49
commits across 62 files would undo real security work that shipped after it — including a
safety check on Dex's own tool calls and the release-awareness notice that stops Dex updating
itself silently.

**What is genuinely still missing is small — three things:**

1. **Existing users have no guided way to get the new layout.** The machinery is built and
   tested, but nothing connects it to the update flow. Today `/dex-doctor` tells a user to run
   `/dex-update`, and `/dex-update` has no idea what it is talking about. Only re-running
   `install.sh` actually converts a vault. *Medium — the biggest remaining piece of real work.*
2. **Personal instructions can be lost on a later update.** The conversion correctly moves a
   user's own instructions into their own file, but nothing puts them back into `CLAUDE.md`
   the next time Dex updates. This must be fixed before the new layout is switched on for
   anyone. *Small.*
3. **The update guide still describes the old way of working.** 765 lines telling users about
   a merge-based update that no longer exists. *Small, writing only.*

Plus one unrelated tidy-up the branch happens to have solved well (two flaky tests).

**Recommendation: abandon the branch and cut four small, fresh pull requests** in the order
below. Total remaining work is roughly one focused build session, not a nine-day programme.

---

## 1. What actually happened on main, 14–23 July

| Release | Date | Relevant PRs | What landed |
|---|---|---|---|
| v1.63.0 `c28a352` | 20 Jul | #153, #154, #155, #156, #158 | **Portable ownership contract** (`core/portable_contract.py`) — the five-class boundary the split needs; founder-content strip; dual-baseline preservation bridge |
| v1.64.0 `47c5c4c` | 21 Jul | #157, #159, #160, #161, #162, #163, #164, #165 | **Transaction core** (`core/transaction/*`); **the Brain/Vault migrator**; **the split-aware updater**; **fresh-install convergence + docs bridge** |
| v1.65.0 `01fd722` | 21 Jul | #166, #167, #168 | Read-only vault inventory + classifier; release-catalog generator; adoption plan + Doctor probes |
| v1.66.0 `ff7c41f` | 22 Jul | #169, #170, #171 | Double-authorized adoption engine; rewind-by-receipt; SQLite snapshot adapter |
| v1.67.0 `549a448` | 22 Jul | #172, #173, #174, #175 | Tamper-evident lifecycle ledger; Doctor five-group UX; hostile-vault gate |
| v1.68.0 `3da970b` | 22 Jul | #176, #177, #178 | **Frozen lifecycle API v1**; **every lifecycle path routed through one executor**; catalog adoption |
| v1.69.0 `affd207` | 22 Jul | #179–#184 | Architecture inventory + drift gate; DEX-CORE-MAP; skill overhaul |

The five PRs that are literally this branch, re-cut:

- **#154 (PR-0)** — *"The shared spine for three tracks: the Brain/Vault split (rebuilding #141)…"*
- **#157 (PR-1)** — *"the one-writer-at-a-time lock (ported from the proven #141 design)"*
- **#161 (PR-2)** — *"Ported from the proven #141 branch and re-authorized against everything shipped since."*
- **#164 (PR-3)** — *"the #141 poison-pill, permanently fenced"*
- **#165 (PR-4)** — fresh-install convergence + the brain-docs bridge

`docs/architecture/DEX-CORE-MAP.md` on main confirms the resulting architecture as **SHIPPED**:
lifecycle engine (v1.65–v1.68), transaction core (v1.66), portable ownership contract (v1.64+).

---

## 2. Slice-by-slice verdict

### D1 — Migrator + ownership layer

**Verdict: already in main, in a stronger form. Nothing here to salvage.**

| Branch artefact | Status on main | Evidence |
|---|---|---|
| `core/migrations/v1-to-v2-brain-vault-split.cjs` (1,551 lines) | **Already in main** at 2,347 lines (#161, v1.64.0) | Same modes (`--dry-run/--auto/--resume/--restore/--status`), same phases P0–P9, same journal/lock/sentinel design |
| `core/update/ownership.{cjs,json}` — 5 classes + deny list | **Superseded** by `core/portable_contract.py` (#154, v1.63.0) | Same five classes (`brain`/`vault`/`seed`/`generated`/`runtime`), same hard-deny set, plus a CI gate (`scripts/check-portable-contract.sh`) that fails closed on any unclassified path. Main's version is Python, shared by three tracks; the branch's is Node, used by one |
| `core/update/owned-lock.cjs` | **Superseded** by `core/transaction/lock.py` (#157, v1.64.0) | Owner-safe fsynced lock with PID liveness; PR #157 credits the #141 design |
| Positive write authorization at migration time | **Already in main** | Main's migrator has `isMigrationProtocolWrite`, `loadPortableContract`, `assertNoSymlinkParents` — the branch has none of these by name |
| Secret hold-back / secret-safe restore | **Already in main, stronger** | Main's migrator has `containsSecretContent`, `isSecretLikePath`, `normalizeHeldBackPaths`; the branch's restore has no equivalent guard |
| `vault_schema: 1` stamping | **Already in main** | Migrator lines 1665–1668; supported range declared as `vault_schema_supported: ">=1 <2"` in `portable_contract.py` and the generated contract JSON |
| `stampPackageSupport()` (schema range into `package.json`) | **Now wrong** | Main declares the supported range in the ownership contract, not `package.json`. Landing this would create a second, competing source of truth |
| `scripts/make-aged-vault-fixture.sh` (163 lines) | **Already in main** at 192 lines | Same variants (`--with-merge-in-progress`, `--no-git`, `--huge`, second remote), plus more |

Functions present in main's migrator and absent from the branch's: `analyzeMigrationPlan`,
`assertNoSymlinkParents`, `containsSecretContent`, `isSecretLikePath`, `isMigrationProtocolWrite`,
`loadPortableContract`, `normalizeHeldBackPaths`, `readLockSnapshot`, `sameLockSnapshot`,
`processIsRunning`, `capabilityRoomState`, `parseTrackedIgnorePolicy`, and 16 more.
Functions present in the branch and absent from main: three (`p3CandidateFiles`,
`stampPackageSupport`, `walkVaultFiles`) — two are internal helpers, one is actively wrong.

**Every one of the branch's late hardening commits already has an equivalent on main:**
owner-safe locks, secrets and hooks kept out of vault commits, held-back state cleaned on
restore, positively authorized root writes, authenticated release history by remote URL,
symlink-parent containment.

---

### D2 — The updater

**Verdict: superseded. Main solved the same problem a different way, and main's way won.**

The branch's `core/update/apply-update.cjs` (1,487 lines, Node) does: staged extraction →
manifest-hash verify → back up user-modified brain files → journaled per-file swap →
blob-safe prune → seed-if-absent → regenerate `CLAUDE.md` → update installed history.

Main's `core/update/apply_update.py` (480 lines, Python) does the same job in a quarter of the
code, because the hard parts are delegated:

- Release identity is verified against an immutable annotated tag *and* an official-origin
  regex before anything is read (`verify_release_ref`, `OFFICIAL_REMOTE`).
- The write plan is built entirely from ownership verdicts — any path the contract refuses
  aborts the whole update (`build_update_plan`, `update_write_verdict`).
- Every mutation goes through `core/transaction/engine.Transaction`, which snapshots, applies,
  verifies, and rolls back atomically. `Transaction.begin()` re-validates *every* entry before
  the first byte is written.
- User-modified brain files are not backed up and replaced — they are simply **kept**
  (`plan.kept`), which is a stronger promise than the branch's backup-first design.

**Why main's won, concretely:**

1. **One engine, not two.** PR #177 (v1.68.0) routed *every* lifecycle path — install, update,
   adopt, self-heal, undo — through a single executor behind a frozen API (`core.lifecycle.service`,
   `api_version = "1.0.0"`). The branch adds a second, parallel update path in a different
   language. That is exactly the seam #177 closed.
2. **Receipts and rewind.** v1.66.0/v1.67.0 added a tamper-evident receipt ledger and
   rewind-by-receipt. The branch has journals and an installed-history file, but no receipts.
3. **Release tag naming.** The branch mints `dist-vX.Y.Z` via a new `.github/workflows/release.yml`.
   Main already mints `dist/release/vX.Y.Z-<short>` inside `ci.yml`'s `build-release` job and
   pushes it. Two incompatible schemes; main's is live and shipped.
4. **The skills.** The branch rewrites `/dex-update` (1,075 lines removed) and `/dex-rollback`
   (885 lines removed) to drive `apply-update.cjs`. Main's `/dex-update` is a 79-line skill that
   drives the lifecycle service and its five-group preview. Landing the branch's version would
   tear out the shipped safe door.

Also superseded on this slice:

- **Opt-in vault auto-commit** — already in main at `.claude/hooks/vault-autocommit.cjs`,
  383 lines to the branch's 278. Main's version uses the shared transaction `mutation.lock`
  (so it can never race an update) where the branch uses its own `.migration-lock`, and adds a
  credential-shaped-content regex. `vault.auto_commit` already ships default-off in
  `System/user-profile-template.yaml`.
- **Topology-aware Doctor** — already in main: `brain.git`, `vault.git`, and
  `topology.migration-pending` probes, with a `_topology_state()` helper that distinguishes
  post-split / invalid-split / migration-in-progress / zip-or-manual / combined.
- **Topology-aware smoke** — main added a `topology` journey to `core/utils/smoke.py`.
- **Removing the SessionStart `git pull`** — already done, by #149 in v1.62.0, replaced with
  bounded release awareness. The branch's version of this change now *deletes* that
  replacement (see §4).

---

### D3 — Convergence, CI, docs

**Verdict: mostly already in main. One real gap.**

| Branch artefact | Status | Evidence |
|---|---|---|
| `install.sh` converges fresh installs to the split | **Already in main** (#165, v1.64.0) | `install.sh` lines 250–290 run the migrator with `--auto`, loop on exit code 75 for `--resume`, and confirm `System/.dex/topology.json` + `.dex/brain.git` |
| `docs/Dex_System/*` brain-owned bridge copies | **Already in main** (#165) | All 13 files present on main |
| CI ownership-validation gate | **Superseded** by `scripts/check-portable-contract.sh` (#154) | Completeness, release safety, dist drift, schema — fails closed |
| Tagging the stripped release commit | **Superseded** | `ci.yml` `build-release` mints and pushes `dist/release/v${VERSION}-<short>` |
| `verify-distribution.sh` extensions | **Superseded** | Main's is a different, later revision under a different release pipeline |
| **`Updating_Dex.md` rewritten for the split** | **STILL NEEDED** | Both copies on main are still **765 lines describing the old merge-based update**; the branch replaced them with 67 lines. Neither version is right now — main's is stale, the branch's describes the Node updater that lost |
| `docs/plans/2026-07-12-brain-vault-split-plan.md` (the v3 plan) | **Do not land** | It specifies the architecture main did *not* adopt. Landing it would actively mislead a future agent reading `docs/plans/` |

---

## 3. Invariants I1–I8, checked against main's shipped code

| # | Invariant | Held by main? | Where |
|---|---|---|---|
| I1 | Updates write only `brain` + `seed`-if-absent + `generated`, behind a deny boundary a fetched manifest cannot override | **Yes, stronger** | `portable_contract.update_write_verdict` — unclassified paths are *never* written; `Transaction.begin()` validates every entry before the first byte; hard-deny list covers `.env*`, `.git`, `System/credentials/`, keys, PEMs, tokens |
| I2 | Migration never modifies vault-class content | **Yes** | Migrator writes only `EXPLICIT_MIGRATION_WRITES` (`CLAUDE-custom.md`, `System/user-profile.yaml`, the report), each snapshotted first |
| I3 | Crash-safe by journal; reconciler; `--restore`; honoured lockfile | **Yes, stronger** | `core/transaction/journal.py` (fsynced, torn-tail truncation) + `lock.py` (owner-safe, PID liveness) + `Transaction.resume()` always rolls back a non-committed transaction. Migrator shares the same lock dir |
| I4 | Secrets never enter vault history | **Yes** | `containsSecretContent` / `isSecretLikePath` in the migrator; credential-shaped regex in `vault-autocommit.cjs`; `System/credentials/` hard-denied by the contract |
| I5 | Dual-topology; "migration pending" is first-class | **Partly** | Doctor's `topology.migration-pending` probe exists and reports BROKEN with a fix instruction — but the fix instruction points at a flow that does not implement it. **This is gap #1** |
| I6 | Bridge release deletes/renames/untracks nothing tracked | **Superseded** | Main deleted legacy tracked files deliberately, in two steps: #158 (dual-baseline preservation bridge, v1.63.0) then #160 (v2 baseline, v1.64.0), with `core/migrations/preserve_local_only_paths.py` preserving user-edited copies. Different answer, already shipped |
| I7 | No new runtime deps; stdlib-only; Windows-safe | **Superseded** | The migrator stayed dependency-free CJS, but the updater is now Python on the existing runtime. The constraint was about running *before* `npm install` in the old sequence — a sequence that no longer exists |
| I8 | Vault repo created with zero remotes | **Yes** | Migrator carries no remotes to the vault gitdir; `OFFICIAL_REMOTE` in the updater authenticates the brain's origin separately |

Against `Vault_Contract.md` v1: §2 dependency surface, §3 ownership boundary, §4 upgrade
policy, §5 the `CLAUDE.md` split, and §6 schema versioning are all implemented on main. §7
(migration) is implemented but **not reachable through a guided flow for existing users**. §8
(skills layering) remains deferred, as planned.

---

## 4. What would now be **wrong** to merge

Each of these is a live regression, verified by diffing the branch against current main:

1. **It deletes two shipped security hooks from `.claude/settings.json`.**
   - The SessionStart `update_verifier.py --session-start` call — the bounded release-awareness
     notice that replaced silent self-updating in v1.62.0 (#149).
   - The `PreToolUse` matcher `mcp__.*` → `dex-safety-guard.sh` — the safety check on Dex's own
     tool calls.
2. **It replaces the one shipped safe door with a second, parallel one.** The rewritten
   `/dex-update` and `/dex-rollback` skills drive `apply-update.cjs` instead of
   `core.lifecycle.service`, reopening the seam PR #177 closed.
3. **It un-sorts the path contract.** `core/path_contract.py` on the branch removes
   `sorted(constants)`, reshuffling every key in the generated
   `packages/dex-contracts/dist/paths.contract.json` — a cross-repo consumed artefact that is
   CI drift-gated on main.
4. **It resurrects deleted files.** The branch edits `System/user-profile.example.yaml`, which
   #153 removed from the shipped tree in v1.63.0 (replaced by `user-profile-template.yaml`).
   The full-tree founder-content gate would reject it.
5. **It introduces a competing release-tag scheme** (`dist-v*` in a new `release.yml`) alongside
   main's live `dist/release/v*` in `ci.yml`.
6. **It adds a plan document specifying an architecture Dex rejected**, into the same
   `docs/plans/` directory future agents are told to read for grounding.
7. **Mechanical scale.** The branch touches 62 files against a merge base nine days and seven
   releases old. Main has since rewritten `core/utils/doctor.py`, `core/utils/smoke.py`,
   `core/tests/test_distribution_artifacts.py`, `scripts/build-release.sh`, `ci.yml`, and
   `install.sh` — every one of which the branch also modifies. A rebase is not a merge conflict
   exercise; it is a rewrite against a different architecture.

---

## 5. What is genuinely still needed

### Gap 1 — Existing users have no guided route to the new layout *(the real remaining scope)*

**Verified:** nothing in a user flow calls the updater or the migrator at update time.

- `git grep "apply_update"` on main returns exactly two hits outside the module itself, both in
  `core/tests/test_apply_update.py`. **`core/update/apply_update.py` has zero production callers.**
- `git grep "v1-to-v2-brain-vault-split"` returns the manifest, two test files,
  `core/utils/doctor.py`, `install.sh`, and the fixture script. **No skill, no lifecycle service
  operation, no CLI invokes it.**
- `core/utils/doctor.py:2538` reports migration-pending as BROKEN with the message
  *"Dex needs its one-time brain/vault upgrade — run /dex-update; notes stay in place."*
- `.claude/skills/dex-update/SKILL.md` on main (79 lines) contains **zero** occurrences of
  "split", "brain", "migrat", or "topology". It routes everything through
  `core.lifecycle.service` and explicitly forbids falling back to an update script.
- `core/lifecycle/bridge.py` handles the legacy-updater → lifecycle-engine handoff. It does
  **not** handle combined → split topology.

So today an existing user who is told to run `/dex-update` gets an update that cannot do what
Doctor asked for. The only working conversion path is re-running `install.sh`, which runs the
migrator with `--auto` — undocumented as a migration route, and it converts without the dry-run
preview the contract requires (§7: *"run dry-run first… no non-technical user should be left to
debug a bad split"*).

This matches the v1.64.0 changelog exactly — *"New machinery (not yet switched on by default)"* —
so it is a known, deliberate state, not an oversight. But it is the whole remaining value of the
programme: the machinery is built, tested and shipped, and no user can reach it.

**Needs a product decision from Dave:** does the split get switched on for existing users
(guided, opt-in, dry-run first), or does it stay fresh-installs-only for another release cycle?

### Gap 2 — Personal instructions can be lost on a later update

**Verified:**

- The migrator does the right thing at conversion time: `phase6Rematerialize()` lifts the
  `USER_EXTENSIONS` block into `CLAUDE-custom.md` and calls `regenerateClaude(template, custom)`
  so the block stays live in `CLAUDE.md`.
- But `core/portable_contract.py:157` classifies `CLAUDE.md` as **`brain`**, and
  `MUTATION_POLICY["brain"] == "replace"` — always allowed, unconditionally.
- Nothing regenerates it. `git grep "CLAUDE-custom"` on main returns the migrator, the contract,
  tests, and documentation — **no runtime loader reads it.**

Consequence: the first update after conversion replaces `CLAUDE.md` with the shipped release
copy and the user's personal instructions go dark. Their text survives in `CLAUDE-custom.md`,
but nothing loads it.

**Scope note — this is not a live bug today.** The live route is the lifecycle service, whose
customization detection marks a modified shipped file as `stock-modified` → `CONFLICT` → held
back for review (`core/lifecycle/customizations.py`, `core/lifecycle/plan.py`). The failure
belongs to the split updater path, which is unwired. **It must be closed before Gap 1 is.**

### Gap 3 — The update guide describes a model that no longer exists

`docs/Dex_System/Updating_Dex.md` and its `06-Resources/` twin are both 765 lines describing the
old merge-based update. Neither mentions the lifecycle engine, previews, receipts, or rewind —
the things v1.65.0–v1.68.0 actually shipped and that `/dex-update` now does. The branch's
67-line replacement is closer in spirit but describes the losing updater, so it is a starting
point for a rewrite, not a patch to cherry-pick.

### Gap 4 — Two test-hygiene fixes worth keeping *(unrelated to the split)*

- `core/tests/test_dexdiff_adopt_profile_script.py` and `test_dexdiff_profile_adopt.py` on main
  still stand up a real `HTTPServer` on `127.0.0.1` in a background thread (lines 15–16, 62–63).
  The branch replaced this with an injected `sitecustomize.py` urllib stub — no socket, no
  thread, deterministic. Worth taking; sandboxed and CI runners dislike bound ports.
- `core/utils/smoke.py:114` `_trusted_node()` on main checks four fixed paths and returns `None`
  otherwise, so smoke degrades to UNKNOWN for anyone using nvm/fnm/Volta. The branch resolves a
  PATH candidate through symlinks while still rejecting protected roots. Worth taking.

---

## 6. Recommendation

**Abandon `feat/brain-vault-split`. Close PR #141 with a pointer to this document. Do not
rebase it.**

Rationale in one line: the branch's D1 is already in main in a better form, its D2 is aimed at
an architecture Dex replaced, its D3 is done except for documentation — and merging it would
regress shipped security work. Re-cutting the four remaining items fresh is smaller, safer, and
faster than reconciling 49 commits against seven releases of change.

Keep the branch itself (do not delete the ref) as the provenance record for the two adversarial
review rounds. Do **not** land `docs/plans/2026-07-12-brain-vault-split-plan.md` — this
reconciliation document supersedes it.

### The four PRs, in order

| # | PR | What it does | Rough size | Depends on |
|---|---|---|---|---|
| **1** | `docs: rewrite the update guide for the lifecycle engine` | Replace both copies of `Updating_Dex.md` with a short guide describing what actually ships today: preview → back up → apply → verify → receipt → rewind. Reconcile the `06-Resources/` and `docs/` copies so the bridge does not carry two truths | **Small** — writing only, ~150 lines net removed | Nothing. Ship first; it is wrong on main today |
| **2** | `fix: keep personal instructions alive across an update` | Make the user block survive. Either reclassify `CLAUDE.md` as `generated` and regenerate it from `CLAUDE-custom.md` in the update plan, or have the runtime read `CLAUDE-custom.md` as a data file. Recommend the former — it matches what the migrator already does and needs no loader change | **Small** — ~100 lines plus tests | Nothing |
| **3** | `feat: the guided upgrade for existing vaults` | Add a lifecycle-service operation that detects combined topology, runs the migrator `--dry-run`, renders the plain-English report for approval, then runs `--auto`/`--resume`, and hand `/dex-update` a branch for it. Make Doctor's migration-pending message true | **Medium** — ~400–600 lines plus journey tests; the migrator itself needs no changes | PR 2. **Needs Dave's go/no-go on switching the split on for existing users** |
| **4** | `test: de-flake the DexDiff and smoke fixtures` | Port the branch's socket-free DexDiff stub transport and the symlink-resolving `_trusted_node()` | **Small** — ~150 lines, tests only | Nothing. Ship any time |

### What to do next

1. Post this document on PR #141 and close it.
2. Ship PRs 1 and 4 immediately — both are self-contained and neither touches the engine.
3. Ship PR 2 next; it is the precondition for turning anything on.
4. Ask Dave the one product question before starting PR 3: **do existing users get offered the
   new layout in the next release, or does it stay fresh-installs-only for another cycle?**

### Method note

Every claim above was checked against code on `origin/main` @ `72c4172`, not against the PR
description or the changelog — both of which predate the overlapping work. Where a claim rests
on absence (no caller, no loader), it was established with `git grep` across the whole tree and
the negative result is quoted inline.
