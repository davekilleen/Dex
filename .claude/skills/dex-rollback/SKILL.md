---
name: dex-rollback
description: Safely return Dex's brain to an earlier installed release, or restore the pre-split layout during the bridge window
---

# Roll back Dex

Use plain-English framing. Start with: “This changes Dex's shipped app files. Your notes, projects, edited planning files, and custom instructions stay yours.” Then explain which of the two rollback scopes applies and ask the user to confirm.

## Safety rule

The topology sentinel is `System/.dex/topology.json`. When it says `brain-vault-split`, never use raw Git recovery. The updater owns brain rollback; the migrator owns the one-release-cycle total pre-split restore. If either script stops, use its recovery mode rather than inventing commands.

## A. Brain-only rollback (normal choice)

Use this when the user wants to undo the most recent Dex release while keeping the split topology and all current vault history.

First show local status:

```bash
node core/update/apply-update.cjs --status
```

Explain the recorded previous version from `System/.dex/installed-history.json`, then get explicit confirmation. Run:

```bash
node core/update/apply-update.cjs --rollback
```

To choose a specific recorded release, use its full OID:

```bash
node core/update/apply-update.cjs --rollback --to FULL_OID_FROM_INSTALLED_HISTORY
```

If interrupted, continue only with:

```bash
node core/update/apply-update.cjs --resume
```

Then follow the `DEX_DEPENDENCIES` signal exactly as `/dex-update` does, run doctor and smoke, and summarize `System/update-report.md`. Mention backed-up or retained shipped files plainly.

## B. Total pre-split restore (temporary bridge option)

Offer this only while `.dex/pre-split-archive.git` and its migration marker still exist. It is available for one release cycle and returns the whole folder to the layout from before the brain/vault split.

Say clearly: “This removes the split topology and restores the archived pre-upgrade repository. Work created since the split is preserved by the migrator's restore safeguards, but this is a bigger change than a brain rollback.” Get a second explicit confirmation.

Run:

```bash
node core/migrations/v1-to-v2-brain-vault-split.cjs --restore
```

If the migration itself is incomplete, inspect its status and choose only `--resume` or `--restore`:

```bash
node core/migrations/v1-to-v2-brain-vault-split.cjs --status
```

Do not manually move `.git`, `.dex/brain.git`, or `.dex/pre-split-archive.git`. The migrator journals and verifies those transitions.

## Refusal cases

- No `System/.dex/topology.json` and no marked archive: explain that automated v2 rollback cannot prove a safe target and stop.
- An active migration/update lock: wait for the owning process; do not remove the lock while that process is alive.
- A target OID absent from `System/.dex/installed-history.json`: refuse it.
- ZIP/no-Git folder: use the manual update/restore guidance in `/dex-update`; do not create a partial repository.

Finish by reporting the exact installed version, doctor/smoke verdicts, and the report path the user can inspect.
