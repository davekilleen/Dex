# Dex Core State

A compact snapshot of released, local, and planned Dex Core work.

<!-- GENERATED:START -->
## Generated snapshot

SHIPPED/LOCAL are computed live — run `/dex-orient` or `python3 scripts/dex_state.py` for current truth.

Released: v1.80.5 (2026-07-29)

### LOCAL — on main, not yet released (42)

- #336 fix: unblock real-user updates and workflow dead ends
- Merge pull request #335 from davekilleen/codex/fleet-acceptance-aggregation
- fix: keep fleet evidence aggregation non-authoritative
- feat: add authenticated historic fleet aggregation
- Merge pull request #334 from davekilleen/codex/release-owned-journey-executor
- fix(update): close fleet proof gaps
- feat(update): add release-owned journey executor
- Merge pull request #333 from davekilleen/codex/release-owned-journey-protocol
- fix(update): keep journey proof fail closed
- feat(update): add release-owned journey protocol
- Merge pull request #331 from davekilleen/codex/fleet-journey-runner
- fix(fleet): kill timed-out process descendants
- Merge remote-tracking branch 'upstream/main' into codex/fleet-journey-runner
- fix(fleet): harden historic installer fixtures
- Merge pull request #332 from davekilleen/codex/onboarding-context-lifecycle
- fix(onboarding): close lifecycle approval gaps
- feat(fleet): survey historic update readiness
- feat(onboarding): persist confirmed context through lifecycle
- Merge pull request #328 from davekilleen/codex/updater-bridge-resume-safety
- fix(update): bind bridge marker to vault runtime
- fix(update): seal bridge runtime environment
- Merge remote-tracking branch 'upstream/main' into codex/updater-bridge-resume-safety
- Merge pull request #329 from davekilleen/codex/fleet-journey-runner
- Merge remote-tracking branch 'upstream/main' into codex/updater-bridge-resume-safety
- feat(fleet): execute one pinned historic update journey
- fix(capabilities): align legacy company defaults
- fix(update): harden bridge resume safety
- test(doctor): expect enabled companies recovery
- fix(capabilities): align legacy company defaults
- fix(update): harden bridge resume boundary
- feat(update): add lifecycle-era bridge bootstrap
- fix(lifecycle): register MCP from delivered definition
- fix(lifecycle): register MCP from delivered definition
- fix: make release changelog insertion portable
- fix: make release changelog insertion portable
- fix(doctor): isolate launch agents by vault
- fix: surface unattributable doctor jobs
- fix: scope doctor launch agents to vault paths
- fix(connect): do not confirm OAuth before token exchange
- fix(connect): do not confirm OAuth before token exchange
- fix: discover archived release fleet trees
- fix: discover archived release fleet trees
<!-- GENERATED:END -->

<!-- PLANNED:START -->
## PLANNED

- Reconcile `release.sh` with the live state ledger at release cut.
- `/dex-orient` — now shipping.
- Add in-flight markers from Dispatch and open PRs — future.
- Verify brain/vault split migrator adoption end to end.
- Live-verify the connection manager.
<!-- PLANNED:END -->
