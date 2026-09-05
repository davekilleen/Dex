# Customization Re-Anchoring Design (proving a vault's release identity without the blocked update)

**Status:** Founder-ruled 2026-09-05 (see "Founder rulings" at the end); nothing
is built yet. Grounded in a
code audit of `core/customization_migration/`, `core/lifecycle/inventory.py`,
`core/lifecycle/customizations.py`, `core/lifecycle/catalog.py`,
`core/update/apply_update.py`, `core/utils/doctor.py`,
`scripts/generate-release-catalog.py`, `scripts/build-release.sh`, and
`docs/customization-migration-threat-model.md` on 2026-09-04, plus one
synthetic-vault experiment reproducing the reported state (see "Empirical
confirmation" below).

## The user problem (from a beta tester, 2026-09-04)

A long-lived vault that (a) was moved on disk in August and (b) was upgraded
once by manually merging files from v1.92 now shows a deep customization
assessment of UNKNOWN/partial: 1,807 of 1,855 exclusions carry the reason
`release-identity-unproved`, across `.claude` (711 files), `core` (506) and
`.agents` (482). That state blocks the Capsule route completely — the exact
route that exists to make `/dex-update` safe for a customized vault. Doctor's
guidance on every one of those exclusions is:

> "Restore a verified release catalog through /dex-update, then reassess."

which sends the user through the unprotected update to earn the protection
that was supposed to come first.

## Outcome

A user in this state runs one guided, consent-gated repair and ends with:
every file under a release-owned location proved against the installed
release's real byte hashes and classified as **release-pristine** (drops out
of the exclusion list), **release-modified** (becomes an assessable
customization with a known baseline), or **user-owned addition** (enters the
existing customization pipeline); the assessment returns to completeness `OK`;
the Capsule route unblocks; and nothing was ever "blessed" as release-owned
without matching a hash derived from cryptographically verified release
evidence. Vaults with no provable evidence stay honestly UNKNOWN — they are
never silently promoted.

## Verified Baseline (what "release-identity-unproved" means in code)

### The invariant that broke

Release identity for a file means: *its exact bytes are provably the bytes a
verified Dex release shipped at that path.* The only proof source the
assessment consults is the installed release catalog's per-file hash table:

- `load_release_baseline` (`core/lifecycle/customizations.py:125-219`) reads
  `System/.installed-files.manifest` and one catalog
  (`System/.release-catalog.json` or `core/lifecycle/catalog/release.json`,
  `:20-23`). Identity is `VERIFIED` only when the catalog's manifest binding
  hash matches the installed manifest bytes (`:158-209`). The baseline's
  `expected_hashes` are **only** the hashes of files the catalog's items
  declare (`:164-168`).
- `classify_release_state` (`core/lifecycle/customizations.py:238-281`): a
  file under a release-owned ("brain") location with no catalog hash for its
  path returns `"unknown"` (`:271-272`) — there is no other proof channel. The
  manifest lists paths only, no hashes (`_parse_manifest`, `:97-113`), so
  manifest membership proves nothing about bytes.
- `build_inventory` (`core/lifecycle/inventory.py:380`) collects every
  `release_state == "unknown"` entry as `unproven_paths`.
- The discovery sweep (`core/customization_migration/inventory.py:775-791`)
  turns every unproven file that is not already a customization candidate into
  an `AssessmentExclusion(path, "release-identity-unproved")`.
- Any non-secret exclusion forces completeness `UNKNOWN`
  (`core/customization_migration/service.py:93-109`), and the `Assessment`
  model enforces verdict-follows-completeness
  (`core/customization_migration/model.py:530-536`).
- The Capsule preview refuses anything but verdict `OK`
  (`core/customization_migration/capsule.py:451-463`; also enforced
  structurally at `capsule.py:148-149`), and the `/dex-update` skill instructs
  the same: "Do not run the Capsule preview or ask for Capsule approval until
  reassessment returns completeness OK"
  (`.claude/skills/dex-update/SKILL.md:104-110`).
- Doctor surfaces the state as UNKNOWN with per-exclusion guidance
  (`core/utils/doctor.py:1983-1992`), and the guidance string for this reason
  is fixed at `core/customization_migration/model.py:47`.

### Why this vault shows it

The manual merge copied a coherent manifest + catalog pair from v1.92, so the
pair verifies against each other and `baseline_identity_state` is `VERIFIED`
(without that, `discover` bails out early with zero exclusions,
`core/customization_migration/inventory.py:491-492`, and Doctor would instead
say it couldn't verify the installed version, `doctor.py:1976-1982`). With a
verified baseline, the exclusion sweep runs — and almost nothing on disk can
be proved, because the catalog's hash table is tiny (next section). Leftover
files from the pre-merge release that v1.92 never shipped inflate the counts
further (711 `.claude` files against, for comparison, 614 in this tree's
manifest), since a manual merge copies but rarely deletes.

The disk move by itself does not change classification — the updater
explicitly tolerates a relocated vault (`core/update/apply_update.py:520-525`)
— but a move that loses or breaks the hidden `.dex/brain.git` store makes the
split-topology check fail closed (`apply_update.py:555-561`), which is the
most plausible reason this user resorted to a manual merge in the first
place. The move explains the merge; the merge explains the state.

### The finding that is bigger than this vault

The release build generates the catalog's items exclusively from the
publisher-declared source registries
(`scripts/generate-release-catalog.py:121-239`, invoked by
`scripts/build-release.sh:271-276`); the only checked-in registry,
`core/lifecycle/catalog/official-capabilities.json`, declares **27 files**,
all dormant capability payloads under `.claude/`. The coverage checker
verifies catalog → tree, never tree → catalog
(`scripts/check-catalog-coverage.py:83-180`). So on the code as read, *any*
vault with a verified catalog-bearing release — including one installed
cleanly by `/dex-update` — has expected hashes for ~27 of its ~2,000
release-owned files, and every other brain-owned file classifies `"unknown"`.
The unproved mass is a catalog-coverage property, not something unique to
moved or hand-merged vaults; this tester is the first to hit the state where
it is visible (verified baseline + heavy divergence). This audit could not run
the assessment on a real installed vault, so field variation is possible, but
the mechanism is confirmed synthetically below.

### Empirical confirmation

A minimal synthetic vault (verified v2 catalog binding a canonical manifest;
one brain file listed in a catalog item, one brain file in the manifest but
not in any item) assessed through the real
`core.customization_migration.service.assess`:

- `baseline_identity_state: VERIFIED`
- the catalog-listed file is proved; the manifest-listed but
  catalog-unlisted file yields exactly
  `EXCLUSION: core/engine.py release-identity-unproved`
- `completeness: UNKNOWN`, `verdict: UNKNOWN`,
  `incomplete_reasons: ('assessment-exclusions',)`

### Why the current guidance is circular

`core/customization_migration/model.py:47` tells the user to "Restore a
verified release catalog through /dex-update, then reassess." Twice circular:

1. **The Capsule exists to make `/dex-update` safe** for a customized vault
   (`CHANGELOG.md` v-entry "Your customisations get a protected snapshot
   first", and the whole of `docs/plans/2026-07-24-customization-migration-mcp.md`).
   The blocked state is precisely "cannot create the Capsule", so the guidance
   routes the user through the unprotected update — where release-owned files
   are replaced wholesale (`build_update_plan`,
   `core/update/apply_update.py:669+`) and any unproved customization there is
   lost — to earn the protection.
2. **Even a successful update reinstates a catalog of the same sparse shape**
   (27 declared files), so the same exclusions reappear on reassessment. The
   remedy the guidance names cannot, as built, produce the evidence it
   promises.

### Where real proof already lives

The update path already proves complete release identity, byte for byte,
from two sources the assessment never consults:

- **The local brain store.** `verify_release_ref`
  (`core/update/apply_update.py:572-653`) proves an annotated
  `dist/release/v*` tag against the official origin (pinned by regex to
  `davekilleen/Dex`, `:34-38`, checked at `:565-569`), binds tag → commit →
  tree, and checks the release's manifest blob is exactly the tree
  (`_verify_manifest`, `:467-482`). `build_update_plan` reads the previously
  installed release's full tree from `refs/dex/installed` (`:672-674`). Every
  file's exact bytes — and therefore its SHA-256 — is derivable from a
  verified tree via `_tree_entries`/`_blob` (`:431-460`).
- **The pinned canonical repository.** The bounded release-evidence flow
  (SessionStart release awareness; the update's own fetch) already fetches
  immutable tags from the one pinned HTTPS origin into an isolated bare
  cache, fetch-only, and the CRLF byte-tolerance policy is centralized in
  `release_bytes_match` (`core/lifecycle/catalog.py:370-383`).

Re-anchoring is the act of carrying that already-trusted proof across to the
assessment's baseline.

## Non-Goals

- No weakening of the fail-closed vocabulary. `UNKNOWN` stays the honest
  answer wherever proof is genuinely absent; this design adds proof sources,
  never optimism.
- No second verification stack. Tag, origin, tree and manifest verification
  reuse `apply_update`'s existing functions; byte comparison reuses
  `release_bytes_match`. New crypto or new trust roots are out.
- No model-held write tool, per threat-model amendment A1
  (`docs/customization-migration-threat-model.md:48-60`). Every mutation in
  this design happens on the Doctor/CLI side behind interactive consent; MCP
  surfaces stay read/preview-only.
- No automatic deletion of the leftover files a re-anchor identifies. They are
  classified and reported; disposal is a separate consented act.
- Not a repair path for a broken brain store or split topology. Re-anchoring
  restores *assessment* evidence; fixing `.dex/brain.git` so the updater
  itself can run again is adjacent, separately-scoped work (noted in the
  deferred list).

## Design

### The anchor: a proven per-file hash table

A new evidence artifact — working name **release anchor**, a JSON file under
`System/.dex/` (the same protected region as the capsule artifacts, threat
model §5) — carrying:

- the release version and the immutable tag identity it was proved from
  (tag name, tag object, commit, tree — the same quadruple
  `verify_release_ref` pins);
- the SHA-256 of the installed manifest bytes it is bound to;
- the SHA-256 of the installed catalog's canonical bytes;
- one `path → sha256` row per file in the proven release tree, computed by
  hashing each verified tree blob's bytes;
- a self-hash over the canonical document.

`load_release_baseline` gains one fail-closed consumer step: if an anchor
exists, it is accepted **only** when its manifest binding equals the installed
manifest bytes' hash AND its catalog binding equals the installed catalog —
the same double-binding discipline the catalog itself uses
(`customizations.py:158-162`). An anchor that fails any binding is reported as
a baseline error and ignored; the vault falls back to exactly today's
behavior. A valid anchor merges its rows *under* the catalog's
`expected_hashes` (catalog rows win on conflict, so the smaller, signed-shape
artifact stays authoritative for what it covers).

With the anchor in place, `classify_release_state` needs no change: files
matching an expected hash become `stock-unmodified`, differing files become
`stock-modified`, and the CRLF tolerance already built in
(`customizations.py:262-270`) carries over.

### The re-anchor flow (Doctor/CLI side, consent-gated)

Offered by Doctor when the deep assessment is UNKNOWN with
`release-identity-unproved` exclusions present. Steps, in order, each
fail-closed:

1. **Identify the claimed release.** Read the installed catalog's
   `release.version` and `source_commit` (already verified against the
   manifest binding). This is a *claim* to be proved, never trusted.
2. **Find a proof source for that exact release, strongest first:**
   a. `refs/dex/installed` in the local brain store, when the tree's manifest
      blob is byte-identical to `System/.installed-files.manifest` (the
      manual-merge vault will usually fail this — the ref still points at the
      pre-merge release — which is correct: mismatch means this source cannot
      prove the claimed release);
   b. any locally present immutable `dist/release/v*` tag whose version
      matches the claim, run through the full `verify_release_ref` discipline
      (origin, annotated tag, commit/tree binding, tree-manifest equality)
      and whose tree manifest is byte-identical to the installed manifest;
   c. a **bounded, fetch-only** retrieval of that one tag from the pinned
      canonical repository into the isolated bare evidence cache (the
      release-awareness transport), then the same verification as (b). This
      step requires its own explicit user confirmation before any network
      operation ("Fetch the official v1.92 release record to check your files
      against? Nothing is changed by this.").
3. **Show the preview.** Per-file classification counts (pristine / modified /
   addition / still-unproved), the tag identity used, and the exact anchor
   document digest. Nothing is written yet.
4. **Consent, then write.** One interactive confirmation writes the anchor
   through the transaction engine with its standard invariants (single vault
   root, symlink refusal, atomic write, journal-before-effect — threat model
   §5), and a receipt.
5. **Reassess.** The normal `assess()` now proves the tree.

If no source verifies — the manifest matches no official release (user-edited
manifest, or a truly pre-catalog install) — the flow stops and says so
plainly. That vault stays UNKNOWN. See "adopt-as-baseline" below for what we
deliberately do *not* do about it in v1.

### What each classification unlocks

- **release-pristine** (matched hash): the exclusion disappears; the file is
  provably stock; the Capsule does not need to carry it; a future update may
  replace it wholesale with zero information loss.
- **release-modified** (hash differs from the proven baseline): becomes a
  `modified-skill` / `modified-shipped-file` customization record with a real
  `BaselineInfo` hash (`core/customization_migration/model.py:141-161`) —
  exactly the evidence the Capsule, verification and migration-planning lanes
  were built to consume. This is the payload the tester is currently locked
  out of protecting.
- **user-owned addition** (present on disk, absent from the proven tree):
  flows through the existing candidate pipeline
  (`core/customization_migration/inventory.py:104-214`) as custom skill /
  script / config / unknown-addition. Leftovers from the pre-merge release
  land here too; the assessment report can flag "files no shipped release
  accounts for" as a reviewable cleanup list — proposed, never auto-deleted.
- **still-unproved** (no verifying source): stays excluded, with corrected
  guidance (below). Fail closed.

### Candidate directions evaluated

**A. Re-prove file-by-file against verified release evidence (chosen, as the
hybrid above).** Reuses the strongest machinery in the codebase, works
offline when the brain store holds the release, degrades to one bounded
fetch when it does not (the moved-vault case), and never manufactures trust:
every anchor row traces to an annotated tag on the pinned origin. Cost:
the anchor artifact + one consumer step in `load_release_baseline` + the
Doctor flow; the verification functions already exist.

**B. Supervised "adopt current state as baseline" (trust-on-first-use).**
Honestly evaluated: it is the only option for a vault whose manifest matches
no official release, and it is also the single most dangerous mechanism in
this document. Blessing current bytes as the baseline converts "unknown" into
"pristine" with no evidence — afterwards, real tampering in `.claude/hooks/`
or `core/` is *invisible by construction*, because the tamper became the
baseline. It also inverts threat-model A3's spirit: provenance would be
"user-confirmed" in name while the user has verified nothing (no human
reviews 1,807 files; the consent would be a rubber stamp on bytes the user
never saw — exactly what §2 "the trust model" forbids transferring consent
to). **Recommendation: do not build it in v1.** If it is ever built, the
non-negotiable shape is: it never assigns release provenance (adopted files
classify as user-owned `unknown-addition`, unblocking the Capsule by
*carrying* them as opaque user material, not by proving them); typed consent
naming the count and the risk; per-category consent with executable surfaces
(hooks, scripts, MCP configs) listed individually; an adoption receipt that
Doctor reports forever after ("this baseline includes N unverified adopted
files"). Founder decision 2.

**C. Full-coverage release catalogs (necessary companion, not the fix for
the stranded vault).** Make the release build emit a per-file hash row for
every shipped file (whole-tree table bound into the catalog, or a sibling
hash-table file the catalog binds by hash — ~2,100 rows, roughly 350 KB,
well inside the 16 MB catalog bound, `customizations.py:25`). This deletes
the unproved mass for every vault that installs or updates normally, and
makes the anchor a transitional artifact rather than a permanent one. It
does nothing for the vault that cannot yet update safely — which is why A
ships too. Founder decision 1 covers the shape.

### Guidance correction (small, immediate)

`core/customization_migration/model.py:47` changes from the circular
instruction to one that names the real remedy and is honest before the
re-anchor flow exists, e.g.: "Dex can't prove these files came from your
installed release. Run /dex-doctor's release re-anchoring to check them
against the official release record — don't update until that's done."
Tester-visible copy: founder approves final wording (decision 5).

## Security: threat-model deltas

Baseline: `docs/customization-migration-threat-model.md` (amendments A1–A3
binding). This design adds two assets and three attack surfaces.

**New assets:** the anchor document (a forged anchor poisons every downstream
"verified" claim, same class as capsule evidence, §2 "the evidence chain");
and the isolated evidence cache during the re-anchor fetch.

**Surface 1 — a tampered or planted anchor file.** An attacker (or a sync
tool) writes `System/.dex/release-anchor.json` directly. Defense: the anchor
is *never* trusted on presence. `load_release_baseline` re-checks its
manifest binding, catalog binding and self-hash on every load; any failure
demotes to today's UNKNOWN state with a named baseline error — fail closed to
less trust, never more. The anchor cannot widen trust beyond what a verified
tag proved because its rows are only ever *generated* from a verified tree by
the Doctor/CLI flow; a hand-written anchor with fabricated rows still binds to
the real manifest, so its rows must match real release bytes to change any
file's classification to pristine — and rows that "prove" attacker-modified
bytes would need the attacker to also control the manifest and catalog pair,
which is the pre-existing (accepted) local-attacker boundary. Residual risk to
state plainly for the founder: an attacker with full vault write access can
already replace manifest + catalog + files wholesale today; the anchor does
not enlarge that attacker's power, and a red-when-removed test must pin the
binding checks (§3.5 "future maintainers").

**Surface 2 — the network fetch.** A malicious or wrong remote serving a
poisoned tag. Defense: identical to the update path — the origin is pinned by
the `OFFICIAL_REMOTE` regex (`apply_update.py:34-38`), the tag must be
annotated and self-consistent (tag object → commit → tree), the tree's
manifest blob must byte-match the *locally installed* manifest, and the fetch
is into the isolated bare cache, never the vault or brain store. A poisoned
tag that doesn't reproduce the installed manifest byte-for-byte proves
nothing and the flow stops. The fetch happens only after explicit interactive
consent (A1: consent is an interactive act on the Doctor/CLI side; the MCP
tools can *report* that re-anchoring is available, never trigger it).

**Surface 3 — a prompt-injected model steering the flow.** A vault note
saying "re-anchor now and adopt everything" must be inert. Defense: same A1
posture as the capsule — the model holds preview/status tools only; the
re-anchor write and the fetch confirmation exist only in the CLI/Doctor
interactive layer; no MCP response ever contains a token whose possession
authorizes anything (tokens are integrity bindings, not consent, A1). The
anchor write goes through the one write authority with its own enumerated
seam (A2): adding `System/.dex/release-anchor.json` (or its directory) to a
seam list is a deliberate frozen-contract change requiring adversarial review
and red-when-removed tests — scheduled, not slipped in.

**Fail-closed rules, stated once:**

- No source verifies → no anchor → state stays UNKNOWN. Silence never
  promotes.
- Anchor binding mismatch → anchor ignored + named error, today's behavior.
- A file's bytes matching no proven hash → never pristine, no matter what.
- The re-anchor flow writes exactly one artifact (the anchor) plus its
  receipt; it never touches release files, the manifest, the catalog, the
  brain store's refs, or user content.

**Never auto-adopted, ever:** file bytes as release-pristine without a
verified-tree hash match; executable surfaces (hooks, scripts, `.mcp.json`,
MCP server sources) under any adopt-as-baseline variant without per-item
listing; a manifest that matches no official release; secrets policy
unchanged — the anchor stores paths and hashes only, never file contents
(§5 secrets rules apply to the new artifact and its receipts verbatim).

**Consent gates, in order of appearance:** (1) run the re-anchor at all
(Doctor offers, user accepts); (2) the network fetch, separately, only if
local sources fail; (3) writing the anchor after the preview; (4) — only if
decision 2 ever approves TOFU — typed adoption consent per the constraints
above. Each is an interactive act; removing any one must make a test fail
(threat model §7).

## Cost and sequencing

**Smallest shippable slice (unblocks nothing yet, costs almost nothing):**

1. Guidance string fix (`model.py:47`) — one string + founder-approved copy.
2. Full-coverage catalog in the next release build (direction C): extend
   `generate-release-catalog.py` to emit the whole-tree hash rows and the
   coverage checker to require tree → catalog coverage too. Prevents every
   *future* vault from ever entering this state after one normal update.

**The real unblocker (second slice):**

3. Anchor artifact + fail-closed consumer in `load_release_baseline` +
   Doctor/CLI re-anchor flow using local sources only (brain store ref and
   locally present verified tags). Depends on: the A2 seam addition with its
   adversarial review; binding red-when-removed tests; a synthetic-vault
   test matrix (verified/mismatched/absent anchor; pristine/modified/leftover
   files; CRLF forms).

**Third slice:**

4. The bounded fetch fallback (step 2c) for vaults whose brain store no
   longer holds the claimed release — the moved-vault case. Depends on slice
   2's flow and reuses the release-awareness transport.

**Deferred (register per WO-028 discipline; rows must not silently vanish):**

- Adopt-as-baseline (TOFU) in any form — pending founder decision 2.
- Brain-store repair for moved vaults (re-clone `.dex/brain.git` from the
  pinned origin so `/dex-update` itself works again) — adjacent, larger.
- Anchor retirement plan once full-coverage catalogs have been the norm for
  several releases.
- Assessment-report affordance for "files no shipped release accounts for"
  cleanup.

## Founder decisions needed

1. **Full-coverage catalog shape (direction C):** whole-tree rows inside the
   catalog document, or a sibling hash-table file the catalog binds by hash?
   The first is simpler; the second keeps the human-reviewable catalog small.
   Either way this changes the release artifact and the v2/v3 schema story.
2. **Build trust-on-first-use adoption at all?** Recommendation in this
   design: no in v1 — a vault whose manifest matches no official release
   stays UNKNOWN, and we learn from the field how often that actually
   happens. If overruled, the constraints in "Candidate directions, B" are
   the floor, not the negotiation range.
3. **Where the network-fetch consent lives:** inside the Doctor re-anchor
   flow as its own yes/no (recommended), or as a separate command the user
   must run deliberately. This is a privacy/consent promise, so it is the
   founder's call under WO-022.
4. **The A2 seam addition** for the anchor write: confirm the contract change
   and schedule its adversarial review — this design must not proceed to
   build without it.
5. **Tester-visible copy:** the corrected guidance string and the re-anchor
   flow's prompts (including the fetch consent wording).
6. **Anchor freshness policy:** should `/dex-update` regenerate the anchor on
   every successful update until full-coverage catalogs make it redundant, or
   is the anchor strictly a repair artifact created on demand? Automatic
   regeneration keeps assessments green for old-release vaults but adds one
   more write to the update transaction.
7. **The coverage finding itself:** on the code as read, even cleanly updated
   vaults carry the sparse 27-file catalog and would show the same unproved
   mass once assessed with a verified baseline. If field reports confirm
   this, the tester's report is the first sighting of a general condition and
   the fix priority (slice 1, item 2) rises accordingly. Worth one
   verification pass against a known-good production vault before build
   sequencing is locked.

## Founder rulings — 2026-09-05

Ruled by the founder in session (accepting the orchestrator's recommendations
as put, one per decision above). Recorded here per the write-the-ruling-down
rule; the later-dated committed ruling governs on any conflict.

1. **Full-coverage catalog shape:** sibling hash-table file, bound by hash from
   the catalog. The catalog document stays human-reviewable.
2. **Trust-on-first-use adoption:** not built in v1. A vault whose manifest
   matches no official release stays UNKNOWN; learn from the field how often
   that occurs before revisiting. The constraints in "Candidate directions, B"
   remain the floor if ever revisited.
3. **Network-fetch consent:** lives inside the Doctor re-anchor flow as its own
   explicit yes/no question (not a separate command). Wording is founder copy
   (ruling 5).
4. **A2 seam addition:** approved in principle; the adversarial review is the
   gating item and must be scheduled before build starts. Build does not
   proceed without it.
5. **Tester-visible copy:** two-stage approval accepted — the corrected
   guidance string is approved for the next patch once the founder confirms
   its verbatim wording; the re-anchor flow prompts (including fetch-consent
   wording) come back for approval when slice 2 is built.
6. **Anchor freshness:** repair artifact created on demand only in v1. No
   automatic regeneration inside the update transaction; full-coverage
   catalogs (ruling 1) make it redundant over time.
7. **Coverage finding:** run the verification pass against a known-good
   production vault (the founder's own) before build sequencing is locked.
   If confirmed, the full-coverage catalog (slice 1, item 2) moves to the
   front of the queue.

Open at ruling time: the verbatim guidance-string wording (ruling 5, first
half) and the verification-pass result (ruling 7).

Update, 2026-09-05 (later the same day): the founder approved the interim
guidance wording verbatim ("Dex can't yet prove these files came from your
installed release — that's a gap in Dex's own records, not a problem with
your files. A guided repair that checks them against the official release
record is coming. Updating will not clear this notice, so don't update just
to fix it."), together with the reworded /change-job opener. Ruling 5's
first half is settled; the re-anchor flow prompts remain open for slice 2.
The adversarial review (2026-09-05-anchor-seam-adversarial-review.md)
returned APPROVE-WITH-CONDITIONS; its C1–C12 are binding on the build.
