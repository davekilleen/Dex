"""Golden checks for the data-driven harness capability registry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.harnesses.registry import (
    REGISTRY_PATH,
    detect_harnesses,
    get_profile,
    list_profiles,
)


EXPECTED_IDS = {
    "claude-code",
    "cowork",
    "codex",
    "copilot-cli",
    "pi",
    "agent-plugin",
    "chatgpt-work",
    "bb",
}


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


def test_every_profile_has_a_reviewable_adapter_descriptor() -> None:
    adapter_root = Path(__file__).resolve().parents[2] / "core" / "harnesses" / "adapters"
    for profile in list_profiles():
        path = adapter_root / f"{profile.id}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["harness_id"] == profile.id
        assert payload["adapter_schema_version"] == "1.0.0"
        assert payload["example"]


def test_get_profile_rejects_unknown_ids() -> None:
    with pytest.raises(KeyError):
        get_profile("not-a-harness")


def test_detection_accepts_explicit_ids_and_environment_markers() -> None:
    assert [profile.id for profile in detect_harnesses(explicit=["codex"])] == ["codex"]
    detected = detect_harnesses(env={"CODEX_CLI": "1"})
    assert [profile.id for profile in detected] == ["codex"]


def test_detection_uses_paths_without_treating_an_empty_environment_as_claude() -> None:
    assert [profile.id for profile in detect_harnesses(env={}, paths=[Path("/tmp/.bb/worktrees/x")])] == ["bb"]
    assert detect_harnesses(env={}, paths=[]) == ()
