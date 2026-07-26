# Working on dex-core (agent instructions)

Instructions for AI agents (and humans) **developing this repository**. Not the
product persona — the root `CLAUDE.md` is seed prose shipped into user vaults
("You are Dex…"); it is a product surface, not contributor guidance. Edit it like
UI copy, not like docs.

## Orient before you touch anything

1. Run `/dex-orient` (or `python3 scripts/dex_state.py --digest`) — released
   version, merged-but-unreleased work, where the maps live.
2. `docs/architecture/DEX-CORE-MAP.md` — the narrative "how it hangs together"
   map, with SHIPPED / LOCAL / PROTOTYPE / PLANNED status per subsystem.
3. `docs/architecture/INVENTORY.md` — **generated, CI-drift-gated**: exact MCP
   servers/tools, skill catalog + trigger analysis, ownership-class path tables.
   Never hand-edit it; regenerate with `python3 scripts/generate-architecture-inventory.py`.
4. `CHANGELOG.md` — the single source of release truth, written in house voice.

## Merged is not shipped, and shipped is not always live

- Release truth is the version tag + CHANGELOG entry, not `main`.
- Some merged work is deliberately **HELD**: customization-migration Lane G
  (activation + rewind) and the `/connect` doorway (draft PR #231, security no-go
  not yet lifted). `core/ritual_intelligence/` is code-complete but wired to
  nothing (PARKED). Never describe held/parked work as available, in code
  comments, docs, or user-facing copy.

## Hard rules

- **One safe door.** Every vault mutation goes through
  `core/lifecycle/service.py` → transaction core → portable ownership contract.
  Never add a code path that writes vault files directly.
- **Generated files are never hand-edited**: `docs/architecture/INVENTORY.md`,
  `core/paths.json`, `packages/dex-contracts/dist/*`, `System/.release-catalog.json`.
  Change the source, re-run the generator (`scripts/generate-*.{py,mjs}`).
- **New top-level paths must be classified** in `core/portable_contract.py`
  (brain/seed/generated/vault/runtime) or CI fails — this is deliberate.
- **No PII, no founder-machine content** — CI gates (`scripts/check-pii.sh`,
  `scripts/check-founder-content.sh`) block it; don't allowlist around them casually.
- **Worktree isolation** — never write in a checkout another session is using;
  work on a branch in its own worktree.
- GitHub Actions are **pinned to commit SHAs**; keep new workflow edits pinned.

## Tests

- Python: `pytest core/tests/ core/mcp/tests/ core/migrations/tests/ -m "not fuzz"`
  (flat naming convention: `test_<subsystem>_<behavior>.py`).
- Node: `npm run test:hooks`, `npm run test:scripts`, `npm run test:integrations`.
- Contracts: `npm run check:connections-contract`.
- CI runs the full gate list in `.github/workflows/ci.yml` (macOS runner);
  nightly quality + fuzz + perf budgets in `.github/workflows/nightly-quality.yml`.
  Governance: `docs/testing-governance.md`.

## Deeper reading (on demand)

- Update/transaction design: `docs/transaction-core-design.md`,
  `docs/portable-vault-contract-design.md`
- Customization migration: `docs/customization-migration-threat-model.md`,
  `docs/plans/2026-07-24-customization-migration-mcp.md`
- Doctor: `docs/dex-doctor-spec.md` · Merge gates: `docs/merge-gates.md`
- Distribution: `DISTRIBUTION_READY.md`, `docs/Dex_System/Distribution_Checklist.md`
- Past root causes and runbooks: `docs/solutions/`
- System docs canon: `docs/Dex_System/` is canonical; the copies under
  `06-Resources/Dex_System/` are compatibility bridge files — keep them
  byte-identical until the physical move lands (see `docs/Dex_System/README.md`).
