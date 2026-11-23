"""Related Tasks list on project pages.

Project pages show a short list of tasks that are explicitly linked to that
project. Open work comes first. A few recently done tasks sit underneath.
The list points at the real task in 03-Tasks/Tasks.md — it never copies the
task or its checkbox. Ticking stays in the main task list.

Matching is explicit only: a ``Project:`` metadata field (path or project
name), or a vault path / wikilink to the project file. A shared word in
the title is not a link.

New installs ship with the list on. Existing vaults are asked once before
any project page is changed. Empty lists are never written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime
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
CLEANUP_STAMP_RELATIVE = "System/.dex/project-related-tasks-cleanup.json"
BACKUP_ROOT_RELATIVE = "System/.dex/backups"
BACKUP_PREFIX = "related-tasks-cleanup-"
TASKS_RELATIVE = f"{TASKS_DIR.name}/{TASKS_FILE.name}"
PROJECTS_DIRNAME = PROJECTS_DIR.name
OPEN_FIRST_LINE = f"*Open first. Tick these in {TASKS_RELATIVE}.*"
PLACEHOLDER_LINE = (
    "*No linked tasks yet. Link a task to this project from the "
    "main task list.*"
)
PLACEHOLDER_SECTION_LINES = (
    f"## {SECTION_HEADING}",
    OPEN_FIRST_LINE,
    PLACEHOLDER_LINE,
)
OPT_IN_ASK = (
    "Project pages can show a Related tasks list near the top — open work "
    "first, a few recently done underneath. Only tasks you linked to that "
    "project appear, and you still tick them in the main task list. Turn it on?"
)
_COMPLETED_RE = re.compile(r"✅\s*(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?")
_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_SECTION_HEADING_RE = re.compile(r"^##[ \t]+Related Tasks[ \t]*\r?$")
_GLUED_HEADING_RE = re.compile(r"^(?P<body>.*\S)##[ \t]+(?P<heading>\S.*)$")
_NAME_SEPARATORS_RE = re.compile(r"[ \-_]+")
_TASK_LINK_LINE_RE = re.compile(
    rf"^- \[[^\]]+\]\({re.escape(TASKS_RELATIVE)}#\^[^\s)]+\)\s*$"
)
_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
_PROFILE_BLOCK_RE = re.compile(
    r"(?m)^project_related_tasks:\r?\n(?:[ \t]+.+\r?\n)*"
)
_DEPTH1_SKIP_NAMES = frozenset({"readme.md", "index.md"})


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


def _name_key(value: str) -> str:
    """Folder and file names compare case-insensitively; space, _ and - are equal."""
    return _NAME_SEPARATORS_RE.sub("-", (value or "").casefold()).strip("-")


def _normalize_rel_path(page_path: str) -> str:
    text = (page_path or "").replace("\\", "/").strip()
    text = text.lstrip("./")
    while text.startswith("/"):
        text = text[1:]
    if text and not Path(text).suffix:
        return f"{text}.md"
    return text


def is_under_projects_dir(page_path: str) -> bool:
    """True when the vault-relative path sits under the projects folder.

    Used to wrap call sites that must not fall through to the generic
    Related Tasks writer for files under the projects folder.
    """
    normalised = _normalize_rel_path(page_path).casefold()
    prefix = f"{PROJECTS_DIRNAME.casefold()}/"
    return normalised.startswith(prefix)


def _frontmatter(content: str) -> dict[str, Any]:
    if not content.startswith("---"):
        return {}
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    end = None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end = index
            break
    if end is None:
        return {}
    try:
        loaded = yaml.safe_load("\n".join(lines[1:end]))
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _folder_main_filename(folder: Path) -> str | None:
    """Return the main project page filename inside ``folder``, if any."""
    if folder.is_symlink() or not folder.is_dir():
        return None
    folder_key = _name_key(folder.name)
    named: list[str] = []
    readme: str | None = None
    index: str | None = None
    try:
        for entry in folder.iterdir():
            if entry.is_symlink() or not entry.is_file():
                continue
            if entry.suffix.casefold() != ".md":
                continue
            if _name_key(entry.stem) == folder_key:
                named.append(entry.name)
            elif entry.name.casefold() == "readme.md":
                readme = entry.name
            elif entry.name.casefold() == "index.md":
                index = entry.name
    except OSError:
        return None
    if named:
        return named[0]
    return readme or index


def _load_tasks(vault_root: Path) -> list[dict[str, Any]]:
    from core.mcp.work_server import parse_tasks_file

    tasks_file = Path(vault_root) / TASKS_RELATIVE
    if not tasks_file.is_file():
        return []
    return parse_tasks_file(tasks_file)


def is_project_page(
    vault_root: Path | str,
    rel_path: str,
    *,
    tasks: list[dict[str, Any]] | None = None,
) -> bool:
    """True when ``rel_path`` is a project page under the projects folder.

    A vault-relative ``.md`` file under the projects folder is a project page
    when any one of these holds:

    1. It sits directly in the projects folder, is not README.md or index.md,
       and does not start with ``_`` or ``.``.
    2. It is ``<Folder>/<Folder>.md`` (names compare case-insensitively, with
       space, underscore and hyphen treated as equal). If that file is
       missing, ``<Folder>/README.md`` or ``index.md`` is the main page.
    3. Its frontmatter has ``type: project``.
    4. A task in the main task list explicitly links to it.
    """
    relative = _normalize_rel_path(rel_path)
    if not relative.casefold().endswith(".md"):
        return False
    if not is_under_projects_dir(relative):
        return False
    parts = relative.split("/")
    rest = parts[1:]
    vault = Path(vault_root)

    if len(rest) == 1:
        name = rest[0]
        if name.casefold() not in _DEPTH1_SKIP_NAMES and not name.startswith(("_", ".")):
            return True

    if len(rest) == 2:
        folder_name, filename = rest
        if _name_key(Path(filename).stem) == _name_key(folder_name):
            return True
        main = _folder_main_filename(vault / PROJECTS_DIRNAME / folder_name)
        if main is not None and filename.casefold() == main.casefold():
            if filename.casefold() in _DEPTH1_SKIP_NAMES:
                return True

    page = _project_page_path(vault, relative)
    if page is not None:
        try:
            meta = _frontmatter(text_io.read_text(page))
        except (OSError, UnicodeError):
            meta = {}
        if str(meta.get("type") or "").strip().casefold() == "project":
            return True

    linked_tasks = _load_tasks(vault) if tasks is None else tasks
    return any(_task_explicitly_linked(task, relative) for task in linked_tasks)


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
    else:
        result["removed"] = remove_sections_on_disable(Path(vault_root))
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
    return [
        task
        for task in _load_tasks(vault_root)
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


def _split_visible_tasks(
    tasks: Iterable[dict[str, Any]], lines: list[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
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
    return open_tasks, done_tasks[:RECENTLY_DONE_LIMIT]


def render_section(tasks: Iterable[dict[str, Any]], lines: list[str]) -> str:
    """Render the machine-owned Related Tasks section. No checkboxes.

    Returns an empty string when there is nothing to show. Empty placeholder
    sections are never written.
    """
    open_tasks, recent = _split_visible_tasks(tasks, lines)
    if not open_tasks and not recent:
        return ""

    parts = [
        f"## {SECTION_HEADING}",
        "",
        OPEN_FIRST_LINE,
        "",
    ]
    if open_tasks:
        parts.extend(f"- {_task_link(task)}" for task in open_tasks)
        parts.append("")
    if recent:
        parts.extend(["### Recently done", ""])
        parts.extend(f"- {_task_link(task)}" for task in recent)
        parts.append("")
    return "\n".join(parts)


def _is_related_tasks_last_line(body: str) -> bool:
    stripped = body.rstrip()
    if stripped == PLACEHOLDER_LINE:
        return True
    return bool(_TASK_LINK_LINE_RE.match(stripped))


def repair_glued_related_task_headings(content: str) -> str:
    """Split a Related Tasks last line that was glued onto the next heading.

    Only the placeholder last line or a task link to the main task list is
    split, and only while inside a Related Tasks section.
    """
    repaired: list[str] = []
    changed = False
    in_section = False
    for line in content.split("\n"):
        match = _GLUED_HEADING_RE.match(line)
        if (
            in_section
            and match
            and not line.lstrip().startswith("##")
            and _is_related_tasks_last_line(match.group("body"))
        ):
            repaired.append(match.group("body").rstrip())
            repaired.append("")
            repaired.append(f"## {match.group('heading').strip()}")
            changed = True
            in_section = False
            continue
        repaired.append(line)
        if _is_related_tasks_heading(line):
            in_section = True
        elif in_section and _is_foreign_heading(line):
            in_section = False
    return "\n".join(repaired) if changed else content


def repair_glued_headings_in_vault(vault_root: Path) -> dict[str, Any]:
    """Restore headings glued onto the previous line on project pages.

    This is the one-off safety repair for pages already damaged. It puts the
    heading back on its own line. It cannot invent body text that a later
    refresh already deleted. Only project pages are touched, and only a glued
    last line of a Related Tasks section is split.
    """
    repaired: list[str] = []
    for relative in iter_project_pages(vault_root):
        page = Path(vault_root) / relative
        try:
            original = text_io.read_text(page)
        except (OSError, UnicodeError):
            continue
        updated = repair_glued_related_task_headings(original)
        if updated == original:
            continue
        text_io.write_text(page, updated)
        repaired.append(relative)
    return {"repaired": repaired, "count": len(repaired)}


def _is_related_tasks_heading(line: str) -> bool:
    return bool(_SECTION_HEADING_RE.match(line))


def _is_foreign_heading(line: str) -> bool:
    """True for a markdown heading this feature does not own."""
    if _is_related_tasks_heading(line):
        return False
    if line.startswith("### "):
        return False
    return line.startswith("## ")


def _machine_section_span(lines: list[str]) -> tuple[int, int] | None:
    """Return ``[start, end)`` of the Related Tasks block, stopping at the next heading it does not own."""
    start = None
    for index, line in enumerate(lines):
        if _is_related_tasks_heading(line):
            start = index
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if _is_foreign_heading(lines[index]):
            end = index
            break
    return start, end


def _significant_section_lines(lines: list[str], start: int, end: int) -> list[str]:
    return [line.rstrip() for line in lines[start:end] if line.strip()]


def _is_placeholder_only_span(lines: list[str], start: int, end: int) -> bool:
    return _significant_section_lines(lines, start, end) == list(PLACEHOLDER_SECTION_LINES)


def _has_placeholder_only_section(content: str) -> bool:
    lines = content.split("\n")
    span = _machine_section_span(lines)
    if span is None:
        return False
    return _is_placeholder_only_span(lines, *span)


def _join_section(prefix: str, section: str, suffix: str) -> str:
    head = prefix.rstrip("\n")
    body = section.strip("\n")
    tail = suffix.lstrip("\n")
    if not head:
        return f"{body}\n\n{tail}" if tail else f"{body}\n"
    if tail:
        return f"{head}\n\n{body}\n\n{tail}"
    return f"{head}\n\n{body}\n"


def _join_without_section(prefix: str, suffix: str) -> str:
    head = prefix.rstrip("\n")
    tail = suffix.lstrip("\n")
    if not head:
        return f"{tail}\n" if tail and not tail.endswith("\n") else tail
    if tail:
        return f"{head}\n\n{tail}"
    return f"{head}\n"


def _insert_near_top(content: str, section: str) -> str:
    if not section.strip():
        return _remove_machine_section(content)
    content = repair_glued_related_task_headings(content)
    lines = content.split("\n")
    span = _machine_section_span(lines)
    if span is not None:
        start, end = span
        prefix = "\n".join(lines[:start])
        suffix = "\n".join(lines[end:])
        return _join_section(prefix, section, suffix)

    insert_at = len(lines)
    for index, line in enumerate(lines):
        if _is_foreign_heading(line):
            insert_at = index
            break
    prefix = "\n".join(lines[:insert_at])
    suffix = "\n".join(lines[insert_at:])
    return _join_section(prefix, section, suffix)


def _remove_machine_section(content: str) -> str:
    content = repair_glued_related_task_headings(content)
    lines = content.split("\n")
    span = _machine_section_span(lines)
    if span is None:
        return content
    start, end = span
    prefix = "\n".join(lines[:start])
    suffix = "\n".join(lines[end:])
    return _join_without_section(prefix, suffix)


def _project_page_path(vault_root: Path, project_rel: str) -> Path | None:
    supplied = Path(_normalize_rel_path(project_rel))
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

    if not is_project_page(vault_root, project_rel):
        return {
            "success": True,
            "status": "skipped",
            "reason": "not_a_project_page",
            "page": project_rel,
        }

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
    original = text_io.read_text(page)
    open_tasks, recent = _split_visible_tasks(tasks, lines)
    if not open_tasks and not recent:
        updated = _remove_machine_section(original)
    else:
        updated = _insert_near_top(original, render_section(tasks, lines))
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


def _iter_markdown_under_projects(vault_root: Path) -> list[Path]:
    """Markdown files under the projects folder. Does not follow symlinks."""
    root = Path(vault_root)
    projects = root / PROJECTS_DIRNAME
    if not projects.exists():
        return []
    if projects.is_symlink():
        try:
            projects.resolve().relative_to(root.resolve())
        except ValueError:
            return []
    if not projects.is_dir():
        return []
    found: list[Path] = []

    def walk(directory: Path) -> None:
        try:
            children = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
        except OSError:
            return
        for child in children:
            try:
                if child.is_symlink():
                    continue
                if child.is_dir():
                    if child.name.startswith("."):
                        continue
                    walk(child)
                    continue
                if not child.is_file():
                    continue
                if child.name.startswith("."):
                    continue
                if child.suffix.casefold() != ".md":
                    continue
                found.append(child)
            except OSError:
                continue

    walk(projects)
    return found


def iter_project_pages(vault_root: Path) -> list[str]:
    """Vault-relative markdown files that are actual project pages."""
    vault = Path(vault_root)
    tasks = _load_tasks(vault)
    pages = []
    for path in _iter_markdown_under_projects(vault):
        relative = path.relative_to(vault).as_posix()
        if is_project_page(vault, relative, tasks=tasks):
            pages.append(relative)
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
        for task in _load_tasks(vault_root):
            if task.get("task_id") == task_id:
                target = task.get("project") or None
                if not target:
                    for ref in task.get("source_paths") or []:
                        if is_project_page(vault_root, str(ref)):
                            target = ref
                            break
                break
    if not target or not is_project_page(vault_root, str(target)):
        return {"success": True, "status": "skipped", "reason": "no_project"}
    return sync_project_page(vault_root, str(target))


def _now() -> datetime:
    from core.mcp import work_server

    try:
        current = work_server._tz_now()
        if getattr(current, "tzinfo", None) is not None:
            return current.replace(tzinfo=None)
        return current
    except Exception:
        return datetime.now()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _new_backup_dir(vault_root: Path) -> Path:
    stamp = _now().strftime("%Y%m%d-%H%M%S")
    base = Path(vault_root) / BACKUP_ROOT_RELATIVE
    path = base / f"{BACKUP_PREFIX}{stamp}"
    suffix = 1
    while path.exists():
        path = base / f"{BACKUP_PREFIX}{stamp}-{suffix}"
        suffix += 1
    path.mkdir(parents=True, exist_ok=True)
    return path


def _apply_rewrites_with_backup(
    vault_root: Path, rewrites: dict[str, tuple[bytes, str]]
) -> dict[str, Any]:
    """Write ``rewrites`` (rel → original bytes, new text) and back up originals."""
    if not rewrites:
        return {
            "changed": [],
            "count": 0,
            "backup_dir": None,
            "manifest": None,
        }
    vault = Path(vault_root)
    backup_dir = _new_backup_dir(vault)
    manifest_files: list[dict[str, str]] = []
    changed: list[str] = []
    for relative in sorted(rewrites):
        original_bytes, updated = rewrites[relative]
        backup_path = backup_dir / relative
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_bytes(original_bytes)
        target = vault / relative
        text_io.write_text(target, updated)
        after = target.read_bytes()
        manifest_files.append(
            {
                "path": relative,
                "sha256_before": _sha256_bytes(original_bytes),
                "sha256_after": _sha256_bytes(after),
            }
        )
        changed.append(relative)
    manifest_path = backup_dir / "manifest.json"
    text_io.write_text(
        manifest_path,
        json.dumps({"files": manifest_files}, indent=2) + "\n",
    )
    backup_rel = backup_dir.relative_to(vault).as_posix()
    return {
        "changed": changed,
        "count": len(changed),
        "backup_dir": backup_rel,
        "manifest": f"{backup_rel}/manifest.json",
    }


def cleanup_placeholder_sections(vault_root: Path) -> dict[str, Any]:
    """Remove placeholder-only Related Tasks blocks under the projects folder.

    Runs once per vault. Only an exact placeholder section is removed. Any
    other Related Tasks block is left untouched and reported. Originals are
    copied to a dated backup folder with a manifest.
    """
    vault = Path(vault_root)
    stamp_path = vault / CLEANUP_STAMP_RELATIVE
    if stamp_path.is_file():
        return {
            "success": True,
            "status": "already_done",
            "cleaned": [],
            "reported": [],
            "count": 0,
        }

    rewrites: dict[str, tuple[bytes, str]] = {}
    reported: list[str] = []
    for path in _iter_markdown_under_projects(vault):
        relative = path.relative_to(vault).as_posix()
        try:
            original_bytes = path.read_bytes()
            text = original_bytes.decode("utf-8-sig")
        except (OSError, UnicodeError):
            continue
        lines = text.split("\n")
        span = _machine_section_span(lines)
        if span is None:
            continue
        if not _is_placeholder_only_span(lines, *span):
            reported.append(relative)
            continue
        updated = _remove_machine_section(text)
        if updated == text:
            continue
        rewrites[relative] = (original_bytes, updated)

    applied = _apply_rewrites_with_backup(vault, rewrites)
    stamp_path.parent.mkdir(parents=True, exist_ok=True)
    text_io.write_text(
        stamp_path,
        json.dumps(
            {
                "completed_at": _now().strftime("%Y-%m-%dT%H:%M:%S"),
                "cleaned": applied["count"],
                "reported": reported,
                "backup_dir": applied["backup_dir"],
            },
            indent=2,
        )
        + "\n",
    )
    return {
        "success": True,
        "status": "cleaned",
        "cleaned": applied["changed"],
        "reported": reported,
        "count": applied["count"],
        "backup_dir": applied["backup_dir"],
        "manifest": applied["manifest"],
    }


def remove_sections_on_disable(vault_root: Path) -> dict[str, Any]:
    """Remove machine-owned sections after the feature is turned off.

    Project pages lose every Related Tasks section this feature owns.
    Placeholder-only sections anywhere under the projects folder are removed
    too. Originals are copied to the same dated backup layout.
    """
    vault = Path(vault_root)
    tasks = _load_tasks(vault)
    rewrites: dict[str, tuple[bytes, str]] = {}
    for path in _iter_markdown_under_projects(vault):
        relative = path.relative_to(vault).as_posix()
        try:
            original_bytes = path.read_bytes()
            text = original_bytes.decode("utf-8-sig")
        except (OSError, UnicodeError):
            continue
        if is_project_page(vault, relative, tasks=tasks):
            updated = _remove_machine_section(text)
        elif _has_placeholder_only_section(text):
            updated = _remove_machine_section(text)
        else:
            continue
        if updated == text:
            continue
        rewrites[relative] = (original_bytes, updated)
    applied = _apply_rewrites_with_backup(vault, rewrites)
    return {
        "success": True,
        "changed": applied["changed"],
        "count": applied["count"],
        "backup_dir": applied["backup_dir"],
        "manifest": applied["manifest"],
    }


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
    cleanup = cleanup_placeholder_sections(vault_root)
    glue = repair_glued_headings_in_vault(vault_root)
    state = load_preference(vault_root)
    if state != "on":
        return {
            "success": True,
            "status": state,
            "ran": bool(glue.get("count") or cleanup.get("count")),
            "glued_repaired": glue.get("count", 0),
            "glued_pages": glue.get("repaired", []),
            "cleanup": cleanup,
        }
    if not daily_refresh_due(vault_root):
        return {
            "success": True,
            "status": "on",
            "ran": False,
            "reason": "already_today",
            "glued_repaired": glue.get("count", 0),
            "cleanup": cleanup,
        }
    result = refresh_all_project_pages(vault_root)
    mark_daily_refresh(vault_root)
    result["ran"] = True
    result["glued_repaired"] = glue.get("count", 0)
    result["cleanup"] = cleanup
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
    parser.add_argument(
        "--repair-glued",
        action="store_true",
        help="Split headings glued onto the previous line on project pages",
    )
    args = parser.parse_args(argv)
    vault = Path(args.vault)
    if args.daily_refresh:
        print(json.dumps(maybe_daily_refresh(vault)))
        return 0
    if args.refresh_all:
        print(json.dumps(refresh_all_project_pages(vault)))
        return 0
    if args.repair_glued:
        print(json.dumps(repair_glued_headings_in_vault(vault)))
        return 0
    parser.error("pass --daily-refresh, --refresh-all, or --repair-glued")
    return 2


if __name__ == "__main__":
    sys.exit(main())
