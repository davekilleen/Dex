# Credential remediation

Todoist and Trello raw credentials live only in the ignored vault-root `.env`. The tracked
`System/integrations/config.yaml` stores `*_env_var` references. Internal task sync resolves
those references itself and sends values only inside the adapter runner's stdin JSON. Values
are excluded from argv, process environment, state, queues, results, and logs.

Existing `.mcp.json` is scan/report-only and Dex never edits it. Any raw residual keeps local
migration `partial`. Revocation and rotation remain provider actions performed by the user;
Dex may run a read-only replacement health check only in an explicitly requested remediation
flow.

Migration is authorized per installation only when all live same-directory journal, temporary
file, durability, replace, identity recheck, readback, rollback, and no-follow containment
capabilities pass. OS, filesystem, sync, removable/network, or support labels never veto a
pass. Failure refuses only migration; scan and manual guidance remain available.

History cleanup is optional privacy hygiene. It requires an explicit choice, a restrictive
verified local bundle, typed consent, and a preinstalled supported `git-filter-repo`. Dex never
installs that tool, contacts a provider, or pushes rewritten history.

## Optional local history hygiene contract

The implementation is `core.utils.history_hygiene`. A trusted in-process remediation caller
passes revoked credential bytes directly to this API; values must never be placed in a shell
command, argv, process environment, manifest, log, state, or Doctor output.

1. Call `prepare_history_cleanup(...)` only after the independent security state is
   `remediated`, the user explicitly chooses optional cleanup, and the user supplies either
   verified external-backup evidence or explicitly acknowledges that no external backup
   exists. The caller must pass the exact unique local refs selected by the user. Supported
   scopes are `refs/heads/*`, `refs/tags/*`, and `refs/stash/*`.
2. Preparation resolves absolute Git and a supported preinstalled `git-filter-repo`; it never
   installs a tool. It refuses linked-worktree/common-dir ambiguity, alternates, shallow or
   promisor repositories, an object database outside the primary common directory, insufficient
   free space including the 1 MiB margin, or projected shared recovery use above 10 GiB.
3. Preparation writes
   `System/.dex/adoption/history-backups/<opaque-transaction-id>/history.bundle`,
   `objects.json`, and `manifest.json`. The transaction directory is mode `0700`; every file is
   mode `0600`. Bundle/object/ref identities are read back, fsynced, hash-bound, and checked with
   `git bundle verify` before preparation succeeds. No ref is rewritten during preview.
4. Apply requires the unchanged preview and exact typed consent
   `CLEAN OPTIONAL HISTORY <opaque-transaction-id>`. It rechecks the tool, topology, bundle,
   object evidence, selected refs, and credential selection before invoking `git-filter-repo`
   with only the selected refs. Git remote configuration is restored byte-for-byte if the tool
   changes it. Dex does not fetch, push, force-push, or contact a provider.
5. Apply validates every rewritten ref object and rescans the selected history. The only cleanup
   results are `history-clean`, `history-cleanup-pending`, and `history-scope-unknown`. These are
   privacy-hygiene results and never change or reverse provider rotation.
6. The durable manifest enters `applying` before rewrite. A failure records
   `recovery-required`, preserves the verified bundle, and says not to push. Automatic
   `rewind_history_cleanup(...)` proceeds only when current selected refs exactly equal the
   recorded post-attempt refs; otherwise it fails closed with exact manual bundle-recovery
   guidance. Rewind uses local bundle objects and transactional `git update-ref`; it never uses
   fetch and never claims to reverse provider rotation.
7. `preview_retention(...)` excludes the newest history recovery bundle and any unverified or
   corrupt bundle. Older bundles become eligible only after both 90 days and two later successful
   release activations, plus the recorded external-backup posture. Deletion requires
   `delete_retention_candidates(...)` with the exact candidate tuple and exact-set SHA-256 from
   the current preview. No bundle is auto-deleted or uploaded.

If no supported preinstalled `git-filter-repo` is available, preparation returns
`optional-tool-unavailable` without creating recovery state. Security remains fixed; the user may
separately install a supported tool and request a new preview, or leave history unchanged without
an ongoing-danger warning.
