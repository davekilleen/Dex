# Credential remediation

Todoist and Trello raw credentials live only in the ignored vault-root `.env`. The tracked
`System/integrations/config.yaml` stores `*_env_var` references. Internal task sync resolves
those references itself and sends values only inside the adapter runner's stdin JSON. Values
are excluded from argv, process environment, state, queues, results, and logs. Trello's provider
transport requires key/token query parameters, but adapter failures discard provider response
bodies and expose only the HTTP status; request URLs are never included in diagnostics.

Existing `.mcp.json` is scan/report-only and Dex never edits it. Any raw residual keeps local
migration `partial`. Revocation and rotation remain provider actions performed by the user;
Dex may run a read-only replacement health check only in an explicitly requested remediation
flow.

Residual inspection includes both the canonical Todoist/Trello variable names and every exact
uppercase `api_key_env_var`/`token_env_var` name configured in bounded tracked YAML. Malformed,
duplicate, or oversized tracked references fail closed before `.mcp.json` can be classified as
clean. The same YAML file identity and bytes are rechecked after active-config inspection, so a
reference-name swap cannot produce a false clean result. Reference placeholders are not raw
values, and `.mcp.json` remains byte-invariant.

Dex inspects `.mcp.json` with `lstat`, a no-follow open, regular-file/single-link/size/readability
checks, and before/open/after identity comparison. A symlink, hard link, directory, FIFO, device,
socket, unreadable or oversized file, or identity race is never treated as empty or inspected.
Migration is refused when legacy credentials still require migration, otherwise remains
`partial`; active residual state is `unrevoked-or-unclassified`, with only the opaque worktree
scope and reason category reported.

Migration opens every journal-directory component relative to no-follow directory descriptors.
Missing contained descendants may be created only beneath those descriptors; a symlinked parent
refuses capability authorization before any probe or credential preimage can be written outside
the vault.

Migration is authorized per installation only when all live same-directory journal, temporary
file, durability, replace, identity recheck, readback, rollback, and no-follow containment
capabilities pass. OS, filesystem, sync, removable/network, or support labels never veto a
pass. Failure refuses only migration; scan and manual guidance remain available.

`credential_migration_exceptions.json` is read and closed at runtime. SR1 supports only the
owner-approved empty registry; malformed or non-empty authority fails migration closed until an
exact evidence-bound matcher is separately implemented and reviewed.

Safe autosave first stages only explicit unstaged/untracked candidates into a temporary index,
preserving already-staged blobs. It then scans every blob in the exact final temporary index,
not worktree approximations. It refuses raw Todoist/Trello YAML fields, configured known values,
active MCP residuals or unsafe MCP state, and values recovered ephemerally from migration journal
preimages. `.env`, `.mcp.json`, and migration journals remain ignored authorities and are never
staged; an unignored or already tracked authority makes autosave refuse without changing the real
index. Git uses an absolute trusted executable, sanitized configuration/environment, disabled
hooks/signing/fsmonitor, and refuses local executable filters, includes, hooks, drivers, textconv,
or redirected-worktree authority. Findings are counts only; values and value-derived fingerprints
are not serialized.

Credential scanning is bounded by aggregate file, byte, object, archive-member, Git-output, and
deadline limits. Worktree/index completion requires every approved file/blob to pass; selected
archive completion requires every regular member to pass. Git common-dir inspection covers the
bounded refs, packed-refs, and reflog metadata subscopes. Reachable history includes every object
reachable from approved heads, tags, stashes, remote-tracking refs, and reflogs—including
reflog-only commits—but not unrelated unreachable objects. Because unreachable loose or packed
objects are not enumerated, `primary-object-db` remains explicitly uninspected even when the
independent `reachable-refs` scope completes. Any skipped, unsafe, unreadable,
oversized, identity-changing, corrupt, or limit-exceeding input makes the affected scope
uninspected with an opaque category reason and prevents universal clean wording.

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
3. Preparation writes under a mode-`0700` `.incomplete-<opaque-transaction-id>` directory,
   fsyncs and verifies every artifact and the manifest, then atomically publishes it as
   `System/.dex/adoption/history-backups/<opaque-transaction-id>/history.bundle`,
   `objects.json`, `git-config.bin`, `index.bin`, and `manifest.json`. The transaction directory
   is mode `0700`; every file is mode `0600`. The bundle covers every restorable ref, while the
   manifest records every ref plus non-secret HEAD/index/worktree/remote state evidence. Bundle,
   object, ref, config, and index evidence is read back, fsynced, hash-bound, and checked with
   `git bundle verify` before preparation succeeds. No ref is rewritten during preview.
   Every recovery-root and transaction-directory component is opened or created relative to
   no-follow directory descriptors. The transaction directory device/inode identity is persisted
   and revalidated after restart; preparation, apply, rewind, retention preview, and deletion do
   not follow a swapped recovery ancestor. Cancellation removes incomplete preparation state.
   After process death, the next preparation or retention preview descriptor-relatively prunes
   only structurally safe `.incomplete-*` directories; unexpected names, links, or file types fail
   closed. It also prunes structurally safe manifest-less transaction directories left by an
   interrupted older implementation. Published manifest-bearing recovery transactions remain
   fully accounted and are never pruned this way. Preparation and retention pruning hold a
   kernel-released lock on the opened vault-root directory descriptor and mutate through the
   descriptor-bound mode-`0700` backup directory. Replacing any named lock-file decoy cannot split
   ownership. Concurrent preparation/retention cannot prune active work, and cancellation or
   process death releases ownership without weakening restart cleanup.
4. Apply requires the unchanged preview and exact typed consent
   `CLEAN OPTIONAL HISTORY <opaque-transaction-id>`. It rechecks the tool, topology, bundle,
   object evidence, all refs, repository state, and the supplied credential's exact non-secret
   blob-ordinal/start/end occurrence spans and multiplicity in the unchanged selected history before
   invoking `git-filter-repo` with only the selected refs. Credential values are supplied through
   an inherited anonymous file descriptor and are never persisted in a replacement file or
   fingerprint field. The closed occurrence spans distinguish prefix-related and same-sized
   credentials that coexist in selected history without storing any value or value-derived digest. Preparation,
   apply, and rewind may run in separate processes; no
   process-global map is authority. Every unselected ref plus HEAD, index, tracked worktree bytes, and Git
   remote configuration must remain invariant. Dex does not fetch, push, force-push, or contact a
   provider.
5. Apply validates every rewritten ref object and rescans the selected history. The only cleanup
   results are `history-clean`, `history-cleanup-pending`, and `history-scope-unknown`. These are
   privacy-hygiene results and never change or reverse provider rotation.
6. The durable manifest enters `applying` before rewrite. A failure records
   `recovery-required`, preserves the verified bundle, and says not to push. Automatic
   `rewind_history_cleanup(...)` proceeds only when every current ref exactly equals the recorded
   post-attempt set. It restores every original ref, deletes collateral refs transactionally, and
   restores restrictive config/index artifacts. Any unverified HEAD/index/worktree/remote result
   fails closed with exact manual bundle-recovery guidance. Rewind never uses fetch and never
   claims to reverse provider rotation.

Security copy may say `remediated` only with all five exact categories: old-key revocation bound
to the active old value, replacement present, successful read-only replacement health,
active-copy classification, and provider binding. A usable or unclassified active copy remains
impossible with `remediated`; a proven-revoked MCP residual must be bound to that same revoked
value. Empty or provider-binding-only evidence is rejected before copy construction.
7. `preview_retention(...)` excludes the newest history recovery bundle and any unverified or
   corrupt bundle. Older bundles become eligible only after both 90 days and two later successful
   release activations, plus the recorded external-backup posture. Deletion requires
   `delete_retention_candidates(...)` with the exact candidate tuple and exact-set SHA-256 from
   the current preview. No bundle is auto-deleted or uploaded.

If no supported preinstalled `git-filter-repo` is available, preparation returns
`optional-tool-unavailable` without creating recovery state. Security remains fixed; the user may
separately install a supported tool and request a new preview, or leave history unchanged without
an ongoing-danger warning.
