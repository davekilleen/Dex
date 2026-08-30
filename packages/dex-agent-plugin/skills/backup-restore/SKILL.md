---
name: backup-restore
description: "Verify a vault backup, prove it restores, or restore it to a folder of the user's choosing. Use when the user says 'restore my backup', 'test my backups', 'are my backups any good', or after data loss. Never overwrites the live vault. Not for taking a backup (`backup-now`); not for scheduling (`backup-setup`)."
---

<!-- Generated from `.claude/skills/backup-restore/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

# Backup Restore

Three jobs, in increasing weight: prove a backup is intact, prove it actually restores, and bring one back. All three are driven by one tool, and none of them will ever overwrite the live vault: a restore always goes to a fresh folder the user chooses, to inspect and move into place themselves.

## Test mode (the one to suggest routinely)

```bash
python3 core/backup/restore_vault.py test
```

This checks the newest set's fingerprints, verifies the version-history bundle with git's own verifier, extracts the whole archive into a throwaway temporary folder, counts what came out, and deletes the extraction. It proves a restore works without touching anything. Suggest running it once after setup and occasionally after that; a backup that has never been test-restored is a hope, not a backup.

## Verify only (quick integrity check)

```bash
python3 core/backup/restore_vault.py verify
```

Fingerprint and history checks only, no extraction. Add `--set <stamp>` for a specific older set, or `--source /path` for a folder other than the configured destination.

## Restore for real

First ask which set they want (default is the newest) and where the restored copy should go. The target must be a new or empty folder.

```bash
python3 core/backup/restore_vault.py restore --to /path/to/fresh-folder
```

Then be explicit about three things:

1. **The live vault was not touched.** The restored copy sits in the folder they chose. Comparing, cherry-picking files, or swapping the whole vault over is their deliberate next step, not something this tool does behind their back.
2. **The version history comes back separately.** The history bundle is copied alongside; `git clone dex-vault-<stamp>.bundle restored-history` recovers it.
3. **Secrets and schedules are not in the backup, on purpose.** API keys, the scheduled backup job itself, and macOS permissions all need re-establishing. Walk them through `docs/backup-restore.md` for the full list.

## For cloud (rclone) backups

The tool is honest about not reaching into the network: copy one set down first (`rclone copy remote:path/dex-vault-<stamp>.* /some/local/folder/`), then point `--source` at that folder.

## Report honestly

Report exactly what the tool printed. If verification failed, the copy in storage is damaged: say so plainly, and suggest trying the next-oldest set (`--set`) rather than pretending the newest one is usable.
