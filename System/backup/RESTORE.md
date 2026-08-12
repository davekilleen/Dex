# Restoring a Dex vault from backup

A short runbook for the day the machine is gone. Written to be followed on a
brand-new computer with nothing but your backup folder.

## What a backup set contains

Each set is three files with the same date-time stamp:

- `dex-vault-<stamp>.tar.gz`: every note, project, person page, task, and
  setting in the vault, as one compressed archive.
- `dex-vault-<stamp>.bundle`: the vault's complete version history, verified
  at backup time with git's own integrity check.
- `dex-vault-<stamp>.sha256`: fingerprints of both files, so damage in
  storage is detectable before you rely on a copy.

## What is deliberately NOT in a backup

Secrets never leave the machine. The archive excludes:

- `.env` and `.env.local` (AI and integration API keys)
- `.mcp.json` (generated tool configuration that can reference credentials)
- saved sign-in tokens (anything named `*token.json`, such as the Google
  Workspace sign-in), the `System/credentials` folder, and any `.key` or
  `.pem` file anywhere in the vault
- virtual environments, `node_modules`, caches, and scratch working copies

This is a feature: a backup folder that syncs through a cloud provider must
never contain plaintext keys.

## Restore steps

1. Get the backup set onto the new machine (open the synced folder, or
   `rclone copy` the set down from the cloud remote).
2. From an existing Dex install:
   `python3 core/backup/restore_vault.py restore --to ~/restored-vault --source /path/to/backups`
   Without Dex installed, the archive is a plain tar file:
   `tar -xzf dex-vault-<stamp>.tar.gz` after checking
   `shasum -a 256 -c dex-vault-<stamp>.sha256`.
3. Recover the version history:
   `git clone dex-vault-<stamp>.bundle restored-history`
4. Inspect the restored copy, then move it into place yourself. No Dex tool
   ever overwrites a live vault.

## What you must re-establish by hand

Three categories, none of which any archive can carry:

1. **Credentials.** Re-enter API keys into a fresh `.env` (and keep it
   private to your account), reconnect integrations with their setup skills
   (`/granola-setup`, `/todoist-setup`, and so on), and re-add anything that
   lives in the system keychain.
2. **Scheduled jobs.** Background automation (the backup schedule itself,
   meeting sync) is registered with the operating system, not stored in the
   vault. Re-run `python3 core/backup/install_backup_job.py` and the other
   installers you use.
3. **Operating system permissions.** macOS grants for Calendar, Reminders,
   and automation belong to the machine. `/dex-doctor` will list what needs
   granting again.

When in doubt, run `/dex-doctor` on the restored vault: it reports honestly
what works, what is off, and what needs your hands.
