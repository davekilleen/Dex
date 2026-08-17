"""Release catalog/source/distribution identity gate at its CLI seam."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GATE = REPO_ROOT / "scripts/check-release-catalog-tag-identity.py"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _identity_repo(tmp_path: Path) -> tuple[Path, str, str, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.name", "Dex Tests")
    _git(repo, "config", "user.email", "tests@example.com")
    (repo / "source.txt").write_text("source\n", encoding="utf-8")
    _git(repo, "add", "source.txt")
    _git(repo, "commit", "--quiet", "-m", "source v9.8.7")
    source_commit = _git(repo, "rev-parse", "HEAD")
    source_tag = "v9.8.7"
    _git(repo, "tag", "-a", source_tag, "-m", source_tag)

    tag_pattern = "dist/release/v9.8.7-<release-commit-prefix>"
    catalog = {
        "catalog_version": 2,
        "release": {
            "version": "9.8.7",
            "channel": "release",
            "immutable_distribution_tag_pattern": tag_pattern,
            "source_commit": source_commit,
        }
    }
    path = repo / "System/.release-catalog.json"
    path.parent.mkdir()
    path.write_text(json.dumps(catalog) + "\n", encoding="utf-8")
    (repo / "source.txt").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "sanitized release")
    release_commit = _git(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "release")
    release_tag = f"dist/release/v9.8.7-{release_commit[:7]}"
    _git(repo, "tag", "-a", release_tag, "-m", release_tag)
    return repo, source_commit, release_commit, release_tag


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), "--repo", str(repo), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def test_catalog_identity_gate_accepts_the_complete_local_loop(tmp_path: Path) -> None:
    repo, source_commit, release_commit, release_tag = _identity_repo(tmp_path)

    result = _run(repo, "--release-ref", "release")

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"v9.8.7 -> {source_commit}" in result.stdout
    assert f"{release_tag} -> {release_commit}" in result.stdout


def test_catalog_identity_gate_accepts_a_release_shaped_candidate_source_ref(
    tmp_path: Path,
) -> None:
    repo, source_commit, release_commit, release_tag = _identity_repo(tmp_path)
    _git(repo, "branch", "candidate", source_commit)
    _git(repo, "tag", "-d", "v9.8.7")

    result = _run(
        repo, "--release-ref", "release", "--source-ref", "candidate"
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"source ref candidate -> {source_commit}" in result.stdout
    assert f"{release_tag} -> {release_commit}" in result.stdout


def test_catalog_identity_gate_rejects_the_wrong_candidate_source_ref(
    tmp_path: Path,
) -> None:
    repo, source_commit, release_commit, _catalog_tag = _identity_repo(tmp_path)
    _git(repo, "branch", "candidate", release_commit)

    result = _run(
        repo, "--release-ref", "release", "--source-ref", "candidate"
    )

    assert result.returncode == 1
    assert (
        f"catalog source_commit {source_commit} does not equal source ref candidate "
        f"{release_commit}"
    ) in result.stderr


def test_catalog_identity_gate_accepts_a_canonical_beta_prerelease(
    tmp_path: Path,
) -> None:
    repo, source_commit, _release_commit, _catalog_tag = _identity_repo(tmp_path)
    catalog = json.loads(
        (repo / "System/.release-catalog.json").read_text(encoding="utf-8")
    )
    beta_pattern = "dist/release-beta/v9.8.7-beta.1-<release-commit-prefix>"
    catalog["release"].update(
        {
            "version": "9.8.7-beta.1",
            "channel": "release-beta",
            "immutable_distribution_tag_pattern": beta_pattern,
        }
    )
    (repo / "System/.release-catalog.json").write_text(
        json.dumps(catalog) + "\n", encoding="utf-8"
    )
    _git(repo, "add", "System/.release-catalog.json")
    _git(repo, "commit", "--quiet", "-m", "beta release catalog")
    release_commit = _git(repo, "rev-parse", "HEAD")
    beta_tag = f"dist/release-beta/v9.8.7-beta.1-{release_commit[:7]}"
    _git(repo, "branch", "release-beta", release_commit)
    _git(repo, "branch", "beta", source_commit)
    _git(repo, "tag", "-a", beta_tag, release_commit, "-m", beta_tag)

    result = _run(
        repo,
        "--release-ref",
        "release-beta",
        "--source-ref",
        "beta",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"source ref beta -> {source_commit}" in result.stdout
    assert f"{beta_tag} -> {release_commit}" in result.stdout


def test_catalog_identity_gate_derives_the_only_allowed_tag_before_minting(
    tmp_path: Path,
) -> None:
    repo, _source_commit, _release_commit, release_tag = _identity_repo(tmp_path)
    _git(repo, "tag", "-d", release_tag)

    result = _run(repo, "--release-ref", "release", "--print-release-tag")

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == f"{release_tag}\n"


def test_catalog_identity_gate_rejects_the_v1_96_2_concrete_tag_promise(
    tmp_path: Path,
) -> None:
    repo, source_commit, _release_commit, _release_tag = _identity_repo(tmp_path)
    catalog_path = repo / "System/.release-catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    catalog["catalog_version"] = 1
    del catalog["release"]["immutable_distribution_tag_pattern"]
    catalog["release"]["immutable_distribution_tag"] = (
        f"dist/release/v9.8.7-{source_commit[:7]}"
    )
    catalog_path.write_text(json.dumps(catalog) + "\n", encoding="utf-8")
    _git(repo, "add", "System/.release-catalog.json")
    _git(repo, "commit", "--quiet", "-m", "repeat concrete catalog promise")
    _git(repo, "branch", "-f", "release", "HEAD")

    result = _run(repo, "--release-ref", "release", "--print-release-tag")

    assert result.returncode == 1
    assert "requires catalog_version 2" in result.stderr


@pytest.mark.parametrize("mutation", ("empty", "duplicate", "missing"))
def test_catalog_identity_gate_rejects_unreadable_local_catalog_observations(
    tmp_path: Path, mutation: str
) -> None:
    repo, _source_commit, _release_commit, _catalog_tag = _identity_repo(tmp_path)
    catalog_path = repo / "System/.release-catalog.json"
    if mutation == "empty":
        catalog_path.write_text("", encoding="utf-8")
        expected = "release catalog observation was empty"
    elif mutation == "duplicate":
        catalog_path.write_text(
            '{"release":{"version":"9.8.7","version":"9.8.8"}}\n',
            encoding="utf-8",
        )
        expected = "release catalog contains duplicate key 'version'"
    else:
        catalog_path.unlink()
        expected = "git show release:System/.release-catalog.json failed"
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", f"{mutation} catalog")
    _git(repo, "branch", "-f", "release", "HEAD")

    result = _run(repo, "--release-ref", "release", "--print-release-tag")

    assert result.returncode == 1
    assert expected in result.stderr


@pytest.mark.parametrize("mutation", ("divergent-suffix", "wrong-release-commit"))
def test_catalog_identity_gate_rejects_minted_tag_mutations(
    tmp_path: Path, mutation: str
) -> None:
    repo, source_commit, release_commit, release_tag = _identity_repo(tmp_path)
    _git(repo, "tag", "-d", release_tag)
    if mutation == "divergent-suffix":
        wrong_tag = f"dist/release/v9.8.7-{source_commit[:7]}"
        _git(repo, "tag", "-a", wrong_tag, release_commit, "-m", wrong_tag)
        expected = f"git cat-file -t {release_tag} failed"
    else:
        _git(repo, "tag", "-a", release_tag, source_commit, "-m", release_tag)
        expected = f"peels to {source_commit}, not release commit {release_commit}"

    result = _run(repo, "--release-ref", "release")

    assert result.returncode == 1
    assert expected in result.stderr


def test_catalog_identity_gate_rejects_source_tag_mismatch(tmp_path: Path) -> None:
    repo, source_commit, _release_commit, _catalog_tag = _identity_repo(tmp_path)
    _git(repo, "tag", "-d", "v9.8.7")
    wrong_source = _git(repo, "rev-parse", "release")
    _git(repo, "tag", "-a", "v9.8.7", wrong_source, "-m", "wrong source")

    result = _run(repo, "--release-ref", "release")

    assert result.returncode == 1
    assert (
        f"catalog source_commit {source_commit} does not equal peeled v9.8.7 {wrong_source}"
        in result.stderr
    )


def test_catalog_identity_gate_rejects_an_annotated_non_commit_source_tag(
    tmp_path: Path,
) -> None:
    repo, _source_commit, _release_commit, _catalog_tag = _identity_repo(tmp_path)
    tree = _git(repo, "rev-parse", "release^{tree}")
    _git(repo, "tag", "-d", "v9.8.7")
    _git(repo, "tag", "-a", "v9.8.7", tree, "-m", "wrong object type")

    result = _run(repo, "--release-ref", "release")

    assert result.returncode == 1
    assert "'v9.8.7' did not peel to a commit" in result.stderr


def test_remote_catalog_identity_gate_rejects_an_empty_tag_observation(
    tmp_path: Path,
) -> None:
    repo, _source_commit, _release_commit, _catalog_tag = _identity_repo(tmp_path)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True)

    result = _run(repo, "--release-ref", "release", "--remote", str(remote))

    assert result.returncode == 1
    assert "remote returned no observation for required tag 'v9.8.7'" in result.stderr


def test_remote_catalog_identity_gate_rejects_a_missing_peeled_observation(
    tmp_path: Path,
) -> None:
    repo, source_commit, _release_commit, _catalog_tag = _identity_repo(tmp_path)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True)
    _git(repo, "push", str(remote), f"{source_commit}:refs/tags/v9.8.7")

    result = _run(repo, "--release-ref", "release", "--remote", str(remote))

    assert result.returncode == 1
    assert "remote did not return annotated and peeled refs for 'v9.8.7'" in result.stderr


def test_remote_catalog_identity_gate_rejects_a_missing_release_tag(
    tmp_path: Path,
) -> None:
    repo, _source_commit, _release_commit, release_tag = _identity_repo(tmp_path)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True)
    _git(repo, "push", str(remote), "refs/tags/v9.8.7")

    result = _run(repo, "--release-ref", "release", "--remote", str(remote))

    assert result.returncode == 1
    assert f"remote returned no observation for required tag {release_tag!r}" in result.stderr


def test_remote_catalog_identity_gate_rejects_the_wrong_peeled_release_commit(
    tmp_path: Path,
) -> None:
    repo, source_commit, release_commit, release_tag = _identity_repo(tmp_path)
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True)
    _git(repo, "tag", "-d", release_tag)
    _git(repo, "tag", "-a", release_tag, source_commit, "-m", release_tag)
    _git(repo, "push", str(remote), "refs/tags/v9.8.7", f"refs/tags/{release_tag}")

    result = _run(repo, "--release-ref", "release", "--remote", str(remote))

    assert result.returncode == 1
    assert f"peels to {source_commit}, not release commit {release_commit}" in result.stderr


def test_remote_tag_parser_rejects_duplicate_observations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("release_identity_gate", GATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    commit = "a" * 40
    monkeypatch.setattr(
        module,
        "_git",
        lambda *_args: (
            f"{commit}\trefs/tags/v9.8.7\n"
            f"{commit}\trefs/tags/v9.8.7\n"
            f"{commit}\trefs/tags/v9.8.7^{{}}"
        ),
    )

    with pytest.raises(module.IdentityError, match="duplicate observation"):
        module._remote_peeled(tmp_path, "origin", "v9.8.7")
