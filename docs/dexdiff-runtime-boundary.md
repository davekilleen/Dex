# DexDiff Runtime Boundary

## Ownership

Hosted contract owner:
- `heydex-website`

Portable runtime owner:
- `dex-core`

Reference-only planning/docs:
- `dex-pi`

## What Belongs In `dex-core`

- the public `/diff-*` command surface
- the client that talks to `heydex.ai`
- local application of adopted methodologies into a Dex vault
- CLI error handling for link/review/publish/adopt flows
- local DexDiff draft paths resolved from the canonical Dex path contract

## What Must Stay In `heydex-website`

- auth and registration
- hosted review session lifecycle
- published diff storage
- public profile pages
- adoption metadata APIs

## Current Hosted Contract

Host split (this has been broken before - keep it straight):

- `https://heydex.ai` - pages only (Caddy static + React). It has **no** `/api/*` routes.
- `https://api.heydex.ai` - every API endpoint below (Convex HTTP actions).

All portable-runtime API calls go to `api.heydex.ai`. Local stubs override via the
`DEXDIFF_API_BASE` environment variable.

The portable runtime should assume these hosted flows exist:

1. browser link starts with `/connect/?cli=true`
2. CLI redeems a short code through `/api/connect/redeem`
3. hosted backend returns a durable `sessionToken`
4. CLI creates review sessions through `/api/review/create`
5. browser completes publish on `/diff/review/?session=...`
6. single-workflow adoption fetches raw methodology from `GET /api/diff`
7. whole-profile adoption fetches the dedicated bundle from `GET /api/profile-bundle`

## Local Draft Contract

The portable runtime must not hard-code machine-specific absolute paths for DexDiff drafts.

Local DexDiff draft paths should resolve from the canonical Dex path contract generated from
`core/paths.py`.

Current contract keys:

- `DEXDIFF_DIR`
- `DEXDIFF_BETA_DIR`
- `DEXDIFF_DIFFS_DIR`
- `DEXDIFF_PROFILE_DRAFTS_DIR`
- `DEXDIFF_DESIGN_DIR`

Current default relative locations:

- single diff drafts: `04-Projects/DexDiff/beta/diffs/`
- profile drafts: `04-Projects/DexDiff/beta/profile/`

For whole-profile adoption, the local runtime should save hosted profile bundles under:

- `DEXDIFF_PROFILE_DRAFTS_DIR/adopted/<handle>/profile-bundle.json`
- `DEXDIFF_PROFILE_DRAFTS_DIR/adopted/<handle>/workflows/*.yaml`
- optional Love Letter: `DEXDIFF_PROFILE_DRAFTS_DIR/adopted/<handle>/love-letter.md`
- adoption log: `System/.dex/adoptions/profiles/<handle>.json`

The CLI should talk about these as the user's DexDiff draft area in their vault, not as a
machine-specific absolute filesystem path unless the user explicitly asks for it.

## Why This Matters

Without this split, Pi-specific bridge code becomes the accidental runtime source of truth and free/paid users drift apart again.
