"""Ritual timing: hook-observed run times for Dex's heavy skills.

A user timed a day of Dex by hand and found fifteen minutes of gathering before
the first question. Nothing in Dex could have told them, because no clock ran.
This module is that clock.

Why hooks record it and not the skill: a skill reporting its own duration is
the assistant grading itself, and a slow run is exactly when it forgets. The
host already reports everything the clock needs:

* ``PreToolUse`` on the ``Skill`` tool: the run started.
* ``Stop``: Dex handed the turn back. The first one after a start is the time
  to the first hand-back, which is what a person actually feels; a ritual
  that never asks anything hands back once, at its end. From then until the
  next prompt Dex is idle and the person is the one taking time, so that
  waiting is recorded separately and never judged.
* ``UserPromptSubmit``: the person replied; Dex is working again.
* ``PreToolUse`` on ``track_event``: the rituals fire a ``*_completed``
  analytics event as their last step. When it arrives it closes the run as
  completed. It is a bonus, not a requirement: the analytics tool may not be
  registered, and a slow, messy run is exactly the one where Dex forgets its
  last step. Without it the run ends, marked ``inferred``, when the next
  skill starts in that session or the session ends. A run that never handed
  back at all when the session ended is ``abandoned`` and never judged.

Two numbers come out of every finished run: the time to the first hand-back,
which needs no end signal, and Dex's working time, the sum of the stretches
between each prompt and the following hand-back. Wall-clock time is kept for
reference and never judged.

Events are appended to ``System/.dex/ritual-timings.jsonl`` (runtime state:
never shipped, never updated, never read by anything but Doctor). Runs in
flight live in ``System/.dex/ritual-timing-active.json`` keyed by session.

Every record carries the Dex version and the skill file's checksum at the
time, so Doctor can say which release a slowdown arrived with and whether the
skill was still the shipped one.

Fail open everywhere: a hook that cannot record leaves the run exactly as it
would have been without this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import sys
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from core import paths

# A run is slow when its latest-week median is at least this long AND at least
# REGRESSION_RATIO times the median of the previous BASELINE_WEEKS weeks. Both
# conditions: a ritual that went from 20s to 40s is not worth a word, and one
# that has always taken six minutes is a design question, not a regression.
SLOW_SECONDS = 120.0
REGRESSION_RATIO = 1.5
MIN_RUNS = 3
BASELINE_WEEKS = 4
ACTIVE_RUN_TTL = timedelta(hours=24)

# The rituals whose completion event the hooks recognise. Any skill's run is
# still timed and closes as inferred when the session moves on; this map only
# lets a run close as completed the moment its own last step fires.
COMPLETION_EVENTS: dict[str, str] = {
    "daily_plan_completed": "daily-plan",
    "daily_review_completed": "daily-review",
    "meeting_processed": "process-meetings",
    "week_review_completed": "week-review",
    "week_plan_completed": "week-plan",
    "meeting_prep_completed": "meeting-prep",
    "triage_completed": "triage",
    "goal_backlog_completed": "goal-backlog",
}

# A skill started while these are open is nested inside them, even after a
# hand-back: the morning plan asks its questions and then runs the meeting
# pass. Any other skill starting after a hand-back means the person moved on.
NESTS_INSIDE: dict[str, frozenset[str]] = {
    "process-meetings": frozenset({"daily-plan", "daily-review"}),
}

HOW_COMPLETED = "completed"  # the skill's own completion event arrived
HOW_INFERRED = "inferred"  # ended when the session moved on or closed
HOW_SUPERSEDED = "superseded"  # the same skill was started again
HOW_ABANDONED = "abandoned"  # the session ended before Dex ever handed back
FINISHED = frozenset({HOW_COMPLETED, HOW_INFERRED})


# --------------------------------------------------------------------------
# Recording (called from the hook)
# --------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def events_path(vault_root: Path) -> Path:
    return paths.resolve_for_vault(vault_root, paths.RITUAL_TIMING_EVENTS_FILE)


def active_path(vault_root: Path) -> Path:
    return paths.resolve_for_vault(vault_root, paths.RITUAL_TIMING_ACTIVE_FILE)


def skill_name_from_tool_input(tool_input: object) -> str | None:
    """Normalise the Skill tool's input to a bare skill name, or None."""
    if not isinstance(tool_input, Mapping):
        return None
    for key in ("skill", "name", "skill_name", "command"):
        raw = tool_input.get(key)
        if isinstance(raw, str) and raw.strip():
            token = raw.strip().split()[0]
            token = token.lstrip("/").strip().lower()
            # A plugin-qualified name ("dex:daily-plan") times the skill itself.
            token = token.rsplit(":", 1)[-1]
            if token:
                return token
    return None


def skill_for_completion_event(event_name: object) -> str | None:
    if not isinstance(event_name, str):
        return None
    return COMPLETION_EVENTS.get(event_name.strip())


def dex_version(vault_root: Path) -> str | None:
    try:
        data = json.loads((Path(vault_root) / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    version = data.get("version") if isinstance(data, dict) else None
    return version if isinstance(version, str) and version else None


def skill_file(vault_root: Path, skill: str) -> Path:
    return Path(vault_root) / ".claude" / "skills" / skill / "SKILL.md"


def skill_sha256(vault_root: Path, skill: str) -> str | None:
    try:
        return hashlib.sha256(skill_file(vault_root, skill).read_bytes()).hexdigest()
    except OSError:
        return None


def _load_active(path: Path) -> dict[str, list[dict[str, Any]]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    cleaned: dict[str, list[dict[str, Any]]] = {}
    for session, runs in data.items():
        if isinstance(session, str) and isinstance(runs, list):
            cleaned[session] = [run for run in runs if isinstance(run, dict)]
    return cleaned


def _save_active(path: Path, active: dict[str, list[dict[str, Any]]], now: datetime) -> None:
    fresh: dict[str, list[dict[str, Any]]] = {}
    for session, runs in active.items():
        kept = []
        for run in runs:
            started = _parse_iso(run.get("started_at"))
            if started is not None and now - started <= ACTIVE_RUN_TTL:
                kept.append(run)
        if kept:
            fresh[session] = kept
    path.parent.mkdir(parents=True, exist_ok=True)
    if not fresh:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(fresh, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _append_event(path: Path, event: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def _round(seconds: float) -> float:
    return round(seconds, 1)


def _settle(run: dict[str, Any], now: datetime) -> None:
    """Fold the open segment (working or waiting) into the run's totals."""
    since = _parse_iso(run.get("segment_since"))
    if since is None:
        return
    elapsed = max(0.0, (now - since).total_seconds())
    key = "seconds_waiting" if run.get("waiting") else "seconds_working"
    run[key] = float(run.get(key) or 0.0) + elapsed
    run["segment_since"] = _iso(now)


def _close(run: dict[str, Any], *, how: str, now: datetime, event_name: str | None = None) -> dict[str, Any]:
    _settle(run, now)
    started = _parse_iso(run.get("started_at"))
    first_yield = _parse_iso(run.get("first_yield_at"))
    event: dict[str, Any] = {
        "kind": "end",
        "how": how,
        "skill": run.get("skill"),
        "session": run.get("session"),
        "started_at": run.get("started_at"),
        "ended_at": _iso(now),
        "seconds_working": _round(float(run.get("seconds_working") or 0.0)),
        "seconds_waiting": _round(float(run.get("seconds_waiting") or 0.0)),
        "seconds_wall": _round((now - started).total_seconds()) if started else None,
        "seconds_to_first_yield": (
            _round((first_yield - started).total_seconds()) if started and first_yield else None
        ),
        "yields": int(run.get("yields") or 0),
        "dex_version": run.get("dex_version"),
        "skill_sha256": run.get("skill_sha256"),
    }
    if event_name:
        event["event_name"] = event_name
    return event


def record_hook(payload: Mapping[str, Any], vault_root: Path, now: datetime | None = None) -> list[dict[str, Any]]:
    """Apply one hook payload. Returns the events appended (for tests)."""
    now = now or _utc_now()
    vault_root = Path(vault_root)
    hook = payload.get("hook_event_name")
    session = payload.get("session_id")
    if not isinstance(session, str) or not session:
        session = "unknown-session"

    events_file = events_path(vault_root)
    state_file = active_path(vault_root)
    active = _load_active(state_file)
    stack = active.get(session, [])
    appended: list[dict[str, Any]] = []

    def close_from(index: int, *, how: str, event_name: str | None = None) -> None:
        nonlocal stack
        # Everything above the closed run was nested inside it; it ends with it.
        for nested in reversed(stack[index + 1 :]):
            appended.append(_close(nested, how=HOW_SUPERSEDED, now=now))
        appended.append(_close(stack[index], how=how, now=now, event_name=event_name))
        stack = stack[:index]

    def close_moved_on(new_skill: str) -> None:
        """The person started something else after a hand-back: earlier runs are over."""
        parents = NESTS_INSIDE.get(new_skill, frozenset())
        for index, run in enumerate(stack):
            if int(run.get("yields") or 0) > 0 and run.get("skill") not in parents:
                close_from(index, how=HOW_INFERRED)
                return

    if hook == "PreToolUse":
        tool_name = payload.get("tool_name")
        tool_input = payload.get("tool_input")
        if tool_name == "Skill":
            skill = skill_name_from_tool_input(tool_input)
            if skill is None:
                return []
            for index, run in enumerate(stack):
                if run.get("skill") == skill:
                    close_from(index, how=HOW_SUPERSEDED)
                    break
            close_moved_on(skill)
            run = {
                "skill": skill,
                "session": session,
                "started_at": _iso(now),
                "segment_since": _iso(now),
                "waiting": False,
                "seconds_working": 0.0,
                "seconds_waiting": 0.0,
                "yields": 0,
                "dex_version": dex_version(vault_root),
                "skill_sha256": skill_sha256(vault_root, skill),
            }
            stack.append(run)
            appended.append(
                {
                    "kind": "start",
                    "skill": skill,
                    "session": session,
                    "at": run["started_at"],
                    "dex_version": run["dex_version"],
                    "skill_sha256": run["skill_sha256"],
                }
            )
        elif isinstance(tool_name, str) and tool_name.endswith("track_event"):
            event_name = tool_input.get("event_name") if isinstance(tool_input, Mapping) else None
            skill = skill_for_completion_event(event_name)
            if skill is None:
                return []
            for index in range(len(stack) - 1, -1, -1):
                if stack[index].get("skill") == skill:
                    close_from(index, how=HOW_COMPLETED, event_name=str(event_name))
                    break
            else:
                return []
        else:
            return []
    elif hook == "Stop":
        if not stack:
            return []
        for run in stack:
            if run.get("waiting"):
                continue
            _settle(run, now)
            run["waiting"] = True
            run["yields"] = int(run.get("yields") or 0) + 1
            if not run.get("first_yield_at"):
                run["first_yield_at"] = _iso(now)
                appended.append(
                    {
                        "kind": "first_yield",
                        "skill": run.get("skill"),
                        "session": session,
                        "at": run["first_yield_at"],
                        "started_at": run.get("started_at"),
                    }
                )
    elif hook == "UserPromptSubmit":
        if not stack:
            return []
        for run in stack:
            if run.get("waiting"):
                _settle(run, now)
                run["waiting"] = False
    elif hook == "SessionEnd":
        if not stack:
            return []
        # The outermost run decides: a run that handed back at least once has a
        # real reading; one that never did was cut off mid-turn.
        how = HOW_INFERRED if int(stack[0].get("yields") or 0) > 0 else HOW_ABANDONED
        close_from(0, how=how)
    else:
        return []

    if stack:
        active[session] = stack
    else:
        active.pop(session, None)
    for event in appended:
        _append_event(events_file, event)
    _save_active(state_file, active, now)
    return appended


def main(argv: list[str] | None = None) -> int:
    """Hook entry point: read one payload from stdin, record it, exit 0."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return 0
        raw = sys.stdin.read()
        if not raw.strip():
            return 0
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return 0
        root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
        vault_root = Path(root)
        if not paths.resolve_for_vault(vault_root, paths.SYSTEM_DIR).is_dir():
            return 0
        record_hook(payload, vault_root)
    except Exception:  # noqa: BLE001 - a timing clock must never break a run
        return 0
    return 0


# --------------------------------------------------------------------------
# Analysis (called from Doctor)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Run:
    skill: str
    session: str
    started_at: datetime
    ended_at: datetime
    seconds_working: float
    seconds_waiting: float
    seconds_to_first_yield: float | None
    yields: int
    how: str  # completed or inferred
    dex_version: str | None
    skill_sha256: str | None


@dataclass(frozen=True)
class Loaded:
    runs: tuple[Run, ...]
    malformed: int
    unfinished: int  # superseded or abandoned: started, never got a reading


def load_runs(path: Path) -> Loaded:
    """Read finished runs from the events file. Missing file raises FileNotFoundError."""
    runs: list[Run] = []
    malformed = 0
    unfinished = 0
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                malformed += 1
                continue
            if not isinstance(event, dict) or event.get("kind") != "end":
                continue
            how = event.get("how")
            if how not in FINISHED:
                unfinished += 1
                continue
            started = _parse_iso(event.get("started_at"))
            ended = _parse_iso(event.get("ended_at"))
            skill = event.get("skill")
            working = event.get("seconds_working")
            if not (started and ended and isinstance(skill, str) and isinstance(working, (int, float))):
                malformed += 1
                continue
            first = event.get("seconds_to_first_yield")
            waiting = event.get("seconds_waiting")
            runs.append(
                Run(
                    skill=skill,
                    session=str(event.get("session") or ""),
                    started_at=started,
                    ended_at=ended,
                    seconds_working=float(working),
                    seconds_waiting=float(waiting) if isinstance(waiting, (int, float)) else 0.0,
                    seconds_to_first_yield=float(first) if isinstance(first, (int, float)) else None,
                    yields=int(event.get("yields") or 0),
                    how=str(how),
                    dex_version=event.get("dex_version") if isinstance(event.get("dex_version"), str) else None,
                    skill_sha256=(
                        event.get("skill_sha256") if isinstance(event.get("skill_sha256"), str) else None
                    ),
                )
            )
    return Loaded(runs=tuple(runs), malformed=malformed, unfinished=unfinished)


def week_start(moment: datetime) -> date:
    """Monday of the ISO week containing ``moment`` (UTC)."""
    day = moment.astimezone(timezone.utc).date()
    return day - timedelta(days=day.weekday())


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


@dataclass(frozen=True)
class WeekStats:
    week: date
    runs: int
    completed: int  # closed by the skill's own event rather than inferred
    median_working: float | None
    median_first_yield: float | None
    median_waiting: float | None
    median_yields: float | None
    versions: tuple[str, ...]
    skill_shas: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["week"] = self.week.isoformat()
        return data


@dataclass(frozen=True)
class SkillTrend:
    skill: str
    runs_total: int
    latest: WeekStats | None
    baseline_runs: int
    baseline_median_working: float | None
    baseline_median_first_yield: float | None
    baseline_versions: tuple[str, ...]
    regressed: bool
    regressed_on: tuple[str, ...]
    shift_week: date | None
    shift_versions_before: tuple[str, ...]
    shift_versions_after: tuple[str, ...]
    stock: str  # "stock" | "customised" | "unpinned" | "unknown"
    skill_changed_in_window: bool
    weeks: tuple[WeekStats, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "skill": self.skill,
            "runs_total": self.runs_total,
            "latest": self.latest.as_dict() if self.latest else None,
            "baseline_runs": self.baseline_runs,
            "baseline_median_working": self.baseline_median_working,
            "baseline_median_first_yield": self.baseline_median_first_yield,
            "baseline_versions": list(self.baseline_versions),
            "regressed": self.regressed,
            "regressed_on": list(self.regressed_on),
            "shift_week": self.shift_week.isoformat() if self.shift_week else None,
            "shift_versions_before": list(self.shift_versions_before),
            "shift_versions_after": list(self.shift_versions_after),
            "stock": self.stock,
            "skill_changed_in_window": self.skill_changed_in_window,
            "weeks": [week.as_dict() for week in self.weeks],
        }


@dataclass(frozen=True)
class Assessment:
    trends: tuple[SkillTrend, ...]
    malformed: int
    unfinished: int

    @property
    def regressed(self) -> tuple[SkillTrend, ...]:
        return tuple(trend for trend in self.trends if trend.regressed)

    @property
    def judged(self) -> tuple[SkillTrend, ...]:
        """Skills with enough runs this week to be judged at all."""
        return tuple(trend for trend in self.trends if trend.latest and trend.latest.runs >= MIN_RUNS)

    def as_dict(self) -> dict[str, Any]:
        return {
            "malformed": self.malformed,
            "unfinished": self.unfinished,
            "thresholds": {
                "slow_seconds": SLOW_SECONDS,
                "regression_ratio": REGRESSION_RATIO,
                "min_runs": MIN_RUNS,
                "baseline_weeks": BASELINE_WEEKS,
            },
            "skills": [trend.as_dict() for trend in self.trends],
        }


def _week_stats(week: date, runs: list[Run]) -> WeekStats:
    return WeekStats(
        week=week,
        runs=len(runs),
        completed=sum(1 for run in runs if run.how == HOW_COMPLETED),
        median_working=_median([run.seconds_working for run in runs]),
        median_first_yield=_median([run.seconds_to_first_yield for run in runs if run.seconds_to_first_yield is not None]),
        median_waiting=_median([run.seconds_waiting for run in runs]),
        median_yields=_median([float(run.yields) for run in runs]),
        versions=tuple(sorted({run.dex_version for run in runs if run.dex_version})),
        skill_shas=tuple(sorted({run.skill_sha256 for run in runs if run.skill_sha256})),
    )


def _exceeds(latest: float | None, baseline: float | None) -> bool:
    return latest is not None and baseline is not None and latest >= SLOW_SECONDS and latest >= REGRESSION_RATIO * baseline


def assess(
    loaded: Loaded,
    *,
    now: datetime,
    shipped_pins: Mapping[str, str] | None = None,
    current_shas: Mapping[str, str | None] | None = None,
) -> Assessment:
    """Judge every skill with completed runs against its own recent history.

    ``shipped_pins`` maps skill name to the sha256 Dex shipped for its SKILL.md
    (from the Lens registry); ``current_shas`` maps skill name to the sha256 of
    the file on disk now. Together they say whether a slow skill is still the
    one Dex shipped.
    """
    shipped_pins = shipped_pins or {}
    current_shas = current_shas or {}
    this_week = week_start(now)
    window_start = this_week - timedelta(weeks=BASELINE_WEEKS)
    trends: list[SkillTrend] = []

    by_skill: dict[str, list[Run]] = {}
    for run in loaded.runs:
        by_skill.setdefault(run.skill, []).append(run)

    for skill in sorted(by_skill):
        runs = sorted(by_skill[skill], key=lambda run: run.started_at)
        by_week: dict[date, list[Run]] = {}
        for run in runs:
            by_week.setdefault(week_start(run.started_at), []).append(run)
        weeks = tuple(_week_stats(week, by_week[week]) for week in sorted(by_week) if week >= window_start)

        latest = next((week for week in reversed(weeks) if week.week == this_week), None)
        if latest is None and weeks and (this_week - weeks[-1].week) <= timedelta(weeks=1):
            latest = weeks[-1]  # early in a quiet week: judge the week just gone

        baseline_runs = [
            run for run in runs
            if latest is not None and window_start <= week_start(run.started_at) < latest.week
        ]
        baseline_working = _median([run.seconds_working for run in baseline_runs])
        baseline_first = _median([run.seconds_to_first_yield for run in baseline_runs if run.seconds_to_first_yield is not None])
        baseline_versions = tuple(sorted({run.dex_version for run in baseline_runs if run.dex_version}))

        regressed_on: list[str] = []
        if latest is not None and latest.runs >= MIN_RUNS and len(baseline_runs) >= MIN_RUNS:
            if _exceeds(latest.median_working, baseline_working):
                regressed_on.append("working")
            if _exceeds(latest.median_first_yield, baseline_first):
                regressed_on.append("first_yield")

        shift_week = None
        before: tuple[str, ...] = ()
        after: tuple[str, ...] = ()
        if regressed_on:
            previous: WeekStats | None = None
            for week in weeks:
                if week.week >= (latest.week if latest else this_week):
                    break
                previous = week
            # Walk forward to the first week that already showed the slowdown.
            prior_stats: WeekStats | None = None
            for week in weeks:
                if _exceeds(week.median_working, baseline_working) or _exceeds(week.median_first_yield, baseline_first):
                    shift_week = week.week
                    after = week.versions
                    before = prior_stats.versions if prior_stats else ()
                    break
                prior_stats = week
            if shift_week is None and latest is not None:
                shift_week = latest.week
                after = latest.versions
                before = previous.versions if previous else ()

        pin = shipped_pins.get(skill)
        current = current_shas.get(skill)
        if pin is None:
            stock = "unpinned"
        elif current is None:
            stock = "unknown"
        elif current == pin:
            stock = "stock"
        else:
            stock = "customised"
        window_shas = {run.skill_sha256 for run in runs if run.skill_sha256 and week_start(run.started_at) >= window_start}
        skill_changed = len(window_shas) > 1

        trends.append(
            SkillTrend(
                skill=skill,
                runs_total=len(runs),
                latest=latest,
                baseline_runs=len(baseline_runs),
                baseline_median_working=baseline_working,
                baseline_median_first_yield=baseline_first,
                baseline_versions=baseline_versions,
                regressed=bool(regressed_on),
                regressed_on=tuple(regressed_on),
                shift_week=shift_week,
                shift_versions_before=before,
                shift_versions_after=after,
                stock=stock,
                skill_changed_in_window=skill_changed,
                weeks=weeks,
            )
        )
    return Assessment(trends=tuple(trends), malformed=loaded.malformed, unfinished=loaded.unfinished)


def shipped_skill_pins(registry_path: Path) -> dict[str, str]:
    """Skill name -> shipped SKILL.md sha256, from the Lens registry."""
    try:
        registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    pins: dict[str, str] = {}
    for entry in registry.get("entries", []) if isinstance(registry, dict) else []:
        source = entry.get("source") if isinstance(entry, dict) else None
        if not isinstance(source, dict):
            continue
        path = source.get("path")
        sha = source.get("sha256")
        if isinstance(path, str) and isinstance(sha, str):
            parts = Path(path).parts
            if len(parts) >= 4 and parts[0] == ".claude" and parts[1] == "skills" and parts[-1] == "SKILL.md":
                pins[parts[2]] = sha
    return pins


def minutes(seconds: float | None) -> str:
    if seconds is None:
        return "no reading"
    if seconds < 90:
        return f"{int(round(seconds))}s"
    return f"{seconds / 60:.1f} min"


def describe_trend(trend: SkillTrend) -> str:
    """One plain sentence per skill for Doctor's detail line."""
    if trend.latest is None:
        return f"/{trend.skill}: no finished runs in the last {BASELINE_WEEKS + 1} weeks"
    latest = trend.latest
    head = (
        f"/{trend.skill}: {minutes(latest.median_working)} of Dex's working time median this week over "
        f"{latest.runs} run{'s' if latest.runs != 1 else ''}"
    )
    if latest.median_first_yield is not None:
        head += f", {minutes(latest.median_first_yield)} to the first hand-back"
    if latest.median_waiting:
        head += f" (plus {minutes(latest.median_waiting)} waiting on replies, not judged)"
    if trend.baseline_runs >= MIN_RUNS:
        head += (
            f"; the previous {BASELINE_WEEKS} weeks: {minutes(trend.baseline_median_working)} working"
            f", {minutes(trend.baseline_median_first_yield)} to the first hand-back"
            f" over {trend.baseline_runs} runs"
        )
    else:
        head += f"; no baseline yet ({trend.baseline_runs} earlier run{'s' if trend.baseline_runs != 1 else ''})"
    if trend.regressed:
        shift = trend.shift_week.strftime("%b %d") if trend.shift_week else "this week"
        versions = ""
        if trend.shift_versions_after:
            if trend.shift_versions_before and trend.shift_versions_before != trend.shift_versions_after:
                versions = (
                    f" as runs moved from {', '.join(trend.shift_versions_before)}"
                    f" to {', '.join(trend.shift_versions_after)}"
                )
            else:
                versions = f" on {', '.join(trend.shift_versions_after)}"
        origin = {
            "stock": "the skill file matches what Dex shipped",
            "customised": "the skill file has been edited locally",
            "unpinned": "Dex has no shipped checksum for this skill",
            "unknown": "the skill file could not be read",
        }[trend.stock]
        if trend.skill_changed_in_window:
            origin += " and changed during this window"
        head += f". Slower since the week of {shift}{versions}; {origin}"
    return head
