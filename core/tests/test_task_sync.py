"""Regression coverage for the Python-owned external task-sync bridge."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from core.integrations import task_sync
from core.mcp import work_server
from core.paths import TASKS_DIR

TEST_PILLARS = {
    "pillar_1": {
        "name": "Product",
        "description": "Product delivery",
        "keywords": ["product", "launch"],
    },
    "pillar_2": {
        "name": "Customers",
        "description": "Customer work",
        "keywords": ["customer"],
    },
}


def _service_state(last_sync: str = "2026-07-12T08:00:00+00:00") -> dict:
    return {
        "last_sync": last_sync,
        "map": {},
        "completed_pushed": [],
        "seen_external_created": [],
    }


def _state(**services: dict) -> dict:
    return services


def _write_tasks(path: Path, *lines: str) -> None:
    path.write_text("# Tasks\n\n" + "\n".join(lines) + "\n", encoding="utf-8")


def _decode_tool_result(result) -> dict:
    return json.loads(result[0].text)


@pytest.fixture
def sync_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    integrations = tmp_path / "System" / "integrations"
    adapters = tmp_path / ".claude" / "hooks" / "adapters"
    tasks = tmp_path / TASKS_DIR.name / "Tasks.md"
    integrations.mkdir(parents=True)
    adapters.mkdir(parents=True)
    tasks.parent.mkdir(parents=True)
    _write_tasks(tasks)

    config = integrations / "config.yaml"
    state = integrations / ".sync-state.json"
    inbound = integrations / "inbound-tasks.json"

    monkeypatch.setattr(task_sync, "INTEGRATION_CONFIG_FILE", config)
    monkeypatch.setattr(task_sync, "TASK_SYNC_STATE_FILE", state)
    monkeypatch.setattr(task_sync, "INBOUND_TASKS_FILE", inbound)
    monkeypatch.setattr(task_sync, "ADAPTERS_DIR", adapters)
    monkeypatch.setattr(work_server, "BASE_DIR", tmp_path)
    monkeypatch.setattr(work_server, "get_tasks_file", lambda: tasks)
    monkeypatch.setattr(work_server, "PILLARS", TEST_PILLARS)

    return {
        "root": tmp_path,
        "integrations": integrations,
        "adapters": adapters,
        "config": config,
        "state": state,
        "inbound": inbound,
        "tasks": tasks,
    }


def _enable(sync_vault: dict[str, Path], *services: str) -> None:
    blocks = []
    for service in services:
        blocks.extend(
            [
                f"{service}:",
                "  enabled: true",
                "  api_key: test-token",
                "  pillar_map:",
                "    pillar_1: Product",
            ]
        )
        (sync_vault["adapters"] / f"{service}.cjs").write_text(
            "module.exports = {};\n", encoding="utf-8"
        )
    sync_vault["config"].write_text("\n".join(blocks) + "\n", encoding="utf-8")


def _install_fake_runner(monkeypatch: pytest.MonkeyPatch, responses: dict) -> list[dict]:
    calls = []
    monkeypatch.setattr(task_sync, "_find_node", lambda: "/fake/node")

    def run(command, **kwargs):
        service, operation = command[-2:]
        request = json.loads(kwargs["input"])
        calls.append(
            {
                "command": command,
                "service": service,
                "operation": operation,
                "request": request,
            }
        )
        key = (service, operation)
        if key not in responses:
            raise AssertionError(f"unexpected adapter call: {service} {operation}")
        result = responses[key]
        return task_sync.subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps({"ok": True, "result": result}),
            stderr="",
        )

    monkeypatch.setattr(task_sync.subprocess, "run", run)
    return calls


def test_first_service_run_creates_baseline_without_adapter_calls(sync_vault, monkeypatch):
    _enable(sync_vault, "todoist")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("first run must not call an adapter")

    monkeypatch.setattr(task_sync, "_run_adapter", fail_if_called)

    result = task_sync.sync_external_tasks()

    assert result["todoist"]["first_run"] is True
    assert result["todoist"]["pushed_creates"] == 0
    state = json.loads(sync_vault["state"].read_text(encoding="utf-8"))
    assert set(state) == {"todoist"}
    assert state["todoist"]["last_sync"]
    assert state["todoist"]["map"] == {}
    assert not sync_vault["inbound"].exists()


def test_push_create_records_opaque_mapping(sync_vault, monkeypatch):
    _enable(sync_vault, "todoist")
    _write_tasks(
        sync_vault["tasks"],
        "- [ ] Launch product notes ^task-20260712-001",
        "\t- Pillar: Product | Priority: P1",
    )
    task_sync._write_state(_state(todoist=_service_state()))
    calls = []

    def run_adapter(service, operation, config, args):
        calls.append((service, operation, config, args))
        if operation == "create":
            return "opaque:todoist:9007199254740999"
        if operation == "get_changes":
            return []
        raise AssertionError(operation)

    monkeypatch.setattr(task_sync, "_run_adapter", run_adapter)

    result = task_sync.sync_external_tasks()

    assert result["todoist"]["pushed_creates"] == 1
    assert calls[0][1] == "create"
    assert calls[0][3]["task_id"] == "task-20260712-001"
    state = task_sync._load_state()
    assert state["todoist"]["map"] == {
        "task-20260712-001": "opaque:todoist:9007199254740999"
    }


def test_push_skips_tasks_older_than_service_baseline(sync_vault, monkeypatch):
    _enable(sync_vault, "todoist")
    _write_tasks(sync_vault["tasks"], "- [ ] Old product note ^task-20260711-001")
    task_sync._write_state(_state(todoist=_service_state()))
    operations = []

    def run_adapter(_service, operation, _config, _args):
        operations.append(operation)
        return []

    monkeypatch.setattr(task_sync, "_run_adapter", run_adapter)

    result = task_sync.sync_external_tasks()

    assert result["todoist"]["pushed_creates"] == 0
    assert "create" not in operations
    assert task_sync._load_state()["todoist"]["map"] == {}


def test_push_complete_happens_once_across_reruns(sync_vault, monkeypatch):
    _enable(sync_vault, "todoist")
    task_id = "task-20260712-002"
    _write_tasks(sync_vault["tasks"], f"- [x] Finished product note ^{task_id}")
    service_state = _service_state()
    service_state["map"][task_id] = "external-complete-id"
    task_sync._write_state(_state(todoist=service_state))
    operations = []

    def run_adapter(_service, operation, _config, _args):
        operations.append(operation)
        return [] if operation == "get_changes" else None

    monkeypatch.setattr(task_sync, "_run_adapter", run_adapter)

    first = task_sync.sync_external_tasks()
    second = task_sync.sync_external_tasks()

    assert first["todoist"]["pushed_completes"] == 1
    assert second["todoist"]["pushed_completes"] == 0
    assert operations.count("complete") == 1
    assert task_id in task_sync._load_state()["todoist"]["completed_pushed"]


def test_pull_complete_updates_real_canonical_task(sync_vault, monkeypatch):
    _enable(sync_vault, "todoist")
    task_id = "task-20260712-003"
    _write_tasks(sync_vault["tasks"], f"- [ ] Finish customer proposal ^{task_id}")
    service_state = _service_state()
    service_state["map"][task_id] = "opaque-completed-id"
    task_sync._write_state(_state(todoist=service_state))

    def run_adapter(_service, operation, _config, _args):
        assert operation == "get_changes"
        return [{"id": "opaque-completed-id", "action": "completed", "task": {}}]

    monkeypatch.setattr(task_sync, "_run_adapter", run_adapter)

    result = task_sync.sync_external_tasks()

    assert result["todoist"]["pulled_completes"] == 1
    assert "- [x] Finish customer proposal" in sync_vault["tasks"].read_text(encoding="utf-8")
    assert task_id in task_sync._load_state()["todoist"]["completed_pushed"]


def test_external_created_task_queues_once_with_python_pillar_inference(sync_vault, monkeypatch):
    _enable(sync_vault, "todoist")
    task_sync._write_state(_state(todoist=_service_state()))
    change = {
        "id": "external-created-id",
        "action": "created",
        "task": {
            "content": "Write launch follow-up",
            "project_name": "Product",
            "priority": 3,
        },
    }
    monkeypatch.setattr(
        task_sync,
        "_run_adapter",
        lambda _service, operation, _config, _args: [change]
        if operation == "get_changes"
        else None,
    )

    first = task_sync.sync_external_tasks()
    second = task_sync.sync_external_tasks()

    assert first["todoist"]["inbound_queued"] == 1
    assert second["todoist"]["inbound_queued"] == 0
    assert json.loads(sync_vault["inbound"].read_text(encoding="utf-8")) == [
        {
            "service": "todoist",
            "external_id": "external-created-id",
            "title": "Write launch follow-up",
            "raw": {
                "content": "Write launch follow-up",
                "project_name": "Product",
                "priority": 3,
                "pillar": "pillar_1",
            },
        }
    ]


def test_dry_run_reports_actions_without_any_local_or_external_writes(sync_vault, monkeypatch):
    _enable(sync_vault, "todoist")
    open_id = "task-20260712-004"
    done_id = "task-20260712-005"
    pull_id = "task-20260712-008"
    _write_tasks(
        sync_vault["tasks"],
        f"- [ ] New launch task ^{open_id}",
        f"- [x] Existing customer task ^{done_id}",
        f"- [ ] Existing mapped task ^{pull_id}",
    )
    service_state = _service_state()
    service_state["map"][done_id] = "mapped-done"
    service_state["map"][pull_id] = "mapped-pull"
    task_sync._write_state(_state(todoist=service_state))
    sync_vault["inbound"].write_text("[]\n", encoding="utf-8")
    before = {path: path.read_bytes() for path in (sync_vault["tasks"], sync_vault["state"], sync_vault["inbound"])}

    def run_adapter(_service, operation, _config, _args):
        if operation in {"create", "complete"}:
            raise AssertionError("dry-run must not perform external writes")
        return [
            {"id": "mapped-pull", "action": "completed", "task": {}},
            {
                "id": "dry-created",
                "action": "created",
                "task": {"content": "Dry external task"},
            },
        ]

    monkeypatch.setattr(task_sync, "_run_adapter", run_adapter)

    result = task_sync.sync_external_tasks(dry_run=True)

    assert {
        key: result["todoist"][key]
        for key in (
            "pushed_creates",
            "pushed_completes",
            "pulled_completes",
            "inbound_queued",
        )
    } == {
        "pushed_creates": 1,
        "pushed_completes": 1,
        "pulled_completes": 1,
        "inbound_queued": 1,
    }
    assert {path: path.read_bytes() for path in before} == before


def test_one_service_error_does_not_block_another(sync_vault, monkeypatch):
    _enable(sync_vault, "bad", "good")
    _write_tasks(sync_vault["tasks"], "- [ ] Launch isolated sync ^task-20260712-006")
    task_sync._write_state(
        _state(bad=_service_state(), good=_service_state())
    )

    def run_adapter(service, operation, _config, _args):
        if service == "bad":
            raise RuntimeError("adapter exploded")
        if operation == "create":
            return "good-external-id"
        return []

    monkeypatch.setattr(task_sync, "_run_adapter", run_adapter)

    result = task_sync.sync_external_tasks()

    assert result["bad"]["errors"] == ["adapter exploded"]
    assert result["bad"]["pushed_creates"] == 0
    assert result["good"]["pushed_creates"] == 1
    assert task_sync._load_state()["good"]["map"] == {
        "task-20260712-006": "good-external-id"
    }


class TestThingsSync:
    def test_push_create_via_runner_records_mapping(self, sync_vault, monkeypatch):
        _enable(sync_vault, "things")
        _write_tasks(
            sync_vault["tasks"],
            "- [ ] Launch Things product notes ^task-20260713-101",
            "\t- Pillar: Product | Priority: P1",
        )
        task_sync._write_state(_state(things=_service_state()))
        monkeypatch.setattr(task_sync.platform, "system", lambda: "Darwin")
        calls = _install_fake_runner(
            monkeypatch,
            {
                ("things", "create"): "things-opaque-id",
                ("things", "get_changes"): [],
            },
        )

        result = task_sync.sync_external_tasks(services=["things"])

        assert result["things"]["pushed_creates"] == 1
        assert task_sync._load_state()["things"]["map"] == {
            "task-20260713-101": "things-opaque-id"
        }
        assert [(call["service"], call["operation"]) for call in calls] == [
            ("things", "create"),
            ("things", "get_changes"),
        ]
        assert calls[0]["request"]["config"]["enabled"] is True
        assert calls[0]["request"]["args"]["task_id"] == "task-20260713-101"
        assert calls[1]["request"]["args"] == "2026-07-12T08:00:00+00:00"

    def test_non_darwin_guard_never_calls_runner(self, sync_vault, monkeypatch):
        _enable(sync_vault, "things")
        task_sync._write_state(_state(things=_service_state()))
        before = sync_vault["state"].read_bytes()

        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("Things runner must not be called off macOS")

        monkeypatch.setattr(task_sync.platform, "system", lambda: "Linux")
        monkeypatch.setattr(task_sync, "_find_node", fail_if_called)
        monkeypatch.setattr(task_sync.subprocess, "run", fail_if_called)

        result = task_sync.sync_external_tasks(services=["things"])

        assert result["things"]["pushed_creates"] == 0
        assert result["things"]["pulled_completes"] == 0
        assert result["things"]["errors"] == [
            "things task sync is only available on macOS"
        ]
        assert sync_vault["state"].read_bytes() == before

    def test_completed_change_via_runner_updates_linked_dex_task(
        self, sync_vault, monkeypatch
    ):
        _enable(sync_vault, "things")
        task_id = "task-20260713-102"
        _write_tasks(sync_vault["tasks"], f"- [ ] Finish Things follow-up ^{task_id}")
        service_state = _service_state()
        service_state["map"][task_id] = "things-completed-id"
        task_sync._write_state(_state(things=service_state))
        monkeypatch.setattr(task_sync.platform, "system", lambda: "Darwin")
        calls = _install_fake_runner(
            monkeypatch,
            {
                ("things", "get_changes"): [
                    {
                        "id": "things-completed-id",
                        "action": "completed",
                        "task": {"title": "Finish Things follow-up"},
                    }
                ]
            },
        )

        result = task_sync.sync_external_tasks(services=["things"])

        assert result["things"]["pulled_completes"] == 1
        assert "- [x] Finish Things follow-up" in sync_vault["tasks"].read_text(
            encoding="utf-8"
        )
        assert task_id in task_sync._load_state()["things"]["completed_pushed"]
        assert [call["operation"] for call in calls] == ["get_changes"]

    def test_created_change_via_runner_queues_once_across_reruns(
        self, sync_vault, monkeypatch
    ):
        _enable(sync_vault, "things")
        task_sync._write_state(_state(things=_service_state()))
        monkeypatch.setattr(task_sync.platform, "system", lambda: "Darwin")
        calls = _install_fake_runner(
            monkeypatch,
            {
                ("things", "get_changes"): [
                    {
                        "id": "things-created-id",
                        "action": "created",
                        "task": {
                            "title": "Prepare product demo",
                            "notes": "Captured in Things Inbox",
                        },
                    }
                ]
            },
        )

        first = task_sync.sync_external_tasks(services=["things"])
        second = task_sync.sync_external_tasks(services=["things"])

        assert first["things"]["inbound_queued"] == 1
        assert second["things"]["inbound_queued"] == 0
        assert json.loads(sync_vault["inbound"].read_text(encoding="utf-8")) == [
            {
                "service": "things",
                "external_id": "things-created-id",
                "title": "Prepare product demo",
                "raw": {
                    "title": "Prepare product demo",
                    "notes": "Captured in Things Inbox",
                    "pillar": "pillar_1",
                },
            }
        ]
        assert [call["operation"] for call in calls] == [
            "get_changes",
            "get_changes",
        ]


class TestTrelloSync:
    def test_push_create_via_runner_records_mapping(self, sync_vault, monkeypatch):
        _enable(sync_vault, "trello")
        _write_tasks(
            sync_vault["tasks"],
            "- [ ] Launch Trello product card ^task-20260713-201",
            "\t- Pillar: Product | Priority: P1",
        )
        task_sync._write_state(_state(trello=_service_state()))
        calls = _install_fake_runner(
            monkeypatch,
            {
                ("trello", "create"): "trello-opaque-id",
                ("trello", "get_changes"): [],
            },
        )

        result = task_sync.sync_external_tasks(services=["trello"])

        assert result["trello"]["pushed_creates"] == 1
        assert task_sync._load_state()["trello"]["map"] == {
            "task-20260713-201": "trello-opaque-id"
        }
        assert [(call["service"], call["operation"]) for call in calls] == [
            ("trello", "create"),
            ("trello", "get_changes"),
        ]
        assert calls[0]["request"]["config"]["api_key"] == "test-token"
        assert calls[0]["request"]["args"]["task_id"] == "task-20260713-201"

    def test_created_change_via_runner_queues_inbound(self, sync_vault, monkeypatch):
        _enable(sync_vault, "trello")
        task_sync._write_state(_state(trello=_service_state()))
        calls = _install_fake_runner(
            monkeypatch,
            {
                ("trello", "get_changes"): [
                    {
                        "id": "trello-created-id",
                        "action": "created",
                        "task": {
                            "name": "Review product launch board",
                            "listName": "Backlog",
                            "labels": [],
                        },
                    }
                ]
            },
        )

        result = task_sync.sync_external_tasks(services=["trello"])

        assert result["trello"]["inbound_queued"] == 1
        assert json.loads(sync_vault["inbound"].read_text(encoding="utf-8")) == [
            {
                "service": "trello",
                "external_id": "trello-created-id",
                "title": "Review product launch board",
                "raw": {
                    "name": "Review product launch board",
                    "listName": "Backlog",
                    "labels": [],
                    "pillar": "pillar_1",
                },
            }
        ]
        assert [call["operation"] for call in calls] == ["get_changes"]

    def test_completed_change_via_runner_updates_linked_dex_task(
        self, sync_vault, monkeypatch
    ):
        _enable(sync_vault, "trello")
        task_id = "task-20260713-202"
        _write_tasks(sync_vault["tasks"], f"- [ ] Finish Trello follow-up ^{task_id}")
        service_state = _service_state()
        service_state["map"][task_id] = "trello-completed-id"
        task_sync._write_state(_state(trello=service_state))
        calls = _install_fake_runner(
            monkeypatch,
            {
                ("trello", "get_changes"): [
                    {
                        "id": "trello-completed-id",
                        "action": "completed",
                        "task": {"name": "Finish Trello follow-up"},
                    }
                ]
            },
        )

        result = task_sync.sync_external_tasks(services=["trello"])

        assert result["trello"]["pulled_completes"] == 1
        assert "- [x] Finish Trello follow-up" in sync_vault["tasks"].read_text(
            encoding="utf-8"
        )
        assert task_id in task_sync._load_state()["trello"]["completed_pushed"]
        assert [call["operation"] for call in calls] == ["get_changes"]

    def test_push_complete_via_runner_uses_mapped_id_once(
        self, sync_vault, monkeypatch
    ):
        _enable(sync_vault, "trello")
        task_id = "task-20260713-203"
        _write_tasks(sync_vault["tasks"], f"- [x] Archive Trello card ^{task_id}")
        service_state = _service_state()
        service_state["map"][task_id] = "trello-mapped-complete-id"
        task_sync._write_state(_state(trello=service_state))
        calls = _install_fake_runner(
            monkeypatch,
            {
                ("trello", "complete"): None,
                ("trello", "get_changes"): [],
            },
        )

        first = task_sync.sync_external_tasks(services=["trello"])
        second = task_sync.sync_external_tasks(services=["trello"])

        assert first["trello"]["pushed_completes"] == 1
        assert second["trello"]["pushed_completes"] == 0
        complete_calls = [call for call in calls if call["operation"] == "complete"]
        assert len(complete_calls) == 1
        assert complete_calls[0]["request"]["args"] == "trello-mapped-complete-id"
        assert task_id in task_sync._load_state()["trello"]["completed_pushed"]


def test_record_mapping_validates_task_updates_state_and_removes_queue_item(sync_vault):
    task_id = "task-20260712-007"
    _write_tasks(sync_vault["tasks"], f"- [ ] Adopt inbound task ^{task_id}")
    task_sync._write_state(_state(todoist=_service_state()))
    sync_vault["inbound"].write_text(
        json.dumps(
            [
                {"service": "todoist", "external_id": "adopt-me", "title": "Adopt", "raw": {}},
                {"service": "todoist", "external_id": "keep-me", "title": "Keep", "raw": {}},
            ]
        ),
        encoding="utf-8",
    )

    result = task_sync.record_external_task_mapping(task_id, "todoist", "adopt-me")

    assert result["success"] is True
    assert task_sync._load_state()["todoist"]["map"][task_id] == "adopt-me"
    assert [item["external_id"] for item in json.loads(sync_vault["inbound"].read_text())] == ["keep-me"]


def test_record_mapping_rejects_missing_canonical_task_without_writes(sync_vault):
    task_sync._write_state(_state(todoist=_service_state()))
    before = sync_vault["state"].read_bytes()

    result = task_sync.record_external_task_mapping(
        "task-20260712-999", "todoist", "missing"
    )

    assert result["success"] is False
    assert "canonical" in result["error"].lower()
    assert sync_vault["state"].read_bytes() == before


def test_atomic_state_round_trip_leaves_no_temporary_files(sync_vault):
    payload = _state(todoist=_service_state())

    task_sync._write_state(payload)

    assert task_sync._load_state() == payload
    assert not list(sync_vault["integrations"].glob("*.tmp"))


def test_work_mcp_exposes_task_sync_tool_schemas():
    tools = asyncio.run(work_server.handle_list_tools())
    by_name = {tool.name: tool for tool in tools}

    sync_schema = by_name["sync_external_tasks"].inputSchema
    assert sync_schema["properties"]["services"] == {
        "type": "array",
        "items": {"type": "string"},
    }
    assert sync_schema["properties"]["dry_run"]["type"] == "boolean"
    assert sync_schema.get("required", []) == []

    mapping_schema = by_name["record_external_task_mapping"].inputSchema
    assert mapping_schema["required"] == ["task_id", "service", "external_id"]


def test_work_mcp_delegates_task_sync_handlers(monkeypatch):
    observed = []
    refreshes = []

    def sync_external_tasks(services=None, dry_run=False):
        observed.append(("sync", services, dry_run))
        return {"todoist": {"first_run": False}}

    def record_external_task_mapping(task_id, service, external_id):
        observed.append(("record", task_id, service, external_id))
        return {"success": True}

    monkeypatch.setattr(task_sync, "sync_external_tasks", sync_external_tasks)
    monkeypatch.setattr(
        task_sync, "record_external_task_mapping", record_external_task_mapping
    )
    monkeypatch.setattr(work_server, "refresh_search_index", lambda: refreshes.append(True))

    sync_result = _decode_tool_result(
        asyncio.run(
            work_server.handle_call_tool(
                "sync_external_tasks", {"services": ["todoist"], "dry_run": True}
            )
        )
    )
    mapping_result = _decode_tool_result(
        asyncio.run(
            work_server.handle_call_tool(
                "record_external_task_mapping",
                {
                    "task_id": "task-20260712-007",
                    "service": "todoist",
                    "external_id": "opaque",
                },
            )
        )
    )

    assert sync_result == {"todoist": {"first_run": False}}
    assert mapping_result == {"success": True}
    assert observed == [
        ("sync", ["todoist"], True),
        ("record", "task-20260712-007", "todoist", "opaque"),
    ]
    assert refreshes == []
