# Working on dex-core (agent instructions)

Instructions for AI agents (and humans) **developing this repository**. Not the
product persona — the root `CLAUDE.md` is seed prose shipped into user vaults
("You are Dex…"); it is a product surface, not contributor guidance. Edit it like
UI copy, not like docs.

## Communicating with the founder

The founder is non-technical. Lead with the outcome and explain what is
happening in plain language; briefly explain an unavoidable technical term the
first time it appears.

- Use an ADHD-friendly structure: keep steps short and numbered, make the one
  required action unmistakable, and prefer copy-paste prompts or commands.
- When the founder must act, begin with a **What I need from you** block stating
  the exact action, where to do it, why the founder is needed, and what will
  happen next.
- When blocked, state the exact blocker, what is and is not affected, the
  lowest-lift recovery action, and how to prevent the issue recurring.
- Never ask the founder to diagnose Git, mounts, permissions, credentials, or
  similar mechanics, and never ask for secrets to be pasted into chat.
- Never claim something is fixed, committed, pushed, merged, published, or live
  without verifying the result the user will actually experience.

## GitHub access in managed Codex runners

The normal Devbox terminal and a managed Codex runner are separate execution
contexts. A successful GitHub check in one does not prove that the other has
working DNS or credentials. Before any GitHub fetch, push, or remote inspection
from a managed runner, run these read-only checks in that same runner:

```bash
getent hosts github.com
gh auth status --hostname github.com
gh api user --hostname github.com --jq '"GITHUB_OK: @" + .login'
git ls-remote origin HEAD
```

If a check fails, classify the failure precisely:

- **Managed-runner DNS**: `getent hosts github.com` cannot resolve the name.
- **Managed-runner HTTPS credentials**: DNS works but `gh api` or HTTPS Git
  authentication fails.
- **SSH key or route**: the repository uses SSH and the SSH remote fails.

Do not collapse these into “Devbox cannot access GitHub.” Do not ask the founder to
re-authenticate or paste a token when his normal Devbox check already passes.
Continue safe local work where possible, and use the already-authenticated
Devbox terminal as the fallback for a remote GitHub operation.

If the remedy requires runner bootstrap, host service, DNS, credential-mount,
or deployment-key changes, do not edit `/etc/resolv.conf` as a temporary fix,
copy secrets, or claim the issue is fixed. Report the exact layer, the exact
configuration change required, and the verification command; ask for approval
only when a host or credential change genuinely needs it.

## Orient before you touch anything

1. Run `/dex-orient` (or `python3 scripts/dex_state.py --digest`) — released
   version, merged-but-unreleased work, where the maps live.
2. `docs/architecture/DEX-CORE-MAP.md` — the narrative "how it hangs together"
   map, with SHIPPED / LOCAL / PROTOTYPE / PLANNED status per subsystem.
3. `docs/architecture/INVENTORY.md` — **generated, CI-drift-gated**: exact MCP
   servers/tools, skill catalog + trigger analysis, ownership-class path tables.
   Never hand-edit it; regenerate with `python3 scripts/generate-architecture-inventory.py`.
4. `CHANGELOG.md` — the single source of release truth, written in house voice.
5. `docs/architecture/HARNESS-CAPABILITY.md` — harness/model contract.
   Claude Code is the **Tier 3 Full** reference (hooks / injectors /
   self-learning). Cursor, Codex, and other Agent Skills harnesses are
   **Tier 2 Skills**: generated `.agents/` adapters, not a hand-mirror.
   Do not describe Dex as Claude-only, and do not promise those other
   harnesses hooks they do not run. Destructive-command and unsafe-path
   refusals are **Tier 1 Core** (`check_safety_gate` on `dex-work-mcp`):
   Cursor/ChatGPT/Codex call the tool before a dangerous action; Claude
   Code still auto-fires the same function via the PreToolUse hook.
   Inventory: `docs/architecture/HOOK-INVENTORY.md`. Non-goals: multi-model
   routing and reviving `/ai-setup`.

## Merged is not shipped, and shipped is not always live

- Release truth is the version tag + CHANGELOG entry, not `main`.
- Some merged work is deliberately **HELD**: customization-migration Lane G
  (activation + rewind) and the `/connect` doorway (draft PR #231, security no-go
  not yet lifted). `core/ritual_intelligence/` is code-complete but wired to
  nothing (PARKED). Never describe held/parked work as available, in code
  comments, docs, or user-facing copy.

## Hard rules

- **One safe door.** Every vault mutation goes through
  `core/lifecycle/service.py` → transaction core → portable ownership contract.
  Never add a code path that writes vault files directly.
- **Generated files are never hand-edited**: `docs/architecture/INVENTORY.md`,
  `core/paths.json`, `packages/dex-contracts/dist/*`, `System/.release-catalog.json`,
  `.agents/skills/` (except `*-custom/`).
  Change the source, re-run the generator (`scripts/generate-*.{py,mjs}`).
- **New top-level paths must be classified** in `core/portable_contract.py`
  (brain/seed/generated/vault/runtime) or CI fails — this is deliberate.
- **No PII, no founder-machine content** — CI gates (`scripts/check-pii.sh`,
  `scripts/check-founder-content.sh`) block it; don't allowlist around them casually.
- **Worktree isolation** — never write in a checkout another session is using;
  work on a branch in its own worktree.
- GitHub Actions are **pinned to commit SHAs**; keep new workflow edits pinned.
- **This repo's issue tracker is public and user-facing only** — bug reports and
  feature requests from real users, nothing else. Internal roadmap planning,
  epics, and architecture-exploration tickets (the "Wayfinder: ..." pattern and
  its sub-issues) go in the private `dex-cards` repo instead. Never open that
  class of issue here, even in draft form — 26 such issues were found publicly
  exposed and moved to `dex-cards` on 2026-08-10 after the founder caught it.

## Tests

- Python: `pytest core/tests/ core/mcp/tests/ core/migrations/tests/ -m "not fuzz"`
  (flat naming convention: `test_<subsystem>_<behavior>.py`).
- Node: `npm run test:hooks`, `npm run test:scripts`, `npm run test:integrations`.
- Contracts: `npm run check:connections-contract`.
- CI runs the full gate list in `.github/workflows/ci.yml` (macOS runner);
  nightly quality + fuzz + perf budgets in `.github/workflows/nightly-quality.yml`.
  Governance: `docs/testing-governance.md`.

## Deeper reading (on demand)

- Update/transaction design: `docs/transaction-core-design.md`,
  `docs/portable-vault-contract-design.md`
- Customization migration: `docs/customization-migration-threat-model.md`,
  `docs/plans/2026-07-24-customization-migration-mcp.md`
- Doctor: `docs/dex-doctor-spec.md` · Merge gates: `docs/merge-gates.md`
- Distribution: `DISTRIBUTION_READY.md`, `docs/Dex_System/Distribution_Checklist.md`
- Past root causes and runbooks: `docs/solutions/`
- System docs canon: `docs/Dex_System/` is canonical; the copies under
  `06-Resources/Dex_System/` are compatibility bridge files — keep them
  byte-identical until the physical move lands (see `docs/Dex_System/README.md`).
