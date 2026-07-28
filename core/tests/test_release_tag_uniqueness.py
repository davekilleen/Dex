"""Regression tests for the one-published-artifact-per-version CI guard."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts/check-release-tag-uniqueness.sh"
REACHABILITY_GATE = REPO_ROOT / "scripts/check-release-tag-reachability.sh"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _repository_with_remote_tags(tmp_path: Path, *tags: str) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )

    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.name", "Dex Tests")
    _git(repository, "config", "user.email", "tests@example.com")
    (repository / "README.md").write_text("# Fixture\n", encoding="utf-8")
    _git(repository, "add", "README.md")
    _git(repository, "commit", "-m", "fixture")
    _git(repository, "remote", "add", "origin", str(remote))

    for tag in tags:
        _git(repository, "tag", "-a", tag, "-m", tag)
    _git(repository, "push", "origin", "main", "--tags")
    return repository


def test_gate_accepts_one_annotated_tag_per_version(tmp_path: Path) -> None:
    repository = _repository_with_remote_tags(
        tmp_path,
        "dist/release/v1.76.1-1111111",
        "dist/release/v1.78.0-2222222",
    )

    result = subprocess.run(
        ["bash", str(GATE)],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_gate_rejects_duplicate_at_old_version(
    tmp_path: Path,
) -> None:
    repository = _repository_with_remote_tags(
        tmp_path,
        "dist/release/v1.76.0-1111111",
        "dist/release/v1.76.0-2222222",
    )

    result = subprocess.run(
        ["bash", str(GATE)],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "v1.76.0 has 2 dist/release tags" in result.stderr
    assert "dist/archive/*" in result.stderr
    assert "git push --tags" in result.stderr
    assert "stale local tags" in result.stderr
    gate_source = GATE.read_text(encoding="utf-8")
    assert "HISTORICAL_VERSION_THRESHOLD" not in gate_source
    assert "version_is_at_or_below_threshold" not in gate_source


def test_gate_reports_every_new_version_with_duplicate_tags(tmp_path: Path) -> None:
    repository = _repository_with_remote_tags(
        tmp_path,
        "dist/release/v1.77.2-1111111",
        "dist/release/v1.77.2-2222222",
        "dist/release/v1.79.0-3333333",
        "dist/release/v1.79.0-4444444",
    )

    result = subprocess.run(
        ["bash", str(GATE)],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "v1.77.2" in result.stderr
    assert "v1.79.0" in result.stderr


def _newer_release_tags(count: int) -> tuple[str, ...]:
    return tuple(
        f"dist/release/v1.{minor}.0-{minor:07x}"
        for minor in range(75, 75 + count)
    )


def test_reachability_gate_passes_below_safety_margin(tmp_path: Path) -> None:
    repository = _repository_with_remote_tags(
        tmp_path,
        *_newer_release_tags(25),
    )

    result = subprocess.run(
        ["bash", str(REACHABILITY_GATE)],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Release-tag reachability gate passed." in result.stdout


@pytest.mark.parametrize("newer_count", (26, 27))
def test_reachability_gate_fails_at_or_above_safety_margin(
    tmp_path: Path,
    newer_count: int,
) -> None:
    repository = _repository_with_remote_tags(
        tmp_path,
        *_newer_release_tags(newer_count),
    )

    result = subprocess.run(
        ["bash", str(REACHABILITY_GATE)],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    for sentinel in ("1.62.0", "1.68.0", "1.74.0"):
        assert (
            f"v{sentinel} has {newer_count} newer dist/release tags"
            in result.stderr
        )
    assert "dist/archive/*" in result.stderr


def test_reachability_gate_fails_loudly_when_remote_tags_are_unreadable(
    tmp_path: Path,
) -> None:
    repository = _repository_with_remote_tags(
        tmp_path,
        "dist/release/v1.79.0-1111111",
    )
    _git(
        repository,
        "remote",
        "set-url",
        "origin",
        str(tmp_path / "missing.git"),
    )

    result = subprocess.run(
        ["bash", str(REACHABILITY_GATE)],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "could not read dist/release tags from origin" in result.stderr
    assert "git ls-remote failed" in result.stderr


def test_reachability_gate_fails_loudly_when_remote_has_no_release_tags(
    tmp_path: Path,
) -> None:
    repository = _repository_with_remote_tags(tmp_path)

    result = subprocess.run(
        ["bash", str(REACHABILITY_GATE)],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "origin returned no readable dist/release tags" in result.stderr
    assert "old-version reachability cannot be verified" in result.stderr


def test_stable_release_ci_publishes_each_version_at_most_once() -> None:
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    )
    quality_steps = workflow["jobs"]["quality"]["steps"]
    assert any(
        step.get("run") == "bash scripts/check-release-tag-uniqueness.sh"
        for step in quality_steps
    )
    assert any(
        step.get("run") == "bash scripts/check-release-tag-reachability.sh"
        for step in quality_steps
    )

    stable_job = workflow["jobs"]["build-release"]
    assert stable_job["outputs"]["release_sha"] == (
        "${{ steps.release_guard.outputs.release_sha || "
        "steps.release_build.outputs.release_sha }}"
    )
    steps = stable_job["steps"]
    named_steps = {step["name"]: step for step in steps if "name" in step}
    guard = named_steps["Check whether this version is already published"]
    assert guard["id"] == "release_guard"
    assert (
        'git ls-remote --tags origin "refs/tags/dist/release/v${VERSION}-*"'
        in guard["run"]
    )
    assert "already_published=true" in guard["run"]
    assert "already_published=false" in guard["run"]
    assert 'echo "release_sha=$RELEASE_SHA"' in guard["run"]
    assert 'PEELED_REF="${PUBLISHED_TAG}^{}"' in guard["run"]
    assert "LC_ALL=C sort" in guard["run"]
    assert "lexicographically first" in guard["run"]

    publish_condition = (
        "steps.release_guard.outputs.already_published != 'true'"
    )
    for step_name in (
        "Build release branch",
        "Push release branch and immutable tag",
        "Build self-contained vault bundle",
        "Upload vault bundle to versioned GitHub Release",
    ):
        assert named_steps[step_name]["if"] == publish_condition

    deploy_health = workflow["jobs"]["deploy-health"]
    assert deploy_health["needs"] == ["quality", "build-release"]
    assert "needs['build-release'].result == 'success'" in deploy_health["if"]
    deploy_steps = {
        step["name"]: step for step in deploy_health["steps"] if "name" in step
    }
    assert (
        deploy_steps["Download release health inputs"]["with"]["name"]
        == "release-health-inputs"
    )
    assert deploy_steps["Build release health page"]["env"]["RELEASE_SHA"] == (
        "${{ needs['build-release'].outputs.release_sha }}"
    )
