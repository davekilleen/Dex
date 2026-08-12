#!/usr/bin/env python3
"""Dex vault backup engine: pluggable backends, verifiable history, tiered retention.

Answers issue #363: after the brain/vault topology split a user's private
vault exists on exactly one machine, and the only implied recovery posture
is a private git remote, which is the wrong answer for Dex's non-technical
audience. This engine archives the vault to any synced folder (OneDrive,
iCloud Drive, Dropbox, a NAS mount) or, via rclone, to any of rclone's
cloud remotes.

Backends (config: System/integrations/config.yaml -> backup.backend):
  folder   (default) any local or cloud-synced directory. Zero dependencies.
  rclone   any rclone remote (S3, B2, Google Drive, ...). Requires the
           rclone binary and a configured remote; fails honestly if absent.

Each run produces a set of three files:
  dex-vault-<stamp>.tar.gz    working-tree archive (secrets excluded)
  dex-vault-<stamp>.bundle    git bundle of the vault history, checked with
                              `git bundle verify` (cryptographic proof of
                              restorability that a tar cannot give)
  dex-vault-<stamp>.sha256    checksums for both, so damage in storage is
                              detectable

Retention is grandfather-father-son: keep the newest N daily, N weekly (one
per ISO week), N monthly (one per month). The newest set is never deleted,
and a file whose name the engine does not recognise is never deleted.
Legacy retention_days config is still honoured if the new block is absent.

Design requirement, paid for by a real failure: a scheduled backup on a
production vault died silently for ten days and nothing noticed. So every
run (success or failure) writes System/.dex/backup-last-run.json, and the
/dex-doctor backup.freshness check reads it. Scheduled runs get a bare
environment (launchd strips PATH), so this module is stdlib-only, resolves
the vault without importing anything, and degrades to a minimal built-in
config parser when PyYAML is unavailable rather than dying silently.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

PREFIX = "dex-vault-"
ARCNAME = "dex-vault"

# The restore runbook has to be readable on a bare machine, so a copy travels
# inside every archive. It is not shipped into the vault at that location,
# though: an update refuses any released path the installed version's ownership
# contract cannot classify, and no released version before this one has a rule
# for System/backup/. Shipping it there stranded every existing install on the
# release that introduced it. It therefore lives under docs/ - which every
# released contract already classifies - and is written into the archive here.
RUNBOOK_SOURCE = "docs/backup-restore.md"
RUNBOOK_IN_ARCHIVE = "System/backup/RESTORE.md"
STAMP_FORMAT = "%Y%m%d-%H%M%S"

# Secrets and generated credential config: never leaves the machine.
# Matched against the exact vault-relative path.
ANCHORED_EXCLUDES = frozenset({
    ".env",
    ".env.local",
    ".mcp.json",
    "System/credentials",
    ".claude/worktrees",
    "System/backup/backup.log",
    "System/backup/backup-job.log",
})

# Secret shapes, matched against any path segment as a glob. These mirror the
# secret entries of core.portable_contract.HARD_DENY_PATTERNS, which is the
# repo's authority on what counts as a credential. The list is duplicated
# rather than imported on purpose: this module stays stdlib-only so a launchd
# run with a bare environment cannot die on an import. The duplication is held
# honest by test_backup_excludes_everything_the_contract_hard_denies, which
# fails if a new deny pattern is added without updating this set.
#
# .git is hard-denied for write-safety, not secrecy, and stays in the archive:
# restoring a working repository is the point.
GLOB_EXCLUDES = (
    ".env",
    ".env.*",
    "*token.json",
    "*.key",
    "*.pem",
)

# Regenerable bulk and platform noise: matched against any path segment.
SEGMENT_EXCLUDES = frozenset({
    ".venv",
    "venv",
    ".testenv",
    "node_modules",
    "__pycache__",
    ".DS_Store",
})


def resolve_vault_root(override: str | os.PathLike | None = None) -> Path:
    """Resolve the vault root without importing anything.

    Order matches the core.paths convention: an explicit override, then the
    VAULT_PATH environment variable, then this file's own location
    (<vault>/core/backup/backup_vault.py). The last rung matters because
    launchd runs jobs with a bare environment.
    """
    if override:
        return Path(override).expanduser().resolve()
    configured = os.environ.get("VAULT_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2]


def config_path(vault: Path) -> Path:
    return vault / "System" / "integrations" / "config.yaml"


def log_path(vault: Path) -> Path:
    return vault / "System" / "backup" / "backup.log"


def stamp_path(vault: Path) -> Path:
    return vault / "System" / ".dex" / "backup-last-run.json"


def log(vault: Path, line: str) -> None:
    target = log_path(vault)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as handle:
        handle.write(f"{datetime.now():%F %T} {line}\n")


def parse_backup_block_without_yaml(text: str) -> dict:
    """Minimal parser for the flat backup block when PyYAML is unavailable.

    Scheduled runs execute under launchd with a bare environment where the
    interpreter may lack PyYAML. A backup that dies on an import error is a
    silent failure; this fallback understands exactly the shape /backup-setup
    writes (scalar keys plus one nested retention mapping) and nothing more.
    """
    block: dict = {}
    in_block = False
    current: dict | None = None
    for raw_line in text.splitlines():
        stripped = raw_line.split("#", 1)[0].rstrip()
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip())
        if not in_block:
            if stripped == "backup:":
                in_block = True
            continue
        if indent == 0:
            break
        key, _, value = stripped.strip().partition(":")
        key = key.strip()
        value = value.strip().strip("'\"")
        if indent == 2:
            if not value:
                current = {}
                block[key] = current
            else:
                current = None
                block[key] = value
        elif indent >= 4 and current is not None:
            current[key] = value
    return block


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "yes", "on", "1"}


def load_config(vault: Path) -> dict:
    """Load and normalise the backup block from the integrations config.

    A parse error raises so the failure is stamped loudly by main();
    a missing file or missing block yields defaults, which fail later with
    a clear "destination is not set" error rather than a vague one.
    """
    path = config_path(vault)
    raw: dict = {}
    if path.exists():
        text = path.read_text()
        try:
            import yaml
        except ImportError:
            raw = parse_backup_block_without_yaml(text)
        else:
            parsed = yaml.safe_load(text) or {}
            raw = parsed.get("backup") or {} if isinstance(parsed, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    retention = raw.get("retention") or {}
    if not isinstance(retention, dict):
        retention = {}
    if not retention and raw.get("retention_days"):
        retention = {"daily": int(raw["retention_days"]), "weekly": 0, "monthly": 0}
    return {
        "enabled": _as_bool(raw.get("enabled", False)),
        "backend": str(raw.get("backend", "folder")),
        "destination": str(raw.get("destination") or ""),
        "remote": str(raw.get("remote") or ""),
        "retention": {
            "daily": int(retention.get("daily", 7)),
            "weekly": int(retention.get("weekly", 4)),
            "monthly": int(retention.get("monthly", 3)),
        },
    }


def excluded(relative: str) -> bool:
    """Return whether a vault-relative path stays out of the archive."""
    if any(rel == relative or relative.startswith(rel + "/")
           for rel in ANCHORED_EXCLUDES):
        return True
    parts = Path(relative).parts
    if any(part in SEGMENT_EXCLUDES for part in parts):
        return True
    return any(fnmatch(part, pattern)
               for part in parts for pattern in GLOB_EXCLUDES)


def _tar_filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
    relative = "/".join(Path(tarinfo.name).parts[1:])  # drop the arcname
    if relative == RUNBOOK_IN_ARCHIVE:
        # A vault restored from an older backup still has a copy here. Drop it
        # so the walk cannot add a second member under the same name; the copy
        # written from RUNBOOK_SOURCE below is the authoritative one.
        return None
    return None if relative and excluded(relative) else tarinfo


def escapes_vault(tarinfo: tarfile.TarInfo) -> bool:
    """Is this a shortcut-style linked file pointing outside the vault?

    Unpacking refuses these, correctly: following one would write outside the
    folder being restored. But the refusal lands at restore time, which is the
    worst moment to learn it. Detecting it while the backup is being taken is
    what makes "this backup can be restored" an honest claim.
    """
    if not (tarinfo.issym() or tarinfo.islnk()):
        return False
    link = PurePosixPath(tarinfo.linkname)
    if link.is_absolute():
        return True
    base = PurePosixPath(tarinfo.name).parent
    depth = 0
    for part in (base / link).parts:
        if part == "..":
            depth -= 1
            if depth < 0:
                return True
        elif part != ".":
            depth += 1
    return False


def _collecting_tar_filter(escaping: list[str]):
    """The exclusion filter, plus a record of links that cannot be unpacked."""
    def apply(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo | None:
        kept = _tar_filter(tarinfo)
        if kept is not None and escapes_vault(kept):
            escaping.append("/".join(Path(kept.name).parts[1:]))
        return kept
    return apply


def file_digest(path: Path) -> str:
    """SHA-256 of a file, read in chunks.

    Reading a whole artifact into memory to hash it costs as much RAM as the
    vault is large, which turns a big vault's backup into an out-of-memory
    failure. Everything here streams instead.
    """
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _add_runbook(tar: tarfile.TarFile, vault: Path,
                 warnings: list[str] | None = None) -> None:
    """Write the restore runbook into the archive at its bare-machine location.

    Read from the vault's own copy rather than embedded here, so there is one
    source of truth for the text. A vault too old to carry it still gets a
    backup - the notes are what matter - but says so, because a set whose
    runbook is missing is a set someone will open on a dead machine.
    """
    source = vault / RUNBOOK_SOURCE
    try:
        payload = source.read_bytes()
        modified = int(source.stat().st_mtime)
    except OSError:
        if warnings is not None:
            warnings.append(
                f"this backup has no restore runbook inside it: {RUNBOOK_SOURCE} "
                "is missing from the vault, so the archive carries the notes but "
                "not the instructions for rebuilding from them")
        return
    info = tarfile.TarInfo(f"{ARCNAME}/{RUNBOOK_IN_ARCHIVE}")
    info.size = len(payload)
    info.mtime = modified
    info.mode = 0o644
    tar.addfile(info, io.BytesIO(payload))


def build_artifacts(vault: Path, workdir: Path, stamp: str,
                    warnings: list[str] | None = None) -> list[Path]:
    """Build the archive, the verified git bundle, and the checksum sidecar.

    The notes archive is the irreplaceable part. A failure to bundle the
    version history therefore degrades to an archive-only set with a recorded
    warning, instead of aborting the run and storing nothing at all: a vault
    whose git repository has no commits yet, or is damaged, would otherwise
    get no backup whatsoever. An unverified bundle is never shipped.
    """
    archive = workdir / f"{PREFIX}{stamp}.tar.gz"
    escaping: list[str] = []
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(vault, arcname=ARCNAME, filter=_collecting_tar_filter(escaping))
        _add_runbook(tar, vault, warnings)
    if escaping and warnings is not None:
        shown = ", ".join(sorted(escaping)[:5])
        warnings.append(
            f"{len(escaping)} linked file(s) in the vault point outside it and "
            f"cannot be unpacked by the restore tool ({shown}); replace them "
            "with real files or links inside the vault, then back up again")
    with tarfile.open(archive) as tar:  # integrity: must be listable
        tar.getmembers()

    artifacts = [archive]
    if (vault / ".git").is_dir():
        bundle = workdir / f"{PREFIX}{stamp}.bundle"
        try:
            subprocess.run(["git", "-C", str(vault), "bundle", "create",
                            str(bundle), "--all"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(vault), "bundle", "verify",
                            str(bundle)], check=True, capture_output=True)
        except (subprocess.CalledProcessError, OSError) as error:
            detail = getattr(error, "stderr", b"") or b""
            if isinstance(detail, bytes):
                detail = detail.decode("utf-8", "replace")
            reason = (detail.strip() or str(error)).splitlines()[-1][:200] \
                if (detail.strip() or str(error)) else error.__class__.__name__
            bundle.unlink(missing_ok=True)  # never ship an unverified bundle
            if warnings is not None:
                warnings.append(
                    "the vault's version history could not be bundled, so this "
                    f"set holds the notes archive only: {reason}")
        else:
            artifacts.append(bundle)

    sums = workdir / f"{PREFIX}{stamp}.sha256"
    lines = [f"{file_digest(a)}  {a.name}" for a in artifacts]
    sums.write_text("\n".join(lines) + "\n")
    artifacts.append(sums)
    return artifacts


# --- backends ---------------------------------------------------------------

class FolderBackend:
    """Any directory: a synced folder, a mounted disk, a NAS share."""

    def __init__(self, config: dict):
        if not config["destination"]:
            raise RuntimeError("backup.destination is not set; run /backup-setup")
        self.dest = Path(config["destination"]).expanduser()
        self.dest.mkdir(parents=True, exist_ok=True)

    def store(self, artifacts: list[Path]) -> str:
        """Copy each artifact in, via a .partial name renamed on completion.

        A run that dies mid-copy (a full disk, a sync folder that went away)
        must not leave its half-written file behind: unswept, those accumulate
        in the destination on every retry and quietly consume the storage the
        backups depend on. Streaming the copy also keeps memory flat.
        """
        partials: list[tuple[Path, Path]] = []
        try:
            for artifact in artifacts:  # phase 1: copy everything aside
                partial = self.dest / (artifact.name + ".partial")
                partials.append((partial, self.dest / artifact.name))
                with artifact.open("rb") as src, partial.open("wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                    dst.flush()
                    os.fsync(dst.fileno())
        except BaseException:
            # Nothing has been published yet, so an earlier set that is already
            # sitting in this folder stays exactly as it was.
            for partial, _final in partials:
                partial.unlink(missing_ok=True)
            raise
        for partial, final in partials:  # phase 2: publish
            partial.rename(final)
        return str(self.dest)

    def list_sets(self) -> list[str]:
        stamps = {p.name[len(PREFIX):-len(".tar.gz")]
                  for p in self.dest.glob(f"{PREFIX}*.tar.gz")}
        return sorted(stamps, reverse=True)

    def delete_set(self, stamp: str) -> None:
        for p in self.dest.glob(f"{PREFIX}{stamp}.*"):
            p.unlink()


class RcloneBackend:
    """Any rclone remote. Fails honestly when rclone is absent."""

    def __init__(self, config: dict):
        self.remote = config["remote"]
        if not self.remote:
            raise RuntimeError("backup.remote is not set for the rclone backend; run /backup-setup")
        try:
            probe = subprocess.run(["rclone", "version"], capture_output=True)
        except FileNotFoundError:
            raise RuntimeError("the rclone tool is not installed or not on PATH") from None
        if probe.returncode != 0:
            raise RuntimeError("the rclone tool is present but not working")

    def store(self, artifacts: list[Path]) -> str:
        for artifact in artifacts:
            subprocess.run(["rclone", "copyto", str(artifact),
                            f"{self.remote}/{artifact.name}"],
                           check=True, capture_output=True)
        return self.remote

    def list_sets(self) -> list[str]:
        out = subprocess.run(["rclone", "lsf", self.remote],
                             check=True, capture_output=True, text=True).stdout
        stamps = {line.strip()[len(PREFIX):-len(".tar.gz")]
                  for line in out.splitlines()
                  if line.strip().startswith(PREFIX)
                  and line.strip().endswith(".tar.gz")}
        return sorted(stamps, reverse=True)

    def delete_set(self, stamp: str) -> None:
        subprocess.run(["rclone", "delete", self.remote,
                        "--include", f"{PREFIX}{stamp}.*"],
                       check=True, capture_output=True)


BACKENDS = {"folder": FolderBackend, "rclone": RcloneBackend}


# --- grandfather-father-son retention ---------------------------------------

def prune(backend, retention: dict) -> list[str]:
    """Delete sets outside the retention ladder; return the pruned stamps.

    Safety rules: the newest set is never deleted, and a stamp that does not
    parse as a timestamp is never deleted (an unrecognised file must not be
    treated as expendable).
    """
    stamps = backend.list_sets()  # newest first
    keep: set[str] = set()
    seen_days: list[str] = []
    seen_weeks: list[str] = []
    seen_months: list[str] = []
    for stamp in stamps:  # newest first: first stamp per period wins
        try:
            when = datetime.strptime(stamp, STAMP_FORMAT)
        except ValueError:
            keep.add(stamp)  # unrecognised: never delete
            continue
        day = f"{when:%Y%m%d}"
        week = f"{when.isocalendar().year}-{when.isocalendar().week}"
        month = f"{when:%Y%m}"
        if day not in seen_days and len(seen_days) < retention["daily"]:
            seen_days.append(day)
            keep.add(stamp)
        if week not in seen_weeks and len(seen_weeks) < retention["weekly"]:
            seen_weeks.append(week)
            keep.add(stamp)
        if month not in seen_months and len(seen_months) < retention["monthly"]:
            seen_months.append(month)
            keep.add(stamp)
    if stamps:
        keep.add(stamps[0])  # never delete the newest set
    pruned = [s for s in stamps if s not in keep]
    for stamp in pruned:
        backend.delete_set(stamp)
    return pruned


def write_stamp(vault: Path, ok: bool, detail: dict) -> None:
    """Record the outcome of every run, success or failure, for /dex-doctor."""
    target = stamp_path(vault)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
               "ok": ok, **detail}
    target.write_text(json.dumps(payload, indent=2) + "\n")


def run_backup(vault: Path) -> int:
    stamp = f"{datetime.now():{STAMP_FORMAT}}"
    config: dict = {}
    try:
        config = load_config(vault)
        backend_cls = BACKENDS.get(config["backend"])
        if backend_cls is None:
            raise RuntimeError(f"unknown backup backend: {config['backend']!r}")
        backend = backend_cls(config)
        warnings: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            artifacts = build_artifacts(vault, Path(tmp), stamp, warnings)
            sizes = {a.name: a.stat().st_size for a in artifacts}
            location = backend.store(artifacts)
        pruned = prune(backend, config["retention"])
        total_mb = sum(sizes.values()) / 1_048_576
        log(vault, f"OK {config['backend']}:{location} set {stamp} "
                   f"({total_mb:.0f}M, {len(sizes)} files"
                   + (f", pruned {len(pruned)} sets" if pruned else "") + ")")
        for warning in warnings:  # a degraded set is never silently "OK"
            log(vault, f"WARNING {warning}")
        write_stamp(vault, True, {"backend": config["backend"],
                                  "location": location, "set": stamp,
                                  "bytes": sum(sizes.values()),
                                  "pruned": pruned,
                                  "warnings": warnings})
        return 0
    except Exception as error:  # any failure must be loud and stamped
        message = str(error)[:500] or error.__class__.__name__
        try:
            log(vault, f"FAILED {message}")
        except OSError:
            pass
        write_stamp(vault, False, {"backend": config.get("backend"),
                                   "error": message})
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Back up the Dex vault")
    parser.add_argument("--vault", help="vault root (default: VAULT_PATH or "
                                        "this file's own vault)")
    args = parser.parse_args(argv)
    return run_backup(resolve_vault_root(args.vault))


if __name__ == "__main__":
    sys.exit(main())
