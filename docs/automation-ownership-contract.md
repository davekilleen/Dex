# Dex Solo automation ownership contract

**Summary:** Dex Solo may take over one existing Dex launchd job only after it
has unloaded that job and verified it is no longer loaded. Core then seals the
exact plist bytes and owner in a transaction-written runtime sidecar. To give
the job back, Solo stops its own scheduler before recording the release.

## Frozen lifecycle API (v1.5.0)

Claim preview:

```python
previewed = service.build_and_preview_automation_claim(vault_root, {
    "automation_id": "com.dex.smoke-nightly",
    "owner_id": "dex-solo",
    "plist_relative_path": "Library/LaunchAgents/com.dex.smoke-nightly.plist",
    "plist_sha256": "<lowercase SHA-256 of the current plist bytes>",
    "launchd_state": "unloaded",
})
```

Claim execution:

```python
claimed = service.execute_approved_automation_claim(
    vault_root,
    previewed["preview"],
    previewed["approval_token"],
)
```

Release preview and execution:

```python
previewed = service.build_and_preview_automation_release(vault_root, {
    "automation_id": "com.dex.smoke-nightly",
    "owner_id": "dex-solo",
    "scheduler_state": "stopped",
})
released = service.execute_approved_automation_release(
    vault_root,
    previewed["preview"],
    previewed["approval_token"],
)
```

The caller must treat `needed: false` as success: the requested claim or
release is already in effect. Re-executing an approved preview is also safe and
returns `already-claimed` or `already-released` without another transaction.

## Safety boundary

- Core accepts only `dex-solo`, canonical launchd ids, a home-relative
  `Library/LaunchAgents/*.plist` path, and lowercase SHA-256 evidence.
- The unload and stop fields are caller attestations at this cross-repository
  boundary. Dex Solo must perform and verify each action before making the
  corresponding call; Core rejects every other state literal but does not
  control or inspect Solo's scheduler process.
- Claim execution re-reads the plist and sidecar, then recomputes the approval
  binding. Changed plist bytes or ownership state require a new preview.
- The only writable path is
  `System/.dex/automation-ownership.json`, allowlisted specifically for the
  `automation-ownership` transaction operation. The legacy lifecycle ledger is
  not touched.
- Doctor and SessionStart ignore a Core launchd job only while its Dex Solo
  claim is structurally valid and its current plist still matches the sealed
  hash. Invalid or stale evidence fails closed to Core's normal checks.
