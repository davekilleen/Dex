"""Title cleanup and source-path extraction for Todoist-bound tasks."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from core.integrations import task_sync
from core.mcp import work_server


def test_extract_file_refs_keeps_para_prefix_and_drops_truncated_duplicate():
    line = (
        "- [ ] Draft executive intro email | "
        "05-Areas/People/Internal/X.md ^task-20260918-001"
    )

    refs = work_server.extract_file_refs_from_task(line)

    assert refs == ["05-Areas/People/Internal/X.md"]
    assert "People/Internal/X.md" not in refs


def test_extract_file_refs_still_accepts_legacy_people_and_active_paths():
    line = (
        "- [ ] Follow up | People/External/John_Doe.md "
        "Active/Relationships/Acme.md"
    )

    refs = work_server.extract_file_refs_from_task(line)

    assert "People/External/John_Doe.md" in refs
    assert "Active/Relationships/Acme.md" in refs


def test_extract_file_refs_normalizes_windows_separators_without_duplicates():
    line = r"- [ ] Prep | 05-Areas\People\Internal\Ada.md"

    refs = work_server.extract_file_refs_from_task(line)

    assert refs == ["05-Areas/People/Internal/Ada.md"]


def test_parse_tasks_file_strips_para_paths_into_source_paths(tmp_path: Path):
    tasks_file = tmp_path / "Tasks.md"
    tasks_file.write_text(
        "# Tasks\n\n## Next Week\n"
        "- [ ] **Draft executive intro email** | "
        "05-Areas/People/Internal/X.md "
        "00-Inbox/Meetings/2026-09-18-kickoff.md ^task-20260918-001\n",
        encoding="utf-8",
    )

    [task] = work_server.parse_tasks_file(tasks_file)

    assert task["title"] == "Draft executive intro email"
    assert "05-Areas" not in task["title"]
    assert task["source_paths"] == [
        "05-Areas/People/Internal/X.md",
        "00-Inbox/Meetings/2026-09-18-kickoff.md",
    ]
    assert "05-Areas/People/Internal/X.md" in task["raw_title"]


def test_parse_tasks_file_leaves_a_pipe_in_the_title_when_it_is_not_a_path(
    tmp_path: Path,
):
    tasks_file = tmp_path / "Tasks.md"
    tasks_file.write_text(
        "# Tasks\n\n## Later\n"
        "- [ ] Review Q1 | decide go/no-go ^task-20260918-002\n",
        encoding="utf-8",
    )

    [task] = work_server.parse_tasks_file(tasks_file)

    assert task["title"] == "Review Q1 | decide go/no-go"
    assert task["source_paths"] == []


def test_obsidian_uri_encodes_vault_and_file_and_omits_unknown_vault():
    with_vault = task_sync.build_obsidian_open_uri(
        "05-Areas/People/Internal/X.md", "My Vault"
    )
    without_vault = task_sync.build_obsidian_open_uri(
        "05-Areas/People/Internal/X.md", None
    )

    parsed = urlparse(with_vault)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "obsidian"
    assert parsed.netloc == "open"
    assert query["vault"] == ["My Vault"]
    assert query["file"] == ["05-Areas/People/Internal/X.md"]
    assert "%20" in with_vault
    assert "%2F" in with_vault
    assert "vault=" not in without_vault
    assert without_vault.startswith("obsidian://open?file=")
    assert unquote(urlparse(without_vault).query.split("=", 1)[1]) == (
        "05-Areas/People/Internal/X.md"
    )


def test_obsidian_uri_rejects_traversal_schemes_and_absolute_paths():
    assert task_sync.build_obsidian_open_uri("../etc/passwd", "Vault") is None
    assert task_sync.build_obsidian_open_uri("foo/../../secret.md", "Vault") is None
    assert task_sync.build_obsidian_open_uri("https://evil.example/note", "Vault") is None
    assert task_sync.build_obsidian_open_uri("/etc/passwd", "Vault") is None
    assert task_sync.build_obsidian_open_uri(r"C:\Windows\note.md", "Vault") is None
    assert task_sync.build_obsidian_open_uri("note.md\njavascript:alert(1)", "Vault") is None
    assert task_sync.build_obsidian_open_uri(
        "05-Areas/People/Internal/X.md", "vault/../evil"
    ) == ("obsidian://open?file=05-Areas%2FPeople%2FInternal%2FX.md")


def test_source_links_prefer_meeting_over_person_and_skip_unsafe_paths():
    links = task_sync.source_links_for_paths(
        [
            "05-Areas/People/Internal/X.md",
            "00-Inbox/Meetings/2026-09-18-kickoff.md",
            "../outside.md",
            "05-Areas/People/Internal/X.md",
        ],
        "Dex",
    )

    assert [link["path"] for link in links] == [
        "00-Inbox/Meetings/2026-09-18-kickoff.md",
        "05-Areas/People/Internal/X.md",
    ]
    assert links[0]["label"] == "2026-09-18-kickoff"
    assert links[0]["uri"].startswith("obsidian://open?vault=Dex&file=")
