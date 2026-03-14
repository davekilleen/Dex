# @dex/contracts

Shared cross-repo contract package.

## Build

From `dex-core` repo root:

```bash
python3 scripts/generate-path-contracts.py
```

## Outputs
- `dist/paths.contract.json`: vault-relative path constants generated from `core/paths.py`
- `dist/paths.schema.json`: JSON schema for validation
- `dist/index.js`: runtime helper exports
- `dist/index.d.ts`: TypeScript declarations
