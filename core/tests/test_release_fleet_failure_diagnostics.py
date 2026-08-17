"""Failure-only diagnostics for the closed historic update executor."""

from __future__ import annotations

import hashlib
import json
import stat
import subprocess
from pathlib import Path

import pytest

from core.update.journey_protocol import load_update_journey_protocol
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


def _released_executor_source(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "released-source"
    source.mkdir()
    subprocess.run(["git", "init", "--quiet"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Dex Tests"], cwd=source, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.com"], cwd=source, check=True
    )
    for relative in (
        "scripts/dex_update_bridge.py",
        "scripts/release_fleet.py",
        "scripts/release_fleet_executor.py",
    ):
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((REPO_ROOT / relative).read_bytes())
    subprocess.run(["git", "add", "-A"], cwd=source, check=True)
    subprocess.run(
        ["git", "commit", "--quiet", "-m", "released executor"],
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
    return source, commit


def _vault(tmp_path: Path) -> tuple[Path, tuple[str, ...]]:
    vault = tmp_path / "vault"
    user_paths = (
        "00-Inbox/keep.md",
        "03-Tasks/Tasks.md",
        "System/user-profile.yaml",
        ".claude/skills/my-weekly-review/SKILL.md",
    )
    for relative in user_paths:
        target = vault / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"user-owned:{relative}\n", encoding="utf-8")
    # This deliberately looks like a sensitive user config. Diagnostics must
    # neither read nor serialize it.
    (vault / ".mcp.json").write_text(
        '{"token":"TOP-SECRET-NOT-FOR-DIAGNOSTICS"}\n', encoding="utf-8"
    )
    (vault / "System/.release-catalog.json").write_text("{}\n", encoding="utf-8")
    (vault / "System/.installed-files.manifest").write_text("{}\n", encoding="utf-8")
    return vault, user_paths


class _Runtime:
    def __init__(self, follow_up: dict[str, str], *, failure: str) -> None:
        self.follow_up = follow_up
        self.failure = failure
        self.installed = ""
        self.doctor_calls = 0

    def bridge_to_foundation(self, vault, foundation, *, input_fn, output_fn):
        for prompt in ("topology", "foundation", "mcp"):
            assert input_fn(prompt) == "APPLY"
        self.installed = foundation["commit"]
        return {
            "foundation": dict(foundation),
            "topology_receipt": {"receipt": {"transaction_id": "topology"}},
            "delivery_receipt": {"receipt": {"transaction_id": "foundation"}},
            "mcp_registration_receipt": {"receipt": {"transaction_id": "mcp"}},
        }

    def installed_release(self, vault):
        return self.installed

    def doctor(self, vault):
        self.doctor_calls += 1
        broken = (self.failure == "foundation-doctor" and self.doctor_calls == 1) or (
            self.failure == "follow-up-doctor" and self.doctor_calls == 2
        )
        verdict = "BROKEN" if broken else "OK"
        return {
            "checks": [
                {
                    "id": "doctor.dependency",
                    "verdict": verdict,
                    "detail": "TOP-SECRET-NOT-FOR-DIAGNOSTICS",
                }
            ]
        }

    def deliver_latest_release(self, vault):
        if self.failure == "follow-up-delivery":
            return {
                "status": "unexpected: TOP-SECRET-NOT-FOR-DIAGNOSTICS",
                "release": {"opaque": "TOP-SECRET-NOT-FOR-DIAGNOSTICS"},
                "evidence": {
                    "reason": "TOP-SECRET-NOT-FOR-DIAGNOSTICS",
                },
            }
        if self.failure == "public-route-drift":
            return {
                "status": "delivered",
                "release": _identity("1.81.6", "c"),
                "unsafe": {
                    "token": "TOP-SECRET-NOT-FOR-DIAGNOSTICS",
                },
            }
        return {"status": "delivered", "release": self.follow_up}

    def build_and_preview_delivered_release(self, vault, release):
        return {
            "preview": {"release": dict(release), "writes": []},
            "approval_token": "exact-token",
        }

    def execute_approved_delivered_release(self, vault, preview, approved_token):
        assert approved_token == "exact-token"
        self.installed = self.follow_up["commit"]
        return {
            "receipt": {"transaction_id": "follow-up"},
            "release": self.follow_up,
        }

    def smoke(self, vault):
        return {
            "journeys": [{"id": "topology", "verdict": "OK"}],
            "summary": {"broken": 0, "unknown": 0},
        }


def _run_failure(
    tmp_path: Path,
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    expected_error: type[executor.ExecutorError] = executor.ExecutorError,
) -> Path:
    source, source_commit = _released_executor_source(tmp_path)
    monkeypatch.setattr(
        executor,
        "_verify_released_executor",
        lambda *_args, **_kwargs: {"source_commit": "test-only"},
    )
    vault, user_paths = _vault(tmp_path)
    protocol = load_update_journey_protocol(
        (REPO_ROOT / "core/update/journey-protocol-v1.json").read_bytes()
    )
    starting = _identity("1.65.0", "a")
    follow_up = _identity("1.81.5", "b")
    bridge_name = f"dex-update-bridge-v{follow_up['version']}.py"
    checksum = f"{protocol.bridge.artifact.sha256}  {bridge_name}\n".encode()
    with pytest.raises(expected_error) as error:
        executor.execute_journey(
            repo_root=source,
            source_commit=source_commit,
            vault_root=vault,
            evidence_root=tmp_path / "case.evidence",
            starting_release=starting,
            foundation_release=protocol.foundation,
            follow_up_release=follow_up,
            protocol=protocol,
            historic_surface={"release": starting, "machine_executable": False},
            foundation_surface={
                "release": protocol.foundation,
                "machine_executable": False,
            },
            user_owned_paths=user_paths,
            platform="darwin",
            bridge_asset_evidence={
                "name": bridge_name,
                "sha256": protocol.bridge.artifact.sha256,
                "checksum_name": f"{bridge_name}.sha256",
                "checksum_sha256": hashlib.sha256(checksum).hexdigest(),
                "source": "released-standalone-asset",
            },
            bridge_asset_path=REPO_ROOT / protocol.bridge.artifact.source_path,
            initial_install_evidence={
                "topology": "legacy-monolithic",
                "brain_refs": [],
            },
            input_fn=lambda _prompt: "APPLY",
            output_fn=lambda _line: None,
            _runtime=_Runtime(follow_up, failure=failure),
        )
    assert "failure diagnostic could not be retained safely" not in str(error.value)
    expected = {
        "foundation-doctor": "foundation Doctor is unhealthy",
        "follow-up-delivery": "lifecycle delivery did not prove",
        "follow-up-doctor": "follow-up Doctor is unhealthy",
        "public-route-drift": "public release route drifted",
    }[failure]
    assert expected in str(error.value)
    return tmp_path / "case.evidence"


@pytest.mark.parametrize(
    ("failure", "artifact", "phase"),
    (
        (
            "foundation-doctor",
            "foundation-doctor-failure.diagnostic.json",
            "foundation-doctor",
        ),
        (
            "follow-up-delivery",
            "follow-up-delivery-failure.diagnostic.json",
            "follow-up-delivery",
        ),
        (
            "follow-up-doctor",
            "follow-up-doctor-failure.diagnostic.json",
            "follow-up-doctor",
        ),
    ),
)
def test_failed_journey_retains_only_private_sanitized_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    artifact: str,
    phase: str,
) -> None:
    evidence = _run_failure(tmp_path, failure, monkeypatch)
    diagnostic = evidence / artifact
    document = json.loads(diagnostic.read_text(encoding="utf-8"))

    assert document["acceptance"] is False
    assert document["kind"] == "local-failure-diagnostic"
    assert document["phase"] == phase
    serialized = diagnostic.read_text(encoding="utf-8")
    assert "TOP-SECRET-NOT-FOR-DIAGNOSTICS" not in serialized
    assert ".mcp.json" not in serialized
    assert set(document["runtime_metadata"]) == {
        "System/.installed-files.manifest",
        "System/.release-catalog.json",
    }
    assert stat.S_IMODE(evidence.stat().st_mode) == 0o700
    assert stat.S_IMODE(diagnostic.stat().st_mode) == 0o600
    assert not (evidence / "journey-result.json").exists()
    assert not (evidence / "evidence-manifest.json").exists()
    assert not (evidence / "journey-transcript.json").exists()
    if "doctor" in failure:
        assert document["doctor"] == {
            "check_count": 1,
            "checks": [{"id": "doctor.dependency", "verdict": "BROKEN"}],
            "details": "redacted",
        }
    else:
        assert document["delivery"] == {
            "attempt_count": 1,
            "elapsed_ms": document["delivery"]["elapsed_ms"],
            "failure_reason": "unclassified",
            "release_matches_expected": False,
            "status": "not-delivered",
        }
        assert isinstance(document["delivery"]["elapsed_ms"], int)
        assert 0 <= document["delivery"]["elapsed_ms"] <= 900_000


def test_closed_delivery_mismatch_is_shared_public_route_drift_with_safe_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = _run_failure(
        tmp_path,
        "public-route-drift",
        monkeypatch,
        expected_error=executor.PublicRouteDriftError,
    )
    diagnostic = evidence / "follow-up-delivery-failure.diagnostic.json"
    document = json.loads(diagnostic.read_text(encoding="utf-8"))

    assert document["delivery"] == {
        "attempt_count": 1,
        "delivered_release": _identity("1.81.6", "c"),
        "elapsed_ms": document["delivery"]["elapsed_ms"],
        "failure_reason": "public-route-drift",
        "release_matches_expected": False,
        "status": "delivered",
    }
    serialized = diagnostic.read_text(encoding="utf-8")
    assert "TOP-SECRET-NOT-FOR-DIAGNOSTICS" not in serialized
    assert ".mcp.json" not in serialized


def test_public_route_drift_identity_returns_only_a_closed_mismatch() -> None:
    expected = _identity("1.81.5", "b")
    delivered = _identity("1.81.6", "c")

    assert executor._public_route_drift_identity(
        {"status": "delivered", "release": delivered},
        expected,
    ) == delivered
    assert (
        executor._public_route_drift_identity(
            {"status": "delivered", "release": expected},
            expected,
        )
        is None
    )
    assert (
        executor._public_route_drift_identity(
            {"status": "delivered", "release": {"unsafe": "value"}},
            expected,
        )
        is None
    )
    assert (
        executor._public_route_drift_identity(
            {"status": "not-delivered", "release": delivered},
            expected,
        )
        is None
    )


def test_failure_diagnostic_retains_only_allowlisted_delivery_reason(
    tmp_path: Path,
) -> None:
    vault, _user_paths = _vault(tmp_path)
    document = executor._failure_diagnostic(
        phase="follow-up-delivery",
        vault=vault,
        foundation=_identity("1.81.0", "a"),
        follow_up=_identity("1.81.10", "b"),
        delivery={
            "status": "not-delivered",
            "evidence": {"reason": "evidence-invalid"},
        },
        delivery_elapsed_ms=1_000_000,
    )

    assert document["delivery"] == {
        "attempt_count": 1,
        "elapsed_ms": 900_000,
        "failure_reason": "evidence-invalid",
        "release_matches_expected": False,
        "status": "not-delivered",
    }

    unclassified = executor._failure_diagnostic(
        phase="follow-up-delivery",
        vault=vault,
        foundation=_identity("1.81.0", "a"),
        follow_up=_identity("1.81.10", "b"),
        delivery={"status": "not-delivered", "evidence": {"reason": ["unsafe"]}},
        delivery_elapsed_ms=-1,
    )
    assert unclassified["delivery"]["failure_reason"] == "unclassified"
    assert unclassified["delivery"]["elapsed_ms"] == 0


def test_failure_diagnostic_is_atomic_and_never_overwrites_existing_file(
    tmp_path: Path,
) -> None:
    evidence = tmp_path / "case.evidence"
    evidence.mkdir(mode=0o700)
    evidence.chmod(0o700)
    destination = evidence / "foundation-doctor-failure.diagnostic.json"
    destination.write_text("original diagnostic\n", encoding="utf-8")
    destination.chmod(0o600)

    with pytest.raises(executor.ExecutorError, match="could not be retained safely"):
        executor._write_failure_diagnostic(
            evidence,
            destination.name,
            {"acceptance": False, "kind": "local-failure-diagnostic"},
        )

    assert destination.read_text(encoding="utf-8") == "original diagnostic\n"
    assert list(evidence.glob("*.tmp")) == []


def test_failure_diagnostic_never_removes_a_preexisting_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = tmp_path / "case.evidence"
    evidence.mkdir(mode=0o700)
    evidence.chmod(0o700)
    name = "foundation-doctor-failure.diagnostic.json"
    timestamp = 123456
    monkeypatch.setattr(executor.time, "time_ns", lambda: timestamp)
    temporary = evidence / f".{name}.{executor.os.getpid()}.{timestamp}.tmp"
    temporary.write_text("another process owns this\n", encoding="utf-8")

    with pytest.raises(executor.ExecutorError, match="could not be retained safely"):
        executor._write_failure_diagnostic(
            evidence,
            name,
            {"acceptance": False, "kind": "local-failure-diagnostic"},
        )

    assert temporary.read_text(encoding="utf-8") == "another process owns this\n"


def test_safe_metadata_does_not_follow_a_symlink_swapped_after_lstat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault, _ = _vault(tmp_path)
    relative = "System/.release-catalog.json"
    candidate = vault / relative
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET-NOT-FOR-DIAGNOSTICS\n", encoding="utf-8")
    original_open = executor.os.open
    swapped = False

    def swap_before_open(path, *args, **kwargs):
        nonlocal swapped
        if Path(path) == candidate and not swapped:
            swapped = True
            candidate.unlink()
            candidate.symlink_to(secret)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(executor.os, "open", swap_before_open)

    metadata = executor._safe_file_metadata(vault, relative)

    assert swapped
    assert metadata["state"] in {"unreadable", "changed"}
    assert "sha256" not in metadata
    assert "TOP-SECRET-NOT-FOR-DIAGNOSTICS" not in json.dumps(metadata)


def test_failure_diagnostic_cleans_temporary_file_when_file_fsync_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = tmp_path / "case.evidence"
    evidence.mkdir(mode=0o700)
    evidence.chmod(0o700)
    original_fsync = executor.os.fsync
    calls = 0

    def fail_first_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("injected fsync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(executor.os, "fsync", fail_first_fsync)

    with pytest.raises(executor.ExecutorError, match="could not be retained safely"):
        executor._write_failure_diagnostic(
            evidence,
            "foundation-doctor-failure.diagnostic.json",
            {"acceptance": False, "kind": "local-failure-diagnostic"},
        )

    assert not (evidence / "foundation-doctor-failure.diagnostic.json").exists()
    assert list(evidence.glob("*.tmp")) == []


# --- TLS-trust routing and detail retention ---------------------------------


def test_tls_untrusted_delivery_is_retried_as_a_transient_network_fault() -> None:
    """A TLS-inspecting proxy is momentary for the fleet, exactly like a dropped link."""
    assert "tls-untrusted" in executor._TRANSIENT_NETWORK_DELIVERY_REASONS
    assert executor._transient_network_delivery(
        {"status": "not-delivered", "evidence": {"reason": "tls-untrusted"}}
    )
    assert executor._transient_network_error(
        "fatal: unable to access 'https://github.com/davekilleen/Dex.git/': "
        "SSL certificate problem: self signed certificate"
    )
    assert "ssl certificate problem" in executor._TRANSIENT_NETWORK_ERROR_FRAGMENTS
    assert "self signed certificate" in executor._TRANSIENT_NETWORK_ERROR_FRAGMENTS
    # Bounded retry is unchanged: three attempts, 10s then 30s.
    assert executor._TRANSIENT_DELIVERY_MAX_ATTEMPTS == 3
    assert executor._TRANSIENT_DELIVERY_BACKOFF_SECONDS == (10.0, 30.0)


def test_failure_diagnostic_keeps_tls_untrusted_as_a_classified_reason(
    tmp_path: Path,
) -> None:
    vault, _user_paths = _vault(tmp_path)
    document = executor._failure_diagnostic(
        phase="follow-up-delivery",
        vault=vault,
        foundation=_identity("1.81.0", "a"),
        follow_up=_identity("1.81.10", "b"),
        delivery={
            "status": "not-delivered",
            "evidence": {"reason": "tls-untrusted"},
        },
    )

    assert document["delivery"]["failure_reason"] == "tls-untrusted"


def test_failure_diagnostic_retains_the_sanitized_underlying_detail(
    tmp_path: Path,
) -> None:
    """Dropping the detail is why diagnosing a proxy fault took hours, not one cat."""
    vault, _user_paths = _vault(tmp_path)
    document = executor._failure_diagnostic(
        phase="follow-up-delivery",
        vault=vault,
        foundation=_identity("1.81.0", "a"),
        follow_up=_identity("1.81.10", "b"),
        delivery={
            "status": "not-delivered",
            "evidence": {
                "reason": "tls-untrusted",
                "detail": (
                    "fatal: unable to access "
                    "'https://github.com/davekilleen/Dex.git/': "
                    "SSL certificate problem: self signed certificate"
                ),
            },
        },
    )

    detail = document["delivery"]["detail"]
    assert "SSL certificate problem: self signed certificate" in detail


def test_failure_diagnostic_detail_is_bounded_and_strips_credentials(
    tmp_path: Path,
) -> None:
    vault, _user_paths = _vault(tmp_path)
    secret = "ghp_" + "A" * 36
    document = executor._failure_diagnostic(
        phase="follow-up-delivery",
        vault=vault,
        foundation=_identity("1.81.0", "a"),
        follow_up=_identity("1.81.10", "b"),
        delivery={
            "status": "not-delivered",
            "evidence": {
                "reason": "evidence-invalid",
                "detail": (
                    f"fatal: unable to access 'https://dave:{secret}@github.com/x.git/'"
                    f" Authorization: Bearer {secret} token={secret} "
                    + "padding " * 400
                ),
            },
        },
    )

    detail = document["delivery"]["detail"]
    assert secret not in detail
    assert "dave:" not in detail
    assert len(detail) <= 512


def test_failure_diagnostic_omits_detail_when_the_foundation_supplies_none(
    tmp_path: Path,
) -> None:
    vault, _user_paths = _vault(tmp_path)
    document = executor._failure_diagnostic(
        phase="follow-up-delivery",
        vault=vault,
        foundation=_identity("1.81.0", "a"),
        follow_up=_identity("1.81.10", "b"),
        delivery={"status": "not-delivered", "evidence": {"reason": "evidence-invalid"}},
    )

    assert "detail" not in document["delivery"]
    document_bad_detail = executor._failure_diagnostic(
        phase="follow-up-delivery",
        vault=vault,
        foundation=_identity("1.81.0", "a"),
        follow_up=_identity("1.81.10", "b"),
        delivery={
            "status": "not-delivered",
            "evidence": {"reason": "evidence-invalid", "detail": ["unsafe"]},
        },
    )
    assert "detail" not in document_bad_detail["delivery"]
