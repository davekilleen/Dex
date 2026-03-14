# Testing Hardening Merge Runbook

This runbook is for the current stacked QA hardening rollout.

## PR Stack
Merge in this exact order:

1. `#25` Lane A: enforce merge gates, CI quality policy
2. `#26` Lane B: behavior tests, hook harness depth, journey coverage
3. `#27` Lane C: migration safety, security/perf gates, nightly quality

Do not merge `#26` before `#25`, and do not merge `#27` before `#26`.

## Merge Checklist (Per PR)
- Confirm required check `Dex CI / quality` is green.
- Confirm no unresolved review threads.
- Confirm at least one approval from a code owner/reviewer.
- Confirm PR template sections are completed (test plan, risk, rollback, docs impact).
- Merge via squash or merge commit (do not rebase stacked branches out of order).
- After merge, retarget the next PR base branch if GitHub does not auto-adjust.

## Ticket Closeout Map
Close only after corresponding PR is merged to `main`.

### Close after PR `#25` merges
- `DEX-31` QA Hardening: Run core/mcp tests in CI by default
- `DEX-30` QA Hardening: Enforce path-contract usage lint policy
- `DEX-37` Testing Ops: Repo as source of truth + doc drift CI gate
- `DEX-39` Testing Ops: Ralph Wiggum loop as merge policy
- `DEX-40` Testing Ops: Diff-aware test-required gate
- `DEX-41` Testing Ops: Coverage thresholds as blocking quality gate

### Close after PR `#26` merges
- `DEX-27` QA Hardening: MCP behavior tests for all servers
- `DEX-28` QA Hardening: Hook test harness + remove silent exits
- `DEX-32` QA Hardening: Corrupted-data resilience test suite
- `DEX-42` Testing Ops: Golden user journeys as required release checks
- `DEX-43` Testing Ops: Regression-test requirement for production incidents

### Close after PR `#27` merges
- `DEX-33` QA Hardening: Atomic writes + lock safety for file mutation
- `DEX-34` QA Hardening: Migration rollback safety + tests
- `DEX-35` QA Hardening: Security leak gate expansion
- `DEX-36` QA Hardening: Large-vault performance budget gate
- `DEX-44` Testing Ops: Nightly flaky/perf/security quality automation

## Post-Merge Sanity
After all three PRs are merged:

1. Run a clean-branch CI check on `main`.
2. Verify branch protection still requires `Dex CI / quality`.
3. Confirm nightly workflow is scheduled and succeeded at least once.
4. Move project status from hardening implementation to steady-state enforcement.
