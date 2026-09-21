# @dex/contracts

This contributor package exports the generated contracts listed below. The app capability registry and portable MCP bridge live separately under `core/harnesses/` and `packages/dex-agent-plugin/`; this package does not export a complete host workflow API. Generated output proves its declared format, not native app support.

Shared cross-repo contract package.

## Build

From `dex-core` repo root:

```bash
python3 scripts/generate-path-contracts.py
node scripts/generate-connections-contract.mjs
node scripts/build-connections-engine-manifest.mjs
```

## Outputs
- `dist/paths.contract.json`: vault-relative path constants generated from `core/paths.py`
- `dist/paths.schema.json`: JSON schema for validation
- `dist/release-catalog-v1.schema.json`: frozen public B1 release-catalog v1 JSON schema
- `dist/release-catalog-v2.schema.json`: release-catalog v2 schema with an honest immutable-tag pattern
- `dist/index.js`: runtime helper exports
- `dist/index.d.ts`: TypeScript declarations
- `dist/connections.contract.json`: frozen connection-manager CLI, status, storage, locking, ownership, and versioning ABI
- `dist/connections.schema.json`: JSON Schema definitions for accessor/status/encrypted-envelope outputs
- `dist/connections-engine.manifest.json`: checksummed vendoring manifest for the consumable engine
- `fixtures/connections/`: canonical consumer examples for all frozen outputs and five statuses
