"""Contract tests for the split-topology no-merge updater."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from core.update import apply_update


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write(root: Path, relative: str, content: bytes, mode: int = 0o644) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    target.chmod(mode)


def _refresh_manifest(release: Path) -> None:
    manifest = release / "System/.installed-files.manifest"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_bytes(b"")
    paths = sorted(
        candidate.relative_to(release).as_posix()
        for candidate in release.rglob("*")
        if candidate.is_file() and ".git" not in candidate.relative_to(release).parts
    )
    manifest.write_text("".join(f"{relative}\n" for relative in paths), encoding="utf-8")


def _commit_release(release: Path, version: str) -> tuple[str, str, str, str]:
    package = release / "package.json"
    package.write_text(json.dumps({"name": "dex-test", "version": version}) + "\n")
    _refresh_manifest(release)
    _git(release, "add", "-A")
    _git(release, "commit", "--quiet", "-m", f"release {version}")
    commit = _git(release, "rev-parse", "HEAD")
    tree = _git(release, "rev-parse", "HEAD^{tree}")
    tag = f"dist/release/v{version}-{commit[:7]}"
    _git(release, "tag", "-a", tag, "-m", f"Dex {version}")
    tag_object = _git(release, "rev-parse", f"refs/tags/{tag}")
    return tag, tag_object, commit, tree


@pytest.fixture
def split_release_fixture(tmp_path: Path) -> dict[str, object]:
    release = tmp_path / "release"
    release.mkdir()
    _git(release, "init", "--quiet")
    _git(release, "config", "user.name", "Dex Update Tests")
    _git(release, "config", "user.email", "update@example.test")
    _write(release, "README.md", b"old brain\n")
    _write(release, "core/obsolete.py", b"OLD = True\n", 0o755)
    _write(release, "03-Tasks/Tasks.md", b"# shipped seed\n")
    _write(release, "04-Projects/private.md", b"release placeholder\n")
    _write(release, "System/.dex/release-runtime.json", b"{}\n")
    old_tag, old_tag_object, old_commit, old_tree = _commit_release(release, "1.63.0")

    _write(release, "README.md", b"new brain\n")
    _write(release, "core/new.py", b"NEW = True\n")
    _write(release, "03-Tasks/Tasks.md", b"# changed shipped seed\n")
    _write(release, "04-Projects/private.md", b"release tried to replace user notes\n")
    _write(release, "System/.dex/release-runtime.json", b'{"new":true}\n')
    (release / "core/obsolete.py").unlink()
    target_tag, target_tag_object, target_commit, target_tree = _commit_release(
        release, "1.64.0"
    )

    vault = tmp_path / "vault"
    vault.mkdir()
    for relative in (
        "README.md",
        "core/obsolete.py",
        "03-Tasks/Tasks.md",
        "04-Projects/private.md",
        "System/.dex/release-runtime.json",
    ):
        raw = subprocess.run(
            ["git", "-C", str(release), "show", f"{old_commit}:{relative}"],
            check=True,
            capture_output=True,
        ).stdout
        _write(vault, relative, raw, 0o755 if relative == "core/obsolete.py" else 0o644)
    _write(vault, "03-Tasks/Tasks.md", b"# user's edited tasks\n")
    _write(vault, "04-Projects/private.md", b"private user bytes\n")
    _write(vault, "System/.dex/release-runtime.json", b'{"local":true}\n')
    _write(vault, "System/user-profile.yaml", b"updates:\n  channel: stable\n")

    brain = vault / ".dex/brain.git"
    brain.parent.mkdir(parents=True)
    _git(vault, "init", "--bare", "--quiet", str(brain))
    subprocess.run(
        [
            "git",
            f"--git-dir={brain}",
            "fetch",
            "--quiet",
            "--tags",
            str(release),
            f"+{old_commit}:refs/dex/installed",
            f"+{target_commit}:refs/remotes/upstream/release",
        ],
        check=True,
    )
    subprocess.run(
        ["git", f"--git-dir={brain}", "remote", "add", "origin", "https://github.com/davekilleen/Dex.git"],
        check=True,
    )
    _write(vault, ".git/dex-vault-v2", b'{"role":"vault"}\n')
    _write(
        vault,
        ".dex/brain.git/dex-brain-v2",
        (json.dumps({"role": "brain", "installed": old_commit}) + "\n").encode(),
    )
    _write(
        vault,
        "System/.dex/topology.json",
        (
            json.dumps(
                {
                    "topology": "brain-vault-split",
                    "vaultGitDir": ".git",
                    "brainGitDir": ".dex/brain.git",
                    "installedRelease": old_commit,
                    "environment": {"DEX_VAULT": str(vault.resolve())},
                }
            )
            + "\n"
        ).encode(),
    )
    return {
        "vault": vault,
        "brain": brain,
        "old": (old_tag, old_tag_object, old_commit, old_tree),
        "target": (target_tag, target_tag_object, target_commit, target_tree),
    }


def _verified(fixture: dict[str, object]) -> apply_update.VerifiedReleaseRef:
    tag, tag_object, commit, tree = fixture["target"]
    return apply_update.verify_release_ref(
        fixture["vault"],
        tag=tag,
        tag_object=tag_object,
        commit=commit,
        tree=tree,
    )


def test_verified_release_is_pinned_to_immutable_tag_and_channel(
    split_release_fixture: dict[str, object],
) -> None:
    release = _verified(split_release_fixture)

    assert release.tag.startswith("dist/release/v1.64.0-")
    assert release.channel == "stable"

    tag, tag_object, commit, tree = split_release_fixture["target"]
    with pytest.raises(apply_update.ReleaseVerificationError, match="tag object"):
        apply_update.verify_release_ref(
            split_release_fixture["vault"],
            tag=tag,
            tag_object="0" * len(tag_object),
            commit=commit,
            tree=tree,
        )


def test_apply_update_replaces_brain_prunes_unchanged_and_preserves_user_owned_paths(
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    release = _verified(split_release_fixture)

    result = apply_update.apply_verified_release(vault, release)

    assert result["committed"] is True
    assert (vault / "README.md").read_bytes() == b"new brain\n"
    assert (vault / "core/new.py").read_bytes() == b"NEW = True\n"
    assert not (vault / "core/obsolete.py").exists()
    assert (vault / "03-Tasks/Tasks.md").read_bytes() == b"# user's edited tasks\n"
    assert (vault / "04-Projects/private.md").read_bytes() == b"private user bytes\n"
    assert (vault / "System/.dex/release-runtime.json").read_bytes() == b'{"local":true}\n'
    _, _, target_commit, _ = split_release_fixture["target"]
    topology = json.loads((vault / "System/.dex/topology.json").read_text())
    marker = json.loads((vault / ".dex/brain.git/dex-brain-v2").read_text())
    assert topology["installedRelease"] == target_commit
    assert marker["installed"] == target_commit
    assert subprocess.run(
        ["git", f"--git-dir={split_release_fixture['brain']}", "rev-parse", "refs/dex/installed"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == target_commit


def test_apply_update_verification_failure_restores_every_release_file(
    monkeypatch: pytest.MonkeyPatch,
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    before = {
        relative: (vault / relative).read_bytes()
        for relative in (
            "README.md",
            "core/obsolete.py",
            "03-Tasks/Tasks.md",
            "04-Projects/private.md",
            "System/.dex/release-runtime.json",
        )
    }
    original_verify = apply_update.Transaction._verify_phase

    def fail_after_verify(transaction: apply_update.Transaction) -> None:
        original_verify(transaction)
        raise RuntimeError("simulated final verification failure")

    monkeypatch.setattr(apply_update.Transaction, "_verify_phase", fail_after_verify)

    with pytest.raises(RuntimeError, match="simulated final verification"):
        apply_update.apply_verified_release(vault, _verified(split_release_fixture))

    for relative, content in before.items():
        assert (vault / relative).read_bytes() == content
    assert not (vault / "core/new.py").exists()
    _, _, old_commit, _ = split_release_fixture["old"]
    assert json.loads((vault / "System/.dex/topology.json").read_text())["installedRelease"] == old_commit


def test_release_pinning_failure_rolls_back_the_committed_file_transaction(
    monkeypatch: pytest.MonkeyPatch,
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    before_readme = (vault / "README.md").read_bytes()
    before_obsolete = (vault / "core/obsolete.py").read_bytes()

    def fail_release_pin(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated release pin failure")

    monkeypatch.setattr(apply_update, "_finalize_release_metadata", fail_release_pin)

    with pytest.raises(RuntimeError, match="simulated release pin failure"):
        apply_update.apply_verified_release(vault, _verified(split_release_fixture))

    assert (vault / "README.md").read_bytes() == before_readme
    assert (vault / "core/obsolete.py").read_bytes() == before_obsolete
    assert not (vault / "core/new.py").exists()
