"""Proof that marking a feature as used actually writes, and never writes the wrong thing.

The adoption checkboxes in usage_log.md had a reader and no writer: 34 skills
instructed the assistant to hand-edit the file, nothing verified that it had,
and a run where the edit was skipped looked exactly like a run where it was not.
These tests exist so that failure mode cannot come back silently.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.mcp import analytics_helper

LOG_WITH_CONSENT = """# Dex Usage Tracking

**Consent asked:** yes
**Consent decision:** opted-in
**Health telemetry:** opted-out

## Core Workflows

- [x] Daily planning (`/daily-plan`)
- [ ] Meeting prep (`/meeting-prep`)
- [ ] Person page created
- [ ] Journaling (`/journal`)
- [ ] Journaling setup (`/journal`)
"""


@pytest.fixture
def vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "System").mkdir(parents=True)
    (tmp_path / "System" / "usage_log.md").write_text(LOG_WITH_CONSENT, encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    return tmp_path


def _log(vault: Path) -> str:
    return (vault / "System" / "usage_log.md").read_text(encoding="utf-8")


def test_marking_an_unticked_feature_writes_the_box(vault: Path) -> None:
    result = analytics_helper.mark_feature_used("meeting-prep")

    assert result["status"] == "marked"
    assert result["label"] == "Meeting prep (`/meeting-prep`)"
    assert "- [x] Meeting prep (`/meeting-prep`)" in _log(vault)


def test_a_leading_slash_is_accepted(vault: Path) -> None:
    assert analytics_helper.mark_feature_used("/meeting-prep")["status"] == "marked"
    assert "- [x] Meeting prep (`/meeting-prep`)" in _log(vault)


def test_a_plain_label_without_a_command_is_matched(vault: Path) -> None:
    result = analytics_helper.mark_feature_used("Person page created")

    assert result["status"] == "marked"
    assert "- [x] Person page created" in _log(vault)


def test_marking_twice_is_idempotent_and_writes_nothing_the_second_time(vault: Path) -> None:
    analytics_helper.mark_feature_used("meeting-prep")
    after_first = _log(vault)

    result = analytics_helper.mark_feature_used("meeting-prep")

    assert result["status"] == "already_marked"
    assert _log(vault) == after_first


def test_an_ambiguous_name_reports_candidates_and_changes_nothing(vault: Path) -> None:
    before = _log(vault)

    result = analytics_helper.mark_feature_used("journal")

    assert result["status"] == "ambiguous"
    assert sorted(result["candidates"]) == [
        "Journaling (`/journal`)",
        "Journaling setup (`/journal`)",
    ]
    assert _log(vault) == before


def test_an_unknown_feature_changes_nothing(vault: Path) -> None:
    before = _log(vault)

    assert analytics_helper.mark_feature_used("no-such-skill")["status"] == "not_found"
    assert _log(vault) == before


def test_consent_lines_are_never_touched(vault: Path) -> None:
    analytics_helper.mark_feature_used("meeting-prep")
    updated = _log(vault)

    assert "**Consent asked:** yes" in updated
    assert "**Consent decision:** opted-in" in updated
    assert "**Health telemetry:** opted-out" in updated
    assert analytics_helper.check_consent() == "opted-in"


def test_every_other_line_survives_byte_for_byte(vault: Path) -> None:
    before = _log(vault).splitlines()

    analytics_helper.mark_feature_used("meeting-prep")

    after = _log(vault).splitlines()
    assert len(before) == len(after)
    changed = [(b, a) for b, a in zip(before, after) if b != a]
    assert changed == [
        ("- [ ] Meeting prep (`/meeting-prep`)", "- [x] Meeting prep (`/meeting-prep`)")
    ]


def test_a_missing_log_is_reported_not_raised(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    result = analytics_helper.mark_feature_used("meeting-prep")

    assert result["status"] == "unavailable"
    assert not (tmp_path / "System" / "usage_log.md").exists()


def test_marking_leaves_no_temp_file_behind(vault: Path) -> None:
    analytics_helper.mark_feature_used("meeting-prep")

    assert list((vault / "System").glob("*.tmp")) == []


def test_marking_never_sends_anything(vault: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Local bookkeeping must not depend on, or trigger, the analytics transport."""
    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("mark_feature_used must not fire an analytics event")

    monkeypatch.setattr(analytics_helper, "fire_event", explode)

    assert analytics_helper.mark_feature_used("meeting-prep")["status"] == "marked"


def test_it_runs_when_analytics_consent_is_declined(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Adoption tracking is local, so opting out of analytics must not disable it."""
    (tmp_path / "System").mkdir(parents=True)
    (tmp_path / "System" / "usage_log.md").write_text(
        LOG_WITH_CONSENT.replace("opted-in", "opted-out"), encoding="utf-8"
    )
    monkeypatch.setenv("VAULT_PATH", str(tmp_path))

    assert analytics_helper.check_consent() == "opted-out"
    assert analytics_helper.is_analytics_enabled() is False
    assert analytics_helper.mark_feature_used("meeting-prep")["status"] == "marked"


def test_the_reader_sees_what_the_writer_wrote(vault: Path) -> None:
    """The parsed feature map was dead code; this is the loop closing."""
    assert analytics_helper.load_usage_log()["features"]["Meeting prep (`/meeting-prep`)"] is False

    analytics_helper.mark_feature_used("meeting-prep")

    assert analytics_helper.load_usage_log()["features"]["Meeting prep (`/meeting-prep`)"] is True


# --- the tool has to be reachable, which is the half that was missing ---


def _decode(result: list) -> dict:
    import json

    return json.loads(result[0].text)


def test_the_tool_is_registered_on_the_analytics_server() -> None:
    """The helper existed for months but no skill could reach it."""
    import asyncio

    from core.mcp import analytics_server

    names = {tool.name for tool in asyncio.run(analytics_server.list_tools())}

    assert "mark_feature_used" in names


def test_the_registered_tool_marks_a_feature_end_to_end(vault: Path) -> None:
    import asyncio

    from core.mcp import analytics_server

    payload = _decode(
        asyncio.run(analytics_server.call_tool("mark_feature_used", {"feature": "meeting-prep"}))
    )

    assert payload["status"] == "marked"
    assert "- [x] Meeting prep (`/meeting-prep`)" in _log(vault)


def test_the_registered_tool_reports_an_unknown_feature_rather_than_failing(vault: Path) -> None:
    import asyncio

    from core.mcp import analytics_server

    payload = _decode(
        asyncio.run(analytics_server.call_tool("mark_feature_used", {"feature": "no-such-skill"}))
    )

    assert payload["status"] == "not_found"


# --- the safety properties the direct write did not have ---
#
# Requested in review of #590. Each of these fails against a plain
# write_text + os.replace, which is what this file used to do.


def test_a_symlinked_system_directory_cannot_redirect_the_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A vault whose System directory is a symlink must not write outside it.

    The direct implementation resolved the path through the symlink and wrote
    to the target, which puts a vault mutation anywhere the link points.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "usage_log.md").write_text(LOG_WITH_CONSENT, encoding="utf-8")
    before = (outside / "usage_log.md").read_text(encoding="utf-8")

    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "System").symlink_to(outside, target_is_directory=True)
    monkeypatch.setenv("VAULT_PATH", str(vault))

    result = analytics_helper.mark_feature_used("meeting-prep")

    assert result["status"] == "unavailable"
    assert (outside / "usage_log.md").read_text(encoding="utf-8") == before


def test_a_symlinked_log_file_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "elsewhere.md"
    outside.write_text(LOG_WITH_CONSENT, encoding="utf-8")
    before = outside.read_text(encoding="utf-8")

    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "usage_log.md").symlink_to(outside)
    monkeypatch.setenv("VAULT_PATH", str(vault))

    result = analytics_helper.mark_feature_used("meeting-prep")

    assert result["status"] == "unavailable"
    assert outside.read_text(encoding="utf-8") == before


def test_a_tightened_file_mode_survives_a_write(vault: Path) -> None:
    """A 0600 log must not become 0644 because the umask said so.

    write_text on a fresh temporary file takes the process umask, and a rename
    over the original carries that mode with it. The plan re-states the mode.
    """
    log = vault / "System" / "usage_log.md"
    log.chmod(0o600)

    assert analytics_helper.mark_feature_used("meeting-prep")["status"] == "marked"

    assert log.stat().st_mode & 0o777 == 0o600


def test_an_unusual_but_legitimate_mode_is_also_preserved(vault: Path) -> None:
    log = vault / "System" / "usage_log.md"
    log.chmod(0o640)

    analytics_helper.mark_feature_used("meeting-prep")

    assert log.stat().st_mode & 0o777 == 0o640


def test_a_feature_tick_and_a_consent_update_do_not_lose_each_other(
    vault: Path,
) -> None:
    """The race the fixed .tmp sibling allowed, driven deterministically.

    Both mutators used to read the whole file, modify it, and write it back.
    Interleaved, the second writer's copy is built from pre-first-writer text,
    so one whole-file change disappears. Here the consent update lands from
    inside the feature tick's transform, which is exactly that interleaving.
    """
    log = vault / "System" / "usage_log.md"
    original_rewrite = analytics_helper._rewrite_usage_log_safely
    fired: list[str] = []

    def racing_rewrite(transform):
        def wrapped(current: str):
            if not fired:
                fired.append("consent")
                analytics_helper.update_consent("opted-out")
            return transform(current)

        return original_rewrite(wrapped)

    analytics_helper._rewrite_usage_log_safely = racing_rewrite
    try:
        result = analytics_helper.mark_feature_used("meeting-prep")
    finally:
        analytics_helper._rewrite_usage_log_safely = original_rewrite

    updated = log.read_text(encoding="utf-8")

    assert fired == ["consent"]
    assert result["status"] == "marked"
    # Neither change was lost: the tick landed AND the consent decision stuck.
    assert "- [x] Meeting prep (`/meeting-prep`)" in updated
    assert "**Consent decision:** opted-out" in updated


def test_consent_updates_also_go_through_the_guarded_writer(
    vault: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dave's point: the guarantee is only real if both mutators use one door."""
    seen: list[str] = []
    original = analytics_helper._rewrite_usage_log_safely

    def recording(transform):
        seen.append("used")
        return original(transform)

    monkeypatch.setattr(analytics_helper, "_rewrite_usage_log_safely", recording)

    analytics_helper.update_consent("opted-out")

    assert seen == ["used"]
    assert analytics_helper.check_consent() == "opted-out"


def test_the_operation_may_write_only_the_usage_log() -> None:
    """The contract, not the caller, is what bounds this operation."""
    from core import portable_contract

    allowed = portable_contract.update_write_verdict(
        portable_contract.USAGE_LOG_RELATIVE, exists=True, operation="usage-log"
    )
    refused = portable_contract.update_write_verdict(
        "03-Tasks/Tasks.md", exists=True, operation="usage-log"
    )

    assert allowed.allowed is True
    assert allowed.action == "write-usage-log"
    assert refused.allowed is False
    assert refused.action == "outside-usage-log"


# --- the wiring itself, pinned to an explicit expected set ---
#
# Requested in review of #593. A "at least N are wired" check cannot catch a
# specific omission: week-plan was missed and the suite stayed green. The set
# below is the contract. Adding a skill to the log without wiring it, or
# unwiring one, now fails here by name.

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SKILLS_DIR = _REPO_ROOT / ".claude" / "skills"
_INSTRUCTION = re.compile(
    r"Call the `mark_feature_used` tool on the `dex-analytics` MCP server with `([^`]+)`"
)

# skill directory -> EVERY feature argument its instruction passes. Almost all
# skills record one thing. A skill with distinct modes records the mode that
# ran, so its entry lists each one and the exact-equality check below fails if
# a mode is dropped or silently collapsed into a single unconditional call.
EXPECTED_WIRING = {
    "create-mcp": "create-mcp",
    "create-skill": "create-skill",
    "daily-plan": "daily-plan",
    "daily-review": "daily-review",
    "dex-add-mcp": "dex-add-mcp",
    "dex-backlog": "dex-backlog",
    "dex-improve": "dex-improve",
    "dex-level-up": "dex-level-up",
    "dex-obsidian-setup": "dex-obsidian-setup",
    "dex-whats-new": "dex-whats-new",
    "getting-started": "getting-started",
    "integrate-mcp": "integrate-mcp",
    # Two modes, two lines in the log. Setup can only ever be ticked by the
    # command that performs it, so the call has to follow the mode. Named by
    # label because /journal itself is ambiguous across both lines.
    "journal": ("Journaling setup", "Journaling"),
    "meeting-prep": "meeting-prep",
    "process-meetings": "process-meetings",
    "product-brief": "product-brief",
    "project-health": "project-health",
    "prompt-improver": "prompt-improver",
    "reset": "reset",
    "save-insight": "save-insight",
    "triage": "triage",
    "week-plan": "week-plan",
    "week-review": "week-review",
    "xray": "xray",
}

# Skills left on prose ON PURPOSE, each with the reason. A skill leaves this
# map only by being wired, and a new checkbox in the shipped log makes the
# reason false, which the next test detects.
DEFERRED_WIRING = {
    "commitments": "no line in the shipped usage log",
    "dex-doctor": "no line in the shipped usage log",
    "initiative-kickoff": "no line in the shipped usage log",
    "meeting-closeout": "no line in the shipped usage log",
    "relationship-radar": "no line in the shipped usage log",
}


def _actual_wiring() -> dict[str, object]:
    """Every feature each skill records, in the order its instruction states them.

    Returns a bare string for the single-call majority and a tuple for a skill
    with distinct modes, matching the shape of EXPECTED_WIRING above.
    """
    found: dict[str, object] = {}
    for skill in sorted(_SKILLS_DIR.glob("*/SKILL.md")):
        names = _INSTRUCTION.findall(skill.read_text(encoding="utf-8"))
        # Preserve order, drop repeats: a skill may restate the same call in
        # prose without that being a second, distinct thing it records.
        unique = list(dict.fromkeys(names))
        if unique:
            found[skill.parent.name] = unique[0] if len(unique) == 1 else tuple(unique)
    return found


def _features_of(entry: object) -> tuple[str, ...]:
    return (entry,) if isinstance(entry, str) else tuple(entry)


def test_exactly_the_expected_skills_are_wired() -> None:
    actual = _actual_wiring()

    assert actual == EXPECTED_WIRING, (
        "wiring drifted. Missing: "
        f"{sorted(set(EXPECTED_WIRING) - set(actual))}; "
        f"unexpected: {sorted(set(actual) - set(EXPECTED_WIRING))}; "
        "changed arguments: "
        f"{ {k: (EXPECTED_WIRING[k], actual[k]) for k in set(actual) & set(EXPECTED_WIRING) if actual[k] != EXPECTED_WIRING[k]} }"
    )


def test_every_deferred_skill_still_has_a_true_reason() -> None:
    """A deferred skill that gains a log line must stop being deferred."""
    log = (_REPO_ROOT / "System" / "usage_log.md").read_text(encoding="utf-8")
    lines = log.splitlines(keepends=True)

    now_wireable = [
        name
        for name, reason in DEFERRED_WIRING.items()
        if reason == "no line in the shipped usage log"
        and len(analytics_helper._match_feature_lines(lines, name)) == 1
    ]

    assert not now_wireable, (
        f"{now_wireable} are deferred for having no line in the log, but the log now "
        "resolves them. Wire them or change the recorded reason."
    )


def test_no_skill_mentions_the_tool_in_a_shape_this_check_cannot_read() -> None:
    """A skill the detector cannot parse is a skill nobody is validating.

    An earlier fix wrote dex-level-up's instruction in a different shape; it
    escaped the detector and the suite stayed green while nothing checked it.
    """
    readable = set(_actual_wiring())
    unreadable = [
        skill.parent.name
        for skill in sorted(_SKILLS_DIR.glob("*/SKILL.md"))
        if "mark_feature_used" in skill.read_text(encoding="utf-8")
        and skill.parent.name not in readable
    ]

    assert not unreadable, (
        f"{unreadable} reference mark_feature_used in a shape this test cannot read, "
        "so the feature name they pass is unvalidated."
    )


@pytest.mark.parametrize(
    "skill,feature",
    sorted(
        (skill, feature)
        for skill, entry in EXPECTED_WIRING.items()
        for feature in _features_of(entry)
    ),
)
def test_each_wired_skill_resolves_through_the_real_tool(
    skill: str, feature: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise the shipped log through the MCP tool, not just the matcher.

    Requested in review: the check should run at the actual tool boundary, so
    a skill's instruction is proven to move a box in the real shipped file.
    """
    import asyncio

    from core.mcp import analytics_server

    vault = tmp_path / skill
    (vault / "System").mkdir(parents=True)
    shipped = (_REPO_ROOT / "System" / "usage_log.md").read_text(encoding="utf-8")
    log = vault / "System" / "usage_log.md"
    log.write_text(shipped, encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(vault))

    payload = json.loads(
        asyncio.run(
            analytics_server.call_tool("mark_feature_used", {"feature": feature})
        )[0].text
    )

    assert payload["status"] in {"marked", "already_marked"}, (
        f"{skill} passes {feature!r}, which the shipped log answers with "
        f"{payload['status']!r}. Its instruction records nothing."
    )


# --- mode-specific scenarios ---
#
# Raised in review of #593: the journal skill runs setup and entry modes, and
# the log carries a separate line for each, so one unconditional call means
# "Journaling setup" can never be ticked by the only command that performs it.
# A count-based or one-call-per-skill check cannot see that, so the scenarios
# are written out.

# (skill, the invocation, the log line it must tick)
MODE_SCENARIOS = [
    ("journal", "/journal on", "Journaling setup"),
    ("journal", "/journal off", "Journaling setup"),
    ("journal", "/journal", "Journaling"),
    ("journal", "/journal morning", "Journaling"),
    ("journal", "/journal evening", "Journaling"),
    ("journal", "/journal week", "Journaling"),
]


@pytest.mark.parametrize("skill,invocation,feature", MODE_SCENARIOS)
def test_each_mode_names_the_line_it_should_tick(
    skill: str, invocation: str, feature: str
) -> None:
    body = (_SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")

    # Backticked throughout, which also keeps "/journal" from matching the
    # "/journal on" row as a substring and testing the wrong mode.
    quoted = f"`{invocation}`"
    assert quoted in body, f"{skill} no longer documents {invocation}; retire this case"
    assert feature in _features_of(EXPECTED_WIRING[skill]), (
        f"{skill} does not record {feature!r} at all, so {invocation} cannot tick it."
    )

    # The mode and the feature it records have to appear together, otherwise
    # the skill states two calls and leaves the reader to guess which mode
    # takes which, which is the ambiguity this test exists to prevent.
    row = next(
        (line for line in body.splitlines() if quoted in line and "mark_feature_used" in line),
        None,
    )
    assert row is not None, (
        f"{skill} records {feature!r} somewhere, but nothing ties {invocation} to a call. "
        "State the mode and its feature on the same line."
    )
    assert f"`{feature}`" in row, (
        f"{invocation} is tied to a call that does not pass {feature!r}: {row.strip()!r}"
    )


def test_a_skill_with_several_modes_never_records_them_unconditionally() -> None:
    """One call for a multi-line skill silently starves the other line.

    The failure is invisible in the output: the call succeeds, a box ticks,
    and the line that should have ticked stays empty forever.
    """
    multi = {skill for skill, _, _ in MODE_SCENARIOS}
    for skill in sorted(multi):
        features = _features_of(EXPECTED_WIRING[skill])
        expected = {feature for s, _, feature in MODE_SCENARIOS if s == skill}
        assert set(features) == expected, (
            f"{skill} records {sorted(features)} but its modes cover {sorted(expected)}. "
            "Every documented mode needs the line it ticks, and no others."
        )


def test_the_ambiguous_command_is_still_ambiguous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Why journal is wired by label: /journal matches both of its lines.

    If the log ever stops being ambiguous for /journal, the label indirection
    is no longer needed and the skill's explanation for it becomes untrue.
    """
    import asyncio

    from core.mcp import analytics_server

    vault = tmp_path / "ambiguous"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "usage_log.md").write_text(
        (_REPO_ROOT / "System" / "usage_log.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setenv("VAULT_PATH", str(vault))

    payload = json.loads(
        asyncio.run(
            analytics_server.call_tool("mark_feature_used", {"feature": "/journal"})
        )[0].text
    )

    assert payload["status"] == "ambiguous", (
        "/journal now resolves to a single line, so the journal skill's stated reason for "
        f"naming its features by label is stale: {payload}"
    )
