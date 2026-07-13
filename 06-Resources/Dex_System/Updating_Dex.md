# Updating Dex

Dex updates can improve the system without putting your work at risk. Your notes now have their own private version history, separate from the files that make Dex run.

That separation is the important bit: `/dex-update` updates Dex only. The updater has a hard boundary around your notes, projects, tasks, people pages, settings, secrets, and custom additions, so it physically cannot replace or delete them.

## Update in one command

In your conversation with Dex, run:

```text
/dex-update
```

Dex checks what is available, explains the practical changes, and asks before installing anything. If an update needs extra care, it says so before you confirm.

The update is prepared and checked away from your live files first. Dex then replaces only the shipped files it owns. If you edited one of those shipped files, Dex makes a backup and tells you what it kept. At the end, it checks that the updated system is healthy and gives you a plain-English summary.

If an update is interrupted, run `/dex-update` again. Let Dex resume its own safe process; do not try to repair it with Git commands.

## Your first update includes a one-time upgrade

The first update to this version separates Dex from your vault — the folders where your own work lives.

This is a one-time upgrade. It:

* gives your notes their own private history on your computer;
* gives Dex a separate history for future app updates;
* moves none of your notes or folders;
* changes none of their contents; and
* loses nothing.

Before making the switch, Dex checks the setup and takes the safety snapshots it needs. It then writes a readable account of exactly what happened to:

```text
System/migration-report-v2.md
```

Your vault starts with no online backup destination, so its history stays on your computer unless you deliberately add a private backup later.

## Rolling back

Run:

```text
/dex-rollback
```

Dex will explain which rollback is appropriate and ask before changing anything.

* **Normal rollback:** returns Dex's shipped files to the previous installed version. Your current notes and their version history stay as they are.
* **Total pre-split restore:** a temporary bridge option available for one release cycle. It returns the whole folder to its layout from before the one-time upgrade. This is a bigger change, so Dex asks for a second confirmation and uses the protected pre-upgrade archive to do it safely.

Use `/dex-rollback` for either route. Do not move hidden Git folders or try raw Git recovery yourself.

## If your copy came from a ZIP or has no Git history

Dex will not create a half-upgraded setup. `/dex-update` offers two complete choices:

1. **Convert to automatic updates.** Start from a fresh official Dex checkout, bring your work across using the guided conversion, and keep the old folder until the new setup passes its checks.
2. **Stay with manual updates.** Download the new Dex ZIP into a separate folder, copy your user-owned folders, settings, secrets, and custom additions across, then check the new folder before retiring the old one.

If you are unsure, leave both folders intact and stop. You can choose either complete route later; Dex will never mix the two into an unsafe partial setup.

## The short version

Run `/dex-update` when you want the latest Dex. Your work has its own private history, the updater can touch only Dex-owned files, and `/dex-rollback` is there if you want to go back.
