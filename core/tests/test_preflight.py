"""Behavior tests for core/utils/preflight.py — the /health-check backbone.

test_preflight_paths.py covers path derivation; this suite covers the actual
health-check logic: config hashing, recheck policy, per-server checks, the
cached run_preflight flow, and hook output formatting.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from core.utils import preflight


@pytest.fixture
def vault(tmp_path, monkeypatch):
    """Temp vault with a valid and a broken core MCP server module."""
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    mcp_dir = tmp_path / "core" / "mcp"
    mcp_dir.mkdir(parents=True)
    (mcp_dir / "work_server.py").write_text("app = object()\n")
    (mcp_dir / "career_server.py").write_text("def broken(:\n")  # syntax error
    return tmp_path


def _write_config(vault, servers):
    (vault / ".mcp.json").write_text(json.dumps({"mcpServers": {s: {} for s in servers}}))


# ---------------------------------------------------------------------------
# Config reading
# ---------------------------------------------------------------------------


def test_config_hash_tracks_file_changes(vault):
    assert preflight.config_hash() == ""
    _write_config(vault, ["work-mcp"])
    first = preflight.config_hash()
    assert first
    _write_config(vault, ["work-mcp", "career-mcp"])
    assert preflight.config_hash() != first


def test_get_configured_servers(vault):
    assert preflight.get_configured_servers() == []
    _write_config(vault, ["work-mcp", "my-custom-mcp"])
    assert preflight.get_configured_servers() == ["work-mcp", "my-custom-mcp"]

    (vault / ".mcp.json").write_text("{not json")
    assert preflight.get_configured_servers() == []


# ---------------------------------------------------------------------------
# Recheck policy
# ---------------------------------------------------------------------------


def test_needs_recheck_true_for_empty_or_stale(vault):
    _write_config(vault, ["work-mcp"])
    assert preflight.needs_recheck({}) is True

    stale = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
    assert preflight.needs_recheck({"configHash": preflight.config_hash(), "lastCheck": stale}) is True


def test_needs_recheck_false_when_fresh_and_unchanged(vault):
    _write_config(vault, ["work-mcp"])
    health = {
        "configHash": preflight.config_hash(),
        "lastCheck": datetime.now(timezone.utc).isoformat(),
    }
    assert preflight.needs_recheck(health) is False


def test_needs_recheck_true_when_config_changed(vault):
    _write_config(vault, ["work-mcp"])
    health = {
        "configHash": "somethingelse",
        "lastCheck": datetime.now(timezone.utc).isoformat(),
    }
    assert preflight.needs_recheck(health) is True


def test_needs_recheck_true_on_new_unacknowledged_error(vault):
    _write_config(vault, ["work-mcp"])
    last_check = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    logs = vault / ".logs"
    logs.mkdir(exist_ok=True)
    (logs / "error-queue.json").write_text(json.dumps([
        {"timestamp": datetime.now(timezone.utc).isoformat(), "acknowledged": False},
    ]))
    health = {"configHash": preflight.config_hash(), "lastCheck": last_check}
    assert preflight.needs_recheck(health) is True

    # Acknowledged errors don't force a recheck
    (logs / "error-queue.json").write_text(json.dumps([
        {"timestamp": datetime.now(timezone.utc).isoformat(), "acknowledged": True},
    ]))
    assert preflight.needs_recheck(health) is False


# ---------------------------------------------------------------------------
# Per-server checks
# ---------------------------------------------------------------------------


def test_check_server_ok_missing_broken_and_unknown(vault):
    assert preflight.check_server("work-mcp") == {"status": "ok"}

    missing = preflight.check_server("beta-mcp")  # module file not created
    assert missing["status"] == "error"
    assert "missing" in missing["humanError"]

    broken = preflight.check_server("career-mcp")
    assert broken["status"] == "error"
    assert "syntax error" in broken["humanError"]

    assert preflight.check_server("my-custom-mcp")["status"] == "unknown"


def test_check_http_server_unreachable_and_unknown(vault, monkeypatch):
    monkeypatch.setitem(preflight.HTTP_SERVERS, "calendar-mcp", "http://127.0.0.1:1/health")
    result = preflight.check_http_server("calendar-mcp")
    assert result["status"] == "error"
    assert "unreachable" in result["humanError"]

    assert preflight.check_http_server("not-configured")["status"] == "unknown"


# ---------------------------------------------------------------------------
# run_preflight caching
# ---------------------------------------------------------------------------


def test_run_preflight_checks_writes_cache_and_reuses_it(vault):
    _write_config(vault, ["work-mcp", "beta-mcp", "my-custom-mcp"])

    health = preflight.run_preflight()

    servers = health["servers"]
    assert servers["work-mcp"]["status"] == "ok"
    assert servers["beta-mcp"]["status"] == "error"
    assert servers["my-custom-mcp"]["status"] == "unknown"
    assert (vault / ".logs" / "mcp-health.json").exists()

    # Second run within 24h with unchanged config returns the cached result
    again = preflight.run_preflight()
    assert again == health

    # Config change invalidates the cache
    _write_config(vault, ["work-mcp"])
    refreshed = preflight.run_preflight()
    assert set(refreshed["servers"]) == {"work-mcp"}


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------


def test_format_output_silent_when_healthy_or_empty():
    assert preflight.format_output({}) == ""
    assert preflight.format_output({"servers": {"a": {"status": "ok"}}}) == ""
    assert preflight.format_output({"servers": {"a": {"status": "unknown"}}}) == ""


def test_format_output_surfaces_errors_with_ratio():
    health = {"servers": {
        "work-mcp": {"status": "ok"},
        "beta-mcp": {"status": "error", "humanError": "Beta Features is missing"},
        "custom": {"status": "unknown"},
    }}
    out = preflight.format_output(health)
    assert "❌ Beta Features is missing" in out
    assert "✅ 1/2 MCP servers ready" in out
    assert "health check" in out
