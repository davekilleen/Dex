# Dex Core — Architecture Map

> **Purpose.** The authoritative, human-readable "how Dex Core hangs together" doc. Load this before working in the `dex-core` repo so you start from what actually exists, not stale assumptions.
>
> **Status vocabulary.** `SHIPPED` = in a released version tag. `LOCAL` = merged on `main`, not yet in a release tag. `PROTOTYPE` = built, not verified against live/real use. `PLANNED` = designed, not built.
>
> **Ground truth as of** `upstream/main` at `fd335640`, latest release tag **v1.97.0** (2026-08-13). Dex Everywhere portability remains unreleased on this branch; exact-head native macOS/Windows acceptance is green, while the mandatory Fable reviews and live release-candidate installs are still pending.
>
> **Don't duplicate generated files.** Tool lists, skill lists, ownership-class path tables, and MCP↔skill wiring live in the auto-generated `docs/architecture/INVENTORY.md`. This map cross-references it; it does not restate it.
>
> **Version sources.** `CHANGELOG.md` is the release truth; `docs/architecture/STATE.md` (regenerate with `python3 scripts/dex_state.py --write`) is the released-vs-LOCAL snapshot. `CLAUDE.md`'s header is user-facing seed prose, not a version source.

---

## Subsystem index

| Subsystem | Status | Lives in | One line |
| --- | --- | --- | --- |
| Lifecycle "safe update" engine | **SHIPPED** (v1.65–v1.68) | `core/lifecycle/*` | Frozen public API: preview → backup → apply → verify → receipt → rewind, over a release catalog + ownership contract |
| Transaction core | **SHIPPED** (v1.66) | `core/transaction/*` | Crash-safe snapshot→apply→verify→commit/rollback substrate the lifecycle engine writes through |
| Portable ownership contract | **SHIPPED** (v1.64+) | `core/portable_contract.py` | Source of truth: every path is brain/seed/generated/vault/runtime; decides what an update may write |
| Release catalog + bridge | **SHIPPED** (v1.65–v1.68) | `core/lifecycle/catalog/*`, `bridge.py` | Publisher-declared packing list per release; one-release handoff from the legacy updater |
| Historic updater journey protocol + executor | **SHIPPED** (v1.81.0), acceptance pending | `core/update/journey-protocol-v1.json`, `core/update/journey_protocol.py`, `scripts/release_fleet_executor.py` | Closed release-owned machine contract and evidence-owning implementation for the pinned bridge and lifecycle delivery route |
| 10 MCP servers | **SHIPPED** (mixed ages) | `core/mcp/*_server.py` | The tool surface Dex acts through; Work MCP is the giant (see INVENTORY) |
| Connection Manager (OAuth/token) | **SHIPPED ENGINE, `/connect` HELD** | `core/integrations/connection-manager/` | Local-first OAuth via Nango catalog-as-data; encrypted on-device tokens; hardened through security Phases 0–5g, but the `/connect` doorway stays held (draft PR #231) |
| Customization migration | **SHIPPED** assess/capsule/guided-journey (v1.75.x) / **LOCAL** rebuild engine and doorway | `core/customization_migration/*`, `core/mcp/customization_migration_server.py` | Inventories customizations, preserves a Capsule, and offers a human-confirmed, receipt-backed rebuild and rewind; the doorway is authorized but remains unshipped until its release |
| DexDiff (methodology sharing) | **SHIPPED** cmd surface / **PARKED** redesign | `.claude/skills/diff-*`, `core/dexdiff_profile_adopt.py` | Generate→publish→adopt-regenerates-locally; redesign parked for the desktop "Vorflux" rebuild |
| Entity engine + gardener + relationships | **SHIPPED** (v1.37 / v1.44 / v1.71–v1.73) | `core/entity_engine/*`, `core/entity_maintenance.py` | Auto-creates person/company pages, logs meeting touches, classifies relationship temperature, resurfaces relationships going cold, and maintains typed person↔company relationships (suggested-until-confirmed) |
| Ritual intelligence | **PARKED** (code-complete, unwired) | `core/ritual_intelligence/*` | Meeting-intelligence pipeline built Mar 2026, tested in CI, but never wired to any skill/hook/MCP; its beta preview surface was explicitly retracted (see CHANGELOG) |
| Hooks | **SHIPPED** (wired subset) | `.claude/hooks/`, `.claude/settings.json` | Small wired core (context injection, safety guards, release awareness, autocommit); the once-dead career-evidence hook is fixed (PR #180) |
| Skills (74 on disk) | **SHIPPED** | `.claude/skills/` | `/command` workflows; the description-rewrite + `/skill-score` quality-gate pass landed (discoverability-risk 53 → 3) |
| Grounding suite (inventory + state + orient) | **SHIPPED** (v1.69+) | `docs/architecture/INVENTORY.md`, `STATE.md`, `scripts/dex_state.py`, `/dex-orient` | Code-derived inventory + CI drift gate, released-vs-LOCAL state snapshot, and a session orientation skill |

---

## 1. Lifecycle "safe update" engine — SHIPPED (v1.65–v1.68)

**What it is.** The single protected path through which Dex changes a user's vault: installing, updating, adopting a feature, self-healing via Doctor, or undoing. The user-facing promise (v1.68 changelog): "one safe door for every change" — preview what changes, back it up, apply, verify, write a receipt, and be able to rewind exactly.

**Where it lives.** `core/lifecycle/`:
- `service.py` — the **frozen public API v1** (`api_version = "1.0.0"`). Sole sanctioned entry point; contains no policy, composes catalog/inventory/plan/ledger/retention for reads and delegates mutations to `engine.py`. Its additive conflict path is `build_and_preview_conflict_resolution` → `execute_approved_conflict_resolution`; the original five operation shapes remain unchanged.
- `engine.py` (42 KB) — the mutation engine; delegates every write to `core/transaction` + `core/portable_contract`.
- `plan.py` / `preview.py` / `conflict.py` — build the per-item adoption plan and canonical approval previews (each item decided independently so "skip this one" can't affect the rest — v1.65 guarantee). Conflict resolution can take the release version or atomically keep both for skills: the release becomes canonical while the user's edited bytes are preserved at `.claude/skills/{name}-custom/`; the ordinary adoption receipt makes either choice rewindable.
- `inventory.py` — reads a vault "like a map without touching it": classifies what's Dex's, what's customized, what's the user's, what's unrecognized.
- `ledger.py` (40 KB) — the **tamper-evident receipt ledger** under `System/.dex/ledger`; detects altered/missing entries and self-heals torn writes (v1.67).
- `sqlite_snapshot.py` — safe backup of SQLite DBs (the v1.66 "databases get real protection" + power-loss-safe restore order).
- `catalog.py`, `retention.py` (keep last 3 rewind points, ~2 GB warn), `customizations.py`, `machine_state.py`, `runtime_evidence.py`, `secrets.py`, `bridge.py`, `cli.py`.

**Status confirmation.** CHANGELOG v1.65 (look-don't-touch), v1.66 (apply+undo, DB protection), v1.67 (ledger + Doctor UI), v1.68 (every path routed through it). `install.sh`, `core/provision.cjs`, `/dex-update`, and `/dex-rollback` all reference the lifecycle service — confirming the "one door" is really wired, not just present.

**Since v1.68 (v1.69–v1.75.2).** The engine gained the brain/vault-split journey and its safety net: a guided upgrade path wired into `/dex-update` (Lane E, v1.75.0/1.75.1), management of the pre-split undo archive + obvious migration recovery (Lanes C+D), conflict resolution's keep-both writer + choice layer (frozen op pair, PR #205/#208), and the guided journey for deeply customized setups (Lane H, capsule-scoped — see §12). A real-vault rehearsal before switch-on surfaced and fixed four findings (v1.75.2): refusal to convert a vault inside a cloud-synced folder (Dropbox etc.), a 12k-file crash, accented-filename false-failures, and clearer symlink-refusal messaging.

**How it connects.** Consumers (installer, updater, Doctor, rollback skill) → `lifecycle/service.py` → `engine.py` → `transaction` (crash safety) + `portable_contract` (write authorization) → `ledger` (receipts). The release catalog feeds it what a version contains.

## 2. Transaction core — SHIPPED (v1.66)

**What it is.** The crash-safe substrate underneath the lifecycle engine: begin → snapshot → apply → verify → commit, with `rollback()` any time and `resume()` after a crash that **always rolls back** a non-committed transaction (no half-states, no roll-forward — you just re-run).

**Where it lives.** `core/transaction/`: `engine.py` (orchestration), `lock.py` (owner-safe fsynced lock, PID-liveness), `journal.py` (append-only fsynced journal, torn-tail truncation), `snapshot.py` (byte-exact copies + sha256 manifest under `System/.dex/tx/<id>/`). Design: `docs/transaction-core-design.md`.

**Key invariant.** `Transaction.begin()` validates **every** plan entry through `portable_contract.update_write_verdict` before the first byte — any disallowed/vault/unclassified entry aborts the whole transaction (all-or-nothing gate). This is why the ownership contract is load-bearing, not advisory.

**How it connects.** Written to only via `lifecycle/engine.py`. The one-time v1→v2 migrator keeps its CJS internals but shares this core's lock + journal dir so the two can never run concurrently.

## 3. Portable ownership contract — SHIPPED

**What it is.** The source of truth for who owns every path in a Dex install. Five classes govern what an update may do:
- `brain` — release-owned, replaced wholesale (44 paths).
- `seed` — shipped once then user-owned, written only if absent (38).
- `generated` — machine-derived, regenerated (7).
- `vault` — user content, an update NEVER writes it (17).
- `runtime` — local machine state, never shipped/updated (13).

**Where it lives.** `core/portable_contract.py` (the RULES + MUTATION_POLICY). Generated JSON view: `packages/dex-contracts/dist/portable-vault.contract.json`. Full per-path table: `docs/architecture/INVENTORY.md` § "Portable ownership classes". Design: `docs/portable-vault-contract-design.md`. Ratified in Vault_Contract v1 (2026-06-18).

**Fail-safe.** An unclassified path is NEVER written (`update_write_verdict`). `scripts/check-portable-contract.sh` fails CI if any tracked repo path doesn't resolve — so adding a top-level path forces a deliberate classification.

**Known limitation (in code).** Classification assumes the default PARA layout; a user who remaps folders via `System/folder-paths.yaml` must have paths canonicalized first, or they're treated as unclassified (and thus never written). Native `folder_map` support is noted as landing "with the first consumer (PR-1)".

## 4. Release catalog + bridge — SHIPPED (v1.65–v1.68)

**What it is.** Each release carries an exact packing list. `core/lifecycle/catalog/*.json` (publisher-owned declarations, e.g. `official-capabilities.json`) is read by the release builder in filename order and emitted as the canonical `System/.release-catalog.json`. The separately modeled `bridge-release.json` keeps its publisher-owned compatibility contract, while the release generator stamps its `release_version` from the same `package.json` version used by the canonical catalog and validates the result through the strict bridge model. `bridge.py` handles the one-release handoff from the legacy CJS updater to the new engine (resumes safely even if a prior update was interrupted — the v1.68 "smooth bridge").

**How it connects.** Feeds `lifecycle/plan.py` (what's available to adopt) and the DexDiff-adjacent adoption receipts under `System/.dex/adoptions/`. The v1.67 "two dozen role-specific tools you can turn on safely" are catalog items adopted through this path.

### Historic updater journey protocol — SHIPPED CONTROL PLANE, ACCEPTANCE PENDING

`core/update/journey-protocol-v1.json` is the release-owned control plane for
historic fleet evidence. Its strict parser permits only the pinned
foundation-bridge adapter and the existing
`deliver_latest_release` → `build_and_preview_delivered_release` →
`execute_approved_delivered_release` lifecycle sequence. The generated root
binds the exact bridge, fleet-runner, and executor bytes in the publisher
source commit, the immutable v1.81.0 foundation identity, maximum conditional
approval counts, macOS support, and the required evidence order. Unknown
fields, adapters, operations, hashes, or approval shapes fail closed; there is
no arbitrary command vocabulary.

`scripts/release_fleet_executor.py` owns one real journey: it verifies its
released source identity, invokes the pinned bridge and only the three declared
lifecycle operations, records the approval prompts that actually occurred,
checks installed refs, runs the installed Doctor and smoke suite, hashes
user-owned files, and writes receipts and the transcript itself. Its successful
result carries process-local authority that serialized JSON cannot recreate;
`check-report` therefore stays closed to externally authored substitutes.

This is implementation truth, not release acceptance. Public v1.81.0 contains
the foundation and closed journey contract, but the separate follow-up and full
170-tree macOS journey have not yet completed. The fleet-acceptance result
therefore remains false.

## 5. The 10 MCP servers — SHIPPED

**What they are.** The tool surface Dex acts through. **Do not restate the tool lists — read `docs/architecture/INVENTORY.md` § "MCP engines" for exact per-server tool names.** Summary:

| Server | Source | Tools | `feature_status` honesty contract |
| --- | --- | ---: | :---: |
| `dex-work-mcp` | `work_server.py` (247 KB) | **50** | yes |
| `dex-calendar-mcp` | `calendar_server.py` | 15 | yes |
| `dex-resume-mcp` | `resume_server.py` | 12 | yes |
| `dex-improvements-mcp` | `dex_improvements_server.py` | 9 | **no** |
| `dex-career-mcp` | `career_server.py` | 8 | yes |
| `dex-onboarding-mcp` | `onboarding_server.py` | 8 | **no** |
| `dex-session-memory` | `session_memory_server.py` | 8 | **no** |
| `dex-granola-mcp` | `granola_server.py` | 6 | yes |
| `dex-customization-migration-mcp` | `customization_migration_server.py` | 7 | yes |
| `dex-analytics` | `analytics_server.py` | 4 | yes |

**The big one.** `dex-work-mcp` is the spine of `/daily-plan`, `/week-plan`, `/process-meetings` (tasks, people/company indexes, goals, priorities, meeting cache, plus `boot_today` / `get_person_context` / `check_safety_gate` for harness-portable context and advisory gates). Per INVENTORY's connectedness section, three servers are **under-surfaced** (0 skills reference them): `dex-career-mcp`, `dex-resume-mcp`, and `dex-session-memory`. The customization-migration MCP is now surfaced through `/dex-update` for Capsule evidence and readable blob access. `dex-analytics` is **over-surfaced** (28 skills call `track_event`).

**Honesty-contract gap.** Three servers lack `feature_status` (`dex-improvements-mcp`, `dex-onboarding-mcp`, `dex-session-memory`) — meaning they don't return the ok/off/not_installed/broken/unknown status envelope the rest do. That's the honest weak spot in the "every MCP tells you its health" story.

## 6. Connection Manager (OAuth/token layer) — SHIPPED ENGINE, PRODUCT-INERT

**What it is.** Local-first OAuth + token management. No Docker, no relay, no cloud. Provider config comes from Nango's open-source catalog (`@nangohq/providers`, ~831 providers, pinned) consumed **as data only**; the runtime (OAuth2 + PKCE, refresh, health state machine) is Dex-owned plain Node; tokens live AES-256-GCM-encrypted on-device under `{DEX_VAULT}/System/credentials/`.

**Where it lives.** `core/integrations/connection-manager/`: `catalog.cjs` (Nango entry → Dex OAuth descriptor), `oauth-flow.cjs` (PKCE + localhost callback + refresh), `token-store.cjs` (encrypted store + `connections.json`), `health.cjs` (connected/expiring/expired/needs_reauth state machine), `connect.cjs` (CLI), `get-token.cjs` (Python MCP accessor). Also `CONSUMPTION-LAYER.md`. Tests: `connection-manager.test.cjs`, run in CI via `npm run test:integrations`.

**Status.** The original engine passed its first live-account gate on 2026-07-24 (runbook: `docs/solutions/connection-manager-live-account-gate.md`) and ships from v1.73 onward. Phase 2 then lifted Desktop's judgment layer into `lib/` (pinned at dex-desktop `2b34aa4d`, hash-verified by `lifted-conformance.test.cjs`): one refresher, bounded Google/Slack/Linear probes, a durable evidence ledger, `status --json`, and Doctor reading real engine health. Phase 3 froze the Desktop consumer contract and engine manifest; the post-Phase-2/3 Google + Linear live-account rerun passed on PR #221.

**Security hardening Phases 5a–5g (all merged, v1.74–v1.75.2):** connection-manager hardening (5a, #228), origin pinning + tamper-proof trust (5b, #230), credential broker (5c, #232), user-presence gate on privileged export (5d/B1, #237), fail-closed on untrusted presence configuration (#239), refresh-steering + default-routing critical fixes (5f, #243), and presence op-scoping + broker auth + timeouts + honest docs (5g, #247).

**DOORWAY STILL HELD:** `/connect` and its session-start hook exist only on draft PR #231 and do not ship. The Phase 5e re-review returned a no-go on the same-user credential boundary (direct decryptor, persistent readable broker capability, unprompted default accessor); Phases 5f–5g closed named criticals but the no-go verdict on the doorway itself has not been lifted — CHANGELOG v1.74–v1.75.2 still describes all of this as "groundwork." Do not describe `/connect` as available. Licence note: Nango providers is Elastic License 2.0 (source-available), consumed as a pinned npm dependency, not vendored; never re-expose the catalog as a managed service.

**How it connects.** Doctor consumes the secret-free `status --json` contract, and Desktop can vendor the pinned engine through `@dex/contracts`. The future doorway will sit under integration setup skills and feed fresh tokens to Python MCP servers via `get-token.cjs`; that doorway is not in the tree today. Existing per-integration `detect.py` / `task_sync.py` paths remain parallel.

## 7. DexDiff — SHIPPED command surface / PARKED redesign

**What it is.** Jobs-to-be-done sharing: package how you use Dex (`/diff-generate`, `/diff-profile`), publish to heydex.ai, and let others adopt — where **adopt regenerates locally** for their role/vault rather than copying your files (`/diff-adopt`, `/diff-adopt-profile`, `/diff-list`, `/diff-remove`).

**Where it lives.** Skills `.claude/skills/diff-*`; local adoption logic `core/dexdiff_profile_adopt.py`; boundary spec `docs/dexdiff-runtime-boundary.md`. Runtime split: `dex-core` owns the `/diff-*` surface + the DexDiff Convex client + local application; `heydex-website` owns auth, hosted review sessions, published storage, profile pages.

**Known issues (real, in code).**
- **PII gate is prompt-only.** `diff-generate` has no redaction machinery — just guidance (e.g. "skills with `-dave` suffix are custom"). Nothing structurally stops personal content leaving.
- **`/diff-adopt` edits CLAUDE.md and hooks.** Confirmed in the skill body: it appends a "Meeting Workflow" section to CLAUDE.md and creates hook scripts in `.claude/hooks/` + registers them in `.claude/settings.json`. That's a broad blast radius for an "adopt a workflow" action, and it runs outside the lifecycle safe-door.

**Status.** The command surface is shipped and usable; a **redesign is PARKED** for the desktop "Vorflux" rebuild. Treat DexDiff as functional-but-frozen — don't invest in hardening the current CLI PII/adopt path; that work moves to Vorflux. One fix since: the CLI now publishes to DexDiff's own backend rather than the Desktop domain (#245, v1.75.2).

## 8. Entity engine + gardener + relationships — SHIPPED (v1.37.0 / v1.44.0 / v1.71–v1.73)

**What it is.** Three layers. (a) **Entity engine** — background meeting sync deterministically creates person/company pages once someone with an email recurs (2+ meetings across 2+ weeks, or 2+ meetings with transcript evidence); `entity_creation` config = `auto`/`suggest`/`off`. (b) **Gardener** (v1.44) — keeps a living "who this person is to you right now" summary block on active pages, refreshed at most weekly, ≤5 pages/sync, only when something new happened, only if an AI key is present. If the user edits inside the marked block, Dex permanently stops maintaining it. (c) **Relationship cooling — SHIPPED (v1.71)** — meeting sync and the post-meeting hook log canonical, idempotent touches; the pure temperature classifier separates warm, cooling, and cold relationships; and the cooling read only surfaces cold people/accounts with engagement on at least two distinct days. (d) **Typed relationships — SHIPPED (v1.72–v1.73)** — map-first, suggested-until-confirmed person↔company/person↔person relationships (`core/entity_engine/relationships.py`), with the v1.73 fast-follow: confirming one suggestion affects only that suggestion, edge-key ownership + tombstones, a hard `mode: off` gate, and an explicit confirm affordance. Surfaced through Work MCP's `confirm_relationship` / `dismiss_relationship` tools (used by `/daily-plan`). A JS↔Python write bridge (#196) makes the Python engine the canonical writer with never-lose-a-write reliability.

**Where it lives.** `core/entity_engine/contract.py` (canonical parse/render, frontmatter, quarantine and composite writes), `core/entity_engine/index.py` (disposable SQLite projection), `core/entity_engine/temperature.py` (pure classifier), `core/entity_engine/cooling.py` (read + `System/.dex/entity-cooling.json` feed), and `core/entity_maintenance.py` (metadata maintenance CLI). Gardener and cooling-feed refresh both tie into the meeting-sync path. Off switch for the gardener: `entity_gardener: enabled: false`.

**How it connects.** Consumes Work MCP meeting/attendee data; produces the person/company pages and disposable index that `lookup_person`, context-injector hooks, and `/process-meetings` read. Sync refreshes the cooling feed after entity work, and `/daily-plan` turns its consequential `cold` list into one "❄️ Going cold" heads-up line.

## 9. Hooks — SHIPPED wired subset / dead weight present

**What it is.** Event-driven shell scripts. The **actually-wired set** (from `.claude/settings.json`) is small:
- SessionStart → `session-start.sh` + `core/utils/update_verifier.py` (bounded release awareness).
- PreToolUse/Read → `person-context-injector.cjs`, `company-context-injector.cjs`.
- PreToolUse/Bash → `dex-safety-guard.sh`, `ensure-mcp-user-scope.cjs`.
- PreToolUse/`mcp__.*` → `dex-safety-guard.sh`.
- SessionEnd → `session-end.sh`, `vault-autocommit.cjs`.
- Stop / Notification → a sound (`afplay`).

**Dead weight / audit findings.**
- **Observation layer** (`observation-extract.cjs`, `observation-profile.cjs`, `observation-serendipity.cjs`, `observation-weekly-synthesis.cjs`, `observation-utils.cjs`) and the **health-checkers** (`connection-health-checker.cjs`, `gmail-health-checker.cjs`, `teams-health-checker.cjs`) exist **only as UNTRACKED local files** on the maintainer's machine — `git ls-files` shows none of them, and neither does `docs/observation-layer-beta-rollout.md`. **They are not in the repo and never ship to users.** So there is no observation layer in the distributed product to "remove"; it's local experimentation. Don't cite these as Core behavior.
- **`career-evidence-capture.cjs` was silently dead — now fixed (PR #180).** It read hook input from `process.env.CLAUDE_HOOK_CONTEXT`, but Claude Code delivers hook input on **stdin** (as the wired hooks do), so it exited at the first guard every time and captured nothing. PR #180 switches it to read stdin and adds an input-contract test so no hook can regress to the env-var pattern. (This is the one tracked observation-adjacent cleanup; the untracked `staging/vault-fixes/` prototype is deleted in the same PR.)

**How it connects.** Wired hooks feed context injection, safety guards, and the bounded release-awareness notice. Automatic firing is **Tier 3 Full** and Claude Code only today — a stated position. Session boot and person-inject payloads are **Tier 1 Core**: `boot_today` and `get_person_context` on Work MCP, implemented in `core/context/`, with the Claude Code hooks as thin wrappers. `check_safety_gate` is an advisory MCP surface; only a verified pre-tool interceptor can enforce it. Scheduled jobs (`com.dex.meeting-intel` and the other launchd promises) are already **Tier 1 Core** and do not need a hook. Three-bucket inventory: `docs/architecture/HOOK-INVENTORY.md`. The observation/health-checker scripts are **untracked local cruft, not product** — treat them as absent when reasoning about what a user's install does.

## 10. Skills — SHIPPED (74 counted by generator)

**What they are.** `/command` workflows in `.claude/skills/`. **Full list + descriptions + trigger analysis: `docs/architecture/INVENTORY.md` § "Skills".** The **discoverability overhaul landed** (v1.69–v1.70): 49 descriptions rewritten with explicit trigger phrases (#184), a `/skill-score` quality gate for new skills (#183), and `create-skill` v2 with collision-check, origin-aware, score-gated authoring (#192). The generator's discoverability-risk count fell from **53 to 3** (the three remaining are Anthropic-bundled artifact/theme skills, not Dex workflows). Role-specific optional skill packs live in `.claude/skills/_available/`, gated by the capability registry (`core/capabilities.py`, `/manage-capabilities`), and are adopted through the lifecycle catalog.

**Governing principle.** "Hard on Core, gentle on user skills": Core-shipped skills get held to the trigger/quality bar and can be consolidated/rewritten; user-authored skills (the `-custom` suffix convention from `create-skill`, and the `.claude/skills-custom/` vault-class dir) are protected from updates and left alone. `create-skill` auto-appends `-custom` so user skills are never overwritten.

**How it connects.** Skills call MCP tools by name (see INVENTORY connectedness). Some skills (`diff-adopt`) write CLAUDE.md/hooks directly — see §7 blast-radius note. Skill payloads that ship as catalog items flow through the lifecycle safe-door (§1/§4).

## 11. Grounding suite — SHIPPED (v1.69+)

**What it is.** The effort this very doc is part of: give agents code-derived truth instead of stale assumptions. All three chunks now exist:
- `docs/architecture/INVENTORY.md` (generated) + `scripts/generate-architecture-inventory.py` + the CI drift gate (`scripts/check-architecture-inventory.sh`, wired in `.github/workflows/ci.yml` as "Architecture inventory drift gate") — landed as PR #179.
- **State snapshot:** `docs/architecture/STATE.md` + `scripts/dex_state.py` (`--write` refreshes the generated block; `--digest` prints a compact SessionStart digest).
- **Session orientation:** the `/dex-orient` skill — prints released version, merged-but-unreleased work, and where map + inventory live.

**How it connects.** The inventory generator parses `core/mcp/*_server.py`, `.claude/skills/*/SKILL.md`, and `core/portable_contract.py` by AST/regex, so the drift gate fails CI if code and INVENTORY diverge. This map is the human narrative layer above that machine inventory — read both: INVENTORY for exact lists, this map for what's real, what's shipped, and how it fits. STATE.md has no CI gate — refresh it (`python3 scripts/dex_state.py --write`) whenever you touch this map.

## 12. Customization migration — SHIPPED assess/capsule/guided-journey (v1.75.x) / LOCAL rebuild doorway

**What it is.** The machinery that lets an update respect a user's customizations instead of silently overwriting or stranding them. Built as lanes A–H over 2026-07-23→26: Doctor produces a **read-only inventory** of everything the user has customized (edited skills, added scripts, custom instructions) with sensitivity classification (v1.75.1); a consent-gated, protected local **Capsule** snapshots the customization evidence through the sealed transaction (Lanes C/E-staging/F); `/dex-update` offers a **guided journey** for deeply customized setups — shows the inventory, explains impact, walks step by step (Lane H, v1.75.2); regeneration candidates are validated before anything is proposed (#238).

**Where it lives.** `core/customization_migration/` (17 modules: `service.py`, `capsule.py`/`capsule_model.py`, `inventory.py`, `sensitivity.py`, `planning.py`, `staging.py`, `verification.py`, `activation.py`, `behaviour.py`, `registration.py`, `references.py`, `report.py`, `state.py`, `model.py`, `cli.py`, …) + the `dex-customization-migration-mcp` server (7 read-only tools, including digest-bound access to sensitivity-approved Capsule text blobs; surfaced through `/dex-update` and Doctor). Lane A's binding contracts: `docs/customization-migration-threat-model.md`; build plan: `docs/plans/2026-07-24-customization-migration-mcp.md`.

**LOCAL, not shipped:** Lane G's activation + rewind engine is merged and rehearsal-proven. The rebuild doorway on this branch adds the human-confirmed CLI journey through staging, verification, activation, status, recovery, and receipt-backed rewind. The MCP remains read-only and exposes bounded Capsule evidence, readable text blobs, and status. This doorway is authorized for release, but it is not available to users until this branch is merged and a release containing it is published.

**How it connects.** Wired into the lifecycle engine (§1) — the guided journey runs inside `/dex-update`; capsule writes go through the sealed transaction (§2); Doctor reads the assessment via the MCP server.

## 13. Ritual intelligence — PARKED (code-complete, unwired)

**What it is.** A meeting-intelligence pipeline (transcript + calendar ingest, ritual matching, meeting reconciliation, brief generation, contact promotion) built March 2026 (#30) at `core/ritual_intelligence/` with a `python -m core.ritual_intelligence` entry point and its own CI-passing tests. **Nothing invokes it**: no skill, hook, MCP server, or the desktop app references it, and the CHANGELOG records the retraction of its beta preview surface ("an unwired ritual beta handout no longer tells testers that `/daily-plan` will surface recurring-meeting previews"). Its tests keep it green in CI, which makes it look alive from a coverage view — it is not. Treat as parked design capital, not a shipped subsystem; wire-or-retire is an open product decision.

---

## What surprised even Fable this session (why this doc must exist)

Concrete non-obvious things that a fresh agent would get wrong by reasoning from priors:

1. **The Work MCP is a 46-tool monster (247 KB).** Most of its tools are never named by any skill; the breadth is easy to miss if you assume "Dex has a few task tools."
2. **A whole local-first OAuth stack (Connection Manager) ships while its product doorway is held** — Nango-catalog-as-data, PKCE, encrypted on-device tokens, a health/refresh state machine, Doctor status, a frozen Desktop contract, live Google/Linear proof, and seven merged security-hardening phases (5a–5g). `/connect` still exists only on draft PR #231; the Phase 5e no-go on the same-user credential boundary has not been lifted.
3. **`career-evidence-capture.cjs` was silently dead (fixed, PR #180).** It read hook input from an env var (`CLAUDE_HOOK_CONTEXT`) when Claude Code delivers it on stdin — so it no-opped on every invocation while looking like a working feature. PR #180 fixed it and added a contract test guarding the whole hook family.
4. **Three MCP servers lack the `feature_status` honesty contract** (`dex-improvements`, `dex-onboarding`, `dex-session-memory`) — so the "every feature reports its own health" promise has real holes.
5. **The observation layer / health-checkers are UNTRACKED local files, not product** — easy to mistake local cruft on the maintainer's disk for shipped Core. Separately, **`/diff-adopt` edits CLAUDE.md + registers hooks outside the lifecycle safe-door** — a real exception to the "one safe door for every change" story worth knowing before you touch it.
6. **Built ≠ shipped, twice over.** Customization-migration activation + rewind is rehearsal-proven and its doorway is authorized, but the doorway is still untagged (§12); `ritual_intelligence` is a whole CI-green subsystem that nothing invokes (§13). Reasoning from "the code exists and tests pass" to "the feature ships" gets both of these wrong.

---

## Open questions / statuses to re-verify on next refresh

- **Connection Manager doorway.** Phases 5f–5g closed named criticals; whether they satisfy the Phase 5e redesign requirements (OS-bound decryptor/consumer identity + default-access contract) is a security-review call, not a docs call. Until a review explicitly lifts the no-go, this map says HELD.
- **Customization-migration rebuild release.** The engine rehearsal and Dave's authorization gate have passed. Keep the doorway LOCAL until it is merged and a release containing it is published; do not infer an independent review from local implementation or test results.
- **`ritual_intelligence` wire-or-retire.** Parked since March; an open product decision, not an engineering blocker.
- **Observation layer's disposition — RESOLVED.** The observation-*.cjs hooks and the beta-rollout doc are untracked local files (verified via `git ls-files`), not in the repo. There is nothing to "remove" from the product; they are local experimentation only. The one tracked observation-adjacent file (`staging/vault-fixes/delight-capture.cjs`) was deleted by PR #180.
