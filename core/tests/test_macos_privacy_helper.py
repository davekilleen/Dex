"""Dex Helper client: routing, fallback, install/update, unsigned build skip."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

from core.utils import macos_privacy_helper as helper


def _fake_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_helper_is_unavailable_on_linux_without_override(monkeypatch):
    monkeypatch.delenv("DEX_HELPER_PATH", raising=False)
    monkeypatch.setattr(helper.sys, "platform", "linux")
    assert helper.helper_is_available() is False
    assert helper.helper_argv("calendar_eventkit.py", ("list",)) is None
    assert helper.run_mapped_helper("calendar_eventkit.py", ("list",)) is None


def test_helper_argv_maps_eventkit_and_create_scripts(tmp_path, monkeypatch):
    exe = _fake_executable(tmp_path / "DexHelper")
    monkeypatch.setenv("DEX_HELPER_PATH", str(exe))
    monkeypatch.setattr(helper.sys, "platform", "linux")

    assert helper.helper_argv("calendar_eventkit.py", ("list",)) == [
        str(exe),
        "calendar",
        "list",
    ]
    assert helper.helper_argv("reminders_eventkit.py", ("list_items", "Dex Today")) == [
        str(exe),
        "reminders",
        "list_items",
        "Dex Today",
    ]
    assert helper.helper_argv(
        "calendar_create_event.sh",
        ("Work", "Hold", "2026-10-27 09:00", "30"),
    ) == [
        str(exe),
        "calendar",
        "create",
        "Work",
        "Hold",
        "2026-10-27 09:00",
        "30",
    ]
    assert helper.helper_argv("check_calendar_permission.py", ()) is None


def test_run_mapped_helper_returns_helper_errors_without_falling_back(
    tmp_path, monkeypatch
):
    exe = _fake_executable(tmp_path / "DexHelper")
    monkeypatch.setenv("DEX_HELPER_PATH", str(exe))
    monkeypatch.setattr(helper.sys, "platform", "linux")

    def fake_run(command, **_kwargs):
        assert command[0] == str(exe)
        return helper.subprocess.CompletedProcess(
            command, 1, stdout='{"error":"Calendar access denied."}\n', stderr=""
        )

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    result = helper.run_mapped_helper("calendar_eventkit.py", ("list",))
    assert result == (False, '{"error":"Calendar access denied."}')


def test_run_mapped_helper_falls_back_when_the_binary_vanishes(
    tmp_path, monkeypatch
):
    exe = _fake_executable(tmp_path / "DexHelper")
    monkeypatch.setenv("DEX_HELPER_PATH", str(exe))
    monkeypatch.setattr(helper.sys, "platform", "linux")

    def fake_run(_command, **_kwargs):
        raise FileNotFoundError("gone")

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    assert helper.run_mapped_helper("calendar_eventkit.py", ("list",)) is None


def test_compare_versions_orders_helper_releases():
    assert helper.compare_versions("1.0.1", "1.0.0") == 1
    assert helper.compare_versions("1.0.0", "1.0.0") == 0
    assert helper.compare_versions("1.0.0", "1.1.0") == -1


def _app_bundle(root: Path, version: str) -> Path:
    app = root / "Dex Helper.app"
    contents = app / "Contents"
    macos = contents / "MacOS"
    macos.mkdir(parents=True)
    _fake_executable(macos / "DexHelper")
    (contents / "Info.plist").write_text(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<plist version=\"1.0\"><dict>"
        f"<key>CFBundleShortVersionString</key><string>{version}</string>"
        "</dict></plist>\n",
        encoding="utf-8",
    )
    return app


def test_install_or_update_skips_when_not_macos(monkeypatch):
    monkeypatch.setattr(helper.sys, "platform", "linux")
    result = helper.install_or_update_helper()
    assert result["ok"] is True
    assert result["skipped"] is True
    assert result["reason"] == "not_macos"


def test_install_or_update_copies_newer_and_skips_current(tmp_path, monkeypatch):
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    source = _app_bundle(tmp_path / "src", "1.0.1")
    dest = tmp_path / "Applications" / "Dex Helper.app"
    dest.parent.mkdir()
    older = _app_bundle(tmp_path / "old", "1.0.0")
    helper.shutil.copytree(older, dest)

    updated = helper.install_or_update_helper(
        source_app=source,
        destination_app=dest,
        vault_root=tmp_path / "vault",
    )
    assert updated["ok"] is True
    assert updated["skipped"] is False
    assert updated["reason"] == "updated"
    assert updated["version"] == "1.0.1"
    assert helper.read_installed_version(dest) == "1.0.1"
    record = (tmp_path / "vault" / "System" / ".dex" / "helpers" / "installed.json")
    assert record.is_file()
    assert '"signed": false' in record.read_text(encoding="utf-8")

    again = helper.install_or_update_helper(
        source_app=source,
        destination_app=dest,
        vault_root=tmp_path / "vault",
    )
    assert again["skipped"] is True
    assert again["reason"] == "already_current"


def test_build_unsigned_helper_skips_off_macos(monkeypatch):
    monkeypatch.setattr(helper.sys, "platform", "linux")
    result = helper.build_unsigned_helper()
    assert result["ok"] is True
    assert result["skipped"] is True
    assert result["reason"] == "not_macos"


def test_build_script_never_invokes_signing_tools():
    script = helper.helper_source_dir() / "build.sh"
    text = script.read_text(encoding="utf-8")
    assert "Unsigned on purpose" in text
    for line in text.splitlines():
        command = line.split("#", 1)[0].strip()
        if not command:
            continue
        assert "codesign" not in command
        assert "notarytool" not in command
        assert "stapler" not in command


def test_install_sh_tries_helper_on_a_mac_and_keeps_going_if_it_skips():
    installer = Path(__file__).resolve().parents[2] / "install.sh"
    text = installer.read_text(encoding="utf-8")
    assert "macos_privacy_helper install" in text
    assert "Never fail install" in text
    assert "fallback path remains" in text


def test_helper_plist_declares_calendar_and_reminders_usage():
    plist = (helper.helper_source_dir() / "Info.plist").read_text(encoding="utf-8")
    assert "ai.heydex.DexHelper" in plist
    assert "NSCalendarsFullAccessUsageDescription" in plist
    assert "NSRemindersFullAccessUsageDescription" in plist
    assert "NSCalendarsUsageDescription" in plist
    assert "NSRemindersUsageDescription" in plist


@pytest.mark.skipif(sys.platform != "darwin", reason="Swift helper builds only on macOS")
def test_unsigned_helper_builds_when_swift_is_present(tmp_path):
    if not helper.shutil.which("swiftc"):
        pytest.skip("swiftc not installed")
    result = helper.build_unsigned_helper(output_dir=tmp_path)
    if result.get("skipped"):
        pytest.skip(str(result.get("message") or result.get("reason")))
    assert result["ok"] is True
    assert result["signed"] is False
    built = Path(str(result["path"]))
    assert helper.helper_executable_from_app(built).is_file()
