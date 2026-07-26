# Dex Distribution Checklist

**Last Updated:** 2026-07-26 (v1.75.2)

Maintainer reference for how Dex ships and what to check when cutting a release.
For the standing overview of the distribution system, see `DISTRIBUTION_READY.md`
at the repo root. This file replaced the original pre-launch checklist (January
2026); the old content is in git history.

---

## 1. Paths — provisioned, not templated

A fresh install runs `install.sh`, which provisions everything through
`node core/provision.cjs` + `core/provision-contract.json` + the generated
portable-vault ownership contract. The vault path is collected once and rendered
with a receipt.

> The old `sed "s|{{VAULT_PATH}}|…|"` templating over `System/.mcp.json.example`
> no longer exists. If a doc describes it, that doc is stale.

## 2. MCP servers — 10 core, external ones stay external

Dex ships **10 MCP servers** in `core/mcp/`. The authoritative, CI-drift-gated
list (names, tool counts, exact tools) is `docs/architecture/INVENTORY.md`
§ "MCP engines" — don't hand-copy it here.

External MCPs (browser automation, user-installed integrations, hosted vendor
MCPs) are not part of Dex; users add them via their own Claude settings.

Optional companions degrade gracefully:
- **Granola** — meeting sync uses Granola's official public API with
  `GRANOLA_API_KEY` (Business/Enterprise plan); `/granola-setup` connects it.
  Without it, users can paste transcripts manually.
- **Apple Calendar/Reminders** — EventKit shims in `core/mcp/scripts/`; macOS
  only; other platforms degrade gracefully (`docs/support/upgrade-platform-matrix.md`).

## 3. Credentials & user data — enforced by CI, not by checklist

What used to be manual verification is now automated gates on every push:

| Concern | Gate |
| --- | --- |
| No PII in tracked files | `scripts/check-pii.sh` + `scripts/pii_gate.py` |
| No founder-machine content ships | `scripts/check-founder-content.sh` |
| No credentials/keys | `scripts/security-gate.sh` + `security-scan.py` |
| Every path classified (user data never shipped) | `scripts/check-portable-contract.sh` |
| Distribution safety | `scripts/verify-distribution.sh` |

`.env`, `.mcp.json`, `System/user-profile.yaml`, `System/pillars.yaml`, and all
user data folders are gitignored; the ownership contract additionally guarantees
updates never write `vault`-class paths.

**99% of features work with no API keys.** Optional keys (Anthropic/OpenAI/Gemini)
only enable background automation; `/setup` offers this and creates `.env` from
`env.example` on an explicit yes.

## 4. Cutting a release

1. Land the changes on `main` with a `CHANGELOG.md` entry in the house voice —
   CHANGELOG is the single source of release truth.
2. CI on the `main` push runs the full gate list, then builds and publishes the
   release branch, tag, and vault bundle, and deploys the release-health page.
3. Tag `vX.Y.Z` — `release.yml` extracts the matching CHANGELOG section and
   creates the GitHub Release.
4. Prerelease work goes through the `beta` branch mirror (prerelease-only guards).

## 5. Manual spot-checks (when touching install/packaging)

- [ ] Fresh clone on a clean machine → `./install.sh` completes; provision
      receipt renders; remote renamed `origin` → `upstream`.
- [ ] `/setup` onboarding completes without API keys.
- [ ] Works with Granola absent (graceful degradation).
- [ ] `./scripts/verify-distribution.sh` passes locally.
