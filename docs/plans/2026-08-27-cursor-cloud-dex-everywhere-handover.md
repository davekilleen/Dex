# Dex Everywhere — Cursor Cloud continuation handover

**Prepared:** 27 August 2026

**Programme state:** unreleased; release remains closed

**Primary repository:** `davekilleen/Dex` (Dex Core)

**Primary draft PR:** <https://github.com/davekilleen/Dex/pull/594>

**Historical Codex source thread:** `01a03796-e4eb-7583-a9c2-645747d86be7`

## 1. Read this first

Continue this programme in **Dex Core first**. The correct GitHub repository is:

```text
https://github.com/davekilleen/Dex
```

Start from the handover branch named in the founder handoff that accompanies this file,
not from `main` and not from the older head currently shown on draft PR #594. Verify the
branch SHA after cloning. Cursor Cloud normally creates its own working branch; preserve
that isolation and do not rewrite another branch's history.

Cursor Cloud is an Ubuntu execution environment. It is suitable for implementation,
Linux-independent local tests, documentation, GitHub operations, and triggering CI. It is
**not** proof of native macOS behaviour, native Windows behaviour, Claude Cowork UI
behaviour, or the macOS-only BB plugin. Those claims require the native GitHub jobs or a
recorded native-host journey.

Do not paste, request, or copy credentials in chat. If a service login is needed, use its
owner-controlled browser login or Cursor's encrypted secret configuration. The existing
authenticated Devbox can run the final genuine Fable review once code heads are frozen;
do not replace Fable with Cursor's model or a self-review.

## 2. Product purpose

Dex Everywhere is not merely a packaging exercise. Its purpose is to let people benefit
from Dex's progress even when they use a different AI host, an older or customised Dex,
or a different personal brain such as a bespoke assistant. It must also let people share
useful, reusable patterns back to the Dex community without exposing personal, company,
health, financial, family, or other sensitive context.

The end state must provide:

1. A shared, portable plugin/skills/MCP core.
2. Capability-aware detection, onboarding, and Doctor reporting which tells the truth
   about what each host can and cannot do.
3. Working local adapters and golden journeys for Codex first, Claude Code/Cowork second,
   then Copilot CLI, Pi, and supported Agent Plugin clients.
4. A researched and implemented getbb.app/BB path where technically supported.
5. A privacy-safe two-way capability exchange: receive relevant Dex improvements and
   deliberately contribute reusable learning back.
6. Documentation, a supported-platform matrix, and an unreleased Amazon-style press
   release that exactly match the code and evidence.
7. Preservation of Dex's transaction, ownership, customisation, and safety contracts.

People may have:

- current stock Dex;
- an older Dex;
- a customised Dex;
- their own personal brain rather than Dex;
- sensitive routines which must never be suggested for sharing merely because they look
  reusable.

The privacy rule is conservative: sharing is always user initiated; an automatically
minimised generic Card is shown before transmission; explicit confirmation applies to the
exact outgoing bytes; declining is durable; withdrawal and deletion are possible; and raw
source prose never leaves the inspected machine.

## 3. Non-negotiable governor

Keep all work unreleased and isolated. Normal draft-PR mechanics and non-production CI are
allowed. Do **not**:

- merge shared `main`;
- publish a package, GitHub release, marketplace entry, website, or plugin;
- deploy or install anything for users;
- make a private repository public;
- change billing;
- submit to a marketplace;
- contact users or reporters;
- copy secrets between the Devbox and Cursor Cloud;
- weaken PII/founder-content checks or allowlist around a real finding;
- claim macOS, Windows, Cowork, or BB evidence from an Ubuntu-only run.

Stop at a clean, fully evidenced, human-review-ready set of draft PRs. Dave's explicit
approval is required for any release or merge.

## 4. Repository map and priority

| Priority | Repository | Purpose | Current review surface |
| --- | --- | --- | --- |
| 1 | `davekilleen/Dex` | Portable Core, host registry, onboarding, Doctor, adapters, release assets, docs and press release | Draft PR #594 |
| 2 | `davekilleen/dex-lens` | Capability Exchange receive/share loop, hosted intake contract, consent, privacy abstraction, withdrawal | Separate integration branches; no release |
| 3 | `davekilleen/dex-cards` | Mission Control Build Card and durable programme evidence | Draft PR #95 |
| 4 | `davekilleen/dex-bb-plugin` | Standalone BB/getbb.app macOS-only adapter | Private draft PR #1 |

The founder's requested sequencing is **Codex first, Claude Code/Cowork second, BB
later**. Do not let BB delay the Core/Codex path; its current exact-head native macOS CI is
already green.

## 5. Verified GitHub state at handover

### Dex Core

- Draft PR: <https://github.com/davekilleen/Dex/pull/594>
- PR branch: `codex/harness-portable-dex-resume`
- Published PR head: `faba7c5715e75915309a6faa88aeaf0f8a3c07ef`
- PR is open and remains a draft.
- Exact-head Core CI at that published head is green:
  <https://github.com/davekilleen/Dex/actions/runs/32951876319>
- Exact-head twelve-journey macOS fleet canary is green:
  <https://github.com/davekilleen/Dex/actions/runs/32951876327>
- Earlier exact-head evidence at `a6425a1926617b5d8d79e5bfb8e1f1d15eb02097`
  is also green:
  <https://github.com/davekilleen/Dex/actions/runs/32872374450> and
  <https://github.com/davekilleen/Dex/actions/runs/32872374477>.
- Cloud continuation branch: `codex/dex-everywhere-cursor-handoff`.
- Latest verified implementation head before this documentation-only reconciliation:
  `1773da6a41f13e5c0ab45cf750b7619d35f2fd74`. Resolve the branch tip after cloning and
  use that newer pushed tip as the starting point.
- The branch has normally merged GitHub `main` through
  `5d1c7027676a2fecd8bd26b42de8b823300c7bf8` (`v1.97.3`). It also contains the nested
  custom-skill repair, transactional keep-both conflict sidecars, Lens catalogue
  reconciliation, and the shared safety-gate repair.
- Re-fetch `main` before final evidence. If it has advanced, use another normal merge,
  not a rebase or history rewrite.

The canonical Devbox Core worktree is dirty with preserved concurrent edits. Do not try to
clean, reset, or overwrite it from another session. The handover branch was made from a
clean isolated clone.

### BB plugin

- Repository: <https://github.com/davekilleen/dex-bb-plugin>
- Private draft PR: <https://github.com/davekilleen/dex-bb-plugin/pull/1>
- Branch/head: `codex/dex-bb-plugin` at
  `9686e2266834e194ceef4eeafaf35cc27a812991`
- Open draft; worktree and pushed branch match.
- The increased Actions budget has resolved the earlier no-code billing block.
- Native macOS push workflow is green:
  <https://github.com/davekilleen/dex-bb-plugin/actions/runs/32949546856>
- Native macOS PR workflow is green:
  <https://github.com/davekilleen/dex-bb-plugin/actions/runs/32949551083>
- Both exact-head runs passed install, 36 tests, typecheck, build, package check, and
  release-ready macOS platform validation.
- Local audit/tarball evidence recorded before handover was also green.
- Scope is macOS only. Linux and WSL2 are deferred; Windows is unavailable for this
  standalone plugin. Keep the repository private and the package unreleased.

### Mission Control

- Repository: <https://github.com/davekilleen/dex-cards>
- Draft PR: <https://github.com/davekilleen/dex-cards/pull/95>
- Branch/head: `codex/harness-portable-dex-card` at
  `200a820b50c58146eb288e765306fde77c35716e`
- Build Card: `dex-everywhere-harness-portability-and-bb-plugin.md`
- Open draft; worktree and pushed branch match.
- This card is behind the newest local implementation/review evidence and must be updated
  only after the final code heads and CI runs are known.

### Capability Exchange

- Canonical repository: <https://github.com/davekilleen/dex-lens>. The older
  `davekilleen/dex-capability-exchange` URL redirects here.
- Verified base before the local integration work:
  `5815bcc8a26d2c4d615119703e15f132dc64ce79`
- Local integration candidate:
  `a12b3b8299f01580bf724bce48729a7b6ccfb43a`
  (`d91fec7` safe hosted contribution controls plus `a12b3b8` standard Lens doorway fix).
- Local privacy candidate:
  `c76f1f55e2747e2af508f5ffbf6691117b439a68`, based on `d91fec7`, not on `a12b3b8`.
- The privacy candidate is **NO-SHIP** and must not be merged unchanged. See section 8.

## 6. Local Core verification already run

The first trustworthy clean-suite baseline was exact local Core head
`3b4a88342c4b83ff660fe7ced95232cbb31f73d4`:

- `npm ci`: passed; 96 packages, zero vulnerabilities.
- Hook tests: 221/221 passed.
- Script tests: 167/167 passed under the normal CI umask. A 166/167 result under
  `umask 0077` was proved to be an artificial fixture-mode mismatch.
- Integration tests: 224 passed, one documented skip.
- Connection contract: passed; eight fixtures and a 21-file manifest.
- Portable contract: passed for 2,081 classified paths.
- Harness portability generator drift check: passed.
- Harness registry generator drift check: passed for 11 profiles.
- Portable `.agents/skills` generator drift check: passed for 271 skills.
- Portable plugin generator drift check: passed for 323 assets.
- Portable artifacts built successfully; MCPB SHA began `26e2efbe`, Gemini archive SHA
  began `86cc2d28`.
- PII check: passed.
- Founder-content check: passed.
- The release-ready portable runtime verifier exits with the deliberate Linux deferral
  when run on the Devbox. This is expected; macOS and Windows CI provide the applicable
  release-ready proof.

The first full Python attempt was invalid as final evidence because the shared `/tmp`
filesystem ran out of inodes and subprocesses lacked the isolated MCP dependency. It
reported 4,239 pass, 80 fail, 289 setup errors, five skips, and two deselections. Do not
quote that run as product evidence.

A clean dependency-isolated rerun with a private temporary directory completed in 898.28
seconds: **4,577 passed, 34 failed, two skipped, and two deselected**. It contained no
inode-exhaustion or missing-MCP setup errors, so those 34 failures were a trustworthy
historical baseline. They are **not** the current open-failure count. Failure families
included:

- nested `*-custom` gitignore/update composition;
- a provision receipt `declared_paths` mismatch;
- one conflict-resolution case;
- distribution-artifact expectations;
- one safety-gate case.

The full log is retained on the Devbox at
`/srv/dex-dev/verification-tmp/core-codex-local-gates-3b4a883/full-pytest-venv.log`.
Cursor Cloud cannot read that local path; the exact formerly failed test names are
captured by the following list for regression reference:

```text
core/tests/test_apply_update.py::test_composed_gitignore_appends_contract_derived_vault_section
core/tests/test_apply_update.py::test_applied_shipped_gitignore_saves_user_files_and_excludes_product_files
core/tests/test_apply_update.py::test_composed_gitignore_reincludes_every_vault_region
core/tests/test_apply_update.py::test_composed_gitignore_reignores_product_files_inside_vault_regions
core/tests/test_apply_update.py::test_composed_gitignore_leaves_user_files_in_a_vault_region_tracked
core/tests/test_apply_update.py::test_composed_gitignore_vault_regions_track_the_contract
core/tests/test_apply_update.py::test_composed_gitignore_is_idempotent_and_replaces_stale_section
core/tests/test_apply_update.py::test_compose_gitignore_import_does_not_require_pyyaml
core/tests/test_apply_update.py::test_vault_section_assumes_direct_child_exceptions_only
core/tests/test_conflict_resolution.py::test_keep_both_writes_sidecar_and_rewind_removes_it
core/tests/test_distribution_artifacts.py::test_first_release_with_vault_gitignore_repair_tracks_para_files
core/tests/test_distribution_artifacts.py::test_release_branch_strips_dev_files_and_untracks_v1_local_only_files
core/tests/test_distribution_artifacts.py::test_beta_release_branch_uses_same_stripping_and_manifest
core/tests/test_distribution_artifacts.py::test_release_build_uses_selected_source_version_for_tree_profile_manifest_and_tag
core/tests/test_distribution_artifacts.py::test_raw_vault_bundle_has_package_profile_manifest_agreement
core/tests/test_distribution_artifacts.py::test_raw_vault_bundle_publishes_standalone_verified_bridge
core/tests/test_distribution_artifacts.py::test_release_script_synchronizes_all_bumped_version_metadata
core/tests/test_distribution_artifacts.py::test_release_build_uses_safe_selected_source_despite_unsafe_current_checkout
core/tests/test_distribution_artifacts.py::test_release_build_creates_immutable_versioned_tags
core/tests/test_distribution_artifacts.py::test_release_build_does_not_repeat_v1_96_2_catalog_tag_lie
core/tests/test_distribution_artifacts.py::test_vault_bundle_tree_manifest_and_archive_contain_no_tau
core/tests/test_doctor.py::test_post_split_core_drift_accepts_the_composed_vault_mode_gitignore
core/tests/test_harness_safety_gates.py::test_safety_hook_is_a_thin_wrapper
core/tests/test_lifecycle_service_contract.py::test_frozen_service_inputs_and_outputs_conform_to_schema
core/tests/test_provision_parity.py::test_completed_vault_records_only_its_confirmed_harness_receipt
core/tests/test_provision_transaction.py::test_execute_commits_marker_and_session_deletion_together
core/tests/test_provision_transaction.py::test_recover_restores_a_real_killed_first_run_transaction
core/tests/test_release_fleet_acceptance.py::test_forged_executor_runs_cannot_mint_a_platform_receipt
core/tests/test_release_fleet_acceptance.py::test_changed_evidence_validator_cannot_mint_a_platform_receipt
core/tests/test_release_fleet_acceptance.py::test_live_finalization_rejects_a_spoofed_host_platform
core/tests/test_smoke.py::test_hooks_are_syntax_checked_without_executing_commands
core/tests/test_tracked_ignored.py::test_update_journey_capture_before_release_restores_files_removed_by_release
core/tests/test_tracked_ignored.py::test_real_fast_forward_and_rollback_preserve_local_only_bytes_modes_and_deletions
core/tests/test_transaction_core.py::test_engine_rechecks_deletion_content_immediately_before_unlink
```

Current disposition at implementation head `1773da6a`:

- all nine apply-update failures are covered by the nested custom-skill repair; the full
  `test_apply_update.py` target passed **81/81**;
- the conflict, lifecycle, provision, portable-contract, transaction, adoption, bridge,
  and MCP-registration family passed **301 tests** after the transaction repair;
- the transaction engine's content-and-mode precondition was deliberately preserved;
  the two file-mode failures were reproduced as an artificial `umask 0077` environment,
  not fixed by weakening the approval contract;
- the three release-fleet tests correctly skip on Linux and still require native CI;
- the safety thin-wrapper failure is fixed by keeping the Python gate authoritative and
  failing closed if it is unavailable; **7 safety tests** and **221 hook tests** passed;
- Lens catalogue/inventory reconciliation passed **92 focused tests**, with generated
  drift checks and Ruff green;
- Doctor and smoke focused targets pass on the integrated branch.

This is focused proof, not a replacement for the full clean suite. The first Cursor task
is to run the formerly failing focused set, then the complete local verification contract,
on the pushed branch tip. Pay particular attention to the expensive distribution-artifact
family and the release-version test against `v1.97.3` truth.

Re-run the first nine apply-update cases despite their focused green proof. Several
distribution failures are expected to collapse against today's release truth, but do not
classify any failure as inherited or fixed without rerunning it.

The nested custom-skill repair has already been implemented on the handover branch:

- recursively re-include nested parent directories and child wildcard exceptions in
  `core/update/apply_update.py`;
- cover `.claude/skills/*-custom` and `.agents/skills/*-custom` in
  `core/tests/test_apply_update.py`;
- include `core/update/apply_update.py` among release-builder inputs in
  `core/tests/test_distribution_artifacts.py`.

Focused proof for that repair:

- 81 `test_apply_update.py` tests passed;
- three release-builder tests passed;
- Ruff passed for the changed Python files.

Do not assume any remaining Python failure shares one cause. Reproduce it independently,
retain or add a failing regression, and make the smallest contract-preserving repair.

## 7. Genuine Fable review already performed

Three mandatory reviews were performed with the genuine Anthropic Fable model, resolved
identifier `claude-fable-5`, using Claude Code 2.1.234:

- product/end-to-end review: `FIX REQUIRED`;
- architecture/cross-harness review: `FIX REQUIRED`;
- full implementation review of the complete Core PR and the entire BB repository tree:
  `FIX REQUIRED`.

The reports and invocation records are preserved on the Devbox at:

```text
/srv/dex-dev/worktrees/dex-everywhere-fable-review/
```

The early reviews positively proved that the Core is capability-driven, drift-gated,
transactional, truthful about partial host capabilities, and backed by real native CI;
that the portable runtime is generated from canonical Core; and that BB is read-only,
contained, and honestly macOS-only. They found no P0 data-loss, credential exposure,
remote compromise, or fundamental false claim.

Their material original findings were:

1. The required two-way community contribution loop was absent.
2. Existing users had no post-onboarding path to create the new capability receipt.
3. Harness truth and Lens catalogue availability were disconnected.
4. Release mechanics did not attach all host artifacts or provide live install evidence.
5. DexDiff's old share path transmitted before final consent and lacked structural
   minimisation/withdrawal.
6. DexDiff publish/adopt surfaces disagreed about the API host.
7. Share/feedback surfaces were not portable to the added hosts.
8. Production detection ignored real home-directory evidence.
9. “Requires an update” was not computed from available version data.
10. Custom skill namespaces were not explicitly preserved.
11. Pi capability claims needed pinned evidence or truthful downgrade.
12. The BB adapter descriptor named paths that did not exist.
13. Generated harness profiles and portability classification needed drift gates.
14. BB needed an accidental-publish guard and smaller CI/documentation hardening.

The eight Core continuation commits after `faba7c57` address substantial portions of the
Core list, including post-onboarding receipt creation, real-home detection, Lens support,
generated custom namespaces, BB/Pi descriptors, portable hook launchers, and release asset
attachment. Treat every claimed disposition as unverified until the final diff and tests
prove it.

After all code heads are frozen, rerun both the architecture review and the full
implementation review with genuine Fable. A Cursor model, Codex self-review, or another
reviewer is not a substitute. Independently reproduce every Fable finding before changing
code.

## 8. Current NO-SHIP privacy findings

An independent review of capability-exchange commit
`c76f1f55e2747e2af508f5ffbf6691117b439a68` reproduced five material gaps. Focused tests
(34) and the inventory check (685 fields, 120 stored, 16 transmitted) pass, but the
acceptance contract does not.

### P1: raw/private content can leave the machine

`src/capability_exchange/contribution/privacy.py` keeps the entire validated Card whenever
its regular expressions do not recognise the text as personal. The reviewer reproduced a
full submission containing `This is my private notebook entry`. A nested reference such as
`file:client-zephyr/weekly.md#snap:secret` also survived into the manifest/payload.

**Required design:** every outgoing Card must be minimised by construction, even when no
detector fires. Sensitivity detection may select stricter handling, but it must never be
the only wall preventing raw prose egress. Test arbitrary prose and nested references, not
only a hand-picked sensitive-word list.

### P1: decline storage can mutate inspected scope

The journey accepts a `ContributionDeclineStore` without rechecking it against the
approved inspection roots; constructor validation is optional. The reviewer wrote a
decline ledger inside an approved root.

**Required design:** validate the configured durable store against the journey's actual
approved roots at the point of use. Writes must remain outside the inspected brain/vault
and still use the ownership/deletion contract.

### P1: the detector has common false negatives

Examples which were retained as non-personal include `I am sick with diabetes`, `my illness
record`, `paid $50,000`, IBAN-like values, and lower-case company names.

**Required design:** do not try to make a regex corpus the sole privacy boundary. Structural
minimisation of every outgoing Card is the primary fix; a conservative detector and test
corpus remain useful as a second layer.

### P2: identity is called before permission validation

A forged/invalid `PermissionSet` can cause `contributor_secret()` to run before
`ConsentLedger.grant` rejects the approval.

**Required design:** validate permission and the exact outgoing Card before deriving or
accessing contributor identity. Add a negative test proving zero identity calls.

### P2: concurrent declines lose durable suppression

The decline ledger performs an unlocked load/replace. Two concurrent declines can leave
only one digest, causing the other candidate to be offered again. Temporary decline files
also are not covered fully by deletion.

**Required design:** lock and merge atomically, prove concurrent writers preserve both
digests, and include temporary files in safe cleanup/deletion evidence.

Do not merge the privacy candidate merely because its existing tests are green. Add
failing-first tests for all five reproduced cases, fix them, rerun the full repository
suite and inventory, then commission a fresh independent review.

## 9. Ordered execution plan

### Phase 1A — freeze a trustworthy Core/Codex head

1. Clone `davekilleen/Dex` and start from
   `codex/dex-everywhere-cursor-handoff` at its exact pushed tip.
2. Run `python3 scripts/dex_state.py --digest`, then read:
   `docs/architecture/DEX-CORE-MAP.md`, generated
   `docs/architecture/INVENTORY.md`, `CHANGELOG.md`, the Dex Everywhere plan, platform
   docs, and press release.
3. Fetch current `main`. The branch already includes `5d1c7027`; merge normally only if
   `main` has advanced. Preserve all new main work. Do not rebase or force-push.
4. Re-run the historical failing set, then the full Python suite in a clean virtual
   environment with a private temporary directory. Fix only genuine branch regressions.
5. Run the complete local Core gate list in section 10.
6. Push a draft-PR head and wait for exact-head GitHub CI. Both native macOS and native
   Windows portable jobs must be green, as must the twelve-journey macOS fleet canary.
7. Prove the **Codex** golden journey from detection through onboarding receipt, Doctor,
   MCP/skills use, safety truth, update/customisation preservation, and staged artifact.
8. Record exact commit, commands, counts, job links, and deliberate exclusions.

### Phase 1B — Claude Code and Cowork

1. Prove Claude Code against the same shared Core and portable skills/MCP contract.
2. Confirm Claude Code authentication via safe browser flow where the native host runs;
   never transfer credentials into Cursor Cloud.
3. Prove Cowork's supported path and report unavailable/advisory capabilities exactly as
   the registry defines them.
4. A Cursor Ubuntu session may implement and trigger tests, but it cannot itself prove a
   Cowork desktop UI journey. Record a native-host receipt at the exact Core head.
5. Do not overclaim hook or session-lifecycle behaviour where the host cannot enforce it.

### Phase 1C — remaining portable hosts

Run or re-prove the advertised golden journeys for Copilot CLI, Pi, and supported Agent
Plugin clients. Pin real upstream evidence for Pi or downgrade its rows. Ensure every
Doctor/onboarding claim is capability-derived, not brand-derived.

### Phase 2 — privacy-safe capability exchange

1. Work in `davekilleen/dex-lens`, not Dex Core. Capability Exchange now lives in the
   Dex Lens repository.
2. Rebase is unnecessary; merge current `main` into an isolated integration branch.
3. Preserve the `a12b3b8` Lens-doorway correction.
4. Treat `c76f1f5` as a reviewed prototype, not an acceptable implementation.
5. Implement failing-first repairs for all section 8 findings.
6. Prove candidate → automatic abstraction → exact preview → explicit consent → hosted
   intake → moderation state → recipient discovery → withdrawal/deletion.
7. Prove no request is made before consent, no raw source text/reference enters any request
   body, declines persist across restarts and concurrent writers, and incompatible or
   irrelevant opportunities remain silent.
8. Keep hosted intake private/unreleased. Do not deploy it.

### Phase 3 — BB and getbb.app, deliberately later

The code and native macOS workflow are already green at exact head. Revisit only after
Core/Codex and Claude/Cowork are stable:

1. Verify the full BB tree, not just the PR diff.
2. Re-run 36 tests, typecheck, build, package audit, package check, tarball inspection, and
   native macOS CI if any file changes.
3. Retain `private: true`/the accidental-publication boundary while unreleased.
4. Confirm the documented getbb.app acquisition route against current first-party BB
   evidence.
5. Keep macOS-only scope explicit; Linux/WSL2 stay deferred.

### Phase 4 — reconcile human-review surfaces

Only after all final code heads and CI links exist:

1. Update Core draft PR #594.
2. Update BB private draft PR #1.
3. Update Mission Control draft PR #95 and its Build Card.
4. Reconcile architecture/capability docs and generated inventory.
5. Reconcile the platform matrix.
6. Reconcile the unreleased press release at
   `docs/press/2026-08-25-dex-everywhere-unreleased.md`.
7. Rerun genuine Fable architecture and implementation reviews.
8. Independently verify and fix every material final finding.
9. Repeat proportionate local/native CI after any review-driven change.
10. Ensure every PR remains open and draft and every worktree/branch is clean and pushed.

## 10. Core verification contract

Run from a clean, dependency-isolated checkout. Use a private temporary directory if the
shared `/tmp` inode pool is under pressure.

```bash
python3 -m pytest core/tests/ core/mcp/tests/ core/migrations/tests/ -m "not fuzz"
npm run test:hooks
npm run test:scripts
npm run test:integrations
npm run check:connections-contract
bash scripts/check-portable-contract.sh
python3 scripts/generate-harness-portability.py --check
python3 scripts/generate-harness-registry.py --check
python3 scripts/generate-agents-skills.py --check
python3 scripts/generate-portable-plugin.py --check
bash scripts/check-pii.sh
bash scripts/check-founder-content.sh
```

Also run the architecture inventory check/generator according to repository instructions,
the release-asset/draft-first tests, capability/onboarding/Doctor tests, every host golden
journey, the connection consumer checks, and any focused test introduced by a fix.

GitHub exact-head acceptance must include:

- all Core quality/test/report jobs;
- native macOS portable runtime journey;
- native Windows portable runtime journey;
- twelve release-shaped macOS fleet journeys;
- release/draft artifact checks applicable to a PR;
- no hidden skipped mandatory job.

## 11. Supported-platform and host truth to preserve

| Surface | Supported boundary |
| --- | --- |
| Dex Core | macOS and native Windows |
| Dex Core on Linux | explicitly deferred for this programme |
| Standalone BB plugin | macOS only |
| BB on Linux/WSL2 | explicitly deferred |
| Cursor Cloud | implementation runner on Ubuntu; not native platform proof |
| Codex | first-priority host journey |
| Claude Code | second-priority shared-Core journey |
| Claude Cowork | second-priority native/UI journey; capability truth may be partial |
| Copilot CLI | supported only to the modes proven by registry/evidence |
| Pi | claims require pinned evidence; otherwise downgrade |
| Agent Plugin clients | supported only to the common contract each client actually implements |

For every host, distinguish `native`, `guided`, `not-verified`, and `unavailable`. MCP
advice is not an interceptor. A safety check must not be described as enforced if the host
cannot intercept the action.

## 12. Dex contracts which no fix may weaken

1. **One safe door:** every vault mutation goes through
   `core/lifecycle/service.py` → transaction core → portable ownership contract.
2. Generated files are regenerated, never hand-edited.
3. Every new top-level path is classified by the portable contract.
4. User customisation namespaces survive installation and update, including nested
   `*-custom` skill directories.
5. Inspection is read-only; consent to inspect is not consent to write or transmit.
6. The exact outgoing contribution bytes are previewed and consented before any network or
   identity action.
7. No PII or founder-machine/company content is allowlisted around a genuine leak.
8. Old/customised Dex and non-Dex brains receive truthful capability/version guidance;
   never assume stock current Dex.
9. Release truth comes from version/tag/CHANGELOG and obtainable artifacts, not from a
   merge or green tests alone.

## 13. Human-review-ready definition

Do not declare success until all of the following are true:

- no unresolved material genuine-Fable finding remains;
- every Fable finding was independently reproduced or rejected with evidence;
- all applicable local checks and native CI are green on the exact final heads;
- Core, capability exchange, BB, and Mission Control branches are clean and pushed;
- the three named PRs remain open drafts and describe the final state;
- Mission Control, repository docs, platform matrix, press release, code, and CI agree;
- macOS/native-Windows boundaries are proved and Linux/WSL2 deferral is explicit;
- BB remains accurately macOS-only;
- a reviewer can understand what changed, why it matters, how it was tested, and what is
  deliberately excluded;
- nothing has been merged, published, deployed, submitted, installed for users, or
  released.

The final handoff must contain outcome/significance, exact Core/BB/Mission Control (and
capability-exchange, if used) commits, all draft PR links, test counts and CI URLs, Fable
results and dispositions, the platform/host matrix, known limitations, the press-release
link, and explicit confirmation that release remains closed.

## 14. First Cursor task prompt

Use this as the first instruction after selecting `davekilleen/Dex` and the exact handover
branch:

> Continue the unreleased Dex Everywhere programme from
> `docs/plans/2026-08-27-cursor-cloud-dex-everywhere-handover.md`. Verify the checked-out
> commit matches the pushed branch tip. Work only on an isolated branch. Preserve all
> unrelated work. Begin with Phase 1A: fetch `origin/main` and merge it normally only if it
> is newer than integrated main `5d1c7027`; rerun the historical failing set and fix any
> remaining genuine Core failures test-first, then run the complete Core local
> verification contract. Prioritise the Codex golden journey. Do not move to Claude
> Code/Cowork until the Core/Codex head is clean and exact-head native CI is green. Do not
> merge main, publish, deploy, install for users, change billing, copy credentials, or
> release. Report exact commits, commands, counts, and CI links; distinguish Ubuntu runner
> evidence from native macOS/Windows evidence.
