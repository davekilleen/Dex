from __future__ import annotations

import logging
import sys
from types import ModuleType

from core import paths


def test_sync_file_tasks_logs_update_success_and_failure(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(paths, "OBSIDIAN_SYNC_LOG", tmp_path / "obsidian-sync.log")

    watchdog = ModuleType("watchdog")
    watchdog_events = ModuleType("watchdog.events")
    watchdog_observers = ModuleType("watchdog.observers")
    watchdog_events.FileSystemEventHandler = object
    watchdog_observers.Observer = object
    monkeypatch.setitem(sys.modules, "watchdog", watchdog)
    monkeypatch.setitem(sys.modules, "watchdog.events", watchdog_events)
    monkeypatch.setitem(sys.modules, "watchdog.observers", watchdog_observers)

    from core.mcp import work_server
    from core.obsidian.sync_daemon import DexSyncHandler

    task_id = "task-20260711-001"
    task_file = tmp_path / "tasks.md"
    task_file.write_text(f"- [x] Ship coverage fix ^{task_id}\n")
    handler = DexSyncHandler()

    monkeypatch.setattr(
        work_server,
        "update_task_status_everywhere",
        lambda _task_id, _completed: {"success": True, "task_id": task_id},
    )
    with caplog.at_level(logging.INFO, logger="core.obsidian.sync_daemon"):
        handler.sync_file_tasks(task_file)

    assert f"Synced {task_id} → d" in caplog.messages

    caplog.clear()
    monkeypatch.setattr(
        work_server,
        "update_task_status_everywhere",
        lambda _task_id, _completed: {
            "success": False,
            "error": "boom",
            "task_id": task_id,
        },
    )
    with caplog.at_level(logging.INFO, logger="core.obsidian.sync_daemon"):
        handler.sync_file_tasks(task_file)

    assert f"Failed to sync {task_id}: boom" in caplog.messages
