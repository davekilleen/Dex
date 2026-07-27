"""Regression coverage for the error queue's useful lifetime."""

from __future__ import annotations

import ast
import builtins
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.utils import dex_logger, doctor

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
CURRENT_VERSION = "1.76.1"


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "package.json").write_text(
        json.dumps({"name": "dex-pkm", "version": CURRENT_VERSION})
    )
    monkeypatch.setenv("VAULT_PATH", str(vault_root))
    monkeypatch.setenv("VAULT_ROOT", str(vault_root))
    return vault_root


def _context(vault: Path, now: datetime) -> doctor.DoctorContext:
    return doctor.DoctorContext(
        vault_root=vault,
        repo_root=vault,
        home=vault.parent / "home",
        now=now,
    )


def _healthy_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor.preflight, "run_preflight", lambda: {"servers": {}})


def _queue(vault: Path) -> list[dict[str, object]]:
    return json.loads((vault / ".logs" / "error-queue.json").read_text())


def _called_logger_functions() -> set[str]:
    repo_root = Path(__file__).resolve().parents[2]
    logger_path = Path(dex_logger.__file__).resolve()
    called: set[str] = set()
    for path in (repo_root / "core").rglob("*.py"):
        if path.resolve() == logger_path or "tests" in path.parts:
            continue
        tree = ast.parse(path.read_text())
        module_aliases: set[str] = set()
        direct_aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "core.utils.dex_logger" and alias.asname:
                        module_aliases.add(alias.asname)
            elif isinstance(node, ast.ImportFrom) and node.module == "core.utils":
                for alias in node.names:
                    if alias.name == "dex_logger":
                        module_aliases.add(alias.asname or alias.name)
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module == "core.utils.dex_logger"
            ):
                direct_aliases.update(
                    {alias.asname or alias.name: alias.name for alias in node.names}
                )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in module_aliases
            ):
                called.add(node.func.attr)
            elif isinstance(node.func, ast.Name) and node.func.id in direct_aliases:
                called.add(direct_aliases[node.func.id])
    return called


def test_new_errors_and_warnings_are_stamped_with_the_installed_version(vault: Path) -> None:
    dex_logger.log_error("work-mcp", "task failed")
    dex_logger.log_warning("calendar-mcp", "calendar delayed")

    assert [entry["dexVersion"] for entry in _queue(vault)] == [
        CURRENT_VERSION,
        CURRENT_VERSION,
    ]


def test_logging_omits_version_without_raising_when_package_cannot_be_read(vault: Path) -> None:
    (vault / "package.json").write_text("not json")

    dex_logger.log_error("work-mcp", "task failed")
    dex_logger.log_warning("calendar-mcp", "calendar delayed")

    assert all("dexVersion" not in entry for entry in _queue(vault))


def test_error_retention_policy_is_thirty_days() -> None:
    assert dex_logger.STALE_ERROR_DAYS == 30


def test_write_prunes_stale_entries_keeps_unknown_dates_and_caps_at_fifty(vault: Path) -> None:
    recent = [
        {
            "id": f"recent-{index}",
            "timestamp": (NOW - timedelta(minutes=index)).isoformat(),
        }
        for index in range(51)
    ]
    stale = {
        "id": "stale",
        "timestamp": (
            NOW - timedelta(days=dex_logger.STALE_ERROR_DAYS + 1)
        ).isoformat(),
    }
    unknown = {"id": "unknown", "timestamp": "not-a-date"}

    dex_logger._write_queue([stale, *recent, unknown], now=NOW)

    saved = _queue(vault)
    assert len(saved) == 50
    assert all(entry["id"] != "stale" for entry in saved)
    assert any(entry["id"] == "unknown" for entry in saved)


def test_error_ages_into_history_and_no_longer_breaks_doctor(
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _healthy_preflight(monkeypatch)
    logged_at = datetime.now(timezone.utc)
    dex_logger.log_error("work-mcp", "old failure", human_message="An earlier task failed")

    result = doctor._probe_preflight_queue(
        _context(vault, logged_at + timedelta(days=dex_logger.STALE_ERROR_DAYS + 1))
    )

    assert result.verdict == "OK"
    assert "1 earlier error" in result.detail
    assert logged_at.date().isoformat() in result.detail


def test_error_from_an_older_dex_version_is_history_not_current_breakage(
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _healthy_preflight(monkeypatch)
    (vault / "package.json").write_text(
        json.dumps({"name": "dex-pkm", "version": "1.75.2"})
    )
    dex_logger.log_error("work-mcp", "old version failure", human_message="An old task failed")
    old_error_date = _queue(vault)[0]["timestamp"][:10]
    (vault / "package.json").write_text(
        json.dumps({"name": "dex-pkm", "version": CURRENT_VERSION})
    )

    result = doctor._probe_preflight_queue(_context(vault, datetime.now(timezone.utc)))

    assert result.verdict == "OK"
    assert "1 earlier error from a previous Dex version" in result.detail
    assert old_error_date in result.detail


def test_fresh_current_version_error_is_broken_and_includes_its_date(
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _healthy_preflight(monkeypatch)
    dex_logger.log_error(
        "work-mcp",
        "current failure",
        human_message="Task Manager cannot start",
    )
    error_date = _queue(vault)[0]["timestamp"][:10]

    result = doctor._probe_preflight_queue(_context(vault, datetime.now(timezone.utc)))

    assert result.verdict == "BROKEN"
    assert f"Task Manager cannot start (on {error_date})" in result.detail


def test_current_version_error_newer_than_retention_threshold_is_current_breakage(
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _healthy_preflight(monkeypatch)
    dex_logger.log_error(
        "work-mcp",
        "recent failure",
        human_message="Task Manager cannot start",
    )
    logged_at = datetime.now(timezone.utc)

    result = doctor._probe_preflight_queue(
        _context(
            vault,
            logged_at + timedelta(days=dex_logger.STALE_ERROR_DAYS - 1),
        )
    )

    assert result.verdict == "BROKEN"
    assert "Task Manager cannot start" in result.detail


@pytest.mark.parametrize(
    "queue_contents",
    ["not json", json.dumps({"unexpected": "object"})],
    ids=["corrupt-json", "not-a-list"],
)
def test_corrupt_or_non_list_error_queue_is_unknown(
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
    queue_contents: str,
) -> None:
    _healthy_preflight(monkeypatch)
    queue_path = vault / ".logs" / "error-queue.json"
    queue_path.parent.mkdir()
    queue_path.write_text(queue_contents)

    result = doctor._probe_preflight_queue(_context(vault, NOW))

    assert result.verdict == "UNKNOWN"
    assert "error log could not be read" in result.detail.lower()
    assert "not checked" in result.detail.lower()


def test_unreadable_error_queue_is_unknown(
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _healthy_preflight(monkeypatch)
    queue_path = vault / ".logs" / "error-queue.json"
    queue_path.parent.mkdir()
    queue_path.write_text("[]")
    real_open = builtins.open

    def deny_queue_read(path: object, *args: object, **kwargs: object):
        if Path(path) == queue_path:
            raise PermissionError("queue is unreadable")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", deny_queue_read)

    result = doctor._probe_preflight_queue(_context(vault, NOW))

    assert result.verdict == "UNKNOWN"
    assert "error log could not be read" in result.detail.lower()
    assert "not checked" in result.detail.lower()


def test_missing_error_queue_is_ok(
    vault: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _healthy_preflight(monkeypatch)
    assert not (vault / ".logs" / "error-queue.json").exists()

    result = doctor._probe_preflight_queue(_context(vault, NOW))

    assert result.verdict == "OK"
    assert "no server or current queued errors" in result.detail.lower()


def test_every_public_error_queue_accessor_is_wired_outside_logger() -> None:
    public_functions = {
        name
        for name, value in inspect.getmembers(dex_logger, inspect.isfunction)
        if value.__module__ == dex_logger.__name__ and not name.startswith("_")
    }
    queue_accessors = public_functions - {"log_error", "log_warning", "mark_healthy"}

    assert queue_accessors
    assert queue_accessors <= _called_logger_functions()
