"""Dex Helper client: LaunchServices open contract, tmp JSON, install/update."""

from __future__ import annotations

import json
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


def _app_bundle(
    root: Path,
    version: str = "1.0.0",
    bundle_id: str = helper.HELPER_BUNDLE_ID,
) -> Path:
    app = root / "Dex Helper.app"
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    _fake_executable(macos / "DexHelper")
    (app / "Contents" / "Info.plist").write_text(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<plist version=\"1.0\"><dict>"
        f"<key>CFBundleIdentifier</key><string>{bundle_id}</string>"
        f"<key>CFBundleShortVersionString</key><string>{version}</string>"
        "</dict></plist>\n",
        encoding="utf-8",
    )
    return app


def test_helper_is_unavailable_on_linux_without_override(monkeypatch):
    monkeypatch.delenv("DEX_HELPER_PATH", raising=False)
    monkeypatch.setattr(helper.sys, "platform", "linux")
    assert helper.helper_is_available() is False
    assert helper.helper_op_for_script("calendar_eventkit.py", ("list",)) == (
        "calendar.list",
        {"args": []},
    )
    assert helper.run_mapped_helper("calendar_eventkit.py", ("list",)) is None


def test_helper_is_unavailable_for_a_bare_executable(tmp_path, monkeypatch):
    exe = _fake_executable(tmp_path / "DexHelper")
    monkeypatch.setenv("DEX_HELPER_PATH", str(exe))
    monkeypatch.setattr(helper.sys, "platform", "linux")
    assert helper.helper_executable() == exe
    assert helper.helper_app_bundle() is None
    assert helper.helper_is_available() is False


def test_helper_op_for_script_maps_eventkit_and_create_scripts():
    assert helper.helper_op_for_script("calendar_eventkit.py", ("list",)) == (
        "calendar.list",
        {"args": []},
    )
    assert helper.helper_op_for_script(
        "reminders_eventkit.py",
        ("list_items", "Dex Today"),
    ) == ("reminders.list_items", {"args": ["Dex Today"]})
    assert helper.helper_op_for_script(
        "calendar_create_event.sh",
        ("Work", "Hold", "2026-10-27 09:00", "30"),
    ) == (
        "calendar.create",
        {"args": ["Work", "Hold", "2026-10-27 09:00", "30"]},
    )
    assert helper.helper_op_for_script("check_calendar_permission.py", ()) is None


def test_open_helper_argv_uses_launchservices_and_keeps_pii_out_of_argv(tmp_path):
    app = tmp_path / "Dex Helper.app"
    out_path = tmp_path / "out.json"
    in_path = tmp_path / "in.json"
    argv = helper.open_helper_argv(app, "calendar.create", out_path, in_path)
    assert argv[:6] == ["open", "-W", "-n", "-a", str(app), "--args"]
    assert argv[6:] == ["calendar.create", str(out_path), str(in_path)]
    assert "Hold" not in argv
    assert "Work" not in argv


def test_run_mapped_helper_uses_open_and_vault_tmp_json(tmp_path, monkeypatch):
    app = _app_bundle(tmp_path / "install")
    vault = tmp_path / "vault"
    monkeypatch.setenv("DEX_HELPER_PATH", str(app))
    monkeypatch.setattr(helper.sys, "platform", "linux")
    seen: dict[str, object] = {}

    def fake_run(command, **_kwargs):
        seen["command"] = command
        assert command[:6] == ["open", "-W", "-n", "-a", str(app), "--args"]
        assert command[6] == "calendar.create"
        out_path = Path(command[7])
        in_path = Path(command[8])
        assert out_path.parent == vault / "System" / ".dex" / "tmp"
        assert in_path.parent == out_path.parent
        assert out_path.name.startswith("helper-out-")
        assert in_path.name.startswith("helper-")
        assert stat.S_IMODE(out_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(in_path.stat().st_mode) == 0o600
        payload = json.loads(in_path.read_text(encoding="utf-8"))
        assert payload == {"args": ["Work", "Hold", "2026-10-27 09:00", "30"]}
        assert "Hold" not in command
        out_path.write_text('{"success": true}\n', encoding="utf-8")
        seen["out_path"] = out_path
        seen["in_path"] = in_path
        return helper.subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    result = helper.run_mapped_helper(
        "calendar_create_event.sh",
        ("Work", "Hold", "2026-10-27 09:00", "30"),
        vault_root=vault,
    )
    assert result == (True, '{"success": true}')
    assert not Path(str(seen["out_path"])).exists()
    assert not Path(str(seen["in_path"])).exists()


def test_run_mapped_helper_returns_helper_errors_without_falling_back(
    tmp_path, monkeypatch
):
    app = _app_bundle(tmp_path / "install")
    monkeypatch.setenv("DEX_HELPER_PATH", str(app))
    monkeypatch.setattr(helper.sys, "platform", "linux")

    def fake_run(command, **_kwargs):
        assert command[:4] == ["open", "-W", "-n", "-a"]
        Path(command[7]).write_text(
            '{"error":"Calendar access denied."}\n', encoding="utf-8"
        )
        return helper.subprocess.CompletedProcess(command, 1, stdout="", stderr="")

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    result = helper.run_mapped_helper(
        "calendar_eventkit.py",
        ("list",),
        vault_root=tmp_path / "vault",
    )
    assert result == (False, '{"error":"Calendar access denied."}')


def test_run_mapped_helper_falls_back_when_open_is_missing(tmp_path, monkeypatch):
    app = _app_bundle(tmp_path / "install")
    monkeypatch.setenv("DEX_HELPER_PATH", str(app))
    monkeypatch.setattr(helper.sys, "platform", "linux")

    def fake_run(_command, **_kwargs):
        raise FileNotFoundError("open")

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    assert helper.run_mapped_helper(
        "calendar_eventkit.py",
        ("list",),
        vault_root=tmp_path / "vault",
    ) is None


def test_compare_versions_orders_helper_releases():
    assert helper.compare_versions("1.0.1", "1.0.0") == 1
    assert helper.compare_versions("1.0.0", "1.0.0") == 0
    assert helper.compare_versions("1.0.0", "1.1.0") == -1


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
    record = tmp_path / "vault" / "System" / ".dex" / "helpers" / "installed.json"
    assert record.is_file()

    again = helper.install_or_update_helper(
        source_app=source,
        destination_app=dest,
        vault_root=tmp_path / "vault",
    )
    assert again["skipped"] is True
    assert again["reason"] == "already_current"


def test_install_refuses_identity_mismatch(tmp_path, monkeypatch):
    monkeypatch.setattr(helper.sys, "platform", "darwin")
    source = _app_bundle(tmp_path / "src", "1.0.1")
    dest = tmp_path / "Applications" / "Dex Helper.app"
    dest.parent.mkdir()
    helper.shutil.copytree(_app_bundle(tmp_path / "old", "1.0.0"), dest)

    def fake_identity(app_path: Path) -> dict[str, str | None]:
        if "src" in app_path.parts:
            return {
                "kind": "adhoc",
                "team_id": "-",
                "bundle_id": helper.HELPER_BUNDLE_ID,
            }
        return {
            "kind": "developer_id",
            "team_id": "ABCD123456",
            "bundle_id": helper.HELPER_BUNDLE_ID,
        }

    monkeypatch.setattr(helper, "read_signing_identity", fake_identity)
    result = helper.install_or_update_helper(
        source_app=source,
        destination_app=dest,
        vault_root=tmp_path / "vault",
    )
    assert result["ok"] is False
    assert result["reason"] == "identity_mismatch"
    assert "grant Calendar and Reminders again" in str(result["message"])
    assert helper.read_installed_version(dest) == "1.0.0"


def test_build_unsigned_helper_skips_off_macos(monkeypatch):
    monkeypatch.setattr(helper.sys, "platform", "linux")
    result = helper.build_unsigned_helper()
    assert result["ok"] is True
    assert result["skipped"] is True
    assert result["reason"] == "not_macos"


def test_build_script_ad_hoc_signs_and_never_notarizes():
    script = helper.helper_source_dir() / "build.sh"
    text = script.read_text(encoding="utf-8")
    assert "codesign --force --sign -" in text
    assert "notarytool" not in text
    assert "stapler" not in text
    for line in text.splitlines():
        command = line.split("#", 1)[0].strip()
        if not command:
            continue
        assert "notarytool" not in command
        assert "stapler" not in command
        if command.split()[:1] == ["codesign"]:
            assert "--sign -" in command or "-s -" in command


def test_install_sh_tries_helper_on_a_mac_and_keeps_going_if_it_skips():
    installer = Path(__file__).resolve().parents[2] / "install.sh"
    text = installer.read_text(encoding="utf-8")
    assert "macos_privacy_helper install" in text
    assert "Never fail install" in text
    assert "fallback path remains" in text


def test_helper_plist_declares_calendar_and_reminders_usage():
    plist = (helper.helper_source_dir() / "Info.plist").read_text(encoding="utf-8")
    assert "ai.heydex.DexHelper" in plist
    assert "<string>ai.heydex.DexHelper</string>" in plist
    assert "NSCalendarsFullAccessUsageDescription" in plist
    assert "NSRemindersFullAccessUsageDescription" in plist
    assert "NSCalendarsUsageDescription" in plist
    assert "NSRemindersUsageDescription" in plist
    assert "<key>LSMinimumSystemVersion</key>" in plist
    assert "<string>14.0</string>" in plist


def test_helper_search_paths_never_include_source_build_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("DEX_HELPER_PATH", raising=False)
    source_build = helper.helper_source_dir() / "build" / helper.HELPER_APP_NAME
    paths = helper.helper_search_paths(env={}, vault_root=tmp_path)
    assert helper.helper_executable_from_app(source_build) not in paths
    assert all("core/macos/dex-helper/build" not in path.as_posix() for path in paths)


def test_helper_version_sources_agree():
    version = (helper.helper_source_dir() / "VERSION").read_text(encoding="utf-8").strip()
    plist = (helper.helper_source_dir() / "Info.plist").read_text(encoding="utf-8")
    assert f"<key>CFBundleShortVersionString</key>\n\t<string>{version}</string>" in plist


def test_doctor_status_line_when_helper_is_missing(monkeypatch):
    monkeypatch.setattr(helper, "helper_app_bundle", lambda vault_root=None: None)
    assert helper.doctor_status_line() == "Dex Helper: not installed"


def test_doctor_status_line_when_helper_is_installed(tmp_path, monkeypatch):
    app = _app_bundle(tmp_path)
    monkeypatch.setattr(helper, "helper_app_bundle", lambda vault_root=None: app)
    monkeypatch.setattr(
        helper,
        "read_signing_identity",
        lambda _app: {"kind": "adhoc", "team_id": "-", "bundle_id": helper.HELPER_BUNDLE_ID},
    )
    monkeypatch.setattr(
        helper,
        "run_helper_op",
        lambda *_args, **_kwargs: (True, '{"calendar":"granted","reminders":"not_determined"}'),
    )
    assert helper.doctor_status_line() == (
        "Dex Helper: installed, adhoc, Calendar granted, Reminders not_determined"
    )


@pytest.mark.skipif(sys.platform != "darwin", reason="Helper builds only on macOS")
def test_helper_builds_and_ad_hoc_signs_when_codesign_is_present(tmp_path):
    result = helper.build_unsigned_helper(output_dir=tmp_path)
    if result.get("skipped"):
        pytest.skip(str(result.get("message") or result.get("reason")))
    assert result["ok"] is True
    built = Path(str(result["path"]))
    assert helper.helper_executable_from_app(built).is_file()
    assert helper.read_bundle_id(built) == helper.HELPER_BUNDLE_ID
