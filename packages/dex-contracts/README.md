# @dex/contracts

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
- `dist/release-catalog-v1.schema.json`: B1 release-catalog JSON schema
- `dist/index.js`: runtime helper exports
- `dist/index.d.ts`: TypeScript declarations
- `dist/connections.contract.json`: frozen connection-manager CLI, status, storage, locking, ownership, and versioning ABI
- `dist/connections.schema.json`: JSON Schema definitions for accessor/status/encrypted-envelope outputs
- `dist/connections-engine.manifest.json`: checksummed vendoring manifest for the consumable engine
- `fixtures/connections/`: canonical consumer examples for all frozen outputs and five statuses
