"""Adversarial release-awareness tests using only local synthetic Git remotes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.mcp import update_checker as update_checker_module
from core.utils import update_verifier as update_verifier_module
from core.utils.update_verifier import (
    ALLOWED_SIGNERS_PATH,
    CATALOG_PATH,
    MANIFEST_PATH,
    PROFILE_PATH,
    STATUS_IDENTITY,
    STATUS_NONE,
    STATUS_OFFLINE,
    STATUS_RELEASE,
    STATUS_SKIPPED,
    STATUS_UNKNOWN,
    STATUS_UP_TO_DATE,
    CancelledError,
    CompatibilityArtifact,
    EvidenceError,
    GitRunner,
    OfflineError,
    ReleaseEvidenceProfile,
    TransientHttpRejectionError,
    UpdateVerifier,
    canonical_profile_bytes,
    legacy_profile_bytes,
    load_allowed_signers,
    parse_profile,
    prove_latest_release,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

APPROVED_NOTICE_AVAILABLE = "A newer version of Dex is available:"
APPROVED_NOTICE_GUIDANCE = (
    "Run /dex-update when you're ready — Dex never updates itself without you."
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()


def _init_repo(path: Path) -> None:
    path.mkdir()
    _git(path, "init", "--quiet")
    _git(path, "config", "user.name", "Dex Evidence Tests")
    _git(path, "config", "user.email", "evidence@example.com")


def _installed_vault(path: Path, version: str = "1.61.0") -> Path:
    _init_repo(path)
    _write(path / "package.json", _canonical({"name": "dex", "version": version}))
    _write(path / PROFILE_PATH, legacy_profile_bytes(version))
    _git(path, "add", ".")
    _git(path, "commit", "--quiet", "-m", "installed release")
    return path


def _release(
    repo: Path,
    version: str,
    *,
    profile_name: str = "legacy-v1",
    profile_raw: bytes | None = None,
    package_version: str | None = None,
    manifest_mutator=None,
    lightweight: bool = False,
    tag_suffix: str | None = None,
    catalog_raw_override: bytes | None = None,
    catalog_hash_override: str | None = None,
    compatibility_raw_override: bytes | None = None,
    compatibility_hash_override: str | None = None,
    omit_catalog: bool = False,
    omit_compatibility: bool = False,
) -> tuple[str, str]:
    for child in tuple(repo.iterdir()):
        if child.name != ".git":
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    _write(repo / "package.json", _canonical({"name": "dex", "version": package_version or version}))
    _write(repo / "README.md", b"synthetic immutable release\n")

    compatibility_path = "System/compatibility/runtime.json"
    compatibility_raw = (
        compatibility_raw_override
        if compatibility_raw_override is not None
        else _canonical({"contract_version": 2, "runtime": "synthetic"})
    )
    if profile_name == "catalog-v1":
        catalog_raw = (
            catalog_raw_override
            if catalog_raw_override is not None
            else _canonical({"contract_version": 1, "items": []})
        )
        if not omit_catalog:
            _write(repo / CATALOG_PATH, catalog_raw)
        if not omit_compatibility:
            _write(repo / compatibility_path, compatibility_raw)
        profile = ReleaseEvidenceProfile(
            schema_version=1,
            profile="catalog-v1",
            release_version=version,
            catalog_contract_version=1,
            catalog_sha256=catalog_hash_override or hashlib.sha256(catalog_raw).hexdigest(),
            compatibility_metadata=(
                CompatibilityArtifact(
                    compatibility_path,
                    2,
                    compatibility_hash_override or hashlib.sha256(compatibility_raw).hexdigest(),
                ),
            ),
        )
        generated_profile = canonical_profile_bytes(profile)
    else:
        generated_profile = legacy_profile_bytes(version)
    _write(repo / PROFILE_PATH, profile_raw if profile_raw is not None else generated_profile)

    tracked = [
        "README.md",
        PROFILE_PATH,
        MANIFEST_PATH,
        "package.json",
    ]
    if profile_name == "catalog-v1":
        if not omit_catalog:
            tracked.append(CATALOG_PATH)
        if not omit_compatibility:
            tracked.append(compatibility_path)
    manifest = "".join(f"{path}\n" for path in sorted(tracked))
    if manifest_mutator is not None:
        manifest = manifest_mutator(manifest)
    _write(repo / MANIFEST_PATH, manifest.encode())
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", f"release {version}")
    commit = _git(repo, "rev-parse", "HEAD")
    short = _git(repo, "rev-parse", "--short", "HEAD")
    tag = f"dist/release/v{version}-{tag_suffix or short}"
    if lightweight:
        _git(repo, "tag", tag)
    else:
        _git(repo, "tag", "-a", tag, "-m", f"Dex release {version}")
    return tag, commit


def _tag_object(repo: Path, tag: str) -> str:
    return _git(repo, "rev-parse", f"refs/tags/{tag}")


def _lightweight_release_tag(repo: Path, version: str, suffix: str) -> str:
    tag = f"dist/release/v{version}-{suffix}"
    _git(repo, "tag", tag)
    return tag


def _lightweight_release_tags(
    repo: Path,
    versions: list[str],
) -> list[str]:
    commit = _git(repo, "rev-parse", "HEAD")
    tags = [
        f"dist/release/v{version}-{index + 1:064x}"
        for index, version in enumerate(versions)
    ]
    subprocess.run(
        ["git", "-C", str(repo), "update-ref", "--stdin"],
        check=True,
        input="".join(f"create refs/tags/{tag} {commit}\n" for tag in tags),
        capture_output=True,
        text=True,
    )
    return tags


@pytest.fixture(autouse=True)
def deny_external_sockets(monkeypatch: pytest.MonkeyPatch):
    def denied_socket(*_args, **_kwargs):
        raise AssertionError("update tests must not open external sockets")

    monkeypatch.setattr(socket, "socket", denied_socket)


def _verifier(vault: Path, remote: Path, state: Path, **kwargs) -> UpdateVerifier:
    # The production 10s SessionStart budget is a real wall-clock deadline
    # (ExecutionBudget uses time.monotonic(), not the injected `now`). Under load
    # — e.g. a slow CI runner, or right after the heavy distribution-artifact
    # clones + `npm ci` — a git evidence command can be SIGKILLed at that deadline,
    # surfacing as a generic EvidenceError ("evidence-invalid") and making these
    # tests non-hermetic and order-dependent. Pin a generous budget so evidence
    # validation is never killed by real time; tests that specifically exercise
    # the deadline pass their own wall_clock_seconds, which setdefault preserves.
    kwargs.setdefault("wall_clock_seconds", 3600.0)
    return UpdateVerifier(
        vault,
        state_root=state,
        remote_url=str(remote),
        allow_test_transport=True,
        now=lambda: datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc),
        **kwargs,
    )


@pytest.mark.parametrize(
    "detail",
    (
        "fatal: unable to access release endpoint: The requested URL returned error: 429 /private/customer/path",
        "error: RPC failed; HTTP 429 curl 22 release endpoint /private/customer/path",
    ),
)
def test_network_git_classifies_only_explicit_http_429_without_retaining_stderr(
    tmp_path: Path,
    detail: str,
) -> None:
    fake_git = tmp_path / "git"
    _write(
        fake_git,
        f'#!/bin/sh\necho "{detail}" >&2\nexit 128\n'.encode(),
    )
    fake_git.chmod(0o755)
    runner = GitRunner(git_path=fake_git)

    with pytest.raises(TransientHttpRejectionError) as error_info:
        runner.run_plain("ls-remote", network=True)

    assert error_info.value.classification == "http-429"
    assert str(error_info.value) == "canonical Git endpoint returned a transient HTTP rejection"
    assert "customer" not in str(error_info.value)
    assert "429" not in str(error_info.value)


def test_release_identity_proof_retains_only_sanitized_http_429_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _installed_vault(tmp_path / "vault")

    def reject(*_args, **_kwargs):
        raise TransientHttpRejectionError

    monkeypatch.setattr(UpdateVerifier, "_remote_release_tags", reject)

    assert update_verifier_module.prove_latest_release(
        vault,
        "stable",
        state_root=tmp_path / "state",
        wall_clock_seconds=10.0,
    ) == {
        "status": STATUS_UNKNOWN,
        "reason": "transient-http-rejection",
        "diagnostic": {"classification": "http-429"},
    }


@pytest.mark.parametrize(
    "detail",
    (
        "fatal: unable to access release endpoint: The requested URL returned error: 503",
        "fatal: generic evidence-invalid",
    ),
)
def test_network_git_does_not_classify_other_rejections_as_transient_http(
    tmp_path: Path,
    detail: str,
) -> None:
    fake_git = tmp_path / "git"
    _write(fake_git, f'#!/bin/sh\necho "{detail}" >&2\nexit 128\n'.encode())
    fake_git.chmod(0o755)
    runner = GitRunner(git_path=fake_git)

    with pytest.raises(EvidenceError) as error_info:
        runner.run_plain("ls-remote", network=True)

    assert type(error_info.value) is EvidenceError


def test_legacy_release_notice_is_readable_and_keeps_technical_evidence_out_of_user_copy(
    tmp_path: Path,
) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    tag, commit = _release(remote, "1.62.0")
    commands: list[tuple[str, ...]] = []
    runner = GitRunner(allowed_protocol="file", command_observer=commands.append)

    result = _verifier(vault, remote, tmp_path / "state", git_runner=runner).check()
    tree = _git(remote, "rev-parse", f"{commit}^{{tree}}")
    tag_object = _tag_object(remote, tag)

    assert result == {
        "status": STATUS_RELEASE,
        "should_notify": True,
        "current_version": "1.61.0",
        "version": "1.62.0",
        "tag": tag,
        "tag_object": tag_object,
        "commit": commit,
        "tree": tree,
        "profile": "legacy-v1",
        "release_page": "https://github.com/davekilleen/Dex/releases/tag/v1.62.0",
        "notice": "\n".join(
            (
                f"{APPROVED_NOTICE_AVAILABLE} v1.62.0",
                "Release notes: https://github.com/davekilleen/Dex/releases/tag/v1.62.0",
                APPROVED_NOTICE_GUIDANCE,
            )
        ),
        "publisher_authentication": "unavailable",
    }
    notice_lower = result["notice"].lower()
    assert "dist/release/" not in result["notice"]
    assert re.search(r"\b[0-9a-f]{40}\b", result["notice"]) is None
    for banned in (
        "appears to exist",
        "has not authenticated its publisher",
        "unverified",
        "evidence",
        "immutable tag",
        "tag object",
        "profile",
        "full commit",
        "authenticated",
        "verified",
        "safe",
        "current",
        "up to date",
    ):
        assert banned not in notice_lower
    assert all(Path(command[0]).is_absolute() for command in commands)
    assert sum("for-each-ref" in command for command in commands) == 1
    joined_commands = "\n".join(" ".join(command) for command in commands)
    for forbidden in (" pull ", " merge ", " reset ", " checkout ", " add ", " commit ", " push ", " remote "):
        assert forbidden not in f" {joined_commands} "


def test_catalog_v1_positive_profile_is_supported_without_implementing_a_catalog_engine(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0", profile_name="catalog-v1")

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result["status"] == STATUS_RELEASE
    assert result["profile"] == "catalog-v1"


def test_self_hashed_noncanonical_catalog_is_unknown_without_notice(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    noncanonical_catalog = b'{"items":[],"contract_version":1}\n'
    _release(
        remote,
        "1.62.0",
        profile_name="catalog-v1",
        catalog_raw_override=noncanonical_catalog,
    )

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result == {
        "status": "UNKNOWN",
        "should_notify": False,
        "current_version": "1.61.0",
        "reason": "evidence-invalid",
    }
    assert "notice" not in result


def test_self_hashed_noncanonical_compatibility_artifact_is_unknown_without_notice(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    noncanonical_compatibility = b'{"runtime":"synthetic","contract_version":2}\n'
    _release(
        remote,
        "1.62.0",
        profile_name="catalog-v1",
        compatibility_raw_override=noncanonical_compatibility,
    )

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result == {
        "status": "UNKNOWN",
        "should_notify": False,
        "current_version": "1.61.0",
        "reason": "evidence-invalid",
    }
    assert "notice" not in result


@pytest.mark.parametrize(
    "release_kwargs",
    [
        {"profile_raw": b'{"profile":"legacy-v1","release_version":"1.62.0","schema_version":1}\n'},
        {"profile_raw": _canonical({"profile": "unknown-v1", "release_version": "1.62.0", "schema_version": 1})},
        {"profile_raw": b'{"profile":"legacy-v1","profile":"catalog-v1","release_version":"1.62.0","schema_version":1}\n'},
        {
            "profile_raw": _canonical(
                {
                    "catalog_sha256": "0" * 64,
                    "profile": "legacy-v1",
                    "release_version": "1.62.0",
                    "schema_version": 1,
                }
            )
        },
        {"profile_raw": legacy_profile_bytes("1.63.0")},
        {"package_version": "1.63.0"},
        {"manifest_mutator": lambda manifest: manifest.replace(f"{PROFILE_PATH}\n", "")},
        {"manifest_mutator": lambda manifest: manifest + "missing-artifact.txt\n"},
        {"tag_suffix": "0000000"},
        {"lightweight": True},
    ],
)
def test_conflicting_or_incomplete_legacy_evidence_is_unknown_without_notice(
    tmp_path: Path,
    release_kwargs: dict[str, object],
) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0", **release_kwargs)

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result["status"] == STATUS_UNKNOWN
    assert result["should_notify"] is False
    assert "notice" not in result


@pytest.mark.parametrize(
    "release_kwargs",
    [
        {"catalog_hash_override": "0" * 64},
        {"compatibility_hash_override": "0" * 64},
        {"omit_catalog": True},
        {"omit_compatibility": True},
    ],
)
def test_declared_catalog_v1_failure_never_downgrades_to_legacy_notice(
    tmp_path: Path,
    release_kwargs: dict[str, object],
) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0", profile_name="catalog-v1", **release_kwargs)

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result["status"] == STATUS_UNKNOWN
    assert result["should_notify"] is False
    assert "profile" not in result
    assert "notice" not in result


def test_missing_profile_on_a_higher_pre_profile_candidate_is_unknown(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")
    (remote / PROFILE_PATH).unlink()
    manifest = (remote / MANIFEST_PATH).read_text().replace(f"{PROFILE_PATH}\n", "")
    (remote / MANIFEST_PATH).write_text(manifest)
    _git(remote, "add", "-A")
    _git(remote, "commit", "--quiet", "-m", "pre-profile higher candidate")
    commit = _git(remote, "rev-parse", "HEAD")
    short = _git(remote, "rev-parse", "--short", "HEAD")
    _git(remote, "tag", "-a", f"dist/release/v1.63.0-{short}", "-m", "pre profile")

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result["status"] == STATUS_UNKNOWN
    assert result["should_notify"] is False
    assert commit not in json.dumps(result)


@pytest.mark.parametrize("release_count", [500, 5_000])
def test_remote_release_enumeration_reports_and_fetches_only_the_newest_version(
    tmp_path: Path,
    release_count: int,
) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    newest_version = "9.0.0"
    newest_tag, _commit = _release(remote, newest_version)
    lower_tags = _lightweight_release_tags(
        remote,
        [f"2.{index}.0" for index in range(release_count - 1)],
    )
    commands: list[tuple[str, ...]] = []
    runner = GitRunner(allowed_protocol="file", command_observer=commands.append)

    result = _verifier(vault, remote, tmp_path / "state", git_runner=runner).check()

    assert result["status"] == STATUS_RELEASE
    assert result["should_notify"] is True
    assert result["version"] == newest_version
    assert result["tag"] == newest_tag
    assert f"{APPROVED_NOTICE_AVAILABLE} v{newest_version}" in result["notice"]
    fetch_commands = [command for command in commands if "fetch" in command]
    assert len(fetch_commands) == 1
    assert f"refs/tags/{newest_tag}:refs/tags/{newest_tag}" in fetch_commands[0]
    assert all(f"refs/tags/{tag}:refs/tags/{tag}" not in fetch_commands[0] for tag in lower_tags)


def test_highest_version_remains_ambiguous_with_many_lower_releases(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    first_tag, _commit = _release(remote, "9.0.0")
    _lightweight_release_tags(remote, [f"2.{index}.0" for index in range(500)])
    (remote / "README.md").write_text("second release identity\n")
    _git(remote, "add", "README.md")
    _git(remote, "commit", "--quiet", "-m", "conflicting release identity")
    second_short = _git(remote, "rev-parse", "--short", "HEAD")
    second_tag = f"dist/release/v9.0.0-{second_short}"
    _git(remote, "tag", "-a", second_tag, "-m", "conflicting identity")
    commands: list[tuple[str, ...]] = []
    runner = GitRunner(allowed_protocol="file", command_observer=commands.append)

    result = _verifier(vault, remote, tmp_path / "state", git_runner=runner).check()

    assert result["status"] == STATUS_UNKNOWN
    assert result["should_notify"] is False
    assert result["reason"] == "evidence-invalid"
    fetch_commands = [command for command in commands if "fetch" in command]
    assert len(fetch_commands) == 1
    assert f"refs/tags/{first_tag}:refs/tags/{first_tag}" in fetch_commands[0]
    assert f"refs/tags/{second_tag}:refs/tags/{second_tag}" in fetch_commands[0]


def test_malformed_remote_release_refs_are_skipped_without_hiding_the_newest_release(
    tmp_path: Path,
) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    newest_tag, _commit = _release(remote, "9.0.0")
    _git(remote, "tag", "dist/release/not-a-release")
    _git(remote, "tag", "dist/release/v999.0.0-not-a-hash")

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result["status"] == STATUS_RELEASE
    assert result["should_notify"] is True
    assert result["version"] == "9.0.0"
    assert result["tag"] == newest_tag


def test_single_highest_version_candidate_bound_remains_an_anomaly_guard(
    tmp_path: Path,
) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "9.0.0")
    for index in range(update_verifier_module.MAX_RELEASE_TAGS):
        _lightweight_release_tag(remote, "9.0.0", f"{index + 1:064x}")
    commands: list[tuple[str, ...]] = []
    runner = GitRunner(allowed_protocol="file", command_observer=commands.append)

    result = _verifier(vault, remote, tmp_path / "state", git_runner=runner).check()

    assert result == {
        "status": STATUS_UNKNOWN,
        "should_notify": False,
        "current_version": "1.61.0",
        "reason": "evidence-invalid",
    }
    assert not any("fetch" in command for command in commands)


def test_moved_annotated_tag_is_unknown_and_never_re_notified(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    tag, _commit = _release(remote, "1.62.0")
    verifier = _verifier(vault, remote, tmp_path / "state")
    first = verifier.check()
    persisted_before = json.loads((tmp_path / "state/state.json").read_text())
    (remote / "README.md").write_text("moved tag bytes\n")
    _git(remote, "add", "README.md")
    _git(remote, "commit", "--quiet", "-m", "move immutable tag")
    _git(remote, "tag", "-f", "-a", tag, "-m", "moved tag")

    result = verifier.check(force=True)

    assert result["status"] == STATUS_UNKNOWN
    assert result["should_notify"] is False
    assert result["reason"] == "tag-object-moved"
    assert "notice" not in result
    persisted_after = json.loads((tmp_path / "state/state.json").read_text())
    assert persisted_after["noticed_releases"] == persisted_before["noticed_releases"] == [
        f"{first['version']}|{first['tag']}|{first['tag_object']}|{first['commit']}|{first['tree']}|{first['profile']}"
    ]


def test_reannotated_tag_on_same_commit_is_unknown_and_preserves_prior_notice(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    tag, commit = _release(remote, "1.62.0")
    state = tmp_path / "state"
    verifier = _verifier(vault, remote, state)
    first = verifier.check()
    prior_notices = json.loads((state / "state.json").read_text())["noticed_releases"]
    old_tag_object = first["tag_object"]
    _git(remote, "tag", "-d", tag)
    _git(remote, "tag", "-a", tag, commit, "-m", "re-annotated same release commit")
    assert _tag_object(remote, tag) != old_tag_object

    result = verifier.check(force=True)

    assert result == {
        "status": STATUS_UNKNOWN,
        "should_notify": False,
        "current_version": "1.61.0",
        "reason": "tag-object-moved",
    }
    persisted = json.loads((state / "state.json").read_text())
    assert persisted["noticed_releases"] == prior_notices
    assert persisted["seen_tags"][tag]["tag_object"] == old_tag_object


def test_fetch_rejects_tag_object_that_differs_from_remote_enumeration(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    tag, commit = _release(remote, "1.62.0")
    advertised = _tag_object(remote, tag)

    def race_fetch(runner: GitRunner, cache: Path, remote_url: str) -> None:
        _git(remote, "tag", "-d", tag)
        _git(remote, "tag", "-a", tag, commit, "-m", "changed after enumeration")
        assert _tag_object(remote, tag) != advertised
        runner.run(
            cache,
            "fetch",
            "--quiet",
            "--no-tags",
            "--no-write-fetch-head",
            "--depth=1",
            "--no-recurse-submodules",
            remote_url,
            f"refs/tags/{tag}:refs/tags/{tag}",
            network=True,
            max_output_bytes=1024,
        )

    result = _verifier(vault, remote, tmp_path / "state", fetch_override=race_fetch).check()

    assert result["status"] == STATUS_UNKNOWN
    assert result["should_notify"] is False
    assert result["reason"] == "tag-object-mismatch"
    assert "notice" not in result


def test_fetch_rejects_lightweight_substitution_after_annotated_advertisement(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    tag, commit = _release(remote, "1.62.0")

    def substitute_fetch(runner: GitRunner, cache: Path, remote_url: str) -> None:
        _git(remote, "tag", "-d", tag)
        _git(remote, "tag", tag, commit)
        runner.run(
            cache,
            "fetch",
            "--quiet",
            "--no-tags",
            "--no-write-fetch-head",
            "--depth=1",
            "--no-recurse-submodules",
            remote_url,
            f"refs/tags/{tag}:refs/tags/{tag}",
            network=True,
            max_output_bytes=1024,
        )

    result = _verifier(vault, remote, tmp_path / "state", fetch_override=substitute_fetch).check()

    assert result["status"] == STATUS_UNKNOWN
    assert result["should_notify"] is False
    assert result["reason"] == "tag-object-mismatch"
    assert "notice" not in result


def test_equal_or_lower_release_yields_no_newer_observed_without_currentness_claim(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.61.0", profile_raw=b"historical release predates profiles\n")

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result["status"] == STATUS_NONE
    assert result["should_notify"] is False
    assert "not a currentness claim" in result["message"]
    message_lower = result["message"].lower()
    assert "up to date" not in message_lower
    assert "verified" not in message_lower
    assert "authenticated" not in message_lower


def test_daily_attempt_exact_release_dedup_and_doctor_redisplay(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")
    verifier = _verifier(vault, remote, tmp_path / "state")

    assert verifier.check()["status"] == STATUS_RELEASE
    daily = verifier.check()
    assert daily == {"status": STATUS_SKIPPED, "should_notify": False, "skip_reason": "daily-attempt"}
    exact = verifier.check(force=True)
    assert exact["status"] == STATUS_SKIPPED
    assert exact["skip_reason"] == "exact-release-notice"
    redisplay = verifier.check(doctor_redisplay=True)
    assert redisplay["status"] == STATUS_RELEASE
    assert redisplay["notice"].startswith(f"{APPROVED_NOTICE_AVAILABLE} v1.62.0\n")


def test_legacy_notice_is_migrated_to_exact_release_suppression_without_mutating_it(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    legacy_path = vault / "System/.update-available"
    legacy_raw = _canonical({"latest_version": "1.62.0", "last_notified": "2026-07-18"})
    _write(legacy_path, legacy_raw)
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result["status"] == STATUS_SKIPPED
    assert result["skip_reason"] == "legacy-notice"
    assert legacy_path.read_bytes() == legacy_raw


def test_offline_cancellation_and_corrupt_state_fail_closed(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")

    def offline(*_args):
        raise OfflineError("synthetic network unavailable")

    offline_result = _verifier(vault, remote, tmp_path / "offline", fetch_override=offline).check()
    assert offline_result["status"] == STATUS_OFFLINE
    assert offline_result["should_notify"] is False

    def cancelled(*_args):
        raise CancelledError("synthetic cancellation")

    cancelled_result = _verifier(vault, remote, tmp_path / "cancelled", fetch_override=cancelled).check()
    assert cancelled_result["status"] == STATUS_UNKNOWN
    assert cancelled_result["should_notify"] is False

    corrupt_state = tmp_path / "corrupt"
    corrupt_state.mkdir()
    (corrupt_state / "state.json").write_text("not json")
    corrupt_result = _verifier(vault, remote, corrupt_state).check()
    assert corrupt_result == {"status": STATUS_UNKNOWN, "should_notify": False, "reason": "state-corrupt"}


def test_missing_aiohttp_cannot_crash_the_mcp_update_check(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")
    state = tmp_path / "state"
    script = r"""
import asyncio
import builtins
import json
import os
from datetime import datetime, timezone
from pathlib import Path

real_import = builtins.__import__

def without_aiohttp(name, *args, **kwargs):
    if name == "aiohttp" or name.startswith("aiohttp."):
        raise ModuleNotFoundError("synthetic missing aiohttp")
    return real_import(name, *args, **kwargs)

builtins.__import__ = without_aiohttp

from core.mcp import update_checker

real_verifier = update_checker.UpdateVerifier
update_checker.UpdateVerifier = lambda vault: real_verifier(
    vault,
    state_root=Path(os.environ["STATE_PATH"]),
    remote_url=os.environ["REMOTE_PATH"],
    allow_test_transport=True,
    now=lambda: datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc),
    wall_clock_seconds=3600.0,
)
result = asyncio.run(update_checker.check_for_updates(force=True))
print(json.dumps(result, sort_keys=True))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env={
            **os.environ,
            "VAULT_PATH": str(vault),
            "REMOTE_PATH": str(remote),
            "STATE_PATH": str(state),
        },
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.splitlines()[-1])
    assert payload["status"] == STATUS_RELEASE
    assert payload["should_notify"] is True
    assert payload["version"] == "1.62.0"


def test_remote_and_git_configuration_poisoning_are_ignored_and_install_is_invariant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _installed_vault(tmp_path / "vault")
    poison = tmp_path / "poison"
    _init_repo(poison)
    _release(poison, "9.9.9", profile_raw=_canonical({"profile": "unknown", "release_version": "9.9.9"}))
    _git(vault, "remote", "add", "origin", str(poison))
    _git(vault, "config", "core.hooksPath", str(poison))
    global_config = tmp_path / "global.gitconfig"
    global_config.write_text(f'[url "{poison}/"]\n\tinsteadOf = file:///\n[credential]\n\thelper = malicious\n')
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")
    before = {
        "head": _git(vault, "rev-parse", "HEAD"),
        "tree": _git(vault, "write-tree"),
        "status": _git(vault, "status", "--porcelain=v1", "--untracked-files=all"),
        "index": (vault / ".git/index").read_bytes(),
    }
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(poison / ".git/objects"))
    monkeypatch.setenv("GIT_ALTERNATE_OBJECT_DIRECTORIES", str(poison / ".git/objects"))
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")

    result = _verifier(vault, remote, tmp_path / "state").check()

    monkeypatch.undo()
    after = {
        "head": _git(vault, "rev-parse", "HEAD"),
        "tree": _git(vault, "write-tree"),
        "status": _git(vault, "status", "--porcelain=v1", "--untracked-files=all"),
        "index": (vault / ".git/index").read_bytes(),
    }
    assert result["status"] == STATUS_RELEASE
    assert result["version"] == "1.62.0"
    assert after == before


def test_isolated_cache_configuration_poisoning_fails_closed(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")
    state = tmp_path / "state"
    verifier = _verifier(vault, remote, state)
    assert verifier.check()["status"] == STATUS_RELEASE
    (state / "objects.git/config").write_text('[url "/poison/"]\n\tinsteadOf = file:///\n')

    result = verifier.check(force=True)

    assert result["status"] == STATUS_UNKNOWN
    assert result["should_notify"] is False
    assert "notice" not in result


def test_failure_state_replaces_stale_release_status_and_same_day_skip_preserves_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")
    state = tmp_path / "state"
    verifier = _verifier(vault, remote, state)
    assert verifier.check()["status"] == STATUS_RELEASE

    def offline(*_args):
        raise OfflineError("synthetic network unavailable")

    assert _verifier(vault, remote, state, fetch_override=offline).check(force=True)["status"] == STATUS_OFFLINE
    persisted = json.loads((state / "state.json").read_text())
    assert persisted["last_status"] == STATUS_OFFLINE
    assert persisted["last_reason"] == "network-unavailable"
    assert persisted["noticed_releases"]
    skipped = verifier.check()
    assert skipped["status"] == STATUS_SKIPPED
    monkeypatch.setattr(update_checker_module, "_default_state_root", lambda _vault: state)
    monkeypatch.setenv("VAULT_PATH", str(vault))
    coroutine = update_checker_module.get_update_status()
    with pytest.raises(StopIteration) as completed:
        coroutine.send(None)
    status = completed.value.value
    assert status["status"] == STATUS_OFFLINE


def test_unknown_and_state_migration_are_persisted_without_duplicate_cache_fields(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")
    state = tmp_path / "state"
    verifier = _verifier(vault, remote, state)
    assert verifier.check()["status"] == STATUS_RELEASE
    persisted = json.loads((state / "state.json").read_text())
    persisted["last_attempt_at"] = "obsolete"
    persisted["last_notice"] = {"obsolete": True}
    (state / "state.json").write_text(json.dumps(persisted))
    (remote / PROFILE_PATH).write_text("not-json")
    _git(remote, "add", PROFILE_PATH)
    _git(remote, "commit", "--quiet", "-m", "malformed higher release")
    short = _git(remote, "rev-parse", "--short", "HEAD")
    _git(remote, "tag", "-a", f"dist/release/v1.63.0-{short}", "-m", "malformed")

    result = verifier.check(force=True)

    assert result["status"] == STATUS_UNKNOWN
    migrated = json.loads((state / "state.json").read_text())
    assert migrated["last_status"] == STATUS_UNKNOWN
    assert migrated["last_reason"] == "evidence-invalid"
    assert migrated["noticed_releases"]
    assert "last_attempt_at" not in migrated
    assert "last_notice" not in migrated


def test_state_without_tag_object_preserves_history_but_requires_fresh_exact_notice(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")
    state = tmp_path / "state"
    verifier = _verifier(vault, remote, state)
    first = verifier.check()
    persisted = json.loads((state / "state.json").read_text())
    old_identity = f"{first['version']}|{first['tag']}|{first['commit']}|{first['tree']}|{first['profile']}"
    persisted["noticed_releases"] = [old_identity]
    persisted["seen_tags"] = {first["tag"]: first["commit"]}
    persisted["last_attempt_at"] = "obsolete"
    persisted["last_notice"] = {"identity": persisted["noticed_releases"][0]}
    (state / "state.json").write_text(json.dumps(persisted))

    result = verifier.check(force=True)

    assert result["status"] == STATUS_RELEASE
    assert result["should_notify"] is True
    assert result["tag_object"] == _tag_object(remote, first["tag"])
    migrated = json.loads((state / "state.json").read_text())
    assert migrated["noticed_releases"][0] == old_identity
    assert migrated["noticed_releases"][1] == (
        f"{result['version']}|{result['tag']}|{result['tag_object']}|{result['commit']}|{result['tree']}|{result['profile']}"
    )
    assert migrated["legacy_seen_tags"] == {first["tag"]: first["commit"]}
    assert migrated["seen_tags"][first["tag"]] == {
        "commit": result["commit"],
        "profile": result["profile"],
        "tag_object": result["tag_object"],
        "tree": result["tree"],
        "version": result["version"],
    }
    assert "last_attempt_at" not in migrated
    assert "last_notice" not in migrated


def test_state_write_failure_returns_unknown_without_destroying_prior_notice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")
    state = tmp_path / "state"
    verifier = _verifier(vault, remote, state)
    assert verifier.check()["status"] == STATUS_RELEASE
    before = (state / "state.json").read_bytes()

    def fail_write(*_args, **_kwargs):
        raise OSError("synthetic write failure")

    monkeypatch.setattr(update_verifier_module, "_atomic_write_json", fail_write)
    result = verifier.check(force=True)

    assert result == {"status": STATUS_UNKNOWN, "should_notify": False, "reason": "state-write-failed"}
    assert (state / "state.json").read_bytes() == before


def test_aggregate_deadline_candidate_bound_quarantine_limit_and_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")
    for index in range(update_verifier_module.MAX_RELEASE_TAGS):
        _git(remote, "tag", "-a", f"dist/release/v2.0.{index}-{_git(remote, 'rev-parse', '--short', 'HEAD')}", "-m", "many")
    many_state = tmp_path / "many-state"
    many = _verifier(vault, remote, many_state).check()
    assert many["status"] == STATUS_UNKNOWN
    assert not list(many_state.glob("objects-quarantine.*"))

    bounded_remote = tmp_path / "bounded-remote"
    _init_repo(bounded_remote)
    _release(bounded_remote, "1.62.0")
    monkeypatch.setattr(update_verifier_module, "MAX_QUARANTINE_BYTES", 1024)
    bounded_state = tmp_path / "bounded-state"
    bounded = _verifier(vault, bounded_remote, bounded_state).check()
    assert bounded["status"] == STATUS_UNKNOWN
    assert not list(bounded_state.glob("objects-quarantine.*"))
    monkeypatch.setattr(update_verifier_module, "MAX_QUARANTINE_BYTES", 128 * 1024 * 1024)

    slow_runner = GitRunner(allowed_protocol="file", command_observer=lambda _command: __import__("time").sleep(0.03))
    deadline_state = tmp_path / "deadline-state"
    deadline = _verifier(
        vault,
        bounded_remote,
        deadline_state,
        git_runner=slow_runner,
        wall_clock_seconds=0.05,
    ).check()
    assert deadline["status"] in {STATUS_OFFLINE, STATUS_UNKNOWN}
    assert not list(deadline_state.glob("objects-quarantine.*"))

    monkeypatch.setattr(update_verifier_module, "MAX_AGGREGATE_OUTPUT_BYTES", 1)
    output_state = tmp_path / "output-state"
    output = _verifier(vault, bounded_remote, output_state).check()
    assert output["status"] == STATUS_UNKNOWN
    assert not list(output_state.glob("objects-quarantine.*"))


@pytest.mark.parametrize("relative_path", ["package.json", PROFILE_PATH])
def test_oversized_installed_evidence_fails_before_network(tmp_path: Path, relative_path: str) -> None:
    vault = _installed_vault(tmp_path / "vault")
    (vault / relative_path).write_bytes(b"x" * (1024 * 1024 + 1))
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")
    commands: list[tuple[str, ...]] = []
    runner = GitRunner(allowed_protocol="file", command_observer=commands.append)

    result = _verifier(vault, remote, tmp_path / "state", git_runner=runner).check()

    assert result["status"] == STATUS_UNKNOWN
    assert not any("ls-remote" in command or "fetch" in command for command in commands)


@pytest.mark.parametrize("bound_name", ["MAX_RELEASE_TAGS", "MAX_PROFILE_BYTES"])
def test_candidate_enumeration_and_required_artifact_bounds_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    bound_name: str,
) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")
    monkeypatch.setattr(update_verifier_module, bound_name, 0)

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result["status"] == STATUS_UNKNOWN
    assert result["should_notify"] is False
    assert "notice" not in result


def test_real_repository_release_tag_count_has_margin_below_the_dos_ceiling() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    listed = subprocess.run(
        ["git", "-C", str(repo_root), "tag", "--list", "dist/release/*"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert listed.returncode == 0, (
        "could not read real dist/release/* tags from this checkout; "
        f"git exited {listed.returncode}: {listed.stderr.strip() or 'no error detail'}"
    )
    actual_tag_count = len([tag for tag in listed.stdout.splitlines() if tag])
    ceiling = update_verifier_module.MAX_REMOTE_RELEASE_REFS

    assert actual_tag_count * 5 <= ceiling * 4, (
        f"real dist/release/* tag count {actual_tag_count} has exceeded 80% of "
        f"MAX_REMOTE_RELEASE_REFS={ceiling}; revisit MAX_REMOTE_RELEASE_REFS before "
        "release history can blind every install"
    )


def test_profile_parser_is_closed_immutable_and_sorted() -> None:
    profile = ReleaseEvidenceProfile(1, "legacy-v1", "1.62.0")
    raw = canonical_profile_bytes(profile)

    assert parse_profile(raw, expected_version="1.62.0") == profile
    with pytest.raises(Exception):
        parse_profile(raw.replace(b'"schema_version": 1', b'"schema_version": 2'), expected_version="1.62.0")


def test_session_start_settings_are_fetch_only_and_do_not_claim_sync() -> None:
    root = Path(__file__).resolve().parents[2]
    settings = json.loads((root / ".claude/settings.json").read_text())
    commands = [hook["command"] for group in settings["hooks"]["SessionStart"] for hook in group["hooks"]]
    update_command = next(command for command in commands if "update_verifier.py" in command)

    assert "--session-start" in update_command
    all_commands = "\n".join(commands).lower()
    assert "git pull" not in all_commands
    assert "pulled latest" not in all_commands
    assert "synced with github" not in all_commands


def test_latest_release_identity_proof_is_exact_and_does_not_persist_notice_state(
    tmp_path: Path,
) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")
    tag, commit = _release(remote, "1.63.0")
    state = tmp_path / "state"

    result = update_verifier_module.prove_latest_release(
        vault,
        "stable",
        state_root=state,
        remote_url=str(remote),
        allow_test_transport=True,
        wall_clock_seconds=60.0,
    )

    assert result == {
        "status": STATUS_IDENTITY,
        "version": "1.63.0",
        "tag": tag,
        "tag_object": _tag_object(remote, tag),
        "commit": commit,
        "tree": _git(remote, "rev-parse", f"{commit}^{{tree}}"),
    }
    assert not state.exists()


def test_release_identity_proof_refuses_unknown_or_ambiguous_versions(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")
    commit = _git(remote, "rev-parse", "HEAD")
    _git(remote, "tag", "-a", f"dist/release/v1.62.0-{commit[:8]}", "-m", "duplicate")
    kwargs = {
        "state_root": tmp_path / "state",
        "remote_url": str(remote),
        "allow_test_transport": True,
        "wall_clock_seconds": 60.0,
    }

    assert update_verifier_module.prove_release_identity(vault, "stable", "1.62.0", **kwargs) == {
        "status": STATUS_UNKNOWN,
        "reason": "release-ambiguous",
    }
    assert update_verifier_module.prove_release_identity(vault, "stable", "9.9.9", **kwargs) == {
        "status": STATUS_UNKNOWN,
        "reason": "release-not-found",
    }


def test_latest_release_identity_proof_reports_up_to_date(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault", "1.63.0")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.63.0")

    result = update_verifier_module.prove_latest_release(
        vault,
        "stable",
        state_root=tmp_path / "state",
        remote_url=str(remote),
        allow_test_transport=True,
        wall_clock_seconds=60.0,
    )

    assert result == {
        "status": STATUS_UP_TO_DATE,
        "current_version": "1.63.0",
        "latest_version": "1.63.0",
    }


# --- TLS-trust classification and subclass-safe failure dispatch -------------
#
# A TLS-inspecting corporate proxy (Zscaler, Netskope) or a captive portal makes
# git fail with a certificate error. That is neither "offline" nor "the release
# evidence is invalid": it is "Dex could not verify a secure connection". These
# tests pin the distinct classification, and pin that the failure dispatch uses
# isinstance so exception subclasses stop collapsing into evidence-invalid.


_TLS_INTERCEPTION_STDERR = (
    "fatal: unable to access 'https://github.com/davekilleen/Dex.git/': "
    "SSL certificate problem: self signed certificate",
    "fatal: unable to access 'https://github.com/davekilleen/Dex.git/': "
    "server certificate verification failed. CAfile: none CRLfile: none",
    "fatal: unable to access 'https://github.com/davekilleen/Dex.git/': "
    "SSL certificate problem: unable to get local issuer certificate",
    "fatal: unable to access 'https://github.com/davekilleen/Dex.git/': "
    "SSL certificate problem: certificate has expired",
    "fatal: unable to access 'https://github.com/davekilleen/Dex.git/': "
    "schannel: CertGetCertificateChain trust error CERT_TRUST_IS_UNTRUSTED_ROOT",
)


@pytest.mark.parametrize("detail", _TLS_INTERCEPTION_STDERR)
def test_network_git_classifies_tls_trust_failures_distinctly(
    tmp_path: Path,
    detail: str,
) -> None:
    """A certificate failure is its own risk class, not offline and not invalid."""
    fake_git = tmp_path / "git"
    _write(fake_git, f'#!/bin/sh\necho "{detail}" >&2\nexit 128\n'.encode())
    fake_git.chmod(0o755)
    runner = GitRunner(git_path=fake_git)

    with pytest.raises(update_verifier_module.TlsTrustError) as error_info:
        runner.run_plain("ls-remote", network=True)

    # It stays inside the evidence-error family so existing handlers still catch
    # it, but it must never be indistinguishable from a generic EvidenceError.
    assert isinstance(error_info.value, EvidenceError)
    assert type(error_info.value) is not EvidenceError
    assert not isinstance(error_info.value, OfflineError)
    # Same stderr-retention rule the HTTP-429 classification already follows.
    assert "github.com" not in str(error_info.value)


def test_tls_trust_markers_are_not_folded_into_the_offline_markers(tmp_path: Path) -> None:
    """Conflating 'cannot verify the certificate' with 'offline' would hide a MITM."""
    for marker in (
        "ssl certificate problem",
        "server certificate verification failed",
        "unable to get local issuer certificate",
        "certificate has expired",
        "schannel:",
    ):
        assert marker not in update_verifier_module._OFFLINE_MARKERS


def test_release_identity_proof_reports_tls_untrusted_not_evidence_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _installed_vault(tmp_path / "vault")

    def reject(*_args, **_kwargs):
        raise update_verifier_module.TlsTrustError(
            "bounded canonical fetch could not verify a secure connection"
        )

    monkeypatch.setattr(UpdateVerifier, "_remote_release_tags", reject)

    result = update_verifier_module.prove_latest_release(
        vault,
        "stable",
        state_root=tmp_path / "state",
        wall_clock_seconds=10.0,
    )

    assert result["status"] == STATUS_UNKNOWN
    assert result["reason"] == "tls-untrusted"
    assert result["reason"] != "evidence-invalid"
    message = result["message"]
    assert "secure connection" in message
    assert "proxy" in message


def test_check_reports_tls_untrusted_with_an_honest_user_facing_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")

    def reject(*_args, **_kwargs):
        raise update_verifier_module.TlsTrustError(
            "bounded canonical fetch could not verify a secure connection"
        )

    monkeypatch.setattr(UpdateVerifier, "_remote_release_tags", reject)

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result["status"] == STATUS_UNKNOWN
    assert result["should_notify"] is False
    assert result["reason"] == "tls-untrusted"
    assert "secure connection" in result["message"]


@pytest.mark.parametrize(
    ("error", "expected_reason"),
    (
        (FileNotFoundError(2, "no such file"), "io-error"),
        (PermissionError(13, "permission denied"), "io-error"),
        (OSError(5, "input/output error"), "io-error"),
        (subprocess.CalledProcessError(128, ("git", "ls-remote")), "subprocess-failed"),
        (subprocess.TimeoutExpired(("git", "ls-remote"), 10.0), "subprocess-failed"),
        (subprocess.SubprocessError("generic subprocess failure"), "subprocess-failed"),
        (UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte"), "encoding-invalid"),
        (CancelledError("synthetic cancellation"), "cancelled"),
        (EvidenceError("genuinely invalid evidence"), "evidence-invalid"),
    ),
)
def test_failure_dispatch_classifies_exception_subclasses_by_isinstance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_reason: str,
) -> None:
    """Exact-type dispatch silently collapsed every subclass into evidence-invalid."""
    vault = _installed_vault(tmp_path / "vault")

    def reject(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(UpdateVerifier, "_remote_release_tags", reject)

    result = update_verifier_module.prove_latest_release(
        vault,
        "stable",
        state_root=tmp_path / "state",
        wall_clock_seconds=10.0,
    )

    assert result == {"status": STATUS_UNKNOWN, "reason": expected_reason}


@pytest.mark.parametrize(
    ("error", "expected_reason"),
    (
        (FileNotFoundError(2, "no such file"), "io-error"),
        (subprocess.CalledProcessError(128, ("git", "ls-remote")), "subprocess-failed"),
    ),
)
def test_check_failure_dispatch_classifies_exception_subclasses_by_isinstance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_reason: str,
) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")

    def reject(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(UpdateVerifier, "_remote_release_tags", reject)

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result["reason"] == expected_reason


def test_no_certificate_verification_escape_hatch_exists_in_the_verifier() -> None:
    """The fix improves the message and the retry, never the trust decision."""
    source = Path(update_verifier_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "GIT_SSL_NO_VERIFY",
        "sslVerify",
        "GIT_SSL_CAINFO",
        "http.sslVerify",
        "--no-verify-ssl",
    ):
        assert forbidden not in source


# ---------------------------------------------------------------------------
# Signed release tags (publisher authentication).
#
# Every test below signs a real tag with a throwaway SSH key and lets Git do
# the verifying. Nothing about Git or ssh-keygen is mocked, because a mock
# would only prove that the mock agrees with itself.
# ---------------------------------------------------------------------------

_SSH_KEYGEN = shutil.which("ssh-keygen")
requires_ssh_signing = pytest.mark.skipif(
    _SSH_KEYGEN is None,
    reason="SSH release-signature verification needs the ssh-keygen tool",
)


def _isolated_git(repo: Path, *args: str) -> str:
    """Run Git with no ambient global/system config.

    A developer machine or CI image may configure its own commit signing; the
    signatures these tests make must come from the test key and nothing else.
    """
    environment = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    ).stdout.strip()


def _signing_key(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    key = directory / name
    subprocess.run(
        [str(_SSH_KEYGEN), "-t", "ed25519", "-N", "", "-C", f"dex-{name}", "-f", str(key), "-q"],
        check=True,
        capture_output=True,
    )
    return key


def _install_trust_anchor(vault: Path, *keys: Path, preamble: str = "") -> Path:
    lines = list(preamble.splitlines())
    for key in keys:
        material = " ".join(Path(f"{key}.pub").read_text(encoding="utf-8").split()[:2])
        lines.append(f"releases@heydex.ai {material}")
    anchor = vault / ALLOWED_SIGNERS_PATH
    anchor.parent.mkdir(parents=True, exist_ok=True)
    anchor.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")
    return anchor


def _sign_release_tag(repo: Path, tag: str, key: Path) -> str:
    """Replace ``tag`` with an SSH-signed annotated tag on the same commit."""
    commit = _isolated_git(repo, "rev-parse", f"{tag}^{{commit}}")
    _isolated_git(repo, "tag", "-d", tag)
    _isolated_git(
        repo,
        "-c",
        "gpg.format=ssh",
        "-c",
        "gpg.ssh.program=ssh-keygen",
        "-c",
        f"user.signingkey={key}",
        "-c",
        "user.name=Dex Release Signing",
        "-c",
        "user.email=releases@example.com",
        "tag",
        "-s",
        "-m",
        f"Dex release {tag}",
        tag,
        commit,
    )
    return _tag_object(repo, tag)


def test_trust_anchor_is_absent_until_a_release_lists_a_real_key(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _installed_vault(vault)
    assert load_allowed_signers(vault) is None

    shutil.copy(REPO_ROOT / ALLOWED_SIGNERS_PATH, _install_trust_anchor(vault))
    assert load_allowed_signers(vault) is None, "the shipped placeholder names no key"

    (vault / ALLOWED_SIGNERS_PATH).write_text(
        "# a comment\n\n   \n# another comment\n", encoding="utf-8"
    )
    assert load_allowed_signers(vault) is None

    (vault / ALLOWED_SIGNERS_PATH).write_text(
        "# leading comment\nreleases@heydex.ai ssh-ed25519 AAAAC3Nza\n\n",
        encoding="utf-8",
    )
    anchor = load_allowed_signers(vault)
    assert anchor is not None
    assert anchor.principals == ("releases@heydex.ai ssh-ed25519 AAAAC3Nza",)
    assert anchor.path.is_absolute()


def test_unsigned_release_is_still_noticed_while_no_trust_anchor_is_installed(
    tmp_path: Path,
) -> None:
    """Pre-signing era: behavior is byte-for-byte what it was before."""
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result["status"] == STATUS_RELEASE
    assert result["should_notify"] is True
    assert result["version"] == "1.62.0"


def test_shipped_placeholder_anchor_does_not_switch_verification_on(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    anchor = vault / ALLOWED_SIGNERS_PATH
    anchor.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_ROOT / ALLOWED_SIGNERS_PATH, anchor)
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result["status"] == STATUS_RELEASE
    assert result["should_notify"] is True


@requires_ssh_signing
def test_release_signed_by_an_allowed_key_is_accepted(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    key = _signing_key(tmp_path / "keys", "release")
    _install_trust_anchor(vault, key)
    remote = tmp_path / "remote"
    _init_repo(remote)
    tag, _commit = _release(remote, "1.62.0")
    tag_object = _sign_release_tag(remote, tag, key)

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result["status"] == STATUS_RELEASE
    assert result["should_notify"] is True
    assert result["tag_object"] == tag_object
    assert result["notice"].startswith(f"{APPROVED_NOTICE_AVAILABLE} v1.62.0\n")


@requires_ssh_signing
def test_unsigned_release_is_refused_once_a_trust_anchor_is_installed(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    _install_trust_anchor(vault, _signing_key(tmp_path / "keys", "release"))
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")
    state = tmp_path / "state"

    result = _verifier(vault, remote, state).check()

    assert result["status"] == STATUS_UNKNOWN
    assert result["should_notify"] is False
    assert result["reason"] == "signature-untrusted"
    assert "not signed by the Dex maintainer" in result["message"]
    assert "notice" not in result
    persisted = json.loads((state / "state.json").read_text())
    assert persisted["last_status"] == STATUS_UNKNOWN
    assert persisted["last_reason"] == "signature-untrusted"
    assert persisted["noticed_releases"] == []


@requires_ssh_signing
def test_release_signed_by_an_unlisted_key_is_refused(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    _install_trust_anchor(vault, _signing_key(tmp_path / "keys", "release"))
    attacker = _signing_key(tmp_path / "keys", "attacker")
    remote = tmp_path / "remote"
    _init_repo(remote)
    tag, _commit = _release(remote, "1.62.0")
    _sign_release_tag(remote, tag, attacker)

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result["status"] == STATUS_UNKNOWN
    assert result["should_notify"] is False
    assert result["reason"] == "signature-untrusted"
    assert "does not match any key Dex trusts" in result["message"]
    assert "notice" not in result


@requires_ssh_signing
def test_rotation_keeps_the_previous_key_trusted_while_it_is_still_listed(
    tmp_path: Path,
) -> None:
    vault = _installed_vault(tmp_path / "vault")
    old_key = _signing_key(tmp_path / "keys", "old")
    new_key = _signing_key(tmp_path / "keys", "new")
    _install_trust_anchor(vault, old_key, new_key)
    remote = tmp_path / "remote"
    _init_repo(remote)
    tag, _commit = _release(remote, "1.62.0")
    _sign_release_tag(remote, tag, new_key)

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result["status"] == STATUS_RELEASE
    assert result["should_notify"] is True


@requires_ssh_signing
@pytest.mark.parametrize("gap", ["old-git", "no-ssh-keygen"])
def test_uncheckable_signature_refuses_without_claiming_a_bad_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gap: str,
) -> None:
    vault = _installed_vault(tmp_path / "vault")
    key = _signing_key(tmp_path / "keys", "release")
    _install_trust_anchor(vault, key)
    remote = tmp_path / "remote"
    _init_repo(remote)
    tag, _commit = _release(remote, "1.62.0")
    _sign_release_tag(remote, tag, key)
    if gap == "old-git":
        monkeypatch.setattr(update_verifier_module, "MIN_SSH_VERIFY_GIT_VERSION", (99, 0, 0))
    else:
        monkeypatch.setattr(update_verifier_module, "_ssh_keygen_available", lambda: False)

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result["status"] == STATUS_UNKNOWN
    assert result["should_notify"] is False
    assert result["reason"] == "signature-unverifiable"
    assert "Git 2.34 or newer" in result["message"]
    message = result["message"].lower()
    assert "does not match" not in message, "an unchecked signature is not a bad signature"
    assert "notice" not in result


@requires_ssh_signing
def test_release_identity_proof_refuses_an_untrusted_publisher(tmp_path: Path) -> None:
    """The delivery route proves identity through the same gate."""
    vault = _installed_vault(tmp_path / "vault")
    _install_trust_anchor(vault, _signing_key(tmp_path / "keys", "release"))
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")

    result = prove_latest_release(
        vault,
        "stable",
        state_root=tmp_path / "state",
        remote_url=str(remote),
        allow_test_transport=True,
        wall_clock_seconds=3600.0,
    )

    assert result["status"] == STATUS_UNKNOWN
    assert result["reason"] == "signature-untrusted"
    assert "has not been changed" in result["message"]


def test_git_version_parsing_covers_the_shapes_git_actually_prints() -> None:
    assert update_verifier_module.parse_git_version("git version 2.34.0") == (2, 34, 0)
    assert update_verifier_module.parse_git_version("git version 2.39") == (2, 39, 0)
    assert update_verifier_module.parse_git_version(
        "git version 2.39.5 (Apple Git-154)"
    ) == (2, 39, 5)
    assert update_verifier_module.parse_git_version("not git at all") is None
    assert update_verifier_module.parse_git_version("") is None


def test_signature_refusals_never_offer_a_way_around_the_check() -> None:
    """A refusal that teaches the bypass is worse than no check at all."""
    messages = (
        update_verifier_module.SIGNATURE_MISSING_MESSAGE,
        update_verifier_module.SIGNATURE_UNTRUSTED_MESSAGE,
        update_verifier_module.SIGNATURE_UNVERIFIABLE_MESSAGE,
    )
    for message in messages:
        lowered = message.lower()
        for forbidden in (
            "bypass",
            "skip",
            "override",
            "disable",
            "turn off",
            "ignore this",
            "--no-verify",
            "force",
            "anyway",
        ):
            assert forbidden not in lowered, f"{forbidden!r} appears in: {message}"
        assert "not been changed" in lowered or "was changed" in lowered
