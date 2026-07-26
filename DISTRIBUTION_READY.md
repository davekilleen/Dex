# Dex Distribution — How It Works Today

**Last Updated:** 2026-07-26 (v1.75.2)

> This file was originally a one-time pre-launch readiness report (January 2026).
> Dex has since shipped 70+ releases; this is now the standing description of how
> distribution actually works. History lives in git if you need the old report.

## The short version

Dex is distributed from this repository. A user installs by cloning and running
`install.sh`; releases are cut by tagging, and CI does the packaging, safety
gating, and publishing automatically. Nothing user-owned ever ships in a release,
and a battery of CI gates enforces that on every push.

## Install mechanism

`install.sh` provisions a new vault through the **sanctioned provision contract**:
it calls `node core/provision.cjs`, which applies `core/provision-contract.json`
plus the generated portable-vault ownership contract to lay down exactly the files
a fresh install should have, with the user's vault path collected once and rendered
into a receipt.

> Historical note: early versions templated `.mcp.json` with a
> `sed "s|{{VAULT_PATH}}|...|"` substitution over `System/.mcp.json.example`.
> That mechanism is gone — if you see it described anywhere, the doc is stale.

The install also renames a cloned `origin` remote to `upstream` so a user's vault
is treated as an independent local project, and detects optional companions
(e.g. Granola) to point users at the right setup skill.

## What ships / what never ships

The portable ownership contract (`core/portable_contract.py`, §3 of
`docs/architecture/DEX-CORE-MAP.md`) classifies every path: `brain` (release-owned),
`seed` (shipped once, then user-owned), `generated`, `vault` (user content — never
written by an update), `runtime` (never shipped). CI fails if any tracked path is
unclassified.

## Release pipeline

1. Merges land on `main`; every push runs the full CI gate list (see
   `docs/architecture/DEX-CORE-MAP.md` and `.github/workflows/ci.yml`), including
   the distribution-safety, PII, founder-content, and portable-contract gates.
2. On a `main` push, CI builds and publishes the release branch, tag, and vault
   bundle, then deploys the public release-health page (GitHub Pages).
3. On a `v*` tag, `release.yml` extracts the matching `CHANGELOG.md` section and
   creates the GitHub Release. `CHANGELOG.md` is the single source of release truth.
4. A `beta` branch mirror runs the same pipeline with prerelease-only guards.

## Safety gates that protect distribution

- `scripts/verify-distribution.sh` — pre-flight distribution check.
- `scripts/check-pii.sh` + `scripts/pii_gate.py` — no personal data in tracked files.
- `scripts/check-founder-content.sh` — no founder-machine-specific content ships.
- `scripts/check-portable-contract.sh` — every path classified.
- `scripts/security-gate.sh` / `security-scan.py` — credential/key scanning.

## Platform support

macOS-first (calendar/reminders integration uses EventKit). Non-macOS installs
degrade gracefully; see `docs/support/upgrade-platform-matrix.md`.

## Licensing

See `LICENSE` and `COMMERCIAL_LICENSE.md`. Note: the connection manager consumes
Nango's provider catalog (Elastic License 2.0) as a pinned npm dependency — never
re-expose it as a managed service.

---

Maintainer checklist for cutting a release:
`docs/Dex_System/Distribution_Checklist.md`.
