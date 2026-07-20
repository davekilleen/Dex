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
values, and `.mcp.json` remains byte-invariant. YAML uses a duplicate-rejecting SafeLoader for
every mapping level, including escaped-equivalent keys and repeated top-level service mappings;
later mappings can never hide an earlier custom credential reference.

Dex inspects `.mcp.json` with `lstat`, a no-follow open, regular-file/single-link/size/readability
checks, and before/open/after identity comparison. A symlink, hard link, directory, FIFO, device,
socket, unreadable or oversized file, or identity race is never treated as empty or inspected.
Migration is refused when legacy credentials still require migration, otherwise remains
`partial`; active residual state is `unrevoked-or-unclassified`, with only the opaque worktree
scope and reason category reported. Integration YAML is parsed through one bounded shared
authority used by migration, runtime task sync, setup validation, status, and scanning. It
rejects every duplicate key plus all aliases, anchors, and merge mappings before adapter use.

Migration opens every journal-directory component relative to no-follow directory descriptors.
Missing contained descendants may be created only beneath those descriptors; a symlinked parent
refuses capability authorization before any probe or credential preimage can be written outside
the vault.

Credential rewind read-only prevalidates the journal, both pinned target parents, both complete
preimages, and the exact migration-owned config and `.env` postimages before changing either
target. One closed typed journal model validates exact top-level, target-image, identity, and
phase keys, initializes every new journal to `ready`, and owns only the explicit
`ready → publishing → completed` and `publishing → recovery → ready` transitions. Missing or
unknown phase state is corrupt rather than inferred. It durably records publication state,
publishes local-only `.env` state before tracked
YAML, and restores both migrated postimages after any caught boundary fault. A process-stopped
publication remains explicitly recoverable; the next rewind invocation first resolves it back to
the no-raw-YAML migrated state before retrying.

Vault `.env` uses one lossless canonical quoted serializer/parser. Accepted non-empty scalar
bytes—including leading/trailing spaces, literal quotes, backslashes, `#`, and `=`—round-trip
exactly while the file's existing CRLF or LF convention is preserved. Reads and replacements
are relative to one pinned no-follow vault descriptor and bind pre-open/open/post-open/current
device, inode, type, link count, size, mode, and ownership evidence. The file must be one
current-user-owned regular file with mode `0600`; `0640`, `0644`, wrong-owner, symlink, hard-link,
and identity-race inputs fail closed with repair guidance. Platforms lacking descriptor-relative
no-follow directory operations are reported unsupported rather than falling back to pathname
authority.

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
index. Autosave creates the commit object without moving `HEAD`, durably journals original and
target ref/index identities, compare-and-swaps `HEAD`, then publishes the index. Any caught
failure restores both exactly; process death is recovered deterministically from the restrictive
Git-directory journal on the next invocation. Git uses an absolute trusted executable, sanitized configuration/environment, disabled
hooks/signing/fsmonitor, and refuses local executable filters, includes, hooks, drivers, textconv,
or redirected-worktree authority. Findings are counts only; values and value-derived fingerprints
are not serialized.

The tracked-file security gate hands off only to an absolute system Python in isolated mode and
the scanner resolves Git through the shared absolute trusted-Git policy. The wrapper uses no
ambient `python3`, `git`, `mktemp`, `sed`, or cleanup utility whose `PATH` replacement could forge
a clean verdict; absence of the trusted interpreter fails closed.

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
   closed. A normal transaction ID without a valid closed manifest is corrupt recovery state and
   fails closed without deletion. Published manifest-bearing recovery transactions remain
   fully accounted and are never pruned this way. Preparation and retention pruning hold a
   kernel-released lock on the opened vault-root directory descriptor. The recovery hierarchy is
   traversed from that descriptor, and preparation, manifest loading, apply, rewind, retention,
   and exact-set deletion retain and mutate through the same descriptor-bound mode-`0700` backup
   directory. Reopening the vault or recovery hierarchy by pathname is not lifecycle authority.
   Replacing any named lock-file decoy cannot split ownership. Concurrent preparation/retention
   cannot prune active work, and cancellation or process death releases ownership without
   weakening restart cleanup. A closed `HistoryManifest` owns exact keys, nested artifact/ref
   validation, canonical hashing/serialization, and only the explicit `begin_apply`,
   `record_applied`, `record_recovery_required`, and `record_rewound` transitions.
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
value. Present, missing, and unavailable evidence have separate typed inputs; unknown states also
require a named unsupported/unavailable/inconsistent cause. A missing provider-binding check is a
valid `rotation-pending` reason, while a present provider binding alone cannot prove remediation.
7. `preview_retention(...)` excludes the newest history recovery bundle and any unverified or
   corrupt bundle. Older bundles become eligible only after both 90 days and two later successful
   release activations, plus the recorded external-backup posture. Deletion requires
   `delete_retention_candidates(...)` with the exact candidate tuple and exact-set SHA-256 from
   the current preview. No bundle is auto-deleted or uploaded.

If no supported preinstalled `git-filter-repo` is available, preparation returns
`optional-tool-unavailable` without creating recovery state. Security remains fixed; the user may
separately install a supported tool and request a new preview, or leave history unchanged without
an ongoing-danger warning.

The guided path also requires an operating-system substrate that can reopen a directory file
descriptor by a derived path (Linux `/proc/self/fd`), which is used to pin the vault root against
rename races for the whole transaction. macOS `/dev/fd` cannot reopen a *directory* descriptor, so
the guided path is unavailable there. Preparation probes this substrate functionally up front
(not by platform name, so `/proc`-less or containerized hosts are judged by what actually works)
and, when it is absent, returns `optional-platform-unsupported` before any lock, transaction, or
recovery directory is created — no exception and no writes. Security remains fixed; the guided path
runs on Linux (including WSL2 or a Linux container that exposes `/proc`), and the manual advanced
path (verify a private local backup, run a separately reviewed offline history-cleaning procedure,
rerun the credential scanner before publication) is available on any platform. Even after a
successful cleanup the revoked value can remain locally recoverable — in the retained recovery
bundle and in unreachable/reflog objects — until local backups expire and repository garbage
collection runs; because remediation already required the provider key to be revoked, that residual
is a dead value, but the guided path never claims a secret is fully gone from disk.
