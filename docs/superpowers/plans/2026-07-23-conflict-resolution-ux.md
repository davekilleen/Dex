# Conflict-resolution UX — design doc

**Status:** DESIGN — awaiting review (orchestrator → Dave) before any implementation.
**Date:** 2026-07-23
**Branch:** `feat/conflict-ux` (worktree off `origin/main`, HEAD post-v1.70.0)
**Surface touched:** `core/lifecycle/service.py` (ABI-frozen, `api_version 1.0.0`), `core/portable_contract.py` (contract), `.claude/skills/dex-update/SKILL.md` (choice layer).

---

## 1. Problem in one line

When a Dex update ships a new version of a skill (or other shipped file) that the user has **edited in place**, the user should get a clean, reversible choice — **keep mine / take theirs / keep both / compare** — instead of the update silently doing nothing.

---

## 2. What already exists (verified in code — do NOT rebuild)

### 2.1 Detection is complete
`core/lifecycle/plan.py` already produces the conflict signal:

- A shipped catalog file the user edited hashes as `stock-modified` (bytes differ from the verified release catalog). The per-item planner (`plan_catalog_item`) turns that into `PlannedAction.CONFLICT` with reason `ReasonCode.RELEASE_FILES_MODIFIED` and the offending paths attached.
- A shipped catalog file the user deleted hashes as `stock-missing` → `CONFLICT` / `RELEASE_FILES_MISSING`.
- `core/lifecycle/customizations.py` (`detect_customizations`, `classify_release_state`) is the byte-vs-catalog comparator underneath. It emits honest `stock-modified` / `stock-missing` / `unknown` states.

**Consequence today:** conflicted items reach the plan as `CONFLICT`, land in the dex-update "Needs your review" group, and **nothing happens to them**. `build_adoption_preview` and `execute_adoption` both hard-refuse any item whose planned action is not `ADOPT` (preview.py L318, engine.py L853). So the *safe default* (never clobber) exists; the *resolve-it-now* path does not.

### 2.2 Revert is complete
`service.rewind_adoption_by_receipt` → `engine.rewind_adoption` restores an adoption's exact pre-state from a captured snapshot, drift-safe, under keep-last-3 snapshot retention. It is receipt-bound: the caller must present the exact `AdoptionReceipt` plus a matching `rewind_acknowledgement_token`.

### 2.3 `-custom` protection exists — but weaker than it looks (IMPORTANT FINDING)
Two separate mechanisms are in play and they disagree:

- **Contract expectation:** `core/portable_contract.py` classifies `.claude/skills-custom/` as ownership `vault` → `MUTATION_POLICY["vault"] = "never"`. The `brain-claude` rule note literally says *"user skills belong in .claude/skills-custom/ (vault)"*.
- **What `/create-skill` v2 actually does** (shipped in #192): it writes user skills to **`.claude/skills/{name}-custom/`** — i.e. a `-custom`-*suffixed folder inside* `.claude/skills/`, which resolves under the `brain-claude` rule → ownership `brain` → `MUTATION_POLICY["brain"] = "replace"`.

So a `/create-skill` user skill is **not** protected by the ownership contract's `never` rule. It is protected only by **absence from the release catalog** — no catalog item names a `-custom` path, so no adopt write ever targets it. That is real protection today, but it is incidental, not contract-guaranteed. **This mismatch is load-bearing for keep-both placement (§5) and is decision D1.**

### 2.4 The choice layer today
`.claude/skills/dex-update/SKILL.md` is the entire UX. It calls the five frozen ops, renders a five-group preview, and asks for one approval. It explicitly forbids working around a conflict ("Never bypass a conflict by replacing the customized file"). There is no keep-both, no compare, no per-file choice.

### 2.5 The frozen surface, precisely
`service.py` exposes exactly five ops, `api_version = "1.0.0"`, each returning `_envelope(api_version=..., ...)`. The contract is `core/lifecycle/contracts/api.schema.json` (closed, `additionalProperties: false`, `api_version` pinned `{"const": "1.0.0"}` in ~30 places). Two guard tests in `core/tests/test_lifecycle_service_contract.py`:

- `test_public_surface_requires_a_version_bump_and_bridge_to_change` — asserts `service.__all__` is **exactly** the current 5-op list.
- `test_api_version_is_present_and_frozen_in_schema` — asserts `service.api_version == "1.0.0"` and the schema pins it.

**Every PlanEntry is contract-checked twice** (`core/transaction/engine.py` L153 at `begin`, L274 at `run`) via `portable_contract.update_write_verdict`. One disallowed write aborts the whole transaction. This is the wall the keep-both writer must pass through — see §5.

---

## 3. What is genuinely new

1. **A keep-both writer** — one new frozen lifecycle operation that, for a conflicted item, atomically (a) lands the incoming release bytes at the canonical path and (b) preserves the user's edited bytes at a sidecar `-custom` path, producing a receipt that the *existing* rewind can undo.
2. **A choice layer** in `dex-update` that, per conflicted file, offers keep-mine / take-theirs / keep-both / compare and routes each to the right operation.

---

## 4. The new frozen operation

### 4.1 Backward-compatibility strategy (the critical constraint)

**Recommendation: keep `api_version = "1.0.0"` and ADD one operation. Do not bump the version.**

Rationale: the frozen-contract rule (service.py docstring) is *"changing a frozen function signature or JSON shape requires an API version bump and a compatibility bridge."* Adding a brand-new operation changes **no existing** signature or shape — all five current ops are byte-for-byte untouched, so every existing caller keeps working. A version bump would be actively harmful here: `api_version` is embedded as a `const "1.0.0"` in every response envelope and asserted ~30× in the schema, so bumping to `1.1.0` would change the value of every existing response and break the very callers the freeze protects. Additive-without-bump is the backward-compatible move.

What the addition costs (all deliberate, all reviewed):
- Add the new op to `service.__all__` and update the `test_public_surface...` guard test's expected list — a **deliberate, reviewed** edit. The test exists precisely to force this to be a conscious act, not to forbid it.
- Add the new op's request/response to `api.schema.json` `x-operations` and `$defs`, and add a contract-conformance case to `test_frozen_service_contract`.
- `api_version` stays `1.0.0`; the two version-pinning assertions stay green untouched.

> Decision D2 for Dave: confirm "additive op, no version bump" vs. a formal `1.1.0`. Recommend additive.

### 4.2 Shape: mirror the existing preview → approve → execute → receipt chain

The keep-both writer must reuse the double-authorization + receipt + rewind machinery so revert is free. Two frozen ops, mirroring `build_and_preview_adoption` / `execute_approved_adoption`:

```
build_and_preview_conflict_resolution(
    vault_root, release_root, resolutions
) -> {api_version, preview, approval_token}

execute_approved_conflict_resolution(
    vault_root, release_root, preview, approved_token
) -> {api_version, receipt, rewind_acknowledgement_token}
```

- `resolutions`: an array of `{item_id, strategy}` where `strategy ∈ {"take-theirs", "keep-both"}`. (keep-mine and compare are pure UX — see §6 — and never reach the service; keep-mine = do nothing, compare = read-only.)
- The **receipt reuses the existing `AdoptionReceipt` shape** so `rewind_adoption_by_receipt` undoes a keep-both with **zero new rewind code**. The keep-both transaction writes 1–2 files per conflicted file (canonical + sidecar); the snapshot captures the pre-state of both (the user's edited canonical file, and the absence of the sidecar), so rewind restores exactly "user's edit back at the canonical path, sidecar removed."

> Decision D3 for Dave: one combined op with a `strategy` field (above), **or** a single `execute_approved_adoption` extended to accept conflict items? Recommend the **separate new op** — it keeps `execute_approved_adoption`'s frozen shape and its "only adopt may be approved" invariant untouched, and isolates the riskier keep-both semantics behind its own contract-tested surface.

### 4.3 Semantics per strategy

- **take-theirs:** write incoming release bytes → canonical path. This is byte-identical to a normal adopt of that item; the only reason it needs a distinct entry point is that the *plan action is CONFLICT, not ADOPT*, so it must re-prove the user genuinely asked to discard their edit. The user's edit is **not** preserved (they chose to drop it) — but it is still recoverable via rewind (snapshot captured the pre-state).
- **keep-both:** one transaction, two writes:
  1. incoming release bytes → canonical path (e.g. `.claude/skills/foo/SKILL.md`),
  2. user's current edited bytes → sidecar preservation path (see §5).

Both strategies re-prove the conflict is still exactly as previewed before committing (same "rebuild preview, compare canonical bytes" guard the adoption path uses), and refuse on any drift.

---

## 5. Where the preserved copy lands — and the contract wall

This is the hardest design point. The keep-both preservation write goes through `Transaction`, which enforces `update_write_verdict` on every entry. So the sidecar path **must be contract-writable**:

| Candidate sidecar path | Ownership | `update_write_verdict` | Verdict |
|---|---|---|---|
| `.claude/skills-custom/foo/SKILL.md` | `vault` | `never` | **REJECTED** — transaction aborts |
| `.claude/skills/foo-custom/SKILL.md` | `brain` | `replace` | **allowed** (matches create-skill v2's real convention) |

The contract-clean choices:

- **Option A (recommended): sidecar under `.claude/skills/{name}-custom/`, authorized as write-if-absent.** This matches where `/create-skill` v2 already puts user skills, so the two systems converge on one `-custom` convention. But it currently resolves to `brain/replace`. Two ways to make it honest:
  - **A1:** add a `portable_contract` rule that `.claude/skills/*-custom/**` is a preservation namespace with `write-if-absent` semantics (create it when absent, never overwrite). This gives the keep-both write a legal, minimal, *user-content-preserving* authorization and simultaneously makes the create-skill protection contract-guaranteed instead of incidental. Repeated updates then refuse to overwrite an existing sidecar (edge case §7).
  - **A2:** leave the contract alone; rely on `brain/replace` allowing the write and on catalog-absence protecting it afterward. Cheapest, but perpetuates the "protected by accident" weakness from §2.3.
- **Option B: preserve the user's edit into the `vault`-owned `.claude/skills-custom/` namespace.** Semantically the "right" home per the contract note, but requires giving that namespace a `write-if-absent` exception (it is `never` today), which weakens the guarantee that updates never touch `vault`. Not recommended.

> Decision D1 for Dave (the big one): **keep-both sidecar placement + naming.** Recommend **Option A1**: place the preserved user copy at `.claude/skills/{name}-custom/`, and add a narrow `write-if-absent` preservation rule to the contract so the write is legal, minimal, and never overwrites an existing user file. This unifies with create-skill and upgrades `-custom` from incidental to contract-guaranteed protection. Second frozen surface touched (`portable_contract`) — but it is the honest place for the change.

Note: this design generalizes beyond skills (any conflicted shipped file), but the `-custom` sidecar naming only reads naturally for skills/docs. For a non-skill conflicted file (e.g. a shipped System doc), the sidecar would be `{stem}-custom{suffix}` beside the original. Confirm we scope the first cut to skills + docs and refuse keep-both elsewhere (falling back to keep-mine/take-theirs), rather than inventing sidecar names for arbitrary paths.

---

## 6. Choice-layer UX (in `dex-update`)

The five-group preview stays. Group 2 ("Needs your review") stops being a dead end. For each conflicted file the user sees, in plain language:

- **what changed:** "You edited `foo`. The update ships a newer `foo`."
- **four choices:**
  - **Keep mine** — nothing is written. (Pure UX; no service call. The update leaves your edit exactly as-is; you stay on your version.)
  - **Take theirs** — the new version replaces yours. Your old version is still recoverable via rewind. (→ `..._conflict_resolution`, strategy `take-theirs`.)
  - **Keep both** — the new version becomes active; your edit is saved beside it as `{name}-custom` and stays invocable. (→ strategy `keep-both`.)
  - **Compare** — show me the difference first, then ask again. (Pure UX; read-only.)

**Compare rendering (Decision D4):** recommend **inline** in the update conversation — a short, plain unified-diff-style summary the skill renders from the two byte sources (user's current file vs. incoming preview bytes), never an external editor or a raw git call. It keeps the "the skill renders, the service owns mutations" boundary intact and works headless. For large files, summarize (N changed regions) rather than dumping.

The approval discipline is unchanged: after the user picks strategies, the skill calls `build_and_preview_conflict_resolution`, shows every exact write it will make, and requires one explicit "apply this exact resolution?" yes bound to that exact preview + token. A refusal (drift, changed evidence, unsafe path) stops and leaves the vault untouched.

---

## 7. Edge cases

1. **Both files already exist** (canonical edited *and* a `{name}-custom` sidecar already present from a prior keep-both or from `/create-skill`): keep-both's sidecar write is `write-if-absent`, so it **refuses** rather than overwriting the user's existing `-custom`. UX falls back to offering keep-mine / take-theirs, or a numbered sidecar (`{name}-custom-2`) only if Dave wants that (Decision D5 — recommend refuse-and-explain over silent numbering, to avoid fragmenting discoverability, consistent with create-skill's "no `-v2` forks" rule).
2. **A `-custom` already exists** (create-skill case): same as (1) — the sidecar namespace is occupied; keep-both refuses the preservation write and the UX explains "you already have a `foo-custom`."
3. **Repeated updates** (user takes an update, edits the shipped file again, next update conflicts again): each resolution is its own receipt-backed transaction. take-theirs re-proves current bytes each time. keep-both refuses if the sidecar is occupied (see 1). No state accumulates in the service beyond receipts + ledger events.
4. **Drift between preview and execute:** reuse the adoption path's guard — rebuild the preview, compare canonical bytes and the sidecar's absence; any mismatch → refuse, no write.
5. **stock-missing conflict** (user deleted a shipped file): keep-both is meaningless (nothing to preserve); offer only take-theirs (restore the shipped file) or keep-mine (stay deleted).
6. **Rewind after keep-both:** the receipt records both writes; rewind restores the user's edit at the canonical path and removes the sidecar. Under keep-last-3 snapshot retention the snapshot may be pruned after 3 further transactions — rewind already fails safe on a missing snapshot (engine.py L762). No new rewind code.
7. **Folder remapping** (`System/folder-paths.yaml`): `update_write_verdict` assumes default PARA layout; a remapped skills dir must be canonicalized before the sidecar path is classified, or the write fails safe (unclassified → never). Confirm dex-update passes canonical paths.

---

## 8. Contract-test plan

1. **Extend `test_lifecycle_service_contract.py`:**
   - update the `test_public_surface...` expected `__all__` to include the two new ops (deliberate, reviewed).
   - add a `build_and_preview_conflict_resolution` → `execute_approved_conflict_resolution` → `rewind_adoption_by_receipt` round trip to `test_frozen_service_contract`, asserting request+response conform to the schema.
   - keep `test_api_version_is_present_and_frozen_in_schema` untouched and green (proves no version bump leaked in).
2. **New op unit/behaviour tests** (mirror `test_adoption_transaction`):
   - take-theirs writes canonical bytes, produces a valid `AdoptionReceipt`, and rewind restores the user's edit.
   - keep-both writes both files atomically; rewind restores canonical edit + removes sidecar.
   - keep-both **refuses** when the sidecar exists (write-if-absent), leaving the vault untouched.
   - drift between preview and execute → refusal, no partial write.
   - a non-CONFLICT item passed to the conflict op → refusal (symmetry with "only adopt may be approved").
3. **`portable_contract` tests** (if Option A1): a new rule test that `.claude/skills/*-custom/**` is `write-if-absent` and that an existing sidecar refuses overwrite; regenerate/gate the path-contract test.
4. **Schema self-consistency:** the closed-schema validator already walks `additionalProperties:false`; the new `$defs` must round-trip the new receipt/preview through it.
5. **Regenerate `docs/architecture/INVENTORY.md`** (drift-gated) and update `DEX-CORE-MAP.md` narrative for the new op.

---

## 9. Decisions Dave should weigh (summary)

- **D1 (biggest): keep-both sidecar placement + naming.** Recommend `.claude/skills/{name}-custom/` + a narrow `write-if-absent` preservation rule in the contract (Option A1) — unifies with create-skill and makes `-custom` protection contract-guaranteed, at the cost of touching a second contract surface.
- **D2: version bump?** Recommend additive op, keep `api_version 1.0.0` (a bump would break every existing response envelope).
- **D3: op shape.** Recommend a **separate** new pair of ops with a `strategy` field, not an extension of `execute_approved_adoption`.
- **D4: compare = inline vs external.** Recommend inline, skill-rendered, read-only.
- **D5: repeated keep-both collision.** Recommend refuse-and-explain over silent `-custom-2` numbering.

---

## 10. Scope guard

First cut: skills (and shipped docs) only, `take-theirs` + `keep-both` + read-only `compare`. keep-mine is the existing no-op default. Everything routes through the frozen service; the skill renders and the service owns every mutation. No implementation until this design is approved (orchestrator → Dave).
