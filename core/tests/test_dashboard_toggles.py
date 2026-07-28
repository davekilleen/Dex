"""Behavioral coverage for the Dex Dashboard vetted toggle write engine."""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path

import pytest


def _toggles():
    return importlib.import_module("core.dashboard.toggles")


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _profile() -> str:
    return """\
# Keep this comment byte-for-byte.
name: "Alex Example"
unknown_root:
  keep_me: "yes"
communication:
  formality: "professional_casual"  # options stay here
  directness: "balanced"
  detail_level: "concise"
  coaching_style: "collaborative"
entity_creation:
  mode: suggest
entity_gardener:
  enabled: true
meeting_intelligence:
  extract_customer_intel: false
  extract_competitive_intel: false
  extract_action_items: true
  extract_decisions: true
  extract_stakeholder_dynamics: false
  extract_budget_timeline: false
  extract_technical_decisions: false
journaling:
  morning: false
  evening: false
  weekly: true
capabilities:
  career:
    enabled: false
  companies:
    enabled: true
  quarter_goals:
    enabled: false
analytics:
  enabled: true  # anonymous counts only
"""


def _integrations() -> str:
    return """\
# Existing integrations can be switched; new ones cannot be invented.
last_updated: null
enabled:
  slack: false  # preserve this comment
  google: true
hooks:
  meeting_prep:
    use_slack: false
detected:
  slack: null
todoist:
  enabled: true
  api_key_env_var: TODOIST_API_KEY
"""


def _usage_log() -> str:
    return """\
## Health Telemetry Consent

Separate from analytics.

**Health telemetry:** pending

## Journey Metadata
"""


def _vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    _write(vault / "System" / "user-profile.yaml", _profile())
    _write(vault / "System" / "integrations" / "config.yaml", _integrations())
    _write(vault / "System" / "usage_log.md", _usage_log())
    return vault


NEW_PROFILE_SETTING_CASES = (
    ("detail_level", "concise", "comprehensive", "exhaustive", '  detail_level: "concise"\n'),
    ("coaching_style", "collaborative", "challenging", "commanding", '  coaching_style: "collaborative"\n'),
    ("entity_gardener", True, False, "false", "  enabled: true\n"),
    ("journaling_morning", False, True, "true", "  morning: false\n"),
    ("journaling_evening", False, True, "true", "  evening: false\n"),
    ("journaling_weekly", True, False, "false", "  weekly: true\n"),
    ("meeting_intel:extract_customer_intel", False, True, "true", "  extract_customer_intel: false\n"),
    ("meeting_intel:extract_competitive_intel", False, True, "true", "  extract_competitive_intel: false\n"),
    ("meeting_intel:extract_action_items", True, False, "false", "  extract_action_items: true\n"),
    ("meeting_intel:extract_decisions", True, False, "false", "  extract_decisions: true\n"),
    (
        "meeting_intel:extract_stakeholder_dynamics",
        False,
        True,
        "true",
        "  extract_stakeholder_dynamics: false\n",
    ),
    ("meeting_intel:extract_budget_timeline", False, True, "true", "  extract_budget_timeline: false\n"),
    (
        "meeting_intel:extract_technical_decisions",
        False,
        True,
        "true",
        "  extract_technical_decisions: false\n",
    ),
)

CAPABILITY_CASES = (
    ("capability:career", "career", False, True),
    ("capability:companies", "companies", True, False),
    ("capability:quarter_goals", "quarter_goals", False, True),
)


def test_read_state_returns_only_vetted_values_with_file_stamps(tmp_path: Path) -> None:
    toggles = _toggles()
    vault = _vault(tmp_path)

    snapshot = toggles.ToggleEngine(vault).read_state()

    assert snapshot.values == {
        "analytics_enabled": True,
        "capability:career": False,
        "capability:companies": True,
        "capability:quarter_goals": False,
        "coaching_style": "collaborative",
        "detail_level": "concise",
        "directness": "balanced",
        "entity_creation": "suggest",
        "entity_gardener": True,
        "formality": "professional_casual",
        "health_telemetry": "pending",
        "integration:google.enabled": True,
        "integration:slack.enabled": False,
        "integration:todoist.enabled": True,
        "journaling_evening": False,
        "journaling_morning": False,
        "journaling_weekly": True,
        "meeting_intel:extract_action_items": True,
        "meeting_intel:extract_budget_timeline": False,
        "meeting_intel:extract_competitive_intel": False,
        "meeting_intel:extract_customer_intel": False,
        "meeting_intel:extract_decisions": True,
        "meeting_intel:extract_stakeholder_dynamics": False,
        "meeting_intel:extract_technical_decisions": False,
    }
    assert set(snapshot.stamps) == set(snapshot.values)
    assert all(stamp.mtime_ns > 0 for stamp in snapshot.stamps.values())
    assert all(len(stamp.sha256) == 64 for stamp in snapshot.stamps.values())
    assert snapshot.unavailable == {}
    serialized = json.dumps(snapshot.values, sort_keys=True)
    assert "TODOIST_API_KEY" not in serialized
    assert "keep_me" not in serialized


@pytest.mark.parametrize(
    ("setting_id", "initial", "_new_value", "_invalid_value", "_profile_line"),
    NEW_PROFILE_SETTING_CASES,
)
def test_new_profile_registry_reads_each_present_setting(
    tmp_path: Path,
    setting_id: str,
    initial: object,
    _new_value: object,
    _invalid_value: object,
    _profile_line: str,
) -> None:
    snapshot = _toggles().ToggleEngine(_vault(tmp_path)).read_state()

    assert snapshot.values[setting_id] == initial
    assert setting_id in snapshot.stamps


@pytest.mark.parametrize(
    ("setting_id", "_initial", "new_value", "_invalid_value", "profile_line"),
    NEW_PROFILE_SETTING_CASES,
)
def test_new_profile_registry_writes_each_existing_anchor(
    tmp_path: Path,
    setting_id: str,
    _initial: object,
    new_value: object,
    _invalid_value: object,
    profile_line: str,
) -> None:
    toggles = _toggles()
    vault = _vault(tmp_path)
    engine = toggles.ToggleEngine(vault)
    snapshot = engine.read_state()
    profile = vault / "System" / "user-profile.yaml"
    before = profile.read_text(encoding="utf-8")

    result = engine.write(setting_id, new_value, expected=snapshot.stamps[setting_id])

    assert result.old == snapshot.values[setting_id]
    assert result.new == new_value
    after = profile.read_text(encoding="utf-8")
    assert after != before
    assert after.count(profile_line) == before.count(profile_line) - 1


@pytest.mark.parametrize(
    ("setting_id", "_initial", "_new_value", "invalid_value", "_profile_line"),
    NEW_PROFILE_SETTING_CASES,
)
def test_new_profile_registry_rejects_each_invalid_value(
    tmp_path: Path,
    setting_id: str,
    _initial: object,
    _new_value: object,
    invalid_value: object,
    _profile_line: str,
) -> None:
    toggles = _toggles()
    vault = _vault(tmp_path)
    engine = toggles.ToggleEngine(vault)
    snapshot = engine.read_state()
    profile = vault / "System" / "user-profile.yaml"
    before = profile.read_bytes()

    with pytest.raises(toggles.ToggleValidationError):
        engine.write(setting_id, invalid_value, expected=snapshot.stamps[setting_id])

    assert profile.read_bytes() == before


@pytest.mark.parametrize(
    ("setting_id", "_initial", "new_value", "_invalid_value", "profile_line"),
    NEW_PROFILE_SETTING_CASES,
)
def test_new_profile_registry_omits_each_absent_key(
    tmp_path: Path,
    setting_id: str,
    _initial: object,
    new_value: object,
    _invalid_value: object,
    profile_line: str,
) -> None:
    toggles = _toggles()
    vault = _vault(tmp_path)
    profile = vault / "System" / "user-profile.yaml"
    profile.write_text(
        profile.read_text(encoding="utf-8").replace(profile_line, "", 1),
        encoding="utf-8",
    )
    engine = toggles.ToggleEngine(vault)

    snapshot = engine.read_state()

    assert setting_id not in snapshot.values
    assert setting_id not in snapshot.stamps
    assert setting_id not in snapshot.unavailable
    with pytest.raises(
        toggles.ToggleValidationError,
        match=r"^That setting is not present in this Dex's files yet\.$",
    ):
        engine.write(setting_id, new_value, expected=None)


@pytest.mark.parametrize(
    ("setting_id", "room", "initial", "new_value"),
    CAPABILITY_CASES,
)
def test_capability_registry_reads_via_enabled_and_writes_via_set_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    setting_id: str,
    room: str,
    initial: bool,
    new_value: bool,
) -> None:
    toggles = _toggles()
    vault = _vault(tmp_path)
    real_enabled = toggles.capabilities.enabled
    enabled_calls: list[tuple[str, Path]] = []
    set_calls: list[tuple[str, bool, Path]] = []

    def enabled(candidate: str, *, profile_path: Path) -> bool:
        enabled_calls.append((candidate, profile_path))
        return real_enabled(candidate, profile_path=profile_path)

    def set_enabled(candidate: str, value: bool, *, vault_root: Path) -> dict[str, object]:
        set_calls.append((candidate, value, vault_root))
        return {"room": candidate, "enabled": value}

    monkeypatch.setattr(toggles.capabilities, "enabled", enabled)
    monkeypatch.setattr(toggles.capabilities, "set_enabled", set_enabled)
    engine = toggles.ToggleEngine(vault)

    snapshot = engine.read_state()
    result = engine.write(setting_id, new_value, expected=snapshot.stamps[setting_id])

    assert snapshot.values[setting_id] is initial
    assert (room, vault / "System" / "user-profile.yaml") in enabled_calls
    assert set_calls == [(room, new_value, vault.resolve())]
    assert result.old is initial
    assert result.new is new_value
    audit = json.loads(
        (vault / "System" / ".dex" / "dashboard" / "audit.jsonl").read_text(encoding="utf-8")
    )
    assert audit["setting_id"] == setting_id
    assert audit["old"] is initial
    assert audit["new"] is new_value


@pytest.mark.parametrize(("setting_id", "room", "_initial", "_new_value"), CAPABILITY_CASES)
def test_capability_registry_rejects_invalid_values_without_calling_set_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    setting_id: str,
    room: str,
    _initial: bool,
    _new_value: bool,
) -> None:
    toggles = _toggles()
    vault = _vault(tmp_path)
    engine = toggles.ToggleEngine(vault)
    snapshot = engine.read_state()
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        toggles.capabilities,
        "set_enabled",
        lambda *args, **kwargs: calls.append((*args, kwargs)),
    )

    with pytest.raises(toggles.ToggleValidationError):
        engine.write(setting_id, "true", expected=snapshot.stamps[setting_id])

    assert calls == []


@pytest.mark.parametrize(("setting_id", "room", "_initial", "_new_value"), CAPABILITY_CASES)
def test_absent_capability_key_reads_its_safe_contract_default(
    tmp_path: Path,
    setting_id: str,
    room: str,
    _initial: bool,
    _new_value: bool,
) -> None:
    vault = _vault(tmp_path)
    profile = vault / "System" / "user-profile.yaml"
    profile.write_text(
        profile.read_text(encoding="utf-8").replace(
            f"  {room}:\n    enabled: {'true' if room == 'companies' else 'false'}\n",
            "",
        ),
        encoding="utf-8",
    )

    snapshot = _toggles().ToggleEngine(vault).read_state()

    # An absent key means "whatever the shipped contract says" — the contract is the
    # source of truth for room defaults, so read it rather than hardcoding a value.
    from core import capabilities as capability_rooms

    expected = capability_rooms.enabled(room, profile_path=profile)
    assert snapshot.values[setting_id] is expected
    assert setting_id in snapshot.stamps


def test_capability_api_errors_are_plain_toggle_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toggles = _toggles()
    vault = _vault(tmp_path)
    engine = toggles.ToggleEngine(vault)
    snapshot = engine.read_state()

    def fail(*_args, **_kwargs) -> None:
        raise RuntimeError("NEVER_EXPOSE_THIS_INTERNAL_PATH")

    monkeypatch.setattr(toggles.capabilities, "set_enabled", fail)

    with pytest.raises(toggles.ToggleError) as raised:
        engine.write(
            "capability:career",
            True,
            expected=snapshot.stamps["capability:career"],
        )

    assert "capability" in str(raised.value).lower()
    assert "NEVER_EXPOSE" not in str(raised.value)


def test_capability_write_rechecks_the_profile_before_calling_set_enabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    toggles = _toggles()
    vault = _vault(tmp_path)
    profile = vault / "System" / "user-profile.yaml"
    engine = toggles.ToggleEngine(vault)
    snapshot = engine.read_state()
    set_calls: list[tuple[object, ...]] = []

    def edit_during_read(_room: str, *, profile_path: Path) -> bool:
        profile_path.write_text(
            profile_path.read_text(encoding="utf-8").replace(
                'name: "Alex Example"',
                'name: "Externally Changed"',
            ),
            encoding="utf-8",
        )
        return False

    monkeypatch.setattr(toggles.capabilities, "enabled", edit_during_read)
    monkeypatch.setattr(
        toggles.capabilities,
        "set_enabled",
        lambda *args, **kwargs: set_calls.append((*args, kwargs)),
    )

    with pytest.raises(toggles.ToggleConflictError, match="refresh"):
        engine.write(
            "capability:career",
            True,
            expected=snapshot.stamps["capability:career"],
        )

    assert set_calls == []
    assert 'name: "Externally Changed"' in profile.read_text(encoding="utf-8")


@pytest.mark.parametrize("requested_value", ["off", "always"])
def test_missing_profile_setting_is_omitted_while_other_settings_still_work(
    tmp_path: Path,
    requested_value: str,
) -> None:
    toggles = _toggles()
    vault = _vault(tmp_path)
    profile = vault / "System" / "user-profile.yaml"
    profile.write_text(
        _profile().replace("entity_creation:\n  mode: suggest\n", ""),
        encoding="utf-8",
    )
    engine = toggles.ToggleEngine(vault)

    snapshot = engine.read_state()

    assert snapshot.values["formality"] == "professional_casual"
    assert "entity_creation" not in snapshot.values
    assert "entity_creation" not in snapshot.stamps
    assert "entity_creation" not in snapshot.unavailable

    engine.write("formality", "casual", expected=snapshot.stamps["formality"])

    with pytest.raises(
        toggles.ToggleValidationError,
        match=r"^That setting is not present in this Dex's files yet\.$",
    ):
        engine.write("entity_creation", requested_value, expected=None)


def test_profile_write_changes_one_scalar_and_appends_audit(tmp_path: Path) -> None:
    toggles = _toggles()
    vault = _vault(tmp_path)
    engine = toggles.ToggleEngine(vault)
    snapshot = engine.read_state()
    profile = vault / "System" / "user-profile.yaml"
    before = profile.read_text(encoding="utf-8")

    result = engine.write(
        "formality",
        "casual",
        expected=snapshot.stamps["formality"],
    )

    after = profile.read_text(encoding="utf-8")
    assert result.old == "professional_casual"
    assert result.new == "casual"
    assert result.stamp.sha256 != snapshot.stamps["formality"].sha256
    assert after == before.replace(
        '  formality: "professional_casual"  # options stay here',
        '  formality: "casual"  # options stay here',
    )
    audit_path = vault / "System" / ".dex" / "dashboard" / "audit.jsonl"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert set(audit) == {"ts", "setting_id", "old", "new"}
    assert audit["setting_id"] == "formality"
    assert audit["old"] == "professional_casual"
    assert audit["new"] == "casual"
    assert audit["ts"].endswith("Z")


def test_successful_noop_is_audited_without_rewriting_the_source(tmp_path: Path) -> None:
    toggles = _toggles()
    vault = _vault(tmp_path)
    engine = toggles.ToggleEngine(vault)
    snapshot = engine.read_state()
    profile = vault / "System" / "user-profile.yaml"
    before = profile.read_bytes()

    result = engine.write(
        "formality",
        "professional_casual",
        expected=snapshot.stamps["formality"],
    )

    assert profile.read_bytes() == before
    assert result.stamp == snapshot.stamps["formality"]
    audit_path = vault / "System" / ".dex" / "dashboard" / "audit.jsonl"
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["old"] == audit["new"] == "professional_casual"


def test_yaml_like_text_inside_unknown_block_scalar_is_preserved(tmp_path: Path) -> None:
    toggles = _toggles()
    vault = _vault(tmp_path)
    profile = vault / "System" / "user-profile.yaml"
    profile.write_text(
        profile.read_text(encoding="utf-8").replace(
            "communication:\n",
            """\
notes: |
  communication:
    formality: formal
communication:
""",
        ),
        encoding="utf-8",
    )
    engine = toggles.ToggleEngine(vault)
    snapshot = engine.read_state()

    engine.write("directness", "supportive", expected=snapshot.stamps["directness"])

    changed = profile.read_text(encoding="utf-8")
    assert "notes: |\n  communication:\n    formality: formal\n" in changed
    assert '  directness: "supportive"' in changed


@pytest.mark.parametrize(
    ("setting_id", "value", "expected_line"),
    [
        ("analytics_enabled", False, "  enabled: false  # anonymous counts only"),
        ("entity_creation", "off", "  mode: off"),
        ("directness", "very_direct", '  directness: "very_direct"'),
        ("health_telemetry", "opted-in", "**Health telemetry:** opted-in"),
        ("integration:slack.enabled", True, "  slack: true  # preserve this comment"),
        ("integration:todoist.enabled", False, "  enabled: false"),
    ],
)
def test_each_vetted_setting_updates_its_existing_anchor(
    tmp_path: Path,
    setting_id: str,
    value: object,
    expected_line: str,
) -> None:
    toggles = _toggles()
    vault = _vault(tmp_path)
    engine = toggles.ToggleEngine(vault)
    snapshot = engine.read_state()

    engine.write(setting_id, value, expected=snapshot.stamps[setting_id])

    if setting_id == "health_telemetry":
        changed = (vault / "System" / "usage_log.md").read_text(encoding="utf-8")
    elif setting_id.startswith("integration:"):
        changed = (vault / "System" / "integrations" / "config.yaml").read_text(encoding="utf-8")
    else:
        changed = (vault / "System" / "user-profile.yaml").read_text(encoding="utf-8")
    assert expected_line in changed


@pytest.mark.parametrize(
    ("setting_id", "value"),
    [
        ("made_up", True),
        ("analytics_enabled", 1),
        ("analytics_enabled", "true"),
        ("entity_creation", "always"),
        ("formality", "royal"),
        ("directness", "rude"),
        ("health_telemetry", "pending"),
        ("integration:new-app.enabled", True),
        ("integration:../escape.enabled", True),
    ],
)
def test_unknown_settings_and_invalid_values_are_rejected_without_writes(
    tmp_path: Path,
    setting_id: str,
    value: object,
) -> None:
    toggles = _toggles()
    vault = _vault(tmp_path)
    engine = toggles.ToggleEngine(vault)
    snapshot = engine.read_state()
    before = {path.relative_to(vault): path.read_bytes() for path in vault.rglob("*") if path.is_file()}
    expected = snapshot.stamps.get(setting_id)

    with pytest.raises(toggles.ToggleValidationError):
        engine.write(setting_id, value, expected=expected)

    after = {path.relative_to(vault): path.read_bytes() for path in vault.rglob("*") if path.is_file()}
    assert after == before


def test_concurrent_edit_is_detected_by_sha_even_when_mtime_is_restored(
    tmp_path: Path,
) -> None:
    toggles = _toggles()
    vault = _vault(tmp_path)
    engine = toggles.ToggleEngine(vault)
    snapshot = engine.read_state()
    profile = vault / "System" / "user-profile.yaml"
    original_stat = profile.stat()
    externally_changed = profile.read_text(encoding="utf-8").replace(
        'name: "Alex Example"',
        'name: "Other Person"',
    )
    profile.write_text(externally_changed, encoding="utf-8")
    os.utime(
        profile,
        ns=(original_stat.st_atime_ns, snapshot.stamps["formality"].mtime_ns),
    )

    with pytest.raises(toggles.ToggleConflictError, match="refresh"):
        engine.write(
            "formality",
            "formal",
            expected=snapshot.stamps["formality"],
        )

    assert profile.read_text(encoding="utf-8") == externally_changed
    assert not (vault / "System" / ".dex" / "dashboard" / "audit.jsonl").exists()


@pytest.mark.parametrize(
    ("replacement", "reason"),
    [
        (
            '  directness: "balanced"\n  directness: "very_direct"',
            "exactly once",
        ),
        ('  directness: "unrecognised"', "outside the supported schema"),
    ],
)
def test_malformed_profile_setting_is_scoped_to_that_setting(
    tmp_path: Path,
    replacement: str,
    reason: str,
) -> None:
    toggles = _toggles()
    vault = _vault(tmp_path)
    profile = vault / "System" / "user-profile.yaml"
    profile.write_text(
        _profile().replace(
            '  directness: "balanced"',
            replacement,
        ),
        encoding="utf-8",
    )
    engine = toggles.ToggleEngine(vault)

    snapshot = engine.read_state()

    assert snapshot.values["formality"] == "professional_casual"
    assert "directness" not in snapshot.values
    assert "directness" not in snapshot.stamps
    assert set(snapshot.unavailable) == {"directness"}
    assert reason in snapshot.unavailable["directness"]

    with pytest.raises(toggles.ToggleSchemaError, match=reason):
        engine.write("directness", "supportive", expected=None)

    engine.write("formality", "casual", expected=snapshot.stamps["formality"])


def test_ambiguous_integration_anchor_is_scoped_to_that_setting(tmp_path: Path) -> None:
    toggles = _toggles()
    vault = _vault(tmp_path)
    config = vault / "System" / "integrations" / "config.yaml"
    config.write_text(
        _integrations()
        + """\
slack:
  enabled: false
""",
        encoding="utf-8",
    )
    engine = toggles.ToggleEngine(vault)

    snapshot = engine.read_state()

    assert snapshot.values["integration:google.enabled"] is True
    assert snapshot.values["integration:todoist.enabled"] is True
    assert "integration:slack.enabled" not in snapshot.values
    assert set(snapshot.unavailable) == {"integration:slack.enabled"}
    assert "slack" in snapshot.unavailable["integration:slack.enabled"]

    with pytest.raises(toggles.ToggleSchemaError, match="slack"):
        engine.write("integration:slack.enabled", True, expected=None)


def test_atomic_replace_interruption_leaves_original_file_intact(tmp_path: Path) -> None:
    toggles = _toggles()
    path = _write(tmp_path / "settings.yaml", "original\n")

    def interrupt() -> None:
        raise RuntimeError("simulated kill before replace")

    with pytest.raises(RuntimeError, match="simulated kill"):
        toggles.atomic_replace_bytes(path, b"replacement\n", before_replace=interrupt)

    assert path.read_bytes() == b"original\n"
    assert list(tmp_path.glob(".settings.yaml.*.tmp")) == []


def test_write_requires_a_state_snapshot_first(tmp_path: Path) -> None:
    toggles = _toggles()
    vault = _vault(tmp_path)

    with pytest.raises(toggles.ToggleConflictError, match="refresh"):
        toggles.ToggleEngine(vault).write("formality", "formal", expected=None)
