"""Doctor checks added in Phase 3: platform.support, Windows python.env, .env UNKNOWN."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.utils import doctor
from core.utils import platform_support as support

pytestmark = pytest.mark.windows_supported

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def context(tmp_path: Path) -> doctor.DoctorContext:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "core").mkdir()
    home = tmp_path / "home"
    home.mkdir()
    return doctor.DoctorContext(vault_root=vault, repo_root=vault, home=home, now=NOW)


def test_platform_support_unsupported_is_broken_tier_3(monkeypatch, context) -> None:
    monkeypatch.setattr(
        support,
        "probe",
        lambda **_kwargs: support.SupportReport(
            family="cygwin-or-msys",
            shell_hint="uname=CYGWIN_NT-10.0",
            python_source="other",
            python_ok=False,
            vault_volume={},
            verdict="unsupported",
            messages=[support.SupportMessage(id="W3", text=support.MESSAGE_W3)],
        ),
    )
    result = doctor._probe_platform_support(context)
    assert result.verdict == "BROKEN"
    assert result.heal is not None
    assert result.heal.tier == 3
    assert support.MESSAGE_W3 in result.detail


def test_platform_support_posix_python_310_is_broken(monkeypatch, context) -> None:
    monkeypatch.setattr(
        support,
        "probe",
        lambda **_kwargs: support.SupportReport(
            family="linux",
            shell_hint="uname=Linux",
            python_source="other",
            python_ok=False,
            vault_volume={},
            verdict="unsupported",
            messages=[
                support.SupportMessage(
                    id="P1",
                    text=support.MESSAGE_POSIX_PYTHON.format(version="3.10.12"),
                )
            ],
        ),
    )
    result = doctor._probe_platform_support(context)
    assert result.verdict == "BROKEN"
    assert result.heal is not None
    assert result.heal.tier == 3
    assert "Python 3.11 or newer" in result.detail
    assert "You have 3.10.12" in result.detail


def test_platform_support_warnings_stay_ok(monkeypatch, context) -> None:
    monkeypatch.setattr(
        support,
        "probe",
        lambda **_kwargs: support.SupportReport(
            family="windows",
            shell_hint="",
            python_source="other",
            python_ok=True,
            vault_volume={},
            verdict="supported-with-warnings",
            messages=[support.SupportMessage(id="W8", text=support.MESSAGE_W8.format(version="3.14.0"))],
        ),
    )
    result = doctor._probe_platform_support(context)
    assert result.verdict == "OK"
    assert "3.14.0" in result.detail


def test_python_env_uses_scripts_python_on_windows(monkeypatch, context) -> None:
    monkeypatch.setattr(doctor.os, "name", "nt")
    missing = doctor._probe_python_env(context)
    assert missing.verdict == "BROKEN"
    # Build the expected fragment as text. pathlib.Path follows os.name, and
    # this test has already patched os.name to "nt".
    detail = missing.detail.replace("\\", "/")
    assert ".venv/Scripts/python.exe" in detail or (
        "Scripts" in missing.detail and "python.exe" in missing.detail
    )

    python = context.vault_root / ".venv" / "Scripts" / "python.exe"
    python.parent.mkdir(parents=True)
    python.write_text("rem\n", encoding="utf-8")
    monkeypatch.setattr(doctor.os, "access", lambda _path, _mode: True)
    monkeypatch.setattr(doctor, "_python_import_check", lambda _python: (True, []))
    assert doctor._probe_python_env(context).verdict == "OK"


def test_windows_env_permissions_are_unknown_never_ok(monkeypatch, context) -> None:
    monkeypatch.setattr(doctor.os, "name", "nt")
    _write_valid_configs(context)
    assert doctor._probe_vault_configs(context).verdict == "OK"

    (context.vault_root / ".env").write_text("TOKEN=x\n", encoding="utf-8")
    result = doctor._probe_vault_configs(context)
    assert result.verdict == "UNKNOWN"
    assert result.detail == doctor.WINDOWS_ENV_PERMISSION_UNKNOWN
    assert result.verdict != "OK"


def _write_valid_configs(context) -> None:
    system = context.vault_root / "System"
    system.mkdir(parents=True, exist_ok=True)
    (system / "user-profile.yaml").write_text("name: Test\n", encoding="utf-8")
    (system / "pillars.yaml").write_text("pillars: []\n", encoding="utf-8")
    settings = context.vault_root / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text('{"hooks": {}}\n', encoding="utf-8")
