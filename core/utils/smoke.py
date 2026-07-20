#!/usr/bin/env python3
"""Safe, isolated end-to-end smoke journeys for a Dex vault."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

RUNNER_ROOT = Path(__file__).resolve().parents[2]
if str(RUNNER_ROOT) in sys.path:
    sys.path.remove(str(RUNNER_ROOT))
sys.path.insert(0, str(RUNNER_ROOT))

from core.utils import release_channel

SCHEMA_VERSION = 1
HISTORY_LIMIT = 120
DEFAULT_MCP_HANDSHAKE_TIMEOUT_SECONDS = 8.0


def _mcp_handshake_timeout_seconds() -> float:
    raw_value = os.environ.get("DEX_MCP_HANDSHAKE_TIMEOUT")
    try:
        value = float(raw_value) if raw_value is not None else DEFAULT_MCP_HANDSHAKE_TIMEOUT_SECONDS
    except (TypeError, ValueError):
        return DEFAULT_MCP_HANDSHAKE_TIMEOUT_SECONDS
    if not 0 < value < float("inf"):
        return DEFAULT_MCP_HANDSHAKE_TIMEOUT_SECONDS
    return value


HANDSHAKE_TIMEOUT_SECONDS = _mcp_handshake_timeout_seconds()
MCP_STARTUP_HANDSHAKE_BUDGET_SECONDS = 40.0
MCP_STARTUP_JOURNEY_TIMEOUT_SECONDS = 45.0
GLOBAL_TIMEOUT_SECONDS = 60.0
VERDICTS = frozenset({"OK", "OFF", "BROKEN", "UNKNOWN"})
VERDICT_PRIORITY = {"OFF": 0, "OK": 1, "UNKNOWN": 2, "BROKEN": 3}
NOT_SET_UP_DETAIL = "not set up yet — complete onboarding first"
MISSING_PACKAGES_DETAIL = (
    "Python packages not installed — run /dex-update (or pip install -r requirements.txt) "
    "then re-run /dex-doctor"
)
PYTHON_COMMAND = re.compile(r"^python(?:\d+(?:\.\d+)*)?$")
SCRIPT_SUFFIXES = {".js", ".cjs", ".mjs", ".sh", ".py"}
TASK_PLAN = ".dex-smoke-task-plan.json"
MCP_PLAN = ".dex-smoke-mcp-plan.json"
SENSITIVE_CONFIG_KEY = re.compile(
    r"(?:api[_-]?key|authorization|credential|password|secret|token)",
    re.IGNORECASE,
)
SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
SNAPSHOT_CHANGED_DETAIL = "snapshot changed before launch"
MCP_ONCE_CONSENT_DETAIL = "valid fresh single-use consent token is required"
MCP_ONCE_TOKEN_PREFIX = "dex-mcp-once-consent-"
MCP_ONCE_TOKEN_MAX_AGE_SECONDS = 120.0
TRUSTED_GIT_CANDIDATES = (Path("/usr/bin/git"), Path("/bin/git"))
RUNNER_FALLBACK_RELATIVES = (
    Path("core/__init__.py"),
    Path("core/paths.py"),
    Path("core/utils/__init__.py"),
    Path("core/utils/release_channel.py"),
    Path("core/utils/smoke.py"),
    Path("core/utils/trust_registry.py"),
    Path("core/utils/validators.py"),
)
CONTENT_VERIFIED_SENSITIVE_DEPENDENCIES = frozenset(
    {
        Path("core/utils/credential_migration_exceptions.json"),
        Path("core/utils/credential_remediation.py"),
        Path("core/utils/credential_scanner.py"),
        Path("core/utils/credential_workflow.py"),
        Path("core/utils/integration_credentials.py"),
    }
)
PARA_PATH_NAMES = (
    "INBOX_DIR",
    "QUARTER_GOALS_DIR",
    "WEEK_PRIORITIES_DIR",
    "TASKS_DIR",
    "PROJECTS_DIR",
    "AREAS_DIR",
    "RESOURCES_DIR",
    "ARCHIVES_DIR",
)


def _trusted_git() -> str | None:
    for candidate in TRUSTED_GIT_CANDIDATES:
        if not candidate.is_symlink() and candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _trusted_node() -> str | None:
    candidates = (
        Path("/usr/bin/node"),
        Path("/usr/local/bin/node"),
        Path("/opt/homebrew/bin/node"),
        Path.home() / ".hermes" / "node" / "bin" / "node",
    )
    for candidate in candidates:
        if not candidate.is_symlink() and candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _git_command(repo_root: Path, *arguments: str) -> list[str] | None:
    executable = _trusted_git()
    if executable is None:
        return None
    return [
        executable,
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.attributesFile=/dev/null",
        "-c",
        "core.excludesFile=/dev/null",
        "-c",
        "submodule.recurse=false",
        "-C",
        str(repo_root),
        *arguments,
    ]


def _git_environment() -> dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": "/var/empty" if Path("/var/empty").is_dir() else "/",
        "LC_ALL": "C",
        "PATH": SAFE_PATH,
    }


@dataclass(frozen=True)
class JourneyDefinition:
    """One isolated smoke journey and its hard timeout."""

    id: str
    timeout_seconds: float


@dataclass(frozen=True)
class SmokeRun:
    """A smoke report plus runner-only failure state used for exit code 2."""

    report: dict[str, Any]
    harness_failed: bool = False

    @property
    def exit_code(self) -> int:
        if self.harness_failed:
            return 2
        return 1 if self.report["summary"]["broken"] else 0


JOURNEYS = (
    JourneyDefinition("configs", 5.0),
    JourneyDefinition("task_lifecycle", 8.0),
    JourneyDefinition("mcp_startup", MCP_STARTUP_JOURNEY_TIMEOUT_SECONDS),
    JourneyDefinition("skills", 5.0),
    JourneyDefinition("hooks", 8.0),
)


class JourneyPreparationError(RuntimeError):
    """The vault could not supply the files required by a journey."""


class JourneyNotSetUp(RuntimeError):
    """The journey depends on onboarding-created state that is not present yet."""


class JourneySafetySkip(RuntimeError):
    """A source path was deliberately not read because it crossed a safety boundary."""


def _one_line(value: object) -> str:
    return " ".join(str(value).split()) or value.__class__.__name__


def _roll_up(verdicts: Sequence[str]) -> str:
    if not verdicts:
        return "OFF"
    return max(verdicts, key=VERDICT_PRIORITY.__getitem__)


def _core_path(root: Path, constant_name: str) -> Path:
    """Retarget one ``core.paths`` constant to an isolated vault root."""
    from core import paths as core_paths

    configured = getattr(core_paths, constant_name)
    return root / configured.relative_to(core_paths.VAULT_ROOT)


def _is_sensitive_path(path: Path) -> bool:
    return any(
        part.lower() == ".env"
        or part.lower().startswith(".env.")
        or "credential" in part.lower()
        for part in path.parts
    )


def _is_runner_runtime_path(path: str | Path) -> bool:
    relative = Path(path).as_posix()
    return not (
        relative.startswith("core/tests/")
        or relative.startswith("core/mcp/tests/")
        or relative.startswith("core/migrations/tests/")
    )


def _ensure_safe_source(path: Path, source_root: Path) -> None:
    try:
        relative = path.relative_to(source_root)
    except ValueError as exc:
        raise JourneySafetySkip(f"refused to read path outside the vault: {path}") from exc
    if _is_sensitive_path(relative) and relative not in CONTENT_VERIFIED_SENSITIVE_DEPENDENCIES:
        raise JourneySafetySkip(f"{relative} is sensitive and was only checked for existence")
    current = source_root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            raise JourneySafetySkip(f"{relative} is symlinked and was not read for safety")
    if path.exists() and not (path.is_file() or path.is_dir()):
        raise JourneySafetySkip(f"{relative} is not a regular file or directory and was not read for safety")


def _copy_file(source: Path, destination: Path, source_root: Path) -> None:
    _ensure_safe_source(source, source_root)
    if not source.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination, follow_symlinks=False)


def _write_analytics_opt_out(vault: Path) -> None:
    """Use Dex's documented consent setting so smoke can never send analytics."""
    usage_log = vault / "System" / "usage_log.md"
    usage_log.parent.mkdir(parents=True, exist_ok=True)
    usage_log.write_text(
        "# Dex smoke analytics state\n\n"
        "**Consent asked:** yes\n"
        "**Consent decision:** opted-out\n",
        encoding="utf-8",
    )


def _redact_config_secrets(value: object, *, key: str = "") -> object:
    if SENSITIVE_CONFIG_KEY.search(key):
        if isinstance(value, str):
            return ""
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return 0
        if isinstance(value, float):
            return 0.0
        if isinstance(value, Mapping):
            return {str(child_key): "" for child_key in value}
    if isinstance(value, Mapping):
        return {
            child_key: _redact_config_secrets(child, key=str(child_key))
            for child_key, child in value.items()
        }
    if isinstance(value, list):
        return [_redact_config_secrets(child, key=key) for child in value]
    return value


def _copy_yaml_projection(source: Path, destination: Path, source_root: Path) -> None:
    _ensure_safe_source(source, source_root)
    if not source.exists():
        return
    import yaml

    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        parsed = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        # Preserve the structural failure without retaining any source values.
        destination.write_text("null\n", encoding="utf-8")
        return
    destination.write_text(
        yaml.safe_dump(_redact_config_secrets(parsed), sort_keys=False),
        encoding="utf-8",
    )


def _require_onboarding(source: Path) -> None:
    marker = source / "System" / ".onboarding-complete"
    _ensure_safe_source(marker, source)
    if not marker.is_file():
        raise JourneyNotSetUp(NOT_SET_UP_DETAIL)


def _copy_configs(source: Path, vault: Path, *, integrations: bool = True) -> None:
    _require_onboarding(source)
    config_relatives = ("System/user-profile.yaml", "System/pillars.yaml")
    missing = [
        relative
        for relative in config_relatives
        if not (source / relative).exists() and not (source / relative).is_symlink()
    ]
    if missing:
        raise JourneyPreparationError(f"missing required configuration: {', '.join(missing)}")
    for relative in config_relatives:
        _copy_yaml_projection(source / relative, vault / relative, source)
    if not integrations:
        return
    integrations = source / "System" / "integrations"
    _ensure_safe_source(integrations, source)
    if integrations.is_dir():
        for config in sorted(integrations.glob("*.yaml")):
            _copy_yaml_projection(
                config,
                vault / "System" / "integrations" / config.name,
                source,
            )


def _validator_path() -> Path | None:
    runner_validator = RUNNER_ROOT / "core" / "utils" / "validators.py"
    if runner_validator.is_file() and not runner_validator.is_symlink():
        return runner_validator
    return None


def _prepare_task_vault(
    source: Path,
    repo_root: Path,
    vault: Path,
    release_root: Path | None,
    release_ref: str | None,
) -> None:
    _copy_configs(source, vault, integrations=False)
    tasks_dir = _core_path(source, "TASKS_DIR")
    tasks_file = _core_path(source, "TASKS_FILE")
    _ensure_safe_source(tasks_dir, source)
    if tasks_dir.is_dir():
        for path in tasks_dir.rglob("*"):
            _ensure_safe_source(path, source)
    missing = [path.relative_to(source).as_posix() for path in (tasks_dir, tasks_file) if not path.exists()]
    if missing:
        raise JourneyPreparationError(f"missing task storage: {', '.join(missing)}")
    for path in (tasks_dir, tasks_file):
        if not path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
            raise JourneyPreparationError(f"{path.relative_to(source)} is not writable")

    for constant_name in PARA_PATH_NAMES:
        if constant_name != "TASKS_DIR":
            _core_path(vault, constant_name).mkdir(parents=True, exist_ok=True)
    _core_path(vault, "SYSTEM_DIR").mkdir(parents=True, exist_ok=True)
    shutil.copytree(tasks_dir, _core_path(vault, "TASKS_DIR"))
    reason = _release_execution_reason(repo_root, release_root, release_ref)
    (vault / TASK_PLAN).write_text(
        json.dumps({"executable": reason is None, "reason": reason or "verified release snapshot"}),
        encoding="utf-8",
    )


def _prepare_mcp_vault(
    source: Path,
    repo_root: Path,
    vault: Path,
    release_root: Path | None,
    release_ref: str | None,
) -> None:
    _require_onboarding(source)
    config_candidates = (
        source / ".mcp.json",
        source / "System" / ".mcp.json",
    )
    config = next(
        (candidate for candidate in config_candidates if candidate.exists() or candidate.is_symlink()),
        None,
    )
    if config is None:
        raise JourneyPreparationError(".mcp.json is missing after onboarding completed")
    _ensure_safe_source(config, source)
    if not config.is_file():
        raise JourneyPreparationError(f"{config.relative_to(source)} is not a regular file")
    try:
        raw = config.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        plan = {"state": "BROKEN", "detail": f".mcp.json is invalid: {_one_line(exc)}", "entries": []}
    else:
        if not isinstance(parsed, Mapping) or not isinstance(parsed.get("mcpServers"), Mapping):
            plan = {
                "state": "BROKEN",
                "detail": ".mcp.json must contain an mcpServers object",
                "entries": [],
            }
        else:
            runtime_reason = _release_execution_reason(repo_root, release_root, release_ref)
            trust_registry = None
            trust_registry_path = source / "System" / "trusted-mcps.yaml"
            validator = None
            expected_validator = _validator_path()
            if expected_validator is not None and expected_validator.is_file():
                from core.utils import validators as validator_module

                if Path(validator_module.__file__).resolve() == expected_validator.resolve():
                    validator = validator_module.validate_mcp_config
            entries = []
            for raw_name, entry in parsed["mcpServers"].items():
                name = _one_line(raw_name)
                if validator is None:
                    entries.append(
                        {
                            "name": name,
                            "verdict": "UNKNOWN",
                            "detail": "not executed for safety; structural validation unavailable "
                            "without a coherent runner snapshot",
                        }
                    )
                    continue
                structural_errors = validator({"mcpServers": {raw_name: entry}})
                custom = isinstance(raw_name, str) and raw_name.startswith("custom-")
                remote = isinstance(entry, Mapping) and (
                    entry.get("type") in {"http", "sse", "streamable-http"} or "url" in entry
                )
                if structural_errors:
                    entries.append(
                        {
                            "name": name,
                            "verdict": "UNKNOWN",
                            "detail": "not executed for safety; structural issues: "
                            + ", ".join(_one_line(error) for error in structural_errors),
                        }
                    )
                    continue
                if custom:
                    if not (
                        trust_registry_path.exists() or trust_registry_path.is_symlink()
                    ):
                        entries.append(
                            {"name": name, "verdict": "UNKNOWN", "detail": "not executed for safety"}
                        )
                        continue
                    if trust_registry is None:
                        from core.utils.trust_registry import (
                            load_trusted_mcp_registry,
                            snapshot_trusted_mcp,
                        )

                        trust_registry = load_trusted_mcp_registry(source)
                    if trust_registry.invalid_reason is not None:
                        entries.append(
                            {
                                "name": name,
                                "verdict": "UNKNOWN",
                                "detail": "trusted MCP registry is invalid "
                                f"({trust_registry.invalid_reason})",
                            }
                        )
                        continue
                    if raw_name not in trust_registry.entries:
                        entries.append(
                            {"name": name, "verdict": "UNKNOWN", "detail": "not executed for safety"}
                        )
                        continue
                    decision = snapshot_trusted_mcp(
                        source,
                        raw_name,
                        entry,
                        trust_registry,
                        vault / ".dex-trusted-mcp-snapshots",
                    )
                    if not decision.trusted or decision.snapshot_path is None:
                        entries.append(
                            {
                                "name": name,
                                "verdict": "UNKNOWN",
                                "detail": decision.detail,
                            }
                        )
                        continue
                    entries.append(
                        {
                            "name": name,
                            "verdict": "EXECUTE",
                            "kind": "trusted-custom",
                            "script": decision.snapshot_path.relative_to(vault).as_posix(),
                        }
                    )
                    continue
                if remote or not isinstance(entry, Mapping):
                    entries.append(
                        {"name": name, "verdict": "UNKNOWN", "detail": "not executed for safety"}
                    )
                    continue
                if runtime_reason:
                    entries.append(
                        {
                            "name": name,
                            "verdict": "UNKNOWN",
                            "detail": f"not executed for safety ({runtime_reason})",
                        }
                    )
                    continue
                script, unsafe_reason = _safe_owned_server(
                    entry,
                    repo_root,
                    release_root,
                    release_ref,
                )
                if script is None:
                    entries.append(
                        {
                            "name": name,
                            "verdict": "UNKNOWN",
                            "detail": f"not executed for safety ({unsafe_reason})",
                        }
                    )
                    continue
                entries.append(
                    {
                        "name": name,
                        "verdict": "EXECUTE",
                        "script": script.relative_to(repo_root.resolve()).as_posix(),
                    }
                )
            plan = {"state": "READY", "entries": entries}
    plan_path = vault / MCP_PLAN
    plan_path.write_text(json.dumps(plan, separators=(",", ":")), encoding="utf-8")
    plan_path.chmod(0o600)


def _prepare_skills_vault(source: Path, vault: Path) -> None:
    skills_root = source / ".claude" / "skills"
    _ensure_safe_source(skills_root, source)
    if not skills_root.is_dir():
        return
    for skill_directory in sorted(skills_root.iterdir()):
        _ensure_safe_source(skill_directory, source)
        skill = skill_directory / "SKILL.md"
        if not skill.exists() and not skill.is_symlink():
            continue
        _copy_file(
            skill,
            vault / ".claude" / "skills" / skill.parent.name / "SKILL.md",
            source,
        )


def _prepare_hooks_vault(source: Path, vault: Path) -> None:
    _copy_file(
        source / ".claude" / "settings.json",
        vault / ".claude" / "settings.json",
        source,
    )
    hooks = source / ".claude" / "hooks"
    _ensure_safe_source(hooks, source)
    if hooks.is_dir():
        for path in hooks.rglob("*"):
            _ensure_safe_source(path, source)
        shutil.copytree(hooks, vault / ".claude" / "hooks", symlinks=True)


def _prepare_vault(
    journey_id: str,
    source: Path,
    repo_root: Path,
    vault: Path,
    release_root: Path | None,
    release_ref: str | None,
) -> None:
    vault.mkdir(parents=True)
    try:
        if journey_id == "configs":
            _copy_configs(source, vault)
        elif journey_id == "task_lifecycle":
            _prepare_task_vault(source, repo_root, vault, release_root, release_ref)
        elif journey_id == "mcp_startup":
            _prepare_mcp_vault(source, repo_root, vault, release_root, release_ref)
        elif journey_id == "skills":
            _prepare_skills_vault(source, vault)
        elif journey_id == "hooks":
            _prepare_hooks_vault(source, vault)
        else:
            raise RuntimeError(f"unknown smoke journey {journey_id!r}")
    except (JourneyPreparationError, JourneySafetySkip):
        raise
    except OSError as exc:
        raise JourneyPreparationError(
            f"could not prepare {journey_id}: {_one_line(exc)}"
        ) from exc
    _write_analytics_opt_out(vault)


def _install_network_guard(parent: Path) -> Path:
    """Install a Python startup guard that blocks IPv4/IPv6 connections."""
    guard = parent / "python-guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(
        "import socket\n"
        "_dex_original_connect = socket.socket.connect\n"
        "def _dex_no_network(self, address):\n"
        "    if self.family in (socket.AF_INET, socket.AF_INET6):\n"
        "        raise OSError('network disabled during Dex smoke tests')\n"
        "    return _dex_original_connect(self, address)\n"
        "socket.socket.connect = _dex_no_network\n"
        "socket.socket.connect_ex = _dex_no_network\n"
        "def _dex_no_sendto(self, *args, **kwargs):\n"
        "    if self.family in (socket.AF_INET, socket.AF_INET6):\n"
        "        raise OSError('network disabled during Dex smoke tests')\n"
        "    return _dex_original_sendto(self, *args, **kwargs)\n"
        "_dex_original_sendto = socket.socket.sendto\n"
        "socket.socket.sendto = _dex_no_sendto\n"
        "def _dex_no_create_connection(*args, **kwargs):\n"
        "    raise OSError('network disabled during Dex smoke tests')\n"
        "socket.create_connection = _dex_no_create_connection\n"
        "def _dex_no_dns(*args, **kwargs):\n"
        "    raise OSError('DNS disabled during Dex smoke tests')\n"
        "socket.getaddrinfo = _dex_no_dns\n"
        "socket.gethostbyname = _dex_no_dns\n"
        "socket.gethostbyname_ex = _dex_no_dns\n"
        "socket.gethostbyaddr = _dex_no_dns\n",
        encoding="utf-8",
    )
    (guard / "server_bootstrap.py").write_text(
        "from pathlib import Path\n"
        "import hashlib\n"
        "import os\n"
        "import re\n"
        "import runpy\n"
        "import stat\n"
        "import sys\n"
        "runpy.run_path(str(Path(__file__).with_name('sitecustomize.py')))\n"
        "if len(sys.argv) < 3 or sys.argv[1] != '--verified-snapshot':\n"
        "    script = sys.argv[1]\n"
        "    sys.argv = sys.argv[1:]\n"
        "    runpy.run_path(script, run_name='__main__')\n"
        "    raise SystemExit(0)\n"
        "def refuse_snapshot():\n"
        "    print('snapshot changed before launch', file=sys.stderr)\n"
        "    raise SystemExit(1)\n"
        "try:\n"
        "    script = Path(sys.argv[2])\n"
        "except IndexError:\n"
        "    refuse_snapshot()\n"
        "match = re.fullmatch(r'.+-([0-9a-f]{64})[.]py', script.name)\n"
        "no_follow = getattr(os, 'O_NOFOLLOW', None)\n"
        "directory_flag = getattr(os, 'O_DIRECTORY', None)\n"
        "if match is None or no_follow is None or directory_flag is None:\n"
        "    refuse_snapshot()\n"
        "close_on_exec = getattr(os, 'O_CLOEXEC', 0)\n"
        "directory_fd = None\n"
        "script_fd = None\n"
        "try:\n"
        "    directory_fd = os.open(script.parent, os.O_RDONLY | no_follow | directory_flag | close_on_exec)\n"
        "    parent_stat = os.fstat(directory_fd)\n"
        "    if parent_stat.st_uid != os.getuid() or parent_stat.st_mode & 0o022:\n"
        "        refuse_snapshot()\n"
        "    leaf_stat = os.stat(script.name, dir_fd=directory_fd, follow_symlinks=False)\n"
        "    if stat.S_ISLNK(leaf_stat.st_mode) or not stat.S_ISREG(leaf_stat.st_mode):\n"
        "        refuse_snapshot()\n"
        "    script_fd = os.open(script.name, os.O_RDONLY | no_follow | close_on_exec, dir_fd=directory_fd)\n"
        "    opened_stat = os.fstat(script_fd)\n"
        "    if ((opened_stat.st_dev, opened_stat.st_ino) != (leaf_stat.st_dev, leaf_stat.st_ino)\n"
        "            or opened_stat.st_uid != os.getuid() or opened_stat.st_mode & 0o022):\n"
        "        refuse_snapshot()\n"
        "    chunks = []\n"
        "    digest = hashlib.sha256()\n"
        "    while True:\n"
        "        chunk = os.read(script_fd, 1024 * 1024)\n"
        "        if not chunk:\n"
        "            break\n"
        "        chunks.append(chunk)\n"
        "        digest.update(chunk)\n"
        "    source = b''.join(chunks)\n"
        "except OSError:\n"
        "    refuse_snapshot()\n"
        "finally:\n"
        "    if script_fd is not None:\n"
        "        os.close(script_fd)\n"
        "    if directory_fd is not None:\n"
        "        os.close(directory_fd)\n"
        "if digest.hexdigest() != match.group(1):\n"
        "    refuse_snapshot()\n"
        "sys.argv = sys.argv[2:]\n"
        "namespace = {'__name__': '__main__', '__file__': str(script), '__cached__': None,\n"
        "             '__doc__': None, '__loader__': None, '__package__': None, '__spec__': None}\n"
        "exec(compile(source, str(script), 'exec'), namespace)\n",
        encoding="utf-8",
    )
    return guard


def _block_python_network() -> None:
    """Block Python IPv4/IPv6 networking before any product import."""
    import socket

    original_connect = socket.socket.connect
    original_sendto = socket.socket.sendto

    def no_network(sock: socket.socket, address: object) -> object:
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise OSError("network disabled during Dex smoke tests")
        return original_connect(sock, address)  # type: ignore[arg-type]

    def no_sendto(sock: socket.socket, *args: object, **kwargs: object) -> object:
        if sock.family in (socket.AF_INET, socket.AF_INET6):
            raise OSError("network disabled during Dex smoke tests")
        return original_sendto(sock, *args, **kwargs)  # type: ignore[arg-type]

    def no_dns(*_args: object, **_kwargs: object) -> object:
        raise OSError("DNS disabled during Dex smoke tests")

    socket.socket.connect = no_network  # type: ignore[method-assign]
    socket.socket.connect_ex = no_network  # type: ignore[method-assign]
    socket.socket.sendto = no_sendto  # type: ignore[method-assign]
    socket.create_connection = no_dns  # type: ignore[assignment]
    socket.getaddrinfo = no_dns  # type: ignore[assignment]
    socket.gethostbyname = no_dns  # type: ignore[assignment]
    socket.gethostbyname_ex = no_dns  # type: ignore[assignment]
    socket.gethostbyaddr = no_dns  # type: ignore[assignment]


def _tracked_runner_relatives(source_root: Path) -> tuple[Path, ...]:
    relatives = RUNNER_FALLBACK_RELATIVES
    tracked = _git_tree_paths(source_root, "HEAD")
    if tracked is None:
        return relatives
    runtime_paths = tuple(
        Path(relative)
        for relative in sorted(tracked)
        if _is_runner_runtime_path(relative)
    )
    return runtime_paths or relatives


def _open_runner_source(source_root: Path, relative: Path) -> tuple[int, os.stat_result]:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory_flag is None:
        raise JourneySafetySkip("safe no-follow runner reads are unavailable")
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    directory_flags = os.O_RDONLY | no_follow | directory_flag | close_on_exec
    file_flags = os.O_RDONLY | no_follow | close_on_exec
    directory_fd: int | None = None
    source_fd: int | None = None
    try:
        directory_fd = os.open(source_root, directory_flags)
        for part in relative.parts[:-1]:
            child_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
        source_fd = os.open(relative.name, file_flags, dir_fd=directory_fd)
        source_stat = os.fstat(source_fd)
        if not stat.S_ISREG(source_stat.st_mode):
            raise JourneySafetySkip(f"tracked runner path is not a regular file: {relative}")
        return source_fd, source_stat
    except JourneySafetySkip:
        if source_fd is not None:
            os.close(source_fd)
        raise
    except OSError as exc:
        if source_fd is not None:
            os.close(source_fd)
        raise JourneySafetySkip(f"tracked runner file could not be opened: {relative}") from exc
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def _copy_runner_file(
    source_root: Path,
    relative: Path,
    destination: Path,
) -> None:
    """Copy a regular file through no-follow descriptors."""
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        raise JourneySafetySkip("safe no-follow runner copy is unavailable")
    close_on_exec = getattr(os, "O_CLOEXEC", 0)
    source_fd: int | None = None
    destination_fd: int | None = None
    try:
        source_fd, source_stat = _open_runner_source(source_root, relative)

        destination.parent.mkdir(parents=True, exist_ok=True)
        destination_fd = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | no_follow | close_on_exec,
            0o600,
        )
        with (
            os.fdopen(os.dup(source_fd), "rb") as source_handle,
            os.fdopen(os.dup(destination_fd), "wb") as destination_handle,
        ):
            shutil.copyfileobj(source_handle, destination_handle)
        os.fchmod(destination_fd, stat.S_IMODE(source_stat.st_mode))
    except OSError as exc:
        raise JourneySafetySkip(f"tracked runner file could not be copied: {relative}") from exc
    finally:
        for descriptor in (destination_fd, source_fd):
            if descriptor is not None:
                os.close(descriptor)


def _runner_file_matches_source(
    source_root: Path,
    relative: Path,
    runner_root: Path,
) -> bool:
    source_fd: int | None = None
    runner_fd: int | None = None
    try:
        source_fd, source_stat = _open_runner_source(source_root, relative)
        runner_fd, runner_stat = _open_runner_source(runner_root, relative)
        if stat.S_IMODE(source_stat.st_mode) != stat.S_IMODE(runner_stat.st_mode):
            return False
        while True:
            source_chunk = os.read(source_fd, 1024 * 1024)
            runner_chunk = os.read(runner_fd, 1024 * 1024)
            if source_chunk != runner_chunk:
                return False
            if not source_chunk:
                return True
    finally:
        for descriptor in (runner_fd, source_fd):
            if descriptor is not None:
                os.close(descriptor)


def _materialize_runner(destination: Path) -> Path:
    """Snapshot the installed core generation away from the writable checkout."""
    source_root = RUNNER_ROOT
    relatives = tuple(sorted(_tracked_runner_relatives(source_root)))

    for relative in relatives:
        if (
            relative.is_absolute()
            or not relative.parts
            or relative.parts[0] != "core"
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise JourneySafetySkip(f"tracked runner path is unsafe: {relative}")
        source = source_root / relative
        _ensure_safe_source(source, source_root)
        _copy_runner_file(source_root, relative, destination / relative)
    if tuple(sorted(_tracked_runner_relatives(source_root))) != relatives:
        raise JourneySafetySkip("tracked runner paths changed during snapshot")
    for relative in relatives:
        if not _runner_file_matches_source(source_root, relative, destination):
            raise JourneySafetySkip(f"tracked runner file changed during snapshot: {relative}")
    return destination


def _materialize_release_core(
    repo_root: Path,
    destination: Path,
    *,
    timeout_seconds: float,
) -> tuple[str | None, str]:
    """Extract regular ``core`` files from the installed release Git tree."""
    channel = release_channel.read_channel(repo_root)
    reference = _git_release_ref(repo_root, channel)
    if reference is None:
        return None, _missing_release_ref_reason(channel)
    command = _git_command(repo_root, "archive", "--format=tar", reference, "--", "core")
    if command is None:
        return None, "trusted system git is unavailable"
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            env=_git_environment(),
            timeout=max(0.05, min(3.0, timeout_seconds)),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"release snapshot failed: {_one_line(exc)}"
    if result.returncode != 0:
        return None, f"release snapshot failed: {_one_line(result.stderr.decode(errors='replace'))}"

    try:
        with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
            for member in archive.getmembers():
                parts = Path(member.name).parts
                if not _is_runner_runtime_path(member.name):
                    continue
                if (
                    not parts
                    or parts[0] != "core"
                    or Path(member.name).is_absolute()
                    or any(part in {"", ".", ".."} for part in parts)
                    or (
                        _is_sensitive_path(Path(member.name))
                        and Path(member.name) not in CONTENT_VERIFIED_SENSITIVE_DEPENDENCIES
                    )
                ):
                    raise JourneySafetySkip(f"release archive contains unsafe path {member.name!r}")
                target = destination.joinpath(*parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    raise JourneySafetySkip(
                        f"release archive path {member.name!r} is not a regular file"
                    )
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise JourneySafetySkip(f"release archive path {member.name!r} could not be read")
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("wb") as handle:
                    shutil.copyfileobj(extracted, handle)
                target.chmod(0o555 if member.mode & 0o111 else 0o444)
    except (OSError, tarfile.TarError, JourneySafetySkip) as exc:
        shutil.rmtree(destination, ignore_errors=True)
        return None, _one_line(exc)
    return reference, "verified installed release snapshot"


def _set_runtime_path_writable(path: Path, *, writable: bool) -> None:
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory_flag is None:
        raise JourneySafetySkip("safe no-follow runtime chmod is unavailable")
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(path_stat.st_mode):
        raise JourneySafetySkip(f"runtime tree contains a symlink: {path}")
    if stat.S_ISDIR(path_stat.st_mode):
        flags = os.O_RDONLY | no_follow | directory_flag
        mode = 0o755 if writable else 0o555
    elif stat.S_ISREG(path_stat.st_mode):
        flags = os.O_RDONLY | no_follow
        current_mode = stat.S_IMODE(path_stat.st_mode)
        mode = (current_mode | stat.S_IWUSR) if writable else (current_mode & ~0o222)
    else:
        raise JourneySafetySkip(f"runtime tree contains a non-regular path: {path}")
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise JourneySafetySkip(f"runtime tree path could not be opened safely: {path}") from exc
    try:
        opened_stat = os.fstat(descriptor)
        if (
            opened_stat.st_dev != path_stat.st_dev
            or opened_stat.st_ino != path_stat.st_ino
            or stat.S_IFMT(opened_stat.st_mode) != stat.S_IFMT(path_stat.st_mode)
        ):
            raise JourneySafetySkip(f"runtime tree path changed during chmod: {path}")
        os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)


def _set_runtime_tree_writable(root: Path, *, writable: bool) -> None:
    try:
        root_stat = root.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
        raise JourneySafetySkip(f"runtime tree root is not a regular directory: {root}")
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=writable):
        _set_runtime_path_writable(path, writable=writable)
    _set_runtime_path_writable(root, writable=writable)


def _create_run_marker(temporary_root: Path) -> tuple[Path, str]:
    marker = temporary_root / ".dex-smoke-run"
    token = secrets.token_urlsafe(32)
    marker.write_text(token, encoding="utf-8")
    marker.chmod(0o600)
    return marker, token


def _authorize_internal(vault: Path, marker: Path | None) -> None:
    if marker is None or marker.is_symlink() or not marker.is_file():
        raise PermissionError("internal smoke mode requires a regular parent-created run marker")
    temporary_root = marker.parent.resolve()
    system_temporary_root = Path(tempfile.gettempdir()).resolve()
    try:
        temporary_root.relative_to(system_temporary_root)
    except ValueError as exc:
        raise PermissionError("internal smoke mode is restricted to the system temp directory") from exc
    if not temporary_root.name.startswith("dex-smoke-"):
        raise PermissionError("internal smoke mode requires a Dex smoke temp directory")
    if vault.resolve() != (temporary_root / "vault").resolve():
        raise PermissionError("internal smoke mode cannot target a live vault")
    configured_vault = os.environ.get("VAULT_PATH")
    if configured_vault is None or Path(configured_vault).resolve() != vault.resolve():
        raise PermissionError("internal smoke mode requires its isolated VAULT_PATH")
    expected = marker.read_text(encoding="utf-8")
    provided = os.environ.get("DEX_SMOKE_RUN_TOKEN", "")
    if not provided or not secrets.compare_digest(provided, expected):
        raise PermissionError("internal smoke run marker did not authenticate")


def _internal_release_root(marker: Path, supplied: Path | None) -> Path:
    expected = marker.parent / "release"
    candidate = supplied or expected
    if candidate.is_symlink() or candidate.resolve() != expected.resolve():
        raise PermissionError("internal smoke release root escaped the run directory")
    return candidate


def _clean_environment(
    vault: Path,
    home: Path,
    runner_root: Path,
    temporary_root: Path,
    run_token: str,
) -> dict[str, str]:
    guard = _install_network_guard(temporary_root)
    python_paths = [str(runner_root), str(guard)]
    for key in ("purelib", "platlib"):
        site_packages = Path(sysconfig.get_paths()[key]).resolve()
        if site_packages.is_dir() and str(site_packages) not in python_paths:
            python_paths.append(str(site_packages))
    return {
        "HOME": str(home),
        "PATH": SAFE_PATH,
        "PYTHONPATH": os.pathsep.join(python_paths),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUNBUFFERED": "1",
        "TMPDIR": str(temporary_root),
        "VAULT_PATH": str(vault),
        "DEX_SMOKE_RUN_TOKEN": run_token,
        "DEX_SMOKE_SERVER_BOOTSTRAP": str(guard / "server_bootstrap.py"),
        **({"DEX_SMOKE_NODE": node} if (node := _trusted_node()) is not None else {}),
    }


def _journey_command(
    journey_id: str,
    runner_root: Path,
    release_root: Path | None,
    marker: Path,
) -> list[str]:
    command = [
        sys.executable,
        "-S",
        str(runner_root / "core" / "utils" / "smoke.py"),
        "--_journey",
        journey_id,
        "--run-marker",
        str(marker),
    ]
    if release_root is not None:
        command.extend(("--release-root", str(release_root)))
    return command


def _preparation_command(
    journey_id: str,
    source: Path,
    vault: Path,
    repo_root: Path,
    runner_root: Path,
    release_root: Path | None,
    release_ref: str | None,
    marker: Path,
) -> list[str]:
    command = [
        sys.executable,
        "-S",
        str(runner_root / "core" / "utils" / "smoke.py"),
        "--_prepare",
        journey_id,
        "--source-root",
        str(source),
        "--vault-root",
        str(vault),
        "--repo-root",
        str(repo_root),
        "--run-marker",
        str(marker),
    ]
    if release_root is not None:
        command.extend(("--release-root", str(release_root)))
    if release_ref is not None:
        command.extend(("--release-ref", release_ref))
    return command


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        if process.poll() is None:
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                pass
        return

    if process.poll() is not None:
        return
    process.kill()
    try:
        process.wait(timeout=0.2)
    except subprocess.TimeoutExpired:
        pass


def _decode_child_result(stdout: str) -> dict[str, str]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise ValueError("journey returned no JSON")
    decoded = json.loads(lines[-1])
    if not isinstance(decoded, dict):
        raise ValueError("journey result is not an object")
    verdict = decoded.get("verdict")
    detail = decoded.get("detail")
    if verdict not in VERDICTS or not isinstance(detail, str) or not detail.strip():
        raise ValueError("journey result has an invalid verdict or detail")
    return {"verdict": verdict, "detail": _one_line(detail)}


def _run_json_process(
    command: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout_seconds: float,
    label: str,
) -> tuple[dict[str, str], bool]:
    process: subprocess.Popen[str] | None = None
    try:
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=dict(env),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _terminate_process_group(process)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
            return (
                {
                    "verdict": "UNKNOWN",
                    "detail": f"{label} timed out after {timeout_seconds:g}s",
                },
                True,
            )
        _terminate_process_group(process)
        if process.returncode != 0:
            diagnostic = _one_line(stderr or stdout or f"exit {process.returncode}")[-500:]
            return (
                {"verdict": "UNKNOWN", "detail": f"{label} harness failed: {diagnostic}"},
                True,
            )
        return _decode_child_result(stdout), False
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        if process is not None:
            _terminate_process_group(process)
        return {"verdict": "UNKNOWN", "detail": f"{label} harness failed: {_one_line(exc)}"}, True


def _run_journey_process(
    definition: JourneyDefinition,
    *,
    runner_root: Path,
    release_root: Path | None,
    cwd: Path,
    marker: Path,
    env: Mapping[str, str],
    timeout_seconds: float,
) -> tuple[dict[str, str], bool]:
    return _run_json_process(
        _journey_command(definition.id, runner_root, release_root, marker),
        cwd=cwd,
        env=env,
        timeout_seconds=timeout_seconds,
        label="journey",
    )


def _summary(journeys: Sequence[Mapping[str, object]]) -> dict[str, int]:
    return {
        "ok": sum(journey["verdict"] == "OK" for journey in journeys),
        "broken": sum(journey["verdict"] == "BROKEN" for journey in journeys),
        "unknown": sum(journey["verdict"] == "UNKNOWN" for journey in journeys),
        "off": sum(journey["verdict"] == "OFF" for journey in journeys),
    }


def _harness_failure_run(
    journey_definitions: Sequence[JourneyDefinition],
    error: object,
) -> SmokeRun:
    detail = f"smoke harness failed: {_one_line(error)}"
    journeys = [
        {"id": definition.id, "verdict": "UNKNOWN", "detail": detail, "duration_ms": 0}
        for definition in journey_definitions
    ]
    return SmokeRun(
        {
            "schema_version": SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "journeys": journeys,
            "summary": _summary(journeys),
        },
        harness_failed=True,
    )


def _safe_temporary_parent(source: Path) -> Path:
    candidates = (Path("/private/tmp"), Path("/tmp"), Path("/var/tmp"), Path(tempfile.gettempdir()))
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(source)
        except FileNotFoundError:
            continue
        except ValueError:
            if resolved.is_dir() and os.access(resolved, os.W_OK | os.X_OK):
                return resolved
    raise OSError("no writable system temp directory exists outside the live vault")


def _is_system_temporary_path(path: Path) -> bool:
    absolute = Path(os.path.abspath(path))
    for candidate in (Path("/private/tmp"), Path("/tmp"), Path("/var/tmp"), Path(tempfile.gettempdir())):
        try:
            root = candidate.resolve(strict=True)
            absolute.relative_to(root)
        except (FileNotFoundError, ValueError):
            continue
        return True
    return False


def _open_system_temporary_parent(parent: Path) -> int | None:
    """Open a temp parent component-by-component, refusing symlink traversal."""
    no_follow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if no_follow is None or directory_flag is None:
        return None
    absolute = Path(os.path.abspath(parent))
    matches: list[tuple[Path, Path]] = []
    for candidate in (Path("/private/tmp"), Path("/tmp"), Path("/var/tmp"), Path(tempfile.gettempdir())):
        try:
            root = candidate.resolve(strict=True)
            relative = absolute.relative_to(root)
        except (FileNotFoundError, ValueError):
            continue
        matches.append((root, relative))
    if not matches:
        return None
    root, relative = max(matches, key=lambda match: len(match[0].parts))
    flags = os.O_RDONLY | no_follow | directory_flag | getattr(os, "O_CLOEXEC", 0)
    descriptor: int | None = None
    opened = False
    try:
        descriptor = os.open(root, flags)
        for part in relative.parts:
            component_stat = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISLNK(component_stat.st_mode) or not stat.S_ISDIR(component_stat.st_mode):
                return None
            child_fd = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child_fd
        opened = True
        return descriptor
    except OSError:
        return None
    finally:
        if descriptor is not None and not opened:
            os.close(descriptor)


def issue_mcp_once_consent_token(name: str, *, directory: Path | None = None) -> Path:
    """Issue a short-lived, single-use marker for one explicitly requested check.

    This keeps automatic and recurring checks from launching one-off custom code. It is
    not protection from another program running as this user; that program could run the
    same custom code directly without any token.
    """
    if not name.startswith("custom-") or not name.strip():
        raise ValueError("one-off consent tokens require a non-empty custom-* name")
    parent = directory or Path(tempfile.gettempdir())
    if not parent.is_dir() or not _is_system_temporary_path(parent):
        raise ValueError("one-off consent tokens must be created in system temp")
    descriptor, raw_path = tempfile.mkstemp(prefix=MCP_ONCE_TOKEN_PREFIX, dir=parent)
    token_path = Path(raw_path)
    payload = json.dumps(
        {
            "schema_version": 1,
            "name": name,
            "nonce": secrets.token_urlsafe(32),
            "issued_at": time.time(),
        },
        separators=(",", ":"),
    ).encode("utf-8")
    try:
        os.fchmod(descriptor, 0o600)
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            view = view[written:]
        os.fsync(descriptor)
    except OSError:
        token_path.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    return token_path


def _consume_mcp_once_consent_token(name: str, token_path: Path | None) -> bool:
    if token_path is None:
        return False
    token = Path(os.path.abspath(token_path))
    if not token.name.startswith(MCP_ONCE_TOKEN_PREFIX) or not _is_system_temporary_path(token):
        return False
    no_follow = getattr(os, "O_NOFOLLOW", None)
    if no_follow is None:
        return False
    parent_fd = _open_system_temporary_parent(token.parent)
    if parent_fd is None:
        return False
    descriptor: int | None = None
    consumed_name = f".{token.name}.consumed-{secrets.token_hex(16)}"
    claimed = False
    payload = b""
    try:
        # Claim the marker before opening or validating its contents. This makes explicit
        # approval single-use but does not authenticate the user against same-uid code.
        os.rename(
            token.name,
            consumed_name,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        claimed = True
        descriptor = os.open(
            consumed_name,
            os.O_RDONLY | no_follow | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_fd,
        )
        opened_stat = os.fstat(descriptor)
        safe_to_read = (
            stat.S_ISREG(opened_stat.st_mode)
            and opened_stat.st_uid == os.getuid()
            and not opened_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            and opened_stat.st_size <= 4096
        )
        if not safe_to_read:
            return False
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 4096)
            if not chunk:
                break
            chunks.append(chunk)
        payload = b"".join(chunks)
        current_stat = os.stat(consumed_name, dir_fd=parent_fd, follow_symlinks=False)
        if (current_stat.st_dev, current_stat.st_ino) != (opened_stat.st_dev, opened_stat.st_ino):
            return False
    except (OSError, ValueError):
        return False
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if claimed:
            try:
                os.unlink(consumed_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        os.close(parent_fd)
    try:
        decoded = json.loads(payload)
        issued_at = float(decoded["issued_at"])
        nonce = decoded["nonce"]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return False
    age = time.time() - issued_at
    return (
        decoded.get("schema_version") == 1
        and decoded.get("name") == name
        and isinstance(nonce, str)
        and len(nonce) >= 32
        and 0 <= age <= MCP_ONCE_TOKEN_MAX_AGE_SECONDS
    )


def _run_smoke_journeys(
    *,
    source: Path,
    repository: Path,
    temporary_parent: Path,
    runner_root: Path,
    journey_definitions: Sequence[JourneyDefinition],
    global_timeout_seconds: float,
    started: float,
) -> tuple[list[dict[str, Any]], bool]:
    results: list[dict[str, Any]] = []
    harness_failed = False

    for definition in journey_definitions:
        journey_started = time.monotonic()
        remaining = global_timeout_seconds - (journey_started - started)
        if remaining <= 0:
            results.append(
                {
                    "id": definition.id,
                    "verdict": "UNKNOWN",
                    "detail": "global 30s smoke budget was exhausted",
                    "duration_ms": 0,
                }
            )
            harness_failed = True
            continue

        try:
            with tempfile.TemporaryDirectory(
                prefix=f"dex-smoke-{definition.id}-",
                dir=temporary_parent,
            ) as temporary:
                temporary_root = Path(temporary)
                vault = temporary_root / "vault"
                home = temporary_root / "home"
                home.mkdir()
                marker, run_token = _create_run_marker(temporary_root)
                release_destination = temporary_root / "release"
                snapshot_budget = min(
                    definition.timeout_seconds - (time.monotonic() - journey_started),
                    global_timeout_seconds - (time.monotonic() - started),
                )
                release_ref, _release_reason = _materialize_release_core(
                    repository,
                    release_destination,
                    timeout_seconds=max(0.05, snapshot_budget),
                )
                release_root = release_destination if release_ref is not None else None
                if release_root is not None:
                    _set_runtime_tree_writable(release_root, writable=False)
                try:
                    env = _clean_environment(
                        vault,
                        home,
                        runner_root,
                        temporary_root,
                        run_token,
                    )
                    preparation_budget = min(
                        definition.timeout_seconds - (time.monotonic() - journey_started),
                        global_timeout_seconds - (time.monotonic() - started),
                    )
                    if preparation_budget <= 0:
                        result = {
                            "verdict": "UNKNOWN",
                            "detail": "journey timed out during preparation",
                        }
                        harness_failed = True
                    else:
                        prepared, preparation_failed = _run_json_process(
                            _preparation_command(
                                definition.id,
                                source,
                                vault,
                                repository,
                                runner_root,
                                release_root,
                                release_ref,
                                marker,
                            ),
                            cwd=temporary_root,
                            env=env,
                            timeout_seconds=preparation_budget,
                            label="journey preparation",
                        )
                        harness_failed = harness_failed or preparation_failed
                        if preparation_failed or prepared["verdict"] != "OK":
                            result = prepared
                        else:
                            process_budget = min(
                                definition.timeout_seconds - (time.monotonic() - journey_started),
                                global_timeout_seconds - (time.monotonic() - started),
                            )
                            if process_budget <= 0:
                                result = {
                                    "verdict": "UNKNOWN",
                                    "detail": "journey timed out during preparation",
                                }
                                harness_failed = True
                            else:
                                result, failed = _run_journey_process(
                                    definition,
                                    runner_root=runner_root,
                                    release_root=release_root,
                                    cwd=temporary_root,
                                    marker=marker,
                                    env=env,
                                    timeout_seconds=process_budget,
                                )
                                harness_failed = harness_failed or failed
                finally:
                    if release_root is not None:
                        _set_runtime_tree_writable(release_root, writable=True)
        except Exception as exc:
            result = {"verdict": "UNKNOWN", "detail": f"journey harness failed: {_one_line(exc)}"}
            harness_failed = True

        results.append(
            {
                "id": definition.id,
                "verdict": result["verdict"],
                "detail": result["detail"],
                "duration_ms": max(0, round((time.monotonic() - journey_started) * 1000)),
            }
        )
    return results, harness_failed


def run_smoke(
    *,
    vault_root: Path | None = None,
    repo_root: Path | None = None,
    journey_definitions: Sequence[JourneyDefinition] = JOURNEYS,
    global_timeout_seconds: float = GLOBAL_TIMEOUT_SECONDS,
) -> SmokeRun:
    """Run isolated journeys against one immutable installed-code snapshot."""
    try:
        source = (vault_root or Path(os.environ.get("VAULT_PATH", Path.cwd()))).resolve()
        repository = (repo_root or Path(__file__).resolve().parents[2]).resolve()
        temporary_parent = _safe_temporary_parent(source)
    except Exception as exc:
        return _harness_failure_run(journey_definitions, exc)

    started = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(
            prefix="dex-smoke-runner-",
            dir=temporary_parent,
        ) as temporary:
            runner_root = _materialize_runner(Path(temporary) / "runner")
            try:
                _set_runtime_tree_writable(runner_root, writable=False)
                results, harness_failed = _run_smoke_journeys(
                    source=source,
                    repository=repository,
                    temporary_parent=temporary_parent,
                    runner_root=runner_root,
                    journey_definitions=journey_definitions,
                    global_timeout_seconds=global_timeout_seconds,
                    started=started,
                )
            finally:
                _set_runtime_tree_writable(runner_root, writable=True)
    except Exception as exc:
        return _harness_failure_run(journey_definitions, exc)

    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "journeys": results,
        "summary": _summary(results),
    }
    return SmokeRun(report, harness_failed)


def check_custom_mcp_once(
    vault_root: Path,
    name: str,
    *,
    consent_token: Path | None = None,
) -> dict[str, str]:
    """Run one explicitly requested custom local Python startup check from a snapshot."""
    from core.utils.mcp_handshake import mcp_stdio_handshake
    from core.utils.trust_registry import TrustRegistryError, snapshot_local_python_mcp
    from core.utils.validators import validate_mcp_config

    if not _consume_mcp_once_consent_token(name, consent_token):
        return {"verdict": "UNKNOWN", "detail": MCP_ONCE_CONSENT_DETAIL}
    if not name.startswith("custom-"):
        return {"verdict": "UNKNOWN", "detail": "only custom-* local Python entries can be checked"}
    config_path = vault_root / ".mcp.json"
    try:
        _ensure_safe_source(config_path, vault_root)
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (JourneySafetySkip, OSError, json.JSONDecodeError) as exc:
        return {"verdict": "UNKNOWN", "detail": f".mcp.json could not be read safely: {_one_line(exc)}"}
    errors = validate_mcp_config(config)
    if errors:
        return {"verdict": "UNKNOWN", "detail": "; ".join(_one_line(error) for error in errors)}
    entry = config["mcpServers"].get(name)
    if entry is None:
        return {"verdict": "UNKNOWN", "detail": f".mcp.json has no entry named {name}"}

    try:
        parent = _safe_temporary_parent(vault_root)
        with tempfile.TemporaryDirectory(prefix="dex-mcp-check-once-", dir=parent) as temporary:
            temporary_root = Path(temporary)
            isolated_vault = temporary_root / "vault"
            isolated_vault.mkdir(mode=0o700)
            _write_analytics_opt_out(isolated_vault)
            snapshot = snapshot_local_python_mcp(
                vault_root,
                name,
                entry,
                isolated_vault / ".dex-trusted-mcp-snapshots",
            )
            if not snapshot.trusted or snapshot.snapshot_path is None:
                return {"verdict": "UNKNOWN", "detail": snapshot.detail}
            home = temporary_root / "home"
            home.mkdir()
            env = _clean_environment(
                isolated_vault,
                home,
                RUNNER_ROOT,
                temporary_root,
                secrets.token_urlsafe(32),
            )
            bootstrap = Path(env["DEX_SMOKE_SERVER_BOOTSTRAP"])
            result = mcp_stdio_handshake(
                [
                    sys.executable,
                    "-S",
                    str(bootstrap),
                    "--verified-snapshot",
                    str(snapshot.snapshot_path),
                ],
                cwd=isolated_vault,
                env=env,
                timeout=HANDSHAKE_TIMEOUT_SECONDS,
            )
    except (OSError, TrustRegistryError) as exc:
        return {"verdict": "UNKNOWN", "detail": _one_line(exc)}
    if result.ok:
        return {"verdict": "OK", "detail": f"{name} started from its private snapshot"}
    if SNAPSHOT_CHANGED_DETAIL in result.stderr:
        return {"verdict": "UNKNOWN", "detail": SNAPSHOT_CHANGED_DETAIL}
    return {
        "verdict": "BROKEN",
        "detail": f"{name} did not start: {_one_line(result.error or result.stderr)}",
    }


def _load_yaml(path: Path) -> object:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _journey_configs(vault: Path, _release_root: Path) -> dict[str, str]:
    expected_validator = _validator_path()
    if expected_validator is None:
        return {
            "verdict": "UNKNOWN",
            "detail": "configuration validation helper is unavailable",
        }
    from core.utils import validators

    if Path(validators.__file__).resolve() != expected_validator.resolve():
        return {
            "verdict": "UNKNOWN",
            "detail": "configuration validation escaped the runner snapshot",
        }

    checks: tuple[tuple[Path, Callable[[object], list[str]]], ...] = (
        (vault / "System" / "user-profile.yaml", validators.validate_user_profile_config),
        (vault / "System" / "pillars.yaml", validators.validate_pillars_config),
    )
    errors = []
    checked = 0
    for path, validator in checks:
        relative = path.relative_to(vault).as_posix()
        try:
            data = _load_yaml(path)
        except FileNotFoundError:
            errors.append(f"{relative}: missing")
            continue
        except Exception as exc:  # PyYAML's error type is deliberately loaded lazily.
            errors.append(f"{relative}: {_one_line(exc)}")
            continue
        checked += 1
        errors.extend(f"{relative}: {error}" for error in validator(data))

    integrations = vault / "System" / "integrations"
    for path in sorted(integrations.glob("*.yaml")):
        relative = path.relative_to(vault).as_posix()
        try:
            data = _load_yaml(path)
        except Exception as exc:
            errors.append(f"{relative}: {_one_line(exc)}")
            continue
        checked += 1
        validator_errors = validators.validate_integration_config(
            data,
            main=path.name == "config.yaml",
        )
        errors.extend(f"{relative}: {error}" for error in validator_errors)

    if errors:
        return {"verdict": "BROKEN", "detail": "; ".join(errors)}
    return {"verdict": "OK", "detail": f"parsed and validated {checked} configuration files"}


def _decode_tool_response(contents: Sequence[object]) -> dict[str, Any]:
    if not contents or not isinstance(getattr(contents[0], "text", None), str):
        raise RuntimeError("work server returned no text result")
    decoded = json.loads(contents[0].text)
    if not isinstance(decoded, dict):
        raise RuntimeError("work server result was not an object")
    return decoded


def _journey_task_lifecycle(vault: Path, _release_root: Path) -> dict[str, str]:
    tasks_file = _core_path(vault, "TASKS_FILE")
    tasks_dir = tasks_file.parent
    try:
        plan_path = vault / TASK_PLAN
        if plan_path.is_symlink() or not plan_path.is_file():
            return {"verdict": "UNKNOWN", "detail": "task lifecycle plan is unavailable"}
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if plan.get("executable") is not True:
            reason = _one_line(plan.get("reason", "release code could not be verified"))
            return {
                "verdict": "UNKNOWN",
                "detail": f"task lifecycle not executed for safety ({reason})",
            }
        expected_work_server = RUNNER_ROOT / "core" / "mcp" / "work_server.py"
        if (
            RUNNER_ROOT.is_symlink()
            or expected_work_server.is_symlink()
            or not expected_work_server.is_file()
        ):
            return {
                "verdict": "UNKNOWN",
                "detail": "task lifecycle not executed for safety (runner work server is unavailable)",
            }
        if not tasks_dir.is_dir() or not tasks_file.is_file():
            return {"verdict": "BROKEN", "detail": f"{tasks_file.relative_to(vault)} is missing"}
        for path in (tasks_dir, tasks_file):
            if not path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
                return {"verdict": "BROKEN", "detail": f"{path.relative_to(vault)} is not writable"}

        original = tasks_file.read_text(encoding="utf-8")
        original_lines = original.splitlines()
        original_task_ids = re.findall(r"\^(task-\d{8}-\d{3})", original)

        from core.mcp import work_server as work

        if Path(work.__file__).resolve() != expected_work_server.resolve():
            return {
                "verdict": "UNKNOWN",
                "detail": "task lifecycle not executed for safety (work server import escaped the runner snapshot)",
            }

        work.HAS_QMD = False
        work.is_qmd_available = lambda: False
        work.refresh_search_index = lambda: None
        work._fire_analytics_event = lambda *_args, **_kwargs: {"fired": False}

        async def exercise() -> tuple[dict[str, Any], dict[str, Any]]:
            pillar_ids = work.get_pillar_ids()
            if not pillar_ids:
                raise RuntimeError("work server has no pillar available for task creation")
            title = f"Verify Dex isolated task lifecycle {os.getpid()}"
            created = _decode_tool_response(
                await work.handle_call_tool(
                    "create_task",
                    {
                        "title": title,
                        "pillar": pillar_ids[0],
                        "priority": "P3",
                        "section": "Dex Smoke",
                    },
                )
            )
            if created.get("success") is not True or not isinstance(created.get("task"), dict):
                raise RuntimeError(f"create_task failed: {_one_line(created)}")
            task_id = created["task"].get("task_id")
            if not isinstance(task_id, str):
                raise RuntimeError("create_task returned no task id")
            updated = _decode_tool_response(
                await work.handle_call_tool(
                    "update_task_status",
                    {"task_id": task_id, "status": "d"},
                )
            )
            if updated.get("success") is not True:
                raise RuntimeError(f"update_task_status failed: {_one_line(updated)}")
            return created, updated

        created, _updated = asyncio.run(exercise())
        task_id = created["task"]["task_id"]
        final = tasks_file.read_text(encoding="utf-8")
        if not final.startswith(original_lines[0] if original_lines else "#"):
            raise RuntimeError("Tasks.md top-level heading changed")
        if len(final) < len(original):
            raise RuntimeError("Tasks.md was truncated")
        remaining_lines = iter(final.splitlines())
        for original_line in original_lines:
            if not any(candidate == original_line for candidate in remaining_lines):
                raise RuntimeError("existing Tasks.md content was changed or reordered")
        for existing_id in original_task_ids:
            if final.count(f"^{existing_id}") != original.count(f"^{existing_id}"):
                raise RuntimeError(f"existing task {existing_id} was changed")
        completed_pattern = rf"- \[x\].*\^{re.escape(task_id)}(?:\s|$)"
        if len(re.findall(completed_pattern, final, re.MULTILINE)) != 1:
            raise RuntimeError("created task was not completed exactly once")
    except Exception as exc:
        return {"verdict": "BROKEN", "detail": _one_line(exc)}
    return {"verdict": "OK", "detail": "create_task and update_task_status preserved Tasks.md integrity"}


def _git_release_ref(repo_root: Path, channel: str | None = None) -> str | None:
    resolved_channel = channel or release_channel.read_channel(repo_root)
    for ref in release_channel.release_ref_candidates(resolved_channel):
        verify_command = _git_command(repo_root, "rev-parse", "--verify", f"{ref}^{{commit}}")
        if verify_command is None:
            return None
        result = subprocess.run(
            verify_command,
            capture_output=True,
            env=_git_environment(),
            text=True,
            timeout=3,
            check=False,
        )
        if result.returncode == 0:
            merge_base_command = _git_command(repo_root, "merge-base", "HEAD", ref)
            if merge_base_command is None:
                return None
            merge_base = subprocess.run(
                merge_base_command,
                capture_output=True,
                env=_git_environment(),
                text=True,
                timeout=3,
                check=False,
            )
            return merge_base.stdout.strip() if merge_base.returncode == 0 else ref
    return None


def _missing_release_ref_reason(channel: str, *, server: bool = False) -> str:
    if channel == "beta":
        return "beta channel selected but no beta release found — staying on stable is safe"
    if channel == "invalid":
        return "couldn't verify your update channel"
    suffix = " to verify the server" if server else ""
    return f"no upstream/release or origin/release ref is available{suffix}"


def _git_tree_paths(repo_root: Path, treeish: str) -> set[str] | None:
    command = _git_command(repo_root, "ls-tree", "-r", "-z", "--name-only", treeish, "--", "core")
    if command is None:
        return None
    result = subprocess.run(
        command,
        capture_output=True,
        env=_git_environment(),
        timeout=3,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return {raw.decode("utf-8") for raw in result.stdout.split(b"\0") if raw}
    except UnicodeDecodeError:
        return None


def _release_execution_reason(
    repo_root: Path,
    release_root: Path | None,
    reference: str | None,
) -> str | None:
    if reference is None or release_root is None:
        return _missing_release_ref_reason(release_channel.read_channel(repo_root))
    if release_root.is_symlink() or not (release_root / "core").is_dir():
        return "the verified release snapshot is unavailable"
    reference_paths = _git_tree_paths(repo_root, reference)
    head_paths = _git_tree_paths(repo_root, "HEAD")
    if reference_paths is None or head_paths is None:
        return f"Dex-owned core could not be compared with {reference}"
    reference_paths = frozenset(path for path in reference_paths if _is_runner_runtime_path(path))
    head_paths = frozenset(path for path in head_paths if _is_runner_runtime_path(path))
    if reference_paths != head_paths:
        return f"Dex-owned core differs from {reference}"
    for relative in sorted(reference_paths):
        snapshot = release_root / relative
        installed = RUNNER_ROOT / relative
        live = repo_root / relative
        unsafe = snapshot.is_symlink()
        for root in (RUNNER_ROOT, repo_root):
            current = root
            for part in Path(relative).parts:
                current /= part
                if current.is_symlink():
                    unsafe = True
                    break
        if unsafe or not snapshot.is_file() or not installed.is_file() or not live.is_file():
            return f"Dex-owned core differs from {reference}"
        try:
            snapshot_bytes = snapshot.read_bytes()
            if snapshot_bytes != installed.read_bytes() or snapshot_bytes != live.read_bytes():
                return f"Dex-owned core differs from {reference}"
            snapshot_executable = bool(snapshot.stat().st_mode & 0o111)
            installed_executable = bool(installed.stat().st_mode & 0o111)
            live_executable = bool(live.stat().st_mode & 0o111)
        except OSError:
            return f"Dex-owned core could not be compared with {reference}"
        if snapshot_executable != installed_executable or snapshot_executable != live_executable:
            return f"Dex-owned core differs from {reference}"
    return None


def _script_is_unmodified(
    script: Path,
    repo_root: Path,
    release_root: Path | None = None,
    reference: str | None = None,
) -> tuple[bool, str]:
    repository = repo_root.resolve()
    lexical_root = repository / "core" / "mcp"
    lexical_script = Path(os.path.abspath(script))
    try:
        lexical_relative = lexical_script.relative_to(lexical_root)
    except ValueError:
        return False, "server target is not a local core/mcp file"
    if len(lexical_relative.parts) != 1 or not lexical_relative.name.endswith("_server.py"):
        return False, "server target is not a core/mcp/*_server.py file"
    if any(path.is_symlink() for path in (repository / "core", lexical_root, lexical_script)):
        return False, "server target is symlinked"
    expected_root = lexical_root.resolve()
    try:
        resolved = lexical_script.resolve(strict=True)
        relative = resolved.relative_to(expected_root)
    except (FileNotFoundError, ValueError):
        return False, "server target is not a local core/mcp file"
    if len(relative.parts) != 1 or not relative.name.endswith("_server.py"):
        return False, "server target is not a core/mcp/*_server.py file"
    current = expected_root / relative
    if current.is_symlink() or not current.is_file():
        return False, "server target is missing or symlinked"

    channel = release_channel.read_channel(repo_root)
    reference = reference or _git_release_ref(repo_root, channel)
    if reference is None:
        return False, _missing_release_ref_reason(channel, server=True)
    repo_relative = current.relative_to(repository).as_posix()
    command = _git_command(repo_root, "cat-file", "blob", f"{reference}:{repo_relative}")
    if command is None:
        return False, "trusted system git is unavailable"
    result = subprocess.run(
        command,
        capture_output=True,
        env=_git_environment(),
        timeout=3,
        check=False,
    )
    if result.returncode != 0:
        return False, f"server is not tracked in {reference}"
    try:
        live_bytes = current.read_bytes()
    except OSError as exc:
        return False, f"server could not be read: {_one_line(exc)}"
    if result.stdout != live_bytes:
        return False, f"server differs from {reference}"
    if release_root is not None:
        snapshot = release_root / repo_relative
        if snapshot.is_symlink() or not snapshot.is_file():
            return False, "server is absent from the verified release snapshot"
        try:
            if snapshot.read_bytes() != result.stdout:
                return False, "verified release snapshot does not match its Git object"
        except OSError as exc:
            return False, f"verified release server could not be read: {_one_line(exc)}"
    return True, ""


def _safe_owned_server(
    entry: Mapping[str, object],
    repo_root: Path,
    release_root: Path | None,
    reference: str | None,
) -> tuple[Path | None, str]:
    command = entry.get("command")
    args = entry.get("args")
    if not isinstance(command, str) or not PYTHON_COMMAND.fullmatch(Path(command).name):
        return None, "entry is not a Python stdio server"
    if not isinstance(args, list) or len(args) != 1 or not isinstance(args[0], str):
        return None, "entry is not a single-script Python stdio server"
    target = Path(args[0]).expanduser()
    if not target.is_absolute():
        target = repo_root / target
    safe, reason = _script_is_unmodified(target, repo_root, release_root, reference)
    if not safe or release_root is None:
        return None, reason or "verified release snapshot is unavailable"
    relative = Path(os.path.abspath(target)).relative_to(repo_root.resolve())
    return repo_root.resolve() / relative, ""


def _journey_mcp_startup(vault: Path, _release_root: Path) -> dict[str, str]:
    plan_path = vault / MCP_PLAN
    if plan_path.is_symlink() or not plan_path.is_file():
        return {"verdict": "UNKNOWN", "detail": "MCP startup plan is unavailable"}
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"verdict": "UNKNOWN", "detail": f"MCP startup plan is invalid: {_one_line(exc)}"}
    if not isinstance(plan, Mapping) or not isinstance(plan.get("entries"), list):
        return {"verdict": "UNKNOWN", "detail": "MCP startup plan has an invalid structure"}
    if plan.get("state") == "OFF":
        return {"verdict": "OFF", "detail": "no MCP configuration is installed"}
    if plan.get("state") == "BROKEN":
        return {"verdict": "BROKEN", "detail": _one_line(plan.get("detail", ".mcp.json is invalid"))}

    statuses = []
    details = []
    handshake_deadline = time.monotonic() + MCP_STARTUP_HANDSHAKE_BUDGET_SECONDS
    handshake = None
    if any(isinstance(entry, Mapping) and entry.get("verdict") == "EXECUTE" for entry in plan["entries"]):
        expected_handshake = RUNNER_ROOT / "core" / "utils" / "mcp_handshake.py"
        if (
            RUNNER_ROOT.is_symlink()
            or expected_handshake.is_symlink()
            or not expected_handshake.is_file()
        ):
            return {
                "verdict": "UNKNOWN",
                "detail": "MCP startup helper is unavailable in the runner snapshot",
            }
        from core.utils import mcp_handshake

        if Path(mcp_handshake.__file__).resolve() != expected_handshake.resolve():
            return {
                "verdict": "UNKNOWN",
                "detail": "MCP startup helper escaped the runner snapshot",
            }
        handshake = mcp_handshake.mcp_stdio_handshake
    for entry in plan["entries"]:
        if not isinstance(entry, Mapping):
            statuses.append("UNKNOWN")
            details.append("unknown entry: UNKNOWN — invalid internal startup plan")
            continue
        label = _one_line(entry.get("name", "unnamed MCP entry"))
        planned_verdict = entry.get("verdict")
        if planned_verdict != "EXECUTE":
            verdict = planned_verdict if planned_verdict in VERDICTS else "UNKNOWN"
            statuses.append(verdict)
            details.append(f"{label}: {verdict} — {_one_line(entry.get('detail', 'not executed for safety'))}")
            continue

        relative_script = entry.get("script")
        if not isinstance(relative_script, str):
            statuses.append("UNKNOWN")
            details.append(f"{label}: UNKNOWN — invalid internal startup plan")
            continue
        parts = Path(relative_script).parts
        trusted_custom = entry.get("kind") == "trusted-custom"
        if trusted_custom:
            script = vault / relative_script
            valid_script = (
                len(parts) == 2
                and parts[0] == ".dex-trusted-mcp-snapshots"
                and parts[1].endswith(".py")
                and not (vault / parts[0]).is_symlink()
                and not script.is_symlink()
                and script.is_file()
            )
        else:
            script = RUNNER_ROOT / relative_script
            valid_script = (
                len(parts) == 3
                and parts[:2] == ("core", "mcp")
                and parts[2].endswith("_server.py")
                and not RUNNER_ROOT.is_symlink()
                and not script.is_symlink()
                and script.is_file()
            )
        if not valid_script:
            statuses.append("UNKNOWN")
            details.append(f"{label}: UNKNOWN — runner server is unavailable")
            continue

        handshake_budget = handshake_deadline - time.monotonic()
        if handshake_budget <= 0:
            statuses.append("BROKEN")
            details.append(f"{label}: BROKEN — MCP startup journey exhausted its safe time budget")
            continue

        if handshake is None:
            statuses.append("UNKNOWN")
            details.append(f"{label}: UNKNOWN — MCP startup helper is unavailable")
            continue
        bootstrap = Path(os.environ.get("DEX_SMOKE_SERVER_BOOTSTRAP", ""))
        expected_bootstrap = vault.parent / "python-guard" / "server_bootstrap.py"
        if (
            bootstrap != expected_bootstrap
            or bootstrap.is_symlink()
            or not bootstrap.is_file()
        ):
            statuses.append("UNKNOWN")
            details.append(f"{label}: UNKNOWN — safe Python bootstrap is unavailable")
            continue
        command = [sys.executable, "-S", str(bootstrap)]
        if trusted_custom:
            command.extend(("--verified-snapshot", str(script)))
        else:
            command.append(str(script))
        result = handshake(
            command,
            cwd=RUNNER_ROOT,
            env=os.environ,
            timeout=min(HANDSHAKE_TIMEOUT_SECONDS, handshake_budget),
        )
        if result.ok:
            statuses.append("OK")
            details.append(f"{label}: OK")
        elif SNAPSHOT_CHANGED_DETAIL in result.stderr:
            statuses.append("UNKNOWN")
            details.append(f"{label}: UNKNOWN — {SNAPSHOT_CHANGED_DETAIL}")
        else:
            statuses.append("BROKEN")
            details.append(f"{label}: BROKEN — {_one_line(result.error or result.stderr)}")

    if not statuses:
        return {"verdict": "OK", "detail": "MCP config has no server entries"}
    return {"verdict": _roll_up(statuses), "detail": "; ".join(details)}


def _journey_skills(vault: Path, _release_root: Path) -> dict[str, str]:
    skills = sorted((vault / ".claude" / "skills").glob("*/SKILL.md"))
    if not skills:
        return {"verdict": "OFF", "detail": "no skills are installed"}
    expected_validator = _validator_path()
    if expected_validator is None:
        return {
            "verdict": "UNKNOWN",
            "detail": "skill validation helper is unavailable",
        }
    from core.utils import validators

    if Path(validators.__file__).resolve() != expected_validator.resolve():
        return {
            "verdict": "UNKNOWN",
            "detail": "skill validation escaped the runner snapshot",
        }
    errors = []
    for skill in skills:
        label = skill.relative_to(vault).as_posix()
        owner = "user" if skill.parent.name.endswith("-custom") else "shipped"
        errors.extend(
            f"{label} ({owner}): {error}"
            for error in validators.validate_skill_frontmatter(skill)
        )
    if errors:
        return {"verdict": "BROKEN", "detail": "; ".join(errors)}
    user_count = sum(skill.parent.name.endswith("-custom") for skill in skills)
    return {
        "verdict": "OK",
        "detail": f"validated {len(skills)} skills ({user_count} user, {len(skills) - user_count} shipped)",
    }


def _walk_hook_commands(value: object) -> Iterator[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "command" and isinstance(child, str):
                yield child
            else:
                yield from _walk_hook_commands(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_hook_commands(child)


def _expanded_hook_command(command: str, vault: Path) -> str:
    return command.replace("${CLAUDE_PROJECT_DIR}", str(vault)).replace("$CLAUDE_PROJECT_DIR", str(vault))


def _shell_tokens(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _hook_script_targets(command: str, vault: Path) -> list[tuple[int, Path]]:
    try:
        tokens = _shell_tokens(command)
    except ValueError:
        return []
    targets = []
    for index, token in enumerate(tokens):
        if token.startswith("-") or any(marker in token for marker in ("$", "|", ">", "<")):
            continue
        candidate = Path(token)
        if candidate.suffix not in SCRIPT_SUFFIXES:
            continue
        if not candidate.is_absolute():
            candidate = vault / candidate
        targets.append((index, candidate))
    return targets


def _hook_executables(tokens: Sequence[str]) -> list[str]:
    executables = []
    expecting_command = True
    for token in tokens:
        if token in {"&", "&&", ";", "|", "||"}:
            expecting_command = True
            continue
        if not expecting_command:
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token):
            continue
        if token in {"!", "(", ")", "{"} or token.startswith((">", "<")):
            continue
        executables.append(token)
        expecting_command = False
    return executables


def _unresolved_hook_targets(tokens: Sequence[str]) -> list[str]:
    unresolved = []
    interpreters = {"bash", "sh", "node", "python", "python3"}
    for index, token in enumerate(tokens):
        if "$" not in token and "`" not in token:
            continue
        previous = Path(tokens[index - 1]).name if index else ""
        if Path(token).suffix in SCRIPT_SUFFIXES or previous in interpreters or index == 0:
            unresolved.append(token)
    return unresolved


def _node_from_clean_environment(env: Mapping[str, str]) -> str | None:
    configured = env.get("DEX_SMOKE_NODE")
    if not configured:
        return None
    candidate = Path(configured)
    if candidate.is_symlink() or not candidate.is_file() or not os.access(candidate, os.X_OK):
        return None
    return str(candidate)


def _syntax_check(target: Path, env: Mapping[str, str], vault: Path) -> tuple[str, str]:
    if target.suffix == ".sh":
        command = ["/bin/bash", "-n", str(target)]
    elif target.suffix in {".js", ".cjs", ".mjs"}:
        node = _node_from_clean_environment(env)
        if node is None:
            return "UNKNOWN", f"{target.relative_to(vault)}: node is unavailable for --check"
        command = [node, "--check", str(target)]
    elif target.suffix == ".py":
        try:
            compile(target.read_text(encoding="utf-8"), str(target), "exec")
        except (OSError, SyntaxError) as exc:
            return "BROKEN", f"{target.relative_to(vault)}: {_one_line(exc)}"
        return "OK", ""
    else:
        return "OK", ""
    result = subprocess.run(
        command,
        cwd=vault,
        env=dict(env),
        capture_output=True,
        text=True,
        timeout=3,
        check=False,
    )
    if result.returncode != 0:
        return "BROKEN", f"{target.relative_to(vault)}: {_one_line(result.stderr or result.stdout)}"
    return "OK", ""


def _journey_hooks(vault: Path, _repo_root: Path) -> dict[str, str]:
    settings_path = vault / ".claude" / "settings.json"
    if not settings_path.is_file():
        return {"verdict": "OFF", "detail": "no Claude hook settings are installed"}
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"verdict": "BROKEN", "detail": f".claude/settings.json is invalid: {_one_line(exc)}"}
    if not isinstance(settings, Mapping):
        return {"verdict": "BROKEN", "detail": ".claude/settings.json must be an object"}
    commands = list(_walk_hook_commands(settings.get("hooks", {})))
    if not commands:
        return {"verdict": "OFF", "detail": "no hooks are configured"}

    statuses = []
    details = []
    checked_targets: set[Path] = set()
    shell_builtins = {"cd", "echo", "export", "false", "printf", "source", "test", "true"}
    env = dict(os.environ)
    for raw_command in commands:
        command = _expanded_hook_command(raw_command, vault)
        syntax = subprocess.run(
            ["/bin/bash", "-n", "-c", command],
            cwd=vault,
            env=env,
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        if syntax.returncode != 0:
            statuses.append("BROKEN")
            details.append(f"hook command has invalid shell syntax: {_one_line(syntax.stderr)}")
            continue
        try:
            tokens = _shell_tokens(command)
        except ValueError as exc:
            statuses.append("BROKEN")
            details.append(f"hook command cannot be parsed: {_one_line(exc)}")
            continue
        for unresolved in _unresolved_hook_targets(tokens):
            statuses.append("UNKNOWN")
            details.append(f"hook target contains an unresolved variable: {unresolved}")
        for executable in _hook_executables(tokens):
            if "$" in executable or "`" in executable:
                statuses.append("UNKNOWN")
                details.append(f"hook executable cannot be resolved structurally: {executable}")
                continue
            executable_path = Path(executable)
            if executable_path.is_absolute() or "/" in executable:
                candidate = executable_path if executable_path.is_absolute() else vault / executable_path
                if not candidate.is_file() or not os.access(candidate, os.X_OK):
                    statuses.append("BROKEN")
                    details.append(f"hook executable is missing or not executable: {executable}")
            elif executable not in shell_builtins and shutil.which(executable, path=env.get("PATH")) is None:
                if executable == "node" and _node_from_clean_environment(env) is not None:
                    continue
                statuses.append("UNKNOWN")
                details.append(f"hook executable is unavailable: {executable}")

        for index, target in _hook_script_targets(command, vault):
            if target in checked_targets:
                continue
            checked_targets.add(target)
            if not target.is_file():
                statuses.append("BROKEN")
                details.append(f"hook target is missing: {target}")
                continue
            if (index == 0 or target.suffix == ".sh") and not os.access(target, os.X_OK):
                statuses.append("BROKEN")
                details.append(f"hook target is not executable: {target}")
                continue
            try:
                target.resolve().relative_to(vault.resolve())
            except ValueError:
                statuses.append("UNKNOWN")
                details.append(f"external hook target was not syntax-checked: {target}")
                continue
            if target.is_symlink():
                statuses.append("UNKNOWN")
                details.append(f"symlinked hook target was not syntax-checked: {target}")
                continue
            verdict, detail = _syntax_check(target, env, vault)
            statuses.append(verdict)
            if detail:
                details.append(detail)

    if not statuses:
        statuses.append("OK")
    verdict = _roll_up(statuses)
    if details:
        return {"verdict": verdict, "detail": "; ".join(details)}
    return {"verdict": verdict, "detail": f"structurally validated {len(commands)} hook commands"}


INTERNAL_JOURNEYS: dict[str, Callable[[Path, Path], dict[str, str]]] = {
    "configs": _journey_configs,
    "task_lifecycle": _journey_task_lifecycle,
    "mcp_startup": _journey_mcp_startup,
    "skills": _journey_skills,
    "hooks": _journey_hooks,
}


def _print_human(report: Mapping[str, object]) -> None:
    for journey in report["journeys"]:
        print(
            f"[{journey['verdict']}] {journey['id']} "
            f"({journey['duration_ms']}ms) — {journey['detail']}"
        )


def _atomic_write(path: Path, content: str) -> None:
    """Durably replace one ledger file without exposing partial JSON."""
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
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def _dex_version(repo_root: Path) -> str:
    package = json.loads((repo_root / "package.json").read_text(encoding="utf-8"))
    version = package.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("package.json has no Dex version")
    return version


def _write_ledger(report: Mapping[str, object], vault_root: Path, repo_root: Path) -> None:
    """Persist the latest report and capped, versioned smoke history."""
    last_run_path = vault_root / "System" / ".smoke-last-run.json"
    history_path = vault_root / "System" / ".dex" / "smoke-history.jsonl"
    entry = dict(report)
    entry["dex_version"] = _dex_version(repo_root)

    history: list[str] = []
    try:
        history = [line for line in history_path.read_text(encoding="utf-8").splitlines() if line]
    except FileNotFoundError:
        pass
    history.append(json.dumps(entry, separators=(",", ":")))
    history = history[-HISTORY_LIMIT:]

    _atomic_write(last_run_path, json.dumps(report, indent=2) + "\n")
    _atomic_write(history_path, "\n".join(history) + "\n")


def main(
    argv: Sequence[str] | None = None,
    *,
    vault_root: Path | None = None,
    repo_root: Path | None = None,
    journey_definitions: Sequence[JourneyDefinition] = JOURNEYS,
) -> int:
    parser = argparse.ArgumentParser(description="Run Dex's safe, isolated smoke journeys.")
    parser.add_argument("--json", action="store_true", help="emit the versioned JSON report")
    parser.add_argument("--ledger", action="store_true", help="record the latest run and history")
    parser.add_argument(
        "--check-mcp-once",
        metavar="CUSTOM_NAME",
        help="run one explicitly approved custom local Python startup check",
    )
    parser.add_argument(
        "--issue-mcp-once-consent",
        metavar="CUSTOM_NAME",
        help="issue a fresh single-use token after explicit user approval",
    )
    parser.add_argument("--consent-token", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--_journey", choices=tuple(INTERNAL_JOURNEYS), help=argparse.SUPPRESS)
    parser.add_argument("--_prepare", choices=tuple(INTERNAL_JOURNEYS), help=argparse.SUPPRESS)
    parser.add_argument("--source-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--vault-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--repo-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--release-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--release-ref", help=argparse.SUPPRESS)
    parser.add_argument("--run-marker", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.issue_mcp_once_consent:
        if args.check_mcp_once or args.consent_token is not None:
            parser.error("--issue-mcp-once-consent cannot be combined with a check")
        try:
            token = issue_mcp_once_consent_token(args.issue_mcp_once_consent)
        except (OSError, ValueError) as exc:
            print(f"UNKNOWN: could not issue one-off consent token: {_one_line(exc)}")
            return 1
        print(token)
        return 0

    if args.consent_token is not None and not args.check_mcp_once:
        parser.error("--consent-token requires --check-mcp-once")

    if args.check_mcp_once:
        source = (vault_root or Path(os.environ.get("VAULT_PATH", Path.cwd()))).resolve()
        result = check_custom_mcp_once(
            source,
            args.check_mcp_once,
            consent_token=args.consent_token,
        )
        print(f"{result['verdict']}: {result['detail']}")
        return 0 if result["verdict"] == "OK" else 1

    if args._prepare:
        if args.source_root is None or args.vault_root is None:
            print("smoke preparation requires source and temp vault paths", file=sys.stderr)
            return 2
        try:
            _authorize_internal(args.vault_root, args.run_marker)
            _block_python_network()
            repository = (args.repo_root or Path(__file__).resolve().parents[2]).resolve()
            release_root = _internal_release_root(args.run_marker, args.release_root)
            _prepare_vault(
                args._prepare,
                args.source_root.resolve(),
                repository,
                args.vault_root.resolve(),
                release_root if release_root.is_dir() else None,
                args.release_ref,
            )
        except JourneyNotSetUp as exc:
            result = {"verdict": "OFF", "detail": _one_line(exc)}
        except JourneyPreparationError as exc:
            result = {"verdict": "BROKEN", "detail": _one_line(exc)}
        except JourneySafetySkip as exc:
            result = {"verdict": "UNKNOWN", "detail": _one_line(exc)}
        except ModuleNotFoundError:
            result = {"verdict": "UNKNOWN", "detail": MISSING_PACKAGES_DETAIL}
        except (OSError, PermissionError) as exc:
            print(f"smoke preparation refused: {_one_line(exc)}", file=sys.stderr)
            return 2
        else:
            result = {"verdict": "OK", "detail": "journey vault prepared safely"}
        print(json.dumps(result, separators=(",", ":")))
        return 0

    if args._journey:
        try:
            vault = Path(os.environ["VAULT_PATH"]).resolve()
            _authorize_internal(vault, args.run_marker)
            _block_python_network()
            release_root = _internal_release_root(args.run_marker, args.release_root)
            result = INTERNAL_JOURNEYS[args._journey](vault, release_root)
        except ModuleNotFoundError:
            result = {"verdict": "UNKNOWN", "detail": MISSING_PACKAGES_DETAIL}
        except (KeyError, OSError, PermissionError) as exc:
            print(f"internal smoke journey refused: {_one_line(exc)}", file=sys.stderr)
            return 2
        print(json.dumps(result, separators=(",", ":")))
        return 0

    run = run_smoke(
        vault_root=vault_root,
        repo_root=repo_root,
        journey_definitions=journey_definitions,
    )
    if args.ledger:
        source = (vault_root or Path(os.environ.get("VAULT_PATH", Path.cwd()))).resolve()
        repository = (repo_root or Path(__file__).resolve().parents[2]).resolve()
        try:
            _write_ledger(run.report, source, repository)
        except Exception as exc:
            print(f"smoke ledger write failed: {_one_line(exc)}", file=sys.stderr)
            return 2
    if args.json:
        print(json.dumps(run.report, separators=(",", ":")))
    else:
        _print_human(run.report)
    return run.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
