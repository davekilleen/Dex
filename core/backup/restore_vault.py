#!/usr/bin/env python3
"""Verify, test-restore, or restore a vault backup set.

Usage:
    python3 core/backup/restore_vault.py verify  [--set STAMP] [--source DIR]
    python3 core/backup/restore_vault.py test    [--set STAMP] [--source DIR]
    python3 core/backup/restore_vault.py restore --to DIR [--set STAMP] [--source DIR]

verify   recompute the checksums against the .sha256 sidecar and, when a
         history bundle is present, run `git bundle verify` on it.
test     verify, then fully extract the archive into a throwaway temporary
         folder, count what came out, and delete the extraction. Proves a
         restore works without touching anything.
restore  verify, then extract into a folder you choose. The target must be
         empty or absent; this tool never overwrites the live vault or any
         existing files. Reconnecting keys, schedules, and permissions is a
         separate, deliberate step: see docs/backup-restore.md.

--source defaults to the folder backend's configured destination. For the
rclone backend, first copy one set down to a local folder
(`rclone copy remote:path/dex-vault-<stamp>.* /some/folder/`) and point
--source at it; this tool stays honest by not reaching into the network.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

try:
    from core.backup.backup_vault import PREFIX, file_digest, load_config, resolve_vault_root
except ImportError:  # invoked by file path: put the vault root on sys.path
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from core.backup.backup_vault import PREFIX, file_digest, load_config, resolve_vault_root


class RestoreError(RuntimeError):
    """A condition that must stop the run with a plain explanation."""


def resolve_source(vault: Path, override: str | None) -> Path:
    if override:
        source = Path(override).expanduser()
        if not source.is_dir():
            raise RestoreError(f"--source {source} is not a folder")
        return source
    config = load_config(vault)
    if config["backend"] != "folder" or not config["destination"]:
        raise RestoreError(
            "No local backup folder is configured. For the rclone backend, "
            "copy one backup set to a local folder first and pass --source.")
    source = Path(config["destination"]).expanduser()
    if not source.is_dir():
        raise RestoreError(f"The configured backup folder {source} does not exist")
    return source


def pick_set(source: Path, requested: str | None) -> str:
    stamps = sorted({p.name[len(PREFIX):-len(".tar.gz")]
                     for p in source.glob(f"{PREFIX}*.tar.gz")}, reverse=True)
    if not stamps:
        raise RestoreError(f"No backup sets found in {source}")
    if requested is None:
        return stamps[0]
    if requested not in stamps:
        raise RestoreError(f"Set {requested} not found in {source}. "
                           f"Available: {', '.join(stamps)}")
    return requested


def verify_set(source: Path, stamp: str) -> list[str]:
    """Return plain-language findings; raise RestoreError on any mismatch."""
    findings: list[str] = []
    sidecar = source / f"{PREFIX}{stamp}.sha256"
    if not sidecar.exists():
        raise RestoreError(f"The checksum file {sidecar.name} is missing; "
                           "this set cannot be proven intact")
    checked: set[str] = set()
    for line in sidecar.read_text().splitlines():
        expected, _, name = line.strip().partition("  ")
        if not name:
            continue
        checked.add(name)
        artifact = source / name
        if not artifact.exists():
            raise RestoreError(f"{name} is listed in the checksum file but missing")
        actual = file_digest(artifact)
        if actual != expected:
            raise RestoreError(f"{name} does not match its recorded checksum; "
                               "the copy in storage is damaged")
        findings.append(f"{name}: checksum matches")
    # The sidecar names the files it covers, so a sidecar carried over from a
    # different set (a copy, a rename, a sync conflict) would otherwise verify
    # that other set's files and report this one intact without ever reading
    # the archive about to be unpacked.
    archive_name = f"{PREFIX}{stamp}.tar.gz"
    if archive_name not in checked:
        raise RestoreError(
            f"{sidecar.name} does not cover {archive_name}, so the archive "
            "this set would restore has not been checked at all. The checksum "
            "file belongs to a different set; do not rely on this copy.")
    bundle = source / f"{PREFIX}{stamp}.bundle"
    if bundle.exists():
        if bundle.name not in checked:
            raise RestoreError(
                f"{bundle.name} is present but {sidecar.name} does not cover "
                "it, so the version history in this set is unchecked.")
        git = shutil.which("git")
        if git is None:
            findings.append(f"{bundle.name}: present, but git is not installed "
                            "so the history could not be verified here")
        else:
            result = subprocess.run([git, "bundle", "verify", str(bundle)],
                                    capture_output=True, text=True)
            if result.returncode != 0:
                raise RestoreError(f"git bundle verify failed for {bundle.name}: "
                                   f"{(result.stderr or result.stdout).strip()[:300]}")
            findings.append(f"{bundle.name}: history verified as complete")
    else:
        findings.append("No history bundle in this set (the vault had no "
                        "version history when it was taken)")
    return findings


def _with_fallback_hint(error: RestoreError, source: Path,
                        failed: str) -> RestoreError:
    """Add the newest set that does verify, when the requested one does not."""
    others = [s for s in sorted(
        {p.name[len(PREFIX):-len(".tar.gz")]
         for p in source.glob(f"{PREFIX}*.tar.gz")}, reverse=True)
        if s != failed]
    for candidate in others:
        try:
            verify_set(source, candidate)
        except RestoreError:
            continue
        return RestoreError(
            f"{error} The most recent set that does check out intact is "
            f"{candidate}; add --set {candidate} to use it.")
    if others:
        return RestoreError(f"{error} No older set in {source} checks out "
                            "intact either.")
    return error


def extract_archive(source: Path, stamp: str, target: Path) -> int:
    """Extract one set's archive, turning any failure into a plain explanation.

    Extraction refuses shortcut-style linked files that point outside the
    folder being written (a safety rule, and the right one). A vault that
    contains such a link therefore backs up cleanly but stops here — which
    must read as a clear sentence and a half-written folder that gets cleaned
    up, never as a crash report on top of a folder the reader might mistake
    for a finished restore.
    """
    archive = source / f"{PREFIX}{stamp}.tar.gz"
    try:
        with tarfile.open(archive) as tar:
            members = tar.getmembers()
            if hasattr(tarfile, "data_filter"):
                tar.extractall(target, filter="data")
            else:  # pragma: no cover (Python < 3.12 fallback)
                tar.extractall(target)
    except tarfile.TarError as error:
        raise RestoreError(
            f"{archive.name} could not be unpacked: {_one_line(error)}. "
            "Nothing usable was written. Try `verify` on this set, or pick an "
            "older one with --set.") from error
    except OSError as error:
        raise RestoreError(
            f"{archive.name} could not be unpacked: {_one_line(error)}. "
            "This usually means the disk is full or the folder is not "
            "writable.") from error
    return len(members)


def _one_line(error: BaseException) -> str:
    text = str(error).strip() or error.__class__.__name__
    return " ".join(text.split())[:300]


def test_restore(source: Path, stamp: str) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        count = extract_archive(source, stamp, Path(tmp))
    print(f"Test restore succeeded: {count} entries extracted to a temporary "
          "folder and cleaned up. Nothing was changed.")


def restore(source: Path, stamp: str, target: Path, vault: Path) -> None:
    target = target.expanduser()
    resolved_target = target.resolve()
    resolved_vault = vault.resolve()
    if resolved_target == resolved_vault \
            or resolved_vault in resolved_target.parents \
            or resolved_target in resolved_vault.parents:
        raise RestoreError(
            "Refusing to restore into (or over) the live vault. Restore to a "
            "fresh folder, inspect it, then move it into place yourself.")
    if target.exists() and any(target.iterdir()):
        raise RestoreError(f"Refusing to restore into {target}: the folder is "
                           "not empty. This tool never overwrites existing files.")
    created = not target.exists()
    target.mkdir(parents=True, exist_ok=True)
    try:
        count = extract_archive(source, stamp, target)
    except RestoreError:
        # The target was empty or absent when we started, so everything in it
        # is ours. Leaving a half-unpacked vault behind is the one outcome a
        # restore tool must never produce: it looks like a finished restore.
        if created:
            shutil.rmtree(target, ignore_errors=True)
        else:
            for child in target.iterdir():
                if child.is_dir() and not child.is_symlink():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
        raise
    print(f"Restored {count} entries to {target}.")
    bundle = source / f"{PREFIX}{stamp}.bundle"
    if bundle.exists():
        shutil.copy2(bundle, target / bundle.name)
        print(f"Copied {bundle.name} alongside; recover the version history "
              f"with: git clone {bundle.name} restored-history")
    print("Secrets, schedules, and permissions are deliberately not in a "
          "backup; see docs/backup-restore.md for what to re-establish.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify or restore vault backups")
    parser.add_argument("mode", choices=["verify", "test", "restore"])
    parser.add_argument("--set", dest="stamp", help="backup set stamp "
                        "(default: the newest set)")
    parser.add_argument("--source", help="folder holding the backup sets")
    parser.add_argument("--to", help="restore target folder (restore mode)")
    parser.add_argument("--vault", help="vault root (default: VAULT_PATH or "
                                        "this file's own vault)")
    args = parser.parse_args(argv)
    vault = resolve_vault_root(args.vault)
    try:
        source = resolve_source(vault, args.source)
        stamp = pick_set(source, args.stamp)
        print(f"Backup set {stamp} in {source}:")
        try:
            findings = verify_set(source, stamp)
        except RestoreError as error:
            # Being told the newest copy is damaged, with no hint that an
            # intact older one is sitting right there, is the worst possible
            # answer on the day someone actually needs this.
            raise _with_fallback_hint(error, source, stamp) from None
        for finding in findings:
            print(f"  {finding}")
        if args.mode == "test":
            test_restore(source, stamp)
        elif args.mode == "restore":
            if not args.to:
                raise RestoreError("restore mode needs --to <empty folder>")
            restore(source, stamp, Path(args.to), vault)
        return 0
    except RestoreError as error:
        print(f"Stopped: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
