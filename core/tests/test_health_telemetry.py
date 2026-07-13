"""Contract tests for Dex's dedicated fleet-health telemetry sender."""

from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

from core.utils import health_telemetry

REPO_ROOT = Path(__file__).resolve().parents[2]


def _report(*, broken: int = 0, unknown: int = 0) -> dict[str, object]:
    return {
        "schema_version": 1,
        "generated_at": "2026-07-13T03:15:00+00:00",
        "summary": {"ok": 5 - broken - unknown, "broken": broken, "unknown": unknown, "off": 0},
        "journeys": [
            {
                "id": "task_lifecycle",
                "verdict": "BROKEN" if broken else "OK",
                "detail": "private/path/that/must/not/leave.md",
                "duration_ms": 12,
            },
            {
                "id": "mcp_startup",
                "verdict": "UNKNOWN" if unknown else "OK",
                "detail": "another private detail",
                "duration_ms": 8,
            },
        ],
    }


def _vault(tmp_path: Path, decision: str = "opted-in") -> Path:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "usage_log.md").write_text(
        f"# Usage\n\n**Health telemetry:** {decision}\n",
        encoding="utf-8",
    )
    return vault


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text('{"version":"1.56.0"}\n', encoding="utf-8")
    return repo


def test_opted_in_posts_only_the_counts_only_contract_and_logs_it(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    repo = _repo(tmp_path)
    calls: list[dict[str, object]] = []

    class Response:
        status_code = 200

    def post(endpoint, *, json, headers, timeout):
        calls.append({"endpoint": endpoint, "json": json, "headers": headers, "timeout": timeout})
        return Response()

    result = health_telemetry.send_smoke_verdict(
        _report(broken=1),
        vault_root=vault,
        repo_root=repo,
        channel="canary",
        transport_getter=lambda: {
            "configured": True,
            "endpoint": "https://telemetry.invalid/verdict",
            "headers": {"Authorization": "Bearer test"},
        },
        post=post,
    )

    assert result == {"sent": True, "reason": "sent"}
    assert len(calls) == 1
    payload = calls[0]["json"]
    assert payload == {
        "schema_version": 1,
        "event": "smoke_verdict",
        "counts": {"ok": 4, "broken": 1, "unknown": 0, "off": 0},
        "worst_journey_id": "task_lifecycle",
        "dex_version": "1.56.0",
        "channel": "canary",
        "telemetry_id": payload["telemetry_id"],
    }
    uuid.UUID(payload["telemetry_id"])
    assert calls[0]["timeout"] == health_telemetry.POST_TIMEOUT_SECONDS

    records = [
        json.loads(line)
        for line in (vault / "System" / ".dex" / "health-telemetry-log.jsonl").read_text().splitlines()
    ]
    assert records[0]["sent"] is True
    assert records[0]["payload"] == payload


def test_transport_failure_is_logged_and_never_retried(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    repo = _repo(tmp_path)
    calls = 0

    def failing_post(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise OSError("offline")

    result = health_telemetry.send_smoke_verdict(
        _report(unknown=1),
        vault_root=vault,
        repo_root=repo,
        transport_getter=lambda: {
            "configured": True,
            "endpoint": "https://telemetry.invalid/verdict",
            "headers": {},
        },
        post=failing_post,
    )

    assert calls == 1
    assert result == {"sent": False, "reason": "post_failed"}
    record = json.loads((vault / "System" / ".dex" / "health-telemetry-log.jsonl").read_text())
    assert record["sent"] is False
    assert record["reason"] == "post_failed"
    assert record["payload"]["worst_journey_id"] == "mcp_startup"


def test_telemetry_id_is_created_only_for_opt_in_and_stable(tmp_path: Path) -> None:
    vault = _vault(tmp_path)

    first = health_telemetry.get_or_create_telemetry_id(vault)
    second = health_telemetry.get_or_create_telemetry_id(vault)

    assert first == second
    assert (vault / "System" / ".dex" / "telemetry-id").read_text().strip() == first
    uuid.UUID(first)


def test_sender_cli_can_run_from_the_nightly_worker_path() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "core" / "utils" / "health_telemetry.py"), "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--report" in result.stdout
