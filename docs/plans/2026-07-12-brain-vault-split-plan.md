# Brain/Vault Split — Implementation Plan (v3, build contract)

**Status:** approved-for-build. Design adversarially reviewed by two independent
models (Opus deep-reasoner; GPT-5.6 Sol read-only) — both verdicts
"proceed with changes"; all accepted changes folded in below (provenance §11).
**Authority:** `Vault_Contract.md` v1 (ratified 2026-06-18), Lane F deliverable #2.
Goal set by Dave 2026-07-12: brain/PARA separation with a seamless upgrade for
current users.
**Branch:** `feat/brain-vault-split` (worktree `dex-core-brainsplit`).

---

## 1. The design in one paragraph

**The inversion, delivered as a bridge release.** The user's existing Dex directory
*becomes* the vault — their own private git repo with real history over their own
content (today they have none: PARA is gitignored). The brain (shipped code/skills/
docs) stays physically in place; its transport becomes a **fresh, sanitized hidden
gitdir** (`.dex/brain.git`, containing only release-lineage objects) and all future
updates are **manifest-driven staged file replacement** — extract → verify → journaled
swap — never a merge. Two repos, two lineages, one directory. Nothing the user
touches moves; every existing path keeps working; merge conflicts become structurally
impossible; updates physically cannot write outside the brain manifest.

Phase 2 (separate lane, deferred): physical brain relocation to `~/.dex`, `DEX_VAULT`
unification, semantic folder registry, skills path abstraction, File Ledger UI.

## 2. Non-negotiable invariants

I1. Updates write ONLY ownership-`brain` + `seed`(-if-absent) + `generated` paths,
    behind a **hardcoded deny boundary** (never `.git`, `.dex/*.git`, PARA roots,
    `System/credentials`, `.env*`, path traversal, symlinked parents) that a fetched
    manifest cannot override.
I2. The migration never modifies vault-class file content. It does not move or
    delete docs, does not re-litigate merge-resolved brain files (reports them), and
    snapshots anything it rewrites (CLAUDE.md, .gitignore).
I3. Crash-safe by journal: fsync'd phase journal written BEFORE every mutation;
    startup reconciler completes or reverses half-states; `--restore` returns the
    pre-migration tree; a concurrency lockfile is honored by all v2 git-touching
    hooks/skills.
I4. Secrets never enter vault history: rewritten root `.gitignore` (vault-serving) +
    `.git/info/exclude` (machine layer) + warn-only secret scan before the first
    snapshot. Reports/backups never include credential file contents.
I5. Dual-topology: every piece of v2 code works pre- and post-split ("migration
    pending" is a first-class state surfaced by session-start + doctor + updater —
    NOT keyed off "update available", since package.json is already v2 after the
    silent pull or a refused migration).
I6. **Bridge release:** v2.0 deletes/renames/untracks NOTHING tracked (38 paths under
    00-07 verified, incl. the seed trio; all Dex_System docs). Additions +
    modifications only. Ownership metadata — not git tracking — defines the boundary
    from v2.0 on. Release-branch cleanup only when pre-v2 population ≈ 0.
I7. No new runtime deps; migrator+updater are dependency-free Node stdlib .cjs (they
    run before `npm install` in the old update sequence — so migrator self-verification
    is stdlib-only; full doctor+smoke runs later in the update flow). Windows-safe
    (no symlinks; copy-then-swap fallback for locked renames). GPG/identity fallback:
    vault git ops pass `-c commit.gpgsign=false` and set a local identity if unset.
I8. The vault repo is created with **zero remotes** (ambient consumers like
    `/end-session` run `git push`; a carried-over remote would upload previously
    private content). The report explains how to add a private backup remote
    deliberately. `/end-session` v2: push only if a remote exists.

## 3. Load-bearing mechanics (all empirically verified 2026-07-12)

- Scoped checkout cannot touch non-manifest paths; does NOT delete upstream-dropped
  files → explicit blob-safe prune (`diff --diff-filter=D <installed> <target>`).
- Modify/delete merge conflicts are invisible to the old updater's conflict scanner
  and wedge it mid-merge → I6.
- **Inherited-ignore trap:** two repos share one worktree and one root `.gitignore`;
  the brain's v1 `.gitignore` ignores PARA, so a naive vault `git add -A` commits
  almost nothing (reproduced in sandbox). → At vault init the migrator REWRITES root
  `.gitignore` as the vault's (user-owned thereafter; brain-path excludes live in
  `.git/info/exclude`, machine-maintained).
- `v*` tags point at MAIN commits; the distributed tree is a different stripped
  commit force-pushed to `release` (release.sh:75 vs build-release.sh) → CI must also
  tag the stripped release commit (`dist-vX.Y.Z`); updater pins by OID and records
  identity in `System/.dex/installed-history.json` (OID + manifest hash + prev).
- SessionStart ships a silent `git pull` hook and fresh clones track `main` → I5;
  v2 removes the hook (today it can strand users mid-merge — bug class dies here).
- The old combined gitdir contains personal data in auto-save commits (tracked seeds)
  → brain.git is built FRESH by local ref-fetch of only the release lineage from the
  old gitdir (offline-safe, sanitized: `git init` + fetch of the release ref +
  `read-tree` so its index = exactly the release manifest); the old gitdir is renamed
  to `.dex/pre-split-archive.git` — inert, excluded from both repos, expiry noted,
  and it IS the total-restore anchor.

## 4. Migration algorithm (core/migrations/v1-to-v2-brain-vault-split.cjs)

Modes: `--dry-run` (default) | `--auto` | `--resume` | `--restore` | `--status`.
Phase journal `System/.dex/migration-v2-state.json` (fsync'd before each phase);
lockfile `System/.dex/.migration-lock`; topology sentinel written into both gitdirs
and `System/.dex/topology.json`.

P0  Preflight: git present; no in-progress merge (safe-abort or refuse with a
    plain-English fix); disk ≥ 2× vault size; write perms; record HEAD/branch/
    remotes/stashes. No git at all → ZIP path: offer conversion (fresh network
    fetch builds brain.git) or remain on the manual-update path — stated plainly;
    no half-topology.
P1  Dry-run report (always): what changes; user-modified brain files computed from
    the pre-update anchor (`backup-before-v2` tag vs old release merge-base — NOT
    the post-merge worktree, which the delivery choreography already resolved);
    remotes found (and that they will NOT be carried); what is untouched. Plain
    English → `System/migration-report-v2.md`.
P2  Snapshots + scan: files the migration rewrites (CLAUDE.md, .gitignore) →
    `System/backups/pre-split/`; warn-only secret scan of the soon-to-be-committed
    tree (results in report; never blocks; credential contents never copied).
P3  Build vault repo UNDER THE OLD TOPOLOGY (old .git intact and live):
    gitdir at `.dex/vault-staging.git`; REWRITE root .gitignore (vault-serving:
    secrets, node_modules, .venv, .dex/, .obsidian/workspace*); write info/exclude
    from ownership metadata (brain+runtime+generated paths); build the FULL initial
    commit ("Your vault — everything here is yours") in resumable batches (each
    bash invocation bounded; `--resume` continues; heavy GB work happens here,
    fully non-destructive).
P4  Build fresh brain gitdir `.dex/brain.git`: init → local fetch of the release
    ref from the old gitdir → `read-tree` (index = release manifest exactly) →
    add the official remote for future fetches → sentinel. No worktree config
    (`core.worktree` unset; brain ops always pass `--work-tree` explicitly).
P5  THE SWAP (destructive window = two renames, journal-bracketed):
    `mv .git .dex/pre-split-archive.git` → `mv .dex/vault-staging.git .git`.
    Windows copy-then-swap fallback with retries. Reconciler completes half-swaps.
P6  CLAUDE.md re-materialization: CLAUDE.md becomes a GENERATED file = brain template
    + inline user block from `CLAUDE-custom.md` (canonical store; created from the
    USER_EXTENSIONS content verbatim). Zero @import — works in Claude Code, Cursor,
    Pi. Stamp `vault_schema: 1` (user-profile.yaml); brain support range in
    package.json.
P7  Report-only pass: merge-resolved/modified brain files listed (doctor's
    core.drift owns them ongoing); NO doc moves, NO file replacement at migration
    time (bridge principle — the first post-split update handles brain-file
    convergence via its backup-first replace).
P8  Self-verify (stdlib only): both gitdirs healthy; vault HEAD contains the
    expected user files (count + spot byte-compares); sentinel + journal complete.
    Full doctor+smoke runs later in the update flow (after npm/pip), per I7.
P9  Finalize: journal complete; commit migration-era changes to vault; final report;
    auto-commit stays OFF by default (see §6).

## 5. New updater (core/update/apply-update.cjs) + skills

- Fetch `dist-v*` tag by OID into brain.git → **staged extraction** to `.dex/staging/`
  → manifest-hash verification → **backup user-modified brain files** (diff worktree
  vs `refs/dex/installed`; snapshot + report; never silently clobber) → journaled
  per-file swap into place (resumable) → explicit blob-safe prune of dropped brain
  files → seed-if-absent pass → regenerate CLAUDE.md (template + CLAUDE-custom) →
  npm/pip → regenerate core/paths.json + info/exclude → add-only MCP sync → update
  `refs/dex/installed` + installed-history.json → doctor + smoke.
- Ownership metadata derives from the EXISTING `System/.installed-files.manifest`
  (shipped per release) + a small override map `core/update/ownership.json`
  (classes: brain/vault/seed/generated/runtime) — one inventory, not two.
- Topology-aware (I5): pre-split + v2 code present → run the migrator first (no
  download needed when package.json already matches the target).
- `dex-update` SKILL.md → thin wrapper (check → confirm → run script → narrate).
  Explicit: once migration begins, recovery is ONLY `--resume`/`--restore`, never
  raw git. `dex-rollback` v2 → brain rollback via installed-history (staged swap to
  previous OID) + total pre-split restore (from the archive gitdir) for one release
  cycle; cleans up .dex/, CLAUDE-custom.md, backups when crossing the boundary.
  Both carry topology sentinels; refuse ambient-git recovery paths post-split.
- **Ambient-git audit** (build task): every shipped skill/hook that runs git
  (`end-session`, session-start pull, pull-request skill, etc.) becomes
  topology-aware; `/end-session` pushes only if the user added a remote.

## 6. Vault history UX (File Ledger seed)

Initial snapshot at migration = the versioning win, decoupled from ongoing behavior.
Ongoing auto-commit (SessionEnd hook): ships **default OFF** (`vault.auto_commit`,
user-profile.yaml) — `/end-session` already commits for its users; the desktop File
Ledger enables it in-app later. Migration report includes the one-line enable. When
on: `add -A && commit` (gpgsign off, local identity fallback), never pushes, skips
mid-merge/rebase, honors the migration lockfile, silent-degrades (feature_status).

## 7. Doctor + CI + install

- Doctor: topology-aware. New checks: vault.git health, brain.git health (incl.
  archive-expiry note), schema.match, migration-pending, auto-commit status.
  core.drift retargets to `refs/dex/installed` in brain.git post-split (pre-split:
  unchanged behavior).
- Smoke: new journey — simulated update on a temp fixture proves I1 + deny boundary.
- CI: ownership validator (every release-manifest path maps to exactly one class;
  delivery-sensitive grandfathered set explicit); release build additionally tags
  the stripped release commit (`dist-vX.Y.Z`); verify-distribution extended;
  existing path gates unchanged (no path moves).
- install.sh v2: fresh installs converge — clone → build vault repo + fresh brain.git
  seeded from the release lineage → same end state as migrated installs.

## 8. What ships when

- **v2.0.0 (this build):** all machinery above; BREAKING-flagged release notes (drives
  the old updater's migration hook); house-style changelog; Updating_Dex.md rewritten
  (§10.5); docs/ COPIES of Dex_System added (originals stay tracked/in place per I6 —
  every existing reference keeps working).
- **v2.0.1+ (first post-split updates):** brain-file convergence via backup-first
  replace; optional local cleanup of duplicated Dex_System docs via manifest rules.
- **Later major:** release-branch cleanup once pre-v2 population ≈ 0.

## 9. Verification gate before merge (non-negotiable)

Aged-vault fixture (`scripts/make-aged-vault-fixture.sh`): clone at an old tag + user
PARA content + edited tracked seeds + USER_EXTENSIONS + -custom skill + custom-* MCP
entry + .env/credentials + auto-save history + second remote + variants
(in-progress merge; no-git ZIP; iCloud-like path; huge-vault batch resume). Prove end
to end: delivery merge applies → migrator runs → §2 invariants hold → synthetic
v2.0→v2.0.1 update touches only brain paths (incl. staged-swap kill/resume) → both
rollback layers work → doctor green. Then Dave's real vault (COPY) before release.

## 10. Explicitly deferred (phase 2 lane, carded)

`~/.dex` physical relocation; DEX_VAULT/VAULT_PATH/7-convention unification;
folder-paths.yaml semantic registry; skills path abstraction (59 prose files);
File Ledger UI; vault remote/backup guidance flows; deliverable #3 (skills layering).

## 11. Review provenance (what changed and why)

- **Opus deep-reasoner:** delivery modify/delete jam (→I6 bridge); kill-mid-migration
  (→P3-before-P5 staging, journal, reconciler); brain index tracks PARA (→fresh
  read-tree gitdir); restore-not-really-no-op (→P2 snapshots + thin migration);
  @import breaks Cursor/Pi (→generated CLAUDE.md); auto-commit sync-dir risk
  (→default off); updater silent clobber (→backup-first); secret scan; Windows locks.
  Its updater-only de-scope was REJECTED: users have no content history today (PARA
  gitignored) — the vault repo is the user-felt value and the stated goal; with the
  two criticals engineered out, the risk asymmetry collapses.
- **GPT-5.6 Sol:** 38 tracked PARA paths not 3 (→I6 verified set); refused migration
  ≠ no-op + version-truth trap (→I5 first-class pending state); fsync journal +
  locks + sentinels (→I3); /end-session pushes (→I8 zero remotes); .dex/ exclusion
  gap + inherited-ignore trap — reproduced in our own sandbox (→§3 rewrite rule);
  sanitized fresh brain gitdir vs moved index/objects (→P4); tags point at main not
  the stripped tree (→dist-v* tagging + OID pinning); migration-before-npm ordering
  (→stdlib self-verify); hardcoded deny boundary; manifest reuse over parallel
  inventory; staged extraction + journaled swap; auto-commit removed from default;
  ZIP = convert-or-manual, no half-topology.
