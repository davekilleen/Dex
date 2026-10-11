"""DEX-240: check_onboarding_complete must read markers written by provision.cjs."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

from core.mcp import onboarding_server


def _call(name: str) -> dict:
    result = asyncio.run(onboarding_server.handle_call_tool(name, {}))
    return json.loads(result[0].text)


def test_age_of_utc_z_marker_from_provision_cjs() -> None:
    now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    assert onboarding_server.marker_age_days("2026-10-06T11:59:00.000Z", now=now) == 3


def test_age_of_naive_marker_written_by_python() -> None:
    now = datetime(2026, 10, 9, 12, 0)
    assert onboarding_server.marker_age_days("2026-10-01T12:00:00", now=now) == 8


def test_age_of_offset_marker() -> None:
    now = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
    assert onboarding_server.marker_age_days("2026-10-09T10:00:00+02:00", now=now) == 0


def test_check_onboarding_complete_reads_js_marker(tmp_path, monkeypatch) -> None:
    marker = tmp_path / ".onboarding-complete"
    written = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(timespec="milliseconds")
    marker.write_text(
        json.dumps({"completed_at": written.replace("+00:00", "Z"), "user_name": "Ada", "role": "PM"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(onboarding_server, "MARKER_FILE", marker)
    payload = _call("check_onboarding_complete")
    assert payload.get("success") is not False, payload
    data = payload.get("data", payload)
    assert data["complete"] is True
    assert data["age_days"] == 2
    assert data["is_new_vault"] is True
