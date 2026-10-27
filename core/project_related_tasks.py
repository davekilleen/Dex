"""Related Tasks list on project pages.

Project pages show a short list of tasks that are explicitly linked to that
project. Open work comes first. A few recently done tasks sit underneath.
The list points at the real task in 03-Tasks/Tasks.md — it never copies the
task or its checkbox. Ticking stays in the main task list.

Matching is explicit only: a ``Project:`` metadata field (path or project
name), or a vault path / wikilink to the project file. A shared word in
the title is not a link.

New installs ship with the list on. Existing vaults are asked once before
any project page is changed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Literal

import yaml

from core.paths import PROJECTS_DIR, TASKS_DIR, TASKS_FILE
from core.utils import text_io

Preference = Literal["on", "off", "ask"]

SECTION_HEADING = "Related Tasks"
RECENTLY_DONE_LIMIT = 3
PROFILE_RELATIVE = "System/user-profile.yaml"
STAMP_RELATIVE = "System/.dex/project-related-tasks-refresh.json"
TASKS_RELATIVE = f"{TASKS_DIR.name}/{TASKS_FILE.name}"
PROJECTS_DIRNAME = PROJECTS_DIR.name
OPT_IN_ASK = (
    "Project pages can show a Related tasks list near the top — open work "
    "first, a few recently done underneath. Only tasks you linked to that "
    "project appear, and you still tick them in the main task list. Turn it on?"
)
_COMPLETED_RE = re.compile(r"✅\s*(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?")
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_SECTION_RE = re.compile(
    r"^##[ \t]+Related Tasks[ \t]*\r?\n.*?(?=^##[ \t]+|\Z)",
    re.MULTILINE | re.DOTALL,
)
_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
_PROFILE_BLOCK_RE = re.compile(
    r"(?m)^project_related_tasks:\r?\n(?:[ \t]+.+\r?\n)*"
)


def normalize_project_ref(value: str) -> str:
    """Compare project paths leniently: slashes, case, and trailing .md."""
    text = (value or "").strip().replace("\\", "/")
    text = text.strip("[]").split("|", 1)[0].strip()
    text = text.removeprefix("./")
    return text.rstrip("/").removesuffix(".md").casefold()


def _project_match_keys(value: str) -> set[str]:
    """Keys that count as the same explicit project link.

    A ``Project: Launch`` field or ``[[Launch]]`` wikilink is a real link,
    not a name coincidence. A title that merely mentions Launch is not.
    """
    normalised = normalize_project_ref(value)
    if not normalised:
        return set()
    name = normalised.rsplit("/", 1)[-1]
    keys = {normalised, name, name.replace("_", " "), name.replace(" ", "_")}
    return {key for key in keys if key}


def is_project_page(page_path: str) -> bool:
    """True when the vault-relative path sits under the projects folder."""
    normalised = (page_path or "").replace("\\", "/").lstrip("./")
    return normalised.casefold().startswith(f"{PROJECTS_DIRNAME.casefold()}/")


def preference_state(profile: Any) -> Preference:
    """Resolve the feature preference from a loaded user profile."""
    if not isinstance(profile, dict):
        return "ask"
    block = profile.get("project_related_tasks")
    if not isinstance(block, dict) or "enabled" not in block:
        return "ask"
    enabled = block.get("enabled")
    if enabled is True:
        return "on"
    if enabled is False:
        return "off"
    return "ask"


def load_preference(vault_root: Path) -> Preference:
    """Read the vault profile. A missing file is an existing-user ask."""
    path = Path(vault_root) / PROFILE_RELATIVE
    if not path.is_file():
        return "ask"
    try:
        loaded = yaml.safe_load(text_io.read_text(path))
    except (OSError, UnicodeError, yaml.YAMLError):
        return "ask"
    return preference_state(loaded)


def opt_in_payload() -> dict[str, Any]:
    """Return the one short ask used before the section is written."""
    return {"status": "needs_opt_in", "ask": OPT_IN_ASK}


def set_preference(vault_root: Path, enabled: bool) -> dict[str, Any]:
    """Write the preference without rewriting the rest of the profile."""
    path = Path(vault_root) / PROFILE_RELATIVE
    path.parent.mkdir(parents=True, exist_ok=True)
    original = text_io.read_text(path) if path.is_file() else ""
    rendered = _render_preference(original, enabled)
    text_io.write_text(path, rendered)
    state: Preference = "on" if enabled else "off"
    result: dict[str, Any] = {
        "success": True,
        "status": state,
        "enabled": enabled,
    }
    if enabled:
        result["refresh"] = refresh_all_project_pages(Path(vault_root))
    return result


def _render_preference(original: str, enabled: bool) -> str:
    flag = "true" if enabled else "false"
    block = f"project_related_tasks:\n  enabled: {flag}\n"
    if _PROFILE_BLOCK_RE.search(original):
        return _PROFILE_BLOCK_RE.sub(block, original, count=1)
    prefix = original
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    if prefix and not prefix.endswith("\n\n"):
        prefix += "\n"
    return f"{prefix}{block}"


def _task_explicitly_linked(task: dict[str, Any], project_rel: str) -> bool:
    wanted = _project_match_keys(project_rel)
    if not wanted:
        return False
    project_field = task.get("project")
    if project_field and (_project_match_keys(str(project_field)) & wanted):
        return True
    from core.mcp.work_server import extract_file_refs_from_task

    haystacks = [
        str(task.get("raw_title") or ""),
        str(task.get("title") or ""),
    ]
    refs = list(task.get("source_paths") or [])
    for haystack in haystacks:
        refs.extend(extract_file_refs_from_task(haystack))
        refs.extend(_WIKILINK_RE.findall(haystack))
    return any(_project_match_keys(ref) & wanted for ref in refs if ref)


def _completed_stamp(task: dict[str, Any], lines: list[str]) -> str:
    line_number = task.get("line_number")
    if isinstance(line_number, int) and 1 <= line_number <= len(lines):
        match = _COMPLETED_RE.search(lines[line_number - 1])
        if match:
            clock = match.group(2) or "00:00"
            return f"{match.group(1)} {clock}"
    task_id = str(task.get("task_id") or "")
    id_match = re.fullmatch(r"task-(\d{4})(\d{2})(\d{2})-\d{3,}", task_id)
    if id_match:
        return (
            f"{id_match.group(1)}-{id_match.group(2)}-{id_match.group(3)} 00:00"
        )
    return "0000-00-00 00:00"


def find_tasks_for_project(
    vault_root: Path, project_rel: str
) -> list[dict[str, Any]]:
    """Return tasks explicitly linked to ``project_rel``. No name matches."""
    from core.mcp.work_server import parse_tasks_file

    tasks_file = Path(vault_root) / TASKS_RELATIVE
    if not tasks_file.is_file():
        return []
    return [
        task
        for task in parse_tasks_file(tasks_file)
        if _task_explicitly_linked(task, project_rel)
    ]


def _link_label(title: str) -> str:
    cleaned = re.sub(r"[\[\]]", "", title or "").strip()
    return cleaned or "Untitled task"


def _task_link(task: dict[str, Any]) -> str:
    label = _link_label(str(task.get("title") or ""))
    task_id = task.get("task_id")
    if task_id:
        return f"[{label}]({TASKS_RELATIVE}#^{task_id})"
    return f"[{label}]({TASKS_RELATIVE})"


def render_section(tasks: Iterable[dict[str, Any]], lines: list[str]) -> str:
    """Render the machine-owned Related Tasks section. No checkboxes."""
    items = list(tasks)
    open_tasks = [task for task in items if not task.get("completed")]
    done_tasks = [task for task in items if task.get("completed")]
    open_tasks.sort(
        key=lambda task: (
            _PRIORITY_ORDER.get(str(task.get("priority") or "P2"), 2),
            int(task.get("next_up") or 10**9),
            str(task.get("title") or "").casefold(),
        )
    )
    done_tasks.sort(
        key=lambda task: _completed_stamp(task, lines),
        reverse=True,
    )
    recent = done_tasks[:RECENTLY_DONE_LIMIT]

    parts = [
        f"## {SECTION_HEADING}",
        "",
        f"*Open first. Tick these in {TASKS_RELATIVE}.*",
        "",
    ]
    if not open_tasks and not recent:
        parts.extend(
            [
                "*No linked tasks yet. Link a task to this project from the "
                "main task list.*",
                "",
            ]
        )
        return "\n".join(parts)

    if open_tasks:
        parts.extend(f"- {_task_link(task)}" for task in open_tasks)
        parts.append("")
    if recent:
        parts.extend(["### Recently done", ""])
        parts.extend(f"- {_task_link(task)}" for task in recent)
        parts.append("")
    return "\n".join(parts)


def _insert_near_top(content: str, section: str) -> str:
    if _SECTION_RE.search(content):
        return _SECTION_RE.sub(section.rstrip(), content, count=1)

    lines = content.split("\n")
    insert_at = len(lines)
    for index, line in enumerate(lines):
        if line.startswith("## ") and not line.startswith(f"## {SECTION_HEADING}"):
            insert_at = index
            break
    block = section if section.endswith("\n") else f"{section}\n"
    if insert_at == 0:
        return block + content
    prefix = "\n".join(lines[:insert_at]).rstrip("\n")
    suffix = "\n".join(lines[insert_at:]).lstrip("\n")
    glued = f"{prefix}\n\n{block}"
    return f"{glued}\n{suffix}" if suffix else glued


def _project_page_path(vault_root: Path, project_rel: str) -> Path | None:
    supplied = Path(project_rel)
    if supplied.is_absolute():
        return None
    base = Path(vault_root).resolve()
    candidates = [(base / supplied).resolve()]
    if not supplied.suffix:
        candidates.append(candidates[0].with_suffix(".md"))
    for candidate in candidates:
        try:
            candidate.relative_to(base)
        except ValueError:
            continue
        if candidate.is_file():
            return candidate
    return None


def sync_project_page(
    vault_root: Path,
    project_rel: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Rewrite one project page's Related Tasks section when allowed."""
    state = load_preference(vault_root)
    if state == "off":
        return {"success": True, "status": "off", "page": project_rel}
    if state == "ask" and not force:
        return {**opt_in_payload(), "success": True, "page": project_rel}

    page = _project_page_path(vault_root, project_rel)
    if page is None:
        return {
            "success": False,
            "status": state,
            "page": project_rel,
            "error": f"Project file does not exist: {project_rel}",
        }

    from core.mcp.work_server import parse_tasks_file

    tasks_file = Path(vault_root) / TASKS_RELATIVE
    lines = (
        text_io.read_text(tasks_file).split("\n") if tasks_file.is_file() else []
    )
    relative = page.relative_to(Path(vault_root).resolve()).as_posix()
    tasks = [
        task
        for task in (parse_tasks_file(tasks_file) if tasks_file.is_file() else [])
        if _task_explicitly_linked(task, relative)
    ]
    section = render_section(tasks, lines)
    original = text_io.read_text(page)
    updated = _insert_near_top(original, section)
    changed = updated != original
    if changed:
        text_io.write_text(page, updated)
    open_count = sum(1 for task in tasks if not task.get("completed"))
    done_count = sum(1 for task in tasks if task.get("completed"))
    return {
        "success": True,
        "status": "on",
        "page": relative,
        "changed": changed,
        "open_count": open_count,
        "done_count": min(done_count, RECENTLY_DONE_LIMIT),
        "linked_count": len(tasks),
    }


def iter_project_pages(vault_root: Path) -> list[str]:
    """Vault-relative markdown files under the projects folder."""
    projects = Path(vault_root) / PROJECTS_DIRNAME
    if not projects.is_dir():
        return []
    pages = []
    for path in sorted(projects.rglob("*.md")):
        if path.name.startswith("."):
            continue
        pages.append(path.relative_to(Path(vault_root)).as_posix())
    return pages


def refresh_all_project_pages(vault_root: Path) -> dict[str, Any]:
    """Refresh every project page. No-op when the feature is not on."""
    state = load_preference(vault_root)
    if state != "on":
        return {
            "success": True,
            "status": state,
            **(opt_in_payload() if state == "ask" else {}),
            "pages": [],
        }
    results = [
        sync_project_page(vault_root, page) for page in iter_project_pages(vault_root)
    ]
    return {
        "success": True,
        "status": "on",
        "pages": results,
        "refreshed": sum(1 for item in results if item.get("changed")),
        "count": len(results),
    }


def sync_after_task_change(
    vault_root: Path,
    *,
    project: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Refresh the project page linked to a created or completed task."""
    target = project
    if not target and task_id:
        from core.mcp.work_server import parse_tasks_file

        tasks_file = Path(vault_root) / TASKS_RELATIVE
        if tasks_file.is_file():
            for task in parse_tasks_file(tasks_file):
                if task.get("task_id") == task_id:
                    target = task.get("project") or None
                    if not target:
                        for ref in task.get("source_paths") or []:
                            if is_project_page(str(ref)):
                                target = ref
                                break
                    break
    if not target or not is_project_page(str(target)):
        return {"success": True, "status": "skipped", "reason": "no_project"}
    return sync_project_page(vault_root, str(target))


def _today(vault_root: Path) -> date:
    from core.mcp import work_server

    try:
        return work_server._tz_now().date()
    except Exception:
        return date.today()


def daily_refresh_due(vault_root: Path, today: date | None = None) -> bool:
    """True when today's catch-up pass has not run yet."""
    stamp_path = Path(vault_root) / STAMP_RELATIVE
    current = today or _today(vault_root)
    if not stamp_path.is_file():
        return True
    try:
        payload = json.loads(text_io.read_text(stamp_path))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return True
    return str(payload.get("last_date") or "") != current.isoformat()


def mark_daily_refresh(vault_root: Path, today: date | None = None) -> None:
    stamp_path = Path(vault_root) / STAMP_RELATIVE
    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    current = today or _today(vault_root)
    text_io.write_text(
        stamp_path,
        json.dumps({"last_date": current.isoformat()}, indent=2) + "\n",
    )


def maybe_daily_refresh(vault_root: Path) -> dict[str, Any]:
    """Once-a-day catch-up for hand edits. Silent when off or already done."""
    state = load_preference(vault_root)
    if state != "on":
        return {"success": True, "status": state, "ran": False}
    if not daily_refresh_due(vault_root):
        return {"success": True, "status": "on", "ran": False, "reason": "already_today"}
    result = refresh_all_project_pages(vault_root)
    mark_daily_refresh(vault_root)
    result["ran"] = True
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh project Related Tasks")
    parser.add_argument("--vault", required=True, help="Vault root")
    parser.add_argument(
        "--daily-refresh",
        action="store_true",
        help="Run the once-a-day catch-up if the feature is on",
    )
    parser.add_argument(
        "--refresh-all",
        action="store_true",
        help="Refresh every project page now (still respects opt-in)",
    )
    args = parser.parse_args(argv)
    vault = Path(args.vault)
    if args.daily_refresh:
        print(json.dumps(maybe_daily_refresh(vault)))
        return 0
    if args.refresh_all:
        print(json.dumps(refresh_all_project_pages(vault)))
        return 0
    parser.error("pass --daily-refresh or --refresh-all")
    return 2


if __name__ == "__main__":
    sys.exit(main())
