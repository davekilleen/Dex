"""Coverage for CLI and module entrypoints."""

from __future__ import annotations

import json
import runpy
from datetime import datetime
from pathlib import Path

import pytest

from core.ritual_intelligence import cli


class _FakeService:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []

    def list_ritual_suggestions(self):
        self.calls.append(("list_ritual_suggestions", None))
        return [{"series_id": "series-1"}]

    def import_manual_transcript(self, **kwargs):
        self.calls.append(("import_manual_transcript", kwargs))
        return {"status": "imported", "title": kwargs["title"]}


def test_cli_preview_suggestions_json(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    service = _FakeService()
    monkeypatch.setattr(cli, "RitualIntelligenceService", lambda: service)

    exit_code = cli.main(["preview-suggestions", "--json"])

    assert exit_code == 0
    assert service.calls == [("list_ritual_suggestions", None)]
    assert json.loads(capsys.readouterr().out) == [{"series_id": "series-1"}]


def test_cli_import_transcript_parses_iso_datetimes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    service = _FakeService()
    monkeypatch.setattr(cli, "RitualIntelligenceService", lambda: service)
    transcript = tmp_path / "transcript.md"
    transcript.write_text("hello", encoding="utf-8")

    exit_code = cli.main(
        [
            "import-transcript",
            str(transcript),
            "--title",
            "Weekly Ritual",
            "--started-at",
            "2026-03-10T09:00:00",
            "--ended-at",
            "2026-03-10T09:30:00",
            "--source-event-id",
            "evt-123",
        ]
    )

    assert exit_code == 0
    assert service.calls[0][0] == "import_manual_transcript"
    payload = service.calls[0][1]
    assert payload["file_path"] == transcript
    assert payload["title"] == "Weekly Ritual"
    assert payload["source_event_id"] == "evt-123"
    assert payload["started_at"] == datetime.fromisoformat("2026-03-10T09:00:00")
    assert payload["ended_at"] == datetime.fromisoformat("2026-03-10T09:30:00")
    assert json.loads(capsys.readouterr().out)["status"] == "imported"


def test_module_entrypoint_exits_with_cli_status(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("core.ritual_intelligence.cli.main", lambda: 7)

    with pytest.raises(SystemExit) as excinfo:
        runpy.run_module("core.ritual_intelligence", run_name="__main__")

    assert excinfo.value.code == 7
