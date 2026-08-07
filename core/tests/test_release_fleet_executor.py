"""Integration and adversarial contracts for the released journey executor."""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from core.update.journey_protocol import load_update_journey_protocol
from scripts import release_fleet
from scripts import release_fleet_executor as executor

REPO_ROOT = Path(__file__).resolve().parents[2]


def _production_runtime() -> executor._ProductionRuntime:
    bridge = REPO_ROOT / "scripts/dex_update_bridge.py"
    return executor._ProductionRuntime(
        bridge_asset=bridge,
        bridge_sha256=hashlib.sha256(bridge.read_bytes()).hexdigest(),
    )


def _identity(version: str, fill: str) -> dict[str, str]:
    commit = fill * 40
    return {
        "tag": f"dist/release/v{version}-{commit[:7]}",
        "tag_object": ("f" if fill != "f" else "e") * 40,
        "commit": commit,
        "tree": ("d" if fill != "d" else "c") * 40,
        "version": version,
        "channel": "stable",
    }


def _legacy_identity(version: str, fill: str) -> dict[str, str]:
    identity = _identity(version, fill)
    identity["tag"] = f"v{version}"
    return identity


def _archive_identity(version: str, fill: str) -> dict[str, str]:
    identity = _identity(version, fill)
    identity["tag"] = identity["tag"].replace("dist/release/", "dist/archive/", 1)
    return identity


def _executor_source_commit(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "source"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Dex Tests"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.com"], cwd=repo, check=True)
    for relative in (
        "scripts/dex_update_bridge.py",
        "scripts/release_fleet.py",
        "scripts/release_fleet_executor.py",
    ):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / relative, target)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "released executor source"],
        cwd=repo,
        check=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo, commit


def _foundation_cache(
    tmp_path: Path,
) -> tuple[Path, executor.dex_update_bridge.ReleasePin]:
    source = tmp_path / "foundation-source"
    source.mkdir(parents=True)
    subprocess.run(
        ["git", "init", "--quiet", "--initial-branch=main"], cwd=source, check=True
    )
    subprocess.run(
        ["git", "config", "user.name", "Dex Tests"],
        cwd=source,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"],
        cwd=source,
        check=True,
    )
    service = source / "core/lifecycle/service.py"
    service.parent.mkdir(parents=True)
    service.write_text("FOUNDATION = True\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=source, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "foundation"],
        cwd=source,
        check=True,
    )
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tree = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tag = f"dist/release/v1.2.3-{commit[:7]}"
    subprocess.run(
        ["git", "tag", "-a", tag, "-m", "foundation"],
        cwd=source,
        check=True,
    )
    tag_object = subprocess.run(
        ["git", "rev-parse", tag],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "branch", "release"], cwd=source, check=True)
    cache = tmp_path / "foundation-cache.git"
    subprocess.run(
        ["git", "clone", "--bare", "--quiet", str(source), str(cache)],
        check=True,
    )
    cache.chmod(0o700)
    pin = executor.dex_update_bridge.ReleasePin(
        tag=tag,
        tag_object=tag_object,
        commit=commit,
        tree=tree,
        version="1.2.3",
    )
    return cache, pin


def _follow_up_cache(
    tmp_path: Path,
) -> tuple[Path, executor.dex_update_bridge.ReleasePin]:
    cache, pin = _foundation_cache(tmp_path)
    subprocess.run(
        ["git", "--git-dir", str(cache), "update-ref", "-d", "refs/heads/main"],
        check=True,
    )
    return cache, pin


def test_private_foundation_cache_preserves_exact_official_identity(
    tmp_path: Path,
) -> None:
    cache, pin = _foundation_cache(tmp_path)

    assert executor._validate_foundation_cache(cache, pin) == cache.resolve()
    temporary, source = executor._acquire_cached_foundation_source(cache, pin)
    try:
        assert (source / "core/lifecycle/service.py").is_file()
        assert (
            executor._cached_git(source, "rev-parse", "HEAD^{commit}")
            == pin.commit
        )
    finally:
        temporary.cleanup()

    vault = tmp_path / "vault"
    brain = vault / ".dex/brain.git"
    brain.parent.mkdir(parents=True)
    subprocess.run(["git", "init", "--bare", "--quiet", str(brain)], check=True)
    executor._fetch_foundation_from_cache(vault, pin, cache=cache)
    assert (
        executor._cached_git(
            brain,
            "rev-parse",
            "refs/remotes/upstream/release^{commit}",
        )
        == pin.commit
    )


def test_foundation_cache_rejects_wrong_channel_or_unsafe_permissions(
    tmp_path: Path,
) -> None:
    cache, pin = _foundation_cache(tmp_path)
    subprocess.run(
        ["git", "--git-dir", str(cache), "update-ref", "-d", "refs/heads/release"],
        check=True,
    )
    with pytest.raises(executor.ExecutorError, match="pinned official"):
        executor._validate_foundation_cache(cache, pin)

    cache, pin = _foundation_cache(tmp_path / "second")
    cache.chmod(0o755)
    with pytest.raises(executor.ExecutorError, match="mode 0700"):
        executor._validate_foundation_cache(cache, pin)


def test_private_follow_up_cache_is_exact_and_rejects_ref_tampering(
    tmp_path: Path,
) -> None:
    cache, pin = _follow_up_cache(tmp_path)
    release = pin.identity()

    assert executor._validate_follow_up_cache(cache, release) == cache.resolve()

    subprocess.run(
        ["git", "--git-dir", str(cache), "update-ref", "-d", "refs/heads/release"],
        check=True,
    )
    with pytest.raises(executor.ExecutorError, match="follow-up cache"):
        executor._validate_follow_up_cache(cache, release)

    cache, pin = _follow_up_cache(tmp_path / "extra-ref")
    subprocess.run(
        [
            "git",
            "--git-dir",
            str(cache),
            "update-ref",
            "refs/heads/unreviewed",
            pin.commit,
        ],
        check=True,
    )
    with pytest.raises(executor.ExecutorError, match="outside the requested"):
        executor._validate_follow_up_cache(cache, pin.identity())

    cache, pin = _follow_up_cache(tmp_path / "alternates")
    alternates = cache / "objects/info/alternates"
    alternates.write_text(str(tmp_path / "other-objects") + "\n", encoding="utf-8")
    with pytest.raises(executor.ExecutorError, match="alternate object stores"):
        executor._validate_follow_up_cache(cache, pin.identity())


def test_production_authority_predicate_is_sealed_inside_executor_boundary() -> None:
    assert not hasattr(executor, "_production_authority_intact")
    assert "_production_authority_intact" not in executor.execute_journey.__code__.co_names


def test_production_runtime_exposes_only_installed_qmd_not_ambient_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    qmd = tmp_path / ".bun" / "bin" / "qmd"
    qmd.parent.mkdir(parents=True)
    qmd.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    qmd.chmod(0o755)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", f"{tmp_path / 'ambient'}:/usr/bin")

    bridge = REPO_ROOT / "scripts/dex_update_bridge.py"
    runtime = executor._ProductionRuntime(
        bridge_asset=bridge,
        bridge_sha256=hashlib.sha256(bridge.read_bytes()).hexdigest(),
    )
    try:
        environment = runtime._runtime_environment(tmp_path)
        runtime_tools = Path(environment["PATH"].split(os.pathsep)[0])

        assert (runtime_tools / "qmd").resolve() == qmd.resolve()
        assert str(qmd.parent) not in environment["PATH"].split(os.pathsep)
        assert str(tmp_path / "ambient") not in environment["PATH"]
    finally:
        runtime.close()


def test_production_runtime_retries_exact_installed_doctor_after_transport_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    interpreter = tmp_path / "python"
    interpreter.touch()
    report = {
        "summary": {"broken": 0, "unknown": 0},
        "checks": [{"id": "core.drift", "verdict": "OK"}],
    }
    processes = []
    killed_process_groups: list[int] = []

    class FakeProcess:
        returncode = 0

        def __init__(self, *, times_out: bool) -> None:
            self.pid = 41000 + len(processes)
            self.times_out = times_out
            self.commands: list[float | int | None] = []

        def communicate(self, timeout=None):
            self.commands.append(timeout)
            if self.times_out and timeout is not None:
                raise subprocess.TimeoutExpired("doctor", timeout)
            if timeout is None:
                return b"", b""
            return json.dumps(report).encode("utf-8"), b""

    def popen(command, **kwargs):
        process = FakeProcess(times_out=not processes)
        process.command = command
        process.kwargs = kwargs
        processes.append(process)
        return process

    monkeypatch.setattr(executor.dex_update_bridge, "_validate_vault", lambda root: root)
    monkeypatch.setattr(
        executor.dex_update_bridge,
        "_installed_python",
        lambda _root: interpreter,
    )
    monkeypatch.setattr(executor.subprocess, "Popen", popen)
    monkeypatch.setattr(
        executor.os,
        "killpg",
        lambda pid, _signal: killed_process_groups.append(pid),
    )

    runtime = _production_runtime()
    try:
        assert runtime.doctor(vault) == {
            **report,
            "journey_transport": {"attempt_count": 2},
        }
    finally:
        runtime.close()

    assert len(processes) == 2
    assert all(
        process.command == [str(interpreter), "-m", "core.utils.doctor"]
        for process in processes
    )
    assert processes[0].commands == [60, None]
    assert processes[1].commands == [60]
    assert killed_process_groups == [processes[0].pid]
    assert all(process.kwargs["start_new_session"] is True for process in processes)


def test_production_runtime_fails_after_two_doctor_transport_timeouts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    interpreter = tmp_path / "python"
    interpreter.touch()
    processes = []
    killed_process_groups: list[int] = []

    class TimedOutProcess:
        returncode = 0

        def __init__(self) -> None:
            self.pid = 44000 + len(processes)
            self.commands: list[float | int | None] = []

        def communicate(self, timeout=None):
            self.commands.append(timeout)
            if timeout is not None:
                raise subprocess.TimeoutExpired("doctor", timeout)
            return b"", b""

    def popen(_command, **kwargs):
        process = TimedOutProcess()
        process.kwargs = kwargs
        processes.append(process)
        return process

    monkeypatch.setattr(executor.dex_update_bridge, "_validate_vault", lambda root: root)
    monkeypatch.setattr(
        executor.dex_update_bridge,
        "_installed_python",
        lambda _root: interpreter,
    )
    monkeypatch.setattr(executor.subprocess, "Popen", popen)
    monkeypatch.setattr(
        executor.os,
        "killpg",
        lambda pid, _signal: killed_process_groups.append(pid),
    )

    runtime = _production_runtime()
    try:
        with pytest.raises(
            executor.ExecutorError,
            match="installed core.utils.doctor timed out",
        ):
            runtime.doctor(vault)
    finally:
        runtime.close()

    assert len(processes) == 2
    assert killed_process_groups == [process.pid for process in processes]
    assert all(process.commands == [60, None] for process in processes)
    assert all(process.kwargs["start_new_session"] is True for process in processes)


@pytest.mark.parametrize(
    ("stdout", "stderr", "returncode", "error"),
    (
        (b"{}", b"doctor failed", 1, "doctor failed"),
        (b"not-json", b"", 0, "malformed JSON"),
    ),
)
def test_production_runtime_does_not_retry_non_timeout_doctor_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stdout: bytes,
    stderr: bytes,
    returncode: int,
    error: str,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    interpreter = tmp_path / "python"
    interpreter.touch()
    processes = []

    class FakeProcess:
        pid = 42000

        def __init__(self) -> None:
            self.returncode = returncode

        def communicate(self, timeout=None):
            return stdout, stderr

    def popen(_command, **_kwargs):
        process = FakeProcess()
        processes.append(process)
        return process

    monkeypatch.setattr(executor.dex_update_bridge, "_validate_vault", lambda root: root)
    monkeypatch.setattr(
        executor.dex_update_bridge,
        "_installed_python",
        lambda _root: interpreter,
    )
    monkeypatch.setattr(executor.subprocess, "Popen", popen)

    runtime = _production_runtime()
    try:
        with pytest.raises(executor.ExecutorError, match=error):
            runtime.doctor(vault)
    finally:
        runtime.close()

    assert len(processes) == 1


def test_production_runtime_does_not_retry_an_unhealthy_doctor_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    interpreter = tmp_path / "python"
    interpreter.touch()
    report = {
        "summary": {"broken": 1, "unknown": 0},
        "checks": [{"id": "core.drift", "verdict": "BROKEN"}],
    }
    processes = []

    class FakeProcess:
        pid = 43000
        returncode = 0

        def communicate(self, timeout=None):
            return json.dumps(report).encode("utf-8"), b""

    def popen(_command, **_kwargs):
        process = FakeProcess()
        processes.append(process)
        return process

    monkeypatch.setattr(executor.dex_update_bridge, "_validate_vault", lambda root: root)
    monkeypatch.setattr(
        executor.dex_update_bridge,
        "_installed_python",
        lambda _root: interpreter,
    )
    monkeypatch.setattr(executor.subprocess, "Popen", popen)

    runtime = _production_runtime()
    try:
        observed = runtime.doctor(vault)
    finally:
        runtime.close()

    assert observed == {
        **report,
        "journey_transport": {"attempt_count": 1},
    }
    assert executor._doctor_healthy(observed) is False
    assert len(processes) == 1


def _commit_executor_tamper(repo: Path) -> str:
    path = repo / "scripts/release_fleet_executor.py"
    path.write_bytes(path.read_bytes() + b"\n# externally substituted bytes\n")
    subprocess.run(["git", "add", str(path)], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "substitute executor"],
        cwd=repo,
        check=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _vault(tmp_path: Path) -> tuple[Path, tuple[str, ...]]:
    root = tmp_path / "vault"
    user_files = (
        "00-Inbox/keep.md",
        "03-Tasks/Tasks.md",
        "System/user-profile.yaml",
        ".claude/skills/my-weekly-review/SKILL.md",
    )
    for relative in user_files:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"user-owned:{relative}\n", encoding="utf-8")
    return root, user_files


class _Runtime:
    def __init__(self, follow_up: dict[str, str]) -> None:
        self.follow_up = follow_up
        self.installed = ""
        self.calls: list[str] = []

    def bridge_to_foundation(self, vault: Path, foundation, *, input_fn, output_fn):
        self.calls.append("bridge")
        output_fn(json.dumps({"preview": "topology"}))
        assert input_fn("topology approval") == "APPLY"
        output_fn(json.dumps({"preview": "foundation"}))
        assert input_fn("foundation approval") == "APPLY"
        output_fn(json.dumps({"preview": "mcp-registration"}))
        assert input_fn("mcp approval") == "APPLY"
        self.installed = foundation["commit"]
        return {
            "foundation": dict(foundation),
            "topology_receipt": {"receipt": {"transaction_id": "topology-tx"}},
            "delivery_receipt": {"receipt": {"transaction_id": "foundation-tx"}},
            "mcp_registration_receipt": {
                "receipt": {"transaction_id": "mcp-registration-tx"}
            },
        }

    def installed_release(self, vault: Path) -> str:
        self.calls.append("installed")
        return self.installed

    def doctor(self, vault: Path) -> dict[str, object]:
        self.calls.append("doctor")
        return {"checks": [{"id": "doctor.self", "verdict": "OK"}]}

    def deliver_latest_release(self, vault: Path) -> dict[str, object]:
        self.calls.append("deliver_latest_release")
        return {"api_version": "1.4.0", "status": "delivered", "release": self.follow_up}

    def build_and_preview_delivered_release(
        self, vault: Path, release
    ) -> dict[str, object]:
        self.calls.append("build_and_preview_delivered_release")
        return {
            "api_version": "1.4.0",
            "preview": {
                "release": dict(release),
                "previous_commit": self.installed,
                "writes": [{"path": "core/released.py"}],
            },
            "approval_token": "exact-preview-token",
        }

    def execute_approved_delivered_release(
        self, vault: Path, preview, approved_token: str
    ) -> dict[str, object]:
        self.calls.append("execute_approved_delivered_release")
        assert approved_token == "exact-preview-token"
        self.installed = self.follow_up["commit"]
        return {
            "api_version": "1.4.0",
            "receipt": {"transaction_id": "follow-up-tx"},
            "release": self.follow_up,
        }

    def smoke(self, vault: Path) -> dict[str, object]:
        self.calls.append("smoke")
        return {
            "schema_version": 1,
            "journeys": [{"id": "topology", "verdict": "OK", "detail": "healthy"}],
            "summary": {"ok": 1, "broken": 0, "unknown": 0, "off": 0},
        }


def test_serialized_or_directly_constructed_run_cannot_gain_executor_authority() -> None:
    authored = {"case": {"starting_tag": "dist/release/v1.0.0-deadbee"}}

    assert executor.is_authoritative_executor_run(authored) is False
    assert not hasattr(executor, "_EXECUTOR_AUTHORITY")
    assert not hasattr(executor, "_authoritative_run")
    with pytest.raises(executor.ExecutorError, match="live executor"):
        executor.ExecutorRun(authored["case"])
    forged = object.__new__(executor.ExecutorRun)
    assert executor.is_authoritative_executor_run(forged) is False
    object.__setattr__(forged, "_authority", object())
    object.__setattr__(
        forged,
        "_case_json",
        json.dumps(authored["case"]).encode("utf-8"),
    )
    assert executor.is_authoritative_executor_run(forged) is False


def test_executor_owns_the_closed_two_hop_journey_and_returned_evidence(
    tmp_path: Path,
) -> None:
    protocol = load_update_journey_protocol(
        (REPO_ROOT / "core/update/journey-protocol-v1.json").read_bytes()
    )
    source_repo, source_commit = _executor_source_commit(tmp_path)
    vault, user_files = _vault(tmp_path)
    starting = _identity("1.61.0", "a")
    follow_up = _identity("1.81.0", "b")
    runtime = _Runtime(follow_up)
    rendered: list[str] = []

    run = executor.execute_journey(
        repo_root=source_repo,
        source_commit=source_commit,
        vault_root=vault,
        evidence_root=tmp_path / "case.evidence",
        starting_release=starting,
        foundation_release=protocol.foundation,
        follow_up_release=follow_up,
        protocol=protocol,
        historic_surface={"release": starting, "machine_executable": False},
        foundation_surface={"release": protocol.foundation, "machine_executable": False},
        user_owned_paths=user_files,
        platform="darwin",
        bridge_asset_evidence=_bridge_asset_evidence(protocol, follow_up),
        bridge_asset_path=REPO_ROOT / protocol.bridge.artifact.source_path,
        initial_install_evidence={"topology": "legacy-monolithic", "brain_refs": []},
        input_fn=lambda _prompt: "APPLY",
        output_fn=rendered.append,
        _runtime=runtime,
    )

    assert executor.is_authoritative_executor_run(run) is False
    assert run.case["reached_foundation"] is True
    assert run.case["reached_follow_up"] is True
    assert run.case["user_hashes_before"] == run.case["user_hashes_after_foundation"]
    assert run.case["user_hashes_before"] == run.case["user_hashes_after_follow_up"]
    assert runtime.calls == [
        "bridge",
        "installed",
        "doctor",
        "deliver_latest_release",
        "build_and_preview_delivered_release",
        "execute_approved_delivered_release",
        "installed",
        "doctor",
        "smoke",
    ]
    evidence = tmp_path / "case.evidence"
    foundation_receipt = json.loads((evidence / "foundation-receipt.json").read_text())
    follow_up_receipt = json.loads((evidence / "follow-up-receipt.json").read_text())
    transcript = json.loads((evidence / "journey-transcript.json").read_text())
    assert foundation_receipt["receipt"]["delivery_receipt"]["receipt"]["transaction_id"] == "foundation-tx"
    assert release_fleet._valid_foundation_bridge_receipt(
        foundation_receipt["receipt"],
        expected_foundation=protocol.foundation,
        approval_count=3,
    )
    assert follow_up_receipt["receipt"]["receipt"]["transaction_id"] == "follow-up-tx"
    assert [event["id"] for event in transcript["events"]] == list(protocol.evidence)
    assert transcript["events"][2]["approval_count"] == 3
    assert rendered

    mutable_copy = run.case
    mutable_copy["user_hashes_before"]["00-Inbox/keep.md"] = "0" * 64
    assert run.case["user_hashes_before"]["00-Inbox/keep.md"] != "0" * 64
    with pytest.raises(executor.ExecutorError, match="immutable"):
        run._case_json = b"{}"


def _execute(
    tmp_path: Path,
    runtime: _Runtime,
    *,
    source_repo: Path,
    source_commit: str,
    input_fn=lambda _prompt: "APPLY",
    starting: dict[str, str] | None = None,
    follow_up_cache: Path | None = None,
    platform: str = "darwin",
    case_started=lambda: None,
) -> executor.ExecutorRun:
    protocol = load_update_journey_protocol(
        (REPO_ROOT / "core/update/journey-protocol-v1.json").read_bytes()
    )
    vault, user_files = _vault(tmp_path)
    starting = starting or _identity("1.61.0", "a")
    return executor.execute_journey(
        repo_root=source_repo,
        source_commit=source_commit,
        vault_root=vault,
        evidence_root=tmp_path / "case.evidence",
        starting_release=starting,
        foundation_release=protocol.foundation,
        follow_up_release=runtime.follow_up,
        protocol=protocol,
        historic_surface={"release": starting, "machine_executable": False},
        foundation_surface={"release": protocol.foundation, "machine_executable": False},
        user_owned_paths=user_files,
        platform=platform,
        bridge_asset_evidence=_bridge_asset_evidence(protocol, runtime.follow_up),
        bridge_asset_path=REPO_ROOT / protocol.bridge.artifact.source_path,
        initial_install_evidence={"topology": "legacy-monolithic", "brain_refs": []},
        follow_up_cache=follow_up_cache,
        input_fn=input_fn,
        output_fn=lambda _line: None,
        _runtime=runtime,
        _case_started=case_started,
    )


def test_executor_marks_case_execution_only_after_shared_integrity_checks(
    tmp_path: Path,
) -> None:
    source_repo, source_commit = _executor_source_commit(tmp_path)
    follow_up = _identity("1.81.0", "b")
    started: list[str] = []

    _execute(
        tmp_path / "valid",
        _Runtime(follow_up),
        source_repo=source_repo,
        source_commit=source_commit,
        case_started=lambda: started.append("valid"),
    )

    with pytest.raises(executor.ExecutorError, match="platform is not declared"):
        _execute(
            tmp_path / "invalid",
            _Runtime(follow_up),
            source_repo=source_repo,
            source_commit=source_commit,
            platform="win32",
            case_started=lambda: started.append("invalid"),
        )

    assert started == ["valid"]


def test_cache_backed_run_cannot_satisfy_formal_acceptance_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = load_update_journey_protocol(
        (REPO_ROOT / "core/update/journey-protocol-v1.json").read_bytes()
    )
    source_repo, source_commit = _executor_source_commit(tmp_path)
    follow_up = _identity("1.81.8", "b")
    monkeypatch.setattr(
        executor,
        "_production_authority_intact",
        lambda *_args, **_kwargs: True,
        raising=False,
    )
    run = _execute(
        tmp_path,
        _Runtime(follow_up),
        source_repo=source_repo,
        source_commit=source_commit,
        follow_up_cache=tmp_path / "candidate-release.git",
    )
    report = release_fleet.AcceptanceReport(
        foundation_tag=protocol.foundation["tag"],
        follow_up_tag=follow_up["tag"],
        cases=(release_fleet.CaseResult(**run.case),),
        platforms=("darwin",),
    )
    foundation = release_fleet.ImmutableRelease(
        tag=protocol.foundation["tag"],
        tag_object=protocol.foundation["tag_object"],
        commit=protocol.foundation["commit"],
        tree=protocol.foundation["tree"],
        version=protocol.foundation["version"],
    )
    target = release_fleet.ImmutableRelease(
        tag=follow_up["tag"],
        tag_object=follow_up["tag_object"],
        commit=follow_up["commit"],
        tree=follow_up["tree"],
        version=follow_up["version"],
    )

    assert executor.is_authoritative_executor_run(run) is False
    with pytest.raises(release_fleet.FleetError, match="executor authority"):
        release_fleet.assert_evidence_bound(
            report,
            repo=tmp_path,
            evidence_root=tmp_path / "case.evidence",
            foundation=foundation,
            follow_up=target,
            executor_runs=(run,),
        )


def _bridge_asset_evidence(protocol, follow_up: dict[str, str]) -> dict[str, str]:
    name = f"dex-update-bridge-v{follow_up['version']}.py"
    checksum = f"{protocol.bridge.artifact.sha256}  {name}\n".encode()
    return {
        "name": name,
        "sha256": protocol.bridge.artifact.sha256,
        "checksum_name": f"{name}.sha256",
        "checksum_sha256": hashlib.sha256(checksum).hexdigest(),
        "source": "released-standalone-asset",
    }


def test_runtime_loads_the_verified_asset_instead_of_the_controller_module(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset = tmp_path / "dex-update-bridge-v1.81.6.py"
    asset.write_bytes(b"MARKER = 'verified'\n")
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    original_read_bytes = Path.read_bytes

    def replace_after_read(path: Path) -> bytes:
        content = original_read_bytes(path)
        if path == asset:
            asset.write_bytes(b"MARKER = 'substituted'\n")
        return content

    monkeypatch.setattr(Path, "read_bytes", replace_after_read)

    loaded = executor._load_released_bridge(asset, digest)

    assert loaded is not executor.dex_update_bridge
    assert Path(loaded.__file__).resolve() == asset.resolve()
    assert loaded.MARKER == "verified"
    with pytest.raises(executor.ExecutorError, match="changed before execution"):
        executor._load_released_bridge(asset, digest)


def test_executor_accepts_an_exact_legacy_starting_tag_without_widening_targets(
    tmp_path: Path,
) -> None:
    source_repo, source_commit = _executor_source_commit(tmp_path)
    runtime = _Runtime(_identity("1.81.0", "b"))
    starting = _legacy_identity("1.20.1", "a")

    run = _execute(
        tmp_path,
        runtime,
        source_repo=source_repo,
        source_commit=source_commit,
        starting=starting,
    )

    assert run.case["starting_tag"] == "v1.20.1"
    assert executor.is_authoritative_executor_run(run) is False


def test_executor_accepts_an_exact_archive_start_without_widening_targets(
    tmp_path: Path,
) -> None:
    source_repo, source_commit = _executor_source_commit(tmp_path)
    runtime = _Runtime(_identity("1.81.0", "b"))
    starting = _archive_identity("1.65.0", "a")

    run = _execute(
        tmp_path,
        runtime,
        source_repo=source_repo,
        source_commit=source_commit,
        starting=starting,
    )

    assert run.case["starting_tag"] == "dist/archive/v1.65.0-aaaaaaa"
    assert executor.is_authoritative_executor_run(run) is False


@pytest.mark.parametrize(
    "tag",
    (
        "refs/tags/v1.20.1",
        "v01.20.1",
        "v1.20",
        "legacy/v1.20.1",
        "dist/archive/v1.20.1-not-a-commit",
        "dist/archive/v1.20.1-aaaaaaaa",
        "dist/archives/v1.20.1-aaaaaaa",
    ),
)
def test_executor_rejects_malformed_or_arbitrary_starting_refs(
    tmp_path: Path,
    tag: str,
) -> None:
    source_repo, source_commit = _executor_source_commit(tmp_path)
    runtime = _Runtime(_identity("1.81.0", "b"))
    starting = _legacy_identity("1.20.1", "a")
    starting["tag"] = tag

    with pytest.raises(executor.ExecutorError, match="starting release identity"):
        _execute(
            tmp_path,
            runtime,
            source_repo=source_repo,
            source_commit=source_commit,
            starting=starting,
        )

    assert runtime.calls == []


def test_executor_refuses_released_source_with_substituted_executor_bytes(
    tmp_path: Path,
) -> None:
    source_repo, _source_commit = _executor_source_commit(tmp_path)
    substituted_commit = _commit_executor_tamper(source_repo)
    runtime = _Runtime(_identity("1.81.0", "b"))

    with pytest.raises(executor.ExecutorError, match="released protocol source"):
        _execute(
            tmp_path,
            runtime,
            source_repo=source_repo,
            source_commit=substituted_commit,
        )

    assert runtime.calls == []


def test_executor_refuses_a_bridge_without_a_real_or_resumed_receipt(
    tmp_path: Path,
) -> None:
    source_repo, source_commit = _executor_source_commit(tmp_path)

    class MissingReceiptRuntime(_Runtime):
        def bridge_to_foundation(
            self, vault: Path, foundation, *, input_fn, output_fn
        ):
            result = dict(
                super().bridge_to_foundation(
                    vault,
                    foundation,
                    input_fn=input_fn,
                    output_fn=output_fn,
                )
            )
            result["delivery_receipt"] = {"status": "claimed-complete"}
            return result

    runtime = MissingReceiptRuntime(_identity("1.81.0", "b"))

    with pytest.raises(executor.ExecutorError, match="transaction receipt"):
        _execute(
            tmp_path,
            runtime,
            source_repo=source_repo,
            source_commit=source_commit,
        )


def test_executor_records_the_bridge_approval_count_that_actually_occurred(
    tmp_path: Path,
) -> None:
    source_repo, source_commit = _executor_source_commit(tmp_path)

    class OneApprovalRuntime(_Runtime):
        def bridge_to_foundation(
            self, vault: Path, foundation, *, input_fn, output_fn
        ):
            self.calls.append("bridge")
            output_fn(json.dumps({"preview": "foundation"}))
            assert input_fn("foundation approval") == "APPLY"
            self.installed = foundation["commit"]
            return {
                "foundation": dict(foundation),
                "topology_receipt": {"skipped": "already-brain-vault-split"},
                "delivery_receipt": {
                    "receipt": {"transaction_id": "foundation-tx"}
                },
                "mcp_registration_receipt": {
                    "skipped": "mcp-already-registered"
                },
            }

    runtime = OneApprovalRuntime(_identity("1.81.0", "b"))
    run = _execute(
        tmp_path,
        runtime,
        source_repo=source_repo,
        source_commit=source_commit,
    )

    transcript = json.loads(
        (
            tmp_path
            / "case.evidence"
            / "journey-transcript.json"
        ).read_text()
    )
    assert executor.is_authoritative_executor_run(run) is False
    assert transcript["events"][2]["approval_count"] == 1
    assert transcript["events"][2]["approvals"] == [
        {"prompt": "foundation approval", "answer": "APPLY"}
    ]


def test_transient_network_classifiers_match_only_momentary_network_loss() -> None:
    assert executor._transient_network_error("Could not resolve host: github.com")
    assert executor._transient_network_error(
        "fatal: unable to access 'https://github.com/': Connection reset by peer"
    )
    assert not executor._transient_network_error("fixture lifecycle runtime timed out")
    assert not executor._transient_network_error("foundation bridge approval was not exact")
    assert executor._transient_network_delivery(
        {"status": "not-delivered", "evidence": {"reason": "network-unavailable"}}
    )
    assert not executor._transient_network_delivery(
        {"status": "not-delivered", "evidence": {"reason": "evidence-invalid"}}
    )
    assert not executor._transient_network_delivery({"status": "not-delivered"})


def test_transient_network_follow_up_delivery_retries_and_records_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo, source_commit = _executor_source_commit(tmp_path)
    slept: list[float] = []
    monkeypatch.setattr(executor.time, "sleep", slept.append)

    class BlippedDeliveryRuntime(_Runtime):
        delivery_attempts = 0

        def deliver_latest_release(self, vault: Path) -> dict[str, object]:
            self.delivery_attempts += 1
            if self.delivery_attempts < 3:
                return {
                    "status": "not-delivered",
                    "evidence": {"reason": "network-unavailable"},
                }
            return super().deliver_latest_release(vault)

    runtime = BlippedDeliveryRuntime(_identity("1.81.0", "b"))
    run = _execute(
        tmp_path,
        runtime,
        source_repo=source_repo,
        source_commit=source_commit,
    )

    assert run.case["reached_follow_up"] is True
    assert runtime.delivery_attempts == 3
    assert slept == list(executor._TRANSIENT_DELIVERY_BACKOFF_SECONDS)
    transcript = json.loads(
        (tmp_path / "case.evidence" / "journey-transcript.json").read_text()
    )
    events = {event["id"]: event for event in transcript["events"]}
    assert events["foundation-preview"]["journey_transport"] == {"attempt_count": 3}
    assert events["bridge-foundation"]["journey_transport"] == {"attempt_count": 1}
    assert not (
        tmp_path / "case.evidence" / "follow-up-delivery-failure.diagnostic.json"
    ).exists()


def test_transient_network_delivery_error_is_retried_without_a_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo, source_commit = _executor_source_commit(tmp_path)
    monkeypatch.setattr(executor.time, "sleep", lambda _delay: None)

    class DnsBlippedDeliveryRuntime(_Runtime):
        delivery_attempts = 0

        def deliver_latest_release(self, vault: Path) -> dict[str, object]:
            self.delivery_attempts += 1
            if self.delivery_attempts == 1:
                raise executor.ExecutorError(
                    "fatal: unable to access 'https://github.com/davekilleen/Dex.git/':"
                    " Could not resolve host: github.com"
                )
            return super().deliver_latest_release(vault)

    runtime = DnsBlippedDeliveryRuntime(_identity("1.81.0", "b"))
    run = _execute(
        tmp_path,
        runtime,
        source_repo=source_repo,
        source_commit=source_commit,
    )

    assert run.case["reached_follow_up"] is True
    assert runtime.delivery_attempts == 2
    transcript = json.loads(
        (tmp_path / "case.evidence" / "journey-transcript.json").read_text()
    )
    events = {event["id"]: event for event in transcript["events"]}
    assert events["foundation-preview"]["journey_transport"] == {"attempt_count": 2}


def test_non_network_delivery_failure_is_never_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo, source_commit = _executor_source_commit(tmp_path)
    monkeypatch.setattr(
        executor.time,
        "sleep",
        lambda _delay: pytest.fail("a non-network delivery failure must not back off"),
    )

    class BrokenDeliveryRuntime(_Runtime):
        def deliver_latest_release(self, vault: Path) -> dict[str, object]:
            self.calls.append("deliver_latest_release")
            return {
                "status": "not-delivered",
                "evidence": {"reason": "evidence-invalid"},
            }

    runtime = BrokenDeliveryRuntime(_identity("1.81.0", "b"))
    with pytest.raises(executor.ExecutorError, match="did not prove"):
        _execute(
            tmp_path,
            runtime,
            source_repo=source_repo,
            source_commit=source_commit,
        )

    assert runtime.calls.count("deliver_latest_release") == 1
    diagnostic = json.loads(
        (
            tmp_path / "case.evidence" / "follow-up-delivery-failure.diagnostic.json"
        ).read_text()
    )
    assert diagnostic["delivery"]["failure_reason"] == "evidence-invalid"
    assert diagnostic["delivery"]["attempt_count"] == 1


def test_transient_network_delivery_still_fails_after_bounded_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo, source_commit = _executor_source_commit(tmp_path)
    slept: list[float] = []
    monkeypatch.setattr(executor.time, "sleep", slept.append)

    class OfflineDeliveryRuntime(_Runtime):
        def deliver_latest_release(self, vault: Path) -> dict[str, object]:
            self.calls.append("deliver_latest_release")
            return {
                "status": "not-delivered",
                "evidence": {"reason": "network-unavailable"},
            }

    runtime = OfflineDeliveryRuntime(_identity("1.81.0", "b"))
    with pytest.raises(executor.ExecutorError, match="did not prove"):
        _execute(
            tmp_path,
            runtime,
            source_repo=source_repo,
            source_commit=source_commit,
        )

    assert runtime.calls.count("deliver_latest_release") == 3
    assert slept == list(executor._TRANSIENT_DELIVERY_BACKOFF_SECONDS)
    diagnostic = json.loads(
        (
            tmp_path / "case.evidence" / "follow-up-delivery-failure.diagnostic.json"
        ).read_text()
    )
    assert diagnostic["delivery"]["failure_reason"] == "network-unavailable"
    assert diagnostic["delivery"]["attempt_count"] == 3


def test_transient_network_bridge_failure_retries_with_fresh_exact_approvals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo, source_commit = _executor_source_commit(tmp_path)
    monkeypatch.setattr(executor.time, "sleep", lambda _delay: None)

    class BlippedBridgeRuntime(_Runtime):
        def bridge_to_foundation(self, vault: Path, foundation, *, input_fn, output_fn):
            if self.calls.count("bridge") == 0:
                self.calls.append("bridge")
                assert input_fn("topology approval") == "APPLY"
                raise executor.ExecutorError(
                    "curl: (6) Could not resolve host: github.com"
                )
            return super().bridge_to_foundation(
                vault,
                foundation,
                input_fn=input_fn,
                output_fn=output_fn,
            )

    runtime = BlippedBridgeRuntime(_identity("1.81.0", "b"))
    run = _execute(
        tmp_path,
        runtime,
        source_repo=source_repo,
        source_commit=source_commit,
    )

    assert run.case["reached_foundation"] is True
    assert runtime.calls.count("bridge") == 2
    transcript = json.loads(
        (tmp_path / "case.evidence" / "journey-transcript.json").read_text()
    )
    events = {event["id"]: event for event in transcript["events"]}
    assert events["bridge-foundation"]["journey_transport"] == {"attempt_count": 2}
    assert events["bridge-foundation"]["approval_count"] == 3
    assert len(events["bridge-foundation"]["approvals"]) == 3


def test_non_network_bridge_failure_is_never_retried(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_repo, source_commit = _executor_source_commit(tmp_path)
    monkeypatch.setattr(
        executor.time,
        "sleep",
        lambda _delay: pytest.fail("a non-network bridge failure must not back off"),
    )

    class RefusingBridgeRuntime(_Runtime):
        def bridge_to_foundation(self, vault: Path, foundation, *, input_fn, output_fn):
            self.calls.append("bridge")
            raise executor.ExecutorError(
                "foundation cache does not match the pinned official release"
            )

    runtime = RefusingBridgeRuntime(_identity("1.81.0", "b"))
    with pytest.raises(executor.ExecutorError, match="foundation cache"):
        _execute(
            tmp_path,
            runtime,
            source_repo=source_repo,
            source_commit=source_commit,
        )

    assert runtime.calls.count("bridge") == 1


def test_controlled_fleet_approval_still_rejects_excess_bridge_prompts(
    tmp_path: Path,
) -> None:
    protocol = load_update_journey_protocol(
        (REPO_ROOT / "core/update/journey-protocol-v1.json").read_bytes()
    )
    source_repo, source_commit = _executor_source_commit(tmp_path)

    class ExcessApprovalRuntime(_Runtime):
        def bridge_to_foundation(
            self, vault: Path, foundation, *, input_fn, output_fn
        ):
            del vault, foundation, output_fn
            for index in range(protocol.bridge.approval_count + 1):
                input_fn(f"controlled approval {index + 1}")
            pytest.fail("the executor must reject an excess controlled approval")

    with pytest.raises(executor.ExecutorError, match="approval was not exact"):
        _execute(
            tmp_path,
            ExcessApprovalRuntime(_identity("1.81.0", "b")),
            source_repo=source_repo,
            source_commit=source_commit,
            input_fn=lambda _prompt: protocol.bridge.approval_word,
        )


def test_already_installed_foundation_executes_and_validates_without_a_fake_transaction(
    tmp_path: Path,
) -> None:
    protocol = load_update_journey_protocol(
        (REPO_ROOT / "core/update/journey-protocol-v1.json").read_bytes()
    )
    source_repo, source_commit = _executor_source_commit(tmp_path)

    class AlreadyInstalledRuntime(_Runtime):
        def bridge_to_foundation(
            self, vault: Path, foundation, *, input_fn, output_fn
        ):
            self.calls.append("bridge")
            self.installed = foundation["commit"]
            return {
                "foundation": dict(foundation),
                "topology_receipt": {
                    "skipped": "foundation-already-installed"
                },
                "delivery_receipt": {
                    "skipped": "foundation-already-installed"
                },
                "mcp_registration_receipt": {
                    "skipped": "mcp-already-registered"
                },
            }

    runtime = AlreadyInstalledRuntime(_identity("1.81.0", "b"))
    run = _execute(
        tmp_path,
        runtime,
        source_repo=source_repo,
        source_commit=source_commit,
    )
    evidence = tmp_path / "case.evidence"
    transcript = json.loads((evidence / "journey-transcript.json").read_text())
    foundation_receipt = json.loads(
        (evidence / "foundation-receipt.json").read_text()
    )

    assert run.case["reached_foundation"] is True
    assert transcript["events"][2]["approval_count"] == 0
    assert "transaction_id" not in json.dumps(foundation_receipt)
    assert foundation_receipt["release"] == protocol.foundation
    assert release_fleet._valid_foundation_bridge_receipt(
        foundation_receipt["receipt"],
        expected_foundation=protocol.foundation,
        approval_count=0,
    )


def test_already_installed_foundation_can_finish_one_approved_mcp_registration(
    tmp_path: Path,
) -> None:
    source_repo, source_commit = _executor_source_commit(tmp_path)

    class ResumeRegistrationRuntime(_Runtime):
        def bridge_to_foundation(
            self, vault: Path, foundation, *, input_fn, output_fn
        ):
            self.calls.append("bridge")
            output_fn(json.dumps({"preview": "mcp-registration"}))
            assert input_fn("mcp approval") == "APPLY"
            self.installed = foundation["commit"]
            return {
                "foundation": dict(foundation),
                "topology_receipt": {
                    "skipped": "foundation-already-installed"
                },
                "delivery_receipt": {
                    "skipped": "foundation-already-installed"
                },
                "mcp_registration_receipt": {
                    "receipt": {"transaction_id": "mcp-registration-tx"}
                },
            }

    run = _execute(
        tmp_path,
        ResumeRegistrationRuntime(_identity("1.81.0", "b")),
        source_repo=source_repo,
        source_commit=source_commit,
    )
    evidence = tmp_path / "case.evidence"
    transcript = json.loads((evidence / "journey-transcript.json").read_text())
    foundation_receipt = json.loads(
        (evidence / "foundation-receipt.json").read_text()
    )

    assert run.case["reached_foundation"] is True
    assert transcript["events"][2]["approval_count"] == 1
    assert release_fleet._valid_foundation_bridge_receipt(
        foundation_receipt["receipt"],
        expected_foundation=foundation_receipt["release"],
        approval_count=1,
    )


def test_mutating_foundation_bridge_still_requires_a_real_delivery_receipt() -> None:
    foundation = _identity("1.80.5", "c")
    claimed_mutation = {
        "foundation": foundation,
        "topology_receipt": {"skipped": "already-brain-vault-split"},
        "delivery_receipt": {"status": "claimed-complete"},
        "mcp_registration_receipt": {"skipped": "mcp-already-registered"},
    }

    assert not release_fleet._valid_foundation_bridge_receipt(
        claimed_mutation,
        expected_foundation=foundation,
        approval_count=1,
    )


def test_executor_rejects_a_partial_already_installed_claim(
    tmp_path: Path,
) -> None:
    source_repo, source_commit = _executor_source_commit(tmp_path)

    class PartialResumeRuntime(_Runtime):
        def bridge_to_foundation(
            self, vault: Path, foundation, *, input_fn, output_fn
        ):
            self.calls.append("bridge")
            self.installed = foundation["commit"]
            return {
                "foundation": dict(foundation),
                "topology_receipt": {"status": "claimed-complete"},
                "delivery_receipt": {
                    "skipped": "foundation-already-installed"
                },
                "mcp_registration_receipt": {
                    "skipped": "foundation-already-installed"
                },
            }

    with pytest.raises(executor.ExecutorError, match="transaction receipt"):
        _execute(
            tmp_path,
            PartialResumeRuntime(_identity("1.81.0", "b")),
            source_repo=source_repo,
            source_commit=source_commit,
        )


def test_executor_refuses_user_content_mutation_and_unhealthy_proof(
    tmp_path: Path,
) -> None:
    source_repo, source_commit = _executor_source_commit(tmp_path)

    class MutatingRuntime(_Runtime):
        def bridge_to_foundation(
            self, vault: Path, foundation, *, input_fn, output_fn
        ):
            result = super().bridge_to_foundation(
                vault,
                foundation,
                input_fn=input_fn,
                output_fn=output_fn,
            )
            (vault / "00-Inbox/keep.md").write_text(
                "mutated by update\n",
                encoding="utf-8",
            )
            return result

    with pytest.raises(executor.ExecutorError, match="user-owned content changed"):
        _execute(
            tmp_path,
            MutatingRuntime(_identity("1.81.0", "b")),
            source_repo=source_repo,
            source_commit=source_commit,
        )

    healthy_root = tmp_path / "unhealthy"
    healthy_root.mkdir()
    source_repo_2, source_commit_2 = _executor_source_commit(healthy_root)

    class UnhealthyRuntime(_Runtime):
        def doctor(self, vault: Path) -> dict[str, object]:
            self.calls.append("doctor")
            return {"checks": [{"id": "doctor.self", "verdict": "BROKEN"}]}

    with pytest.raises(executor.ExecutorError, match="Doctor is unhealthy"):
        _execute(
            healthy_root,
            UnhealthyRuntime(_identity("1.81.0", "b")),
            source_repo=source_repo_2,
            source_commit=source_commit_2,
        )


def test_production_runtime_refuses_undeclared_lifecycle_operation() -> None:
    with pytest.raises(executor.ExecutorError, match="not declared"):
        executor._ProductionRuntime._service_call(
            object(),
            "run_any_command",
        )


@pytest.mark.parametrize(
    (
        "foundation_installed",
        "use_foundation_cache",
        "use_follow_up_cache",
        "expected_cleaned",
    ),
    (
        (False, False, False, [True]),
        (True, True, False, []),
        (True, False, True, []),
    ),
)
def test_fixture_runtime_server_exposes_only_fixed_bridge_and_lifecycle_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    foundation_installed: bool,
    use_foundation_cache: bool,
    use_follow_up_cache: bool,
    expected_cleaned: list[bool],
) -> None:
    cleaned: list[bool] = []
    delivery_arguments: list[dict[str, object]] = []

    class Temporary:
        def cleanup(self) -> None:
            cleaned.append(True)

    class Service:
        @staticmethod
        def deliver_latest_release(
            vault: Path,
            **kwargs: object,
        ) -> dict[str, object]:
            delivery_arguments.append(kwargs)
            return {"status": "delivered", "vault": str(vault)}

    def run_bridge(vault, service, *, pin, input_fn, output_fn):
        assert service.__class__ is Service
        assert pin is executor.dex_update_bridge.FOUNDATION
        output_fn("exact topology preview")
        assert input_fn("exact topology prompt") == "APPLY"
        return {
            "foundation": pin.identity(),
            "topology_receipt": {"receipt": {"transaction_id": "topology"}},
            "delivery_receipt": {"receipt": {"transaction_id": "foundation"}},
            "mcp_registration_receipt": {
                "receipt": {"transaction_id": "mcp-registration"}
            },
        }

    monkeypatch.setattr(
        executor.dex_update_bridge,
        "_validate_vault",
        lambda vault: vault,
    )
    monkeypatch.setattr(
        executor.dex_update_bridge,
        "_foundation_is_installed",
        lambda *_args: foundation_installed,
    )
    monkeypatch.setattr(
        executor.dex_update_bridge,
        "acquire_foundation_source",
        lambda: (Temporary(), tmp_path / "foundation"),
    )
    monkeypatch.setattr(
        executor.dex_update_bridge,
        "_load_lifecycle_service",
        lambda _source: Service(),
    )
    monkeypatch.setattr(executor.dex_update_bridge, "run_bridge", run_bridge)
    monkeypatch.setattr(
        executor,
        "_load_released_bridge",
        lambda _asset, _digest: executor.dex_update_bridge,
    )
    monkeypatch.setattr(
        executor,
        "_validate_follow_up_cache",
        lambda cache, _release: cache.resolve(),
    )
    request_stream = io.StringIO(
        "\n".join(
            (
                '{"operation":"bridge"}',
                '{"answer":"APPLY"}',
                '{"operation":"deliver_latest_release"}',
                '{"operation":"close"}',
                "",
            )
        )
    )
    response_stream = io.StringIO()
    monkeypatch.setattr(executor.sys, "stdin", request_stream)
    monkeypatch.setattr(executor.sys, "stdout", response_stream)

    assert (
            executor._runtime_server(
                tmp_path / "vault",
                bridge_asset=REPO_ROOT / "scripts/dex_update_bridge.py",
                bridge_sha256=hashlib.sha256(
                    (REPO_ROOT / "scripts/dex_update_bridge.py").read_bytes()
                ).hexdigest(),
                foundation_cache=(
                    tmp_path / "unused-cache"
                    if use_foundation_cache
                    else None
                ),
                follow_up_cache=(
                    tmp_path / "candidate-release.git"
                    if use_follow_up_cache
                    else None
                ),
                follow_up_release=(
                    _identity("1.81.8", "b") if use_follow_up_cache else None
                ),
        )
        == 0
    )

    messages = [
        json.loads(line)
        for line in response_stream.getvalue().splitlines()
    ]
    assert [message["kind"] for message in messages] == [
        "ready",
        "output",
        "prompt",
        "result",
        "result",
    ]
    assert messages[1]["text"] == "exact topology preview"
    assert messages[2]["prompt"] == "exact topology prompt"
    assert messages[4]["value"]["status"] == "delivered"
    assert delivery_arguments == (
        [
            {
                "remote_url": str(
                    (tmp_path / "candidate-release.git").resolve()
                ),
                "allow_test_transport": True,
            }
        ]
        if use_follow_up_cache
        else [{}]
    )
    assert cleaned == expected_cleaned
