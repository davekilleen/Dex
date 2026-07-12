from __future__ import annotations

import importlib
import json
import logging
import sys
from types import ModuleType

import pytest

from core import paths


@pytest.fixture
def sync_daemon(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "OBSIDIAN_SYNC_LOG", tmp_path / "obsidian-sync.log")

    watchdog = ModuleType("watchdog")
    watchdog_events = ModuleType("watchdog.events")
    watchdog_observers = ModuleType("watchdog.observers")
    watchdog_events.FileSystemEventHandler = object
    watchdog_observers.Observer = object
    monkeypatch.setitem(sys.modules, "watchdog", watchdog)
    monkeypatch.setitem(sys.modules, "watchdog.events", watchdog_events)
    monkeypatch.setitem(sys.modules, "watchdog.observers", watchdog_observers)

    sys.modules.pop("core.obsidian.sync_daemon", None)
    return importlib.import_module("core.obsidian.sync_daemon")


def write_task(path, task_id, completed):
    checkbox = "x" if completed else " "
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"- [{checkbox}] Ship coverage fix ^{task_id}\n")


def test_unchanged_stale_note_never_overrides_canonical_state(
    tmp_path, monkeypatch, sync_daemon
):
    from core.mcp import work_server

    task_id = "task-20260711-001"
    canonical_file = tmp_path / "03-Tasks" / "Tasks.md"
    note_file = tmp_path / "meeting.md"
    write_task(canonical_file, task_id, completed=True)
    write_task(note_file, task_id, completed=False)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: canonical_file)

    updates = []
    monkeypatch.setattr(
        work_server,
        "update_task_status_everywhere",
        lambda changed_id, completed: updates.append((changed_id, completed))
        or {"success": True, "task_id": changed_id},
    )

    handler = sync_daemon.DexSyncHandler(tmp_path)
    handler.sync_file_tasks(note_file)
    handler.sync_file_tasks(note_file)

    assert updates == []


def test_first_changed_note_after_startup_propagates_when_it_differs_from_canonical(
    tmp_path, monkeypatch, sync_daemon
):
    from core.mcp import work_server

    task_id = "task-20260711-002"
    canonical_file = tmp_path / "03-Tasks" / "Tasks.md"
    note_file = tmp_path / "meeting.md"
    write_task(canonical_file, task_id, completed=False)
    write_task(note_file, task_id, completed=False)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: canonical_file)

    updates = []
    monkeypatch.setattr(
        work_server,
        "update_task_status_everywhere",
        lambda changed_id, completed: updates.append((changed_id, completed))
        or {"success": True, "task_id": changed_id},
    )

    handler = sync_daemon.DexSyncHandler(tmp_path)
    write_task(note_file, task_id, completed=True)
    handler.sync_file_tasks(note_file)
    handler.sync_file_tasks(note_file)  # An mtime-only event is ignored.

    assert updates == [(task_id, True)]


def test_changed_note_matching_canonical_does_not_push(
    tmp_path, monkeypatch, sync_daemon
):
    from core.mcp import work_server

    task_id = "task-20260711-003"
    canonical_file = tmp_path / "03-Tasks" / "Tasks.md"
    note_file = tmp_path / "meeting.md"
    write_task(canonical_file, task_id, completed=True)
    write_task(note_file, task_id, completed=False)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: canonical_file)

    updates = []
    monkeypatch.setattr(
        work_server,
        "update_task_status_everywhere",
        lambda changed_id, completed: updates.append((changed_id, completed))
        or {"success": True, "task_id": changed_id},
    )

    handler = sync_daemon.DexSyncHandler(tmp_path)
    write_task(note_file, task_id, completed=True)
    handler.sync_file_tasks(note_file)

    assert updates == []


def test_pending_batch_parses_the_canonical_task_list_once(
    tmp_path, monkeypatch, sync_daemon
):
    from core.mcp import work_server

    first_id = "task-20260711-007"
    second_id = "task-20260711-008"
    canonical_file = tmp_path / "03-Tasks" / "Tasks.md"
    first_note = tmp_path / "first.md"
    second_note = tmp_path / "second.md"
    canonical_file.parent.mkdir(parents=True, exist_ok=True)
    canonical_file.write_text(
        f"- [ ] First task ^{first_id}\n- [ ] Second task ^{second_id}\n"
    )
    write_task(first_note, first_id, completed=False)
    write_task(second_note, second_id, completed=False)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: canonical_file)

    parse_calls = []
    real_parse_tasks_file = work_server.parse_tasks_file

    def count_parse_calls(filepath):
        parse_calls.append(filepath)
        return real_parse_tasks_file(filepath)

    monkeypatch.setattr(work_server, "parse_tasks_file", count_parse_calls)
    updates = []
    monkeypatch.setattr(
        work_server,
        "update_task_status_everywhere",
        lambda task_id, completed: updates.append((task_id, completed))
        or {"success": True, "task_id": task_id},
    )

    handler = sync_daemon.DexSyncHandler(tmp_path)
    write_task(first_note, first_id, completed=True)
    write_task(second_note, second_id, completed=True)
    handler.pending_files.update({first_note, second_note})
    handler.process_pending_files()

    assert parse_calls == [canonical_file]
    assert sorted(updates) == sorted([(first_id, True), (second_id, True)])


def test_third_failure_is_queued_once_for_session_start(
    tmp_path, monkeypatch, sync_daemon, caplog
):
    from core.mcp import work_server

    task_id = "task-20260711-004"
    canonical_file = tmp_path / "03-Tasks" / "Tasks.md"
    note_file = tmp_path / "meeting.md"
    write_task(canonical_file, task_id, completed=False)
    write_task(note_file, task_id, completed=False)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: canonical_file)
    attempts = []
    monkeypatch.setattr(
        work_server,
        "update_task_status_everywhere",
        lambda changed_id, completed: attempts.append((changed_id, completed))
        or {
            "success": False,
            "error": "boom",
            "task_id": task_id,
        },
    )
    queued = []
    monkeypatch.setattr(
        sync_daemon,
        "log_error",
        lambda source, message, human_message=None, context=None: queued.append(
            (source, message, human_message, context)
        ),
    )

    handler = sync_daemon.DexSyncHandler(tmp_path)
    write_task(note_file, task_id, completed=True)
    with caplog.at_level(logging.INFO, logger="core.obsidian.sync_daemon"):
        for attempt in range(4):
            handler.sync_file_tasks(note_file)
            if attempt < 2:
                assert queued == []

    assert f"Failed to sync {task_id}: boom" in caplog.messages
    assert attempts == [(task_id, True)] * 4
    assert len(queued) == 1
    assert queued[0][0] == "obsidian-sync"
    assert queued[0][3] == {"task_id": task_id, "failures": 3}


def test_canonical_reconciliation_resets_the_failure_episode(
    tmp_path, monkeypatch, sync_daemon
):
    from core.mcp import work_server

    task_id = "task-20260711-006"
    canonical_file = tmp_path / "03-Tasks" / "Tasks.md"
    note_file = tmp_path / "meeting.md"
    write_task(canonical_file, task_id, completed=False)
    write_task(note_file, task_id, completed=False)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: canonical_file)
    monkeypatch.setattr(
        work_server,
        "update_task_status_everywhere",
        lambda _task_id, _completed: {
            "success": False,
            "error": "boom",
            "task_id": task_id,
        },
    )
    queued = []
    monkeypatch.setattr(
        sync_daemon,
        "log_error",
        lambda source, message, human_message=None, context=None: queued.append(
            (source, message, human_message, context)
        ),
    )

    handler = sync_daemon.DexSyncHandler(tmp_path)
    write_task(note_file, task_id, completed=True)
    handler.sync_file_tasks(note_file)
    handler.sync_file_tasks(note_file)
    assert handler.failure_counts[task_id] == 2

    write_task(canonical_file, task_id, completed=True)
    handler.sync_file_tasks(note_file)
    assert task_id not in handler.failure_counts

    write_task(note_file, task_id, completed=False)
    handler.sync_file_tasks(note_file)
    handler.sync_file_tasks(note_file)
    assert queued == []

    handler.sync_file_tasks(note_file)
    assert len(queued) == 1


def test_repeated_failure_uses_the_session_start_error_queue(
    tmp_path, monkeypatch, sync_daemon
):
    from core.utils import preflight

    monkeypatch.setenv("VAULT_PATH", str(tmp_path))
    task_id = "task-20260711-005"
    handler = sync_daemon.DexSyncHandler(tmp_path)

    for _ in range(4):
        handler._record_sync_failure(task_id, "boom")

    queue_path = preflight.get_error_queue_path()
    queue = json.loads(queue_path.read_text())
    assert len(queue) == 1
    assert queue[0]["source"] == "obsidian-sync"
    assert queue[0]["context"] == {"task_id": task_id, "failures": 3}
    assert task_id in preflight.format_errors()


def test_direct_edit_to_canonical_tasks_file_propagates(
    tmp_path, monkeypatch, sync_daemon
):
    """A checkbox toggled directly in Tasks.md must still sync to the mirror
    pages — the canonical-equality guard would otherwise skip it because the
    canonical snapshot is read from that same just-saved file."""
    from core.mcp import work_server

    task_id = "task-20260712-010"
    canonical_file = tmp_path / "03-Tasks" / "Tasks.md"
    write_task(canonical_file, task_id, completed=False)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: canonical_file)

    updates = []
    monkeypatch.setattr(
        work_server,
        "update_task_status_everywhere",
        lambda changed_id, completed: updates.append((changed_id, completed))
        or {"success": True, "task_id": changed_id},
    )

    handler = sync_daemon.DexSyncHandler(tmp_path)
    handler.sync_file_tasks(canonical_file)  # startup prime, no propagation
    assert updates == []

    write_task(canonical_file, task_id, completed=True)  # user checks the box in Tasks.md
    handler.sync_file_tasks(canonical_file)

    assert updates == [(task_id, True)]
    # The write-back this triggers is caught by the last-seen guard, not re-pushed.
    handler.sync_file_tasks(canonical_file)
    assert updates == [(task_id, True)]
