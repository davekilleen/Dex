"""Adversarial release-awareness tests using only local synthetic Git remotes."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.utils import update_verifier as update_verifier_module
from core.utils.update_verifier import (
    CATALOG_PATH,
    MANIFEST_PATH,
    NOTICE_CAUTION,
    NOTICE_GUIDANCE,
    PROFILE_PATH,
    STATUS_NONE,
    STATUS_OFFLINE,
    STATUS_RELEASE,
    STATUS_SKIPPED,
    STATUS_UNKNOWN,
    CancelledError,
    CompatibilityArtifact,
    GitRunner,
    OfflineError,
    ReleaseEvidenceProfile,
    UpdateVerifier,
    canonical_profile_bytes,
    legacy_profile_bytes,
    parse_profile,
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
    catalog_hash_override: str | None = None,
    compatibility_hash_override: str | None = None,
    omit_catalog: bool = False,
    omit_compatibility: bool = False,
) -> tuple[str, str]:
    for child in tuple(repo.iterdir()):
        if child.name != ".git":
            if child.is_dir():
                subprocess.run(["rm", "-rf", str(child)], check=True)
            else:
                child.unlink()
    _write(repo / "package.json", _canonical({"name": "dex", "version": package_version or version}))
    _write(repo / "README.md", b"synthetic immutable release\n")

    compatibility_path = "System/compatibility/runtime.json"
    compatibility_raw = _canonical({"contract_version": 2, "runtime": "synthetic"})
    if profile_name == "catalog-v1":
        catalog_raw = _canonical({"contract_version": 1, "items": []})
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


@pytest.fixture(autouse=True)
def deny_external_sockets(monkeypatch: pytest.MonkeyPatch):
    def denied_socket(*_args, **_kwargs):
        raise AssertionError("update tests must not open external sockets")

    monkeypatch.setattr(socket, "socket", denied_socket)


def _verifier(vault: Path, remote: Path, state: Path, **kwargs) -> UpdateVerifier:
    return UpdateVerifier(
        vault,
        state_root=state,
        remote_url=str(remote),
        allow_test_transport=True,
        now=lambda: datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc),
        **kwargs,
    )


def test_legacy_release_notice_has_exact_caution_identity_and_no_positive_trust_claims(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    tag, commit = _release(remote, "1.62.0")
    commands: list[tuple[str, ...]] = []
    runner = GitRunner(allowed_protocol="file", command_observer=commands.append)

    result = _verifier(vault, remote, tmp_path / "state", git_runner=runner).check()

    assert result == {
        "status": STATUS_RELEASE,
        "should_notify": True,
        "current_version": "1.61.0",
        "version": "1.62.0",
        "tag": tag,
        "commit": commit,
        "profile": "legacy-v1",
        "release_page": f"https://github.com/davekilleen/Dex/releases/tag/{tag}",
        "notice": "\n".join(
            (
                NOTICE_CAUTION,
                "Target version: v1.62.0",
                f"Immutable tag: {tag}",
                f"Full commit: {commit}",
                "Evidence profile: legacy-v1",
                f"Release page: https://github.com/davekilleen/Dex/releases/tag/{tag}",
                NOTICE_GUIDANCE,
            )
        ),
        "publisher_authentication": "unavailable",
    }
    notice_lower = result["notice"].lower()
    assert "update available" not in notice_lower
    assert "safe" not in notice_lower
    assert "current" not in notice_lower
    assert "up to date" not in notice_lower
    assert "verified" not in notice_lower
    assert all(Path(command[0]).is_absolute() for command in commands)
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


def test_two_distinct_candidates_for_the_same_higher_version_are_ambiguous(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    _release(remote, "1.62.0")
    (remote / "README.md").write_text("second release identity\n")
    _git(remote, "add", "README.md")
    _git(remote, "commit", "--quiet", "-m", "conflicting release identity")
    second_short = _git(remote, "rev-parse", "--short", "HEAD")
    _git(remote, "tag", "-a", f"dist/release/v1.62.0-{second_short}", "-m", "conflicting identity")

    result = _verifier(vault, remote, tmp_path / "state").check()

    assert result["status"] == STATUS_UNKNOWN
    assert result["should_notify"] is False


def test_moved_annotated_tag_is_unknown_and_never_re_notified(tmp_path: Path) -> None:
    vault = _installed_vault(tmp_path / "vault")
    remote = tmp_path / "remote"
    _init_repo(remote)
    tag, _commit = _release(remote, "1.62.0")
    verifier = _verifier(vault, remote, tmp_path / "state")
    assert verifier.check()["status"] == STATUS_RELEASE
    (remote / "README.md").write_text("moved tag bytes\n")
    _git(remote, "add", "README.md")
    _git(remote, "commit", "--quiet", "-m", "move immutable tag")
    _git(remote, "tag", "-f", "-a", tag, "-m", "moved tag")

    result = verifier.check(force=True)

    assert result["status"] == STATUS_UNKNOWN
    assert result["should_notify"] is False
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
    assert "up to date" not in result["message"].lower()


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
    assert redisplay["notice"].startswith(NOTICE_CAUTION)


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
