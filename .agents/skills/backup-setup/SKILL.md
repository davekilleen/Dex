---
name: backup-setup
description: "Set up automatic vault backups to a synced folder or a cloud provider, with verified archives and tiered retention. Use when the user says 'back up my vault', 'set up backups', 'where are my backups going', or asks about losing their notes. Not for restoring or testing a restore (`backup-restore`); not for a one-off backup right now (`backup-now`)."
integration:
  id: vault-backup
  name: Vault Backup
  mcp_server: null
  auth: none
---

<!-- Generated from `.claude/skills/backup-setup/SKILL.md` by `scripts/generate-agents-skills.py`. Do not edit. -->

# Backup Setup

Set up (or change) automatic backups of the whole vault: notes, projects, people, tasks, settings, and the vault's own version history. Runs on a schedule in the background, keeps a sensible ladder of older copies, and tells you loudly if it ever stops working.

## What a backup contains

Every run writes a **set** of three files, stamped with the date and time:

| File | What it is |
|------|-----------|
| `dex-vault-<stamp>.tar.gz` | The whole vault as one compressed archive |
| `dex-vault-<stamp>.bundle` | The vault's version history, individually verified so a restore is provable rather than hoped for |
| `dex-vault-<stamp>.sha256` | Fingerprints of both, so damage in storage is detectable |

Secrets are deliberately left out: the `.env` file holding AI keys, generated tool configuration that can reference credentials, saved sign-in tokens (`*token.json`), the `System/credentials` folder, any `.key` or `.pem` file, virtual environments, and caches. Never store those in a synced folder. Keys live in the system keychain or get re-entered on restore. See `docs/backup-restore.md` for what a full rebuild needs beyond these files.

## Step 1: Where should backups go?

Ask which destination suits them, in plain terms:

1. **A synced folder** (default, simplest): OneDrive, iCloud Drive, Dropbox, Google Drive, or a plugged-in external disk. Anything that looks like a folder on their Mac. The file-sync app carries copies off the machine.
2. **A cloud storage provider directly**: Amazon S3, Backblaze B2, Google Drive proper, and around seventy others, using a tool called rclone. Choose this when they want backups genuinely off their machine rather than mirrored by a sync app, or their vault is large enough that a sync folder is awkward.

For option 1 ask for the folder path. Offer to detect likely candidates:

```bash
ls -d ~/Library/CloudStorage/* ~/Dropbox ~/Google\ Drive 2>/dev/null
```

For option 2, check whether rclone is present and configured:

```bash
rclone listremotes
```

If they choose rclone, use a named remote they created with `rclone config` (for example `b2:dex-backups`). Never put an inline connection string carrying a key or secret into `backup.remote`: it would be written to the local run record and archived inside the backup itself.

If rclone is missing, say so plainly and give them the choice: install it (`brew install rclone`, then `rclone config` to add their provider) or start with a synced folder now and switch later. Do not attempt to configure their cloud credentials for them; rclone's own setup handles that interactively and safely.

## Step 2: How many copies to keep?

Explain the default in one line: **7 daily, 4 weekly, 3 monthly**. Recent copies for accidents, older copies for problems noticed late (a bad edit that spread quietly, a file corrupted weeks ago). Roughly fourteen sets, which for a typical vault is a couple of gigabytes.

Accept a different ladder if they want one. The newest set is never deleted, whatever the ladder says.

## Step 3: Save the settings

Write to `System/integrations/config.yaml` under `backup:`:

```yaml
backup:
  enabled: true
  backend: folder          # folder | rclone
  destination: /path/to/folder    # folder backend
  remote: ""                      # rclone backend, e.g. "b2:dex-backups"
  retention:
    daily: 7
    weekly: 4
    monthly: 3
```

## Step 4: Schedule it

Install the background job (daily, 12:30 by default; ask if they'd prefer another time, and pick a time their machine is usually awake):

```bash
python3 core/backup/install_backup_job.py --hour 12 --minute 30
```

On macOS this schedules the job so missed runs fire when the machine wakes. On other platforms the installer does not pretend: it prints the exact line to schedule the same command with the platform's own scheduler, and installs nothing.

## Step 5: Prove it works

Do not tell them backups are set up until one has actually run. Run one now:

```bash
python3 core/backup/backup_vault.py
```

Then show them the real result from `System/.dex/backup-last-run.json`: the set name, size, and destination. If it failed, show the recorded error and fix the cause before declaring success.

Finish by telling them three things: where backups are going, how to get one on demand (`/backup-now`), and that `/backup-restore` in test mode proves a restore works without touching anything.

## If backups stop working

`/dex-doctor` checks the last-run record and flags it when the newest successful backup is more than two days old. That check exists because a backup can fail silently for weeks and look identical to a healthy one. If they ask why a warning appeared, read `System/.dex/backup-last-run.json` and report the recorded error verbatim rather than guessing.
