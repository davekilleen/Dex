"""Service-generic task-sync orchestration owned by Dex's Python core."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from core.mcp import work_server
from core.paths import (
    INBOUND_TASKS_FILE,
    INTEGRATION_CONFIG_FILE,
    TASK_SYNC_STATE_FILE,
    VAULT_ROOT,
)
from core.utils.integration_credentials import resolve_service_credentials
from core.utils.strict_yaml import load_yaml_path

ADAPTERS_DIR = VAULT_ROOT / ".claude" / "hooks" / "adapters"
_SERVICE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
_TASK_ID_PATTERN = re.compile(r"^task-(\d{8})-\d{3}$")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_service_state(last_sync: str | None = None) -> dict[str, Any]:
    return {
        "last_sync": last_sync or _now_iso(),
        "map": {},
        "completed_pushed": [],
        "seen_external_created": [],
    }


def _write_json_atomic(path: Path, payload: object) -> None:
    """Write JSON through a same-directory temporary file and atomic replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _load_json(path: Path, default: object) -> object:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _load_state() -> dict[str, Any]:
    payload = _load_json(TASK_SYNC_STATE_FILE, {})
    if not isinstance(payload, dict):
        raise ValueError("task sync state must contain an object")
    # Pre-bridge prototype seeds wrapped services in an `adapters` object. Read
    # that once, then the next atomic write emits the locked top-level shape.
    legacy_adapters = payload.get("adapters")
    if isinstance(legacy_adapters, dict):
        return legacy_adapters
    legacy_services = payload.get("services")
    if isinstance(legacy_services, dict):
        return legacy_services
    return payload


def _write_state(state: dict[str, Any]) -> None:
    _write_json_atomic(TASK_SYNC_STATE_FILE, state)


def _normalize_service_state(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return _new_service_state()
    value.setdefault("last_sync", _now_iso())
    if not isinstance(value.get("map"), dict):
        value["map"] = {}
    for key in ("completed_pushed", "seen_external_created"):
        if not isinstance(value.get(key), list):
            value[key] = []
    return value


def _load_inbound() -> list[dict[str, Any]]:
    payload = _load_json(INBOUND_TASKS_FILE, [])
    if not isinstance(payload, list):
        raise ValueError("inbound task queue must contain an array")
    return [item for item in payload if isinstance(item, dict)]


def _write_inbound(items: list[dict[str, Any]]) -> None:
    _write_json_atomic(INBOUND_TASKS_FILE, items)


def _load_config() -> dict[str, Any]:
    if not INTEGRATION_CONFIG_FILE.exists():
        return {}
    payload = load_yaml_path(INTEGRATION_CONFIG_FILE)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ValueError("integration config must contain an object")
    return payload


def _enabled_services(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    enabled: dict[str, dict[str, Any]] = {}
    legacy = config.get("enabled")
    if isinstance(legacy, dict):
        for name, value in legacy.items():
            if value is True:
                settings = config.get(name)
                enabled[str(name)] = settings if isinstance(settings, dict) else {}

    for name, settings in config.items():
        if name == "enabled" or not isinstance(settings, dict):
            continue
        if settings.get("enabled") is True:
            enabled[str(name)] = settings
        elif settings.get("enabled") is False:
            enabled.pop(str(name), None)
    return enabled


def _find_node() -> str:
    discovered = shutil.which("node")
    if discovered:
        return discovered
    candidates = (
        Path("/opt/homebrew/bin/node"),
        Path("/usr/local/bin/node"),
        Path("/usr/bin/node"),
        Path.home() / ".hermes" / "node" / "bin" / "node",
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise FileNotFoundError("node is required to run task-sync adapters")


def _resolve_adapter_service(service: str) -> str:
    if not _SERVICE_PATTERN.fullmatch(service):
        raise ValueError(f"invalid task-sync service name: {service}")
    runner = ADAPTERS_DIR / "run.cjs"
    try:
        result = subprocess.run(
            [_find_node(), str(runner), "--resolve-adapter", service],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            cwd=VAULT_ROOT,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError(f"adapter alias preflight failed: {error}") from error
    if len(result.stdout.encode("utf-8")) > 4096:
        raise ValueError("adapter alias preflight returned oversized output")
    try:
        payload = json.loads(result.stdout.strip())
    except json.JSONDecodeError as error:
        raise ValueError("adapter alias preflight returned invalid JSON") from error
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        detail = payload.get("error") if isinstance(payload, dict) else None
        raise ValueError(str(detail or "adapter alias preflight failed"))
    if set(payload) != {"ok", "requested_service", "adapter_service"}:
        raise ValueError("adapter alias preflight returned unexpected fields")
    adapter = payload.get("adapter_service")
    if payload.get("requested_service") != service or not isinstance(adapter, str):
        raise ValueError("adapter alias preflight returned a mismatched identity")
    if not _SERVICE_PATTERN.fullmatch(adapter):
        raise ValueError("adapter alias preflight returned an unsafe adapter identity")
    return adapter


def _adapter_path(adapter_service: str) -> Path | None:
    candidate = ADAPTERS_DIR / f"{adapter_service}.cjs"
    return candidate if candidate.is_file() else None


def _run_adapter(
    service: str,
    operation: str,
    config: dict[str, Any],
    args: object,
) -> object:
    """Invoke one adapter operation through the JSON-only Node runner."""
    runner = ADAPTERS_DIR / "run.cjs"
    result = subprocess.run(
        [_find_node(), str(runner), service, operation],
        input=json.dumps({"config": config, "args": args}),
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
        cwd=VAULT_ROOT,
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        },
    )
    try:
        payload = json.loads(result.stdout.strip())
    except (json.JSONDecodeError, TypeError) as error:
        raise RuntimeError("task-sync adapter runner returned invalid JSON") from error
    if not isinstance(payload, dict) or payload.get("ok") is not True:
        detail = payload.get("error") if isinstance(payload, dict) else None
        raise RuntimeError(str(detail or "task-sync adapter operation failed"))
    return payload.get("result")


def _runtime_settings(
    service: str, settings: dict[str, Any]
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Return ephemeral adapter settings and exact values that must be redacted."""
    credentials = resolve_service_credentials(service, settings, VAULT_ROOT)
    runtime = dict(settings)
    runtime.update(credentials)
    return runtime, tuple(credentials.values())


def _redact_error(error: Exception, secrets: tuple[str, ...]) -> str:
    message = str(error)
    for secret in secrets:
        message = message.replace(secret, "[REDACTED]")
    return message


def check_service_health(service: str) -> dict[str, object]:
    """Run one explicit read-only replacement health check."""
    settings = _enabled_services(_load_config()).get(service)
    if settings is None:
        return {"healthy": False, "error": "service is not enabled"}
    secrets: tuple[str, ...] = ()
    try:
        runtime_settings, secrets = _runtime_settings(service, settings)
        result = _run_adapter(service, "health", runtime_settings, None)
        if not isinstance(result, dict) or result.get("healthy") is not True:
            raise RuntimeError("adapter health response was not healthy")
        return {"healthy": True}
    except Exception as error:
        return {"healthy": False, "error": _redact_error(error, secrets)}


def _canonical_tasks() -> list[dict[str, Any]]:
    return work_server.parse_tasks_file(work_server.get_tasks_file())


def _task_id_date(task_id: object) -> date | None:
    match = _TASK_ID_PATTERN.fullmatch(str(task_id or ""))
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date()
    except ValueError:
        return None


def _sync_cursor_date(cursor: object) -> date:
    value = str(cursor or "")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError as error:
        raise ValueError(f"invalid task-sync cursor: {value}") from error


def _report() -> dict[str, Any]:
    return {
        "first_run": False,
        "pushed_creates": 0,
        "pushed_completes": 0,
        "pulled_completes": 0,
        "inbound_queued": 0,
        "errors": [],
    }


def _raw_title(raw: dict[str, Any]) -> str:
    for key in ("title", "content", "name"):
        value = raw.get(key)
        if value:
            return str(value)
    return "Untitled task"


def _infer_external_pillar(
    raw: dict[str, Any], title: str, config: dict[str, Any]
) -> str | None:
    location = next(
        (
            raw.get(key)
            for key in (
                "project_name",
                "_project_name",
                "list_name",
                "listName",
                "project",
                "list",
            )
            if raw.get(key)
        ),
        None,
    )
    pillar_map = config.get("pillar_map")
    if location is not None and isinstance(pillar_map, dict):
        location_key = str(location).casefold()
        for pillar, external_location in pillar_map.items():
            if str(external_location).casefold() == location_key:
                return str(pillar)
    return work_server.guess_pillar(title)


def sync_external_tasks(
    services: list[str] | None = None,
    dry_run: bool = False,
) -> dict[str, dict[str, object]]:
    """Synchronize enabled external task services without creating inbound Dex tasks."""
    config = _load_config()
    enabled = _enabled_services(config)
    requested = (
        list(dict.fromkeys(str(service) for service in services))
        if services is not None
        else list(enabled)
    )
    state = _load_state()
    inbound = _load_inbound()
    queued_ids = {
        (str(item.get("service")), str(item.get("external_id")))
        for item in inbound
    }
    results: dict[str, dict[str, object]] = {}

    for service in requested:
        report = _report()
        results[service] = report
        settings = enabled.get(service)
        if settings is None:
            report["errors"].append(f"service is not enabled: {service}")
            continue
        if service == "things" and platform.system() != "Darwin":
            report["errors"].append("things task sync is only available on macOS")
            continue
        try:
            adapter_service = _resolve_adapter_service(service)
            adapter_path = _adapter_path(adapter_service)
        except ValueError as error:
            report["errors"].append(
                f"task-sync adapter configuration error for enabled service '{service}': {error}"
            )
            continue
        if adapter_path is None:
            report["errors"].append(
                f"task-sync adapter unavailable for enabled service '{service}': "
                f"expected adapter '{adapter_service}.cjs'; repair Dex or disable this service"
            )
            continue

        if service not in state:
            report["first_run"] = True
            if not dry_run:
                state[service] = _new_service_state()
                _write_state(state)
            continue

        service_state = _normalize_service_state(state[service])
        state[service] = service_state
        previous_cursor = service_state["last_sync"]
        cycle_cursor = _now_iso()

        secrets: tuple[str, ...] = ()
        try:
            runtime_settings, secrets = _runtime_settings(service, settings)
            tasks = _canonical_tasks()
            baseline_date = _sync_cursor_date(previous_cursor)
            mapping = service_state["map"]
            completed_pushed = set(str(value) for value in service_state["completed_pushed"])

            for task in tasks:
                task_id = task.get("task_id")
                task_date = _task_id_date(task_id)
                if (
                    task.get("completed")
                    or task_id is None
                    or task_date is None
                    or task_date < baseline_date
                    or task_id in mapping
                ):
                    continue
                if dry_run:
                    report["pushed_creates"] += 1
                    continue
                external_id = _run_adapter(service, "create", runtime_settings, task)
                if external_id is None:
                    raise RuntimeError(f"{service} create returned no external ID")
                mapping[str(task_id)] = str(external_id)
                _write_state(state)
                report["pushed_creates"] += 1

            for task in tasks:
                task_id = task.get("task_id")
                if (
                    not task.get("completed")
                    or task_id not in mapping
                    or str(task_id) in completed_pushed
                ):
                    continue
                if dry_run:
                    report["pushed_completes"] += 1
                    continue
                _run_adapter(
                    service, "complete", runtime_settings, str(mapping[str(task_id)])
                )
                completed_pushed.add(str(task_id))
                service_state["completed_pushed"] = sorted(completed_pushed)
                _write_state(state)
                report["pushed_completes"] += 1

            changes = _run_adapter(
                service, "get_changes", runtime_settings, str(previous_cursor)
            )
            if changes is None:
                changes = []
            if not isinstance(changes, list):
                raise RuntimeError(f"{service} get_changes returned a non-array result")

            reverse_mapping = {
                str(external_id): str(task_id)
                for task_id, external_id in mapping.items()
            }
            canonical_by_id = {
                str(task["task_id"]): task
                for task in tasks
                if task.get("task_id")
            }
            seen = set(
                str(value) for value in service_state["seen_external_created"]
            )
            for change in changes:
                if not isinstance(change, dict):
                    continue
                external_id = str(change.get("id") or "")
                action = change.get("action")
                if not external_id:
                    continue

                if action == "completed":
                    task_id = reverse_mapping.get(external_id)
                    task = canonical_by_id.get(task_id or "")
                    if not task_id or not task or task.get("completed"):
                        continue
                    if dry_run:
                        report["pulled_completes"] += 1
                        continue
                    update = work_server.update_task_status_everywhere(
                        task_id, completed=True
                    )
                    if not update.get("success"):
                        raise RuntimeError(
                            str(update.get("error") or "Dex task completion failed")
                        )
                    completed_pushed.add(task_id)
                    service_state["completed_pushed"] = sorted(completed_pushed)
                    _write_state(state)
                    report["pulled_completes"] += 1
                    continue

                if action != "created" or external_id in reverse_mapping or external_id in seen:
                    continue
                raw_value = change.get("task")
                raw = dict(raw_value) if isinstance(raw_value, dict) else {}
                title = _raw_title(raw)
                pillar = _infer_external_pillar(raw, title, settings)
                if pillar is not None:
                    raw["pillar"] = pillar

                if (service, external_id) not in queued_ids:
                    if not dry_run:
                        inbound.append(
                            {
                                "service": service,
                                "external_id": external_id,
                                "title": title,
                                "raw": raw,
                            }
                        )
                        queued_ids.add((service, external_id))
                        _write_inbound(inbound)
                    report["inbound_queued"] += 1
                seen.add(external_id)
                if not dry_run:
                    service_state["seen_external_created"] = sorted(seen)
                    _write_state(state)

            if not dry_run:
                service_state["last_sync"] = cycle_cursor
                _write_state(state)
        except Exception as error:
            report["errors"].append(_redact_error(error, secrets))

    return results


def record_external_task_mapping(
    task_id: str,
    service: str,
    external_id: str,
) -> dict[str, object]:
    """Record an adopted inbound task's external mapping and dequeue it."""
    canonical = {
        str(task.get("task_id"))
        for task in _canonical_tasks()
        if task.get("task_id")
    }
    if task_id not in canonical:
        return {
            "success": False,
            "error": f"Canonical task not found: {task_id}",
        }
    if not _SERVICE_PATTERN.fullmatch(service):
        return {"success": False, "error": f"Invalid service name: {service}"}
    if not external_id:
        return {"success": False, "error": "external_id is required"}

    state = _load_state()
    service_state = _normalize_service_state(
        state.get(service, _new_service_state())
    )
    state[service] = service_state
    service_state["map"][task_id] = str(external_id)
    _write_state(state)

    inbound = _load_inbound()
    retained = [
        item
        for item in inbound
        if not (
            str(item.get("service")) == service
            and str(item.get("external_id")) == str(external_id)
        )
    ]
    removed = len(inbound) - len(retained)
    if removed:
        _write_inbound(retained)

    return {
        "success": True,
        "task_id": task_id,
        "service": service,
        "external_id": str(external_id),
        "removed_from_inbound": removed,
    }
