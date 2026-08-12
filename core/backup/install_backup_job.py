#!/usr/bin/env python3
"""Install the scheduled vault backup job (macOS launchd).

Usage:
    python3 core/backup/install_backup_job.py [--hour 12] [--minute 30]
    python3 core/backup/install_backup_job.py --status
    python3 core/backup/install_backup_job.py --uninstall

The job runs core/backup/backup_vault.py once a day at the configured time;
launchd fires missed runs on wake, so a laptop that was asleep still gets
its backup.

Two hard-won rules are baked in:

1. launchd runs jobs with a bare environment (no usable PATH, no VAULT_PATH),
   which once broke a real vault's backups silently for ten days because
   the interpreter could not be resolved. The plist therefore pins the
   absolute interpreter path (the same Python running this installer), sets
   VAULT_PATH explicitly, and pins a PATH that covers git and Homebrew's
   rclone locations.

2. Never point a machine-wide background job at a temporary checkout.
   Agent tooling runs installers from short-lived git worktrees which then
   vanish and leave the job failing forever; a worktree marks .git as a
   file, so that shape is refused (same guard as the meeting-intel
   installer).

On platforms other than macOS this installer does not pretend: it prints
the equivalent cron line and exits without installing anything.
"""
from __future__ import annotations

import argparse
import plistlib
import subprocess
import sys
from pathlib import Path

try:
    from core.backup.backup_vault import resolve_vault_root
except ImportError:  # invoked by file path: put the vault root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from core.backup.backup_vault import resolve_vault_root

LABEL = "com.dex.vault-backup"
PINNED_PATH = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin"


def plist_destination(home: Path) -> Path:
    return home / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def build_plist(vault: Path, interpreter: str, hour: int, minute: int) -> dict:
    """Build the launchd job definition with every path made absolute."""
    job_log = str(vault / "System" / "backup" / "backup-job.log")
    return {
        "Label": LABEL,
        "ProgramArguments": [
            interpreter,
            str(vault / "core" / "backup" / "backup_vault.py"),
        ],
        "WorkingDirectory": str(vault),
        "EnvironmentVariables": {
            "VAULT_PATH": str(vault),
            "PATH": PINNED_PATH,
        },
        "StartCalendarInterval": {"Hour": hour, "Minute": minute},
        "RunAtLoad": False,
        "StandardOutPath": job_log,
        "StandardErrorPath": job_log,
    }


def looks_like_temporary_checkout(vault: Path) -> bool:
    """A git worktree marks .git as a file; a real vault does not."""
    if (vault / ".git").is_file():
        return True
    return "/worktrees/" in vault.as_posix()


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def _job_loaded() -> bool:
    listing = _launchctl("list")
    return listing.returncode == 0 and LABEL in listing.stdout


def status(home: Path) -> int:
    destination = plist_destination(home)
    if destination.exists():
        print(f"Installed: {destination}")
    else:
        print("Not installed. Run /backup-setup to schedule backups.")
        return 0
    print("Loaded and scheduled." if _job_loaded()
          else "Installed but not loaded; re-run this installer to load it.")
    return 0


def uninstall(home: Path) -> int:
    destination = plist_destination(home)
    if _job_loaded():
        _launchctl("unload", str(destination))
        print("Stopped the scheduled backup job.")
    if destination.exists():
        destination.unlink()
        print(f"Removed {destination}")
    else:
        print("Nothing to remove; the job was not installed.")
    print("Scheduled backups are off. Your existing backup copies are untouched.")
    return 0


def install(vault: Path, home: Path, hour: int, minute: int) -> int:
    if looks_like_temporary_checkout(vault):
        print(f"Refusing to install: {vault} looks like a temporary working "
              "copy (a git worktree), not your real Dex vault.\n"
              "A background job pointed here would fail silently once this "
              "folder disappears. Run the installer from your real vault.")
        return 1
    engine = vault / "core" / "backup" / "backup_vault.py"
    if not engine.exists():
        print(f"Refusing to install: the backup engine is missing at {engine}")
        return 1

    destination = plist_destination(home)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = build_plist(vault, sys.executable, hour, minute)
    with destination.open("wb") as handle:
        plistlib.dump(payload, handle)
    print(f"Wrote {destination}")

    if _job_loaded():
        _launchctl("unload", str(destination))
    load = _launchctl("load", str(destination))
    if load.returncode != 0 or not _job_loaded():
        detail = (load.stderr or load.stdout).strip()
        print("The job was written but launchd did not load it."
              + (f" launchctl said: {detail}" if detail else ""))
        return 1
    print(f"Scheduled: daily at {hour:02d}:{minute:02d} "
          "(missed runs fire when the machine wakes).")
    print("Run python3 core/backup/backup_vault.py now to prove the first "
          "backup works; do not assume it does.")
    return 0


def cron_guidance(vault: Path, hour: int, minute: int) -> str:
    return (
        "Automatic scheduling is only wired up for macOS (launchd) so far.\n"
        "On Linux, add this line with `crontab -e` (cron does not run missed "
        "jobs after sleep, so pick a time the machine is reliably on):\n"
        f"  {minute} {hour} * * * cd {vault} && "
        f"VAULT_PATH={vault} {sys.executable} core/backup/backup_vault.py\n"
        "On Windows, use Task Scheduler to run the same command daily.\n"
        "Nothing was installed."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hour", type=int, default=12)
    parser.add_argument("--minute", type=int, default=30)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--vault", help="vault root (default: VAULT_PATH or "
                                        "this file's own vault)")
    args = parser.parse_args(argv)
    if not (0 <= args.hour <= 23 and 0 <= args.minute <= 59):
        parser.error("--hour must be 0-23 and --minute must be 0-59")
    vault = resolve_vault_root(args.vault)
    home = Path.home()
    if sys.platform != "darwin":
        print(cron_guidance(vault, args.hour, args.minute))
        return 2
    if args.status:
        return status(home)
    if args.uninstall:
        return uninstall(home)
    return install(vault, home, args.hour, args.minute)


if __name__ == "__main__":
    sys.exit(main())
