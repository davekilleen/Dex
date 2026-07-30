"""Tests for the historic-release acceptance fleet builder."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from scripts import release_fleet


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repository(tmp_path: Path) -> Path:
    repo = tmp_path / "releases"
    _git(tmp_path, "init", "--quiet", str(repo))
    _git(repo, "config", "user.name", "Dex Fleet Tests")
    _git(repo, "config", "user.email", "fleet-tests@example.com")
    return repo


def _tag_release(
    repo: Path,
    version: str,
    content: str,
    *,
    allow_empty: bool = False,
    suffix: str | None = None,
) -> str:
    (repo / "README.md").write_text(content + "\n", encoding="utf-8")
    _git(repo, "add", "-A")
    commit_args = ["commit", "--quiet", "-m", f"release {version}"]
    if allow_empty:
        commit_args.insert(1, "--allow-empty")
    _git(repo, *commit_args)
    commit = _git(repo, "rev-parse", "HEAD")
    tag = f"dist/release/v{version}-{suffix or commit[:7]}"
    _git(repo, "tag", "-a", tag, "-m", tag)
    return tag


def _tag_legacy_release(repo: Path, version: str, content: str) -> str:
    (repo / "README.md").write_text(content + "\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "--quiet", "-m", f"legacy release {version}")
    tag = f"v{version}"
    _git(repo, "tag", "-a", tag, "-m", tag)
    return tag


def _archive_release_tag(repo: Path, tag: str) -> str:
    commit = _git(repo, "rev-parse", f"{tag}^{{commit}}")
    version, short = tag.removeprefix("dist/release/v").split("-", maxsplit=1)
    archive_tag = f"dist/archive/v{version}-{short}"
    _git(repo, "tag", "-a", archive_tag, commit, "-m", archive_tag)
    return archive_tag


def test_discovers_each_distinct_distribution_tree_once(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    first = _tag_release(repo, "1.61.0", "one")
    second = _tag_release(repo, "1.61.0", "two")
    _tag_release(repo, "1.62.0", "two", allow_empty=True)

    releases = release_fleet.discover_distribution_releases(repo)

    assert [release.tag for release in releases] == sorted([first, second])


def test_rejects_distribution_tag_that_does_not_name_its_commit(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    _tag_release(repo, "1.61.0", "actual", suffix="deadbee")

    with pytest.raises(release_fleet.FleetError, match="does not match"):
        release_fleet.discover_distribution_releases(repo)


def test_discovers_archived_distribution_tree_when_the_canonical_tag_is_absent(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    tag = _tag_release(repo, "1.64.0", "historic release")
    archive_tag = _archive_release_tag(repo, tag)
    _git(repo, "tag", "-d", tag)

    releases = release_fleet.discover_distribution_releases(repo)

    assert [release.tag for release in releases] == [archive_tag]


def test_discovers_exact_v164_archived_starting_tree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    tag = "dist/archive/v1.64.0-366c168"
    commit = "366c168af61c50ee7157976a9eb8a154ca0fd7f4"
    tree = "0bf7e30785d511e4b3774358f73ce569167f3f60"

    def fake_git(_repo: Path, *arguments: str) -> str:
        if arguments == ("tag", "--list"):
            return tag
        if arguments == ("rev-parse", f"{tag}^{{commit}}"):
            return commit
        if arguments == ("rev-parse", f"{tag}^{{tree}}"):
            return tree
        raise AssertionError(arguments)

    monkeypatch.setattr(release_fleet, "_git", fake_git)

    assert release_fleet.discover_distribution_releases(tmp_path) == (
        release_fleet.DistributionRelease(
            tag=tag,
            version="1.64.0",
            commit=commit,
            tree=tree,
        ),
    )


def test_prefers_canonical_tag_when_archive_tag_has_the_same_tree(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    tag = _tag_release(repo, "1.64.0", "historic release")
    _archive_release_tag(repo, tag)

    releases = release_fleet.discover_distribution_releases(repo)

    assert [release.tag for release in releases] == [tag]


def test_rejects_colliding_immutable_distribution_identities(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    canonical_tag = "dist/release/v1.64.0-366c168"
    archive_tag = "dist/archive/v1.64.0-366c168"
    commits = {
        canonical_tag: "366c168af61c50ee7157976a9eb8a154ca0fd7f4",
        archive_tag: "366c168dddddddddddddddddddddddddddddddddd",
    }
    trees = {
        canonical_tag: "0bf7e30785d511e4b3774358f73ce569167f3f60",
        archive_tag: "ad5c7be7f2075bc3de74d4d0b168bb29e72c2d4e",
    }

    def fake_git(_repo: Path, *arguments: str) -> str:
        if arguments == ("tag", "--list"):
            return "\n".join((canonical_tag, archive_tag))
        for suffix, values in (("^{commit}", commits), ("^{tree}", trees)):
            tag = arguments[1].removesuffix(suffix)
            if arguments == ("rev-parse", f"{tag}{suffix}"):
                return values[tag]
        raise AssertionError(arguments)

    monkeypatch.setattr(release_fleet, "_git", fake_git)

    with pytest.raises(release_fleet.FleetError, match="ambiguous immutable distribution identity"):
        release_fleet.discover_distribution_releases(tmp_path)


def test_discovers_legacy_published_release_trees_too(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    legacy = _tag_legacy_release(repo, "1.20.1", "legacy")
    distribution = _tag_release(repo, "1.61.0", "distribution")

    releases = release_fleet.discover_distribution_releases(repo)

    assert [release.tag for release in releases] == [legacy, distribution]


def test_build_fixture_uses_requested_release_and_preserves_user_hashes(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    _tag_release(repo, "1.61.0", "one")
    release = release_fleet.discover_distribution_releases(repo)[0]

    case = release_fleet.build_fixture(repo, release, tmp_path / "fleet")

    assert _git(case.vault, "rev-parse", "HEAD^") == release.commit
    assert _git(case.vault, "remote", "get-url", "upstream") == "DISABLED"
    assert _git(case.vault, "remote", "get-url", "--push", "upstream") == "DISABLED"
    assert case.user_hashes == release_fleet.hash_user_owned_files(case.vault)


def test_installed_fixture_runs_the_historic_installer_before_seeding_user_content(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    installer = repo / "install.sh"
    installer.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "test ! -e 00-Inbox/keep.md\n"
        f'test "$(git remote get-url upstream)" = "{release_fleet.OFFICIAL_REPOSITORY_URL}"\n'
        "mkdir -p System\n"
        "printf installed > System/fixture-install-proof\n",
        encoding="utf-8",
    )
    installer.chmod(0o755)
    tag = _tag_release(repo, "1.61.0", "one")
    _git(
        repo,
        "update-ref",
        release_fleet.OFFICIAL_RELEASE_REF,
        _git(repo, "rev-parse", f"{tag}^{{commit}}"),
    )
    release = release_fleet.discover_distribution_releases(repo)[0]

    case = release_fleet.build_installed_fixture(repo, release, tmp_path / "fleet")

    assert (case.vault / "System/fixture-install-proof").read_text(encoding="utf-8") == "installed"
    assert case.user_hashes == release_fleet.hash_user_owned_files(case.vault)


def test_installer_sees_the_official_release_ref_then_the_runner_disables_it(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    installer = repo / "install.sh"
    installer.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        f'test "$(git remote get-url upstream)" = "{release_fleet.OFFICIAL_REPOSITORY_URL}"\n'
        "test -n \"$(git rev-parse refs/remotes/upstream/release)\"\n",
        encoding="utf-8",
    )
    installer.chmod(0o755)
    tag = _tag_release(repo, "1.80.5", "foundation")
    commit = _git(repo, "rev-parse", f"{tag}^{{commit}}")
    _git(repo, "update-ref", release_fleet.OFFICIAL_RELEASE_REF, commit)
    release = release_fleet.discover_distribution_releases(repo)[0]

    case = release_fleet.build_installed_fixture(repo, release, tmp_path / "fleet")

    assert _git(case.vault, "remote", "get-url", "upstream") == "DISABLED"
    assert _git(case.vault, "remote", "get-url", "--push", "upstream") == "DISABLED"


def test_installer_release_ref_is_pinned_to_the_historic_start(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    tag = _tag_release(repo, "1.20.1", "historic")
    release = release_fleet.discover_distribution_releases(repo)[0]
    (repo / "current-foundation").write_text("newer release\n", encoding="utf-8")
    _git(repo, "add", "current-foundation")
    _git(repo, "commit", "--quiet", "-m", "current foundation")
    current_foundation = _git(repo, "rev-parse", "HEAD")
    _git(
        repo,
        "update-ref",
        release_fleet.OFFICIAL_RELEASE_REF,
        current_foundation,
    )
    vault = release_fleet._create_fixture_vault(
        repo,
        release,
        tmp_path / "fleet",
    )
    environment = release_fleet._case_environment(vault, tmp_path / "runtime")

    release_commit, release_tree = release_fleet._prepare_installer_release_remote(
        repo,
        vault,
        release,
        environment,
    )

    assert release_commit == release.commit
    assert release_tree == release.tree
    assert (
        _git(vault, "rev-parse", release_fleet.OFFICIAL_RELEASE_REF)
        == release.commit
    )
    assert release_commit != current_foundation
    assert _git(repo, "rev-parse", f"{tag}^{{commit}}") == release.commit


def test_installer_created_split_topology_preserves_the_exact_starting_release(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    tag = _tag_release(repo, "1.80.5", "foundation")
    commit = _git(repo, "rev-parse", f"{tag}^{{commit}}")
    tree = _git(repo, "rev-parse", f"{tag}^{{tree}}")
    _git(repo, "update-ref", release_fleet.OFFICIAL_RELEASE_REF, commit)
    release = release_fleet.discover_distribution_releases(repo)[0]
    vault = release_fleet._create_fixture_vault(repo, release, tmp_path / "fleet")
    environment = release_fleet._case_environment(vault, tmp_path / "runtime")
    official_commit, official_tree = release_fleet._prepare_installer_release_remote(
        repo, vault, release, environment
    )

    archive = vault / ".dex" / "pre-split-archive.git"
    archive.parent.mkdir()
    (vault / ".git").rename(archive)
    _git(vault, "init", "--quiet")
    _git(vault, "config", "user.name", "Dex Fleet Fixture")
    _git(vault, "config", "user.email", "fleet@example.com")
    (vault / ".git/dex-vault-v2").write_text(
        json.dumps({"schemaVersion": 1, "role": "vault"}) + "\n",
        encoding="utf-8",
    )
    (vault / "vault-note.md").write_text("fixture vault history\n", encoding="utf-8")
    _git(vault, "add", "vault-note.md")
    _git(vault, "commit", "--quiet", "-m", "installer-created vault history")

    brain = vault / ".dex" / "brain.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(brain)], check=True)
    subprocess.run(
        [
            "git",
            f"--git-dir={brain}",
            "fetch",
            "--quiet",
            str(repo),
            f"+{official_commit}:refs/dex/installed",
        ],
        check=True,
    )
    (brain / "dex-brain-v2").write_text(
        json.dumps(
            {"schemaVersion": 1, "role": "brain", "installed": official_commit}
        )
        + "\n",
        encoding="utf-8",
    )
    topology = vault / "System/.dex/topology.json"
    topology.parent.mkdir(parents=True)
    topology.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "topology": "brain-vault-split",
                "vaultGitDir": ".git",
                "brainGitDir": ".dex/brain.git",
                "archiveGitDir": ".dex/pre-split-archive.git",
                "installedRelease": official_commit,
                "environment": {"DEX_VAULT": str(vault)},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    release_fleet._prove_installed_release_identity(
        vault,
        release,
        environment,
        official_release_commit=official_commit,
        official_release_tree=official_tree,
    )
    assert (
        release_fleet._git_directory(
            archive, "rev-parse", "HEAD^{tree}", environment=environment
        )
        == tree
    )

    _git(repo, "commit", "--allow-empty", "--quiet", "-m", "unrelated")
    wrong = _git(repo, "rev-parse", "HEAD")
    subprocess.run(
        [
            "git",
            f"--git-dir={archive}",
            "fetch",
            "--quiet",
            str(repo),
            f"+{wrong}:refs/heads/wrong",
        ],
        check=True,
    )
    subprocess.run(
        ["git", f"--git-dir={archive}", "update-ref", "HEAD", wrong],
        check=True,
    )
    with pytest.raises(release_fleet.FleetError, match="pre-split archive"):
        release_fleet._prove_installed_release_identity(
            vault,
            release,
            environment,
            official_release_commit=official_commit,
            official_release_tree=official_tree,
        )


@pytest.mark.parametrize(
    "detail",
    (
        "installed catalog release does not match the designated bridge release",
        "ModuleNotFoundError: No module named 'yaml'",
    ),
)
def test_known_post_topology_adoption_stops_are_narrowly_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, detail: str
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    installer = vault / "install.sh"
    installer.write_text("#!/bin/sh\n", encoding="utf-8")
    environment = {key: "fixture" for key in release_fleet.SEALED_INSTALLER_ENVIRONMENT_KEYS}
    release = release_fleet.DistributionRelease(
        tag="dist/release/v1.67.0-27ecbb3",
        version="1.67.0",
        commit="a" * 40,
        tree="b" * 40,
    )
    proved: list[bool] = []
    monkeypatch.setattr(
        release_fleet,
        "_run_bounded_process_group",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["bash", "install.sh"],
            1,
            "",
            detail,
        ),
    )
    monkeypatch.setattr(
        release_fleet,
        "_prove_installed_release_identity",
        lambda *_args, **_kwargs: proved.append(True),
    )
    monkeypatch.setattr(release_fleet, "_disable_fixture_remotes", lambda *_args: None)

    outcome = release_fleet._run_historic_installer(
        vault,
        release,
        environment,
        official_release_commit="c" * 40,
        official_release_tree="d" * 40,
    )

    assert outcome == "installer-complete-after-known-post-topology-stop"
    assert proved == [True]


def test_v175_transition_repair_uses_its_own_publisher_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = tmp_path / "vault"
    transition = vault / "System/.local-only-preservation-transition.json"
    transition.parent.mkdir(parents=True)
    transition.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "phase": "untrack-v1",
                "release_version": "1.74.0",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (vault / "package.json").write_text(
        json.dumps({"version": "1.75.0"}) + "\n",
        encoding="utf-8",
    )
    commands: list[list[str]] = []

    def stamp(command, **_kwargs):
        commands.append(list(command))
        transition.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "phase": "untrack-v1",
                    "release_version": "1.75.0",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(release_fleet, "_run_bounded_process_group", stamp)

    release_fleet._stamp_v175_transition(
        vault,
        {key: "fixture" for key in release_fleet.SEALED_INSTALLER_ENVIRONMENT_KEYS},
        timeout_seconds=10,
    )

    assert commands == [
        [
            str(vault / ".venv/bin/python"),
            "-m",
            "core.migrations.preserve_local_only_paths",
            "stamp-transition",
            "--repo",
            str(vault),
        ]
    ]


def test_v175_installer_uses_its_explicit_disposable_sync_folder_override(
    tmp_path: Path,
) -> None:
    installer = tmp_path / "install.sh"
    installer.write_text(
        'for INSTALL_ARGUMENT in "$@"; do\n'
        '  if [ "$INSTALL_ARGUMENT" = "--allow-synced-folder" ]; then :; fi\n'
        "done\n",
        encoding="utf-8",
    )

    release = release_fleet.DistributionRelease(
        tag="v1.75.0",
        version="1.75.0",
        commit="a" * 40,
        tree="b" * 40,
    )

    assert release_fleet._historic_installer_command(installer, release) == [
        "bash",
        "install.sh",
        "--allow-synced-folder",
    ]


def test_build_fixture_does_not_preload_future_release_tags(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    first = _tag_release(repo, "1.61.0", "one")
    future = _tag_release(repo, "1.62.0", "two")
    release = next(
        candidate
        for candidate in release_fleet.discover_distribution_releases(repo)
        if candidate.tag == first
    )

    case = release_fleet.build_fixture(repo, release, tmp_path / "fleet")

    assert _git(case.vault, "tag", "--list", future) == ""


def test_installer_timeout_terminates_and_reaps_its_whole_process_group(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    _tag_release(repo, "1.60.0", "parent")
    installer = repo / "install.sh"
    installer.write_text(
        "#!/bin/sh\n"
        "(sleep 0.5; printf escaped > child-finished) &\n"
        "wait\n",
        encoding="utf-8",
    )
    installer.chmod(0o755)
    _tag_release(repo, "1.61.0", "release")
    release = release_fleet.discover_distribution_releases(repo)[-1]
    vault = release_fleet._create_fixture_vault(repo, release, tmp_path / "fleet")
    environment = release_fleet._case_environment(
        vault, tmp_path / "installer-runtime"
    )

    with pytest.raises(subprocess.TimeoutExpired):
        release_fleet._run_historic_installer(
            vault,
            release,
            environment,
            timeout_seconds=0.05,
        )

    time.sleep(0.6)
    assert not (vault / "child-finished").exists()


def test_installer_timeout_kills_detached_term_ignoring_child_after_leader_exits(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    _tag_release(repo, "1.60.0", "parent")
    installer = repo / "install.sh"
    installer.write_text(
        "#!/bin/sh\n"
        "trap 'exit 0' TERM\n"
        "(\n"
        "  trap '' TERM\n"
        "  exec >/dev/null 2>&1\n"
        "  printf ready > child-ready\n"
        "  sleep 1.25\n"
        "  printf escaped > child-finished\n"
        ") &\n"
        "while [ ! -e child-ready ]; do :; done\n"
        "while :; do sleep 10; done\n",
        encoding="utf-8",
    )
    installer.chmod(0o755)
    _tag_release(repo, "1.61.0", "release")
    release = release_fleet.discover_distribution_releases(repo)[-1]
    vault = release_fleet._create_fixture_vault(repo, release, tmp_path / "fleet")
    environment = release_fleet._case_environment(
        vault, tmp_path / "installer-runtime"
    )

    with pytest.raises(subprocess.TimeoutExpired):
        release_fleet._run_historic_installer(
            vault,
            release,
            environment,
            timeout_seconds=0.2,
        )

    time.sleep(2.0)
    assert not (vault / "child-finished").exists()


def test_revision_switching_installer_is_rejected_before_doctor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repository(tmp_path)
    _tag_release(repo, "1.60.0", "parent")
    installer = repo / "install.sh"
    installer.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "git checkout --quiet HEAD^\n",
        encoding="utf-8",
    )
    installer.chmod(0o755)
    tag = _tag_release(repo, "1.61.0", "release")
    _git(
        repo,
        "update-ref",
        release_fleet.OFFICIAL_RELEASE_REF,
        _git(repo, "rev-parse", f"{tag}^{{commit}}"),
    )
    release = next(
        candidate
        for candidate in release_fleet.discover_distribution_releases(repo)
        if candidate.tag == tag
    )
    node_runtime = release_fleet.NodeRuntime(
        requested_node=tmp_path / "trusted" / "node",
        resolved_node=tmp_path / "trusted" / "node",
        node_version="v20.10.0",
        node_sha256="a" * 64,
        requested_npm=tmp_path / "trusted" / "npm",
        resolved_npm=tmp_path / "trusted" / "npm",
        npm_version="10.8.0",
        npm_sha256="b" * 64,
    )
    python_runtime = release_fleet.PythonRuntime(
        requested_python=Path(sys.executable),
        resolved_python=Path(sys.executable),
        python_version=f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        python_sha256="c" * 64,
    )
    monkeypatch.setattr(release_fleet, "resolve_trusted_node_runtime", lambda: node_runtime)
    monkeypatch.setattr(
        release_fleet, "resolve_trusted_python_runtime", lambda: python_runtime
    )

    def doctor_must_not_run(*_args, **_kwargs):
        raise AssertionError("Doctor ran after the installer changed revisions")

    monkeypatch.setattr(release_fleet, "_doctor_preflight", doctor_must_not_run)

    survey = release_fleet.run_discovery_sweep(
        repo,
        releases=(release,),
        output=tmp_path / "survey",
        workers=1,
        install_timeout_seconds=10,
        doctor_timeout_seconds=10,
    )

    case = survey["cases"][0]
    assert case["fixture_install"] == {
        "status": "failed",
        "code": "installer-release-identity-changed",
    }
    assert case["doctor_preflight"] == {"status": "not-run", "code": "not-run"}
    assert survey["acceptance"] is False


def test_build_fixture_refuses_to_overwrite_an_existing_case(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    _tag_release(repo, "1.61.0", "one")
    release = release_fleet.discover_distribution_releases(repo)[0]
    output = tmp_path / "fleet"
    case = output / release_fleet.safe_case_name(release)
    case.mkdir(parents=True)
    (case / "keep-me").write_text("do not delete", encoding="utf-8")

    with pytest.raises(release_fleet.FleetError, match="case directory"):
        release_fleet.build_fixture(repo, release, output)


def test_acceptance_report_requires_both_hops_and_unchanged_user_hashes() -> None:
    hashes = {"00-Inbox/keep.md": "a" * 64}
    report = release_fleet.AcceptanceReport(
        foundation_tag="dist/release/v1.80.0-aaaaaaa",
        follow_up_tag="dist/release/v1.80.1-bbbbbbb",
        cases=(
            release_fleet.CaseResult(
                starting_tag="dist/release/v1.61.0-ccccccc",
                reached_foundation=True,
                reached_follow_up=True,
                foundation_doctor_healthy=True,
                follow_up_doctor_healthy=True,
                user_hashes_before=hashes,
                user_hashes_after_foundation=hashes,
                user_hashes_after_follow_up=hashes,
                transcript_path="journeys/v1.61.0.md",
            ),
            release_fleet.CaseResult(
                starting_tag="dist/release/v1.62.0-ddddddd",
                reached_foundation=True,
                reached_follow_up=False,
                foundation_doctor_healthy=True,
                follow_up_doctor_healthy=True,
                user_hashes_before=hashes,
                user_hashes_after_foundation=hashes,
                user_hashes_after_follow_up=hashes,
                transcript_path="journeys/v1.62.0.md",
            ),
        ),
    )

    with pytest.raises(release_fleet.FleetError, match="follow-up"):
        release_fleet.assert_complete(
            report,
            {
                "dist/release/v1.61.0-ccccccc",
                "dist/release/v1.62.0-ddddddd",
            },
        )


def test_acceptance_report_refuses_when_any_published_start_is_missing() -> None:
    hashes = {"00-Inbox/keep.md": "a" * 64}
    report = release_fleet.AcceptanceReport(
        foundation_tag="dist/release/v1.80.0-aaaaaaa",
        follow_up_tag="dist/release/v1.80.1-bbbbbbb",
        cases=(
            release_fleet.CaseResult(
                starting_tag="dist/release/v1.61.0-ccccccc",
                reached_foundation=True,
                reached_follow_up=True,
                foundation_doctor_healthy=True,
                follow_up_doctor_healthy=True,
                user_hashes_before=hashes,
                user_hashes_after_foundation=hashes,
                user_hashes_after_follow_up=hashes,
                transcript_path="journeys/v1.61.0.md",
            ),
        ),
    )

    with pytest.raises(release_fleet.FleetError, match="missing"):
        release_fleet.assert_complete(
            report,
            {
                "dist/release/v1.61.0-ccccccc",
                "dist/release/v1.62.0-ddddddd",
            },
        )


def test_acceptance_report_requires_each_declared_platform_to_cover_each_release() -> None:
    hashes = {"00-Inbox/keep.md": "a" * 64}
    common = {
        "starting_tag": "dist/release/v1.61.0-ccccccc",
        "reached_foundation": True,
        "reached_follow_up": True,
        "foundation_doctor_healthy": True,
        "follow_up_doctor_healthy": True,
        "user_hashes_before": hashes,
        "user_hashes_after_foundation": hashes,
        "user_hashes_after_follow_up": hashes,
        "transcript_path": "journeys/v1.61.0.md",
    }
    report = release_fleet.AcceptanceReport(
        foundation_tag="dist/release/v1.80.0-aaaaaaa",
        follow_up_tag="dist/release/v1.80.1-bbbbbbb",
        cases=(
            release_fleet.CaseResult(**common, platform="darwin"),
            release_fleet.CaseResult(**common, platform="linux"),
        ),
        platforms=("darwin", "linux"),
    )

    release_fleet.assert_complete(report, {common["starting_tag"]})


def test_build_command_outputs_every_distinct_historic_release(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repository(tmp_path)
    _tag_release(repo, "1.61.0", "one")
    _tag_release(repo, "1.62.0", "two")

    exit_code = release_fleet.main(
        ["build", "--repo", str(repo), "--output", str(tmp_path / "fleet")]
    )

    manifest = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert manifest["case_count"] == 2
    assert [case["starting"]["tag"] for case in manifest["cases"]] == [
        release.tag for release in release_fleet.discover_distribution_releases(repo)
    ]


def test_manifest_command_lists_every_release_without_building_fixtures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repository(tmp_path)
    _tag_release(repo, "1.61.0", "one")
    _tag_release(repo, "1.62.0", "two")
    output = tmp_path / "fleet"

    exit_code = release_fleet.main(["manifest", "--repo", str(repo)])

    manifest = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert manifest["case_count"] == 2
    assert not output.exists()


def test_generated_starting_manifest_supplies_the_required_case_count(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    _tag_release(repo, "1.61.0", "one")
    _tag_release(repo, "1.62.0", "two")
    releases = release_fleet.discover_distribution_releases(repo)
    generated = release_fleet.starting_release_manifest(releases)

    assert generated["case_count"] == len(releases) == 2
    assert release_fleet.releases_from_starting_manifest(
        json.dumps(generated), current_releases=releases
    ) == releases
    generated["case_count"] = 165
    with pytest.raises(release_fleet.FleetError, match="case count"):
        release_fleet.releases_from_starting_manifest(json.dumps(generated), current_releases=releases)


def test_manifest_cli_runs_from_the_documented_repository_root(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    _tag_release(repo, "1.61.0", "one")

    result = subprocess.run(
        [sys.executable, release_fleet.__file__, "manifest", "--repo", str(repo)],
        cwd=release_fleet.Path(__file__).resolve().parents[2],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["case_count"] == 1


def test_build_command_can_construct_one_historic_release_at_a_time(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _repository(tmp_path)
    first = _tag_release(repo, "1.61.0", "one")
    _tag_release(repo, "1.62.0", "two")

    exit_code = release_fleet.main(
        [
            "build",
            "--repo",
            str(repo),
            "--output",
            str(tmp_path / "fleet"),
            "--starting-tag",
            first,
        ]
    )

    manifest = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert manifest["case_count"] == 1
    assert manifest["cases"][0]["starting"]["tag"] == first


def test_discovery_sweep_uses_disposable_fixtures_and_never_reports_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repository(tmp_path)
    (repo / "install.sh").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    tag = _tag_release(repo, "1.61.0", "historic")
    _git(
        repo,
        "update-ref",
        release_fleet.OFFICIAL_RELEASE_REF,
        _git(repo, "rev-parse", f"{tag}^{{commit}}"),
    )
    releases = release_fleet.discover_distribution_releases(repo)
    output = tmp_path / "survey"
    runtime = release_fleet.NodeRuntime(
        requested_node=tmp_path / "trusted" / "node",
        resolved_node=tmp_path / "trusted" / "node",
        node_version="v20.10.0",
        node_sha256="a" * 64,
        requested_npm=tmp_path / "trusted" / "npm",
        resolved_npm=tmp_path / "trusted" / "npm",
        npm_version="10.8.0",
        npm_sha256="b" * 64,
    )
    python_runtime = release_fleet.PythonRuntime(
        requested_python=Path(sys.executable),
        resolved_python=Path(sys.executable),
        python_version="Python 3.14.6",
        python_sha256="c" * 64,
    )
    monkeypatch.setattr(release_fleet, "resolve_trusted_node_runtime", lambda: runtime)
    monkeypatch.setattr(release_fleet, "resolve_trusted_python_runtime", lambda: python_runtime)

    survey = release_fleet.run_discovery_sweep(
        repo,
        releases=releases,
        output=output,
        workers=1,
        install_timeout_seconds=10,
        doctor_timeout_seconds=10,
    )

    assert survey["outcome"] == "NON_ACCEPTANCE_DISCOVERY"
    assert survey["acceptance"] is False
    assert survey["executed_count"] == survey["expected_count"] == 1
    assert survey["fixture_runtime"]["node"] == runtime.identity()
    assert survey["fixture_runtime"]["python"] == python_runtime.identity()
    case = survey["cases"][0]
    assert case["fixture_install"] == {"status": "ok", "code": "installer-complete"}
    assert case["doctor_preflight"] == {
        "status": "failed",
        "code": "doctor-fixture-python-unavailable",
        "requested_interpreter": str(
            output
            / release_fleet.DISCOVERY_WORK_NAME
            / release_fleet.safe_case_name(releases[0])
            / ".venv"
            / "bin"
            / "python"
        ),
    }
    assert case["shipped_update_surface"]["route_classification"] == "missing-dex-update-skill"
    assert not (output / release_fleet.DISCOVERY_WORK_NAME).exists()
    assert not (output / release_fleet.safe_case_name(releases[0])).exists()


def test_discovery_sweep_groups_known_installer_dependency_failures() -> None:
    assert release_fleet._installer_failure_code(
        release_fleet.FleetError("historic installer failed: npm: command not found")
    ) == "installer-npm-unavailable"
    assert release_fleet._installer_failure_code(
        release_fleet.FleetError("historic installer failed: Python 3.9.6 found (too old)")
    ) == "installer-python-unsupported"
    assert release_fleet._installer_failure_code(
        release_fleet.FleetError(
            "Dex vault provision failed: installed catalog release does not match the designated bridge release"
        )
    ) == "installer-lifecycle-bridge-release-mismatch"
    assert release_fleet._installer_failure_code(
        release_fleet.FleetError("Dex vault provision failed: ModuleNotFoundError: No module named 'yaml'")
    ) == "installer-python-yaml-missing"


def test_doctor_unhealthy_code_groups_missing_mcp_dependency() -> None:
    checks = [
        {"id": "preflight.queue", "verdict": "BROKEN", "detail": "'mcp' package missing"},
        {"id": "doctor.self", "verdict": "BROKEN", "detail": "same dependency missing"},
    ]

    assert release_fleet._doctor_unhealthy_code(checks) == "doctor-mcp-dependency-missing"


def _write_update_surface(repo: Path) -> None:
    skill = repo / release_fleet.UPDATE_SKILL_RELATIVE
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(
        "core.lifecycle.service\npreview\napproval\nApply this exact update?\nreceipt\n"
        "deliver_latest_release\nbuild_and_preview_delivered_release\n"
        "execute_approved_delivered_release\n",
        encoding="utf-8",
    )
    rescue = repo / release_fleet.UPDATE_RESCUE_RELATIVE
    rescue.parent.mkdir(parents=True, exist_ok=True)
    rescue.write_text("# Published rescue\n", encoding="utf-8")


def _write_starting_manifest(root: Path, releases: tuple[release_fleet.DistributionRelease, ...]) -> Path:
    path = root / "historic-release-manifest.json"
    path.write_text(json.dumps(release_fleet.starting_release_manifest(releases)), encoding="utf-8")
    return path


def _tag_protocol_control_release(
    repo: Path,
    *,
    foundation: release_fleet.ImmutableRelease,
    version: str,
) -> str:
    for relative in (
        "scripts/dex_update_bridge.py",
        "scripts/release_fleet.py",
        "scripts/release_fleet_executor.py",
    ):
        source = repo / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes((release_fleet.PROJECT_ROOT / relative).read_bytes())
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "release-owned journey source")
    source_commit = _git(repo, "rev-parse", "HEAD")

    protocol_path = repo / release_fleet.UPDATE_JOURNEY_RELATIVE
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    document = json.loads(
        (release_fleet.PROJECT_ROOT / release_fleet.UPDATE_JOURNEY_RELATIVE).read_text()
    )
    document["historic_to_foundation"]["foundation"] = foundation.identity()
    protocol_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    (repo / "System/.release-catalog.json").write_text(
        json.dumps(
            {
                "catalog_version": 1,
                "release": {"source_commit": source_commit},
                "items": [],
                "integrity": {},
            }
        ),
        encoding="utf-8",
    )
    return _tag_release(repo, version, "protocol control release")


def _write_complete_evidence(
    repo: Path,
    root: Path,
    *,
    start: release_fleet.DistributionRelease,
    foundation: release_fleet.ImmutableRelease,
    follow_up: release_fleet.ImmutableRelease,
) -> tuple[dict[str, object], str, str]:
    evidence = root / "case.evidence"
    evidence.mkdir()
    historic_surface = release_fleet.shipped_update_surface(repo, start)
    foundation_surface = release_fleet.shipped_update_surface(repo, foundation)
    (evidence / "historic-update-surface.json").write_text(json.dumps(historic_surface))
    (evidence / "foundation-update-surface.json").write_text(json.dumps(foundation_surface))
    (evidence / "foundation-receipt.json").write_text(
        json.dumps({"release": foundation.identity(), "receipt": {"transaction_id": "foundation"}})
    )
    (evidence / "follow-up-receipt.json").write_text(
        json.dumps({"release": follow_up.identity(), "receipt": {"transaction_id": "follow-up"}})
    )
    doctor = json.dumps({"checks": [{"id": "doctor", "verdict": "OK"}]})
    (evidence / "foundation-doctor.json").write_text(doctor)
    (evidence / "follow-up-doctor.json").write_text(doctor)
    (evidence / "smoke.json").write_text(json.dumps({"status": "OK", "platform": "darwin"}))
    events = [
        {
            "id": "historic-update-surface",
            "command": ["git", "show", f"{start.tag}:{release_fleet.UPDATE_SKILL_RELATIVE}"],
            "release": historic_surface["release"],
            "skill_sha256": historic_surface["skill_sha256"],
            "rescue_sha256": historic_surface["rescue_sha256"],
        },
        {"id": "historic-route-refusal", "command": ["/dex-update"], "release": historic_surface["release"]},
        {"id": "bridge-foundation", "command": ["fleet-journey", "bridge"], "release": foundation.identity()},
        {
            "id": "foundation-update-surface",
            "command": ["git", "show", f"{foundation.tag}:{release_fleet.UPDATE_SKILL_RELATIVE}"],
            "release": foundation.identity(),
            "skill_sha256": foundation_surface["skill_sha256"],
            "rescue_sha256": foundation_surface["rescue_sha256"],
        },
        {
            "id": "foundation-preview",
            "command": ["/dex-update", "preview"],
            "from_release": foundation.identity(),
            "target_release": follow_up.identity(),
        },
        {
            "id": "foundation-approval",
            "command": ["/dex-update", "approve"],
            "target_release": follow_up.identity(),
            "answer": "APPLY",
        },
        {"id": "foundation-receipt", "command": ["/dex-update", "receipt"], "release": follow_up.identity()},
        {"id": "follow-up-installed", "command": ["git", "rev-parse"], "release": follow_up.identity()},
        {"id": "follow-up-doctor", "command": ["/dex-doctor"]},
        {"id": "follow-up-smoke", "command": ["dex-smoke"], "platform": "darwin"},
    ]
    transcript = evidence / "journey.json"
    transcript.write_text(json.dumps({"events": events}))
    manifest_path, manifest_sha256 = release_fleet._write_evidence_manifest(
        evidence,
        start=historic_surface["release"],
        foundation=foundation,
        follow_up=follow_up,
        events=events,
        artifacts={
            "transcript": transcript,
            "historic_update_surface": evidence / "historic-update-surface.json",
            "foundation_update_surface": evidence / "foundation-update-surface.json",
            "foundation_receipt": evidence / "foundation-receipt.json",
            "follow_up_receipt": evidence / "follow-up-receipt.json",
            "foundation_doctor": evidence / "foundation-doctor.json",
            "follow_up_doctor": evidence / "follow-up-doctor.json",
            "follow_up_smoke": evidence / "smoke.json",
        },
    )
    return ({"events": events}, manifest_path, manifest_sha256)


def test_check_report_rejects_a_fully_self_consistent_evidence_set_without_a_released_executor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repository(tmp_path)
    _write_update_surface(repo)
    start_tag = _tag_release(repo, "1.61.0", "one")
    hashes = {"00-Inbox/keep.md": "a" * 64}
    foundation_tag = _tag_release(repo, "1.80.0", "foundation")
    follow_up_tag = _tag_release(repo, "1.80.1", "follow-up")
    start = next(item for item in release_fleet.discover_distribution_releases(repo) if item.tag == start_tag)
    foundation = release_fleet.resolve_immutable_release(repo, foundation_tag)
    follow_up = release_fleet.resolve_immutable_release(repo, follow_up_tag)
    monkeypatch.setattr(release_fleet, "discover_distribution_releases", lambda _repo: (start,))
    starting_manifest = _write_starting_manifest(tmp_path, (start,))
    _events, manifest_path, manifest_sha256 = _write_complete_evidence(
        repo, tmp_path, start=start, foundation=foundation, follow_up=follow_up
    )
    report = {
        "foundation_tag": foundation_tag,
        "follow_up_tag": follow_up_tag,
        "platforms": ["darwin"],
        "cases": [
            {
                "starting_tag": start_tag,
                "reached_foundation": True,
                "reached_follow_up": True,
                "foundation_doctor_healthy": True,
                "follow_up_doctor_healthy": True,
                "user_hashes_before": hashes,
                "user_hashes_after_foundation": hashes,
                "user_hashes_after_follow_up": hashes,
                "transcript_path": "case.evidence/journey.json",
                "foundation_receipt_path": "case.evidence/foundation-receipt.json",
                "follow_up_receipt_path": "case.evidence/follow-up-receipt.json",
                "foundation_doctor_path": "case.evidence/foundation-doctor.json",
                "follow_up_doctor_path": "case.evidence/follow-up-doctor.json",
                "follow_up_smoke_path": "case.evidence/smoke.json",
                "platform": "darwin",
                "evidence_manifest_path": manifest_path,
                "evidence_manifest_sha256": manifest_sha256,
            }
        ],
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(release_fleet.FleetError, match="released journey executor"):
        release_fleet.main(
            [
                "check-report",
                "--repo",
                str(repo),
                "--starting-manifest",
                str(starting_manifest),
                str(report_path),
            ]
        )

    assert "PASS" not in capsys.readouterr().out


def test_check_report_rejects_hand_authored_evidence_even_with_a_valid_protocol(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repository(tmp_path)
    _write_update_surface(repo)
    start_tag = _tag_release(repo, "1.61.0", "start")
    foundation_tag = _tag_release(repo, "1.80.0", "foundation")
    start = next(
        item
        for item in release_fleet.discover_distribution_releases(repo)
        if item.tag == start_tag
    )
    foundation = release_fleet.resolve_immutable_release(repo, foundation_tag)
    follow_up_tag = _tag_protocol_control_release(
        repo,
        foundation=foundation,
        version="1.80.1",
    )
    follow_up = release_fleet.resolve_immutable_release(repo, follow_up_tag)
    monkeypatch.setattr(release_fleet, "discover_distribution_releases", lambda _repo: (start,))
    _events, manifest_path, manifest_sha256 = _write_complete_evidence(
        repo,
        tmp_path,
        start=start,
        foundation=foundation,
        follow_up=follow_up,
    )
    hashes = {"00-Inbox/keep.md": "a" * 64}
    starting_manifest = _write_starting_manifest(tmp_path, (start,))
    report_path = tmp_path / "report.json"
    report_path.write_text(
        json.dumps(
            {
                "foundation_tag": foundation.tag,
                "follow_up_tag": follow_up.tag,
                "platforms": ["darwin"],
                "cases": [
                    {
                        "starting_tag": start.tag,
                        "reached_foundation": True,
                        "reached_follow_up": True,
                        "foundation_doctor_healthy": True,
                        "follow_up_doctor_healthy": True,
                        "user_hashes_before": hashes,
                        "user_hashes_after_foundation": hashes,
                        "user_hashes_after_follow_up": hashes,
                        "transcript_path": "case.evidence/journey.json",
                        "foundation_receipt_path": "case.evidence/foundation-receipt.json",
                        "follow_up_receipt_path": "case.evidence/follow-up-receipt.json",
                        "foundation_doctor_path": "case.evidence/foundation-doctor.json",
                        "follow_up_doctor_path": "case.evidence/follow-up-doctor.json",
                        "follow_up_smoke_path": "case.evidence/smoke.json",
                        "platform": "darwin",
                        "evidence_manifest_path": manifest_path,
                        "evidence_manifest_sha256": manifest_sha256,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(release_fleet.FleetError, match="released journey executor"):
        release_fleet.main(
            [
                "check-report",
                "--repo",
                str(repo),
                "--starting-manifest",
                str(starting_manifest),
                str(report_path),
            ]
        )

    assert "PASS" not in capsys.readouterr().out


def test_check_report_rejects_a_plausible_manifest_when_surface_bytes_are_not_from_the_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repository(tmp_path)
    _write_update_surface(repo)
    start_tag = _tag_release(repo, "1.61.0", "start")
    foundation_tag = _tag_release(repo, "1.80.0", "foundation")
    follow_up_tag = _tag_release(repo, "1.80.1", "follow-up")
    start = next(item for item in release_fleet.discover_distribution_releases(repo) if item.tag == start_tag)
    foundation = release_fleet.resolve_immutable_release(repo, foundation_tag)
    follow_up = release_fleet.resolve_immutable_release(repo, follow_up_tag)
    monkeypatch.setattr(release_fleet, "discover_distribution_releases", lambda _repo: (start,))
    starting_manifest = _write_starting_manifest(tmp_path, (start,))
    _events, manifest_path, manifest_sha256 = _write_complete_evidence(
        repo, tmp_path, start=start, foundation=foundation, follow_up=follow_up
    )
    forged_surface = {"not": "a release surface"}
    (tmp_path / "case.evidence" / "historic-update-surface.json").write_text(json.dumps(forged_surface))
    # Rewriting the runner manifest's digest cannot make a hand-authored surface
    # pass: check-report independently re-reads the immutable tag bytes.
    manifest = tmp_path / manifest_path
    value = json.loads(manifest.read_text())
    value["artifacts"]["historic_update_surface"]["sha256"] = release_fleet.hashlib.sha256(
        (tmp_path / "case.evidence" / "historic-update-surface.json").read_bytes()
    ).hexdigest()
    manifest.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    manifest_sha256 = release_fleet.hashlib.sha256(manifest.read_bytes()).hexdigest()
    hashes = {"00-Inbox/keep.md": "a" * 64}
    report = {
        "foundation_tag": foundation_tag,
        "follow_up_tag": follow_up_tag,
        "platforms": ["darwin"],
        "cases": [{
            "starting_tag": start_tag, "reached_foundation": True, "reached_follow_up": True,
            "foundation_doctor_healthy": True, "follow_up_doctor_healthy": True,
            "user_hashes_before": hashes, "user_hashes_after_foundation": hashes,
            "user_hashes_after_follow_up": hashes, "transcript_path": "case.evidence/journey.json",
            "foundation_receipt_path": "case.evidence/foundation-receipt.json",
            "follow_up_receipt_path": "case.evidence/follow-up-receipt.json",
            "foundation_doctor_path": "case.evidence/foundation-doctor.json",
            "follow_up_doctor_path": "case.evidence/follow-up-doctor.json",
            "follow_up_smoke_path": "case.evidence/smoke.json", "platform": "darwin",
            "evidence_manifest_path": manifest_path, "evidence_manifest_sha256": manifest_sha256,
        }],
    }
    report_path = tmp_path / "report.json"
    report_path.write_text(json.dumps(report))

    with pytest.raises(release_fleet.FleetError, match="released journey executor"):
        release_fleet.main(
            [
                "check-report",
                "--repo",
                str(repo),
                "--starting-manifest",
                str(starting_manifest),
                str(report_path),
            ]
        )


def test_journey_target_must_be_an_immutable_annotated_distribution_tag(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    _tag_legacy_release(repo, "1.20.1", "legacy")

    with pytest.raises(release_fleet.FleetError, match="immutable dist/release"):
        release_fleet.resolve_immutable_release(repo, "v1.20.1")


def test_case_environment_is_allowlisted_and_has_an_isolated_home(tmp_path: Path) -> None:
    environment = release_fleet._case_environment(tmp_path / "vault", tmp_path / "runtime")

    assert set(environment) == {
        "HOME",
        "TMPDIR",
        "PATH",
        "LANG",
        "LC_ALL",
        "PYTHONNOUSERSITE",
        "PYTHONDONTWRITEBYTECODE",
        "GIT_CONFIG_NOSYSTEM",
        "GIT_TERMINAL_PROMPT",
        "VAULT_PATH",
    }
    assert Path(environment["HOME"]).is_dir()
    assert environment["HOME"] != str(Path.home())
    assert environment["VAULT_PATH"] == str(tmp_path / "vault")


def test_trusted_node_runtime_ignores_hostile_path_and_is_explicitly_injected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted = tmp_path / "trusted" / "bin"
    trusted.mkdir(parents=True)
    ambient = tmp_path / "ambient"
    ambient.mkdir()
    marker = tmp_path / "ambient-node-used"
    node = trusted / "node"
    npm = trusted / "npm"
    node.write_text("#!/bin/sh\nprintf 'v20.10.0\\n'\n", encoding="utf-8")
    npm.write_text("#!/bin/sh\nprintf '10.8.0\\n'\n", encoding="utf-8")
    (ambient / "node").write_text(
        f"#!/bin/sh\ntouch '{marker}'\nprintf 'v99.0.0\\n'\n", encoding="utf-8"
    )
    for executable in (node, npm, ambient / "node"):
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(ambient))
    monkeypatch.setattr(release_fleet, "TRUSTED_NODE_CANDIDATES", (node,))
    monkeypatch.setattr(release_fleet, "TRUSTED_NODE_ROOTS", (tmp_path / "trusted",))

    runtime = release_fleet.resolve_trusted_node_runtime()
    environment = release_fleet._case_environment(
        tmp_path / "vault", tmp_path / "runtime", node_runtime=runtime
    )

    assert runtime.resolved_node == node
    assert runtime.node_version == "v20.10.0"
    assert runtime.npm_version == "10.8.0"
    assert runtime.node_sha256 == release_fleet.hashlib.sha256(node.read_bytes()).hexdigest()
    assert not marker.exists()
    assert environment["PATH"] == f"{trusted}:/usr/bin:/bin:/usr/sbin:/sbin"
    assert str(ambient) not in environment["PATH"]


def test_trusted_python_runtime_ignores_hostile_path_and_is_explicitly_injected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trusted = tmp_path / "trusted" / "bin"
    trusted.mkdir(parents=True)
    ambient = tmp_path / "ambient"
    ambient.mkdir()
    marker = tmp_path / "ambient-python-used"
    python = trusted / "python3"
    python.write_text("#!/bin/sh\nprintf 'Python 3.14.6\\n'\n", encoding="utf-8")
    (ambient / "python3").write_text(
        f"#!/bin/sh\ntouch '{marker}'\nprintf 'Python 99.0.0\\n'\n", encoding="utf-8"
    )
    for executable in (python, ambient / "python3"):
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(ambient))
    monkeypatch.setattr(release_fleet, "TRUSTED_PYTHON_CANDIDATES", (python,))
    monkeypatch.setattr(release_fleet, "TRUSTED_PYTHON_ROOTS", (tmp_path / "trusted",))

    runtime = release_fleet.resolve_trusted_python_runtime()
    environment = release_fleet._case_environment(
        tmp_path / "vault", tmp_path / "runtime", python_runtime=runtime
    )

    assert runtime.resolved_python == python
    assert runtime.python_version == "Python 3.14.6"
    assert runtime.python_sha256 == release_fleet.hashlib.sha256(python.read_bytes()).hexdigest()
    assert not marker.exists()
    assert environment["PATH"] == f"{trusted}:/usr/bin:/bin:/usr/sbin:/sbin"
    assert str(ambient) not in environment["PATH"]


def _current_base_python_runtime() -> release_fleet.PythonRuntime:
    trusted = Path(getattr(sys, "_base_executable", sys.executable)).resolve()
    version = subprocess.run(
        [str(trusted), "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return release_fleet.PythonRuntime(
        requested_python=trusted,
        resolved_python=trusted,
        python_version=version,
        python_sha256=release_fleet.hashlib.sha256(trusted.read_bytes()).hexdigest(),
    )


def test_doctor_timeout_kills_detached_term_ignoring_child_after_leader_exits(
    tmp_path: Path,
) -> None:
    runtime = _current_base_python_runtime()
    vault = tmp_path / "vault"
    marker = vault / "doctor-child-finished"
    ready = vault / "doctor-child-ready"
    child_program = (
        "import signal, time\n"
        "from pathlib import Path\n"
        "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
        f"Path({str(ready)!r}).write_text('ready')\n"
        "time.sleep(1.25)\n"
        f"Path({str(marker)!r}).write_text('escaped')\n"
    )
    doctor_module = vault / "core" / "utils" / "doctor.py"
    doctor_module.parent.mkdir(parents=True)
    doctor_module.write_text(
        "import signal, subprocess, sys, time\n"
        "from pathlib import Path\n"
        f"ready = Path({str(ready)!r})\n"
        "subprocess.Popen(\n"
        f"    [sys.executable, '-c', {child_program!r}],\n"
        "    stdout=subprocess.DEVNULL,\n"
        "    stderr=subprocess.DEVNULL,\n"
        ")\n"
        "while not ready.exists():\n"
        "    time.sleep(0.01)\n"
        "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
        "while True:\n"
        "    time.sleep(10)\n",
        encoding="utf-8",
    )
    fixture_python = release_fleet.FixturePython(
        requested_python=runtime.requested_python,
        resolved_python=runtime.resolved_python,
        python_version=runtime.python_version,
        python_sha256=runtime.python_sha256,
        pyvenv_cfg=vault / ".venv" / "pyvenv.cfg",
        pyvenv_cfg_sha256="d" * 64,
        venv_prefix=vault / ".venv",
        base_prefix=runtime.resolved_python.parent.parent,
        dependency_origins=(),
    )
    environment = release_fleet._case_environment(vault, tmp_path / "runtime")

    doctor = release_fleet._doctor_preflight(
        vault,
        environment,
        fixture_python=fixture_python,
        timeout_seconds=0.2,
    )

    assert doctor["status"] == "failed"
    assert doctor["code"] == "doctor-timeout"
    time.sleep(2.0)
    assert not marker.exists()


def test_fixture_python_rejects_a_host_interpreter_symlink_without_a_real_venv(
    tmp_path: Path,
) -> None:
    runtime = _current_base_python_runtime()
    vault = tmp_path / "vault"
    fixture_python_path = vault / ".venv" / "bin" / "python"
    fixture_python_path.parent.mkdir(parents=True)
    fixture_python_path.symlink_to(runtime.resolved_python)

    with pytest.raises(release_fleet.FleetError, match="pyvenv.cfg"):
        release_fleet.resolve_fixture_python(vault, trusted_python=runtime)


def test_fixture_python_proves_real_venv_and_local_dependencies_before_doctor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _current_base_python_runtime()
    vault = tmp_path / "vault"
    fixture_root = vault / ".venv"
    subprocess.run(
        [sys.executable, "-m", "venv", str(fixture_root)],
        check=True,
        capture_output=True,
        text=True,
    )
    site_packages = (
        fixture_root
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    dependency_origins = {}
    for dependency in ("mcp", "yaml"):
        package = site_packages / dependency
        package.mkdir(parents=True)
        origin = package / "__init__.py"
        origin.write_text("# fixture-local test dependency\n", encoding="utf-8")
        dependency_origins[dependency] = str(origin)
    doctor_module = vault / "core" / "utils" / "doctor.py"
    doctor_module.parent.mkdir(parents=True)
    doctor_module.write_text(
        "import json\n"
        "print(json.dumps({'checks': [{'id': 'doctor', 'verdict': 'OK'}]}))\n",
        encoding="utf-8",
    )
    ambient = tmp_path / "ambient"
    ambient.mkdir()
    marker = tmp_path / "ambient-python-used"
    host_python = ambient / "python"
    host_python.write_text(f"#!/bin/sh\ntouch '{marker}'\nexit 1\n", encoding="utf-8")
    host_python.chmod(0o755)
    fixture_python_path = vault / ".venv" / "bin" / "python"
    monkeypatch.setenv("PATH", str(ambient))

    fixture_python = release_fleet.resolve_fixture_python(vault, trusted_python=runtime)
    environment = release_fleet._case_environment(vault, tmp_path / "runtime")
    doctor = release_fleet._doctor_preflight(
        vault, environment, fixture_python=fixture_python, timeout_seconds=10
    )

    assert doctor["status"] == "ok"
    assert doctor["command"] == [str(fixture_python_path), "-m", "core.utils.doctor"]
    assert doctor["interpreter"] == fixture_python.identity()
    assert doctor["interpreter"]["venv_prefix"] == str(fixture_root)
    assert doctor["interpreter"]["base_prefix"] == str(runtime.resolved_python.parent.parent)
    assert doctor["interpreter"]["dependency_origins"] == dependency_origins
    assert not marker.exists()

    with pytest.raises(release_fleet.FleetError, match="fixture venv pyvenv.cfg is unavailable"):
        release_fleet.resolve_fixture_python(tmp_path / "no-venv", trusted_python=runtime)
    assert not marker.exists()


def test_journey_fails_closed_before_building_when_release_has_no_executor(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    _write_update_surface(repo)
    start_tag = _tag_release(repo, "1.61.0", "start")
    foundation_tag = _tag_release(repo, "1.80.0", "foundation")
    follow_up_tag = _tag_release(repo, "1.80.5", "follow-up")

    with pytest.raises(release_fleet.FleetError, match="released journey executor"):
        release_fleet.run_journey(
            repo,
            output=tmp_path / "output",
            starting_tag=start_tag,
            foundation_tag=foundation_tag,
            follow_up_tag=follow_up_tag,
        )

    assert not (tmp_path / "output").exists()


def test_journey_refuses_an_undeclared_host_platform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(release_fleet.sys, "platform", "win32")

    with pytest.raises(release_fleet.FleetError, match="macOS and Linux only"):
        release_fleet.run_journey(
            tmp_path,
            output=tmp_path / "output",
            starting_tag="unused",
            foundation_tag="unused",
            follow_up_tag="unused",
        )


def test_journey_delegates_only_after_released_source_and_fixture_are_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.update.journey_protocol import load_update_journey_protocol
    from scripts import release_fleet_executor

    protocol_bytes = (
        release_fleet.PROJECT_ROOT / release_fleet.UPDATE_JOURNEY_RELATIVE
    ).read_bytes()
    protocol = load_update_journey_protocol(protocol_bytes)
    foundation = release_fleet.ImmutableRelease(
        tag=protocol.foundation["tag"],
        tag_object=protocol.foundation["tag_object"],
        commit=protocol.foundation["commit"],
        tree=protocol.foundation["tree"],
        version=protocol.foundation["version"],
    )
    follow_up = release_fleet.ImmutableRelease(
        tag="dist/release/v1.81.0-bbbbbbb",
        tag_object="c" * 40,
        commit="b" * 40,
        tree="d" * 40,
        version="1.81.0",
    )
    start = release_fleet.DistributionRelease(
        tag="dist/release/v1.61.0-aaaaaaa",
        version="1.61.0",
        commit="a" * 40,
        tree="e" * 40,
    )
    source_commit = "f" * 40
    captured: dict[str, object] = {}

    class Run:
        case = {"starting_tag": start.tag}

    monkeypatch.setattr(
        release_fleet,
        "discover_distribution_releases",
        lambda _repo: (start,),
    )
    monkeypatch.setattr(
        release_fleet,
        "resolve_immutable_release",
        lambda _repo, tag: foundation if tag == foundation.tag else follow_up,
    )
    monkeypatch.setattr(
        release_fleet,
        "_optional_tag_file",
        lambda _repo, _tag, relative: (
            protocol_bytes
            if relative == release_fleet.UPDATE_JOURNEY_RELATIVE
            else None
        ),
    )
    monkeypatch.setattr(
        release_fleet,
        "_verify_released_protocol_artifacts",
        lambda _repo, _release, _protocol: source_commit,
    )
    monkeypatch.setattr(
        release_fleet,
        "_tag_file",
        lambda _repo, _commit, relative: (
            release_fleet.PROJECT_ROOT / relative
        ).read_bytes(),
    )
    monkeypatch.setattr(
        release_fleet,
        "shipped_update_surface",
        lambda _repo, release: {
            "release": (
                release.identity()
                if isinstance(release, release_fleet.ImmutableRelease)
                else {
                    "tag": release.tag,
                    "tag_object": "9" * 40,
                    "commit": release.commit,
                    "tree": release.tree,
                    "version": release.version,
                    "channel": "stable",
                }
            ),
            "machine_executable": False,
        },
    )
    monkeypatch.setattr(release_fleet, "resolve_trusted_node_runtime", object)
    monkeypatch.setattr(release_fleet, "resolve_trusted_python_runtime", object)
    monkeypatch.setattr(
        release_fleet,
        "_case_environment",
        lambda *_args, **_kwargs: {},
    )

    def build_case(_repo, release, output, *, environment):
        assert environment == {}
        vault = output / release_fleet.safe_case_name(release)
        vault.mkdir(parents=True)
        return release_fleet.FleetCase(release, vault, {"00-Inbox/keep.md": "0" * 64})

    def execute(**kwargs):
        captured.update(kwargs)
        return Run()

    monkeypatch.setattr(release_fleet, "build_installed_fixture", build_case)
    monkeypatch.setattr(release_fleet, "resolve_fixture_python", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(release_fleet_executor, "execute_journey", execute)

    run = release_fleet.run_journey(
        tmp_path,
        output=tmp_path / "output",
        starting_tag=start.tag,
        foundation_tag=foundation.tag,
        follow_up_tag=follow_up.tag,
    )

    assert run.case == {"starting_tag": start.tag}
    assert captured["source_commit"] == source_commit
    assert captured["foundation_release"] == foundation.identity()
    assert captured["follow_up_release"] == follow_up.identity()
    assert captured["user_owned_paths"] == tuple(release_fleet.USER_FIXTURES)
    assert not (tmp_path / "output" / release_fleet.safe_case_name(start)).exists()


def test_shipped_update_surface_requires_and_exposes_the_released_executor(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    _write_update_surface(repo)
    prose_tag = _tag_release(repo, "1.80.5", "prose")
    prose_release = release_fleet.resolve_immutable_release(repo, prose_tag)

    assert release_fleet.shipped_update_surface(repo, prose_release)["machine_executable"] is False

    for relative in (
        "scripts/dex_update_bridge.py",
        "scripts/release_fleet.py",
        "scripts/release_fleet_executor.py",
    ):
        source = repo / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes((release_fleet.PROJECT_ROOT / relative).read_bytes())
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "release-owned journey source")
    source_commit = _git(repo, "rev-parse", "HEAD")

    protocol_path = repo / release_fleet.UPDATE_JOURNEY_RELATIVE
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    protocol_path.write_bytes(
        (release_fleet.PROJECT_ROOT / release_fleet.UPDATE_JOURNEY_RELATIVE).read_bytes()
    )
    catalog = repo / "System/.release-catalog.json"
    catalog.write_text(
        json.dumps(
            {
                "catalog_version": 1,
                "release": {"source_commit": source_commit},
                "items": [],
                "integrity": {},
            }
        ),
        encoding="utf-8",
    )
    protocol_tag = _tag_release(repo, "1.80.6", "protocol")
    protocol_release = release_fleet.resolve_immutable_release(repo, protocol_tag)
    surface = release_fleet.shipped_update_surface(repo, protocol_release)

    assert surface["machine_executable"] is True
    assert surface["journey_protocol"]["path"] == release_fleet.UPDATE_JOURNEY_RELATIVE
    assert surface["journey_protocol"]["schema_version"] == 1
    assert surface["journey_protocol"]["source_commit"] == source_commit
    assert surface["journey_protocol"]["executor"] == {
        "source_path": "scripts/release_fleet_executor.py",
        "sha256": release_fleet.hashlib.sha256(
            (release_fleet.PROJECT_ROOT / "scripts/release_fleet_executor.py").read_bytes()
        ).hexdigest(),
    }
    distribution = next(
        item
        for item in release_fleet.discover_distribution_releases(repo)
        if item.tag == protocol_tag
    )
    classification = release_fleet.classify_historic_update_surface(repo, distribution)
    assert classification["machine_executable"] is True
    assert classification["route_classification"] == "machine-protocol-released-executor"


def test_shipped_update_surface_rejects_a_protocol_with_an_unknown_operation(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    _write_update_surface(repo)
    protocol_path = repo / release_fleet.UPDATE_JOURNEY_RELATIVE
    protocol_path.parent.mkdir(parents=True, exist_ok=True)
    document = json.loads(
        (release_fleet.PROJECT_ROOT / release_fleet.UPDATE_JOURNEY_RELATIVE).read_text()
    )
    document["foundation_to_follow_up"]["operations"].append("run_any_command")
    protocol_path.write_text(json.dumps(document), encoding="utf-8")
    tag = _tag_release(repo, "1.80.6", "invalid-protocol")
    release = release_fleet.resolve_immutable_release(repo, tag)

    with pytest.raises(release_fleet.FleetError, match="journey protocol"):
        release_fleet.shipped_update_surface(repo, release)
