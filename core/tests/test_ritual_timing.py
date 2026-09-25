"""The rituals get a clock: hooks record how long they take, Doctor judges the trend."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.utils import doctor, ritual_timing

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / ".claude" / "hooks" / "ritual-timing.py"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"
HOOKS_README = REPO_ROOT / ".claude" / "hooks" / "README.md"
DOCTOR_SPEC = REPO_ROOT / "docs" / "dex-doctor-spec.md"

# A Wednesday at noon: this week's Monday is Sept 21, 2026.
NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
THIS_WEEK = ritual_timing.week_start(NOW)
SKILL_BODY = "---\nname: daily-plan\ndescription: Plan the day.\n---\n\n# /daily-plan\n"
SKILL_SHA = hashlib.sha256(SKILL_BODY.encode("utf-8")).hexdigest()


def _vault(tmp_path: Path, version: str = "1.97.20") -> Path:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "package.json").write_text(json.dumps({"version": version}), encoding="utf-8")
    for skill in ("daily-plan", "process-meetings", "daily-review"):
        skill_dir = vault / ".claude" / "skills" / skill
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(SKILL_BODY.replace("daily-plan", skill), encoding="utf-8")
    return vault


def _payload(hook: str, session: str = "sess-1", **extra: object) -> dict[str, object]:
    return {"hook_event_name": hook, "session_id": session, **extra}


def _start(skill: str, session: str = "sess-1") -> dict[str, object]:
    return _payload("PreToolUse", session, tool_name="Skill", tool_input={"skill": skill})


def _prompt(session: str = "sess-1") -> dict[str, object]:
    return _payload("UserPromptSubmit", session, prompt="ok, go ahead")


def _complete(event_name: str, session: str = "sess-1") -> dict[str, object]:
    return _payload(
        "PreToolUse",
        session,
        tool_name="mcp__dex-analytics__track_event",
        tool_input={"event_name": event_name},
    )


def _events(vault: Path) -> list[dict[str, object]]:
    path = ritual_timing.events_path(vault)
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _run_hook(vault: Path, stdin: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(vault)
    return subprocess.run(
        [sys.executable, str(HOOK)],
        cwd=vault,
        env=env,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------


def test_hook_is_wired_for_every_event_it_needs() -> None:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    hooks = settings["hooks"]

    def commands(event: str, matcher: str | None) -> list[str]:
        return [
            hook["command"]
            for group in hooks.get(event, [])
            if group.get("matcher") == matcher
            for hook in group.get("hooks", [])
        ]

    expected = 'python3 "$CLAUDE_PROJECT_DIR"/.claude/hooks/ritual-timing.py 2>/dev/null || true'
    assert expected in commands("PreToolUse", "Skill")
    assert expected in commands("PreToolUse", "mcp__.*__track_event")
    assert expected in commands("Stop", None)
    assert expected in commands("UserPromptSubmit", None)
    assert expected in commands("SessionEnd", None)
    assert HOOK.exists()
    assert os.access(HOOK, os.X_OK)


def test_hook_is_documented_and_shipped() -> None:
    assert "ritual-timing.py" in HOOKS_README.read_text(encoding="utf-8")
    assert "rituals.duration" in DOCTOR_SPEC.read_text(encoding="utf-8")
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "!.claude/hooks/ritual-timing.py" in gitignore
    assert "RITUAL_TIMING_EVENTS_FILE" in (REPO_ROOT / "core" / "paths.py").read_text(encoding="utf-8")


def test_doctor_registers_the_check_in_the_quick_registry() -> None:
    ids = [definition.id for definition in doctor.QUICK_CHECKS]
    assert "rituals.duration" in ids
    assert ids.index("rituals.duration") < ids.index("doctor.self")


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------


def test_a_completed_run_records_start_first_hand_back_and_end(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    t0 = NOW
    ritual_timing.record_hook(_start("daily-plan"), vault, now=t0)
    ritual_timing.record_hook(_payload("Stop"), vault, now=t0 + timedelta(seconds=276))
    ritual_timing.record_hook(_prompt(), vault, now=t0 + timedelta(seconds=300))
    ritual_timing.record_hook(_payload("Stop"), vault, now=t0 + timedelta(seconds=400))
    ritual_timing.record_hook(_prompt(), vault, now=t0 + timedelta(seconds=430))
    ritual_timing.record_hook(_complete("daily_plan_completed"), vault, now=t0 + timedelta(seconds=610))

    events = _events(vault)
    assert [event["kind"] for event in events] == ["start", "first_yield", "end"]
    start, first, end = events
    assert start["skill"] == "daily-plan"
    assert start["dex_version"] == "1.97.20"
    assert start["skill_sha256"] == SKILL_SHA
    assert first["at"] == "2026-09-23T12:04:36Z"
    assert end["how"] == "completed"
    assert end["event_name"] == "daily_plan_completed"
    assert end["seconds_working"] == 276.0 + 100.0 + 180.0
    assert end["seconds_waiting"] == 24.0 + 30.0
    assert end["seconds_wall"] == 610.0
    assert end["seconds_to_first_yield"] == 276.0
    assert end["yields"] == 2
    assert end["dex_version"] == "1.97.20"
    assert not ritual_timing.active_path(vault).exists(), "a finished run leaves no in-flight state"


def test_walking_away_after_a_question_does_not_count_against_dex(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    t0 = NOW
    ritual_timing.record_hook(_start("daily-plan"), vault, now=t0)
    ritual_timing.record_hook(_payload("Stop"), vault, now=t0 + timedelta(seconds=60))
    # Three hours away from the keyboard.
    ritual_timing.record_hook(_prompt(), vault, now=t0 + timedelta(hours=3))
    ritual_timing.record_hook(_payload("Stop"), vault, now=t0 + timedelta(hours=3, seconds=100))
    ritual_timing.record_hook(_complete("daily_plan_completed"), vault, now=t0 + timedelta(hours=3, seconds=100))

    (end,) = [event for event in _events(vault) if event["kind"] == "end"]
    assert end["seconds_working"] == 160.0
    assert end["seconds_waiting"] == 3 * 3600 - 60.0
    assert end["seconds_wall"] == 3 * 3600 + 100.0
    (run,) = ritual_timing.load_runs(ritual_timing.events_path(vault)).runs
    assert run.seconds_working == 160.0


def test_a_ritual_that_never_asks_anything_hands_back_once_at_its_end(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    ritual_timing.record_hook(_start("process-meetings"), vault, now=NOW)
    ritual_timing.record_hook(_complete("meeting_processed"), vault, now=NOW + timedelta(seconds=90))
    (end,) = [event for event in _events(vault) if event["kind"] == "end"]
    assert end["how"] == "completed"
    assert end["yields"] == 0
    assert end["seconds_to_first_yield"] is None
    assert end["seconds_working"] == 90.0
    # Without a completion event the first hand-back is also the end.
    vault2 = _vault(tmp_path / "two")
    ritual_timing.record_hook(_start("daily-plan"), vault2, now=NOW)
    ritual_timing.record_hook(_payload("Stop"), vault2, now=NOW + timedelta(seconds=200))
    ritual_timing.record_hook(_payload("SessionEnd"), vault2, now=NOW + timedelta(hours=2))
    (end,) = [event for event in _events(vault2) if event["kind"] == "end"]
    assert end["how"] == "inferred"
    assert end["seconds_to_first_yield"] == 200.0
    assert end["seconds_working"] == 200.0
    assert end["seconds_waiting"] == 2 * 3600 - 200.0


def test_a_run_with_no_completion_event_ends_when_the_person_moves_on(tmp_path: Path) -> None:
    """The analytics tool may be missing or the last step skipped; the reading survives."""
    vault = _vault(tmp_path)
    t0 = NOW
    ritual_timing.record_hook(_start("daily-plan"), vault, now=t0)
    ritual_timing.record_hook(_payload("Stop"), vault, now=t0 + timedelta(seconds=240))
    ritual_timing.record_hook(_prompt(), vault, now=t0 + timedelta(seconds=300))
    ritual_timing.record_hook(_payload("Stop"), vault, now=t0 + timedelta(seconds=330))
    ritual_timing.record_hook(_prompt(), vault, now=t0 + timedelta(seconds=900))
    ritual_timing.record_hook(_start("meeting-prep"), vault, now=t0 + timedelta(seconds=901))

    ends = [event for event in _events(vault) if event["kind"] == "end"]
    assert [(event["skill"], event["how"]) for event in ends] == [("daily-plan", "inferred")]
    assert ends[0]["seconds_working"] == 240.0 + 30.0 + 1.0
    assert ends[0]["seconds_to_first_yield"] == 240.0
    loaded = ritual_timing.load_runs(ritual_timing.events_path(vault))
    assert [run.how for run in loaded.runs] == ["inferred"]
    active = json.loads(ritual_timing.active_path(vault).read_text(encoding="utf-8"))
    assert [run["skill"] for run in active["sess-1"]] == ["meeting-prep"]


def test_the_meeting_pass_still_nests_inside_the_plan_after_a_question(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    t0 = NOW
    ritual_timing.record_hook(_start("daily-plan"), vault, now=t0)
    ritual_timing.record_hook(_payload("Stop"), vault, now=t0 + timedelta(seconds=30))
    ritual_timing.record_hook(_prompt(), vault, now=t0 + timedelta(seconds=60))
    ritual_timing.record_hook(_start("process-meetings"), vault, now=t0 + timedelta(seconds=61))
    ritual_timing.record_hook(_complete("meeting_processed"), vault, now=t0 + timedelta(seconds=181))
    ritual_timing.record_hook(_complete("daily_plan_completed"), vault, now=t0 + timedelta(seconds=400))

    ends = [event for event in _events(vault) if event["kind"] == "end"]
    assert [(event["skill"], event["how"]) for event in ends] == [
        ("process-meetings", "completed"),
        ("daily-plan", "completed"),
    ]
    assert ends[1]["seconds_working"] == 30.0 + 340.0


def test_a_ritual_nested_inside_another_closes_on_its_own_event(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    t0 = NOW
    ritual_timing.record_hook(_start("daily-plan"), vault, now=t0)
    ritual_timing.record_hook(_start("process-meetings"), vault, now=t0 + timedelta(seconds=10))
    ritual_timing.record_hook(_complete("meeting_processed"), vault, now=t0 + timedelta(seconds=130))
    ritual_timing.record_hook(_payload("Stop"), vault, now=t0 + timedelta(seconds=200))
    ritual_timing.record_hook(_complete("daily_plan_completed"), vault, now=t0 + timedelta(seconds=500))

    ends = [event for event in _events(vault) if event["kind"] == "end"]
    assert [(event["skill"], event["how"], event["seconds_working"]) for event in ends] == [
        ("process-meetings", "completed", 120.0),
        ("daily-plan", "completed", 200.0),
    ]
    assert ends[1]["seconds_waiting"] == 300.0, "the completion arrived while the plan was still waiting on the person"
    # The meeting pass finished before the first hand-back, so it never yielded.
    assert ends[0]["yields"] == 0
    assert ends[0]["seconds_to_first_yield"] is None
    assert ends[1]["yields"] == 1


def test_starting_the_same_ritual_again_supersedes_the_unfinished_one(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    ritual_timing.record_hook(_start("daily-plan"), vault, now=NOW)
    ritual_timing.record_hook(_start("daily-plan"), vault, now=NOW + timedelta(seconds=30))
    ritual_timing.record_hook(_complete("daily_plan_completed"), vault, now=NOW + timedelta(seconds=90))

    ends = [event for event in _events(vault) if event["kind"] == "end"]
    assert [(event["how"], event["seconds_working"]) for event in ends] == [("superseded", 30.0), ("completed", 60.0)]
    loaded = ritual_timing.load_runs(ritual_timing.events_path(vault))
    assert len(loaded.runs) == 1
    assert loaded.unfinished == 1


def test_session_end_before_any_hand_back_is_abandoned_and_never_judged(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    ritual_timing.record_hook(_start("daily-review"), vault, now=NOW)
    ritual_timing.record_hook(_payload("SessionEnd"), vault, now=NOW + timedelta(seconds=900))

    ends = [event for event in _events(vault) if event["kind"] == "end"]
    assert len(ends) == 1
    assert ends[0]["how"] == "abandoned"
    assert not ritual_timing.active_path(vault).exists()
    loaded = ritual_timing.load_runs(ritual_timing.events_path(vault))
    assert loaded.runs == ()
    assert loaded.unfinished == 1


def test_session_end_after_a_hand_back_keeps_the_reading(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    ritual_timing.record_hook(_start("daily-review"), vault, now=NOW)
    ritual_timing.record_hook(_payload("Stop"), vault, now=NOW + timedelta(seconds=45))
    ritual_timing.record_hook(_payload("SessionEnd"), vault, now=NOW + timedelta(seconds=900))

    (end,) = [event for event in _events(vault) if event["kind"] == "end"]
    assert end["how"] == "inferred"
    assert end["seconds_working"] == 45.0
    assert end["seconds_waiting"] == 855.0
    loaded = ritual_timing.load_runs(ritual_timing.events_path(vault))
    assert len(loaded.runs) == 1 and loaded.unfinished == 0


def test_sessions_are_tracked_independently(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    ritual_timing.record_hook(_start("daily-plan", session="a"), vault, now=NOW)
    ritual_timing.record_hook(_start("daily-plan", session="b"), vault, now=NOW + timedelta(seconds=5))
    ritual_timing.record_hook(_payload("Stop", session="a"), vault, now=NOW + timedelta(seconds=60))
    ritual_timing.record_hook(_complete("daily_plan_completed", session="b"), vault, now=NOW + timedelta(seconds=65))

    ends = [event for event in _events(vault) if event["kind"] == "end"]
    assert [(event["session"], event["how"], event["seconds_working"]) for event in ends] == [("b", "completed", 60.0)]
    active = json.loads(ritual_timing.active_path(vault).read_text(encoding="utf-8"))
    assert list(active) == ["a"]
    assert active["a"][0]["yields"] == 1


def test_events_that_are_not_ritual_boundaries_write_nothing(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    assert ritual_timing.record_hook(_payload("Stop"), vault, now=NOW) == []
    assert ritual_timing.record_hook(_payload("SessionEnd"), vault, now=NOW) == []
    assert ritual_timing.record_hook(_complete("some_other_event"), vault, now=NOW) == []
    assert ritual_timing.record_hook(_payload("PreToolUse", tool_name="Read", tool_input={}), vault, now=NOW) == []
    assert ritual_timing.record_hook(_payload("UserPromptSubmit"), vault, now=NOW) == []
    assert not ritual_timing.events_path(vault).exists()
    assert not ritual_timing.active_path(vault).exists()


def test_skill_names_are_normalised_from_every_input_shape() -> None:
    assert ritual_timing.skill_name_from_tool_input({"skill": "daily-plan"}) == "daily-plan"
    assert ritual_timing.skill_name_from_tool_input({"skill": "/Daily-Plan"}) == "daily-plan"
    assert ritual_timing.skill_name_from_tool_input({"skill": "dex:daily-plan", "args": "x"}) == "daily-plan"
    assert ritual_timing.skill_name_from_tool_input({"command": "process-meetings --all"}) == "process-meetings"
    assert ritual_timing.skill_name_from_tool_input({"skill": "   "}) is None
    assert ritual_timing.skill_name_from_tool_input("daily-plan") is None


def test_the_hook_process_records_a_run_end_to_end(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    for payload in (_start("daily-plan"), _payload("Stop"), _complete("daily_plan_completed")):
        result = _run_hook(vault, json.dumps(payload))
        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
        assert result.stderr == ""
    kinds = [event["kind"] for event in _events(vault)]
    assert kinds == ["start", "first_yield", "end"]


@pytest.mark.parametrize("stdin", ["", "not json", "[1, 2]", json.dumps({"hook_event_name": "Stop"})])
def test_the_hook_fails_open_on_anything_it_cannot_use(tmp_path: Path, stdin: str) -> None:
    vault = _vault(tmp_path)
    result = _run_hook(vault, stdin)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""
    assert _events(vault) == []


def test_the_hook_does_nothing_outside_a_dex_vault(tmp_path: Path) -> None:
    not_a_vault = tmp_path / "elsewhere"
    not_a_vault.mkdir()
    result = _run_hook(not_a_vault, json.dumps(_start("daily-plan")))
    assert result.returncode == 0
    assert result.stderr == ""
    assert not (not_a_vault / "System").exists()


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------


def _end_event(
    skill: str,
    started: datetime,
    total: float,
    *,
    first: float | None = 60.0,
    version: str = "1.97.19",
    sha: str = SKILL_SHA,
    how: str = "completed",
) -> dict[str, object]:
    return {
        "kind": "end",
        "how": how,
        "skill": skill,
        "session": "s",
        "started_at": ritual_timing._iso(started),
        "ended_at": ritual_timing._iso(started + timedelta(seconds=total)),
        "seconds_working": total,
        "seconds_waiting": 0.0,
        "seconds_wall": total,
        "seconds_to_first_yield": first,
        "yields": 3,
        "dex_version": version,
        "skill_sha256": sha,
    }


def _write_events(path: Path, events: list[object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [event if isinstance(event, str) else json.dumps(event) for event in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _weeks_of_runs(
    skill: str,
    *,
    weeks_ago: range,
    total: float,
    first: float | None = 60.0,
    version: str = "1.97.19",
    sha: str = SKILL_SHA,
    per_week: int = 3,
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for back in weeks_ago:
        monday = datetime.combine(THIS_WEEK - timedelta(weeks=back), datetime.min.time(), tzinfo=timezone.utc)
        for day in range(per_week):
            events.append(_end_event(skill, monday + timedelta(days=day, hours=8), total, first=first, version=version, sha=sha))
    return events


def test_a_ritual_that_stays_quick_is_not_a_regression(tmp_path: Path) -> None:
    events = _weeks_of_runs("daily-plan", weeks_ago=range(0, 5), total=95.0, first=40.0)
    loaded = ritual_timing.load_runs(_write_events(tmp_path / "t.jsonl", events))
    assessment = ritual_timing.assess(loaded, now=NOW, shipped_pins={"daily-plan": SKILL_SHA}, current_shas={"daily-plan": SKILL_SHA})
    (trend,) = assessment.trends
    assert trend.regressed is False
    assert trend.latest is not None and trend.latest.runs == 3
    assert trend.baseline_runs == 12
    assert trend.stock == "stock"
    assert "no baseline" not in ritual_timing.describe_trend(trend)


def test_a_ritual_that_has_always_been_slow_is_not_a_regression(tmp_path: Path) -> None:
    events = _weeks_of_runs("daily-review", weeks_ago=range(0, 5), total=360.0, first=200.0)
    loaded = ritual_timing.load_runs(_write_events(tmp_path / "t.jsonl", events))
    (trend,) = ritual_timing.assess(loaded, now=NOW).trends
    assert trend.regressed is False


def test_a_regression_names_the_week_and_the_release_it_arrived_with(tmp_path: Path) -> None:
    events = _weeks_of_runs("daily-plan", weeks_ago=range(2, 5), total=100.0, first=45.0, version="1.97.16")
    events += _weeks_of_runs("daily-plan", weeks_ago=range(0, 2), total=290.0, first=280.0, version="1.97.18")
    loaded = ritual_timing.load_runs(_write_events(tmp_path / "t.jsonl", events))
    assessment = ritual_timing.assess(loaded, now=NOW, shipped_pins={"daily-plan": SKILL_SHA}, current_shas={"daily-plan": SKILL_SHA})
    (trend,) = assessment.trends
    assert trend.regressed is True
    assert set(trend.regressed_on) == {"working", "first_yield"}
    assert trend.shift_week == THIS_WEEK - timedelta(weeks=1)
    assert trend.shift_versions_before == ("1.97.16",)
    assert trend.shift_versions_after == ("1.97.18",)
    assert trend.stock == "stock"
    assert trend.skill_changed_in_window is False
    described = ritual_timing.describe_trend(trend)
    assert "Slower since the week of" in described
    assert "from 1.97.16 to 1.97.18" in described
    assert "matches what Dex shipped" in described
    assert assessment.regressed == (trend,)


def test_a_slowdown_smaller_than_the_threshold_is_left_alone(tmp_path: Path) -> None:
    # 100s -> 130s is 1.3x: real, but not worth a Doctor finding.
    events = _weeks_of_runs("daily-plan", weeks_ago=range(1, 5), total=100.0)
    events += _weeks_of_runs("daily-plan", weeks_ago=range(0, 1), total=130.0)
    loaded = ritual_timing.load_runs(_write_events(tmp_path / "t.jsonl", events))
    (trend,) = ritual_timing.assess(loaded, now=NOW).trends
    assert trend.regressed is False


def test_too_few_runs_this_week_means_no_verdict(tmp_path: Path) -> None:
    events = _weeks_of_runs("daily-plan", weeks_ago=range(1, 5), total=100.0)
    events += _weeks_of_runs("daily-plan", weeks_ago=range(0, 1), total=900.0, per_week=2)
    loaded = ritual_timing.load_runs(_write_events(tmp_path / "t.jsonl", events))
    assessment = ritual_timing.assess(loaded, now=NOW)
    (trend,) = assessment.trends
    assert trend.regressed is False
    assert assessment.judged == ()


def test_a_locally_edited_skill_is_reported_as_customised(tmp_path: Path) -> None:
    edited = hashlib.sha256(b"edited").hexdigest()
    events = _weeks_of_runs("daily-plan", weeks_ago=range(1, 5), total=100.0)
    events += _weeks_of_runs("daily-plan", weeks_ago=range(0, 1), total=400.0, sha=edited)
    loaded = ritual_timing.load_runs(_write_events(tmp_path / "t.jsonl", events))
    (trend,) = ritual_timing.assess(
        loaded, now=NOW, shipped_pins={"daily-plan": SKILL_SHA}, current_shas={"daily-plan": edited}
    ).trends
    assert trend.regressed is True
    assert trend.stock == "customised"
    assert trend.skill_changed_in_window is True
    described = ritual_timing.describe_trend(trend)
    assert "edited locally" in described
    assert "changed during this window" in described


def test_malformed_and_unfinished_lines_are_counted_not_fatal(tmp_path: Path) -> None:
    good = _end_event("daily-plan", NOW - timedelta(days=1), 120.0)
    abandoned = _end_event("daily-plan", NOW - timedelta(days=2), 30.0, how="abandoned")
    inferred = _end_event("daily-plan", NOW - timedelta(days=3), 80.0, how="inferred")
    missing_fields = {"kind": "end", "how": "completed", "skill": "daily-plan"}
    path = _write_events(tmp_path / "t.jsonl", [good, "{not json", abandoned, inferred, missing_fields, {"kind": "start"}, ""])
    loaded = ritual_timing.load_runs(path)
    assert [run.how for run in loaded.runs] == ["completed", "inferred"]
    assert loaded.malformed == 2
    assert loaded.unfinished == 1
    assessment = ritual_timing.assess(loaded, now=NOW)
    assert assessment.as_dict()["malformed"] == 2
    assert assessment.as_dict()["unfinished"] == 1


def test_shipped_pins_come_from_the_lens_registry(tmp_path: Path) -> None:
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "entries": [
                    {"id": "daily-plan", "source": {"path": ".claude/skills/daily-plan/SKILL.md", "sha256": "abc"}},
                    {"id": "work-mcp", "source": {"path": "core/mcp/work_server.py", "sha256": "def"}},
                    {"id": "broken", "source": "nope"},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert ritual_timing.shipped_skill_pins(registry) == {"daily-plan": "abc"}
    assert ritual_timing.shipped_skill_pins(tmp_path / "missing.json") == {}
    live = ritual_timing.shipped_skill_pins(REPO_ROOT / "core" / "lens-catalog" / "registry.json")
    assert {"daily-plan", "daily-review", "process-meetings"} <= set(live)


def test_minutes_reads_like_a_person_wrote_it() -> None:
    assert ritual_timing.minutes(None) == "no reading"
    assert ritual_timing.minutes(42.4) == "42s"
    assert ritual_timing.minutes(276.0) == "4.6 min"


# --------------------------------------------------------------------------
# Doctor
# --------------------------------------------------------------------------


def _context(vault: Path) -> doctor.DoctorContext:
    return doctor.DoctorContext(vault_root=vault, repo_root=vault, home=vault / "home", now=NOW)


def _write_registry(vault: Path, pins: dict[str, str]) -> None:
    registry = vault / "core" / "lens-catalog" / "registry.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(
        json.dumps(
            {
                "entries": [
                    {"id": skill, "source": {"path": f".claude/skills/{skill}/SKILL.md", "sha256": sha}}
                    for skill, sha in pins.items()
                ]
            }
        ),
        encoding="utf-8",
    )


def test_doctor_is_calm_before_any_run_has_finished(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    result = doctor._probe_ritual_duration(_context(vault))
    assert result.verdict == "OK"
    assert result.feature_status == "ok"
    assert "No finished ritual runs recorded yet" in result.detail
    assert result.structured_detail["state"] == "no-runs"


def test_doctor_reports_steady_rituals_as_healthy_with_their_times(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _write_registry(vault, {"daily-plan": SKILL_SHA})
    events = _weeks_of_runs("daily-plan", weeks_ago=range(0, 5), total=95.0, first=40.0)
    _write_events(ritual_timing.events_path(vault), events)
    result = doctor._probe_ritual_duration(_context(vault))
    assert result.verdict == "OK"
    assert "none slower than its own history" in result.detail
    assert "/daily-plan: 1.6 min of Dex's working time median this week over 3 runs, 40s to the first hand-back" in result.detail
    assert result.structured_detail["state"] == "steady"
    assert result.structured_detail["skills"][0]["stock"] == "stock"


def test_doctor_flags_a_stock_ritual_that_regressed_and_offers_feedback(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    _write_registry(vault, {"daily-plan": SKILL_SHA})
    events = _weeks_of_runs("daily-plan", weeks_ago=range(2, 5), total=100.0, first=45.0, version="1.97.16")
    events += _weeks_of_runs("daily-plan", weeks_ago=range(0, 2), total=290.0, first=280.0, version="1.97.18")
    _write_events(ritual_timing.events_path(vault), events)
    result = doctor._probe_ritual_duration(_context(vault))
    assert result.verdict == "BROKEN"
    assert result.feature_status == "broken"
    assert result.detail.startswith("Slower than their own history: /daily-plan.")
    assert result.heal is not None and result.heal.tier == 3 and result.heal.applied is False
    assert result.user_message is not None
    assert "/daily-plan is taking markedly longer" in result.user_message
    assert "Dex's to fix, not yours" in result.user_message
    assert "slower on Dex 1.97.18" in result.user_message
    assert "/feedback" in result.user_message
    assert "nothing from your notes goes with it" in result.user_message
    assert result.structured_detail["state"] == "regressed"


def test_doctor_points_at_the_local_edit_when_the_slow_skill_was_customised(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    shipped = hashlib.sha256(b"what dex shipped").hexdigest()
    _write_registry(vault, {"daily-plan": shipped})
    events = _weeks_of_runs("daily-plan", weeks_ago=range(1, 5), total=100.0, sha=shipped)
    events += _weeks_of_runs("daily-plan", weeks_ago=range(0, 1), total=400.0)
    _write_events(ritual_timing.events_path(vault), events)
    result = doctor._probe_ritual_duration(_context(vault))
    assert result.verdict == "BROKEN"
    assert "edited locally" in result.user_message
    assert "Dex's to fix" not in result.user_message
    assert result.structured_detail["skills"][0]["stock"] == "customised"


def test_doctor_cannot_judge_a_log_it_cannot_read(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    path = ritual_timing.events_path(vault)
    path.parent.mkdir(parents=True)
    path.mkdir()  # a directory where the log should be: reading it raises, not FileNotFoundError
    result = doctor._probe_ritual_duration(_context(vault))
    assert result.verdict == "UNKNOWN"
    assert result.feature_status == "unknown"
    assert "Could not read the ritual timing log" in result.detail


def test_doctor_quick_run_includes_the_check(tmp_path: Path) -> None:
    vault = _vault(tmp_path)
    report = doctor.collect(context=_context(vault), deep=False, only=["rituals.duration"])
    ids = [check["id"] for check in report["checks"]]
    assert ids == ["rituals.duration", "doctor.self"]
