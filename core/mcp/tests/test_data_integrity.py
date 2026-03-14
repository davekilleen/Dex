"""Corrupted-data resilience tests for MCP modules."""

from __future__ import annotations

import sys
from pathlib import Path

# Add MCP folder to import path for direct module imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import commitment_server  # noqa: E402
import work_server  # noqa: E402


def test_load_queue_recovers_from_corrupted_json(tmp_path, monkeypatch):
    queue_file = tmp_path / "commitment_queue.json"
    queue_file.write_text("{not-valid-json", encoding="utf-8")
    monkeypatch.setattr(commitment_server, "QUEUE_FILE", queue_file)

    queue = commitment_server.load_queue()
    assert queue["version"] == 1
    assert queue["commitments"] == []
    assert queue["stats"]["total_detected"] == 0


def test_load_pillars_from_corrupted_yaml_falls_back_to_defaults(tmp_path, monkeypatch):
    pillars_file = tmp_path / "pillars.yaml"
    pillars_file.write_text("pillars: [broken-yaml", encoding="utf-8")
    monkeypatch.setattr(work_server, "get_pillars_file", lambda: pillars_file)

    loaded = work_server.load_pillars_from_yaml()
    assert loaded == work_server.DEFAULT_PILLARS


def test_load_priority_limits_from_corrupted_yaml_falls_back_to_defaults(tmp_path, monkeypatch):
    pillars_file = tmp_path / "pillars.yaml"
    pillars_file.write_text("priority_limits: [broken-yaml", encoding="utf-8")
    monkeypatch.setattr(work_server, "get_pillars_file", lambda: pillars_file)

    loaded = work_server.load_priority_limits_from_yaml()
    assert loaded == work_server.DEFAULT_PRIORITY_LIMITS
