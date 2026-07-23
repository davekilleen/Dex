"""Contract tests for the split-topology no-merge updater."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.update import apply_update

REPO_ROOT = Path(__file__).resolve().parents[2]


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
    _git(release, "config", "user.email", "update@example.com")
    _write(release, "README.md", b"old brain\n")
    _write(
        release,
        "CLAUDE.md",
        b"# Old instructions\n\n## USER_EXTENSIONS_START\n## USER_EXTENSIONS_END\n\nOld footer.\n",
    )
    _write(release, "core/obsolete.py", b"OLD = True\n", 0o755)
    _write(release, "03-Tasks/Tasks.md", b"# shipped seed\n")
    _write(release, "04-Projects/private.md", b"release placeholder\n")
    _write(release, "System/.dex/release-runtime.json", b"{}\n")
    old_tag, old_tag_object, old_commit, old_tree = _commit_release(release, "1.63.0")

    _write(release, "README.md", b"new brain\n")
    _write(
        release,
        "CLAUDE.md",
        b"# New instructions\n\n## USER_EXTENSIONS_START trailing text\r\n"
        b"## USER_EXTENSIONS_END trailing text\r\n\r\nNew footer.\n",
    )
    _write(release, "core/new.py", b"NEW = True\n")
    _write(release, "03-Tasks/Tasks.md", b"# changed shipped seed\n")
    _write(release, "04-Projects/private.md", b"release tried to replace user notes\n")
    _write(release, "System/.dex/release-runtime.json", b'{"new":true}\n')
    (release / "core/obsolete.py").unlink()
    target_tag, target_tag_object, target_commit, target_tree = _commit_release(release, "1.64.0")

    vault = tmp_path / "vault"
    vault.mkdir()
    for relative in (
        "README.md",
        "CLAUDE.md",
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
        "release": release,
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


def _retarget_release(
    fixture: dict[str, object],
    relative: str,
    content: bytes,
    version: str = "1.65.0",
) -> None:
    release = fixture["release"]
    _write(release, relative, content)
    target = _commit_release(release, version)
    _, _, commit, _ = target
    _git(
        fixture["brain"],
        "fetch",
        "--quiet",
        "--tags",
        str(release),
        f"+{commit}:refs/remotes/upstream/release",
    )
    fixture["target"] = target


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
    assert (
        subprocess.run(
            ["git", f"--git-dir={split_release_fixture['brain']}", "rev-parse", "refs/dex/installed"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        == target_commit
    )


def test_apply_update_keeps_personal_instructions_when_release_template_changes(
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    custom = b"Always explain decisions plainly."
    _write(vault, "CLAUDE-custom.md", custom)
    _write(
        vault,
        "CLAUDE.md",
        b"# Old instructions\n\nAlways explain decisions plainly.\n\nOld footer.\n",
    )

    result = apply_update.apply_verified_release(vault, _verified(split_release_fixture))

    assert result["committed"] is True
    assert (vault / "CLAUDE.md").read_bytes() == (
        b"# New instructions\n\nAlways explain decisions plainly.\n\r\nNew footer.\n"
    )
    assert "CLAUDE.md" in result["regenerated"]


@pytest.mark.parametrize(
    "malformed_template",
    [
        b"# Broken release\n\nNo markers.\n",
        b"# Broken release\n\n## USER_EXTENSIONS_END\n## USER_EXTENSIONS_START\n",
        (
            b"## USER_EXTENSIONS_START\n## USER_EXTENSIONS_END\n"
            b"## USER_EXTENSIONS_START\n## USER_EXTENSIONS_END\n"
        ),
    ],
)
def test_malformed_claude_template_is_kept_and_current_file_is_untouched(
    split_release_fixture: dict[str, object],
    malformed_template: bytes,
) -> None:
    vault = split_release_fixture["vault"]
    current = b"# Current instructions\n\nNever lose this personal block.\n"
    _write(vault, "CLAUDE-custom.md", b"Never lose this personal block.\n")
    _write(vault, "CLAUDE.md", current)
    _retarget_release(
        split_release_fixture,
        "CLAUDE.md",
        malformed_template,
    )

    result = apply_update.apply_verified_release(vault, _verified(split_release_fixture))

    assert (vault / "CLAUDE.md").read_bytes() == current
    assert "CLAUDE.md" in result["kept"]
    assert "marker" in result["kept_reasons"]["CLAUDE.md"].lower()


def test_update_plan_compares_current_claude_against_composed_bytes(
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    custom = b"Personal instruction without a trailing newline."
    _write(vault, "CLAUDE-custom.md", custom)
    release = _verified(split_release_fixture)
    release_entry = next(entry for entry in release.entries if entry.path == "CLAUDE.md")
    release_blob = apply_update._blob(vault, release.brain_git, release_entry.object_id)
    _write(vault, "CLAUDE.md", apply_update._regenerate_claude(release_blob, custom))

    plan = apply_update.build_update_plan(vault, release)

    assert "CLAUDE.md" not in {entry.relative for entry in plan.entries}
    assert "CLAUDE.md" not in plan.regenerated
    assert "CLAUDE.md" in plan.untouched


@pytest.mark.parametrize("empty_custom_file", [False, True])
def test_absent_or_empty_custom_instructions_use_release_template_as_is(
    split_release_fixture: dict[str, object],
    empty_custom_file: bool,
) -> None:
    vault = split_release_fixture["vault"]
    if empty_custom_file:
        _write(vault, "CLAUDE-custom.md", b"")
    release = _verified(split_release_fixture)
    release_entry = next(entry for entry in release.entries if entry.path == "CLAUDE.md")
    release_blob = apply_update._blob(vault, release.brain_git, release_entry.object_id)

    apply_update.apply_verified_release(vault, release)

    assert (vault / "CLAUDE.md").read_bytes() == release_blob


@pytest.mark.parametrize("unsafe_custom", ["directory", "symlink"])
def test_non_regular_custom_instructions_keep_current_claude_file(
    split_release_fixture: dict[str, object],
    unsafe_custom: str,
) -> None:
    vault = split_release_fixture["vault"]
    current = (vault / "CLAUDE.md").read_bytes()
    custom = vault / "CLAUDE-custom.md"
    if unsafe_custom == "directory":
        custom.mkdir()
    else:
        _write(vault, "custom-target.md", b"must not be followed\n")
        custom.symlink_to(vault / "custom-target.md")

    result = apply_update.apply_verified_release(vault, _verified(split_release_fixture))

    assert (vault / "CLAUDE.md").read_bytes() == current
    assert result["kept_reasons"]["CLAUDE.md"] == (
        "CLAUDE-custom.md is not a regular file"
    )


def test_unreadable_custom_instructions_keep_current_claude_file(
    monkeypatch: pytest.MonkeyPatch,
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    current = (vault / "CLAUDE.md").read_bytes()
    custom = vault / "CLAUDE-custom.md"
    _write(vault, "CLAUDE-custom.md", b"private instructions\n")
    original_read_bytes = Path.read_bytes

    def unreadable(path: Path) -> bytes:
        if path == custom:
            raise PermissionError("simulated unreadable custom file")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", unreadable)

    result = apply_update.apply_verified_release(vault, _verified(split_release_fixture))

    assert (vault / "CLAUDE.md").read_bytes() == current
    assert result["kept_reasons"]["CLAUDE.md"] == "CLAUDE-custom.md is unreadable"


@pytest.mark.parametrize(
    ("template", "custom"),
    [
        (
            b"# Dex\n\n## USER_EXTENSIONS_START\n## USER_EXTENSIONS_END\nAfter.\n",
            b"",
        ),
        (
            b"# Dex\n\n## USER_EXTENSIONS_START trailing\n## USER_EXTENSIONS_END\nAfter.\n",
            b"Personal instruction.",
        ),
        (
            b"# Dex\r\n\r\n## USER_EXTENSIONS_START\r\n## USER_EXTENSIONS_END\r\nAfter.\r\n",
            b"First.\r\nSecond.\r\n",
        ),
        (
            b"# Dex\n## USER_EXTENSIONS_START\n## USER_EXTENSIONS_END\nAfter.\n",
            b"Text that looks like a marker:\n## USER_EXTENSIONS_END\nKeep it.\n",
        ),
    ],
)
def test_python_claude_regeneration_is_byte_identical_to_cjs(
    template: bytes,
    custom: bytes,
) -> None:
    script = """
const fs = require('fs');
const migrator = require('./core/migrations/v1-to-v2-brain-vault-split.cjs');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const template = Buffer.from(input.template, 'base64').toString('utf8');
const custom = Buffer.from(input.custom, 'base64').toString('utf8');
process.stdout.write(Buffer.from(migrator.regenerateClaude(template, custom), 'utf8'));
"""
    payload = json.dumps(
        {
            "template": base64.b64encode(template).decode("ascii"),
            "custom": base64.b64encode(custom).decode("ascii"),
        }
    ).encode()
    expected = subprocess.run(
        ["node", "-e", script],
        cwd=REPO_ROOT,
        input=payload,
        check=True,
        capture_output=True,
    ).stdout

    assert apply_update._regenerate_claude(template, custom) == expected


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


def test_release_pinning_failure_rolls_back_file_transaction_under_lock(
    monkeypatch: pytest.MonkeyPatch,
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    before_readme = (vault / "README.md").read_bytes()
    before_obsolete = (vault / "core/obsolete.py").read_bytes()
    lock = vault / "System/.dex/mutation.lock"

    def fail_release_pin(*_args: object, **_kwargs: object) -> None:
        assert lock.is_file(), "release identity finalization must run under the transaction lock"
        raise RuntimeError("simulated release pin failure")

    monkeypatch.setattr(apply_update, "_finalize_release_metadata", fail_release_pin)

    with pytest.raises(RuntimeError, match="simulated release pin failure"):
        apply_update.apply_verified_release(vault, _verified(split_release_fixture))

    assert (vault / "README.md").read_bytes() == before_readme
    assert (vault / "core/obsolete.py").read_bytes() == before_obsolete
    assert not (vault / "core/new.py").exists()


def test_crash_between_apply_and_release_identity_finalize_converges(
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    tag, tag_object, target_commit, tree = split_release_fixture["target"]
    _, _, old_commit, _ = split_release_fixture["old"]
    before = {relative: (vault / relative).read_bytes() for relative in ("README.md", "core/obsolete.py")}
    worker = """
import sys
from pathlib import Path
from core.update.apply_update import apply_verified_release, verify_release_ref
vault = Path(sys.argv[1])
release = verify_release_ref(
    vault,
    tag=sys.argv[2],
    tag_object=sys.argv[3],
    commit=sys.argv[4],
    tree=sys.argv[5],
)
apply_verified_release(vault, release)
"""
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            worker,
            str(vault),
            tag,
            tag_object,
            target_commit,
            tree,
        ],
        cwd=REPO_ROOT,
        env=dict(os.environ, DEX_TX_TEST_STOP_AFTER="before-finalize"),
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert process.returncode == 137, process.stderr[-500:]
    outcomes = apply_update.Transaction.resume(vault)

    assert len(outcomes) == 1 and outcomes[0]["resumed"] is True
    assert (vault / "README.md").read_bytes() == before["README.md"]
    assert (vault / "core/obsolete.py").read_bytes() == before["core/obsolete.py"]
    assert not (vault / "core/new.py").exists()
    assert json.loads((vault / "System/.dex/topology.json").read_text())["installedRelease"] == old_commit
    assert json.loads((vault / ".dex/brain.git/dex-brain-v2").read_text())["installed"] == old_commit
    assert _git(vault / ".dex/brain.git", "rev-parse", "refs/dex/installed") == old_commit


def test_update_plan_skips_release_entries_that_already_match_bytes_and_mode(
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    release = _verified(split_release_fixture)
    (vault / "README.md").write_bytes(b"new brain\n")
    (vault / "README.md").chmod(0o644)

    plan = apply_update.build_update_plan(vault, release)

    assert "README.md" not in {entry.relative for entry in plan.entries}
    assert "README.md" not in plan.replaced


def test_apply_update_can_finalize_when_every_release_mutation_already_matches(
    split_release_fixture: dict[str, object],
) -> None:
    vault = split_release_fixture["vault"]
    release = _verified(split_release_fixture)
    for entry in release.entries:
        target = vault / entry.path
        verdict = apply_update.portable_contract.update_write_verdict(
            entry.path,
            exists=target.exists(),
        )
        if not verdict.allowed:
            continue
        content = subprocess.run(
            ["git", f"--git-dir={release.brain_git}", "show", f"{release.commit}:{entry.path}"],
            check=True,
            capture_output=True,
        ).stdout
        _write(vault, entry.path, content, entry.mode)
    (vault / "core/obsolete.py").unlink()

    result = apply_update.apply_verified_release(vault, release)

    assert result["committed"] is True
    assert result["targets"] == []
    assert _git(vault / ".dex/brain.git", "rev-parse", "refs/dex/installed") == release.commit
