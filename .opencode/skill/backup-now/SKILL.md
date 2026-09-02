---
name: backup-now
description: "Run a vault backup right now and report the verified result. Use when the user says 'back up now', 'take a backup before I do this', or is about to make a big change. Not for scheduling or changing where backups go (`backup-setup`); not for getting files back (`backup-restore`)."
---

# Backup Now

Take an immediate backup of the vault, on top of whatever the schedule is doing. Worth suggesting before anything sweeping: a bulk edit, a big reorganisation, a system update, or a migration.

## Run it

```bash
python3 core/backup/backup_vault.py
```

It takes well under a minute for a typical vault. The command handles archiving, verifying, storing, and pruning old copies in one pass.

If backups have never been configured, the run will fail with a clear message; offer `/backup-setup` rather than improvising a destination.

## Report honestly

Read `System/.dex/backup-last-run.json` and report what actually happened, not what was attempted:

- **On success:** the set name, total size, where it went, and how many older sets were pruned. Say plainly that the version history in the set was verified as complete.
- **On failure:** the recorded error, verbatim. Do not soften it and do not claim a backup exists. Common causes worth naming: the destination folder is missing or not mounted, a cloud remote is not reachable, or the disk is full.

Never infer success from the command finishing. The run record is the evidence.

## If it has not run in a while

If the previous successful run was more than two days before this one, mention it once, quietly and without alarm, and offer `/backup-setup` to check the schedule. A silent scheduling failure is the most common way backups die.
