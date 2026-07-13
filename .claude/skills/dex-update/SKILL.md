---
name: dex-update
description: Check for and safely install a Dex release without merging into the user's vault
---

# Update Dex

Talk like a smart friend. Explain what will change, what stays untouched, and what the user should do next. Do not narrate internal Git plumbing.

## Safety rule

Dex v2 updates are staged file replacements, never merges. Once a migration or update begins, recovery is only through the owning script's `--resume`, `--restore`, or `--rollback` mode. Never use raw Git for recovery, even if a command looks familiar.

Work from the vault root. The topology sentinel is `System/.dex/topology.json`.

## 1. Find the topology

Run:

```bash
node core/update/apply-update.cjs --status
```

- `post-split`: continue to the update check.
- `migration-pending`: say, “Dex needs a one-time upgrade that separates the app from your notes. Your folders stay where they are.” Then run the migrator below before applying the release.
- `migration-in-progress`: run the migrator with `--resume`.
- `zip-or-manual`: use the ZIP/no-Git section. Do not start a partial conversion.

For the one-time migration:

```bash
node core/migrations/v1-to-v2-brain-vault-split.cjs --auto
```

If it exits with the safe-resume signal, continue only with:

```bash
node core/migrations/v1-to-v2-brain-vault-split.cjs --resume
```

Do not continue to the updater until the migration reports that both histories are healthy.

## 2. Check and confirm

Run:

```bash
node core/update/apply-update.cjs --check
```

If it reports `DEX_UPDATE_CURRENT`, say Dex is already current and stop.

If an update is available, show the current and target versions and summarize the release notes in plain English. Keep the BREAKING gate: when the release notes or update metadata mark the release `BREAKING`, explain the practical consequence and get an explicit confirmation before doing anything else. For an ordinary release, ask for a short “Update now?” confirmation.

## 3. Apply

After confirmation, run:

```bash
node core/update/apply-update.cjs --apply
```

For a chosen release, append `--target dist-vX.Y.Z`.

If the script stops safely, use only:

```bash
node core/update/apply-update.cjs --resume
```

The updater backs up modified shipped files before replacement, preserves edited seeds, stages and verifies the release, and reports files it kept rather than pruning. Do not substitute manual file copies or raw Git commands.

## 4. Install signalled dependencies

Read the final `DEX_DEPENDENCIES npm=N pip=N` line.

When `npm=1`:

```bash
npm install
```

When `pip=1`, use the vault environment if it exists:

```bash
if [ -x .venv/bin/python ]; then
  .venv/bin/python -m pip install -r requirements.txt
else
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi
```

If dependency installation fails, leave the installed brain release in place, explain the failure, and retry the dependency command. Do not roll files backward behind the updater's journal.

## 5. Verify

Use the vault Python when available:

```bash
DEX_PYTHON=python3
[ ! -x .venv/bin/python ] || DEX_PYTHON=.venv/bin/python
"$DEX_PYTHON" core/utils/doctor.py --deep
"$DEX_PYTHON" core/utils/smoke.py
```

Report the doctor/smoke verdicts honestly. `UNKNOWN` means a check could not prove its answer; it is not the same as healthy.

## 6. Tell the user what happened

Read and summarize:

- `System/migration-report-v2.md` when the one-time split ran.
- `System/.dex/update-report.md` after an update or rollback.

Call out backed-up shipped files, files kept because the user's copy differed, dependency work, and any doctor/smoke follow-up. Use plain English, not a dump of command output.

## ZIP or no-Git installs

Present two choices and wait for the user:

1. **Convert to automatic updates.** Create a separate fresh Dex checkout from the official repository, follow the conversion instructions in `System/migration-report-v2.md`, verify the new brain/vault topology, then keep the old folder until doctor and smoke pass. Never graft a downloaded `.git` directory into the current folder.
2. **Stay on manual updates.** Download the new Dex ZIP into a separate folder. Copy the complete user-owned set from the old folder: `00-Inbox/` through `07-Archives/`, `System/user-profile.yaml`, `System/pillars.yaml`, `System/Session_Learnings/`, `System/Session_Memory/`, `CLAUDE-custom.md`, `.mcp.json`, every `.claude/skills/*-custom/` folder, `core/mcp-custom/`, and private environment/credential files. Do not copy old shipped `core/`, `.claude` non-custom content, `package.json`, or hidden Git data over the new release. Run doctor and smoke in the new folder before retiring the old one.

If either choice is uncertain, stop with both folders intact. A ZIP update must never create a half-topology.
