#!/usr/bin/env python3
"""Collect an honest, machine-readable health report for Dex."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import plistlib
import py_compile
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core import paths
from core.utils import preflight

VERDICTS = frozenset({"OK", "OFF", "BROKEN", "UNKNOWN"})
DOCTOR_SAFE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
DOCTOR_GIT_CANDIDATES = (Path("/usr/bin/git"), Path("/bin/git"))
MISSING_PACKAGES_DETAIL = (
    "Python packages not installed — run /dex-update (or pip install -r requirements.txt) "
    "then re-run /dex-doctor"
)


@dataclass(frozen=True)
class CheckDefinition:
    """A stable registry entry for one collector probe."""

    id: str
    feature: str
    probe: str


@dataclass(frozen=True)
class Heal:
    """A safe-heal result or a higher-tier suggestion."""

    tier: int
    action: str
    applied: bool = False


@dataclass(frozen=True)
class ProbeResult:
    """The normalized outcome of one probe."""

    verdict: str
    detail: str
    heal: Heal | None = None

    def __post_init__(self) -> None:
        if self.verdict not in VERDICTS:
            raise ValueError(f"Invalid doctor verdict: {self.verdict}")


@dataclass(frozen=True)
class JobFreshness:
    """The application log and allowed age for one installed job."""

    log_path: Path
    max_age: timedelta


@dataclass(frozen=True)
class DoctorContext:
    """Filesystem and clock inputs for deterministic collector runs."""

    vault_root: Path
    repo_root: Path
    home: Path
    now: datetime

    @classmethod
    def from_environment(cls) -> "DoctorContext":
        return cls(
            vault_root=paths.VAULT_ROOT.resolve(),
            repo_root=paths.VAULT_ROOT.resolve(),
            home=Path.home(),
            now=datetime.now(timezone.utc),
        )

    def core_path(self, constant_name: str) -> Path:
        """Retarget a core.paths constant to this context's vault root."""
        configured = getattr(paths, constant_name)
        relative = configured.relative_to(paths.VAULT_ROOT)
        return self.vault_root / relative

    @property
    def last_run_path(self) -> Path:
        return self.core_path("SYSTEM_DIR") / ".doctor-last-run.json"

    @property
    def paths_json_path(self) -> Path:
        return self.repo_root / "core" / "paths.json"

    @property
    def launch_agents_dir(self) -> Path:
        return self.home / "Library" / "LaunchAgents"


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

# Keep in sync with .claude/hooks/session-start.sh's background-job staleness table.
JOB_FRESHNESS = {
    "com.dex.meeting-intel": JobFreshness(
        Path(".scripts/logs/meeting-intel.log"),
        timedelta(hours=48),
    ),
    "com.dex.changelog-checker": JobFreshness(
        Path(".scripts/logs/changelog-checker.log"),
        timedelta(days=7),
    ),
    "com.dex.learning-review": JobFreshness(
        Path(".scripts/logs/learning-review.log"),
        timedelta(days=7),
    ),
}

# Ownership includes every launch agent this repo can install; only some emit freshness logs.
SHIPPED_LAUNCH_AGENT_LABELS = frozenset(
    {
        "com.dex.changelog-checker",
        "com.dex.learning-review",
        "com.dex.meeting-intel",
        "com.dex.obsidian-sync",
    }
)


QUICK_CHECKS = (
    CheckDefinition("vault.structure", "Vault structure", "_probe_vault_structure"),
    CheckDefinition("vault.configs", "Vault configuration", "_probe_vault_configs"),
    CheckDefinition("vault.git", "Vault history", "_probe_vault_git"),
    CheckDefinition("brain.git", "Dex brain history", "_probe_brain_git"),
    CheckDefinition("schema.match", "Brain and vault compatibility", "_probe_schema_match"),
    CheckDefinition("vault.auto-commit", "Vault auto-commit", "_probe_vault_auto_commit"),
    CheckDefinition(
        "topology.migration-pending",
        "Brain/vault topology",
        "_probe_migration_pending",
    ),
    CheckDefinition("mcp.registered", "MCP registration", "_probe_mcp_registered"),
    CheckDefinition("mcp.orphans", "MCP server registration", "_probe_mcp_orphans"),
    CheckDefinition("python.env", "Python environment", "_probe_python_env"),
    CheckDefinition("hooks.wired", "Claude hooks", "_probe_hooks_wired"),
    CheckDefinition("jobs.loaded", "Background jobs", "_probe_jobs_loaded"),
    CheckDefinition("jobs.fresh", "Background job freshness", "_probe_jobs_fresh"),
    CheckDefinition("preflight.queue", "Preflight health", "_probe_preflight_queue"),
    CheckDefinition("entity.engine", "Entity engine", "_probe_entity_engine"),
    CheckDefinition(
        "customizations.skills",
        "Skill customizations",
        "_probe_customization_skills",
    ),
    CheckDefinition(
        "customizations.mcp",
        "MCP customizations",
        "_probe_customization_mcp",
    ),
    CheckDefinition("core.drift", "Shipped-file drift", "_probe_core_drift"),
    CheckDefinition("doctor.self", "Doctor instruments", "_probe_doctor_self"),
)

DEEP_CHECKS = (
    CheckDefinition("granola.query_path", "Granola meeting sync", "_probe_granola_query_path"),
    CheckDefinition("calendar.access", "Calendar access", "_probe_calendar_access"),
    CheckDefinition("qmd.live", "Semantic search", "_probe_qmd_live"),
    CheckDefinition("integrations.enabled", "Enabled integrations", "_probe_integrations_enabled"),
    CheckDefinition("mcp.importable", "MCP imports", "_probe_mcp_importable"),
    CheckDefinition("smoke.journeys", "End-to-end smoke journeys", "_probe_smoke_journeys"),
)


def _one_line(value: object) -> str:
    return " ".join(str(value).split()) or value.__class__.__name__


def _sentence(value: object) -> str:
    detail = _one_line(value)
    if detail[-1] not in ".?!":
        detail += "."
    return detail


def _actionable_probe_error(error: Exception) -> str:
    detail = _one_line(error)
    if _is_missing_package_error(error, detail):
        return MISSING_PACKAGES_DETAIL
    return detail


def _is_missing_package_error(value: object, detail: str | None = None) -> bool:
    rendered = detail or _one_line(value)
    return isinstance(value, ModuleNotFoundError) or any(
        marker in rendered for marker in ("ModuleNotFoundError", "No module named")
    )


def _load_yaml(path: Path) -> object:
    """Load YAML lazily so a broken venv can still produce a doctor report."""
    import yaml

    return yaml.safe_load(path.read_text())


def _result_json(definition: CheckDefinition, result: ProbeResult) -> dict[str, Any]:
    detail = _sentence(result.detail)
    return {
        "id": definition.id,
        "feature": definition.feature,
        "verdict": result.verdict,
        "detail": detail,
        "heal": asdict(result.heal) if result.heal else None,
        "success": result.verdict == "OK",
        "feature_status": result.verdict.lower(),
        "user_message": detail,
    }


def _summary(checks: list[dict[str, Any]]) -> dict[str, int]:
    return {
        verdict.lower(): sum(check["verdict"] == verdict for check in checks)
        for verdict in ("OK", "OFF", "BROKEN", "UNKNOWN")
    }


def _repair_count_word(count: int) -> str:
    return {1: "one", 2: "two", 3: "three"}.get(count, str(count))


def _paths_export_for(context: DoctorContext) -> dict[str, str]:
    """Reuse core.paths' export and retarget it for an injected test vault."""
    exported = paths.export_json()
    retargeted: dict[str, str] = {}
    for name, raw_path in exported.items():
        configured = Path(raw_path)
        try:
            relative = configured.relative_to(paths.VAULT_ROOT)
        except ValueError:
            retargeted[name] = raw_path
        else:
            retargeted[name] = str(context.vault_root / relative)
    return retargeted


def _repo_shipped_executables(context: DoctorContext) -> list[Path]:
    """Return files marked executable in the repository's Git index."""
    result = subprocess.run(
        ["git", "-C", str(context.repo_root), "ls-files", "--stage", "-z"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git could not inspect shipped script modes")

    executable_paths = []
    for record in result.stdout.split("\0"):
        if not record or "\t" not in record:
            continue
        metadata, relative = record.split("\t", 1)
        mode = metadata.split(" ", 1)[0]
        if mode == "100755":
            executable_paths.append(context.repo_root / relative)
    return executable_paths


def _apply_t1_heals(context: DoctorContext) -> tuple[list[str], list[str]]:
    """Apply the collector's safe, idempotent repair set."""
    actions: list[str] = []
    errors: list[str] = []

    missing_directories = [context.core_path(name) for name in PARA_PATH_NAMES if not context.core_path(name).is_dir()]
    if missing_directories:
        created = []
        for directory in missing_directories:
            try:
                directory.mkdir(parents=True, exist_ok=True)
                created.append(directory)
            except OSError as error:
                errors.append(f"Directory heal failed for {directory.name}: {_one_line(error)}")
        if created:
            names = ", ".join(directory.name for directory in created)
            actions.append(f"Created {names}")

    try:
        expected_paths = _paths_export_for(context)
        current_paths: object = None
        try:
            current_paths = json.loads(context.paths_json_path.read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        if current_paths != expected_paths:
            context.paths_json_path.parent.mkdir(parents=True, exist_ok=True)
            context.paths_json_path.write_text(json.dumps(expected_paths, indent=2) + "\n")
            actions.append("regenerated core/paths.json")
    except Exception as error:
        errors.append(f"Path-export heal failed: {_one_line(error)}")

    restored = []
    try:
        shipped_executables = _repo_shipped_executables(context)
    except Exception as error:
        errors.append(f"Executable-mode heal failed: {_one_line(error)}")
        shipped_executables = []
    for script in shipped_executables:
        try:
            if not script.is_file() or script.stat().st_mode & 0o111:
                continue
            script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
            try:
                restored.append(str(script.relative_to(context.repo_root)))
            except ValueError:
                restored.append(str(script))
        except OSError as error:
            errors.append(f"Executable-mode heal failed for {script}: {_one_line(error)}")
    if restored:
        noun = "permission" if len(restored) == 1 else "permissions"
        actions.append(f"restored executable {noun} on {', '.join(restored)}")

    return actions, errors


def _write_last_run(report: dict[str, Any], context: DoctorContext) -> None:
    serialized = json.dumps(report, indent=2) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=context.last_run_path.parent,
            prefix=".doctor-last-run.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, context.last_run_path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def collect(
    *,
    deep: bool = False,
    heal: bool = False,
    context: DoctorContext | None = None,
) -> dict[str, Any]:
    """Run the selected registry and return its JSON-serializable report."""
    context = context or DoctorContext.from_environment()
    definitions = [*QUICK_CHECKS, *DEEP_CHECKS] if deep else list(QUICK_CHECKS)
    results: dict[str, ProbeResult] = {}
    failed: list[dict[str, str]] = []

    t1_actions: list[str] = []
    if heal:
        try:
            t1_actions, t1_errors = _apply_t1_heals(context)
            if t1_errors:
                failed.append({"id": "doctor.self", "error": "; ".join(t1_errors)})
        except Exception as error:
            failed.append({"id": "doctor.self", "error": _one_line(error)})

    for definition in definitions:
        if definition.id == "doctor.self":
            continue
        try:
            result = globals()[definition.probe](context)
        except Exception as error:
            error_text = _actionable_probe_error(error)
            failed.append({"id": definition.id, "error": error_text})
            result = ProbeResult(
                "UNKNOWN",
                error_text
                if error_text == MISSING_PACKAGES_DETAIL
                else f"The {definition.feature} probe could not run: {error_text}",
            )
        if result.verdict == "UNKNOWN" and _is_missing_package_error(result.detail):
            result = ProbeResult("UNKNOWN", MISSING_PACKAGES_DETAIL, result.heal)
        if definition.id == "vault.structure" and t1_actions:
            action = "; ".join(t1_actions) + "."
            if result.verdict == "OK":
                repair_word = _repair_count_word(len(t1_actions))
                repair_noun = "repair" if len(t1_actions) == 1 else "repairs"
                detail = f"All standard PARA directories exist after {repair_word} safe {repair_noun}"
            else:
                detail = f"{result.detail.rstrip('.')} while safe Tier-1 repairs were also applied"
            result = ProbeResult(
                result.verdict,
                detail,
                Heal(tier=1, action=action, applied=True),
            )
        results[definition.id] = result

    if failed:
        failed_ids = ", ".join(failure["id"] for failure in failed)
        self_result = ProbeResult(
            "BROKEN",
            f"The doctor could not complete these instruments: {failed_ids}",
        )
    else:
        self_result = ProbeResult(
            "OK",
            f"All {len(definitions)} probes completed and the last-run report target is writable",
        )
    results["doctor.self"] = self_result

    checks = [_result_json(definition, results[definition.id]) for definition in definitions]
    report = {
        "generated_at": context.now.isoformat(),
        "mode": "deep" if deep else "quick",
        "instruments": {
            "attempted": len(definitions),
            "completed": len(definitions) - len(failed),
            "failed": failed,
        },
        "checks": checks,
        "summary": _summary(checks),
    }

    try:
        _write_last_run(report, context)
    except Exception as error:
        error_text = _one_line(error)
        if not any(failure["id"] == "doctor.self" for failure in failed):
            failed.append({"id": "doctor.self", "error": error_text})
        report["instruments"] = {
            "attempted": len(definitions),
            "completed": len(definitions) - len(failed),
            "failed": failed,
        }
        results["doctor.self"] = ProbeResult(
            "BROKEN",
            f"The doctor could not write System/.doctor-last-run.json: {error_text}",
        )
        report["checks"] = [_result_json(definition, results[definition.id]) for definition in definitions]
        report["summary"] = _summary(report["checks"])

    return report


@contextmanager
def _vault_environment(context: DoctorContext) -> Iterator[None]:
    previous = {name: os.environ.get(name) for name in ("VAULT_PATH", "VAULT_ROOT")}
    os.environ["VAULT_PATH"] = str(context.vault_root)
    os.environ["VAULT_ROOT"] = str(context.vault_root)
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _probe_vault_structure(context: DoctorContext) -> ProbeResult:
    missing = [context.core_path(name).name for name in PARA_PATH_NAMES if not context.core_path(name).is_dir()]
    if missing:
        return ProbeResult(
            "BROKEN",
            f"Missing standard PARA directories: {', '.join(missing)}",
            Heal(tier=1, action=f"Create the missing directories: {', '.join(missing)}.", applied=False),
        )
    return ProbeResult("OK", "All standard PARA directories exist")


def _probe_vault_configs(context: DoctorContext) -> ProbeResult:
    config_files = (
        (context.core_path("USER_PROFILE_FILE"), "yaml"),
        (context.core_path("PILLARS_FILE"), "yaml"),
        (context.vault_root / ".claude" / "settings.json", "json"),
    )
    failures = []
    for config_path, kind in config_files:
        if not config_path.is_file():
            failures.append(f"{config_path.name} is missing")
            continue
        try:
            if kind == "yaml":
                parsed = _load_yaml(config_path)
            else:
                parsed = json.loads(config_path.read_text())
            if parsed is not None and not isinstance(parsed, dict):
                raise ValueError("top level must be an object")
        except ImportError:
            raise
        except Exception as error:
            failures.append(f"{config_path.name} could not be parsed ({_one_line(error)})")
    if failures:
        return ProbeResult(
            "BROKEN",
            "; ".join(failures),
            Heal(tier=3, action="Repair the named configuration file by hand.", applied=False),
        )
    return ProbeResult("OK", "user-profile.yaml, pillars.yaml, and .claude/settings.json all parse")


def _mcp_config_path(context: DoctorContext) -> Path:
    with _vault_environment(context):
        return preflight.get_mcp_config_path()


def _load_mcp_config(context: DoctorContext) -> dict[str, Any]:
    loaded = json.loads(_mcp_config_path(context).read_text())
    if (
        not isinstance(loaded, dict)
        or "mcpServers" not in loaded
        or not isinstance(loaded["mcpServers"], dict)
    ):
        raise ValueError(".mcp.json must contain an mcpServers object")
    return loaded


def _with_mcp_config_note(context: DoctorContext, detail: str) -> str:
    legacy_path = context.vault_root / "System" / ".mcp.json"
    if _mcp_config_path(context) == legacy_path:
        return f"{detail} (using legacy System/.mcp.json because root .mcp.json is absent)"
    return detail


def _expand_path_token(token: str, context: DoctorContext) -> str:
    expanded = token.replace("{{VAULT_PATH}}", str(context.vault_root))
    expanded = expanded.replace("__VAULT_PATH__", str(context.vault_root))
    expanded = expanded.replace("${CLAUDE_PROJECT_DIR}", str(context.vault_root))
    expanded = expanded.replace("$CLAUDE_PROJECT_DIR", str(context.vault_root))
    return os.path.expanduser(os.path.expandvars(expanded))


def _local_target(token: object, context: DoctorContext, *, command: bool = False) -> Path | None:
    if not isinstance(token, str) or not token or token.startswith("-") or "://" in token:
        return None
    expanded = _expand_path_token(token, context)
    suffixes = {".py", ".js", ".cjs", ".mjs", ".sh"}
    if command:
        if "/" not in expanded and not expanded.startswith((".", "~")):
            return None
    elif Path(expanded).suffix not in suffixes:
        return None
    path = Path(expanded)
    return path if path.is_absolute() else context.vault_root / path


def _entry_targets(entry: object, context: DoctorContext) -> list[Path]:
    if not isinstance(entry, dict):
        raise ValueError("each MCP entry must be an object")
    targets = []
    command_target = _local_target(entry.get("command"), context, command=True)
    if command_target:
        targets.append(command_target)
    args = entry.get("args", [])
    if not isinstance(args, list):
        raise ValueError("each MCP args value must be a list")
    for argument in args:
        target = _local_target(argument, context)
        if target:
            targets.append(target)
    return targets


def _registered_core_scripts(context: DoctorContext, config: dict[str, Any]) -> dict[str, tuple[Path, str]]:
    registered = {}
    for name, entry in config.get("mcpServers", {}).items():
        if not isinstance(entry, dict):
            continue
        interpreter = _expand_path_token(str(entry.get("command", sys.executable)), context)
        for target in _entry_targets(entry, context):
            try:
                relative = target.resolve().relative_to((context.vault_root / "core" / "mcp").resolve())
            except ValueError:
                continue
            if len(relative.parts) == 1 and target.name.endswith("_server.py"):
                registered[name] = (target, interpreter)
                break
    return registered


def _probe_mcp_registered(context: DoctorContext) -> ProbeResult:
    config_path = _mcp_config_path(context)
    if not config_path.exists():
        if not context.core_path("MARKER_FILE").exists():
            return ProbeResult("OFF", ".mcp.json is absent because onboarding has not completed")
        return ProbeResult(
            "BROKEN",
            ".mcp.json is missing after onboarding completed",
            Heal(tier=2, action="Restore .mcp.json from the shipped example.", applied=False),
        )
    try:
        config = _load_mcp_config(context)
        missing = []
        for name, entry in config["mcpServers"].items():
            if not isinstance(entry, dict):
                raise ValueError(f"{name} must contain an object")
            serialized_entry = json.dumps(entry)
            if any(marker in serialized_entry for marker in ("{{VAULT_PATH}}", "{{NODE_PATH}}", "__VAULT_PATH__")):
                missing.append(f"{name} -> live config contains unresolved template values")
                continue
            remote_type = entry.get("type") in {"http", "sse", "streamable-http"} or "url" in entry
            if remote_type:
                url = entry.get("url")
                if not isinstance(url, str) or not url.startswith(("https://", "http://")):
                    raise ValueError(f"{name} must define a valid remote URL")
                continue
            if not isinstance(entry.get("command"), str) or not entry["command"]:
                raise ValueError(f"{name} must define a command string")
            expanded_command = _expand_path_token(entry["command"], context)
            command_target = _local_target(entry["command"], context, command=True)
            if command_target and command_target.is_file() and not os.access(command_target, os.X_OK):
                missing.append(f"{name} -> command {command_target} is not executable")
            elif command_target is None and not shutil.which(expanded_command):
                missing.append(f"{name} -> command {expanded_command}")
            for target in _entry_targets(entry, context):
                if not target.is_file():
                    missing.append(f"{name} -> {target}")
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return ProbeResult(
            "BROKEN",
            _with_mcp_config_note(context, f".mcp.json is invalid: {_one_line(error)}"),
            Heal(tier=3, action="Repair .mcp.json by hand while preserving user-added servers.", applied=False),
        )
    if missing:
        return ProbeResult(
            "BROKEN",
            _with_mcp_config_note(context, f"Registered MCP targets are missing: {', '.join(missing)}"),
            Heal(tier=2, action="Repair the missing MCP target paths in .mcp.json.", applied=False),
        )
    return ProbeResult(
        "OK",
        _with_mcp_config_note(
            context,
            f"All {len(config['mcpServers'])} registered MCP entries have valid targets",
        ),
    )


def _probe_mcp_orphans(context: DoctorContext) -> ProbeResult:
    server_dir = context.vault_root / "core" / "mcp"
    shipped = {path.resolve(): path for path in server_dir.glob("*_server.py") if path.is_file()}
    try:
        config = _load_mcp_config(context)
    except FileNotFoundError:
        config = {"mcpServers": {}}
    registered = {
        target.resolve()
        for entry in config["mcpServers"].values()
        for target in _entry_targets(entry, context)
    }
    orphans = [path.name for resolved, path in shipped.items() if resolved not in registered]
    if orphans:
        return ProbeResult(
            "BROKEN",
            _with_mcp_config_note(
                context,
                f"Core MCP servers are not registered: {', '.join(sorted(orphans))}",
            ),
            Heal(tier=2, action="Add the orphaned core MCP servers to .mcp.json.", applied=False),
        )
    return ProbeResult(
        "OK",
        _with_mcp_config_note(context, f"All {len(shipped)} core MCP server files are registered"),
    )


def _python_import_check(python: Path) -> tuple[bool, list[str]]:
    code = """import importlib
import json

names = ["mcp", "yaml", "dateutil", "requests"]
missing = []
for name in names:
    try:
        importlib.import_module(name)
    except Exception:
        missing.append(name)
print(json.dumps(missing))
"""
    result = subprocess.run(
        [str(python), "-c", code],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if result.returncode != 0:
        return False, [_one_line(result.stderr or result.stdout or f"exit {result.returncode}")]
    return (lambda missing: (not missing, missing))(json.loads(result.stdout))


def _probe_python_env(context: DoctorContext) -> ProbeResult:
    python = context.vault_root / ".venv" / "bin" / "python"
    if not python.is_file() or not os.access(python, os.X_OK):
        return ProbeResult(
            "BROKEN",
            f"The vault Python interpreter is missing or not executable at {python}",
            Heal(tier=2, action="Recreate the vault .venv and install its requirements.", applied=False),
        )
    importable, missing = _python_import_check(python)
    if not importable:
        return ProbeResult(
            "BROKEN",
            f"The vault Python environment cannot import: {', '.join(missing)}",
            Heal(tier=2, action="Install the missing packages into the vault .venv.", applied=False),
        )
    return ProbeResult("OK", "The vault Python and required packages are importable")


def _walk_hook_commands(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "command" and isinstance(child, str):
                yield child
            else:
                yield from _walk_hook_commands(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_hook_commands(child)


def _hook_targets(command: str, context: DoctorContext) -> list[Path]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    targets = []
    for index, token in enumerate(tokens):
        expanded = _expand_path_token(token, context)
        if any(marker in expanded for marker in (">", "<", "|")):
            continue
        candidate = _local_target(expanded, context, command=index == 0)
        if candidate and (index == 0 or candidate.suffix in {".py", ".js", ".cjs", ".mjs", ".sh"}):
            targets.append(candidate)
    return targets


def _missing_hook_executable(command: str, context: DoctorContext) -> str | None:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()
    if not tokens:
        return None
    executable = _expand_path_token(tokens[0], context)
    if _local_target(executable, context, command=True) is not None:
        return None
    shell_builtins = {"cd", "echo", "export", "false", "printf", "source", "test", "true"}
    if executable in shell_builtins or shutil.which(executable):
        return None
    return executable


def _probe_hooks_wired(context: DoctorContext) -> ProbeResult:
    settings_path = context.vault_root / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text())
    if not isinstance(settings, dict):
        raise ValueError(".claude/settings.json must contain an object")
    hooks = settings.get("hooks", {})
    missing = []
    for command in _walk_hook_commands(hooks):
        missing_executable = _missing_hook_executable(command, context)
        if missing_executable:
            missing.append(f"command executable '{missing_executable}'")
        missing.extend(str(target) for target in _hook_targets(command, context) if not target.is_file())
    if missing:
        return ProbeResult(
            "BROKEN",
            f"Hook commands point at missing files: {', '.join(sorted(set(missing)))}",
            Heal(tier=2, action="Repair the dangling hook command paths.", applied=False),
        )
    return ProbeResult("OK", "Every configured hook command points at an existing file")


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _installed_launch_agents(context: DoctorContext) -> list[Path]:
    return sorted(context.launch_agents_dir.glob("com.dex.*.plist"))


def _plist_data(plist: Path) -> dict[str, Any]:
    try:
        with plist.open("rb") as handle:
            loaded = plistlib.load(handle)
    except PermissionError:
        raise
    except (OSError, plistlib.InvalidFileException) as error:
        raise RuntimeError(f"Could not parse {plist.name}: {_one_line(error)}") from error
    if not isinstance(loaded, dict):
        raise RuntimeError(f"Could not parse {plist.name}: top level is not a dictionary")
    return loaded


def _plist_label(plist: Path) -> str:
    return str(_plist_data(plist).get("Label") or plist.stem)


def _plist_strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _plist_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _plist_strings(child)


def _plist_owned_by_vault(plist: Path, data: dict[str, Any], context: DoctorContext) -> bool:
    label = str(data.get("Label") or plist.stem)
    if label in SHIPPED_LAUNCH_AGENT_LABELS:
        return True
    arguments = data.get("ProgramArguments")
    if not isinstance(arguments, list):
        return False
    vault_root = context.vault_root.resolve()
    for argument in arguments:
        if not isinstance(argument, str):
            continue
        candidate = Path(argument).expanduser()
        if not candidate.is_absolute():
            continue
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_relative_to(vault_root):
            return True
    return False


def _with_skipped_launch_agents(detail: str, skipped_count: int) -> str:
    if not skipped_count:
        return detail
    if skipped_count == 1:
        note = "1 Dex launch agent from another Dex product was skipped"
    else:
        note = f"{skipped_count} Dex launch agents from other Dex products were skipped"
    return f"{detail}; {note}"


def _plist_configuration_issue(plist: Path, data: dict[str, Any], context: DoctorContext) -> str | None:
    arguments = data.get("ProgramArguments")
    if not isinstance(arguments, list) or not arguments or not isinstance(arguments[0], str):
        return f"{plist.name} has no valid ProgramArguments[0]"
    markers = ("{{", "}}", "__VAULT_PATH__", "__HOME__")
    if any(any(marker in value for marker in markers) for value in _plist_strings(data)):
        return f"{plist.name} still contains unsubstituted template values"
    for argument in arguments[1:]:
        target = _local_target(argument, context)
        if target and not target.is_file():
            return f"{plist.name} points at missing program file {target}"
    working_directory = data.get("WorkingDirectory")
    if isinstance(working_directory, str):
        expanded = Path(_expand_path_token(working_directory, context))
        if not expanded.is_absolute():
            expanded = context.vault_root / expanded
        if not expanded.is_dir():
            return f"{plist.name} points at missing working directory {expanded}"
    return None


def _plist_interpreter(plist: Path) -> str:
    result = subprocess.run(
        ["plutil", "-extract", "ProgramArguments.0", "raw", str(plist)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raw_detail = result.stderr.strip() or result.stdout.strip()
        if not raw_detail:
            raise PermissionError(f"plutil could not run while checking {plist.name}")
        detail = raw_detail
        if _looks_like_sandbox_failure(detail):
            raise PermissionError(detail)
        raise RuntimeError(detail)
    return result.stdout.strip()


def _launchctl_domain_check() -> None:
    result = subprocess.run(
        ["launchctl", "list"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        detail = _one_line(result.stderr or result.stdout or "launchctl list is unavailable in this environment")
        raise PermissionError(detail)


def _launchctl_status(label: str) -> dict[str, int | bool | None]:
    result = subprocess.run(
        ["launchctl", "list", label],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    combined = _one_line(f"{result.stdout} {result.stderr}")
    if result.returncode != 0:
        if _looks_like_sandbox_failure(combined):
            raise PermissionError(combined)
        return {"loaded": False, "last_exit_status": None}
    match = re.search(r"LastExitStatus\D+(-?\d+)", result.stdout)
    return {
        "loaded": True,
        "last_exit_status": int(match.group(1)) if match else None,
    }


def _resolved_interpreter(raw: str, context: DoctorContext) -> str | None:
    expanded = _expand_path_token(raw, context)
    if "/" not in expanded:
        return shutil.which(expanded)
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = context.vault_root / candidate
    return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None


def _probe_jobs_loaded(context: DoctorContext) -> ProbeResult:
    plists = _installed_launch_agents(context)
    if not plists:
        return ProbeResult("OFF", "No com.dex launch agents are installed")
    if not _is_macos():
        return ProbeResult("UNKNOWN", "launchctl and plutil checks are only available on macOS")

    issues: list[tuple[int, str]] = []
    unknowns = []
    runtime_labels = []
    skipped_count = 0
    for plist in plists:
        try:
            data = _plist_data(plist)
        except RuntimeError as error:
            if plist.stem in SHIPPED_LAUNCH_AGENT_LABELS:
                issues.append((2, _one_line(error)))
            else:
                skipped_count += 1
            continue
        if not _plist_owned_by_vault(plist, data, context):
            skipped_count += 1
            continue
        label = str(data.get("Label") or plist.stem)
        configuration_issue = _plist_configuration_issue(plist, data, context)
        if configuration_issue:
            issues.append((2, f"{label} has invalid launch-agent configuration ({configuration_issue})"))
            continue
        try:
            raw_interpreter = _plist_interpreter(plist)
        except RuntimeError as error:
            issues.append((2, f"{label} has invalid launch-agent configuration ({_one_line(error)})"))
            continue
        if not _resolved_interpreter(raw_interpreter, context):
            issues.append((3, f"{label} interpreter is missing or not executable ({raw_interpreter})"))
            continue
        runtime_labels.append(label)

    if runtime_labels:
        try:
            _launchctl_domain_check()
        except Exception as error:
            if not issues:
                raise
            unknowns.append(f"launchctl state could not be checked ({_one_line(error)})")
        else:
            for label in runtime_labels:
                try:
                    status = _launchctl_status(label)
                except Exception as error:
                    unknowns.append(f"{label} launchctl state could not be checked ({_one_line(error)})")
                    continue
                if not status["loaded"]:
                    issues.append((2, f"{label} is installed but not loaded"))
                elif status["last_exit_status"] is None:
                    unknowns.append(f"{label} is loaded but has no observable LastExitStatus")
                elif status["last_exit_status"] != 0:
                    issues.append((2, f"{label} last exited with status {status['last_exit_status']}"))
    owned_count = len(plists) - skipped_count
    if not owned_count:
        return ProbeResult(
            "OFF",
            _with_skipped_launch_agents("No launch agents for this vault are installed", skipped_count),
        )
    if issues:
        tier = max(issue_tier for issue_tier, _detail in issues)
        action_parts = []
        if any(issue_tier == 3 for issue_tier, _detail in issues):
            action_parts.append("Install or repair the missing job interpreter by hand")
        if any(issue_tier == 2 for issue_tier, _detail in issues):
            action_parts.append("repair or reload the named launch agent only after explicit approval")
        detail_parts = [detail for _tier, detail in issues]
        detail_parts.extend(unknowns)
        return ProbeResult(
            "BROKEN",
            _with_skipped_launch_agents("; ".join(detail_parts), skipped_count),
            Heal(tier=tier, action="; then ".join(action_parts) + ".", applied=False),
        )
    if unknowns:
        return ProbeResult(
            "UNKNOWN",
            _with_skipped_launch_agents("; ".join(unknowns), skipped_count),
        )
    return ProbeResult(
        "OK",
        _with_skipped_launch_agents(
            f"All {owned_count} installed launch agents for this vault are loaded with valid interpreters",
            skipped_count,
        ),
    )


def _probe_jobs_fresh(context: DoctorContext) -> ProbeResult:
    installed = {_plist_label(plist) for plist in _installed_launch_agents(context)}
    monitored = [label for label in JOB_FRESHNESS if label in installed]
    if not monitored:
        return ProbeResult("OFF", "No monitored Dex freshness jobs are installed")

    stale = []
    for label in monitored:
        policy = JOB_FRESHNESS[label]
        log_path = context.vault_root / policy.log_path
        if not log_path.is_file():
            stale.append(f"{label} has no run log")
            continue
        modified = datetime.fromtimestamp(log_path.stat().st_mtime, tz=timezone.utc)
        if context.now.astimezone(timezone.utc) - modified > policy.max_age:
            stale.append(f"{label} last ran on {modified.date().isoformat()}")
    if stale:
        return ProbeResult(
            "BROKEN",
            "; ".join(stale),
            Heal(tier=2, action="Run the stale job once and inspect its application log.", applied=False),
        )
    return ProbeResult("OK", f"All {len(monitored)} installed job logs are within their freshness thresholds")


def _preflight_snapshot(context: DoctorContext) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with _vault_environment(context):
        health = preflight.run_preflight()
        queue_path = preflight.get_error_queue_path()
        queued = json.loads(queue_path.read_text()) if queue_path.exists() else []
    if not isinstance(queued, list):
        raise ValueError("the preflight error queue must contain a list")
    return health, queued


def _probe_preflight_queue(context: DoctorContext) -> ProbeResult:
    health, queued = _preflight_snapshot(context)
    server_errors = []
    core_server_names = set(preflight.SERVER_MODULES)
    try:
        core_server_names.update(_registered_core_scripts(context, _load_mcp_config(context)))
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        pass
    unknown_core_servers = []
    for name, result in health.get("servers", {}).items():
        if result.get("status") == "error":
            server_errors.append(result.get("humanError") or result.get("error") or f"{name} failed")
        elif result.get("status") == "unknown" and name in core_server_names:
            unknown_core_servers.append(name)
    queued_errors = [
        error.get("humanMessage") or error.get("message") or "queued background error"
        for error in queued
        if not error.get("acknowledged", False)
    ]
    problems = [*server_errors, *queued_errors]
    if problems:
        detail = f"Preflight reported: {'; '.join(str(problem) for problem in problems)}"
        if unknown_core_servers:
            detail += f"; preflight did not check: {', '.join(sorted(unknown_core_servers))}"
        return ProbeResult("BROKEN", detail)
    if unknown_core_servers:
        return ProbeResult(
            "UNKNOWN",
            f"Preflight did not check registered core servers: {', '.join(sorted(unknown_core_servers))}",
        )
    return ProbeResult("OK", "Preflight completed with no server or queued errors")


def _display_vault_path(context: DoctorContext, path: Path) -> str:
    try:
        return path.relative_to(context.vault_root).as_posix()
    except ValueError:
        return str(path)


def _unsafe_customization_path(context: DoctorContext, path: Path) -> str | None:
    """Return why *path* must not be read, without resolving symlinks."""
    try:
        relative = path.relative_to(context.vault_root)
    except ValueError:
        return "is outside the vault"
    if any(part in {"", ".", ".."} for part in relative.parts):
        return "contains an unsafe path component"
    if any(
        part.lower() == ".env"
        or part.lower().startswith(".env.")
        or "credential" in part.lower()
        for part in relative.parts
    ):
        return "is credential-sensitive"
    current = context.vault_root
    for part in relative.parts:
        current /= part
        if current.is_symlink():
            return "is symlinked"
    return None


def _probe_customization_skills(context: DoctorContext) -> ProbeResult:
    from core.utils.validators import validate_skill_frontmatter

    skills_root = context.vault_root / ".claude" / "skills"
    root_safety = _unsafe_customization_path(context, skills_root)
    if root_safety:
        relative = _display_vault_path(context, skills_root)
        return ProbeResult(
            "UNKNOWN",
            f"{relative} {root_safety} and was not read for safety; fix or remove {relative}",
        )
    skill_directories = sorted(
        (path for path in skills_root.iterdir() if path.is_symlink() or path.is_dir()),
        key=lambda path: path.name,
    ) if skills_root.is_dir() else []
    failures = []
    safety_findings = []
    custom_count = 0
    for skill_directory in skill_directories:
        skill_path = skill_directory / "SKILL.md"
        relative = _display_vault_path(context, skill_path)
        is_custom = skill_directory.name.endswith("-custom")
        custom_count += int(is_custom)
        safety_reason = _unsafe_customization_path(context, skill_path)
        if safety_reason:
            if is_custom:
                safety_findings.append(
                    f"user customization {relative} {safety_reason} and was not read for safety; "
                    f"fix or remove {relative}"
                )
            else:
                safety_findings.append(
                    f"shipped skill {relative} {safety_reason} and was not read for safety; "
                    f"run /dex-update to restore {relative}"
                )
            continue
        errors = validate_skill_frontmatter(skill_path)
        if not errors:
            continue
        issue = "; ".join(_one_line(error) for error in errors)
        if is_custom:
            failures.append(
                f"user customization {relative} is invalid ({issue}); fix or remove {relative}"
            )
        else:
            failures.append(
                f"shipped skill {relative} is invalid ({issue}); run /dex-update to restore {relative}"
            )

    findings = [*failures, *safety_findings]
    if findings:
        return ProbeResult("BROKEN" if failures else "UNKNOWN", "; ".join(findings))
    shipped_count = len(skill_directories) - custom_count
    custom_noun = "customization" if custom_count == 1 else "customizations"
    shipped_noun = "skill" if shipped_count == 1 else "skills"
    return ProbeResult(
        "OK",
        f"Validated {custom_count} user {custom_noun} and {shipped_count} shipped {shipped_noun}",
    )


def _customization_mcp_source(context: DoctorContext) -> tuple[Path | None, bool]:
    live_config = _mcp_config_path(context)
    if live_config.exists() or live_config.is_symlink():
        return live_config, False
    shipped_example = context.vault_root / "System" / ".mcp.json.example"
    if shipped_example.exists() or shipped_example.is_symlink():
        return shipped_example, True
    return None, False


def _mcp_customization_failure(
    context: DoctorContext,
    config_path: Path,
    issue: str,
    *,
    shipped_example: bool,
) -> ProbeResult:
    relative = _display_vault_path(context, config_path)
    if shipped_example:
        guidance = f"run /dex-update to restore {relative}"
    else:
        guidance = f"fix your customization in {relative}"
    return ProbeResult("BROKEN", f"{relative} is invalid ({issue}); {guidance}")


def _probe_customization_mcp(context: DoctorContext) -> ProbeResult:
    from core.utils.validators import validate_mcp_config

    config_path, shipped_example = _customization_mcp_source(context)
    if config_path is None:
        return ProbeResult("OK", "No live MCP configuration is present; 0 custom entries require validation")

    config_safety = _unsafe_customization_path(context, config_path)
    if config_safety:
        relative = _display_vault_path(context, config_path)
        guidance = (
            f"run /dex-update to restore {relative}"
            if shipped_example
            else f"fix your customization in {relative}"
        )
        return ProbeResult(
            "UNKNOWN",
            f"{relative} {config_safety} and was not read or executed for safety; {guidance}",
        )

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return _mcp_customization_failure(
            context,
            config_path,
            _one_line(error),
            shipped_example=shipped_example,
        )

    structural_errors = validate_mcp_config(config)
    if shipped_example:
        structural_errors = [
            error for error in structural_errors if "unresolved placeholder" not in error
        ]
    if structural_errors:
        return _mcp_customization_failure(
            context,
            config_path,
            "; ".join(_one_line(error) for error in structural_errors),
            shipped_example=shipped_example,
        )

    servers = config["mcpServers"]
    custom_entries = [
        (name, entry)
        for name, entry in servers.items()
        if isinstance(name, str) and name.startswith("custom-")
    ]
    compile_failures = []
    safety_findings = []
    with tempfile.TemporaryDirectory(prefix="dex-doctor-mcp-compile-") as temporary:
        compile_root = Path(temporary)
        compile_index = 0
        for name, entry in custom_entries:
            python_targets = sorted(
                {
                    target
                    for target in _entry_targets(entry, context)
                    if target.suffix == ".py"
                },
                key=str,
            )
            for target in python_targets:
                relative_target = _display_vault_path(context, target)
                safety_reason = _unsafe_customization_path(context, target)
                if safety_reason:
                    safety_findings.append(
                        f"{name} target {relative_target} {safety_reason} and was not compiled or "
                        "executed for safety"
                    )
                    continue
                if not target.is_file():
                    compile_failures.append(f"{name} target {relative_target} is missing")
                    continue
                compile_index += 1
                cfile = compile_root / f"target-{compile_index}.pyc"
                try:
                    py_compile.compile(
                        str(target),
                        cfile=str(cfile),
                        doraise=True,
                    )
                except (OSError, py_compile.PyCompileError) as error:
                    compile_failures.append(
                        f"{name} target {relative_target} does not compile ({_one_line(error)})"
                    )

    if compile_failures:
        issues = [*compile_failures, *safety_findings]
        return _mcp_customization_failure(
            context,
            config_path,
            "; ".join(issues),
            shipped_example=shipped_example,
        )

    if safety_findings:
        relative = _display_vault_path(context, config_path)
        guidance = (
            f"run /dex-update to restore {relative}"
            if shipped_example
            else f"fix your customization in {relative}"
        )
        return ProbeResult(
            "UNKNOWN",
            f"{relative} is structurally valid; {'; '.join(safety_findings)}; {guidance}",
        )

    relative = _display_vault_path(context, config_path)
    noun = "entry" if len(custom_entries) == 1 else "entries"
    return ProbeResult(
        "OK",
        f"{relative} is structurally valid; {len(custom_entries)} custom MCP {noun} checked and not executed for safety",
    )


def _git_result(
    context: DoctorContext,
    *arguments: str,
    git_directory: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    executable = next(
        (
            str(candidate)
            for candidate in DOCTOR_GIT_CANDIDATES
            if not candidate.is_symlink() and candidate.is_file() and os.access(candidate, os.X_OK)
        ),
        None,
    )
    if executable is None:
        return subprocess.CompletedProcess([], 127, "", "trusted system git is unavailable")
    repository_arguments = (
        [f"--git-dir={git_directory}", f"--work-tree={context.repo_root}"]
        if git_directory is not None
        else ["-C", str(context.repo_root)]
    )
    return subprocess.run(
        [
            executable,
            "-c", "core.fsmonitor=false",
            "-c", "core.hooksPath=/dev/null",
            "-c", "core.attributesFile=/dev/null",
            "-c", "core.excludesFile=/dev/null",
            "-c", "submodule.recurse=false",
            *repository_arguments,
            *arguments,
        ],
        capture_output=True,
        env={
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_PAGER": "cat",
            "GIT_TERMINAL_PROMPT": "0",
            "HOME": "/var/empty" if Path("/var/empty").is_dir() else "/",
            "LC_ALL": "C",
            "PATH": DOCTOR_SAFE_PATH,
        },
        text=True,
        timeout=10,
        check=False,
    )


def _regular_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _topology_state(context: DoctorContext) -> str:
    vault_git = context.vault_root / ".git"
    brain_git = context.vault_root / ".dex" / "brain.git"
    topology = _regular_json(context.vault_root / "System" / ".dex" / "topology.json")
    vault_marker = _regular_json(vault_git / "dex-vault-v2")
    brain_marker = _regular_json(brain_git / "dex-brain-v2")
    if topology and topology.get("topology") == "brain-vault-split":
        if (
            vault_git.is_dir()
            and not vault_git.is_symlink()
            and brain_git.is_dir()
            and not brain_git.is_symlink()
            and vault_marker
            and vault_marker.get("role") == "vault"
            and brain_marker
            and brain_marker.get("role") == "brain"
        ):
            return "post-split"
        return "invalid-split"
    migration_state = _regular_json(
        context.vault_root / "System" / ".dex" / "migration-v2-state.json"
    )
    if migration_state and migration_state.get("status") != "complete":
        return "migration-in-progress"
    updater = context.vault_root / "core" / "update" / "apply-update.cjs"
    root_git = context.vault_root / ".git"
    if updater.is_file() and not updater.is_symlink() and root_git.is_dir():
        return "migration-pending"
    if not root_git.exists():
        return "zip-or-manual"
    return "pre-split"


def _probe_vault_git(context: DoctorContext) -> ProbeResult:
    topology = _topology_state(context)
    if topology != "post-split":
        if topology == "invalid-split":
            return ProbeResult(
                "BROKEN",
                "The split topology marker exists, but the vault Git marker is missing or invalid — run /dex-doctor after /dex-update recovery",
            )
        return ProbeResult(
            "OFF",
            "The separate vault history is not active yet; the topology check explains whether an upgrade is pending",
        )
    git_directory = context.vault_root / ".git"
    healthy = _git_result(context, "rev-parse", "--git-dir", git_directory=git_directory)
    if healthy.returncode != 0:
        return ProbeResult("BROKEN", "The vault Git repository cannot be opened — your files remain on disk, but history needs repair")
    integrity = _git_result(context, "fsck", "--no-progress", git_directory=git_directory)
    if integrity.returncode != 0:
        return ProbeResult("BROKEN", "The vault Git repository failed its integrity check — do not push it; get help repairing the local history")
    remotes = _git_result(context, "remote", git_directory=git_directory)
    remote_count = len([line for line in remotes.stdout.splitlines() if line.strip()]) if remotes.returncode == 0 else 0
    suffix = "no backup remote configured" if remote_count == 0 else f"{remote_count} private backup remote(s) configured"
    return ProbeResult("OK", f"The local vault history is healthy; {suffix}")


def _probe_brain_git(context: DoctorContext) -> ProbeResult:
    topology = _topology_state(context)
    if topology != "post-split":
        if topology == "invalid-split":
            return ProbeResult("BROKEN", "The split topology marker exists, but the brain Git marker is missing or invalid — use the updater's recovery mode")
        return ProbeResult("OFF", "The separate Dex brain history is not active yet")
    brain = context.vault_root / ".dex" / "brain.git"
    installed = _git_result(
        context,
        "rev-parse",
        "--verify",
        "refs/dex/installed^{commit}",
        git_directory=brain,
    )
    if installed.returncode != 0:
        return ProbeResult("BROKEN", "The Dex brain history cannot resolve its installed release — run the updater with --resume")
    installed_oid = installed.stdout.strip().lower()
    brain_marker = _regular_json(brain / "dex-brain-v2")
    topology = _regular_json(context.vault_root / "System" / ".dex" / "topology.json")
    marker_oid = str(brain_marker.get("installed", "")).lower() if brain_marker else ""
    topology_oid = str(topology.get("installedRelease", "")).lower() if topology else ""
    if not installed_oid or marker_oid != installed_oid or topology_oid != installed_oid:
        return ProbeResult(
            "BROKEN",
            "The Dex brain release identity disagrees across its installed ref and topology markers — use the updater's --resume recovery",
        )
    official_remote = re.compile(
        r"^(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)davekilleen/Dex(?:\.git)?/?$",
        re.IGNORECASE,
    )
    configured = _git_result(
        context,
        "config",
        "--get",
        "remote.origin.url",
        git_directory=brain,
    )
    effective = _git_result(
        context,
        "remote",
        "get-url",
        "origin",
        git_directory=brain,
    )
    if (
        configured.returncode != 0
        or effective.returncode != 0
        or not official_remote.fullmatch(configured.stdout.strip())
        or not official_remote.fullmatch(effective.stdout.strip())
    ):
        return ProbeResult(
            "BROKEN",
            "The Dex brain origin is not the effective official repository — repair the origin or local URL rewrite before updating",
        )
    integrity = _git_result(context, "fsck", "--no-progress", git_directory=brain)
    if integrity.returncode != 0:
        return ProbeResult("BROKEN", "The Dex brain Git store failed its integrity check — stop updating and get help")
    archive = context.vault_root / ".dex" / "pre-split-archive.git"
    archive_note = (
        " The pre-split archive is still available for the one release cycle restore window."
        if archive.is_dir() and not archive.is_symlink()
        else " The pre-split restore archive is no longer present."
    )
    return ProbeResult("OK", f"The Dex brain history is healthy at {installed_oid[:12]}.{archive_note}")


def _parse_semver(value: object) -> tuple[int, int, int] | None:
    match = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", str(value))
    return tuple(map(int, match.groups())) if match else None


def _version_in_range(version: object, requirement: object) -> bool:
    candidate = _parse_semver(version)
    if candidate is None or not isinstance(requirement, str):
        return False
    clauses = re.findall(r"(>=|<=|>|<|=)?\s*(\d+\.\d+\.\d+)", requirement)
    if not clauses:
        return False
    for operator, raw_limit in clauses:
        limit = _parse_semver(raw_limit)
        if limit is None:
            return False
        if operator == ">=" and not candidate >= limit:
            return False
        if operator == ">" and not candidate > limit:
            return False
        if operator == "<=" and not candidate <= limit:
            return False
        if operator == "<" and not candidate < limit:
            return False
        if operator in {"", "="} and candidate != limit:
            return False
    return True


def _probe_schema_match(context: DoctorContext) -> ProbeResult:
    if _topology_state(context) != "post-split":
        return ProbeResult("OFF", "Brain/vault schema matching starts after the one-time split")
    profile_path = context.vault_root / "System" / "user-profile.yaml"
    package_path = context.vault_root / "package.json"
    if profile_path.is_symlink() or package_path.is_symlink():
        return ProbeResult("UNKNOWN", "The doctor will not follow a symlinked profile or package file to check compatibility")
    profile = _load_yaml(profile_path)
    package = json.loads(package_path.read_text(encoding="utf-8"))
    if not isinstance(profile, dict) or not isinstance(package, dict):
        return ProbeResult("BROKEN", "The profile or package metadata is not a mapping, so compatibility cannot be established")
    dex = package.get("dex") if isinstance(package.get("dex"), dict) else {}
    vault_schema = profile.get("vault_schema")
    expected_schema = dex.get("vault_schema")
    brain_support = dex.get("brain_support")
    version = package.get("version")
    if vault_schema != expected_schema:
        return ProbeResult(
            "BROKEN",
            f"Vault schema {vault_schema!s} does not match this Dex brain's schema {expected_schema!s} — run /dex-update",
        )
    if not _version_in_range(version, brain_support):
        return ProbeResult(
            "BROKEN",
            f"Dex brain {version!s} is outside its declared support range {brain_support!s} — run /dex-update",
        )
    return ProbeResult("OK", f"Vault schema {vault_schema!s} matches Dex brain {version!s} ({brain_support})")


def _probe_vault_auto_commit(context: DoctorContext) -> ProbeResult:
    profile_path = context.vault_root / "System" / "user-profile.yaml"
    if profile_path.is_symlink():
        return ProbeResult("UNKNOWN", "The doctor will not follow a symlinked user profile to inspect vault auto-commit")
    try:
        profile = _load_yaml(profile_path)
    except FileNotFoundError:
        profile = {}
    if not isinstance(profile, dict):
        return ProbeResult("BROKEN", "Vault auto-commit cannot read System/user-profile.yaml as a mapping")
    vault = profile.get("vault") if isinstance(profile.get("vault"), dict) else {}
    enabled = vault.get("auto_commit") is True
    if not enabled:
        return ProbeResult("OFF", "Vault auto-commit is off by default; your files still stay in the local vault")
    if _topology_state(context) != "post-split":
        return ProbeResult("BROKEN", "Vault auto-commit is enabled before the split topology is ready — run /dex-update")
    return ProbeResult("OK", "Vault auto-commit is enabled for local SessionEnd snapshots; it disables Git hooks and does not run push")


def _probe_migration_pending(context: DoctorContext) -> ProbeResult:
    topology = _topology_state(context)
    if topology == "post-split":
        return ProbeResult("OK", "The brain/vault split is complete")
    if topology == "migration-pending":
        return ProbeResult("BROKEN", "Dex needs a one-time upgrade — run /dex-update; your notes stay in place")
    if topology == "migration-in-progress":
        return ProbeResult("BROKEN", "The one-time upgrade is incomplete — run /dex-update so the journal can resume it")
    if topology == "invalid-split":
        return ProbeResult("BROKEN", "The split topology markers disagree — use the updater or migrator --resume recovery, never raw Git")
    if topology == "zip-or-manual":
        return ProbeResult("OFF", "This ZIP/manual install has no Git topology; /dex-update can explain conversion or manual updates")
    return ProbeResult("OFF", "This is the older combined topology; no v2 migration code is active")


def _upstream_release_ref(context: DoctorContext) -> str | None:
    for candidate in ("refs/remotes/upstream/release", "refs/remotes/origin/release"):
        result = _git_result(context, "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}")
        if result.returncode == 0:
            return candidate
    return None


def _git_output_or_raise(result: subprocess.CompletedProcess[str], operation: str) -> str:
    if result.returncode == 0:
        return result.stdout
    detail = _one_line(result.stderr or result.stdout or f"exit {result.returncode}")
    raise RuntimeError(f"git could not {operation}: {detail}")


def _sanctioned_customization_path(relative: str) -> bool:
    if relative in {"System/user-profile.yaml", "System/pillars.yaml"}:
        return True
    parts = relative.split("/")
    if (
        len(parts) >= 3
        and parts[:2] == [".claude", "skills"]
        and parts[2].endswith("-custom")
    ):
        return True
    return (
        len(parts) == 3
        and parts[:2] == ["System", "integrations"]
        and Path(relative).suffix == ".yaml"
    )


def _git_file(
    context: DoctorContext,
    treeish: str,
    relative: str,
    *,
    git_directory: Path | None = None,
) -> str | None:
    result = _git_result(
        context,
        "show",
        f"{treeish}:{relative}",
        git_directory=git_directory,
    )
    return result.stdout if result.returncode == 0 else None


def _working_file(context: DoctorContext, relative: str) -> str | None:
    path = context.repo_root / relative
    try:
        lexical = path.relative_to(context.repo_root)
    except ValueError:
        return None
    if any(
        part in {"", ".", ".."}
        or part.lower() == ".env"
        or part.lower().startswith(".env.")
        or "credential" in part.lower()
        for part in lexical.parts
    ):
        return None
    current = context.repo_root
    for part in lexical.parts:
        current /= part
        if current.is_symlink():
            return None
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _strip_user_extensions(text: str) -> str:
    lines = text.splitlines(keepends=True)
    start = next(
        (index for index, line in enumerate(lines) if line.strip() == "## USER_EXTENSIONS_START"),
        None,
    )
    if start is None:
        return text
    end = next(
        (
            index
            for index, line in enumerate(lines[start + 1 :], start=start + 1)
            if line.strip() == "## USER_EXTENSIONS_END"
        ),
        None,
    )
    if end is None:
        return text
    return "".join([*lines[: start + 1], *lines[end:]])


def _mcp_without_custom_entries(text: str) -> str | None:
    try:
        config = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(config, dict) or not isinstance(config.get("mcpServers"), dict):
        return None
    normalized = dict(config)
    normalized["mcpServers"] = {
        name: entry
        for name, entry in config["mcpServers"].items()
        if not isinstance(name, str) or not name.startswith("custom-")
    }
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def _only_sanctioned_file_changes(
    context: DoctorContext,
    baseline: str,
    relative: str,
    *,
    git_directory: Path | None = None,
) -> bool:
    baseline_text = _git_file(
        context,
        baseline,
        relative,
        git_directory=git_directory,
    )
    working_text = _working_file(context, relative)
    if baseline_text is None or working_text is None:
        return False
    if relative == "CLAUDE.md":
        return _strip_user_extensions(baseline_text) == _strip_user_extensions(working_text)
    if relative == ".mcp.json":
        baseline_config = _mcp_without_custom_entries(baseline_text)
        working_config = _mcp_without_custom_entries(working_text)
        return baseline_config is not None and baseline_config == working_config
    return False


def _release_tree_entries(
    context: DoctorContext,
    baseline: str,
    *,
    git_directory: Path | None = None,
) -> dict[str, tuple[str, str]]:
    output = _git_output_or_raise(
        _git_result(
            context,
            "ls-tree",
            "-r",
            "-z",
            baseline,
            git_directory=git_directory,
        ),
        "list release files",
    )
    entries = {}
    for record in output.split("\0"):
        if not record:
            continue
        metadata, separator, relative = record.partition("\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise RuntimeError("git returned an invalid release tree entry")
        mode, object_type, object_id = fields
        if object_type != "blob":
            entries[relative] = (mode, "")
        else:
            entries[relative] = (mode, object_id)
    return entries


def _worktree_matches_release_blob(
    context: DoctorContext,
    relative: str,
    mode: str,
    object_id: str,
) -> bool:
    parts = Path(relative).parts
    if not parts or any(
        part in {"", ".", ".."}
        or part.lower() == ".env"
        or part.lower().startswith(".env.")
        or "credential" in part.lower()
        for part in parts
    ):
        return False
    current = context.repo_root
    for part in parts[:-1]:
        current /= part
        if current.is_symlink():
            return False
    path = context.repo_root / relative
    try:
        if mode == "120000":
            if not path.is_symlink():
                return False
            data = os.readlink(path).encode("utf-8")
        elif mode in {"100644", "100755"}:
            if path.is_symlink() or not path.is_file():
                return False
            data = path.read_bytes()
            if bool(path.stat().st_mode & 0o111) != (mode == "100755"):
                return False
        else:
            return False
    except (OSError, UnicodeError):
        return False

    algorithm = "sha1" if len(object_id) == 40 else "sha256" if len(object_id) == 64 else None
    if algorithm is None:
        return False
    digest = hashlib.new(algorithm)
    digest.update(f"blob {len(data)}\0".encode("ascii"))
    digest.update(data)
    return digest.hexdigest() == object_id


def _brain_paths_from_installed_release(
    context: DoctorContext,
    baseline: str,
    brain: Path,
) -> set[str]:
    manifest = _git_file(
        context,
        baseline,
        "System/.installed-files.manifest",
        git_directory=brain,
    )
    ownership_text = _git_file(
        context,
        baseline,
        "core/update/ownership.json",
        git_directory=brain,
    )
    if manifest is None or ownership_text is None:
        raise RuntimeError("installed brain release is missing its manifest or ownership map")
    ownership_config = json.loads(ownership_text)
    if not isinstance(ownership_config, dict) or not isinstance(ownership_config.get("rules"), list):
        raise RuntimeError("installed brain ownership map is invalid")

    def classify(relative: str) -> str:
        parts = relative.split("/")
        if len(parts) >= 3 and parts[:2] == [".claude", "skills"] and parts[2].endswith("-custom"):
            return "vault"
        matches = []
        for rule in ownership_config["rules"]:
            if not isinstance(rule, dict) or not isinstance(rule.get("prefix"), str):
                continue
            prefix = rule["prefix"]
            if relative == prefix or (prefix.endswith("/") and relative.startswith(prefix)):
                matches.append(rule)
        if not matches:
            return str(ownership_config.get("defaultClass", "vault"))
        longest = max(len(rule["prefix"]) for rule in matches)
        classes = {rule.get("class") for rule in matches if len(rule["prefix"]) == longest}
        if len(classes) != 1:
            raise RuntimeError(f"installed ownership is ambiguous for {relative}")
        return str(classes.pop())

    return {
        relative
        for relative in manifest.splitlines()
        if relative and classify(relative) == "brain"
    }


def _probe_core_drift(context: DoctorContext) -> ProbeResult:
    if _topology_state(context) == "post-split":
        brain = context.vault_root / ".dex" / "brain.git"
        baseline = "refs/dex/installed"
        installed = _git_result(
            context,
            "rev-parse",
            "--verify",
            f"{baseline}^{{commit}}",
            git_directory=brain,
        )
        if installed.returncode != 0:
            return ProbeResult("UNKNOWN", "the brain Git store cannot resolve refs/dex/installed — run /dex-update --resume")
        release_entries = _release_tree_entries(
            context,
            baseline,
            git_directory=brain,
        )
        brain_paths = _brain_paths_from_installed_release(context, baseline, brain)
        drifted = sorted(
            relative
            for relative in brain_paths
            if relative in release_entries
            and not _worktree_matches_release_blob(
                context,
                relative,
                *release_entries[relative],
            )
        )
        if not drifted:
            return ProbeResult("OK", "No shipped brain files differ from refs/dex/installed")
        return ProbeResult(
            "UNKNOWN",
            "Modified shipped brain files: "
            f"{', '.join(drifted)}; the updater will back these up before replacement",
        )

    release_ref = _upstream_release_ref(context)
    if release_ref is None:
        return ProbeResult("UNKNOWN", "no upstream remote — can't compare")

    merge_base = _git_result(context, "merge-base", "HEAD", release_ref)
    baseline = merge_base.stdout.strip() if merge_base.returncode == 0 else release_ref
    release_entries = _release_tree_entries(context, baseline)
    candidates = sorted(
        relative
        for relative, (mode, object_id) in release_entries.items()
        if not _sanctioned_customization_path(relative)
        and not _worktree_matches_release_blob(context, relative, mode, object_id)
    )
    drifted = [
        relative
        for relative in candidates
        if not _only_sanctioned_file_changes(context, baseline, relative)
    ]
    if not drifted:
        return ProbeResult("OK", "No tracked shipped files differ from the installed release")
    return ProbeResult(
        "UNKNOWN",
        "Modified shipped files: "
        f"{', '.join(drifted)}; updates may conflict; the doctor can't vouch for modified shipped files",
    )


def _probe_entity_engine(context: DoctorContext) -> ProbeResult:
    """Report entity tracking, creation, verification, quarantine, and index health."""
    try:
        from core.utils.entity_pages import parse_entity_page

        contacts_path = context.core_path("CONTACTS_STATE_FILE")
        suggestions_path = context.core_path("ENTITY_SUGGESTIONS_FILE")
        verification_path = context.core_path("ENTITY_VERIFICATION_FILE")
        gardener_path = context.core_path("GARDENER_STATE_FILE")
        profile_path = context.core_path("USER_PROFILE_FILE")
        people_dir = context.core_path("PEOPLE_DIR")
        companies_dir = context.core_path("COMPANIES_DIR")
        people_index_path = context.core_path("PEOPLE_INDEX_FILE")

        contacts = json.loads(contacts_path.read_text()) if contacts_path.exists() else {}
        suggestions = json.loads(suggestions_path.read_text()) if suggestions_path.exists() else {}
        verification = json.loads(verification_path.read_text()) if verification_path.exists() else {}
        gardener = json.loads(gardener_path.read_text()) if gardener_path.exists() else {}
        profile = _load_yaml(profile_path) if profile_path.exists() else {}
        if profile is None:
            profile = {}
        if not isinstance(profile, dict):
            raise ValueError("user-profile.yaml must contain a mapping")

        raw_mode = profile.get("entity_creation", {}).get("mode")
        if raw_mode is False:
            raw_mode = "off"
        mode = raw_mode if raw_mode in {"auto", "suggest", "off"} else "suggest"
        mode_label = mode if raw_mode in {"auto", "suggest", "off"} else "suggest (default — key missing)"
        tracked = len(contacts.get("contacts", {}))
        observations = len(contacts.get("observations", {}))
        suggestion_items = suggestions if isinstance(suggestions, list) else suggestions.get("suggestions", [])
        pending = sum(item.get("status") == "suggested" for item in suggestion_items)
        gardener_pages = gardener.get("pages", {}) if isinstance(gardener, dict) else {}
        gardener_locked = sum(bool(item.get("locked")) for item in gardener_pages.values())
        if profile.get("entity_gardener", {}).get("enabled") is False:
            gardener_label = "off (disabled)"
        elif not any(os.environ.get(key) for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY")):
            gardener_label = "off (no LLM key)"
        else:
            maintained = sum(bool(item.get("output_hash")) for item in gardener_pages.values())
            gardener_label = f"on ({maintained} pages maintained)"
        if gardener_locked:
            gardener_label += f", {gardener_locked} locked"

        unresolved = len(verification.get("unresolved", []))
        generated_at = verification.get("generated_at")
        stale = False
        if generated_at:
            verified_at = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
            if verified_at.tzinfo is None:
                verified_at = verified_at.replace(tzinfo=timezone.utc)
            stale = context.now - verified_at.astimezone(timezone.utc) > timedelta(hours=48)

        quarantined_paths = []
        for directory in (people_dir, companies_dir):
            if not directory.exists():
                continue
            for page in directory.rglob("*.md"):
                if page.name != "README.md" and parse_entity_page(page).get("quarantined"):
                    quarantined_paths.append(str(page.relative_to(context.vault_root)))

        newest_people_mtime = max(
            (page.stat().st_mtime for page in people_dir.rglob("*.md") if page.name != "README.md"),
            default=0.0,
        ) if people_dir.exists() else 0.0
        index_freshness = "missing"
        if people_index_path.exists():
            people_index = json.loads(people_index_path.read_text())
            built_at = datetime.fromisoformat(str(people_index.get("built_at", "")).replace("Z", "+00:00"))
            index_freshness = "fresh" if built_at.timestamp() >= newest_people_mtime else "stale"

        verification_label = f"{generated_at or 'never'} / {unresolved} unresolved"
        if stale:
            verification_label += " / stale >48h"
        quarantine_label = str(len(quarantined_paths))
        if quarantined_paths:
            quarantine_label += f" ({', '.join(quarantined_paths[:3])})"
        detail = (
            f"Entity engine tracks {tracked} contacts and {observations} observations; "
            f"creation is {mode_label}; {pending} suggestions pending; last verification "
            f"{verification_label}; {quarantine_label} quarantined pages; people index {index_freshness}"
            f"; gardener {gardener_label}"
        )
        if unresolved or quarantined_paths:
            return ProbeResult("BROKEN", detail)
        if mode == "off":
            return ProbeResult("OFF", detail)
        return ProbeResult("OK", detail)
    except (ImportError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        return ProbeResult("UNKNOWN", f"Entity engine files could not be checked: {_one_line(error)}")


def _probe_doctor_self(_context: DoctorContext) -> ProbeResult:
    return ProbeResult("OK", "The doctor instrument runner completed")


def _looks_like_sandbox_failure(detail: str) -> bool:
    lowered = detail.lower()
    return any(
        marker in lowered
        for marker in (
            "operation not permitted",
            "sandbox",
            "gpu",
            "metal device",
            "not authorized to send apple events",
            "deny file-read",
        )
    )


def _granola_api_key(context: DoctorContext) -> str | None:
    configured = os.environ.get("GRANOLA_API_KEY")
    if configured and configured.strip():
        return configured.strip()
    env_path = context.vault_root / ".env"
    if not env_path.exists():
        return None
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        name, separator, value = line.partition("=")
        if not separator or name.strip() != "GRANOLA_API_KEY":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value or None
    return None


def _granola_filtered_query(context: DoctorContext) -> list[dict[str, Any]]:
    """Run the exact filtered-list path used by real Granola queries."""
    with _vault_environment(context):
        from core.mcp.granola_server import _cutoff_iso, _list_notes

        return _list_notes(
            created_after=_cutoff_iso(7),
            max_notes=1,
            page_size=1,
        )


def _probe_granola_query_path(context: DoctorContext) -> ProbeResult:
    if not _granola_api_key(context):
        return ProbeResult("OFF", "Granola is not connected because no API key is configured")
    try:
        notes = _granola_filtered_query(context)
    except Exception as error:
        from core.mcp.granola_server import GranolaAPIError

        if isinstance(error, GranolaAPIError):
            return ProbeResult(
                "BROKEN",
                error.user_message,
                Heal(tier=3, action="Run /granola-setup to repair the Granola connection.", applied=False),
            )
        if _looks_like_sandbox_failure(_one_line(error)):
            return ProbeResult("UNKNOWN", f"The sandbox blocked the Granola query: {_one_line(error)}")
        raise
    return ProbeResult("OK", f"The real filtered Granola query completed and returned {len(notes)} note summaries")


def _calendar_permission_status(_context: DoctorContext) -> str:
    if not _is_macos():
        return "unsupported"
    code = (
        "import EventKit; "
        "print(EventKit.EKEventStore.authorizationStatusForEntityType_(EventKit.EKEntityTypeEvent))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    combined = _one_line(f"{result.stdout} {result.stderr}")
    if result.returncode != 0:
        if _looks_like_sandbox_failure(combined):
            raise PermissionError(combined)
        raise RuntimeError(combined)
    try:
        status = int(result.stdout.strip())
    except ValueError as error:
        raise RuntimeError(f"EventKit returned an invalid authorization status: {combined}") from error
    return {
        0: "not_determined",
        1: "restricted",
        2: "denied",
        3: "authorized",
        4: "write_only",
    }.get(status, f"unknown ({status})")


def _calendar_list_result(context: DoctorContext) -> dict[str, Any]:
    """Call the exact helper behind calendar_list_calendars."""
    with _vault_environment(context):
        from core.mcp.calendar_server import _get_calendar_list_result

        return _get_calendar_list_result()


def _configured_work_calendar(context: DoctorContext) -> str | None:
    profile_path = context.core_path("USER_PROFILE_FILE")
    if not profile_path.exists():
        return None
    profile = _load_yaml(profile_path) or {}
    if not isinstance(profile, dict):
        raise ValueError("user-profile.yaml must contain an object")
    calendar = profile.get("calendar", {})
    if not isinstance(calendar, dict):
        return None
    configured = calendar.get("work_calendar")
    return str(configured).strip() if configured else None


def _probe_calendar_access(context: DoctorContext) -> ProbeResult:
    configured = _configured_work_calendar(context)
    status = _calendar_permission_status(context)
    if status == "unsupported":
        return ProbeResult("UNKNOWN", "EventKit calendar access can only be checked on macOS")
    if status == "not_determined" and not configured:
        return ProbeResult("OFF", "Calendar access has never been requested and no work calendar is configured")
    if status == "write_only":
        return ProbeResult(
            "BROKEN",
            "Calendar permission is write only; Dex needs full calendar access to read calendars",
            Heal(
                tier=3,
                action="Grant Full Calendar Access in System Settings > Privacy & Security > Calendars.",
                applied=False,
            ),
        )
    if status in {"not_determined", "restricted", "denied"}:
        return ProbeResult(
            "BROKEN",
            f"Calendar permission is {status.replace('_', ' ')}",
            Heal(
                tier=3,
                action="Enable Calendar access in System Settings > Privacy & Security > Calendars.",
                applied=False,
            ),
        )
    if status != "authorized":
        return ProbeResult("UNKNOWN", f"EventKit returned an unknown permission status: {status}")

    result = _calendar_list_result(context)
    if not result.get("success"):
        detail = _one_line(result.get("error", "calendar_list_calendars failed"))
        if _looks_like_sandbox_failure(detail):
            return ProbeResult("UNKNOWN", f"The sandbox blocked calendar_list_calendars: {detail}")
        if "denied" in detail.lower() or "permission" in detail.lower():
            return ProbeResult(
                "BROKEN",
                detail,
                Heal(
                    tier=3,
                    action="Enable Calendar access in System Settings > Privacy & Security > Calendars.",
                    applied=False,
                ),
            )
        return ProbeResult("UNKNOWN", f"calendar_list_calendars could not complete: {detail}")

    calendars = [str(name) for name in result.get("calendars", [])]
    if configured and configured not in calendars:
        available = ", ".join(calendars) or "none"
        return ProbeResult(
            "BROKEN",
            f"Configured work calendar '{configured}' was not found; available calendars are {available}",
            Heal(
                tier=3,
                action="Set calendar.work_calendar in System/user-profile.yaml to one of the listed names.",
                applied=False,
            ),
        )
    return ProbeResult("OK", f"Calendar access works and {len(calendars)} calendar names were returned")


def _qmd_registered(config: dict[str, Any]) -> bool:
    for name, entry in config.get("mcpServers", {}).items():
        if not isinstance(entry, dict):
            continue
        command = str(entry.get("command", ""))
        args = [str(argument) for argument in entry.get("args", []) if isinstance(argument, str)]
        if "qmd" in name.lower() or Path(command).name == "qmd" or any(Path(argument).name == "qmd" for argument in args):
            return True
    return False


def _qmd_binary(_context: DoctorContext) -> str | None:
    from core.utils.qmd_query import _find_qmd

    return _find_qmd()


def _qmd_status(binary: str) -> tuple[bool, str]:
    result = subprocess.run(
        [binary, "status"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    detail = _one_line(result.stdout if result.returncode == 0 else result.stderr or result.stdout)
    return result.returncode == 0, detail


def _probe_qmd_live(context: DoctorContext) -> ProbeResult:
    try:
        config = _load_mcp_config(context)
    except FileNotFoundError:
        return ProbeResult("OFF", "qmd is not registered, so semantic search remains opt-in")
    if not _qmd_registered(config):
        return ProbeResult("OFF", "qmd is not registered, so semantic search remains opt-in")
    binary = _qmd_binary(context)
    if not binary:
        return ProbeResult(
            "BROKEN",
            "qmd is registered but its binary is not installed",
            Heal(tier=3, action="Run /enable-semantic-search to install and configure qmd.", applied=False),
        )
    healthy, detail = _qmd_status(binary)
    if not healthy:
        if _looks_like_sandbox_failure(detail):
            return ProbeResult("UNKNOWN", f"The sandbox or GPU environment blocked qmd status: {detail}")
        return ProbeResult(
            "BROKEN",
            f"qmd status failed: {detail}",
            Heal(tier=3, action="Run /enable-semantic-search to repair qmd.", applied=False),
        )
    return ProbeResult("OK", f"qmd status completed successfully: {detail}")


def _enabled_integrations(config: object) -> list[tuple[str, dict[str, Any]]]:
    if not isinstance(config, dict):
        raise ValueError("integration config must contain an object")
    enabled: dict[str, dict[str, Any]] = {}
    legacy = config.get("enabled", {})
    if isinstance(legacy, dict):
        for name, value in legacy.items():
            if value is True:
                enabled[str(name)] = {}
    for name, settings in config.items():
        if name == "enabled" or not isinstance(settings, dict):
            continue
        if settings.get("enabled") is True:
            enabled[str(name)] = settings
    return sorted(enabled.items())


def _integration_checker_command(
    context: DoctorContext,
    name: str,
    settings: dict[str, Any],
) -> list[str]:
    configured = settings.get("health_checker") or settings.get("health_check")
    if isinstance(configured, list) and all(isinstance(part, str) for part in configured):
        return [_expand_path_token(part, context) for part in configured]
    if isinstance(configured, str):
        checker = Path(_expand_path_token(configured, context))
        if not checker.is_absolute():
            checker = context.vault_root / checker
        return [shutil.which("node") or "node", str(checker)]

    candidates = (
        context.vault_root / "core" / "integrations" / name / "connection.cjs",
        context.vault_root / ".scripts" / "integrations" / name / "connection.cjs",
        context.vault_root / ".scripts" / name / "connection.cjs",
        context.vault_root / ".claude" / "skills" / f"{name}-setup" / "connection.cjs",
    )
    checker = next((candidate for candidate in candidates if candidate.is_file()), None)
    if checker is None:
        raise FileNotFoundError(f"no existing {name} connection health checker was found")
    node = shutil.which("node")
    if not node:
        raise FileNotFoundError("node is required to run integration connection checkers")
    return [node, str(checker)]


def _integration_health_check(
    context: DoctorContext,
    name: str,
    settings: dict[str, Any],
) -> tuple[bool, str]:
    command = _integration_checker_command(context, name, settings)
    result = subprocess.run(
        command,
        cwd=context.vault_root,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    detail = _one_line(result.stdout if result.returncode == 0 else result.stderr or result.stdout)
    if result.returncode != 0:
        return False, detail
    try:
        payload = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError):
        return True, detail
    if isinstance(payload, dict):
        for key in ("healthy", "success", "ok", "connected"):
            if payload.get(key) is False:
                return False, _one_line(payload.get("error") or payload.get("message") or detail)
    return True, detail


def _probe_integrations_enabled(context: DoctorContext) -> ProbeResult:
    config_path = context.vault_root / "System" / "integrations" / "config.yaml"
    if not config_path.exists():
        return ProbeResult("OFF", "No integrations are enabled")
    config = _load_yaml(config_path) or {}
    enabled = _enabled_integrations(config)
    if not enabled:
        return ProbeResult("OFF", "No integrations are enabled")

    failures = []
    unknowns = []
    for name, settings in enabled:
        try:
            healthy, detail = _integration_health_check(context, name, settings)
        except Exception as error:
            unknowns.append(f"{name}: {_one_line(error)}")
            continue
        if not healthy:
            if _looks_like_sandbox_failure(detail):
                unknowns.append(f"{name}: {detail}")
            else:
                failures.append(f"{name}: {detail}")
    if failures:
        detail_parts = [f"failed: {'; '.join(failures)}"]
        if unknowns:
            detail_parts.append(f"could not check: {'; '.join(unknowns)}")
        return ProbeResult(
            "BROKEN",
            f"Enabled integration checks {'; '.join(detail_parts)}",
            Heal(tier=3, action="Reconnect the named integration with its setup skill.", applied=False),
        )
    if unknowns:
        return ProbeResult(
            "UNKNOWN",
            f"Enabled integration checks could not run: {'; '.join(unknowns)}",
        )
    names = ", ".join(name for name, _settings in enabled)
    return ProbeResult("OK", f"Existing health checkers passed for enabled integrations: {names}")


def _mcp_import_check(
    context: DoctorContext,
    module: str,
    interpreter: str,
) -> tuple[bool, str]:
    executable = _resolved_interpreter(interpreter, context)
    if not executable:
        return False, f"interpreter is missing or not executable: {interpreter}"
    with tempfile.TemporaryDirectory(prefix="dex-doctor-import-") as sandbox:
        env = dict(os.environ)
        env["VAULT_PATH"] = sandbox
        env["VAULT_ROOT"] = sandbox
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(context.vault_root) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
        result = subprocess.run(
            [executable, "-c", f"import importlib; importlib.import_module({module!r})"],
            cwd=context.vault_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    detail = _one_line(result.stderr or result.stdout or f"exit {result.returncode}")
    return result.returncode == 0, detail


def _probe_mcp_importable(context: DoctorContext) -> ProbeResult:
    config = _load_mcp_config(context)
    registered = _registered_core_scripts(context, config)
    failures = []
    for _name, (target, interpreter) in registered.items():
        module = f"core.mcp.{target.stem}"
        importable, detail = _mcp_import_check(context, module, interpreter)
        if not importable:
            failures.append(f"{module}: {detail}")
    if failures:
        return ProbeResult(
            "BROKEN",
            f"Registered MCP imports failed: {'; '.join(failures)}",
            Heal(tier=2, action="Reinstall the missing MCP dependencies into the vault .venv.", applied=False),
        )
    return ProbeResult("OK", f"All {len(registered)} registered core MCP servers import in a subprocess")


def _probe_smoke_journeys(context: DoctorContext) -> ProbeResult:
    smoke_path = context.repo_root / "core" / "utils" / "smoke.py"
    env = {
        name: os.environ[name]
        for name in ("PATH", "PYTHONPATH")
        if name in os.environ
    }
    env.update(
        {
            "VAULT_PATH": str(context.vault_root),
            "VAULT_ROOT": str(context.vault_root),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    result = subprocess.run(
        [sys.executable, str(smoke_path), "--json"],
        cwd=context.vault_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=35,
        check=False,
    )
    if result.returncode == 2:
        detail = _one_line(result.stderr or result.stdout or "exit 2")
        raise RuntimeError(f"smoke harness failed: {detail}")
    if result.returncode not in {0, 1}:
        detail = _one_line(result.stderr or result.stdout or f"exit {result.returncode}")
        raise RuntimeError(f"smoke harness returned exit {result.returncode}: {detail}")
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"smoke harness returned invalid JSON: {_one_line(error)}") from error
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        raise RuntimeError("smoke harness returned an unsupported report schema")
    journeys = report.get("journeys")
    if not isinstance(journeys, list) or not journeys:
        raise RuntimeError("smoke harness returned no journeys")

    rendered = []
    verdicts = []
    for journey in journeys:
        if not isinstance(journey, dict):
            raise RuntimeError("smoke harness returned a malformed journey")
        journey_id = journey.get("id")
        verdict = journey.get("verdict")
        detail = journey.get("detail")
        if not isinstance(journey_id, str) or verdict not in VERDICTS or not isinstance(detail, str):
            raise RuntimeError("smoke harness returned a malformed journey")
        verdicts.append(verdict)
        rendered.append(f"{journey_id} [{verdict}]: {_one_line(detail)}")

    if "BROKEN" in verdicts:
        worst = "BROKEN"
    elif "UNKNOWN" in verdicts:
        worst = "UNKNOWN"
    elif "OK" in verdicts:
        worst = "OK"
    else:
        worst = "OFF"
    if (result.returncode == 1) != (worst == "BROKEN"):
        raise RuntimeError(
            f"smoke harness exit {result.returncode} did not match its {worst} journey roll-up"
        )
    return ProbeResult(worst, " | ".join(rendered))


def main(argv: list[str] | None = None, *, context: DoctorContext | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deep", action="store_true", help="Run live service probes.")
    parser.add_argument("--heal", action="store_true", help="Apply safe Tier-1 repairs before checking.")
    args = parser.parse_args(argv)

    try:
        report = collect(deep=args.deep, heal=args.heal, context=context)
        output = json.dumps(report, indent=2)
    except Exception as error:
        print(f"dex-doctor could not produce JSON: {_one_line(error)}", file=sys.stderr)
        return 1

    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
