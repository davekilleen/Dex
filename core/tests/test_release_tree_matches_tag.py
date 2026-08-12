"""Regression tests for the tag-vs-built CI guard.

On 2026-08-12 a v1.95.0 bundle was built from a tree two commits ahead of the
v1.95.0 tag and attached to the release, because the run at the release commit
failed on a flaky test and a later run built the assets under the old version.
The downstream read-back check could not see it: it compares what was attached
against what was built, and both sides were the same wrong tree. Nothing
compared the tag against the built tree. These tests pin that comparison.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts/check-release-tree-matches-tag.sh"

# The gate waits for the tag to appear on origin, because release.sh pushes main
# first and the tag immediately after. Tests supply the tag up front, so collapse
# the wait rather than paying it.
NO_WAIT = {"RELEASE_TAG_WAIT_ATTEMPTS": "1", "RELEASE_TAG_WAIT_SECONDS": "0"}


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )


def _repository(tmp_path: Path, version: str = "1.95.0") -> tuple[Path, Path]:
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote)], check=True, capture_output=True, text=True
    )
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "Dex Tests")
    _git(repository, "config", "user.email", "tests@example.com")
    (repository / "package.json").write_text(f'{{"version":"{version}"}}\n', encoding="utf-8")
    (repository / "shipped.py").write_text("original\n", encoding="utf-8")
    _git(repository, "add", "package.json", "shipped.py")
    _git(repository, "commit", "-m", "release: v" + version)
    _git(repository, "tag", "-a", f"v{version}", "-m", f"Release v{version}")
    _git(repository, "remote", "add", "origin", str(remote))
    _git(repository, "push", "origin", "main", "--tags")
    return repository, remote


def _run(repository: Path) -> subprocess.CompletedProcess[str]:
    import os

    return subprocess.run(
        ["bash", str(GATE)],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, **NO_WAIT},
    )


def test_gate_passes_when_the_build_runs_on_the_release_commit(tmp_path: Path) -> None:
    repository, _ = _repository(tmp_path)

    result = _run(repository)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "share tree" in result.stdout


def test_gate_rejects_a_build_running_ahead_of_the_tag(tmp_path: Path) -> None:
    """The exact v1.95.0 failure: version says 1.95.0, HEAD is the tag plus commits."""
    repository, _ = _repository(tmp_path)
    (repository / "shipped.py").write_text("changed after the tag\n", encoding="utf-8")
    _git(repository, "add", "shipped.py")
    _git(repository, "commit", "-m", "a merge that landed after the tag was pushed")

    result = _run(repository)

    assert result.returncode == 1
    assert "would label a different tree as 1.95.0" in result.stderr
    # The operator has to be able to see WHICH files would ship wrongly.
    assert "shipped.py" in result.stderr


def test_gate_passes_when_a_later_commit_changed_nothing(tmp_path: Path) -> None:
    """Trees, not commits: identical content under a new commit is safe to publish."""
    repository, _ = _repository(tmp_path)
    _git(repository, "commit", "--allow-empty", "-m", "empty commit after the tag")

    result = _run(repository)

    assert result.returncode == 0, result.stdout + result.stderr


def test_gate_refuses_when_the_version_has_no_tag(tmp_path: Path) -> None:
    """A version nothing can be checked against is not a version worth publishing."""
    repository, _ = _repository(tmp_path)
    (repository / "package.json").write_text('{"version":"9.9.9"}\n', encoding="utf-8")
    _git(repository, "add", "package.json")
    _git(repository, "commit", "-m", "bump without a release tag")

    result = _run(repository)

    assert result.returncode == 1
    assert "no v9.9.9 exists on origin" in result.stderr
