#!/usr/bin/env python3
"""Send an explicitly opted-in, counts-only nightly smoke verdict."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import uuid
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

RUNNER_ROOT = Path(__file__).resolve().parents[2]
if str(RUNNER_ROOT) in sys.path:
    sys.path.remove(str(RUNNER_ROOT))
sys.path.insert(0, str(RUNNER_ROOT))

from core.mcp.analytics_helper import get_analytics_transport

SCHEMA_VERSION = 1
EVENT_NAME = "smoke_verdict"
DEFAULT_CHANNEL = "stable"
POST_TIMEOUT_SECONDS = 5
COUNT_KEYS = ("ok", "broken", "unknown", "off")
KNOWN_JOURNEY_IDS = frozenset({"configs", "task_lifecycle", "mcp_startup", "skills", "hooks"})
HEALTH_CONSENT_PATTERN = re.compile(
    r"^\*\*Health telemetry:\*\* (opted-in|opted-out|pending)$",
    re.MULTILINE,
)

TransportGetter = Callable[[], Mapping[str, Any]]
PostFunction = Callable[..., Any]


def read_health_consent(vault_root: Path) -> str:
    """Read the separate health-telemetry decision, failing closed to pending."""
    try:
        content = (vault_root / "System" / "usage_log.md").read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return "pending"

    decisions = HEALTH_CONSENT_PATTERN.findall(content)
    if len(decisions) != 1:
        return "pending"
    return decisions[0]


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def get_or_create_telemetry_id(vault_root: Path) -> str:
    """Return the install-scoped anonymous UUID, creating it after opt-in."""
    telemetry_path = vault_root / "System" / ".dex" / "telemetry-id"
    try:
        existing = telemetry_path.read_text(encoding="utf-8").strip()
        return str(uuid.UUID(existing))
    except (FileNotFoundError, ValueError, UnicodeError):
        telemetry_id = str(uuid.uuid4())
        _atomic_write(telemetry_path, telemetry_id + "\n")
        return telemetry_id


def _read_dex_version(repo_root: Path) -> str:
    package = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))
    version = package.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("package.json has no Dex version")
    return version


def _counts(report: Mapping[str, Any]) -> dict[str, int]:
    summary = report.get("summary")
    if not isinstance(summary, Mapping):
        raise ValueError("smoke report has no summary")

    counts: dict[str, int] = {}
    for key in COUNT_KEYS:
        value = summary.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"smoke report has invalid {key} count")
        counts[key] = value
    return counts


def _worst_journey_id(report: Mapping[str, Any]) -> str | None:
    journeys = report.get("journeys")
    if not isinstance(journeys, list):
        return None
    for verdict in ("BROKEN", "UNKNOWN"):
        for journey in journeys:
            if not isinstance(journey, Mapping) or journey.get("verdict") != verdict:
                continue
            journey_id = journey.get("id")
            if isinstance(journey_id, str) and journey_id in KNOWN_JOURNEY_IDS:
                return journey_id
    return None


def build_payload(
    report: Mapping[str, Any],
    *,
    telemetry_id: str | None,
    dex_version: str,
    channel: str = DEFAULT_CHANNEL,
) -> dict[str, Any]:
    """Build the complete, unenriched wire payload."""
    if not isinstance(channel, str) or not channel.strip():
        raise ValueError("channel must be a non-empty string")
    return {
        "schema_version": SCHEMA_VERSION,
        "event": EVENT_NAME,
        "counts": _counts(report),
        "worst_journey_id": _worst_journey_id(report),
        "dex_version": dex_version,
        "channel": channel,
        "telemetry_id": telemetry_id,
    }


def _append_local_record(
    vault_root: Path,
    *,
    payload: Mapping[str, Any],
    sent: bool,
    reason: str,
) -> None:
    log_path = vault_root / "System" / ".dex" / "health-telemetry-log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "attempted_at": datetime.now(timezone.utc).isoformat(),
        "sent": sent,
        "reason": reason,
        "payload": dict(payload),
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")


def send_smoke_verdict(
    report: Mapping[str, Any],
    *,
    vault_root: Path,
    repo_root: Path,
    channel: str = DEFAULT_CHANNEL,
    transport_getter: TransportGetter = get_analytics_transport,
    post: PostFunction = requests.post,
) -> dict[str, object]:
    """Record one attempt and POST it once only when health telemetry is opted in."""
    consent = read_health_consent(vault_root)
    telemetry_id = get_or_create_telemetry_id(vault_root) if consent == "opted-in" else None
    payload = build_payload(
        report,
        telemetry_id=telemetry_id,
        dex_version=_read_dex_version(repo_root),
        channel=channel,
    )

    if consent != "opted-in":
        reason = "health_telemetry_not_opted_in"
        _append_local_record(vault_root, payload=payload, sent=False, reason=reason)
        return {"sent": False, "reason": reason}

    transport = transport_getter()
    if not transport.get("configured"):
        reason = "transport_not_configured"
        _append_local_record(vault_root, payload=payload, sent=False, reason=reason)
        return {"sent": False, "reason": reason}

    try:
        response = post(
            transport["endpoint"],
            json=payload,
            headers=transport["headers"],
            timeout=POST_TIMEOUT_SECONDS,
        )
        sent = 200 <= response.status_code < 300
        reason = "sent" if sent else "http_error"
    except Exception:
        sent = False
        reason = "post_failed"

    _append_local_record(vault_root, payload=payload, sent=sent, reason=reason)
    return {"sent": sent, "reason": reason}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record and optionally send a nightly health verdict.")
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--channel", default=DEFAULT_CHANNEL)
    args = parser.parse_args(argv)

    report = json.loads(args.report.read_text(encoding="utf-8"))
    result = send_smoke_verdict(
        report,
        vault_root=args.vault,
        repo_root=args.repo,
        channel=args.channel,
    )
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
