# Dex Lens Catalogue Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the current Dex Lens v2 catalogue publish all 66 active first-party skills, exclude dormant and vendored skills, use the documented eight Jobs to Be Done, and continue to validate against the current Lens schema.

**Architecture:** Discovery owns which active skills exist; `registry.json` owns reviewed annotations. The generator compares those sets exactly, emits only active entries through the unchanged v2 wire format, and treats `metadata.produced_at` as the generation date.

**Tech Stack:** Python 3.12, pytest, JSON Schema, Ed25519 catalogue signing, Markdown system documentation.

---

### Task 1: Add active-skill discovery

**Files:**
- Create: `core/lens_catalog_discovery.py`
- Create: `core/tests/test_lens_catalog_discovery.py`

1. Write failing tests proving the scanner finds the repository's 66 direct, first-party skills; excludes all `anthropic-*` directories and `_available`; sorts by ID; parses frontmatter name and description; and rejects symlinked or malformed payloads.
2. Run `python3 -m pytest core/tests/test_lens_catalog_discovery.py -q` and confirm the import or behavior fails for the expected reason.
3. Implement an immutable `SkillCandidate` plus `discover_active_skills(release_root)` using direct-child traversal and fail-closed path/frontmatter checks.
4. Re-run the focused test and confirm it passes.
5. Commit: `feat: discover active Lens skills from release tree`.

### Task 2: Move the publisher registry to the eight-job model

**Files:**
- Modify: `core/lens-catalog/registry.json`
- Modify: `06-Resources/Dex_System/Dex_Jobs_to_Be_Done.md`
- Modify: `docs/Dex_System/Dex_Jobs_to_Be_Done.md`
- Modify: `core/tests/test_dex_lens_catalog_generation.py`

1. Add failing real-registry assertions for exactly eight canonical job IDs, `catalog_version: 4`, 95 reviewed annotations, 66 active annotations, 29 dormant annotations, and a complete 66-ID match with discovery.
2. Run the focused real-registry tests and confirm the old 11-job/55-entry registry fails.
3. Replace the registry jobs with the eight approved IDs. Add closed `availability`, `capability_class`, and `impact_tier` annotations to every entry; mark legacy lifecycle/room entries dormant; add complete reviewed annotations for the 40 missing active skills; and remap every job reference.
4. Correct “The Six Jobs” to “The Eight Jobs” in the canonical and bridge documents, keeping the files byte-identical.
5. Re-run focused registry tests and `cmp 06-Resources/Dex_System/Dex_Jobs_to_Be_Done.md docs/Dex_System/Dex_Jobs_to_Be_Done.md`.
6. Commit: `data: complete active Lens skill annotations`.

### Task 3: Make generation scan-then-annotate

**Files:**
- Modify: `scripts/generate-dex-lens-catalog.py`
- Modify: `core/tests/test_dex_lens_catalog_generation.py`

1. Add failing tests for missing annotations, stale active annotations, dormant exclusion, vendor exclusion, unknown availability/class/tier rejection, unknown job rejection, and deterministic active-skill order.
2. Run the focused tests and confirm each new contract fails against registry-only generation.
3. Parse the new closed registry fields, discover active skills, enforce the exact active discovery/annotation set, resolve only active entries for the current wire format, and derive published order from discovery. Keep skill-shaped output unchanged and preserve `metadata.produced_at` as the one honest generation timestamp.
4. Update synthetic fixtures for the closed internal fields without weakening existing source-pin and schema checks.
5. Run `python3 -m pytest core/tests/test_dex_lens_catalog_generation.py -q` and confirm it passes.
6. Commit: `fix: publish the complete active Lens skill set`.

### Task 4: Prove Phase 1 is publishable

**Files:**
- Regenerate only temporary catalogue artifacts; do not commit signed output.

1. Run the real-registry signed-generation test.
2. Run the generator into a temporary directory with a temporary test signing key and confirm `_validate_against_lens_schema` accepts the exact generated envelope.
3. Inspect the envelope: 66 capabilities, eight jobs, no dormant/vendor IDs, `catalog_version: 4`, and populated `metadata.produced_at`.
4. Run `python3 -m pytest core/tests/test_lens_catalog_discovery.py core/tests/test_dex_lens_catalog_generation.py -q` and `python3 -m ruff check core/lens_catalog_discovery.py scripts/generate-dex-lens-catalog.py core/tests/test_lens_catalog_discovery.py core/tests/test_dex_lens_catalog_generation.py`.
5. Read the complete Phase 1 diff and commit any verification-only corrections.
