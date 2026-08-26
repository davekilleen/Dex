# Dex Lens Catalogue Phase 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build and validate a guarded four-class catalogue preview covering skills, MCP servers, scheduled automations, and system engines without allowing that preview into the current signing or release path.

**Architecture:** One normalized candidate model feeds per-class resolvers. Repository structure owns discoverable facts while registry annotations own impact and user-facing judgment. A proposed local schema validates the preview; the current Lens schema remains authoritative for publishable Phase 1 output.

**Tech Stack:** Python 3.12, `ast`, `plistlib`, pytest, JSON Schema Draft 2020-12, Pydantic-compatible discriminated-union specification.

---

### Task 1: Add normalized capability discovery and MCP coverage

**Files:**
- Modify: `core/lens_catalog_discovery.py`
- Create: `core/tests/test_lens_catalog_enriched_discovery.py`
- Modify if necessary: `scripts/generate-architecture-inventory.py`
- Modify if necessary: `core/tests/test_architecture_inventory.py`

1. Write failing tests for the closed capability-class, impact-tier, and availability enums and for exact MCP discovery: 10 `core/mcp/*_server.py` servers, 131 tools, literal server names, list-tools handlers, stable example tools, and deterministic order.
2. Run the enriched discovery tests and confirm they fail.
3. Implement immutable normalized candidates and a reusable AST MCP parser. Share the architecture-inventory parser rather than allowing two definitions to drift.
4. Re-run enriched discovery and architecture-inventory tests. If generated inventory changes, regenerate it with `python3 scripts/generate-architecture-inventory.py` and verify no semantic count regression.
5. Commit: `feat: discover Lens MCP capabilities`.

### Task 2: Discover scheduled automations and reviewed system engines

**Files:**
- Modify: `core/lens_catalog_discovery.py`
- Modify: `core/lens-catalog/registry.json`
- Modify: `core/tests/test_lens_catalog_enriched_discovery.py`

1. Add failing tests for four plist-backed automations and the daily backup scheduler, including normalized cadence and installer/source resolution.
2. Add failing tests for the four reviewed engine groups, real nonempty source matches, stable component examples, exclusion of hook tests, and parked ritual intelligence.
3. Implement fail-closed `plistlib` discovery plus the explicit backup resolver.
4. Implement closed engine-group pattern resolution and source/component summaries.
5. Add the 19 non-skill registry annotations with reviewed jobs, impact tiers, user value, evidence, and availability.
6. Re-run the focused tests and commit: `feat: discover Lens automations and engines`.

### Task 3: Add per-class resolution and a guarded preview command

**Files:**
- Modify: `scripts/generate-dex-lens-catalog.py`
- Modify: `core/tests/test_dex_lens_catalog_generation.py`
- Create: `core/tests/fixtures/dex-lens-catalogue-enriched-preview.schema.json`

1. Add failing tests proving each class emits only meaningful fields, all entries carry `capability_class` and `impact_tier`, inactive entries carry honest availability, and every source resolves through its class resolver.
2. Add failing safety tests proving enriched generation requires both `--enriched-preview` and `--lens-schema`, refuses `--sign`, refuses release artifact filenames, and cannot alter the default current-schema output.
3. Implement per-class resolvers and a preview-only catalogue builder.
4. Add the proposed closed schema fixture with a `capability_class` discriminator and class-specific `oneOf` requirements.
5. Validate a preview containing at least one entry of every class against the fixture, and demonstrate the same preview is rejected by the current vendored Lens schema.
6. Re-run focused tests and commit: `feat: generate guarded enriched Lens preview`.

### Task 4: Produce the example and exact Dex Lens schema delta

**Files:**
- Create: `docs/examples/dex-lens-catalog-enriched-preview.json`
- Create: `docs/dex-lens-catalogue-enriched-schema-delta.md`
- Modify: `core/tests/test_dex_lens_catalog_generation.py`

1. Add a failing test that regenerates the committed example and compares semantic JSON, then validates it against the proposed fixture.
2. Generate the example through the guarded command, never by hand.
3. Write the Lens-repository delta precisely: `capability_class` and `impact_tier` enums; availability semantics; shared required fields; skill-only requirements unchanged; MCP `server_name`, `tool_count`, and `example_tools`; automation `cadence`, sources, and program target; engine component/source fields; Pydantic discriminated-union model; exported-schema regeneration; positive and negative verifier tests; and coordinated landing order.
4. Include `metadata.produced_at` as the generation date and explicitly avoid a redundant `generated_at` alias.
5. Re-run the example drift test and commit: `docs: specify enriched Lens catalogue contract`.

### Task 5: Verify both contracts and prepare review

**Files:**
- Review all files changed by Phases 1 and 2.

1. Run the default signed Phase 1 generator and current `_validate_against_lens_schema`; confirm green with 66 skills and eight jobs.
2. Run the enriched preview generator and proposed `_validate_against_lens_schema`; confirm green with all four classes.
3. Run all Lens catalogue/discovery tests, architecture-inventory tests, Ruff, JSON parsing, documentation bridge comparison, and generated-artifact drift checks.
4. Read the complete diff for product truth: dormant is not active, parked is not live, 10/131 MCP boundary is exact, no preview path can sign or publish, and no current schema file changed.
5. Reconcile the Mission Control card and Dispatch milestone, push the branch, open a draft PR, and wait for explicit approval before merge, signing with the production key, serving, or release publication.
