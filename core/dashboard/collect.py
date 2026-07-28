#!/usr/bin/env python3
"""Collect read-only, privacy-safe data for the local Dex Dashboard."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    import yaml
except ImportError:  # Bare system Python is a supported degraded runtime.
    yaml = None

from core.mcp.analytics_helper import calculate_journey_metadata, load_usage_log
from core.paths import (
    COMPANIES_DIR,
    COMPANY_INDEX_FILE,
    INTEGRATION_CONFIG_FILE,
    MCP_CONFIG_TARGET,
    MEETING_CACHE_FILE,
    MEETINGS_DIR,
    PEOPLE_DIR,
    PEOPLE_INDEX_FILE,
    PILLARS_FILE,
    PROJECTS_DIR,
    QUARTER_GOALS_FILE,
    SKILL_RATINGS_FILE,
    SYSTEM_DIR,
    TASKS_FILE,
    USER_PROFILE_FILE,
    VAULT_ROOT,
    WEEK_PRIORITIES_FILE,
)

COLLECTOR_VERSION = "1"
SECRET_KEY = re.compile(r"(api_key|token|secret|password|credential|key$)", re.IGNORECASE)
TASK_ID = re.compile(r"\^task-\d{8}-\d{3}\b")
TASK_DONE = re.compile(r"^\s*-\s+\[[xX]\]", re.MULTILINE)
COMPLETION_STAMP = re.compile(r"✅\s*(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}")
DATE_FRAGMENT = re.compile(r"(?<!\d)(\d{4})[-_](\d{2})[-_](\d{2})(?!\d)")
SKILL_COMMAND = re.compile(r"/([a-z0-9][a-z0-9-]*)", re.IGNORECASE)
GRANOLA_ENV_LINE = re.compile(r"^\s*(?:export\s+)?GRANOLA_API_KEY\s*=")
EVENT_SUFFIXES = ("_completed", "_viewed", "_started", "_rated")
EVENT_SKILL_NAMES = {
    "daily_plan": "daily-plan",
    "daily_review": "daily-review",
    "week_plan": "week-plan",
    "week_review": "week-review",
    "quarter_plan": "quarter-plan",
    "quarter_review": "quarter-review",
    "meeting_prep": "meeting-prep",
    "process_meetings": "process-meetings",
    "whats_new": "dex-whats-new",
    "level_up": "dex-level-up",
    "career_coach": "career-coach",
}
QUARTER_GOALS_BLANK_TEMPLATE = (
    "# Quarter Goals\n\n"
    "This file is provisioned only when the Quarter Goals room is enabled."
)
WEEK_PRIORITIES_TEMPLATE_PROSE = {
    "The most important outcomes for this week. Everything else is secondary.",
    "How does this week's work align to your strategic pillars?",
    "Tasks from last week that still need attention:",
}
WEEK_PRIORITIES_TEMPLATE_TABLE_CELLS = {
    "balance",
    "day",
    "fri",
    "meeting",
    "mon",
    "pillar",
    "prep needed",
    "tasks/focus",
    "thu",
    "time",
    "tue",
    "wed",
    "⬜",
}


def _short_error(error: Exception) -> str:
    message = str(error).strip().splitlines()[0] if str(error).strip() else error.__class__.__name__
    return message[:160]


def _safe(collector: Callable[[], Any]) -> Any:
    try:
        return collector()
    except Exception as error:
        return {"error": _short_error(error)}


def _at(vault: Path, configured_path: Path) -> Path:
    """Rebase a core.paths constant from its configured vault onto this invocation."""
    return vault / configured_path.relative_to(VAULT_ROOT)


def _load_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise RuntimeError("pyyaml unavailable")
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError as error:
        raise RuntimeError("yaml could not be read") from error
    except yaml.YAMLError as error:
        raise ValueError("yaml could not be parsed") from error
    if not isinstance(parsed, dict):
        raise ValueError("yaml root must be an object")
    return parsed


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _bool_mapping(value: Any, keys: tuple[str, ...]) -> dict[str, bool]:
    source = _mapping(value)
    return {key: source[key] for key in keys if isinstance(source.get(key), bool)}


def _collect_profile(vault: Path) -> dict[str, Any]:
    path = _at(vault, USER_PROFILE_FILE)
    if not path.is_file():
        return {
            "status": "not configured",
            "name": "",
            "role": "",
            "company": "",
            "communication": {},
            "analytics": {"enabled": None},
            "entity_creation": {},
            "journaling": {},
            "quarterly_planning": {"enabled": None},
        }
    profile = _load_yaml(path)
    capabilities = _mapping(profile.get("capabilities"))
    quarter_room = _mapping(capabilities.get("quarter_goals"))
    legacy_quarter = _mapping(profile.get("quarterly_planning"))
    quarter_enabled = quarter_room.get("enabled")
    if not isinstance(quarter_enabled, bool):
        quarter_enabled = legacy_quarter.get("enabled")
    if not isinstance(quarter_enabled, bool):
        quarter_enabled = None
    return {
        "status": "configured",
        "name": str(profile.get("name") or ""),
        "role": str(profile.get("role") or ""),
        "company": str(profile.get("company") or ""),
        "communication": _bool_or_scalar_preferences(profile.get("communication")),
        "analytics": {"enabled": _mapping(profile.get("analytics")).get("enabled")},
        "entity_creation": _selected_mapping(profile.get("entity_creation"), ("mode",)),
        "journaling": _bool_mapping(profile.get("journaling"), ("morning", "evening", "weekly")),
        "quarterly_planning": {"enabled": quarter_enabled},
    }


def _bool_or_scalar_preferences(value: Any) -> dict[str, Any]:
    source = _mapping(value)
    keys = ("formality", "directness", "detail_level", "career_level", "coaching_style")
    return {key: source[key] for key in keys if isinstance(source.get(key), (str, bool, int, float))}


def _selected_mapping(value: Any, keys: tuple[str, ...]) -> dict[str, Any]:
    source = _mapping(value)
    return {key: source[key] for key in keys if isinstance(source.get(key), (str, bool, int, float))}


def _collect_pillars(vault: Path) -> list[dict[str, str]]:
    path = _at(vault, PILLARS_FILE)
    if not path.is_file():
        return []
    raw = _load_yaml(path).get("pillars", [])
    if not isinstance(raw, list):
        raise ValueError("pillars must be a list")
    pillars = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        pillars.append(
            {
                "id": str(item.get("id") or ""),
                "name": str(item.get("name") or ""),
                "description": str(item.get("description") or ""),
            }
        )
    return pillars


def _redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _redact_secrets(item)
            for key, item in value.items()
            if not SECRET_KEY.search(str(key))
        }
    if isinstance(value, list):
        return [_redact_secrets(item) for item in value]
    return value


def _json_scalar(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (str, bool, int, float)) or value is None:
        return value
    return str(value)


def _flatten_boolean_features(value: Any, prefix: str = "") -> dict[str, bool]:
    result: dict[str, bool] = {}
    if not isinstance(value, dict):
        return result
    for key, item in value.items():
        label = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, bool):
            result[label] = item
        elif isinstance(item, dict):
            result.update(_flatten_boolean_features(item, label))
    return result


def _collect_integrations(vault: Path) -> dict[str, Any]:
    path = _at(vault, INTEGRATION_CONFIG_FILE)
    if not path.is_file():
        return {"apps": {}, "enabled_count": 0}
    config = _redact_secrets(_load_yaml(path))
    enabled = _mapping(config.get("enabled"))
    reserved = {"enabled", "hooks", "detected", "last_updated"}
    app_names = {str(name) for name in enabled}
    for name, value in config.items():
        if name not in reserved and isinstance(value, dict):
            if any(key in value for key in ("enabled", "configured_at", "features")):
                app_names.add(str(name))

    hooks = _mapping(config.get("hooks"))
    apps: dict[str, dict[str, Any]] = {}
    for app_name in sorted(app_names):
        details = _mapping(config.get(app_name))
        is_enabled = enabled.get(app_name, details.get("enabled", False))
        features = _flatten_boolean_features(details.get("features"))
        for hook_name, hook_config in hooks.items():
            if not isinstance(hook_config, dict):
                continue
            for key, flag in hook_config.items():
                if isinstance(flag, bool) and key in {app_name, f"use_{app_name}", f"{app_name}_enabled"}:
                    features[str(hook_name)] = flag
        app: dict[str, Any] = {"enabled": bool(is_enabled)}
        if "configured_at" in details:
            app["configured_at"] = _json_scalar(details["configured_at"])
        if features:
            app["features"] = dict(sorted(features.items()))
        apps[app_name] = app
    return {
        "apps": apps,
        "enabled_count": sum(1 for app in apps.values() if app["enabled"]),
    }


def _mcp_server_names(vault: Path) -> tuple[list[str], bool]:
    path = _at(vault, MCP_CONFIG_TARGET)
    if not path.is_file():
        return [], False
    try:
        config = _read_json(path)
    except (OSError, json.JSONDecodeError):
        return [], False
    servers = _mapping(_mapping(config).get("mcpServers"))
    names = sorted(
        name
        for raw_name in servers
        if (name := str(raw_name).strip())
    )
    return names, True


def _env_file_has_granola_key(vault: Path) -> bool:
    path = vault / ".env"
    if not path.is_file():
        return False
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            return any(
                GRANOLA_ENV_LINE.match(line) is not None
                for line in handle
                if not line.lstrip().startswith("#")
            )
    except OSError:
        return False


def _collect_connections(vault: Path, integrations: Any) -> dict[str, Any]:
    sources: list[str] = []
    dex_integrations_on = 0
    config_path = _at(vault, INTEGRATION_CONFIG_FILE)
    if (
        config_path.is_file()
        and isinstance(integrations, dict)
        and "error" not in integrations
        and isinstance(integrations.get("enabled_count"), int)
    ):
        dex_integrations_on = integrations["enabled_count"]
        sources.append("integrations config")

    mcp_servers, mcp_readable = _mcp_server_names(vault)
    if mcp_readable:
        sources.append(".mcp.json")

    granola_key_present = (
        "GRANOLA_API_KEY" in os.environ
        or _env_file_has_granola_key(vault)
    )
    sources.append("environment")
    mcp_count = len(mcp_servers)
    return {
        "mcp_servers": mcp_servers,
        "mcp_count": mcp_count,
        "dex_integrations_on": dex_integrations_on,
        "granola_key_present": granola_key_present,
        "total_connected": (
            mcp_count
            + dex_integrations_on
            + int(granola_key_present)
        ),
        "sources": sources,
    }


@contextmanager
def _vault_environment(vault: Path) -> Iterator[None]:
    previous = os.environ.get("VAULT_PATH")
    os.environ["VAULT_PATH"] = str(vault)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("VAULT_PATH", None)
        else:
            os.environ["VAULT_PATH"] = previous


def _collect_usage(vault: Path) -> dict[str, Any]:
    with _vault_environment(vault):
        raw = load_usage_log()
        journey = calculate_journey_metadata()
    features = _mapping(raw.get("features"))
    normalized = {str(name): bool(used) for name, used in sorted(features.items())}
    return {
        "features": normalized,
        "metadata": _mapping(raw.get("metadata")),
        "counts": {
            "available": len(normalized),
            "used": sum(normalized.values()),
        },
        "journey": journey,
    }


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _week_labels(now: datetime) -> list[str]:
    monday = now.date() - timedelta(days=now.weekday())
    labels = []
    for weeks_ago in range(11, -1, -1):
        day = monday - timedelta(weeks=weeks_ago)
        iso = day.isocalendar()
        labels.append(f"{iso.year}-W{iso.week:02d}")
    return labels


def _normalize_skill_reference(value: str) -> str:
    return value.strip().lower().lstrip("/").replace("_", "-")


def _event_skill_name(value: str) -> str:
    normalized = value.strip().lower().lstrip("/").replace("-", "_")
    for suffix in EVENT_SUFFIXES:
        if normalized.endswith(suffix):
            normalized = normalized.removesuffix(suffix)
            break
    return EVENT_SKILL_NAMES.get(normalized, normalized.replace("_", "-"))


def _event_skill_names(entry: dict[str, Any]) -> set[str]:
    names = set()
    event = entry.get("event") or entry.get("event_name")
    if isinstance(event, str):
        names.add(_event_skill_name(event))
    properties = _mapping(entry.get("properties"))
    for key in ("skill_name", "skill"):
        value = properties.get(key)
        if isinstance(value, str):
            names.add(_normalize_skill_reference(value))
    return {name for name in names if name}


def _collect_analytics(vault: Path, now: datetime) -> dict[str, Any]:
    path = _at(vault, SYSTEM_DIR) / "analytics_log.jsonl"
    labels = _week_labels(now)
    weekly = {label: 0 for label in labels}
    by_event: Counter[str] = Counter()
    total = 0
    malformed = 0
    skill_names: set[str] = set()
    if not path.is_file():
        return {
            "total": 0,
            "by_event": {},
            "by_iso_week": weekly,
            "malformed_lines": 0,
            "skill_names_used": [],
        }
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(entry, dict):
                malformed += 1
                continue
            event = entry.get("event") or entry.get("event_name")
            if not isinstance(event, str) or not event.strip():
                malformed += 1
                continue
            total += 1
            by_event[event.strip()] += 1
            skill_names.update(_event_skill_names(entry))
            timestamp = _parse_datetime(entry.get("timestamp") or entry.get("ts"))
            if timestamp is not None:
                iso = timestamp.date().isocalendar()
                label = f"{iso.year}-W{iso.week:02d}"
                if label in weekly:
                    weekly[label] += 1
    return {
        "total": total,
        "by_event": dict(sorted(by_event.items())),
        "by_iso_week": weekly,
        "malformed_lines": malformed,
        "skill_names_used": sorted(skill_names),
    }


def _collect_tasks(vault: Path, now: datetime) -> dict[str, int]:
    path = _at(vault, TASKS_FILE)
    if not path.is_file():
        return {"total": 0, "completed": 0, "completed_last_7_days": 0}
    content = path.read_text(encoding="utf-8", errors="replace")
    cutoff = now.date() - timedelta(days=6)
    recent = 0
    for stamp in COMPLETION_STAMP.findall(content):
        try:
            completed_on = date.fromisoformat(stamp)
        except ValueError:
            continue
        if cutoff <= completed_on <= now.date():
            recent += 1
    return {
        "total": len(TASK_ID.findall(content)),
        "completed": len(TASK_DONE.findall(content)),
        "completed_last_7_days": recent,
    }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _markdown_files(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(
        path
        for path in root.rglob("*.md")
        if path.is_file() and path.name.casefold() != "readme.md"
    )


def _people_from_filesystem(vault: Path, source: str) -> dict[str, Any]:
    root = _at(vault, PEOPLE_DIR)
    files = _markdown_files(root)
    internal = 0
    external = 0
    for path in files:
        parts = {part.casefold() for part in path.relative_to(root).parts}
        internal += "internal" in parts
        external += "external" in parts
    return {
        "total": len(files),
        "internal": internal,
        "external": external,
        "source": source,
    }


def _collect_people(vault: Path) -> dict[str, Any]:
    filesystem = _people_from_filesystem(vault, "filesystem")
    index_path = _at(vault, PEOPLE_INDEX_FILE)
    if index_path.is_file():
        try:
            index = _read_json(index_path)
            people = index.get("people", []) if isinstance(index, dict) else []
            total = index.get("total") if isinstance(index, dict) else None
            if isinstance(total, int) and total >= 0 and isinstance(people, list):
                if filesystem["total"] > total:
                    filesystem["source"] = "filesystem (index stale)"
                    return filesystem
                internal = 0
                external = 0
                for person in people:
                    path = str(person.get("path", "")) if isinstance(person, dict) else ""
                    parts = {part.casefold() for part in Path(path).parts}
                    internal += "internal" in parts
                    external += "external" in parts
                return {
                    "total": total,
                    "internal": internal,
                    "external": external,
                    "source": "index",
                }
        except (OSError, json.JSONDecodeError):
            pass
    return filesystem


def _collect_companies(vault: Path) -> dict[str, Any]:
    index_path = _at(vault, COMPANY_INDEX_FILE)
    if index_path.is_file():
        try:
            index = _read_json(index_path)
            total = index.get("total") if isinstance(index, dict) else None
            companies = index.get("companies") if isinstance(index, dict) else None
            if isinstance(total, int) and total >= 0 and isinstance(companies, list):
                return {"total": total, "source": "index"}
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "total": len(_markdown_files(_at(vault, COMPANIES_DIR))),
        "source": "filesystem",
    }


def _date_from_path(path: Path) -> date | None:
    match = DATE_FRAGMENT.search(path.as_posix())
    if match is None:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


def _meeting_dates_from_cache(cache_path: Path) -> list[date | None]:
    if not cache_path.is_file():
        return []
    try:
        cache = _read_json(cache_path)
    except (OSError, json.JSONDecodeError):
        return []
    meetings = cache.get("meetings", []) if isinstance(cache, dict) else []
    if not isinstance(meetings, list):
        return []
    dates = []
    for meeting in meetings:
        raw = meeting.get("date") if isinstance(meeting, dict) else None
        try:
            dates.append(date.fromisoformat(raw) if isinstance(raw, str) else None)
        except ValueError:
            dates.append(None)
    return dates


def _collect_meetings(vault: Path, now: datetime) -> dict[str, int]:
    root = _at(vault, MEETINGS_DIR)
    files = _markdown_files(root)
    meeting_dates: list[date | None] = []
    for path in files:
        dated = _date_from_path(path.relative_to(root))
        if dated is None:
            dated = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date()
        meeting_dates.append(dated)
    if not files:
        meeting_dates = _meeting_dates_from_cache(_at(vault, MEETING_CACHE_FILE))
    cutoff_7 = now.date() - timedelta(days=6)
    cutoff_30 = now.date() - timedelta(days=29)
    return {
        "total": len(meeting_dates),
        "last_7_days": sum(dated is not None and cutoff_7 <= dated <= now.date() for dated in meeting_dates),
        "last_30_days": sum(dated is not None and cutoff_30 <= dated <= now.date() for dated in meeting_dates),
    }


def _collect_projects(vault: Path) -> dict[str, int]:
    root = _at(vault, PROJECTS_DIR)
    if not root.is_dir():
        return {"total": 0, "directories": 0, "files": 0}
    entries = [entry for entry in root.iterdir() if not entry.name.startswith(".")]
    directories = sum(entry.is_dir() for entry in entries)
    files = sum(entry.is_file() for entry in entries)
    return {"total": directories + files, "directories": directories, "files": files}


def _collect_health(vault: Path, now: datetime) -> dict[str, Any]:
    path = _at(vault, SYSTEM_DIR) / ".doctor-last-run.json"
    guidance = "run /dex-doctor for a fresh checkup"
    if not path.is_file():
        return {
            "label": "cached dex-doctor check",
            "status": "missing",
            "guidance": guidance,
        }
    report = _read_json(path)
    if not isinstance(report, dict):
        raise ValueError("doctor cache must contain an object")
    generated = _parse_datetime(report.get("generated_at"))
    fresh = generated is not None and now - generated <= timedelta(days=7)
    checks = []
    for check in report.get("checks", []):
        if not isinstance(check, dict):
            continue
        checks.append(
            {
                "id": str(check.get("id") or ""),
                "feature": str(check.get("feature") or check.get("id") or "Unknown check"),
                "verdict": str(check.get("verdict") or "UNKNOWN").upper(),
            }
        )
    summary = {
        key: value
        for key, value in sorted(_mapping(report.get("summary")).items())
        if key in {"ok", "off", "broken", "unknown"} and isinstance(value, int)
    }
    result: dict[str, Any] = {
        "label": "cached dex-doctor check",
        "status": "fresh" if fresh else "stale",
        "generated_at": report.get("generated_at"),
        "mode": str(report.get("mode") or "unknown"),
        "checks": checks,
        "summary": summary,
    }
    if not fresh:
        result["guidance"] = guidance
    return result


def _load_skills_list(path: Path | None) -> list[str]:
    if path is None:
        return []
    raw = _read_json(path)
    if isinstance(raw, dict):
        raw = raw.get("skills", [])
    if not isinstance(raw, list):
        raise ValueError("skills list must be a JSON list")
    names = []
    for item in raw:
        name = item.get("name") if isinstance(item, dict) else item
        if isinstance(name, str) and name.strip():
            names.append(name.strip().lstrip("/"))
    return sorted(set(names))


def _collect_ratings(vault: Path) -> dict[str, dict[str, float | int]]:
    path = _at(vault, SKILL_RATINGS_FILE)
    scores: defaultdict[str, list[float]] = defaultdict(list)
    if path.is_file():
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue
                skill = entry.get("skill")
                rating = entry.get("rating")
                if isinstance(skill, str) and isinstance(rating, (int, float)) and 1 <= rating <= 5:
                    scores[skill].append(float(rating))
    return {
        skill: {"average": round(sum(values) / len(values), 1), "count": len(values)}
        for skill, values in sorted(scores.items())
    }


def _ritual_usage_evidence(
    skill_name: str,
    usage: Any,
    analytics: Any,
) -> dict[str, bool | str]:
    if isinstance(usage, dict):
        for feature, used in _mapping(usage.get("features")).items():
            if not used:
                continue
            commands = {
                _normalize_skill_reference(command)
                for command in SKILL_COMMAND.findall(str(feature))
            }
            if skill_name in commands:
                return {
                    "used": True,
                    "evidence": f"usage_log.md marks /{skill_name} used",
                }
    if isinstance(analytics, dict):
        for event_name, count in _mapping(analytics.get("by_event")).items():
            if (
                isinstance(event_name, str)
                and isinstance(count, int)
                and count > 0
                and _event_skill_name(event_name) == skill_name
            ):
                return {
                    "used": True,
                    "evidence": f"analytics event {event_name}",
                }
        used_names = {
            _normalize_skill_reference(name)
            for name in analytics.get("skill_names_used", [])
            if isinstance(name, str)
        }
        if skill_name in used_names:
            return {
                "used": True,
                "evidence": f"analytics recorded /{skill_name}",
            }
    return {
        "used": False,
        "evidence": "no usage or analytics event found",
    }


def _normalized_markdown(content: str) -> str:
    return "\n".join(line.rstrip() for line in content.splitlines()).strip()


def _quarter_goals_set(vault: Path) -> bool:
    path = _at(vault, QUARTER_GOALS_FILE)
    if not path.is_file():
        return False
    content = _normalized_markdown(
        path.read_text(encoding="utf-8", errors="replace")
    )
    return content not in {
        "",
        "# Quarter Goals",
        QUARTER_GOALS_BLANK_TEMPLATE,
    }


def _table_has_week_priority_content(line: str) -> bool:
    cells = [
        cell.strip()
        for cell in line.strip("|").split("|")
        if cell.strip()
    ]
    for cell in cells:
        lowered = cell.casefold()
        if re.fullmatch(r":?-{2,}:?", cell):
            continue
        if lowered in WEEK_PRIORITIES_TEMPLATE_TABLE_CELLS:
            continue
        if re.fullmatch(r"pillar\s+\d+", lowered):
            continue
        return True
    return False


def _week_priorities_set(vault: Path) -> bool:
    path = _at(vault, WEEK_PRIORITIES_FILE)
    if not path.is_file():
        return False
    content = path.read_text(encoding="utf-8", errors="replace")
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line == "---":
            continue
        if line.startswith("**Week of:**"):
            week = line.partition(":")[2].strip("* ")
            if week and "{{" not in week and "[" not in week:
                return True
            continue
        numbered = re.fullmatch(r"\d+\.\s*(.*)", line)
        if numbered is not None:
            if numbered.group(1).strip():
                return True
            continue
        checkbox = re.fullmatch(r"-\s+\[[ xX]\]\s*(.*)", line)
        if checkbox is not None:
            if checkbox.group(1).strip():
                return True
            continue
        bullet = re.fullmatch(r"-\s*(.*)", line)
        if bullet is not None:
            if bullet.group(1).strip():
                return True
            continue
        if line.startswith("|"):
            if _table_has_week_priority_content(line):
                return True
            continue
        if line.startswith("*") and line.endswith("*"):
            continue
        if line in WEEK_PRIORITIES_TEMPLATE_PROSE:
            continue
        return True
    return False


def _collect_rituals(vault: Path, usage: Any, analytics: Any) -> dict[str, Any]:
    quarter_goals_set = _quarter_goals_set(vault)
    week_priorities_set = _week_priorities_set(vault)
    return {
        "daily_plan": _ritual_usage_evidence("daily-plan", usage, analytics),
        "week_plan": _ritual_usage_evidence("week-plan", usage, analytics),
        "week_review": _ritual_usage_evidence("week-review", usage, analytics),
        "quarter_goals": {
            "set": quarter_goals_set,
            "evidence": (
                "Quarter_Goals.md differs from blank template"
                if quarter_goals_set
                else "Quarter_Goals.md is missing or still blank"
            ),
        },
        "week_priorities": {
            "set": week_priorities_set,
            "evidence": (
                "Week_Priorities.md contains priorities"
                if week_priorities_set
                else "Week_Priorities.md has no priorities"
            ),
        },
    }


def _collect_skills(
    vault: Path,
    skills_list: Path | None,
    usage: Any,
    analytics: Any,
) -> dict[str, Any]:
    available = _load_skills_list(skills_list)
    detected: set[str] = set()
    ratings = _collect_ratings(vault)
    if isinstance(usage, dict):
        for feature, used in _mapping(usage.get("features")).items():
            if not used:
                continue
            detected.update(command.lower() for command in SKILL_COMMAND.findall(str(feature)))
    if isinstance(analytics, dict):
        detected.update(
            _normalize_skill_reference(name)
            for name in analytics.get("skill_names_used", [])
            if isinstance(name, str)
        )
    detected.update(_normalize_skill_reference(name) for name in ratings)
    if available:
        used = sorted(set(available).intersection(detected))
    else:
        used = sorted(detected)
    return {
        "available": available,
        "used": used,
        "unused": sorted(set(available) - set(used)),
        "ratings": ratings,
    }


def _collect_vault_age(vault: Path, now: datetime) -> dict[str, Any]:
    candidates: list[date] = []
    meetings_root = _at(vault, MEETINGS_DIR)
    for path in _markdown_files(meetings_root):
        dated = _date_from_path(path.relative_to(meetings_root))
        if dated is not None:
            candidates.append(dated)
    projects_root = _at(vault, PROJECTS_DIR)
    if projects_root.is_dir():
        for path in projects_root.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(projects_root)
            if any(part.startswith(".") for part in relative.parts):
                continue
            candidates.append(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date())
    if not candidates:
        return {"status": "unknown"}
    started = min(candidates)
    return {
        "status": "known",
        "started_on": started.isoformat(),
        "age_days": max(0, (now.date() - started).days),
    }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def collect_dashboard(
    vault: Path | str,
    *,
    skills_list: Path | str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Collect every dashboard section independently so one messy file cannot abort it."""
    vault_path = Path(vault).expanduser().resolve()
    generated = (now or _utc_now()).astimezone(timezone.utc)
    skills_path = Path(skills_list).expanduser().resolve() if skills_list is not None else None
    integrations = _safe(lambda: _collect_integrations(vault_path))
    usage = _safe(lambda: _collect_usage(vault_path))
    analytics = _safe(lambda: _collect_analytics(vault_path, generated))
    return {
        "meta": {
            "generated_at": generated.isoformat().replace("+00:00", "Z"),
            "vault_path": str(vault_path),
            "collector_version": COLLECTOR_VERSION,
            "vault_age": _safe(lambda: _collect_vault_age(vault_path, generated)),
        },
        "profile": _safe(lambda: _collect_profile(vault_path)),
        "pillars": _safe(lambda: _collect_pillars(vault_path)),
        "integrations": integrations,
        "connections": _safe(lambda: _collect_connections(vault_path, integrations)),
        "rituals": _safe(lambda: _collect_rituals(vault_path, usage, analytics)),
        "usage": usage,
        "analytics": analytics,
        "tasks": _safe(lambda: _collect_tasks(vault_path, generated)),
        "people": _safe(lambda: _collect_people(vault_path)),
        "companies": _safe(lambda: _collect_companies(vault_path)),
        "meetings": _safe(lambda: _collect_meetings(vault_path, generated)),
        "projects": _safe(lambda: _collect_projects(vault_path)),
        "health": _safe(lambda: _collect_health(vault_path, generated)),
        "skills": _safe(lambda: _collect_skills(vault_path, skills_path, usage, analytics)),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, required=True, help="Dex vault root")
    parser.add_argument("--skills-list", type=Path, help="JSON list of vault skill names")
    parser.add_argument("--json", action="store_true", help="Emit compact JSON")
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="Also report section-level collection errors to stderr",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    vault = args.vault.expanduser()
    if not vault.is_dir():
        print(f"Error: vault is not a directory: {vault}", file=sys.stderr)
        return 2
    try:
        data = collect_dashboard(vault, skills_list=args.skills_list)
    except Exception as error:
        print(f"Error: dashboard collection failed: {_short_error(error)}", file=sys.stderr)
        return 1
    print(json.dumps(data, sort_keys=True, ensure_ascii=False, indent=None if args.json else 2))
    if args.diagnose:
        errors = sorted(
            key
            for key, value in data.items()
            if isinstance(value, dict) and isinstance(value.get("error"), str)
        )
        print(json.dumps({"sections_with_errors": errors}, sort_keys=True), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
