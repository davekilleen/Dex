# Typed Relationships — Build Plan (map-first, suggested-until-confirmed)

**Branch:** `feat/entity-relationships` (worktree `wt-relationships`, on latest main w/ bridge + cooling + lifecycle).
**Date:** 2026-07-23

## Headline (from the engine map)

Typed relationships are **already scaffolded end-to-end but not wired**. These exist in BOTH the Python (`core/entity_engine/`) and JS (`.scripts/lib/`) twins:

- `edges` table — `index.py:79-87` (`src_id, edge_type, dst_id, dst_ref, source_path`).
- inverse-label map — `index.py:39-42` (`works_at→employs`, `part_of→contains`).
- `neighbors()` reader — `index.py:1018-1063` (out-edges + query-derived inverse in-edges). **Zero callers today.**
- `## Relationships` managed region on every page — `contract.py:502-505` (person), `554-557` (company). Always emitted, always empty.
- update-log relationship renderer — `contract.py:712-748` (`- <date> — relationship · <type> — <target>`); JS twin `.scripts/lib/entity-pages.cjs:198-227`. **No caller passes `relationship_provenance`.**

Verified inert: `grep "INSERT INTO edges"` → **zero writers**. So the build **populates** the skeleton. No new write path — one existing `mutate_page` CAS call carries it.

## Fixed vocabulary (do not expand without sign-off)

`works_at`, `reports_to`, `part_of`, `stakeholder_on`, `deal_with`, `related_to`. Inverse labels: works_at↔employs, part_of↔contains, reports_to↔manages, stakeholder_on↔has_stakeholder, deal_with↔deal_with (symmetric), related_to↔related_to (symmetric).

## Design invariants (non-negotiable)

1. **Map-first / suggested-until-confirmed.** A machine-written edge is a *proposal*. Confirmation = the field-ownership mechanism already in `merge_frontmatter_text` (`contract.py:285-430`): machine writes recorded in `dex_last_written`; user-confirmed fields become `dex_pinned` and are never overwritten. Nothing is asserted as fact until the user confirms.
2. **Dual-twin byte-parity.** Every rendering behavior has a Python twin AND a JS twin producing byte-identical output. Golden tests: `entity-pages.test.cjs:76`, `:295`. Update both fixtures together.
3. **One atomic write.** Persist via a single `mutate_page(...)` per page (`write.py:183-229`) — never a second write path.
4. **No raw PARA path literals.** Derive from `core.paths` (path-contract gate `test_path_contract.py`).
5. **Files are truth; the SQLite index is disposable.** Edges are projected from page content in `_project_source` (`index.py:440`), never authoritative.

## Persistence decision

- **On-page visible surface:** the `## Relationships` managed region (`region_projections={"relationships": <md>}`, owner `replace_machine_region` `contract.py:583-593`).
- **Confirm-state:** a frontmatter `relationships:` list field added to `V2_FIELDS` (`contract.py:29`), owned by `merge_frontmatter_text` (pinned = confirmed).
- **Off-page proposal feed (surface layer):** `System/.dex/entity-relationships.json`, mirroring the cooling feed (`cooling.py:223-237`).
- **Projection:** populate `edges` in `_project_source` right after touches (`index.py:440`) so `neighbors()` lights up.

## Parallel lanes (shared contract first, then fan out)

**Lane 0 — Intent + feed schema (DO FIRST, blocks the rest).** Define the `relationship` intent shape and the `entity-relationships.json` feed shape once, as a written contract both twins code against. Small, single-author.

Then parallel:

- **Lane A — Python edge projection + neighbors() wakeup.** Populate `edges` in `_project_source` (`index.py:440`); give `neighbors()` its first real caller; extend `render_update_log` callers to pass `relationship_provenance`. Tests: `test_entity_index.py` edges coverage, first `neighbors()` tests.
- **Lane B — Python write path.** `relationship` intent → `mutate_page` with the `## Relationships` region projection + frontmatter `relationships:` field + provenance in update-log. Field-ownership = confirm-state. Tests: writers + contract.
- **Lane C — JS twin.** `materializeRelationshipIntent` beside `materializeTouchIntent` (`entity-engine-client.cjs:459-505`); `buildRelationshipOperations` beside `buildTouchOperations` (`entity-creation.cjs:352`) — person↔company by email domain → `works_at`; co-attendance → `related_to`. Byte-parity renderers. Tests: `entity-engine-client.test.cjs`, `entity-creation.test.cjs`, golden fixtures.
- **Lane D — Surface.** Producer writes `entity-relationships.json` at end of sync (mirror `sync-from-granola.cjs:1031`); one-line daily-plan nudge ("relationships to confirm") in `## ⚠️ Heads Up`, degrade silently; wire the confirm-gated flow into the existing `relationship-radar` skill (already confirm-gated, Step 5).

**Join — dual-twin parity gate.** Byte-parity golden tests pass; path-contract + portable-contract green; `neighbors()` covered.

## Lane 0 — Contract (DEFINED; all lanes build against this)

### Relationship intent (bridge op + internal)
```json
{
  "kind": "relationship",
  "relationships": [
    {
      "type": "works_at|reports_to|part_of|stakeholder_on|deal_with|related_to",
      "target_id": "<canonical entity id / page slug of the other entity>",
      "target_ref": "<human display: name or [[Page]] wikilink>",
      "source": { "kind": "meeting|domain-match|co-attendance|manual", "id": "<evidence id, e.g. granola_id>", "date": "<ISO-8601 date>" },
      "confidence": "suggested"
    }
  ]
}
```
`confidence` is always `suggested` on machine write. Only user confirmation promotes it (see below). Unknown `type` values are rejected by both twins (fixed vocab).

### Edges projection (existing `edges` table — index.py:79-87)
For each relationship on a page, project one row: `src_id`=this page's node id, `edge_type`=type, `dst_id`=target_id (nullable if unresolved), `dst_ref`=target_ref, `source_path`=this page path. Projected in `_project_source` right after touches (`index.py:440`). `neighbors()` reads out-edges + inverse in-edges.

### On-page persistence
- **Frontmatter** `relationships:` — list of `{type, target, status, source, date}`. `status` ∈ `suggested|confirmed`. Add `relationships` to `V2_FIELDS` (`contract.py:29`). Machine writes land as `suggested`; a user-confirmed relationship becomes `dex_pinned` (never overwritten) and `status: confirmed`.
- **`## Relationships` region** — render the list grouped by type; mark each row `(suggested)` until confirmed. Both twins byte-identical.
- **Update-log** — one `- <date> — relationship · <type> — <target_ref>` line per new relationship (existing `relationship_provenance` param, `contract.py:712-748` / `entity-pages.cjs:198-227`).

### Off-page proposal feed
`System/.dex/entity-relationships.json` (mirror cooling feed `cooling.py:223-237`):
```json
{ "schema": 1, "generated_at": "<ISO>", "suggestions": [
  { "src_ref": "...", "src_path": "...", "type": "...", "target_ref": "...", "source": {"kind":"...","id":"...","date":"..."}, "first_seen": "<ISO>" } ] }
```
Only `status: suggested` relationships appear; confirming one drops it from the feed. Daily-plan reads it "if present and fresh," one line in `## ⚠️ Heads Up`, degrade silently.

## Test bar to clear

Python (`core/tests/`): edges writer coverage in `test_entity_index.py`, `neighbors()` tests, writer/contract tests. JS (`.scripts/lib/tests/`, `.scripts/meeting-intel/__tests__/`): materialize + creation tests, byte-parity golden (`entity-pages.test.cjs`). Both golden fixtures updated together. CI quality gates: ruff, path-contract, portable-contract, coverage (COVERAGE_MIN_TOUCHED=10 → in-process tests, not subprocess-only).
