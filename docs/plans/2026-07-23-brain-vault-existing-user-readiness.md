# Offering the new layout to existing users — readiness plan

**Date:** 2026-07-23
**Context:** follow-on from `2026-07-23-pr141-reconciliation.md`
**Baseline:** `origin/main` @ `72c4172`, release v1.69.0
**Goal:** close the six risks that stand between "the machinery is shipped but switched off"
and "we can safely offer existing users the move."

---

## The short version

Six risks were on the table. **Checking the code moved two of them off it.**

- **The desktop app doesn't care about any of this.** I checked: it runs no version-control
  commands at all, treats the vault as an ordinary folder, and hides dot-folders from the file
  tree. The new layout is invisible to it. *No work needed.*
- **Nothing in Dex uploads your vault anywhere.** The old worry was a shipped feature pushing
  your notes to a remote server after conversion. No shipped skill or hook on main runs a push
  or a commit except the local auto-save, which never pushes. *No work needed.*

That leaves **four small builds, one medium build, and one rehearsal.** Roughly a session and a
half of Codex work plus a supervised test run against a copy of a real vault.

The order matters: the four small ones make the move *safe*, the medium one makes it
*available*, and the rehearsal is the gate before anyone is offered it.

| Lane | Risk it closes | Size | Blocking? |
|---|---|---|---|
| **A** — Personal instructions survive updates | 1 | Small | **Yes** |
| **B** — Refuse to convert inside a cloud-synced folder | 2 | Small–medium | **Yes** |
| **C** — Manage the undo copy | 3 | Small | Yes, before switch-on |
| **D** — Make recovery obvious when something stops | 6 | Small | Yes, before switch-on |
| **E** — The guided upgrade itself | the actual feature | Medium | — |
| **F** — Rehearsal on real vaults | 4 | Half a day, supervised | **Gate** |
| ~~G~~ — Other Dex surfaces | 5 | **None — verified benign** | — |

---

## Lane A — Personal instructions survive updates *(blocking)*

**What's wrong.** The conversion correctly lifts a user's own instructions out of `CLAUDE.md`
into their own `CLAUDE-custom.md`, and re-inlines them so nothing changes on day one. But
`core/portable_contract.py:157` classifies `CLAUDE.md` as `brain`, and the mutation policy for
`brain` is `replace` — unconditionally. The next update overwrites the file with the shipped
copy and the user's text stops being read. Nothing anywhere loads `CLAUDE-custom.md` at
runtime — I checked the whole tree; every reference is the migrator, the contract, tests, or
documentation.

**What to build.** Reclassify `CLAUDE.md` as `generated` and regenerate it during the update
plan from the shipped template plus `CLAUDE-custom.md`. This is the right of the two options
because the migrator already contains exactly this function (`regenerateClaude`) — the update
path simply needs to call the same logic, so conversion and update produce byte-identical
results instead of two implementations that can drift.

**Where.**
- `core/portable_contract.py` — the `brain-claude-md` rule → `generated`.
- `core/update/apply_update.py` — `build_update_plan()` already routes a `generated` verdict to
  the `regenerated` bucket; give it the composition step.
- Shared regeneration helper so the CJS migrator and the Python updater cannot diverge — or, if
  a shared helper is disproportionate, a golden-file test asserting both produce identical output.

**Tests.** `test_portable_contract.py` (classification + red-when-removed), `test_apply_update.py`
(user block present before update → present after), and a migrate-then-update journey test.

**Size.** ~150 lines plus tests. **Delegate to Codex** (Sol, clear spec).

---

## Lane B — Refuse to convert inside a cloud-synced folder *(blocking)*

**What's wrong.** If someone keeps their Dex folder in iCloud, Dropbox, OneDrive or Google
Drive, the sync client copies files while the conversion rebuilds the folder underneath it —
a well-known way to end up with a half-copied mess. Dex already has a good detector for exactly
this (`detect_sync_folder` in `core/lifecycle/sqlite_snapshot.py`, covering Dropbox markers,
Apple's CloudStorage convention, OneDrive path and paired-folder identifiers, with honest
"unknown" handling). **The conversion tool never calls it.** I grepped: its only caller is the
SQLite backup path.

**Why it can't just import it.** The migrator is deliberately dependency-free CommonJS — it has
to run before Python is guaranteed available. So the fix is not a call, it's a shared source of
truth.

**What to build.**
1. Extract the marker table out of `sqlite_snapshot.py` into a data file (a JSON marker
   descriptor under `core/data/`), leaving the Python behaviour unchanged.
2. Add a small CJS reader in the migrator's P0 preflight that consumes the same file.
3. On detection: **refuse by default** with a plain-English explanation and the two safe options
   (move the vault out of the synced folder, or pause syncing for the duration). Allow an
   explicit override flag for someone who genuinely knows what they're doing — recorded in the
   report, never the default.
4. One shared test-vector fixture exercised from both languages, so the two readers cannot drift.

**Where.** `core/lifecycle/sqlite_snapshot.py`, new `core/data/sync-folder-markers.json`,
`core/migrations/v1-to-v2-brain-vault-split.cjs` (P0), plus the contract classification for the
new data file.

**Tests.** Extend `test_adoption_sqlite_snapshot.py` to read from the data file;
new migrator unit tests per provider; one integration test proving refusal leaves the vault
completely untouched.

**Size.** ~200 lines plus tests. **Delegate to Codex** (Sol).

---

## Lane C — Manage the undo copy *(before switch-on)*

**What's wrong.** The escape hatch is a copy of the old setup left at
`.dex/pre-split-archive.git`. Nothing expires it, cleans it up, reports its size, or tells the
user it exists. Two consequences: it occupies disk permanently (roughly the size of the vault's
prior history), and it contains old automatic snapshots that may hold personal content — so it
is a privacy surface as well as a storage one.

To be precise about what it does *not* break: after a successful conversion, `topology.json`
exists and Doctor returns `post-split` before it ever looks at the archive, so its presence does
not produce a false "incomplete" verdict on the happy path.

**What to build.**
1. A Doctor probe that surfaces the archive: present / age in days / size on disk, and states
   plainly that it is the one-command undo and when it stops being needed.
2. A retention decision — recommend **keeping it for one full release cycle after conversion**,
   then offering (never forcing) removal through the lifecycle service so the removal is
   transactional and receipted like every other change.
3. A line in the migration report explaining what the archive is, in the user's terms.

**Where.** `core/utils/doctor.py` (new probe alongside `_probe_brain_git`), a lifecycle
operation for the removal, migration report text.

**Size.** ~150 lines plus tests. **Delegate to Codex** (Terra — mechanical against a clear spec).

---

## Lane D — Make recovery obvious when something stops *(before switch-on)*

**What's wrong.** If the conversion halts, recovery is two specific commands (`--resume` or
`--restore`) and *only* those. Normal repair instincts — reinstalling, restoring from a backup,
or another AI agent reaching for raw version-control commands — make it worse. Today that
knowledge lives in the report; if the user or an agent doesn't read the report, it's invisible.

**What to build.**
1. Make Doctor's `migration-in-progress` and `invalid-split` verdicts state the exact recovery
   command and explicitly warn against manual repair.
2. Add the same warning to the top of the migration report, not buried.
3. Add a guard rail for agents: extend the existing safety hook so raw version-control
   mutation inside a vault holding a live migration lock is blocked with an explanatory message
   pointing at `--resume` / `--restore`.

Point 3 is the one that actually matters — Dex is usually being driven by an AI, and an agent
"helpfully" repairing a half-converted vault is the realistic failure, not a human doing it.

**Where.** `core/utils/doctor.py`, migration report generator,
`.claude/hooks/dex-safety-guard.sh`.

**Size.** ~120 lines plus tests. **Delegate to Codex** (Terra).

---

## Lane E — The guided upgrade *(the actual feature)*

**What's wrong.** Nothing connects the machinery to a user flow. `core/update/apply_update.py`
has zero production callers. Doctor tells users to run `/dex-update`; that skill routes
everything through the lifecycle service and contains no mention of migration. The only working
route is re-running `install.sh`, which converts with `--auto` — no preview, undocumented as a
migration path, and contrary to the contract's own rule that a dry-run must come first.

**What to build.** A lifecycle-service operation for the topology move, so it inherits the
shipped safe door rather than opening a second one:

1. Detect combined topology as part of the normal update read.
2. Run the migrator `--dry-run` and surface its report as a preview, in the same five-group
   shape `/dex-update` already renders.
3. Require explicit approval of *that* preview — reusing the existing approval-token mechanism,
   so a vague earlier "update Dex" cannot authorize a topology change.
4. On approval, run `--auto`, routing exit code 75 back through `--resume` (the loop `install.sh`
   already implements), and emit a receipt.
5. Teach `/dex-update`'s skill body the migration branch, in plain language.
6. Make Doctor's migration-pending message true.

**Where.** `core/lifecycle/service.py` (new operation behind the frozen API — note the API
version implications), `core/lifecycle/engine.py`, `.claude/skills/dex-update/SKILL.md`,
`core/utils/doctor.py`. **The migrator itself needs no changes.**

**Design constraint worth stating up front:** the frozen lifecycle API is at `1.0.0`. Adding an
operation is an additive change, but decide deliberately whether it lands as `1.1.0` or inside
the existing operation set before writing code.

**Size.** ~400–600 lines plus journey tests. **Delegate to Codex** (Sol — this is the one with
real design judgement in it, and it ships to users).

---

## Lane F — Rehearsal on real vaults *(the gate, not a PR)*

**What's wrong.** Everything the conversion has been proven against is synthetic — deliberately
messy, tested at 100,000-file scale, exercised with interrupted merges and missing version
control, but built by a script. Real vaults are messy in ways scripts don't imagine. The
original plan said exactly this: test against a copy of the real vault before release.

**What to do, in order.**
1. Take a **copy** of Dave's real vault. Never the original.
2. Run `--dry-run`. Read the report as a non-technical user would. Does it explain what will
   happen, in terms someone would actually act on?
3. Run `--auto` on the copy. Confirm: notes byte-identical, personal instructions still live,
   Doctor green, the vault's own history present and readable.
4. Run a synthetic update on top. Confirm Lane A holds — instructions survive.
5. Kill the process mid-conversion, deliberately. Confirm `--resume` finishes and `--restore`
   returns the copy to exactly its starting state.
6. Repeat the whole thing on one more real-shaped vault if a second is available.

**Output.** A short rehearsal report — pass/fail per step, with the dry-run report attached as
the artefact Dave reads to judge whether it's clear enough for a stranger.

**Needs Dave:** authorization to work against a copy of his real vault.

---

## Lane G — Other Dex surfaces: verified benign, no work

Checked rather than assumed:

- **`dex-desktop`** contains no reference to `brain.git`, `topology.json`, or the archive; runs
  **no version-control commands at all**; resolves the vault as a plain folder path
  (`main.js:1292`, `1411`, `1417`); and filters dot-entries out of the file tree
  (`main.js:1325`), so the new hidden folder never appears. The layout change is invisible to it.
- **No shipped skill or hook runs a push or a commit** on main. The only committer is
  `vault-autocommit.cjs`, which is default-off and never pushes. The "a shipped feature uploads
  your notes after conversion" risk — the original reason for the zero-remotes rule — has no
  live carrier.
- **Obsidian** ignores dot-folders by convention; the vault's own folders are untouched by the
  conversion.

If the desktop app later grows version-control features, this conclusion needs revisiting —
but nothing today needs changing.

---

## Sequencing

| PR | Lane(s) | Depends on | Size |
|---|---|---|---|
| 1 | **A** — instructions survive updates | — | Small |
| 2 | **B** — cloud-sync guard | — | Small–medium |
| 3 | **C + D** — archive lifecycle + recovery UX | — (pairs naturally; both touch Doctor and the report) | Small |
| 4 | **E** — the guided upgrade | 1, 2, 3 | Medium |
| — | **F** — rehearsal | 4 | Half a day, supervised |
| — | *switch on for existing users* | F passes | Decision |

PRs 1, 2 and 3 are independent of each other and can run in parallel lanes. They are also all
worth having **even if the split is never switched on for existing users** — Lane A is a latent
data-loss path for anyone who converts by re-running the installer today, and Lane B protects
those same people.

Running alongside, from the reconciliation document and unrelated to this sequence: the update
guide rewrite and the two test de-flakes.

**Operating model:** I plan and review; Codex writes. Every lane above has a clear enough
contract to delegate. I read each diff before it lands.

---

## Decisions I need from Dave

1. **Authorize the rehearsal against a copy of your real vault** (Lane F). Nothing else proves
   this is ready.
2. **Confirm the target:** is the goal to offer this to existing users in the next release once
   the gate passes, or to fix the safety lanes now and decide on timing separately? The plan
   works either way — PRs 1–3 are worth shipping regardless.

Everything else in here I'd treat as routine and just do.
