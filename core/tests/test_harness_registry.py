"""Golden checks for the data-driven harness capability registry."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from core.harnesses.registry import (
    REGISTRY_PATH,
    detect_harnesses,
    get_platform_release,
    get_profile,
    get_release_contract,
    list_profiles,
    standard_detection_paths,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

EXPECTED_IDS = {
    "claude-code",
    "claude-desktop",
    "cowork",
    "codex",
    "copilot-cli",
    "cursor",
    "gemini-cli",
    "pi",
    "agent-plugin",
    "chatgpt-work",
    "bb",
}

REGISTRY_GENERATOR = REPO_ROOT / "scripts" / "generate-harness-registry.py"


def _load_registry_generator():
    spec = importlib.util.spec_from_file_location("generate_harness_registry", REGISTRY_GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_registry_is_versioned_and_contains_the_supported_harnesses() -> None:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0.0"
    assert {entry["id"] for entry in payload["profiles"]} == EXPECTED_IDS
    assert [entry["id"] for entry in payload["profiles"]] == sorted(
        entry["id"] for entry in payload["profiles"]
    )
    assert all(
        row.get("mode") in {"automatic", "on_demand", "guided", "unavailable"}
        for profile in payload["profiles"]
        for row in profile["capabilities"]
    )


def test_registry_capability_statuses_use_a_closed_vocabulary() -> None:
    allowed_statuses = {"native", "partial", "none", "not-verified", "portable", "scheduled"}
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    statuses = {
        row["status"]
        for profile in payload["profiles"]
        for row in profile["capabilities"]
    }
    assert statuses
    assert statuses <= allowed_statuses


def test_generated_harness_profiles_are_current() -> None:
    assert _load_registry_generator().check_profiles(REPO_ROOT) == 0


def test_profile_generator_check_detects_drift_in_a_fixture(tmp_path: Path) -> None:
    fixture = tmp_path / "repo"
    source = REPO_ROOT / "core" / "harnesses"
    profile_root = fixture / "core" / "harnesses"
    profile_root.mkdir(parents=True)
    shutil.copy2(source / "registry.json", profile_root / "registry.json")
    shutil.copytree(source / "profiles", profile_root / "profiles")

    target = profile_root / "profiles" / "bb.json"
    target.write_text(target.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    assert _load_registry_generator().check_profiles(fixture) == 1


def test_registry_names_release_ready_platforms_and_linux_deferral() -> None:
    release = get_release_contract()
    assert release["status"] == "unreleased"
    assert set(release["platforms"]) == {"linux", "macos", "windows"}
    assert release["platforms"]["macos"]["readiness"] == "release_ready"
    assert release["platforms"]["windows"]["readiness"] == "release_ready"
    assert release["platforms"]["linux"]["readiness"] == "deferred"
    assert release["platforms"]["linux"]["included_in_release"] is False

    assert get_platform_release("Darwin")["id"] == "macos"
    assert get_platform_release("win32")["id"] == "windows"
    assert get_platform_release("linux")["readiness"] == "deferred"


def test_profiles_are_json_serializable_and_have_honest_modes() -> None:
    profiles = list_profiles()
    assert {profile.id for profile in profiles} == EXPECTED_IDS
    for profile in profiles:
        encoded = json.dumps(profile.to_dict(), sort_keys=True)
        assert encoded.startswith("{")
        assert profile.modes
        rows = profile.capability_rows()
        assert rows
        assert all({"id", "status", "tier"} <= set(row) for row in rows)
        assert profile.adapter.get("kind")

    # The generic package is the portable floor; it must not claim hooks or a
    # host lifecycle that the Agent Plugins v1 contract does not define.
    generic = get_profile("agent-plugin")
    rows = {row["id"]: row for row in generic.capability_rows()}
    assert rows["agent-skills"]["status"] == "native"
    assert rows["mcp"]["status"] == "native"
    assert rows["hooks"]["status"] in {"none", "not-verified"}

    codex = {row["id"]: row for row in get_profile("codex").capability_rows()}
    assert codex["agent-plugins"]["status"] == "native"
    assert codex["hooks"]["mode"] == "guided"
    cowork = {row["id"]: row for row in get_profile("cowork").capability_rows()}
    assert cowork["mcp"]["status"] == "partial"
    assert cowork["mcp"]["mode"] == "guided"
    bb = {row["id"]: row for row in get_profile("bb").capability_rows()}
    assert bb["agent-plugins"]["status"] == "native"
    copilot = {row["id"]: row for row in get_profile("copilot-cli").capability_rows()}
    assert copilot["hooks"]["status"] == "not-verified"
    assert copilot["hooks"]["mode"] == "unavailable"

    cursor = {row["id"]: row for row in get_profile("cursor").capability_rows()}
    assert cursor["agent-plugins"]["status"] == "native"
    assert cursor["hooks"]["status"] == "native"
    assert "tier-3-full" not in get_profile("cursor").modes

    gemini = {row["id"]: row for row in get_profile("gemini-cli").capability_rows()}
    assert gemini["mcp"]["status"] == "native"
    assert gemini["hooks"]["status"] == "native"
    assert "tier-3-full" not in get_profile("gemini-cli").modes

    desktop = {row["id"]: row for row in get_profile("claude-desktop").capability_rows()}
    assert desktop["mcp"]["status"] == "native"
    assert desktop["hooks"]["mode"] == "unavailable"


def test_every_profile_has_a_reviewable_adapter_descriptor() -> None:
    adapter_root = Path(__file__).resolve().parents[2] / "core" / "harnesses" / "adapters"
    for profile in list_profiles():
        path = adapter_root / f"{profile.id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["harness_id"] == profile.id
        assert payload["adapter_schema_version"] == "1.0.0"
        assert payload["example"]


def test_bb_adapter_matches_the_standalone_package_layout() -> None:
    adapter_path = REPO_ROOT / "core" / "harnesses" / "adapters" / "bb.json"
    adapter = json.loads(adapter_path.read_text(encoding="utf-8"))
    assert adapter["native_paths"] == [
        "package.json (bb field)",
        "server.ts",
        "app.tsx",
        "skills/",
    ]
    assert adapter["example"]["manifest"] == "bb-plugin-dex/package.json"
    assert get_profile("bb").adapter["manifest"] == "package.json#bb"


def test_get_profile_rejects_unknown_ids() -> None:
    with pytest.raises(KeyError):
        get_profile("not-a-harness")


def test_detection_accepts_explicit_ids_and_environment_markers() -> None:
    assert [profile.id for profile in detect_harnesses(explicit=["codex"])] == ["codex"]
    detected = detect_harnesses(env={"CODEX_CLI": "1"})
    assert [profile.id for profile in detected] == ["codex"]
    assert [profile.id for profile in detect_harnesses(env={"CURSOR_TRACE_ID": "x"})] == ["cursor"]
    assert [profile.id for profile in detect_harnesses(env={"GEMINI_CLI": "1"})] == ["gemini-cli"]
    assert [profile.id for profile in detect_harnesses(env={"COWORK": "1"})] == ["cowork"]
    assert [profile.id for profile in detect_harnesses(env={"CLAUDE_COWORK": "1"})] == ["cowork"]
    assert [profile.id for profile in detect_harnesses(env={"CLAUDE_CODE": "1"})] == ["claude-code"]
    assert [profile.id for profile in detect_harnesses(env={"PI_CLI": "1"})] == ["pi"]
    assert [profile.id for profile in detect_harnesses(env={"PI_CODING_AGENT": "1"})] == ["pi"]
    assert [profile.id for profile in detect_harnesses(env={"BB_HARNESS": "1"})] == ["bb"]
    assert [profile.id for profile in detect_harnesses(env={"BB_RUNNER": "1"})] == ["bb"]


def test_detection_uses_paths_without_treating_an_empty_environment_as_claude() -> None:
    assert [profile.id for profile in detect_harnesses(env={}, paths=[Path("/tmp/.bb/worktrees/x")])] == ["bb"]
    assert [profile.id for profile in detect_harnesses(env={}, paths=[Path("/tmp/.cowork/task")])] == ["cowork"]
    assert [profile.id for profile in detect_harnesses(env={}, paths=[Path("/tmp/.pi/session")])] == ["pi"]
    assert detect_harnesses(env={}, paths=[]) == ()


def test_standard_detection_paths_return_only_real_home_evidence(tmp_path: Path) -> None:
    codex = tmp_path / ".codex"
    codex.mkdir()
    claude = tmp_path / "Library/Application Support/Claude"
    claude.mkdir(parents=True)
    desktop_config = claude / "claude_desktop_config.json"
    desktop_config.write_text("{}\n", encoding="utf-8")

    paths = standard_detection_paths(home=tmp_path, env={})

    assert codex in paths
    assert claude in paths
    assert desktop_config in paths
    assert tmp_path / ".pi" not in paths


def test_detection_cli_uses_real_home_path_evidence_by_default(tmp_path: Path) -> None:
    (tmp_path / ".pi").mkdir()
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "core.harnesses.registry",
            "detect",
            "--format",
            "ids",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env={
            "HOME": str(tmp_path),
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == ["pi"]
