"""Integration and adversarial contracts for the released journey executor."""

from __future__ import annotations

import io
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from core.update.journey_protocol import load_update_journey_protocol
from scripts import release_fleet
from scripts import release_fleet_executor as executor

REPO_ROOT = Path(__file__).resolve().parents[2]


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
    subprocess.run(["git", "init", "--quiet"], cwd=source, check=True)
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
        self.installed = foundation["commit"]
        return {
            "foundation": dict(foundation),
            "topology_receipt": {"receipt": {"transaction_id": "topology-tx"}},
            "delivery_receipt": {"receipt": {"transaction_id": "foundation-tx"}},
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
        approval_count=2,
    )
    assert follow_up_receipt["receipt"]["receipt"]["transaction_id"] == "follow-up-tx"
    assert [event["id"] for event in transcript["events"]] == list(protocol.evidence)
    assert transcript["events"][2]["approval_count"] == 2
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
        platform="darwin",
        input_fn=input_fn,
        output_fn=lambda _line: None,
        _runtime=runtime,
    )


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


@pytest.mark.parametrize(
    "tag",
    (
        "refs/tags/v1.20.1",
        "v01.20.1",
        "v1.20",
        "legacy/v1.20.1",
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


def test_mutating_foundation_bridge_still_requires_a_real_delivery_receipt() -> None:
    foundation = _identity("1.80.5", "c")
    claimed_mutation = {
        "foundation": foundation,
        "topology_receipt": {"skipped": "already-brain-vault-split"},
        "delivery_receipt": {"status": "claimed-complete"},
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
    ("foundation_installed", "use_cache", "expected_cleaned"),
    ((False, False, [True]), (True, True, [])),
)
def test_fixture_runtime_server_exposes_only_fixed_bridge_and_lifecycle_messages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    foundation_installed: bool,
    use_cache: bool,
    expected_cleaned: list[bool],
) -> None:
    cleaned: list[bool] = []

    class Temporary:
        def cleanup(self) -> None:
            cleaned.append(True)

    class Service:
        @staticmethod
        def deliver_latest_release(vault: Path) -> dict[str, object]:
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
            foundation_cache=(tmp_path / "unused-cache" if use_cache else None),
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
    assert cleaned == expected_cleaned
