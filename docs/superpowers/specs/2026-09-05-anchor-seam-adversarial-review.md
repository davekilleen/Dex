# Adversarial review — the A2 seam addition for the release anchor

**Status:** Adversarial review for founder and build gate. Commissioned by
founder ruling 4 (2026-09-05) in
`docs/superpowers/specs/2026-09-04-customization-reanchoring-design.md`:
"the adversarial review is the gating item and must be scheduled before build
starts. Build does not proceed without it." This document is that review.
Grounded in the code as checked out on 2026-09-05 (HEAD `af52bb6`); every
claim cites file:line from the real implementation, not the design's
paraphrase. Baseline contract: `docs/customization-migration-threat-model.md`
(amendments A1–A3 binding).

**Verdict: APPROVE-WITH-CONDITIONS.** The seam addition is sound in shape —
the write-authority machinery it plugs into is genuinely fail-closed and
well-tested — but the design as written carries one proof hole (finding F1),
one reuse claim that does not survive contact with the code (F2), and one
consent claim that the existing implementation does not actually deliver
(F3). The conditions in §6 are the build gate.

---

## 1. The write authority's seams as implemented

The single sanctioned check is `core.portable_contract.update_write_verdict`
(`core/portable_contract.py:615`). It accepts exactly thirteen `operation`
values (`:629-644`); an unknown operation raises. Per branch, as implemented:

| operation | grant | refusal shape |
|---|---|---|
| `onboarding-provision` | exact-path set `ONBOARDING_PROVISION_PATHS` (`:542-563`, checked `:670`) | fail-closed (`outside-onboarding-provision`, `:678-684`) |
| `transition-capsule` | prefix `System/.dex/transition-capsules/` (`:572`, `:711-715`) | fail-closed |
| `transition-restore` | exact-path set `TRANSITION_RESTORE_PATHS` (`:573-578`) | fail-closed |
| `capability-state` | exactly `System/user-profile.yaml` (`:756`) | fail-closed |
| `onboarding-context` | exactly `System/user-profile.yaml` (`:796`) | fail-closed |
| `automation-ownership` | exactly `System/.dex/automation-ownership.json` (`:836`) | fail-closed |
| `analytics-receipt` | exactly `System/.dex/analytics-attempts.jsonl` (`:876`) | fail-closed |
| `mcp-registration` / `legacy-qmd-reconciliation` | exactly `.mcp.json` (`:912`) | fail-closed |
| `customization-migration` | seam list: prefix `System/.dex/customization-migrations/`, path `CLAUDE-custom.md` (`:565-567`, matched `:959-962`) | fail-closed (`outside-migration-seams`, `:971-977`) |
| `conflict-resolution` | rule-id set (`:1000-1007`) | **falls through** to the generic update policy (`:1039+`) when the rule doesn't match |
| `adoption-rewind` | rule-id set (`:1030-1037`) | **falls through** likewise |
| `update` (default) | `MUTATION_POLICY` by ownership class (`:530-536`, `:1047`) | `never` / `deny` / `unclassified-never-write` |

Hard-deny precedence holds in every branch (`is_denied` checked before any
grant; case-folded matching, `:1074-1091`). Normalization happens before
seam matching (`_normalize`, `:1065-1071`), so traversal and separator games
resolve first — verified empirically: `System/.dex/customization-migrations/../release-anchor.json`
normalizes to `System/.dex/release-anchor.json` and refuses
`outside-migration-seams`.

**The anchor path is refused everywhere today.** An exhaustive probe of
`System/.dex/release-anchor.json` (and a receipt sibling) across all thirteen
operations × exists∈{False,True} produced zero allowed verdicts. The path
resolves to `runtime-dex-dir` (`System/.dex` dir rule, `:322`) → mutation
policy `never` (`:535`).

**Confirmed: adding the anchor path is a frozen-contract change per A2.**
The seam list travels in the frozen JSON contract view
(`core/portable_contract.py:1294-1316`, emitted `:1398-1401`; committed at
`packages/dex-contracts/dist/portable-vault.contract.json`, whose
`customization_migration` block today reads exactly
`{version: 0, seam_prefixes: ["System/.dex/customization-migrations/"], seam_paths: ["CLAUDE-custom.md"]}`),
and is pinned verbatim by
`core/tests/test_portable_contract.py:640-646`
(`test_customization_migration_contract_view_is_frozen`). Any seam change
turns that test and the CI-gated dist view red. The design's premise stands.

**The enumeration is not the whole write surface.** Two sanctioned writers
bypass the verdict entirely and the review must name them so the anchor work
doesn't accidentally model itself on them: adoption receipts are persisted
post-commit by a dedicated direct writer with its own symlink checks
(`core/lifecycle/engine.py:606-646`), and the lifecycle ledger writes its own
records (`core/lifecycle/ledger.py:547`). "One write authority" is true for
transactional vault mutations, not for every byte the lifecycle lands on
disk. Condition C10 makes the anchor's receipt path explicit.

---

## 2. Attacks on the proposed seam

Format per attack: what the attacker does; what the current code plus the
proposed design do about it; verdict; the red-when-removed test that must
exist (the named check whose deletion must fail the test).

### 2.1 Surface 1 — planted or tampered anchor file

**Attack.** Write `System/.dex/release-anchor.json` directly (attacker,
sync-tool resurrection of an old anchor, or a confused backup restore),
carrying fabricated `path → sha256` rows.

**Code + design.** The design's defense is load-time re-verification: the
anchor is accepted only when its manifest binding equals the installed
manifest bytes' hash AND its catalog binding equals the installed catalog,
plus a self-hash — the same double-binding discipline
`load_release_baseline` applies to the catalog today
(`core/lifecycle/customizations.py:158-162` via `release_bytes_match`,
`core/lifecycle/catalog.py:370-383`). A fabricated anchor that binds to the
real manifest+catalog can only bless bytes matching its own rows; to bless
*tampered* bytes the attacker's rows must be self-consistent with the real
catalog binding, which reduces to the pre-existing accepted boundary: an
attacker who can rewrite manifest + catalog owns the baseline already
(nothing signs the catalog — `loads_catalog` checks self-hash and manifest
binding only, `catalog.py:385-395`).

**Verdict: defended-only-if** the consumer implements all three checks (both
bindings and the self-hash) and reads the file through the bounded,
symlink-refusing reader (`bounded_read` → `_open_beneath`,
`core/lifecycle/filesystem.py:201-223`, `:134-171`) with an explicit byte
cap, and any failure demotes to today's UNKNOWN with a *named* baseline
error, exactly as catalog failures do (`customizations.py:139-153`).
A malformed, oversized, non-UTF-8, or truncated anchor must land in
`ReleaseBaseline.errors`, never raise past the assessment.

**Tests (red-when-removed):** three separate tests, one per check — delete
the manifest-binding comparison, the catalog-binding comparison, or the
self-hash comparison in the consumer and the corresponding test (planted
anchor with that one binding wrong is silently ignored + error named) must
fail. Plus: a 17 MB anchor and a non-UTF-8 anchor each produce a named error
and today's classification, not an exception.

### 2.2 Surface 1b — anchor rows for paths the release tree ships but the user owns (found by this review)

**Attack.** None needed — a *legitimately generated* full-tree anchor is the
attack. `classify_release_state` consults `expected_hashes` **before** any
ownership branching: `customizations.py:262-270` returns
`stock-unmodified`/`stock-modified` for any path with an expected hash,
regardless of ownership class; the `brain`/`vault`/`seed` branches only run
when no hash exists (`:271-280`). Today's catalog rows are 27 brain-owned
payloads, so this order is unexercised. The proven release tree, however,
ships **seed** files (`03-Tasks/Tasks.md`, `System/pillars.yaml`, the PARA
READMEs — `portable_contract.py:238-277`) and legacy-tracked **runtime**
files (`System/usage_log.md`, `:306-307`). A whole-tree anchor therefore
reclassifies the user's *living* task file and usage log from
`canonical-customization`/`durable-state` to `stock-modified`, turning them
into divergences (`detect_customizations`, `customizations.py:288-289`) and
feeding user content into the modified-shipped-file capsule lane the design
says this unlocks.

**Verdict: undefended in the design as written.** The design's claim that
"`classify_release_state` needs no change" is only true if anchor rows are
restricted; unrestricted rows change the meaning of seed and runtime
classifications for every re-anchored vault.

**Test (red-when-removed):** generate an anchor whose source tree contains a
seed path and a runtime path; assert both keep their non-stock
classification after the anchor merges. Delete the row filter (condition C6)
and this test must fail.

### 2.3 Surface 2 — poisoned network fetch (and the local-source variant)

**Attack A (design's surface 2).** A malicious remote serves a poisoned
`dist/release/v*` tag during step 2c.

**Code + design.** The pinning stack is real: origin regex
`OFFICIAL_REMOTE` (`core/update/apply_update.py:34-38`) checked against both
configured and effective origin URL (`:691-695`); annotated-tag discipline,
tag→commit→tree binding, tree-manifest equality, and package-version
equality in `verify_release_ref` (`:698-779`); the release-awareness
transport pins `CANONICAL_REMOTE_URL` as a literal and refuses substitutes
(`core/utils/update_verifier.py:26`, `:700-710`) with proxy-env hygiene and
TLS-failure honesty (`:52-77`). A poisoned tag whose tree manifest doesn't
byte-match the locally installed manifest proves nothing.

**But the design's reuse claim fails against the code — two ways:**

1. **The channel pin rejects every old release.** `verify_release_ref`
   requires the commit to be the *current pinned target of the update
   channel* (`apply_update.py:742-757`: `commit in channel_commits` from
   `refs/remotes/...`). A vault re-anchoring its *installed* release — v1.92
   while the channel head is newer, which is the entire target population —
   fails this check. Step 2b as designed ("run through the full
   `verify_release_ref` discipline") almost never succeeds.
2. **The function is welded to the brain store.** It resolves everything
   through `_topology` (`:708`, `:636-688`), which requires an intact
   brain/vault split — precisely what the moved-vault case (step 2c's reason
   to exist) lacks — and reads refs from `brain_git`, not from the isolated
   evidence cache the fetch lands in.

So both 2b and 2c require a verification *variant*, which collides with the
design's own non-goal "No second verification stack." Left unspecified,
the variant is where a check quietly goes missing.

**Verdict: defended-only-if** the variant is specified as: the existing
function parameterized by git-dir (brain store or evidence cache), retaining
verbatim the origin pin (applied to the cache's remote / the literal fetch
URL), the tag-name regex, the annotated-tag and header discipline, the
tag→commit→tree binding, tree-manifest equality against the *installed*
manifest, and package-version equality — and replacing only the channel-head
equality with equality against the installed catalog's claimed version
(which is itself manifest-bound, `customizations.py:158-162`). One
implementation, one flag, never a re-typed copy.

**Tests (red-when-removed):** one test per retained check against the
evidence-cache path: wrong origin URL, lightweight (non-annotated) tag,
tag object not matching the pin, tree manifest differing from the installed
manifest by one byte, package version differing from the claimed version —
each must refuse. Deleting any single retained check in the variant must
fail its test. Plus the consent-ordering test: the fetch subprocess must be
unreachable before the fetch confirmation is recorded (threat model §7).

### 2.4 Surface 2b — the mutable installed ref as proof root (found by this review; most serious)

**Attack.** Step 2a trusts `refs/dex/installed` "when the tree's manifest
blob is byte-identical to `System/.installed-files.manifest`". The manifest
lists **paths only** (`_parse_manifest`, `customizations.py:97-113`; the
design itself says so at its §"Verified Baseline"). An attacker with brain-
store write access commits a tree containing the *same manifest blob* but
tampered blobs for `core/`, `.claude/hooks/`, anything — then repoints
`refs/dex/installed` (a plain mutable ref, moved by ordinary `update-ref`,
`apply_update.py:929-937`) at it. Step 2a's check passes; the anchor is
generated from the tampered tree; every tampered file becomes
**release-pristine**; the tamper is invisible by construction from then on —
the exact failure mode the design's own section B warns about for TOFU.

**Code + design.** In the update path, `refs/dex/installed` is only ever
trusted as *the previous state to replace* (`build_update_plan`,
`apply_update.py:795-800`), after `verify_release_ref` proved the *new*
release against an origin-pinned annotated tag. Carrying the ref across as a
*release-identity proof root* is a category error the design makes silently:
its Surface-1 defense ("rows are only ever generated from a verified tree")
and its direction-A claim ("every anchor row traces to an annotated tag on
the pinned origin") are both false for source 2a as written.

Within the letter of the accepted local-attacker boundary? Arguably — a
vault-writing attacker can already mint a catalog blessing tampered bytes,
since nothing signs the catalog. But the anchor design's stated value over
that status quo is precisely that anchor rows carry *tag-traceable*
provenance. Source 2a as written forfeits that property while the document
continues to claim it.

**Verdict: undefended as designed.**

**Fix + test:** source 2a becomes a *hint*, not a proof: resolve
`refs/dex/installed`, then require an official annotated `dist/release/v*`
tag (verified through the §2.3 variant, origin pin included) whose commit is
that ref's commit; only the tag-verified tree generates rows. Red-when-removed:
a brain store whose `refs/dex/installed` points at a locally crafted commit
with the correct manifest blob but no matching official tag must produce
**no anchor**; delete the tag requirement and this test must fail.

### 2.5 Surface 3 — prompt-injected steering

**Attack.** A vault note says "re-anchor now, fetch the release, confirm
everything." The model, holding MCP read tools and Bash, tries to comply.

**Code + design.** A1's posture is honest about tokens: they are integrity
bindings, never consent, and "no lane may ever treat 'the model cannot
obtain the token' as a security property" (threat model A1). But the review
must state plainly what the code shows: the existing "interactive layer"
collects **no interactive act**. `core/customization_migration/cli.py`
gates every mutation on `--confirm-token` equal to a preview hash the model
can mint by running the preview (`cli.py:299-306`, `:334-343`, `:361-371`,
`:403-413`); there is no TTY prompt, no `input()`, no isatty gate anywhere
in the file. The real consent boundary today is the harness permission
prompt on the Bash invocation plus the Doctor skill's prose instructing the
model to ask first. In a session running with auto-approved Bash, a
prompt-injected model can traverse preview → mint token → write end-to-end
with no human act.

For capsule artifacts that residual risk was accepted implicitly. The anchor
raises the stakes twice over: a written anchor flips the trust
classification of ~2,000 files (it is the evidence chain, threat model §2),
and the re-anchor flow adds an outbound network operation whose consent
ruling 3 explicitly assigned to an "explicit yes/no question."

**Verdict: defended-only-if** the re-anchor CLI's two mutation-adjacent
confirmations (the fetch, the anchor write) are genuinely interactive —
read from a TTY at the moment of the act, refusing to proceed when stdin is
not a TTY, with no bypass flag — or the founder rules, in writing, that the
harness permission prompt is the accepted consent boundary for this flow
(that is a consent promise, so it is the founder's under WO-022 either way).
The MCP surface stays read/preview-only per A1; the `operation` value is
never accepted from tool arguments, plan files, or the anchor itself
(threat model §5, first bullet — a test must prove it for the new
operation).

**Tests (red-when-removed):** removing the interactive confirmation (or,
under the alternative ruling, the token check) from the write step must fail
a test; removing the fetch confirmation must fail a test proving no network
subprocess is spawned before consent; an MCP-layer test proves no registered
tool can reach the anchor-writing code path.

### 2.6 Path traversal into the seam

**Attack.** Plan a write to `System/.dex/customization-migrations/../release-anchor.json`
(or the future anchor seam's equivalent) hoping the seam prefix matches
before normalization.

**Code.** `_normalize` runs before matching (`portable_contract.py:934-935`)
— verified empirically: the traversal form normalizes to the anchor path and
refuses. Root escape (`../x`) refuses `unclassified-never-write` (pinned by
`test_portable_contract.py:620-628`). The transaction engine independently
rejects non-canonical relatives (`path_safety.py:15-22`) at begin, snapshot,
and apply (`engine.py:228`, `:336`, `:371`) — the verdict is deliberately
never the sole path gate (threat model §6).

**Verdict: defended.** Test that must exist for the new seam: the traversal
form targeting the anchor via the migration seam (and vice versa) refuses;
deleting `_normalize` from the new branch must fail it.

### 2.7 Symlinked `System/.dex`

**Attack.** Replace `System/.dex` (or `System`) with a symlink pointing
outside the vault so the anchor write or read lands elsewhere.

**Code.** Writes: `unsafe_existing_parent` lstat-walks every parent and
refuses symlinks and non-directories (`path_safety.py:32-46`), enforced at
all three transaction phases (above); the update lane separately refuses a
symlinked `System/.dex` outright (`apply_update.py:638-641`). Reads: only if
the consumer uses `bounded_read`/`_open_beneath`, which opens descriptor-
relative with `O_NOFOLLOW` and refuses observed symlinks
(`filesystem.py:134-171`) — the manifest and catalog readers already do
(`customizations.py:117`, `:137`).

**Verdict: defended**, conditional on the consumer using `bounded_read`
(condition C7). Red-when-removed: a symlinked `System/.dex` makes the anchor
write refuse and the anchor read produce a named error; deleting the
symlink checks in either path must fail the tests (write-side deletion
already fails existing engine tests).

### 2.8 Case-insensitive filesystem collisions

**Attack.** On APFS (the primary install target), plant
`System/.DEX/Release-Anchor.json` or ask the verdict about a case-variant
path.

**Code.** Verdict-side matching is case-sensitive, so a case variant fails
to resolve (`ContractViolation` → refuse) or misses the seam → refuse:
fail-closed, verified empirically (`SYSTEM/.dex/...` →
`outside-migration-seams`). Hard-deny is deliberately case-folded
(`portable_contract.py:1074-1081`) so secret-suffix games still deny.
Read-side: on APFS a case-variant plant *is* the canonical file; the §2.1
binding checks are the defense, and the inventory walk already detects
case collisions (`detect_case_collisions`, exported at
`filesystem.py:238`).

**Verdict: defended.** Test: a case-variant anchor plan entry refuses under
the new operation (pin it so a future case-folding "fix" to seam matching
fails loudly rather than silently widening on case-sensitive filesystems).

### 2.9 Partial writes / crash between anchor and receipt

**Attack.** Crash after the anchor lands but before its receipt (or
mid-anchor), leaving evidence the flow can't account for.

**Code.** The transaction engine is atomic per file (temp + fsync + rename,
`engine.py:483-532`), journal-before-effect, byte-exact rollback; a
mid-write crash converges. If anchor and receipt are two entries in one
transaction, they commit or roll back together.

**Verdict: defended-only-if** both artifacts ride one transaction (or the
receipt uses the documented post-commit publication pattern with its
partial-state error class, as adoption receipts do —
`engine.py:80`, `:606-646` — and Doctor reports the
committed-but-receiptless state honestly). A dangling anchor with no receipt
is still safe *for trust* because trust derives from the anchor's own
bindings, not the receipt — which motivates C10 below.

**Test:** the existing `DEX_TX_TEST_STOP_AFTER` fault-injection seam
(`engine.py:83-85`) exercised at every new mutation seam (threat model §7),
converging to old-verified or new-committed.

### 2.10 Receipt forgery

**Attack.** Forge or replay `…release-anchor….receipt.json` to make a
never-consented anchor look consented, or to trick a later flow.

**Code + design.** Adoption receipts today are convenience/rewind evidence
persisted outside the verdict (`engine.py:606-646`) and strictly validated
on read (`engine.py:301-356`). The anchor design must keep the same
property: **no code path may read the anchor's receipt to establish trust**
— classification trust flows only from the anchor's bindings; the receipt is
audit trail. Then a forged receipt is noise.

**Verdict: defended-only-if** that property is stated and pinned.
**Test:** deleting the anchor but keeping (or forging) its receipt yields
today's UNKNOWN state; a test asserts the baseline consumer never opens the
receipt path.

### 2.11 Seam widening via directory-vs-file grants

**Attack.** The seam addition itself is the attack surface: grant
`System/.dex/` or a slashless prefix, and the "anchor seam" quietly
authorizes writes to the ledger, adoption receipts, health state, topology
marker — everything under `System/.dex/`.

**Code.** Two live hazards to copy-proof against:

1. **Prefix semantics.** Seam prefixes match by `startswith`
   (`portable_contract.py:960-961`); only the trailing slash prevents
   `System/.dex/customization-migrations-evil/…` from matching — pinned by
   `test_portable_contract.py:313-322`. The design's parenthetical
   "`System/.dex/release-anchor.json` (or its directory)" must resolve to
   **exact file paths** (or, if a directory is truly needed, a dedicated
   `System/.dex/release-anchor/` prefix with trailing slash and its own
   sibling-refusal test). A grant of `System/.dex/` is rejected by this
   review outright.
2. **The fall-through idiom.** The `conflict-resolution` and
   `adoption-rewind` branches fall through to the generic
   `MUTATION_POLICY` when their rule doesn't match
   (`portable_contract.py:1000-1007`, `:1030-1037` — no terminal refusal,
   execution continues at `:1039`), making those operations strictly wider
   than `update`. Harmless for the anchor path itself (runtime → `never`),
   but a new branch written in that style would let the anchor operation
   write brain and generated paths wholesale. The new branch must terminate
   with an explicit `outside-release-anchor` refusal, like
   `customization-migration` does (`:971-977`).

3. **Shared-seam consent bleed.** Appending the anchor to
   `CUSTOMIZATION_MIGRATION_SEAM_*` would let every *migration*-consented
   transaction (capsule create, staging, activation — all pass
   `operation="customization-migration"`: `capsule.py:673`,
   `staging.py:931`, `activation.py:802,926,983,1831`,
   `verification.py:590,703,1442`, `planning.py:154`) also write or
   overwrite the anchor under a consent the user gave for something else.
   The anchor gets its **own operation value** with its own enumerated
   paths.

**Verdict: undefended by the design text; fully addressable.**
**Tests (red-when-removed):** the frozen-view test updated deliberately in
the same change (its failure is the tripwire working); the new operation on
a brain path (`core/x.py`) refuses `outside-release-anchor` — deleting the
terminal refusal (reintroducing fall-through) must fail it; hard-deny wins
inside the new seam (mirror of `test_portable_contract.py:574-592`);
ordinary `update` still refuses the anchor path (mirror of `:343-349`);
`customization-migration` still refuses the anchor path (proves the seams
stayed separate); the trailing-slash sibling test if any prefix is used.

### 2.12 TOCTOU between verify and write

**Attack.** Change the manifest/catalog (or the anchor target) between the
step-3 preview and the step-4 write, so the consented bytes and the written
bytes diverge, or so a stale anchor lands on a changed vault.

**Code + design.** Three layers close this: (a) the anchor's content
derives from the verified tag tree plus manifest/catalog hashes captured at
generation — if manifest or catalog change after generation, the written
anchor simply fails its bindings on next load and is ignored with a named
error (fail-closed to today's state); (b) the confirm token must be the
anchor document digest shown in the preview, and the CLI writes exactly
those bytes — the existing pattern (`cli.py:299-306`); (c) the plan entry
carries `expected_absent=True` for a first anchor (engine re-checks at
snapshot and apply, `engine.py:339-345`, `:502-513`, hardlink-based
no-follow create `:508-513`) or `expected_current_sha256` for a
regeneration (engine aborts if the live file moved, `:346-357`, `:493-501`
— the A2-mandated engine capability, already built).

**Verdict: defended-only-if** (b) and (c) are required, not optional. A bare
unconditioned content write (which the engine permits) must not be used for
the anchor. **Test:** mutating the anchor target between preview and write
aborts the transaction; deleting the `expected_absent`/precondition from the
plan builder must fail it.

---

## 3. Fail-closed rules vs. the code paths that would implement them

The design states four fail-closed rules. Audited against the real code:

- **"No source verifies → no anchor → UNKNOWN."** Holds structurally:
  without anchor rows, brain files with no catalog hash classify `unknown`
  (`customizations.py:271-272`), sweep to exclusions
  (`core/customization_migration/inventory.py:775-791`), force completeness
  UNKNOWN (`service.py:93-109`), verdict follows completeness
  (`model.py:530-540`), and the capsule refuses
  (`capsule.py:148-149`, `:451-463`). No code path promotes on absence
  today. **But finding F1 (§2.4) breaks the rule's premise**: step 2a lets a
  *wrong* source verify. Fail-closed rules are only as good as what counts
  as verification.
- **"Anchor binding mismatch → ignored + named error."** Implementable
  exactly as the catalog does it (`customizations.py:139-153`, errors
  carried in `ReleaseBaseline.errors:46`). Condition C5 adds the check this
  review found missing from the design: anchor rows merge **only when the
  catalog/manifest pair already verifies** (`identity_state == "VERIFIED"`).
  Without that, an anchor could rescue a vault whose catalog fails
  verification — the anchor binding to the catalog's *bytes* is not the same
  as the catalog verifying against the *manifest*; requiring VERIFIED first
  closes the gap and keeps the anchor strictly subordinate.
- **"Bytes matching no proven hash → never pristine."** Holds:
  `classify_release_state` has no other pristine path (`:262-270`). The
  inverse hazard is §2.2: bytes matching a proven hash for a path the user
  owns. Condition C6.
- **"The flow writes exactly one artifact plus its receipt."** Enforceable
  only by the seam shape (exact paths, own operation, terminal refusal —
  §2.11) plus a test that the re-anchor plan builder emits exactly those
  entries. The design's phrase "or its directory" is the one place its own
  text invites a wider write than its own rule allows.

One further absence-promotes-trust hazard, stated for the record: the
`discover` early-bail (`inventory.py:491-492`) returns **zero exclusions**
when the baseline is unverified — upstream, `baseline-not-verified` forces
UNKNOWN anyway (`service.py:85-86`), so no promotion occurs, but any future
consumer reading `discovery.exclusions` alone would misread "no exclusions"
as clean. The anchor consumer must key off `identity_state` and
`completeness`, never off exclusion emptiness.

---

## 4. What the review confirms the design got right

For balance, and because these must not regress during build: the write
authority really is one function with enumerated operations and deny
precedence everywhere; the transaction engine really does enforce
authorize-before-write at three phases, symlink/traversal refusal via
`path_safety`, atomic applies, journal-before-effect, mode bounding
(`engine.py:192-197`), and content preconditions; the seam boundary really
is pinned by red-when-removed tests including the sibling-prefix refusal;
the frozen JSON view really exists and is drift-gated; the evidence
transport really is origin-pinned, bounded, fetch-only, and honest about
TLS interception (`update_verifier.py:59-77`). The anchor concept — carry
tag-verified proof across to the assessment baseline, subordinate to the
catalog, fail-closed on any binding failure — is the right shape. The
conditions below are about making the implementation match the concept.

---

## 5. Findings ranked

- **F1 (§2.4)** — step 2a's proof root is a mutable ref plus a paths-only
  manifest equality; a crafted local commit passes and gets tampered bytes
  blessed pristine. Contradicts the design's own provenance claim. Must be
  re-specified before build.
- **F2 (§2.3)** — `verify_release_ref` as-is rejects every old release
  (channel pin) and cannot run against the evidence cache (topology
  welding); the promised reuse is impossible without a specified variant,
  and an unspecified variant is where a check goes missing.
- **F3 (§2.5)** — the "interactive layer" the design leans on is, as
  implemented, token-echo with no interactive act; for a flow that flips
  ~2,000 files' trust state and performs a network fetch, that boundary
  must be made real or explicitly accepted by the founder.
- **F4 (§2.2)** — expected-hash rows override ownership classification;
  a full-tree anchor reclassifies the user's living seed/runtime files.
- **F5 (§2.11)** — "or its directory," shared seam lists, and the
  fall-through idiom are three concrete widening paths the build must
  explicitly avoid.

---

## 6. Verdict and conditions

**APPROVE-WITH-CONDITIONS.** The A2 seam addition may proceed to build only
when every box below is satisfiable in the implementation plan and satisfied
before merge. Each "test" is red-when-removed: the named check's deletion
must fail it.

- [ ] **C1 — own operation, exact paths.** A new `operation` value (e.g.
  `release-anchor`) whose branch grants exactly the anchor file path (and
  the receipt path if transactional), enumerated as `SEAM_PATHS`-style
  exact files — no `System/.dex/` grant, no slashless prefix; any prefix
  carries a trailing slash and a sibling-refusal test. The
  `customization-migration` seam list is not touched.
- [ ] **C2 — terminal refusal.** The new branch ends with an explicit
  `outside-release-anchor` refusal; it never falls through to the generic
  mutation policy. Test: the operation on `core/x.py` refuses; deleting the
  terminal refusal fails it.
- [ ] **C3 — frozen-contract discipline.** The seam constants, the frozen
  JSON view, the dist file, and the pinned view test
  (`test_portable_contract.py:640-646` pattern) all change in the same
  deliberate commit; deny precedence and ordinary-update refusal tests
  mirror the existing migration-seam suite (`:343-349`, `:574-592`,
  `:649+`).
- [ ] **C4 — source 2a re-specified (F1).** `refs/dex/installed` is a hint
  only; anchor rows are generated exclusively from a tree bound to an
  official annotated `dist/release/v*` tag verified with the origin pin.
  Test: a crafted installed-ref commit with the correct manifest blob and no
  matching official tag produces no anchor.
- [ ] **C5 — verification variant specified (F2).** One parameterized
  implementation of the tag discipline usable against the brain store and
  the evidence cache; retains origin pin, tag regex, annotated-tag and
  header checks, tag→commit→tree binding, tree-manifest equality against
  the installed manifest, package-version equality; replaces only the
  channel-head equality with version-equality against the installed
  catalog's claim; one red-when-removed test per retained check. The anchor
  merges only when the catalog baseline is already `VERIFIED`.
- [ ] **C6 — row filtering (F4).** Anchor rows are restricted to
  brain-owned paths (at generation or at merge — pick one, test both
  directions). Test: a seed-path row and a runtime-path row are inert; the
  user's `03-Tasks/Tasks.md` never classifies `stock-*` because of an
  anchor.
- [ ] **C7 — fail-closed consumer.** Anchor read via `bounded_read` with an
  explicit cap; manifest binding, catalog binding, and self-hash each
  independently red-when-removed; every failure (including oversized,
  malformed, non-UTF-8, symlinked) demotes to today's behavior with a named
  `ReleaseBaseline` error, never an exception, never a promotion.
- [ ] **C8 — consent made real (F3).** The fetch confirmation and the
  anchor-write confirmation are genuinely interactive (TTY-read, refusing
  on non-TTY, no bypass flag) — or the founder rules in writing that the
  harness permission prompt is the accepted boundary. Either way: the fetch
  subprocess is unreachable before fetch consent (test), the write is
  unreachable without the confirmation (test), no MCP tool reaches the
  write or fetch path (test), and the `operation` value is never accepted
  from tool arguments, plan files, or anchor content (test).
- [ ] **C9 — write discipline.** The anchor plan entry carries
  `expected_absent` (first write) or `expected_current_sha256`
  (regeneration); the written bytes equal the previewed digest the confirm
  token names; anchor + receipt converge under crash fault injection at
  every new seam (`DEX_TX_TEST_STOP_AFTER`).
- [ ] **C10 — receipt is audit, never trust.** The design names the
  receipt's exact path and writer (transactional entry, or the documented
  post-commit publication pattern of `engine.py:606-646`); no code path
  reads the receipt to establish classification trust. Test: forged/orphan
  receipt has zero trust effect.
- [ ] **C11 — secrets and size.** The anchor stores paths and hashes only;
  the §5 leak test (planted fake key appears in no anchor, receipt, log, or
  report) extends to the new artifacts. The anchor document has a declared
  size bound enforced at read.
- [ ] **C12 — no CLI override of the claim.** The re-anchor CLI accepts no
  version/tag argument that substitutes for the installed catalog's
  manifest-bound claim; the release to prove is derived, never supplied.

Per threat model §7, the write-capable re-anchor lane must additionally
re-run the full red-when-removed suite, add fault injection at every new
mutation seam, and demonstrate that removing each consent step fails a test
— this review does not substitute for that pre-merge gate; it defines what
the gate must contain for this seam.

---

*Reviewed 2026-09-05 against HEAD `af52bb6`. Line numbers cited are from
that tree; a later refactor moves lines, not obligations.*
