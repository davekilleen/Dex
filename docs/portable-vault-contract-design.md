# Portable Vault Contract — PR-0 design (authored by orchestrator, 2026-07-20)

The shared spine for three tracks: Brain/Vault split (Decision B), the catalog upgrade
engine (Decision A), and capability rooms (Decision C). Spec source: the ratified
`Vault_Contract.md` v1 (2026-06-18, private handbook) reconciled with what has shipped
on main through v1.62.0 (SR1 #147–#150).

## Artifacts (mirrors the existing paths-contract idiom)

| Artifact | Role |
|---|---|
| `core/portable_contract.py` | Source of truth: the classification rules, five classes, capability registry, mutation policy; loader + resolution API |
| `scripts/generate-portable-contract.py` | Generator → committed dist JSON (like `generate-path-contracts.py`) |
| `packages/dex-contracts/dist/portable-vault.contract.json` | Generated, committed cross-repo view |
| `packages/dex-contracts/dist/portable-vault.schema.json` | JSON Schema validating the contract |
| `scripts/check-portable-contract.sh` | CI gate (see Gate) |
| `core/tests/test_portable_contract.py` | Unit + red-when-removed gate tests |

## Five ownership classes (from #141, reconciled with Vault_Contract §3)

- `brain` — release-owned; replaced wholesale on update. `core/`, `packages/`,
  `scripts/`, `extensions/`, shipped `.claude/` skills+hooks, `CLAUDE.md`, `AGENTS.md`,
  system docs, `install.sh`.
- `vault` — user content; updates NEVER write. PARA folders (`00-Inbox/` … `07-Archives/`,
  ALL of `06-Resources/` per ratified decision §10.1 — brain docs eventually move to
  `docs/`), user config values (`System/user-profile.yaml`, `System/pillars.yaml`,
  `System/folder-paths.yaml`), user extensions (`CLAUDE-custom.md`,
  `.claude/skills-custom/`, `core/mcp-custom/`, `core/mcp-premium/`), `.mcp.json`.
- `seed` — shipped once, then user-owned; update writes ONLY if absent.
  Templates (`System/Templates/`), `System/user-profile-template.yaml` (canonical
  template on main; the ratified doc says `user-profile.example.yaml` — the repo
  consolidated to `-template` in the hygiene PR; contract follows the repo, deviation
  noted), `System/pillars.example.yaml`, `env.example`, `System/.mcp.json.example`,
  `System/integrations/config.yaml` + `slack.yaml` (SR1 #150: tracked templates carrying
  env-var references — NOT vault, NOT brain), `03-Tasks/Tasks.md` and other starter files.
- `generated` — machine-derived, regenerated; neither user- nor release-precious:
  `System/.installed-files.manifest`, `System/.release-evidence-profile.json`,
  `packages/dex-contracts/dist/*` (committed but regenerable), people/company indexes.
- `runtime` — local machine state; never shipped, never updated, may be gitignored:
  `System/.dex/`, `System/Session_Learnings/` (today: 3 legacy tracked files under
  SR1 #148's 27-row baseline — contract marks the DIRECTORY runtime with an explicit
  `legacy_tracked` exception list so the baseline reduction follow-up has one place to
  edit), `System/Session_Memory/`, `System/usage_log.md`, logs, caches, `node_modules`.

## Hard-deny list (write-plan may never target, any class)
`.env*`, `.git/`, `System/credentials/`, `*token.json`, `*.key`, `*.pem`, symlinks,
path traversal. (From #141 ownership.cjs deny set + Vault_Contract §3 secrets row.)

## Credential reconciliation (the SR1 collision, settled here)
- `System/integrations/config.yaml` = `seed` (shipped reference-schema template;
  install-if-absent; never overwritten once user-owned).
- `.mcp.json` = `vault` + `report_only: true` (SR1's structural residual detector owns
  it; release updates and migration engines never rewrite it). The one narrow
  exception is the later-ratified lifecycle registration repair: after showing
  the exact preview and receiving explicit approval, it may add Dex's own missing
  Customization Migration entry. The normal public lifecycle service remains
  add-only and cannot replace or remove any user entry. There is one bridge-only
  legacy exception: an exact v1.20-compatible install may remove only the exact
  dormant `qmd` registration (`{"command":"qmd","args":["mcp"]}`) when no real
  `qmd` executable exists, the removal is shown in the exact preview, and the user
  explicitly approves it. The immutable v1.81.0 transaction engine carries that
  write under its older `mcp-registration` path gate, but the logical transaction
  and receipt purpose is `legacy-qmd-reconciliation`; all other MCP configuration
  remains user-owned and unchanged.
- Raw secret authority = vault-root `.env` (hard-deny).

## Capability registry (Decision C, Option 2)
Declarative rooms; the spine (meetings/people/tasks) is NOT a capability — always on.
```
capabilities:
  career:        { folders: [05-Areas/Career/], skills: [career-setup, career-coach, resume-builder], mcp: [career_server, resume_server], default: off }
  companies:     { folders: [05-Areas/Companies/], features: [entity-engine.company-pages], default: off }
  quarter_goals: { folders: [01-Quarter_Goals/], skills: [quarter-plan, quarter-review], config: quarterly_planning, default: off }
```
State lives in `System/user-profile.yaml` → `capabilities:` (vault-owned values), per
the portability audit — reusing the existing `quarterly_planning.enabled` precedent.
Contract rule: an absent room is VALID (repair/convergence must not recreate it).

### Current room-skill wire contract (v2)

Contract v1 remains readable with its historical room shape and no payload pins.
Contract v2 adds one closed `skill_sources` authority per room skill. Each entry
pins the dormant source path, active target path, current SHA-256 and byte size,
plus `previous_payloads` containing the release tag, SHA-256 and byte size of
published older Dex payloads that may be upgraded. The pin set must exactly equal
the room's `skills` list; Lens refers only to the room and skill and does not
duplicate these paths or hashes.

Before a toggle or onboarding run mutates the vault, Core verifies every source,
every lexical target ancestor, and every existing active payload. Current bytes
are left alone, exact prior published bytes may be replaced, and all other bytes are
treated as user-owned and refused. Room reconciliation records every file and
directory mutation and rolls its bounded changes back on failure.

## vault_schema
The contract JSON carries `vault_schema_supported: ">=1 <2"`. The migration must
not stamp or rewrite `System/user-profile.yaml` to record this: that file belongs to
the user. Boot comparison semantics per Vault_Contract §6 (older → offer migrator;
newer → refuse writes) remain an engine concern; the contract only carries the
supported range.

## The CI gate (red-when-removed)
`scripts/check-portable-contract.sh` fails when:
1. any path in `git ls-files` does not resolve to exactly one class;
2. any `RELEASE_BUILD_INPUTS`/release-tree path resolves to `vault` or a deny rule
   (release must never ship user content);
3. the committed dist JSON differs from regeneration (drift gate, like
   check-contract-consistency.sh);
4. the contract JSON fails its schema.

## Resolution semantics
Longest-prefix rule wins; explicit file rules beat directory rules; deny beats all.
`resolve(path) -> {class, rule_id, deny: bool}`. Loader is pure stdlib (no pyyaml
dependency in the hot path — JSON only), mirroring `core/path_contract.py`.

### Installed-vault Git tracking

The release repository's base `.gitignore` excludes the PARA regions because they
contain shipped examples in the public source tree. An installed vault has the
opposite ownership boundary: every path named by `VAULT_REGIONS` is re-included so
the user's notes, tasks, projects, and resources remain eligible for private Git
history. This vault-mode section is appended after the distribution rules because
Git's last matching rule wins.

The temporary exception is release-owned reference material still shipped inside
`06-Resources/Dex_System/`. `brain_paths_inside_vault_regions()` derives those exact
file paths from the ownership contract and the composer excludes each file again
after re-including the region. The exclusion is deliberately per-file, never the
whole directory, so a user note beside a shipped reference file remains user-owned
and trackable. Secrets and other hard-denied paths remain excluded independently.

## Non-goals for PR-0
No behavior change: nothing consumes the contract for writes yet. PR-1 (snapshot/journal
core) and the migrator/updater ports build on it. `ownership.json` CJS bridge is
deferred to PR-2 (generated view, only when the ported migrator needs it).
