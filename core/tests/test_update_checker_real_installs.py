"""Release-awareness checks against vaults archived from real shipped tags."""

from __future__ import annotations

import io
import json
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.utils.update_verifier import (
    MAX_PROFILE_BYTES,
    PROFILE_PATH,
    STATUS_NONE,
    STATUS_RELEASE,
    EvidenceError,
    UpdateVerifier,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CURRENT_VERSION = json.loads((REPO_ROOT / "package.json").read_text())["version"]


def _git(*args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        check=check,
        capture_output=True,
    )


def _require_tag(tag: str) -> None:
    result = _git("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}", check=False)
    if result.returncode != 0:
        pytest.skip(f"required shipped git tag {tag} is unavailable")


def _archive_tag(tag: str, destination: Path) -> Path:
    _require_tag(tag)
    archive = _git("archive", "--format=tar", tag).stdout
    destination.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as release:
        release.extractall(destination, filter="data")
    return destination


def _real_distribution_remote(tmp_path: Path, version: str) -> Path:
    pattern = f"dist/release/v{version}-*"
    tags = _git("tag", "--list", pattern).stdout.decode().splitlines()
    if not tags:
        pytest.skip(f"required shipped distribution tag matching {pattern} is unavailable")

    tag = sorted(tags)[0]
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(remote),
            "fetch",
            "--quiet",
            "--no-tags",
            str(REPO_ROOT),
            f"+refs/tags/{tag}:refs/tags/{tag}",
        ],
        check=True,
    )
    return remote


def _verifier(vault: Path, remote: Path, state: Path) -> UpdateVerifier:
    return UpdateVerifier(
        vault,
        state_root=state,
        remote_url=str(remote),
        allow_test_transport=True,
        now=lambda: datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
        wall_clock_seconds=3600.0,
    )


@pytest.mark.parametrize(
    ("installed_version", "expected_status", "expected_notification"),
    [
        ("1.61.0", STATUS_RELEASE, True),
        ("1.62.0", STATUS_RELEASE, True),
        (CURRENT_VERSION, STATUS_NONE, False),
    ],
)
def test_real_shipped_install_can_complete_release_awareness(
    tmp_path: Path,
    installed_version: str,
    expected_status: str,
    expected_notification: bool,
) -> None:
    vault = _archive_tag(f"v{installed_version}", tmp_path / "vault")
    remote = _real_distribution_remote(tmp_path, CURRENT_VERSION)

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result["status"] == expected_status
    assert result["should_notify"] is expected_notification
    assert result.get("reason") != "evidence-invalid"
    assert result["current_version"] == installed_version


def test_real_pre_profile_install_is_absent_not_damaged(tmp_path: Path) -> None:
    vault = _archive_tag("v1.61.0", tmp_path / "vault")
    remote = _real_distribution_remote(tmp_path, CURRENT_VERSION)

    assert not (vault / PROFILE_PATH).exists()
    assert _verifier(vault, remote, tmp_path / "state")._current_version() == "1.61.0"


def test_modern_install_still_requires_its_shipped_profile(tmp_path: Path) -> None:
    vault = _archive_tag("v1.62.0", tmp_path / "vault")
    (vault / PROFILE_PATH).unlink()
    remote = _real_distribution_remote(tmp_path, CURRENT_VERSION)

    with pytest.raises(EvidenceError):
        _verifier(vault, remote, tmp_path / "state")._current_version()


@pytest.mark.parametrize(
    "profile_kind",
    ["directory", "oversized", "symlink", "unreadable"],
)
def test_pre_profile_non_regular_or_unreadable_profile_is_not_treated_as_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile_kind: str,
) -> None:
    vault = _archive_tag("v1.61.0", tmp_path / "vault")
    profile = vault / PROFILE_PATH
    profile.parent.mkdir(parents=True, exist_ok=True)
    if profile_kind == "directory":
        profile.mkdir()
    elif profile_kind == "oversized":
        profile.write_bytes(b"x" * (MAX_PROFILE_BYTES + 1))
    elif profile_kind == "symlink":
        profile.symlink_to(vault / "missing-profile.json")
    else:
        profile.write_text("{}")
        original_read_bytes = Path.read_bytes

        def unreadable(path: Path) -> bytes:
            if path == profile:
                raise PermissionError("profile cannot be read")
            return original_read_bytes(path)

        monkeypatch.setattr(Path, "read_bytes", unreadable)
    remote = _real_distribution_remote(tmp_path, CURRENT_VERSION)

    with pytest.raises(EvidenceError):
        _verifier(vault, remote, tmp_path / "state")._current_version()
