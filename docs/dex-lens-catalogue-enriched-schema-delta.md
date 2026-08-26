# Dex Lens catalogue v2 enriched schema delta

**Purpose:** This is the exact cross-repository contract Dex Lens must implement before Dex Core may sign or publish a four-class catalogue.

**Minimum compatible Lens release:** `0.1.9` (proposed)

**Current release gate:** A live GitHub release and tag check on 25 August 2026 confirmed `v0.1.8` as the latest `davekilleen/dex-lens` release. Its exported catalogue schema still requires the skill-shaped fields on every entry and does not define the four class-specific models below. The generated enriched example produces 190 validation errors against that tagged schema. Dex Core's enriched output therefore remains an unsigned preview until a `v0.1.9` (or newer) release exports this complete contract. A release number alone does not lift the gate; the released schema and verifier must pass both legacy and enriched catalogues.

The executable proposal is [the enriched preview schema](../core/tests/fixtures/dex-lens-catalogue-enriched-preview.schema.json). The generated four-class example is [the enriched preview catalogue](examples/dex-lens-catalog-enriched-preview.json).

## 1. New closed enums

Add these aliases in `src/capability_exchange/catalogue/v2.py`:

```python
CapabilityClassV2 = Literal[
    "active-skill",
    "mcp-server",
    "scheduled-automation",
    "system-engine",
]
ImpactTierV2 = Literal["core", "high", "medium", "niche"]
CapabilityAvailabilityV2 = Literal["active", "dormant", "parked"]
```

Every enriched entry requires:

| Field | Type | Rule |
| --- | --- | --- |
| `capability_id` | existing `_CatalogueId` | Unique across all classes. |
| `capability_class` | `CapabilityClassV2` | Discriminator for the class-specific model. |
| `impact_tier` | `ImpactTierV2` | Publisher-reviewed impact, never inferred from file or tool count. |
| `availability` | `CapabilityAvailabilityV2` | Restricted further by class below. |
| `title` | existing constrained string | Required. |
| `summary` | existing constrained string | Required. |
| `value` | existing constrained string | Required. |
| `jobs` | existing unique `_CatalogueId` tuple | Required and closed against `jobs_taxonomy`. |
| `prerequisites` | existing constrained tuple | Required. |
| `trade_offs` | existing constrained tuple | Required. |
| `evidence` | existing `CapabilityEvidenceV2` tuple | Required. |
| `release_provenance` | `Literal["core-release"]` | Required. |

Do not add `generated_at`. `CatalogueMetadataV2.produced_at` remains the one required, timezone-aware generation timestamp.

## 2. Class-specific models and conditional requirements

All models continue to inherit `InventoriedModel`, so unknown fields remain rejected.

### `ActiveSkillCapabilityEntryV2`

Required discriminator fields:

```python
capability_class: Literal["active-skill"]
impact_tier: ImpactTierV2
availability: Literal["active", "dormant"]
```

Keep every current `CatalogueCapabilityEntryV2` field and validator unchanged:

```text
compatibility
docs_url
since_release
changed_in
portable_brief
```

Those five fields are skill-only. Do not require or permit them on the other three classes.

### `McpServerCapabilityEntryV2`

Required discriminator and availability:

```python
capability_class: Literal["mcp-server"]
impact_tier: ImpactTierV2
availability: Literal["active"]
```

Required class fields:

| Field | Type and limits |
| --- | --- |
| `server_name` | `str`, pattern `^dex-[a-z0-9-]+$` |
| `tool_count` | `int`, minimum `1` |
| `example_tools` | unique tuple of 1–5 strings, each matching `^[a-z][a-z0-9_]*$` |
| `source_paths` | unique tuple of 1–300 safe repository-relative paths |

### `ScheduledAutomationCapabilityEntryV2`

Required discriminator and availability:

```python
capability_class: Literal["scheduled-automation"]
impact_tier: ImpactTierV2
availability: Literal["active"]
```

Required class fields:

| Field | Type and limits |
| --- | --- |
| `automation_label` | `str`, pattern `^com\.dex\.[a-z0-9.-]+$` |
| `cadence` | non-empty `str`, maximum 200 characters |
| `source_paths` | unique tuple of 1–300 safe repository-relative paths |
| `installer_path` | one safe repository-relative path |
| `program_target` | non-empty `str`, maximum 512 characters; templates may retain their path token |
| `run_at_load` | `bool` |

The catalogue ID stays kebab-case (`dex-meeting-intel`); the literal launchd label is preserved separately as `automation_label` (`com.dex.meeting-intel`).

### `SystemEngineCapabilityEntryV2`

Required discriminator and availability:

```python
capability_class: Literal["system-engine"]
impact_tier: ImpactTierV2
availability: Literal["active", "parked"]
```

Required class fields:

| Field | Type and limits |
| --- | --- |
| `source_paths` | unique tuple of 1–300 safe repository-relative paths |
| `component_count` | `int`, minimum `1`; must equal the number of `source_paths` |
| `example_components` | unique tuple of 1–5 safe repository-relative paths, each also present in `source_paths` |

`parked` is necessary for `ritual-intelligence-engine`. Lens must not rank a parked entry as an available recommendation.

## 3. Pydantic union

After the transition rule below, the enriched entry alias is:

```python
EnrichedCatalogueCapabilityEntryV2 = Annotated[
    ActiveSkillCapabilityEntryV2
    | McpServerCapabilityEntryV2
    | ScheduledAutomationCapabilityEntryV2
    | SystemEngineCapabilityEntryV2,
    Field(discriminator="capability_class"),
]
```

Change `CatalogueV2.capabilities` to a tuple of the rollout-compatible union. Keep its existing `uniqueItems`, `x-dex-lens-unique-by: capability_id`, maximum 300 entries, duplicate-ID validator, and closed job-reference validator.

## 4. Mandatory 0.1.9 transition compatibility

Lens must release before Core publishes the enriched catalogue. Therefore the next compatible Lens release must accept both:

1. the current signed, skill-only catalogue, whose entries do not carry the three new fields; and
2. the enriched discriminated entries.

Define `LegacySkillCapabilityEntryV2` as the byte-for-byte current `CatalogueCapabilityEntryV2` model. During the transition, use:

```python
CatalogueCapabilityEntryV2 = (
    LegacySkillCapabilityEntryV2
    | EnrichedCatalogueCapabilityEntryV2
)
```

Do not make the new fields optional on MCP, automation, or engine entries. The legacy branch is closed and skill-shaped, so it cannot accidentally admit a classless non-skill entry. The exported JSON Schema must express this as `oneOf` with five closed branches. After every supported Core catalogue carries the enriched fields, a later Lens release may remove the legacy branch as a separate, explicit compatibility decision.

## 5. Exported schema changes

In `scripts/export_catalogue_schema.py`, continue generating both:

```text
schemas/dex-lens-catalogue-v2.schema.json
schemas/dex-lens-catalogue-v2-dialect.schema.json
```

Do not hand-edit the generated schema. Regenerate it from `SignedCatalogueEnvelopeV2.model_json_schema(...)` through `build_catalogue_schema()`.

The exported producer schema must:

- retain the required Lens dialect and `x-dex-lens-unique-by` vocabulary;
- add root annotation `x-dex-lens-minimum-version: "0.1.9"` so Core's preview guard can verify the compatible Lens floor;
- define the five closed entry branches described above;
- preserve `signature` as required and non-empty for a published envelope;
- preserve all metadata, job taxonomy, expiry, unique-ID, and cross-reference rules.

The committed Core preview uses `UNSIGNED-PREVIEW-NOT-FOR-PUBLICATION` as an obvious schema-only sentinel. It is not a valid Ed25519 signature and must never pass Lens cryptographic verification.

## 6. Lens verification and ranking changes

Update every consumer that assumes `CatalogueCapabilityEntryV2` is skill-shaped:

- signature verification remains over the untouched raw `metadata` plus `catalogue` canonical JSON;
- parse the rollout-compatible union only after signature verification;
- cache the verified envelope without erasing the discriminator or class fields;
- never offer `availability == "dormant"` or `"parked"` as an active match;
- allow matching/ranking code to use `impact_tier`, but do not replace evidence and compatibility checks with tier alone;
- apply `portable_brief`, host compatibility, and skill installation logic only to `active-skill` entries;
- render MCP tool counts, automation cadence, and engine component facts through their respective models.

## 7. Required Lens tests

Add positive tests for:

1. the currently published legacy skill-only envelope;
2. one enriched active skill;
3. one dormant skill that validates but cannot be recommended as active;
4. one MCP server with tool count and example tools;
5. one scheduled automation with cadence and launchd label;
6. one active system engine;
7. one parked system engine that cannot be recommended;
8. a mixed four-class signed envelope through model validation, schema validation, signature verification, cache round-trip, and ranking ingestion.

Add negative tests for:

- missing or unknown `capability_class` on every non-legacy shape;
- unknown `impact_tier` or `availability`;
- skill-only fields on a non-skill entry;
- missing class-specific required fields;
- dotted `capability_id` values (the launchd label belongs in `automation_label`);
- duplicate capability IDs across different classes;
- unknown job references;
- parked or dormant entries entering the active recommendation set;
- the released 0.1.8 model rejecting the enriched example, documenting the compatibility boundary;
- invalid signature, unknown key, expiry, rollback, and cache-tamper cases remaining fail-closed.

Run at minimum:

```text
python -m pytest tests -q
python scripts/export_catalogue_schema.py
git diff --exit-code -- schemas/dex-lens-catalogue-v2.schema.json schemas/dex-lens-catalogue-v2-dialect.schema.json
```

Use the Lens repository's own virtual environment and command names if they differ.

## 8. Landing and publication order

1. Merge the Dex Lens model, verifier, ranking, tests, and generated schema together.
2. Release Dex Lens `v0.1.9` or newer with this complete contract.
3. Verify the GitHub release/tag, installable artifact, and exported schema all contain the enriched contract and still accept the live legacy catalogue.
4. Vendor that exact released schema into Dex Core and replace the proposal fixture in Core's validation command.
5. Re-run Core's default Phase 1 generator against the legacy-compatible released schema.
6. Re-run Core's enriched generator against the same released schema, then run Lens's real verifier with a test signing key.
7. Only after both paths are green may Core remove the unsigned-preview guard, sign catalogue version 5, update `latest`, and serve it.

Until step 7, `--enriched-preview` must continue to refuse `--sign` and write only `dex-lens-catalog-enriched-preview.json`.
