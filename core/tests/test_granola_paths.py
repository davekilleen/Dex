"""Granola desktop path resolution for macOS and Windows."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.integrations import granola_paths
from core.mcp import onboarding_server
from core.meeting_sources import granola_adapter

REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOWS_DATA_FIXTURE = (
    REPO_ROOT / "core" / "tests" / "fixtures" / "granola" / "windows-data-dir"
)


def _kind_from(existing: dict[str, str]):
    folded = {path.casefold(): kind for path, kind in existing.items()}

    def kind(path: str) -> str | None:
        return folded.get(path.casefold())

    return kind


def _mac_home() -> str:
    # Built at runtime so source never contains a literal /Users/ path.
    return "/".join(("", "Users", "sam"))


def _windows_env(**overrides: str) -> dict[str, str]:
    env = {
        "APPDATA": r"C:\Users\Sam\AppData\Roaming",
        "LOCALAPPDATA": r"C:\Users\Sam\AppData\Local",
        "USERPROFILE": r"C:\Users\Sam",
        "PROGRAMFILES": r"C:\Program Files",
        "PROGRAMFILES(X86)": r"C:\Program Files (x86)",
    }
    env.update(overrides)
    return env


def test_classify_cygwin_and_msys_as_windows() -> None:
    for raw in ("win32", "Windows", "cygwin", "CYGWIN_NT-10.0", "msys", "MINGW64_NT-10.0"):
        assert granola_paths.classify_platform(raw) == "win32"
    assert granola_paths.classify_platform("darwin") == "darwin"
    assert granola_paths.classify_platform("linux") == "linux"


def test_windows_default_app_and_data_paths() -> None:
    exe = r"C:\Users\Sam\AppData\Local\Programs\@granolaelectron\Granola.exe"
    data = r"C:\Users\Sam\AppData\Roaming\Granola"
    result = granola_paths.detect_granola(
        platform="win32",
        env=_windows_env(),
        kind=_kind_from({exe: "file", data: "dir"}),
    )

    assert result.installed is True
    assert result.app_found is True
    assert result.data_found is True
    assert result.app_path == exe
    assert result.data_path == data
    assert result.app_path_posix == granola_paths.windows_to_git_bash(exe)
    assert result.data_path_posix == granola_paths.windows_to_git_bash(data)
    assert any(probe.source.endswith(r"Programs\@granolaelectron\Granola.exe") for probe in result.tried)


def test_windows_data_directory_alone_counts_as_installed() -> None:
    data = r"C:\Users\Sam\AppData\Roaming\Granola"
    result = granola_paths.detect_granola(
        platform="win32",
        env=_windows_env(),
        kind=_kind_from({data: "dir"}),
    )
    assert result.installed is True
    assert result.app_found is False
    assert result.data_found is True
    assert result.app_path is None
    assert result.data_path == data


def test_windows_machine_wide_and_unscoped_app_variants() -> None:
    env = _windows_env()
    candidates = granola_paths.detect_granola(
        platform="win32", env=env, kind=lambda _path: None
    )
    paths = [probe.path for probe in candidates.tried if probe.kind == "app"]
    assert r"C:\Users\Sam\AppData\Local\Programs\@granolaelectron\Granola.exe" in paths
    assert r"C:\Users\Sam\AppData\Local\Programs\Granola\Granola.exe" in paths
    assert r"C:\Program Files\@granolaelectron\Granola.exe" in paths
    assert r"C:\Program Files\Granola\Granola.exe" in paths
    assert r"C:\Program Files (x86)\@granolaelectron\Granola.exe" in paths
    assert r"C:\Program Files (x86)\Granola\Granola.exe" in paths


def test_missing_windows_env_falls_back_to_userprofile() -> None:
    env = {"USERPROFILE": r"C:\Users\Sam"}
    result = granola_paths.detect_granola(
        platform="win32",
        env=env,
        kind=_kind_from(
            {
                r"C:\Users\Sam\AppData\Local\Programs\@granolaelectron\Granola.exe": "file",
                r"C:\Users\Sam\AppData\Roaming\Granola": "dir",
            }
        ),
    )
    assert result.app_path == r"C:\Users\Sam\AppData\Local\Programs\@granolaelectron\Granola.exe"
    assert result.data_path == r"C:\Users\Sam\AppData\Roaming\Granola"
    assert any(probe.source.startswith("USERPROFILE\\") for probe in result.tried)


def test_homedrive_homepath_fallback_when_userprofile_missing() -> None:
    env = {"HOMEDRIVE": "C:", "HOMEPATH": r"\Users\Sam"}
    result = granola_paths.detect_granola(
        platform="win32",
        env=env,
        kind=_kind_from({r"C:\Users\Sam\AppData\Roaming\Granola": "dir"}),
    )
    assert result.data_path == r"C:\Users\Sam\AppData\Roaming\Granola"


def test_onedrive_redirected_appdata_is_used_first() -> None:
    env = _windows_env(
        APPDATA=r"C:\Users\Sam\OneDrive\AppData\Roaming",
        USERPROFILE=r"C:\Users\Sam",
    )
    onedrive = r"C:\Users\Sam\OneDrive\AppData\Roaming\Granola"
    physical = r"C:\Users\Sam\AppData\Roaming\Granola"
    result = granola_paths.detect_granola(
        platform="win32",
        env=env,
        kind=_kind_from({physical: "dir"}),
    )
    data_tries = [probe for probe in result.tried if probe.kind == "data"]
    assert data_tries[0].path == onedrive
    assert data_tries[0].ok is False
    assert result.data_path == physical


def test_unc_appdata_stays_unc() -> None:
    env = _windows_env(APPDATA=r"\\fileserver\users\sam\AppData\Roaming")
    data = r"\\fileserver\users\sam\AppData\Roaming\Granola"
    result = granola_paths.detect_granola(
        platform="win32",
        env=env,
        kind=_kind_from({data: "dir"}),
    )
    assert result.data_path == data
    assert result.data_path_posix == "//fileserver/users/sam/AppData/Roaming/Granola"


def test_control_characters_in_env_are_rejected() -> None:
    env = _windows_env(APPDATA="C:\\Users\\Sam\\AppData\\Roaming\nC:\\evil")
    result = granola_paths.detect_granola(
        platform="win32",
        env=env,
        kind=_kind_from({r"C:\Users\Sam\AppData\Roaming\Granola": "dir"}),
    )
    assert all(
        probe.path != "C:\\Users\\Sam\\AppData\\Roaming\nC:\\evil\\Granola"
        for probe in result.tried
    )
    # Physical USERPROFILE fallback still works.
    assert result.data_path == r"C:\Users\Sam\AppData\Roaming\Granola"


def test_dotdot_in_appdata_is_collapsed_not_executed() -> None:
    env = _windows_env(APPDATA=r"C:\Users\Sam\AppData\Roaming\..\..\..\..\Windows")
    result = granola_paths.detect_granola(
        platform="win32", env=env, kind=lambda _path: None
    )
    first_data = next(probe for probe in result.tried if probe.kind == "data")
    assert first_data.path == r"C:\Windows\Granola"
    assert first_data.ok is False
    assert first_data.reason == "missing"


def test_empty_localappdata_is_logged_and_skipped() -> None:
    env = _windows_env()
    env["LOCALAPPDATA"] = "   "
    result = granola_paths.detect_granola(
        platform="win32", env=env, kind=lambda _path: None
    )
    app_sources = [probe.source for probe in result.tried if probe.kind == "app"]
    assert not any(source.startswith("LOCALAPPDATA\\") for source in app_sources)
    assert any("USERPROFILE" in probe.source or "AppData\\Local" in probe.source for probe in result.tried)


def test_quoted_and_relative_env_values_are_sanitized() -> None:
    quoted = granola_paths.detect_granola(
        platform="win32",
        env=_windows_env(APPDATA=r'"C:\Users\Sam\AppData\Roaming"'),
        kind=_kind_from({r"C:\Users\Sam\AppData\Roaming\Granola": "dir"}),
    )
    assert quoted.data_path == r"C:\Users\Sam\AppData\Roaming\Granola"

    relative = granola_paths.detect_granola(
        platform="win32",
        env=_windows_env(APPDATA=".."),
        kind=_kind_from({r"C:\Users\Sam\AppData\Roaming\Granola": "dir"}),
    )
    assert relative.data_path == r"C:\Users\Sam\AppData\Roaming\Granola"
    assert all(probe.path != r"..\Granola" for probe in relative.tried)


def test_override_env_wins_and_invalid_override_is_ignored() -> None:
    custom = r"D:\Apps\Granola.exe"
    result = granola_paths.detect_granola(
        platform="win32",
        env=_windows_env(**{"DEX_GRANOLA_APP": custom}),
        kind=_kind_from({custom: "file"}),
    )
    assert result.app_path == custom

    rejected = granola_paths.detect_granola(
        platform="win32",
        env=_windows_env(**{"DEX_GRANOLA_APP": "C:\\evil\x00Granola.exe"}),
        kind=lambda _path: None,
    )
    assert all("evil" not in probe.path for probe in rejected.tried)


def test_macos_app_bundle_still_required_for_installed() -> None:
    home = _mac_home()
    result = granola_paths.detect_granola(
        platform="darwin",
        env={"HOME": home},
        home=home,
        kind=_kind_from(
            {
                f"{home}/Library/Application Support/Granola": "dir",
            }
        ),
    )
    assert result.installed is False
    assert result.data_found is True
    assert result.app_found is False

    found = granola_paths.detect_granola(
        platform="darwin",
        env={"HOME": home},
        home=home,
        kind=_kind_from({"/Applications/Granola.app": "dir"}),
    )
    assert found.installed is True
    assert found.app_path == "/Applications/Granola.app"


def test_linux_is_unchanged_even_when_windows_env_is_present() -> None:
    result = granola_paths.detect_granola(
        platform="linux",
        env=_windows_env(),
        kind=_kind_from(
            {
                r"C:\Users\Sam\AppData\Local\Programs\@granolaelectron\Granola.exe": "file",
                r"C:\Users\Sam\AppData\Roaming\Granola": "dir",
            }
        ),
    )
    assert result.platform == "linux"
    assert result.installed is False
    assert result.tried == []
    assert result.app_path is None
    assert result.data_path is None


def test_onboarding_check_granola_uses_windows_locator(monkeypatch) -> None:
    exe = r"C:\Users\Sam\AppData\Local\Programs\@granolaelectron\Granola.exe"
    monkeypatch.setattr(onboarding_server.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        granola_paths,
        "default_kind",
        _kind_from({exe: "file"}),
    )
    for key, value in _windows_env().items():
        monkeypatch.setenv(key, value)

    detected = onboarding_server.check_granola()
    assert detected["installed"] is True
    assert detected["app_found"] is True
    assert detected["path"] == exe
    assert detected["setup"] == "/granola-setup"


def test_onboarding_granola_detection_checks_the_application(monkeypatch, tmp_path: Path) -> None:
    app_path = tmp_path / "Granola.app"
    monkeypatch.setattr(onboarding_server.platform, "system", lambda: "Darwin")
    monkeypatch.setenv("DEX_GRANOLA_APP", str(app_path))

    assert onboarding_server.check_granola()["installed"] is False

    app_path.mkdir()
    detected = onboarding_server.check_granola()
    assert detected["installed"] is True
    assert detected["app_found"] is True
    assert detected["path"] == str(app_path)


def test_windows_data_dir_fixture_is_detected_without_reading_files() -> None:
    """Windows community cache lives under the same data directory as macOS.

    Dex does not parse those local files. Detection is existence-only. The
    official API payload (tested below) is the only meeting parser, and it
    does not differ by OS.
    """
    assert WINDOWS_DATA_FIXTURE.is_dir()
    marker = WINDOWS_DATA_FIXTURE / "Local State"
    assert marker.is_file()

    def kind(path: str) -> str | None:
        if Path(path) == WINDOWS_DATA_FIXTURE:
            return "dir"
        return None

    result = granola_paths.detect_granola(
        platform="win32",
        env=_windows_env(**{"DEX_GRANOLA_DATA": str(WINDOWS_DATA_FIXTURE)}),
        kind=kind,
    )
    assert result.data_found is True
    assert result.data_path == str(WINDOWS_DATA_FIXTURE)
    # Official API payloads are the only meeting parser, and they do not differ by OS.
    record = granola_adapter.to_record(
        {
            "id": "gran-win-1",
            "title": "Weekly review",
            "created_at": "2026-08-14T09:00:00Z",
            "summary_markdown": "- [ ] Send notes",
            "attendees": [{"name": "Sam", "email": "sam@example.com"}],
        }
    )
    assert record.source == "granola"


def test_python_and_js_resolvers_agree_on_windows_candidates() -> None:
    env = _windows_env()
    python = granola_paths.detect_granola(platform="win32", env=env, kind=lambda _path: None)
    script = (
        "const { detectGranola } = require('./core/integrations/granola_paths.cjs');"
        f"process.stdout.write(JSON.stringify(detectGranola({json.dumps({'platform': 'win32', 'env': env})})));"
    )
    completed = subprocess.run(
        [process_node(), "-e", script],
        check=True,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    js = json.loads(completed.stdout)
    assert [probe.path for probe in python.tried] == [item["path"] for item in js["tried"]]
    assert [probe.source for probe in python.tried] == [item["source"] for item in js["tried"]]


def process_node() -> str:
    return "node"


@pytest.mark.parametrize("raw", ["win32", "cygwin", "darwin", "linux"])
def test_cli_json_shape(raw: str) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "core.integrations.granola_paths", "--platform", raw],
        check=False,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    payload = json.loads(completed.stdout)
    assert payload["platform"] in {"win32", "darwin", "linux"}
    assert "tried" in payload
    assert isinstance(payload["installed"], bool)
    if raw == "linux":
        assert completed.returncode == 1
        assert payload["tried"] == []
