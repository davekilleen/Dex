# Dex Core — Architecture Map

> **Purpose.** The authoritative, human-readable "how Dex Core hangs together" doc. Load this before working in the `dex-core` repo so you start from what actually exists, not stale assumptions.
>
> **Status vocabulary.** `SHIPPED` = in a released version tag. `LOCAL` = merged on `main`, not yet in a release tag. `PROTOTYPE` = built, not verified against live/real use. `PLANNED` = designed, not built.
>
> **Ground truth as of** HEAD on `main`, latest release tag **v1.68.0** (2026-07-22). One commit sits after the tag: PR #179 (the inventory grounding suite) — that is the only `LOCAL` delta right now.
>
> **Don't duplicate generated files.** Tool lists, skill lists, ownership-class path tables, and MCP↔skill wiring live in the auto-generated `docs/architecture/INVENTORY.md`. This map cross-references it; it does not restate it.
>
> **Stale-header warning.** `CLAUDE.md` still self-labels "v1.11.0". Ignore that; the code is at v1.68.0. The CLAUDE.md header is user-facing seed prose, not a version source.

---

## Subsystem index

| Subsystem | Status | Lives in | One line |
| --- | --- | --- | --- |
| Lifecycle "safe update" engine | **SHIPPED** (v1.65–v1.68) | `core/lifecycle/*` | Frozen public API: preview → backup → apply → verify → receipt → rewind, over a release catalog + ownership contract |
| Transaction core | **SHIPPED** (v1.66) | `core/transaction/*` | Crash-safe snapshot→apply→verify→commit/rollback substrate the lifecycle engine writes through |
| Portable ownership contract | **SHIPPED** (v1.64+) | `core/portable_contract.py` | Source of truth: every path is brain/seed/generated/vault/runtime; decides what an update may write |
| Release catalog + bridge | **SHIPPED** (v1.65–v1.68) | `core/lifecycle/catalog/*`, `bridge.py` | Publisher-declared packing list per release; one-release handoff from the legacy updater |
| 9 MCP servers | **SHIPPED** (mixed ages) | `core/mcp/*_server.py` | The tool surface Dex acts through; Work MCP is the giant (43 tools) |
| Connection Manager (OAuth/token) | **PROTOTYPE** | `core/integrations/connection-manager/` | Local-first OAuth via Nango catalog-as-data; encrypted on-device tokens; not yet run against a live provider |
| DexDiff (methodology sharing) | **SHIPPED** cmd surface / **PARKED** redesign | `.claude/skills/diff-*`, `core/dexdiff_profile_adopt.py` | Generate→publish→adopt-regenerates-locally; redesign parked for the desktop "Vorflux" rebuild |
| Entity engine + gardener | **SHIPPED** (v1.37 / v1.44) + **LOCAL** cooling | `core/entity_engine/*`, `core/entity_maintenance.py` | Auto-creates person/company pages, logs meeting touches, classifies relationship temperature, and resurfaces consequential relationships going cold |
| Hooks | **SHIPPED** (wired subset) / dead weight present | `.claude/hooks/`, `.claude/settings.json` | Small wired core; several unwired scripts + one silently-dead hook still in the tree |
| Skills (68 shipped, ~74 on disk) | **SHIPPED** | `.claude/skills/` | `/command` workflows; consolidation + description-rewrite direction in flight |
| Grounding suite (inventory + drift gate) | **LOCAL** (PR #179) | `docs/architecture/INVENTORY.md`, `scripts/generate-architecture-inventory.py` | Code-derived inventory + CI drift gate; state ledger + session digest are **PLANNED** |

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

**What it is.** Each release carries an exact packing list. `core/lifecycle/catalog/*.json` (publisher-owned declarations, e.g. `official-capabilities.json`) is read by the release builder in filename order and emitted as the canonical `System/.release-catalog.json`. `bridge.py` handles the one-release handoff from the legacy CJS updater to the new engine (resumes safely even if a prior update was interrupted — the v1.68 "smooth bridge").

**How it connects.** Feeds `lifecycle/plan.py` (what's available to adopt) and the DexDiff-adjacent adoption receipts under `System/.dex/adoptions/`. The v1.67 "two dozen role-specific tools you can turn on safely" are catalog items adopted through this path.

## 5. The 9 MCP servers — SHIPPED

**What they are.** The tool surface Dex acts through. **Do not restate the tool lists — read `docs/architecture/INVENTORY.md` § "MCP engines" for exact per-server tool names.** Summary:

| Server | Source | Tools | `feature_status` honesty contract |
| --- | --- | ---: | :---: |
| `dex-work-mcp` | `work_server.py` (247 KB) | **43** | yes |
| `dex-calendar-mcp` | `calendar_server.py` | 15 | yes |
| `dex-resume-mcp` | `resume_server.py` | 12 | yes |
| `dex-improvements-mcp` | `dex_improvements_server.py` | 9 | **no** |
| `dex-career-mcp` | `career_server.py` | 8 | yes |
| `dex-onboarding-mcp` | `onboarding_server.py` | 8 | **no** |
| `dex-session-memory` | `session_memory_server.py` | 8 | **no** |
| `dex-granola-mcp` | `granola_server.py` | 6 | yes |
| `dex-analytics` | `analytics_server.py` | 4 | yes |

**The big one.** `dex-work-mcp` is 43 tools (tasks, people/company indexes, goals, priorities, meeting cache, external task sync, focus/scheduling). It is the spine of `/daily-plan`, `/week-plan`, `/process-meetings`. Per INVENTORY's connectedness section, three servers are **under-surfaced** (0 skills reference them): `dex-career-mcp`, `dex-resume-mcp`, `dex-session-memory` — their tools exist but no skill invokes them by name. `dex-analytics` is **over-surfaced** (25 skills call `track_event`).

**Honesty-contract gap.** Three servers lack `feature_status` (`dex-improvements-mcp`, `dex-onboarding-mcp`, `dex-session-memory`) — meaning they don't return the ok/off/not_installed/broken/unknown status envelope the rest do. That's the honest weak spot in the "every MCP tells you its health" story.

## 6. Connection Manager (OAuth/token layer) — PROTOTYPE

**What it is.** Local-first OAuth + token management. No Docker, no relay, no cloud. Provider config comes from Nango's open-source catalog (`@nangohq/providers`, ~831 providers) consumed **as data only**; the runtime (OAuth2 + PKCE, refresh, health state machine) is Dex-owned plain Node; tokens live AES-256-GCM-encrypted on-device under `{DEX_VAULT}/System/credentials/`.

**Where it lives.** `core/integrations/connection-manager/`: `catalog.cjs` (Nango entry → Dex OAuth descriptor), `oauth-flow.cjs` (PKCE + localhost callback + refresh), `token-store.cjs` (encrypted store + `connections.json`), `health.cjs` (connected/expiring/expired/needs_reauth state machine), `connect.cjs` (CLI), `get-token.cjs` (Python MCP accessor). Also `CONSUMPTION-LAYER.md`.

**Status (from its README).** "Foundation built and smoke-tested… **Not yet run against a live provider**… Do not `dex-push` until the break→detect→reconnect loop is verified on real accounts." So: **PROTOTYPE** — real machinery, unverified end-to-end. Licence note: Nango providers is Elastic License 2.0 (source-available), consumed as npm dep, not vendored.

**How it connects.** Intended to sit under the integration setup skills (`google-workspace-setup`, `slack`, `notion`, etc.) and feed fresh tokens to Python MCP servers via `get-token.cjs`. Currently parallel to the existing per-integration `detect.py` / `task_sync.py` paths.

## 7. DexDiff — SHIPPED command surface / PARKED redesign

**What it is.** Jobs-to-be-done sharing: package how you use Dex (`/diff-generate`, `/diff-profile`), publish to heydex.ai, and let others adopt — where **adopt regenerates locally** for their role/vault rather than copying your files (`/diff-adopt`, `/diff-adopt-profile`, `/diff-list`, `/diff-remove`).

**Where it lives.** Skills `.claude/skills/diff-*`; local adoption logic `core/dexdiff_profile_adopt.py`; boundary spec `docs/dexdiff-runtime-boundary.md`. Runtime split: `dex-core` owns the `/diff-*` surface + the client to `api.heydex.ai` + local application; `heydex-website` owns auth, hosted review sessions, published storage, profile pages.

**Known issues (real, in code).**
- **PII gate is prompt-only.** `diff-generate` has no redaction machinery — just guidance (e.g. "skills with `-dave` suffix are custom"). Nothing structurally stops personal content leaving.
- **`/diff-adopt` edits CLAUDE.md and hooks.** Confirmed in the skill body: it appends a "Meeting Workflow" section to CLAUDE.md and creates hook scripts in `.claude/hooks/` + registers them in `.claude/settings.json`. That's a broad blast radius for an "adopt a workflow" action, and it runs outside the lifecycle safe-door.

**Status.** The command surface is shipped and usable; a **redesign is PARKED** for the desktop "Vorflux" rebuild. Treat DexDiff as functional-but-frozen — don't invest in hardening the current CLI PII/adopt path; that work moves to Vorflux.

## 8. Entity engine + gardener — SHIPPED (v1.37.0 / v1.44.0) + LOCAL cooling

**What it is.** Three layers. (a) **Entity engine** — background meeting sync deterministically creates person/company pages once someone with an email recurs (2+ meetings across 2+ weeks, or 2+ meetings with transcript evidence); `entity_creation` config = `auto`/`suggest`/`off`. (b) **Gardener** (v1.44) — keeps a living "who this person is to you right now" summary block on active pages, refreshed at most weekly, ≤5 pages/sync, only when something new happened, only if an AI key is present. If the user edits inside the marked block, Dex permanently stops maintaining it. (c) **LOCAL relationship cooling** — meeting sync and the post-meeting hook log canonical, idempotent touches; the pure temperature classifier separates warm, cooling, and cold relationships; and the cooling read only surfaces cold people/accounts with engagement on at least two distinct days.

**Where it lives.** `core/entity_engine/contract.py` (canonical parse/render, frontmatter, quarantine and composite writes), `core/entity_engine/index.py` (disposable SQLite projection), `core/entity_engine/temperature.py` (pure classifier), `core/entity_engine/cooling.py` (read + `System/.dex/entity-cooling.json` feed), and `core/entity_maintenance.py` (metadata maintenance CLI). Gardener and cooling-feed refresh both tie into the meeting-sync path. Off switch for the gardener: `entity_gardener: enabled: false`.

**How it connects.** Consumes Work MCP meeting/attendee data; produces the person/company pages and disposable index that `lookup_person`, context-injector hooks, and `/process-meetings` read. Sync refreshes the cooling feed after entity work, and `/daily-plan` turns its consequential `cold` list into one "❄️ Going cold" heads-up line. `07` memory note confirms v1.37 shipped the auto-creation machinery; touch logging, temperature, and cooling remain **LOCAL** until the next release.

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

**How it connects.** Wired hooks feed context injection, safety guards, and the bounded release-awareness notice. The observation/health-checker scripts are **untracked local cruft, not product** — treat them as absent when reasoning about what a user's install does.

## 10. Skills — SHIPPED (68 counted by generator; ~74 dirs on disk)

**What they are.** `/command` workflows in `.claude/skills/`. **Full list + descriptions + trigger analysis: `docs/architecture/INVENTORY.md` § "Skills".** The generator flags **53 of 68 as "discoverability-risk"** — their frontmatter descriptions lack a `when`/`whenever` trigger, so the model is less likely to auto-invoke them. That is the concrete basis for the **description-rewrite / consolidation direction**.

**Governing principle.** "Hard on Core, gentle on user skills": Core-shipped skills get held to the trigger/quality bar and can be consolidated/rewritten; user-authored skills (the `-custom` suffix convention from `create-skill`, and the `.claude/skills-custom/` vault-class dir) are protected from updates and left alone. `create-skill` auto-appends `-custom` so user skills are never overwritten.

**How it connects.** Skills call MCP tools by name (see INVENTORY connectedness). Some skills (`diff-adopt`) write CLAUDE.md/hooks directly — see §7 blast-radius note. Skill payloads that ship as catalog items flow through the lifecycle safe-door (§1/§4).

## 11. Grounding suite — LOCAL (chunk 1) / PLANNED (rest)

**What it is.** The effort this very doc is part of: give agents code-derived truth instead of stale assumptions.
- **Chunk 1 — SHIPPED-locally (LOCAL):** `docs/architecture/INVENTORY.md` (generated) + `scripts/generate-architecture-inventory.py` + the CI drift gate (`scripts/check-architecture-inventory.sh`, wired in `.github/workflows/ci.yml` as "Architecture inventory drift gate"). Landed as **PR #179**, which is the single commit after tag v1.68.0 → merged on main, **not yet in a release**.
- **Chunk 2+ — PLANNED:** a runtime **state ledger** and a **session digest** (per the task brief). No code found for these in the repo; treat as design intent only.

**How it connects.** The inventory generator parses `core/mcp/*_server.py`, `.claude/skills/*/SKILL.md`, and `core/portable_contract.py` by AST/regex, so the drift gate fails CI if code and INVENTORY diverge. This map is the human narrative layer above that machine inventory — read both: INVENTORY for exact lists, this map for what's real, what's shipped, and how it fits.

---

## What surprised even Fable this session (why this doc must exist)

Concrete non-obvious things that a fresh agent would get wrong by reasoning from priors:

1. **The Work MCP is a 43-tool monster (247 KB) and it's under-surfaced.** Only 7 skills reference it; most of its 43 tools are never named by any skill. Easy to assume "Dex has a few task tools" and miss the actual breadth.
2. **A whole local-first OAuth stack (Connection Manager) exists** — Nango-catalog-as-data, PKCE, encrypted on-device tokens, a health/refresh state machine — and it is a **PROTOTYPE never run against a live provider**. You would not guess this layer is there, nor that it's unverified.
3. **`career-evidence-capture.cjs` was silently dead (now fixed, PR #180).** It read hook input from an env var (`CLAUDE_HOOK_CONTEXT`) when Claude Code delivers it on stdin — so it no-opped on every invocation while looking like a working feature. PR #180 fixes it and adds a contract test guarding the whole hook family.
4. **Three MCP servers lack the `feature_status` honesty contract** (`dex-improvements`, `dex-onboarding`, `dex-session-memory`) — so the "every feature reports its own health" promise has real holes.
5. **The observation layer / health-checkers are UNTRACKED local files, not product** — easy to mistake local cruft on the maintainer's disk for shipped Core. Separately, **`/diff-adopt` edits CLAUDE.md + registers hooks outside the lifecycle safe-door** — a real exception to the "one safe door for every change" story worth knowing before you touch it.
6. **CLAUDE.md self-labels v1.11.0 while the code is v1.68.0.** Trusting the header would put an agent ~57 minor versions behind reality.

---

## STATUS I could not fully determine from code (flag for Fable)

- **Grounding suite chunk 2 (state ledger + session digest): PLANNED, unverified.** I found no code for either in-repo; I inferred PLANNED from the task brief plus absence. If a design doc exists elsewhere (e.g. Mission Control / a worktree), confirm scope before an agent assumes it's greenfield.
- **Connection Manager's live status may have moved.** README says "not yet run against a live provider" (dated files early June). It's possible a later integration path (the `core/integrations/notion/` dir was touched 22 Jul) exercises it; I did not trace a live call end-to-end. Confirm whether any shipped integration now depends on it before treating it as pure PROTOTYPE.
- **Observation layer's disposition — RESOLVED.** The observation-*.cjs hooks and the beta-rollout doc are untracked local files (verified via `git ls-files`), not in the repo. There is nothing to "remove" from the product; they are local experimentation only. The one tracked observation-adjacent file (`staging/vault-fixes/delight-capture.cjs`) is deleted by PR #180.
