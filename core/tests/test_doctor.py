"""Contract tests for the /dex-doctor collector."""

import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from core.utils import doctor

DOCTOR_PATH = Path(__file__).resolve().parents[1] / "utils" / "doctor.py"
NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)

QUICK_IDS = [
    "vault.structure",
    "vault.configs",
    "mcp.registered",
    "mcp.orphans",
    "python.env",
    "hooks.wired",
    "jobs.loaded",
    "jobs.fresh",
    "preflight.queue",
    "doctor.self",
]

DEEP_IDS = [
    "granola.query_path",
    "calendar.access",
    "qmd.live",
    "integrations.enabled",
    "mcp.importable",
]


@pytest.fixture
def context(tmp_path):
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "core").mkdir()
    home = tmp_path / "home"
    home.mkdir()
    return doctor.DoctorContext(vault_root=vault, repo_root=vault, home=home, now=NOW)


def _check(report, check_id):
    return next(check for check in report["checks"] if check["id"] == check_id)


def _stub_probes(monkeypatch, *, overrides=None, exclude=()):
    overrides = overrides or {}
    excluded = set(exclude)
    for definition in (*doctor.QUICK_CHECKS, *doctor.DEEP_CHECKS):
        if definition.id == "doctor.self" or definition.id in excluded:
            continue
        probe_result = overrides.get(definition.id, doctor.ProbeResult("OK", "Stub probe completed."))
        monkeypatch.setattr(
            doctor,
            definition.probe,
            lambda _context, result=probe_result: result,
        )


def _write_valid_configs(context, *, calendar=None):
    profile = "name: Test User\n"
    if calendar is not None:
        profile += f"calendar:\n  work_calendar: {calendar}\n"
    (context.vault_root / "System" / "user-profile.yaml").write_text(profile)
    (context.vault_root / "System" / "pillars.yaml").write_text("pillars: []\n")
    settings = context.vault_root / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text('{"hooks": {}}\n')


def _write_mcp_config(context, servers):
    path = context.vault_root / ".mcp.json"
    path.write_text(json.dumps({"mcpServers": servers}))
    return path


def _write_plist(context, label):
    agents = context.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / f"{label}.plist"
    with plist.open("wb") as handle:
        plistlib.dump({"Label": label, "ProgramArguments": ["/bin/bash"]}, handle)
    return plist


def _tree_snapshot(root):
    snapshot = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        mode = stat.S_IMODE(path.stat().st_mode)
        snapshot[relative] = ("dir", mode) if path.is_dir() else ("file", mode, path.read_bytes())
    return snapshot


def test_doctor_collector_module_exists():
    assert DOCTOR_PATH.is_file()


def test_registry_ids_match_the_approved_spec():
    assert [definition.id for definition in doctor.QUICK_CHECKS] == QUICK_IDS
    assert [definition.id for definition in doctor.DEEP_CHECKS] == DEEP_IDS
    assert doctor.VERDICTS == frozenset({"OK", "OFF", "BROKEN", "UNKNOWN"})


@pytest.mark.parametrize("deep,expected_ids", [(False, QUICK_IDS), (True, QUICK_IDS + DEEP_IDS)])
def test_json_contract_shape_and_last_run_file(monkeypatch, context, deep, expected_ids):
    _stub_probes(monkeypatch)

    report = doctor.collect(deep=deep, context=context)

    assert set(report) == {"generated_at", "mode", "instruments", "checks", "summary"}
    assert report["generated_at"] == NOW.isoformat()
    assert report["mode"] == ("deep" if deep else "quick")
    assert report["instruments"] == {
        "attempted": len(expected_ids),
        "completed": len(expected_ids),
        "failed": [],
    }
    assert [check["id"] for check in report["checks"]] == expected_ids
    assert report["summary"] == {"ok": len(expected_ids), "off": 0, "broken": 0, "unknown": 0}
    for check in report["checks"]:
        assert set(check) == {"id", "feature", "verdict", "detail", "heal"}
        assert check["verdict"] in doctor.VERDICTS
        assert isinstance(check["detail"], str) and check["detail"]
        assert check["heal"] is None

    assert json.loads(context.last_run_path.read_text()) == report


def test_summary_counts_each_exact_verdict(monkeypatch, context):
    _stub_probes(
        monkeypatch,
        overrides={
            "vault.configs": doctor.ProbeResult("OFF", "Deliberately disabled."),
            "mcp.registered": doctor.ProbeResult("BROKEN", "Configuration is broken."),
            "mcp.orphans": doctor.ProbeResult("UNKNOWN", "Could not inspect registration."),
        },
    )

    report = doctor.collect(context=context)

    assert report["summary"] == {"ok": 7, "off": 1, "broken": 1, "unknown": 1}
    assert report["instruments"]["completed"] == 10


def test_raising_probe_becomes_unknown_and_main_still_returns_valid_json(monkeypatch, context, capsys):
    _stub_probes(monkeypatch)

    def explode(_context):
        raise RuntimeError("probe exploded")

    monkeypatch.setattr(doctor, "_probe_vault_configs", explode)

    exit_code = doctor.main([], context=context)
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert _check(report, "vault.configs")["verdict"] == "UNKNOWN"
    assert "probe exploded" in _check(report, "vault.configs")["detail"]
    assert report["instruments"] == {
        "attempted": 10,
        "completed": 9,
        "failed": [{"id": "vault.configs", "error": "probe exploded"}],
    }
    assert _check(report, "doctor.self")["verdict"] == "BROKEN"


def test_last_run_write_failure_marks_doctor_self_broken(monkeypatch, context):
    _stub_probes(monkeypatch)

    def fail_write(_report, _context):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(doctor, "_write_last_run", fail_write)

    report = doctor.collect(context=context)

    assert _check(report, "doctor.self")["verdict"] == "BROKEN"
    assert "read-only filesystem" in _check(report, "doctor.self")["detail"]
    assert {failure["id"] for failure in report["instruments"]["failed"]} == {"doctor.self"}


def test_heal_applies_all_t1_actions_and_leaves_t2_suggestion_untouched(
    monkeypatch,
    tmp_path,
    fixture_vault,
):
    vault = tmp_path / "vault-copy"
    shutil.copytree(fixture_vault, vault)
    shutil.rmtree(vault / "00-Inbox")
    (vault / "core").mkdir()
    script = vault / ".scripts" / "repo-tool.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n")
    script.chmod(0o644)
    missing_target = vault / "core" / "mcp" / "missing_server.py"
    mcp_config = _write_mcp_config(
        doctor.DoctorContext(vault, vault, tmp_path / "home", NOW),
        {"missing": {"command": sys.executable, "args": [str(missing_target)]}},
    )
    original_mcp = mcp_config.read_text()
    test_context = doctor.DoctorContext(vault_root=vault, repo_root=vault, home=tmp_path / "home", now=NOW)
    test_context.home.mkdir()

    t2 = doctor.ProbeResult(
        "BROKEN",
        "A registered MCP target is missing.",
        doctor.Heal(tier=2, action="Repair the missing MCP target.", applied=False),
    )
    _stub_probes(
        monkeypatch,
        overrides={"mcp.registered": t2},
        exclude={"vault.structure"},
    )
    monkeypatch.setattr(doctor, "_repo_shipped_executables", lambda _context: [script])
    before = _tree_snapshot(vault)

    report = doctor.collect(heal=True, context=test_context)
    after = _tree_snapshot(vault)

    assert (vault / "00-Inbox").is_dir()
    paths_json = json.loads((vault / "core" / "paths.json").read_text())
    assert paths_json["VAULT_ROOT"] == str(vault)
    assert script.stat().st_mode & stat.S_IXUSR
    assert mcp_config.read_text() == original_mcp
    assert not missing_target.exists()
    assert _check(report, "vault.structure") == {
        "id": "vault.structure",
        "feature": "Vault structure",
        "verdict": "OK",
        "detail": "All standard PARA directories exist after three safe repairs.",
        "heal": {
            "tier": 1,
            "action": (
                "Created 00-Inbox; regenerated core/paths.json; "
                "restored executable permission on .scripts/repo-tool.sh."
            ),
            "applied": True,
        },
    }
    assert _check(report, "mcp.registered")["heal"] == {
        "tier": 2,
        "action": "Repair the missing MCP target.",
        "applied": False,
    }
    allowed_new_paths = {
        "00-Inbox",
        "System/.doctor-last-run.json",
        "core/paths.json",
    }
    assert set(after) - set(before) <= allowed_new_paths
    assert {"00-Inbox", "core/paths.json"} <= set(after) - set(before)
    assert set(before) - set(after) == set()
    assert {path for path in before if before[path] != after[path]} == {".scripts/repo-tool.sh"}


def test_quick_mode_does_not_apply_t1_without_heal(monkeypatch, context):
    script = context.vault_root / ".scripts" / "repo-tool.sh"
    script.parent.mkdir()
    script.write_text("#!/bin/sh\n")
    script.chmod(0o644)
    _stub_probes(monkeypatch, exclude={"vault.structure"})
    monkeypatch.setattr(doctor, "_repo_shipped_executables", lambda _context: [script])

    report = doctor.collect(context=context)

    assert _check(report, "vault.structure")["verdict"] == "BROKEN"
    assert not (context.vault_root / "00-Inbox").exists()
    assert not (context.vault_root / "core" / "paths.json").exists()
    assert not script.stat().st_mode & stat.S_IXUSR


def test_partial_t1_failure_reports_applied_actions_and_breaks_doctor_self(monkeypatch, context):
    _stub_probes(monkeypatch, exclude={"vault.structure"})

    def fail_mode_inspection(_context):
        raise RuntimeError("git mode inspection failed")

    monkeypatch.setattr(doctor, "_repo_shipped_executables", fail_mode_inspection)

    report = doctor.collect(heal=True, context=context)

    structure = _check(report, "vault.structure")
    assert structure["verdict"] == "OK"
    assert structure["heal"]["applied"] is True
    assert "Created 00-Inbox" in structure["heal"]["action"]
    assert "regenerated core/paths.json" in structure["heal"]["action"]
    assert _check(report, "doctor.self")["verdict"] == "BROKEN"
    assert report["instruments"]["failed"] == [
        {"id": "doctor.self", "error": "Executable-mode heal failed: git mode inspection failed"}
    ]


def test_heal_does_not_overwrite_a_raising_structure_probe_with_ok(monkeypatch, context):
    _stub_probes(monkeypatch)
    monkeypatch.setattr(
        doctor,
        "_apply_t1_heals",
        lambda _context: (["regenerated core/paths.json"], []),
    )

    def explode(_context):
        raise RuntimeError("structure probe exploded")

    monkeypatch.setattr(doctor, "_probe_vault_structure", explode)

    report = doctor.collect(heal=True, context=context)

    structure = _check(report, "vault.structure")
    assert structure["verdict"] == "UNKNOWN"
    assert structure["heal"]["applied"] is True
    assert report["instruments"]["failed"] == [
        {"id": "vault.structure", "error": "structure probe exploded"}
    ]


def test_main_heal_flag_invokes_t1_and_still_returns_json(monkeypatch, context, capsys):
    _stub_probes(monkeypatch)
    calls = []
    monkeypatch.setattr(doctor, "_apply_t1_heals", lambda candidate: (calls.append(candidate) or [], []))

    assert doctor.main(["--heal"], context=context) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "quick"
    assert calls == [context]


def test_main_deep_flag_runs_the_deep_registry(monkeypatch, context, capsys):
    _stub_probes(monkeypatch)

    assert doctor.main(["--deep"], context=context) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "deep"
    assert [check["id"] for check in report["checks"]] == QUICK_IDS + DEEP_IDS


def test_cli_still_emits_json_when_yaml_is_not_importable(tmp_path):
    vault = tmp_path / "vault-without-yaml"
    (vault / "System").mkdir(parents=True)
    (vault / "System" / "user-profile.yaml").write_text("name: Test User\n")
    (vault / "System" / "pillars.yaml").write_text("pillars: []\n")
    settings = vault / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text('{"hooks": {}}\n')
    home = tmp_path / "empty-home"
    home.mkdir()
    env = dict(os.environ)
    env.update({"HOME": str(home), "VAULT_PATH": str(vault)})

    result = subprocess.run(
        [sys.executable, "-S", str(DOCTOR_PATH)],
        cwd=vault,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0
    report = json.loads(result.stdout)
    assert _check(report, "vault.configs")["verdict"] == "UNKNOWN"
    assert "yaml" in _check(report, "vault.configs")["detail"]
    assert _check(report, "python.env")["verdict"] == "BROKEN"


def test_vault_structure_maps_missing_and_complete_directories(context):
    missing = doctor._probe_vault_structure(context)
    assert missing.verdict == "BROKEN"
    assert missing.heal.tier == 1

    for name in doctor.PARA_PATH_NAMES:
        context.core_path(name).mkdir(parents=True, exist_ok=True)

    assert doctor._probe_vault_structure(context).verdict == "OK"


def test_vault_configs_maps_parse_errors_to_broken(context):
    _write_valid_configs(context)
    assert doctor._probe_vault_configs(context).verdict == "OK"

    (context.vault_root / "System" / "pillars.yaml").write_text("pillars: [\n")
    result = doctor._probe_vault_configs(context)
    assert result.verdict == "BROKEN"
    assert "pillars.yaml" in result.detail
    assert result.heal.tier == 3


def test_mcp_registered_distinguishes_never_onboarded_from_missing_after_onboarding(context):
    result = doctor._probe_mcp_registered(context)
    assert result.verdict == "OFF"

    (context.vault_root / "System" / ".onboarding-complete").touch()
    result = doctor._probe_mcp_registered(context)
    assert result.verdict == "BROKEN"


def test_mcp_registered_reports_missing_target_as_broken(context):
    target = context.vault_root / "core" / "mcp" / "missing_server.py"
    _write_mcp_config(
        context,
        {"missing": {"command": sys.executable, "args": [str(target)]}},
    )

    result = doctor._probe_mcp_registered(context)

    assert result.verdict == "BROKEN"
    assert "missing_server.py" in result.detail
    assert result.heal.tier == 2


def test_mcp_registered_maps_missing_registry_object_to_broken_t3(context):
    (context.vault_root / ".mcp.json").write_text("{}\n")

    result = doctor._probe_mcp_registered(context)

    assert result.verdict == "BROKEN"
    assert result.heal.tier == 3


def test_mcp_target_detection_ignores_external_package_and_data_arguments(context):
    entry = {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/allowed-directory"],
    }

    assert doctor._entry_targets(entry, context) == []


def test_mcp_registered_reports_missing_bare_command(monkeypatch, context):
    _write_mcp_config(context, {"external": {"command": "missing-mcp-command", "args": []}})
    monkeypatch.setattr(doctor.shutil, "which", lambda _command: None)

    result = doctor._probe_mcp_registered(context)

    assert result.verdict == "BROKEN"
    assert "missing-mcp-command" in result.detail


def test_mcp_registered_reports_non_executable_command_path(context):
    command = context.vault_root / "bin" / "server"
    command.parent.mkdir()
    command.write_text("#!/bin/sh\n")
    command.chmod(0o644)
    _write_mcp_config(context, {"local": {"command": str(command), "args": []}})

    result = doctor._probe_mcp_registered(context)

    assert result.verdict == "BROKEN"
    assert "not executable" in result.detail


def test_mcp_registered_accepts_remote_http_entries_without_a_command(context):
    _write_mcp_config(
        context,
        {"remote": {"type": "http", "url": "https://example.com/mcp"}},
    )

    assert doctor._probe_mcp_registered(context).verdict == "OK"


def test_mcp_registered_rejects_unsubstituted_live_template(context):
    _write_mcp_config(
        context,
        {
            "work-mcp": {
                "command": "{{VAULT_PATH}}/.venv/bin/python",
                "args": ["{{VAULT_PATH}}/core/mcp/work_server.py"],
            }
        },
    )

    result = doctor._probe_mcp_registered(context)

    assert result.verdict == "BROKEN"
    assert result.heal.tier == 2
    assert "template" in result.detail


def test_mcp_orphans_compares_server_targets_not_registry_names(context):
    mcp_dir = context.vault_root / "core" / "mcp"
    mcp_dir.mkdir(parents=True)
    alpha = mcp_dir / "alpha_server.py"
    alpha.touch()
    _write_mcp_config(
        context,
        {"friendly-alpha": {"command": sys.executable, "args": [str(alpha)]}},
    )
    assert doctor._probe_mcp_orphans(context).verdict == "OK"

    (mcp_dir / "beta_server.py").touch()
    result = doctor._probe_mcp_orphans(context)
    assert result.verdict == "BROKEN"
    assert "beta_server.py" in result.detail


def test_mcp_orphans_invalid_registry_becomes_unknown_in_the_runner(monkeypatch, context):
    mcp_dir = context.vault_root / "core" / "mcp"
    mcp_dir.mkdir(parents=True)
    (mcp_dir / "work_server.py").touch()
    (context.vault_root / ".mcp.json").write_text("{invalid\n")
    _stub_probes(monkeypatch, exclude={"mcp.orphans"})

    report = doctor.collect(context=context)

    assert _check(report, "mcp.orphans")["verdict"] == "UNKNOWN"
    assert report["instruments"]["failed"][0]["id"] == "mcp.orphans"


def test_python_env_maps_missing_interpreter_and_missing_imports_to_broken(monkeypatch, context):
    assert doctor._probe_python_env(context).verdict == "BROKEN"

    python = context.vault_root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)
    monkeypatch.setattr(doctor, "_python_import_check", lambda _python: (False, ["requests"]))
    missing_import = doctor._probe_python_env(context)
    assert missing_import.verdict == "BROKEN"
    assert "requests" in missing_import.detail

    monkeypatch.setattr(doctor, "_python_import_check", lambda _python: (True, []))
    assert doctor._probe_python_env(context).verdict == "OK"


def test_python_dependency_probe_imports_modules_instead_of_only_discovering_them(monkeypatch):
    def run(command, **_kwargs):
        assert "import_module" in command[2]
        return subprocess.CompletedProcess(command, 0, stdout="[]\n", stderr="")

    monkeypatch.setattr(doctor.subprocess, "run", run)

    assert doctor._python_import_check(Path(sys.executable)) == (True, [])


def test_relative_interpreter_paths_resolve_from_the_vault(context):
    python = context.vault_root / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n")
    python.chmod(0o755)

    assert doctor._resolved_interpreter(".venv/bin/python", context) == str(python)


def test_hooks_wired_detects_dangling_hook_files(context):
    settings = context.vault_root / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"type": "command", "command": "bash .claude/hooks/session-start.sh"}]}
                    ]
                }
            }
        )
    )

    broken = doctor._probe_hooks_wired(context)
    assert broken.verdict == "BROKEN"
    assert "session-start.sh" in broken.detail

    hook = context.vault_root / ".claude" / "hooks" / "session-start.sh"
    hook.parent.mkdir()
    hook.touch()
    assert doctor._probe_hooks_wired(context).verdict == "OK"


def test_hooks_wired_detects_missing_bare_executable(monkeypatch, context):
    hook = context.vault_root / ".claude" / "hooks" / "run.cjs"
    hook.parent.mkdir(parents=True)
    hook.touch()
    settings = context.vault_root / ".claude" / "settings.json"
    settings.write_text(json.dumps({"hooks": {"SessionStart": [{"command": "node .claude/hooks/run.cjs"}]}}))
    monkeypatch.setattr(doctor.shutil, "which", lambda _command: None)

    result = doctor._probe_hooks_wired(context)

    assert result.verdict == "BROKEN"
    assert "node" in result.detail


def test_hooks_invalid_settings_becomes_unknown_in_the_runner(monkeypatch, context):
    settings = context.vault_root / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text("{invalid\n")
    _stub_probes(monkeypatch, exclude={"hooks.wired"})

    report = doctor.collect(context=context)

    assert _check(report, "hooks.wired")["verdict"] == "UNKNOWN"
    assert report["instruments"]["failed"][0]["id"] == "hooks.wired"


def test_jobs_loaded_distinguishes_not_installed_from_unloaded(monkeypatch, context):
    assert doctor._probe_jobs_loaded(context).verdict == "OFF"

    plist = _write_plist(context, "com.dex.meeting-intel")
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_launchctl_domain_check", lambda: None)
    monkeypatch.setattr(doctor, "_plist_interpreter", lambda candidate: "/bin/bash" if candidate == plist else None)
    monkeypatch.setattr(doctor, "_launchctl_status", lambda _label: {"loaded": False, "last_exit_status": None})

    result = doctor._probe_jobs_loaded(context)
    assert result.verdict == "BROKEN"
    assert "not loaded" in result.detail
    assert result.heal.tier == 2


def test_jobs_loaded_checks_interpreter_exit_status_and_healthy_state(monkeypatch, context):
    _write_plist(context, "com.dex.meeting-intel")
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_launchctl_domain_check", lambda: None)
    monkeypatch.setattr(doctor, "_plist_interpreter", lambda _plist: "/missing/python")
    monkeypatch.setattr(
        doctor,
        "_launchctl_status",
        lambda _label: pytest.fail("launchctl must not run for a missing interpreter"),
    )
    missing = doctor._probe_jobs_loaded(context)
    assert missing.verdict == "BROKEN"
    assert missing.heal.tier == 3

    monkeypatch.setattr(doctor, "_plist_interpreter", lambda _plist: "/bin/bash")
    monkeypatch.setattr(
        doctor,
        "_launchctl_status",
        lambda _label: {"loaded": True, "last_exit_status": 9},
    )
    failed_run = doctor._probe_jobs_loaded(context)
    assert failed_run.verdict == "BROKEN"
    assert failed_run.heal.tier == 2

    monkeypatch.setattr(
        doctor,
        "_launchctl_status",
        lambda _label: {"loaded": True, "last_exit_status": 0},
    )
    assert doctor._probe_jobs_loaded(context).verdict == "OK"

    monkeypatch.setattr(
        doctor,
        "_launchctl_status",
        lambda _label: {"loaded": True, "last_exit_status": None},
    )
    assert doctor._probe_jobs_loaded(context).verdict == "UNKNOWN"


def test_jobs_loaded_maps_invalid_or_unsubstituted_plist_to_broken_t2(monkeypatch, context):
    plist = _write_plist(context, "com.dex.meeting-intel")
    with plist.open("wb") as handle:
        plistlib.dump(
            {
                "Label": "com.dex.meeting-intel",
                "ProgramArguments": ["/bin/bash", "{{VAULT_PATH}}/.scripts/dex-launcher.sh"],
            },
            handle,
        )
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_launchctl_domain_check", lambda: None)
    monkeypatch.setattr(doctor, "_plist_interpreter", lambda _plist: "/bin/bash")
    monkeypatch.setattr(
        doctor,
        "_launchctl_status",
        lambda _label: pytest.fail("launchctl must not run for an unsubstituted plist"),
    )

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "BROKEN"
    assert result.heal.tier == 2


def test_jobs_loaded_reports_missing_program_script_as_broken_t2(monkeypatch, context):
    plist = _write_plist(context, "com.dex.meeting-intel")
    missing_script = context.vault_root / ".scripts" / "missing.sh"
    with plist.open("wb") as handle:
        plistlib.dump(
            {"Label": "com.dex.meeting-intel", "ProgramArguments": ["/bin/bash", str(missing_script)]},
            handle,
        )
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_launchctl_domain_check", lambda: None)
    monkeypatch.setattr(doctor, "_plist_interpreter", lambda _plist: "/bin/bash")
    monkeypatch.setattr(
        doctor,
        "_launchctl_status",
        lambda _label: pytest.fail("launchctl must not run when the program script is missing"),
    )

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "BROKEN"
    assert result.heal.tier == 2


def test_launchctl_domain_failure_is_an_unknown_instrument(monkeypatch, context):
    _write_plist(context, "com.dex.meeting-intel")
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(
        doctor,
        "_launchctl_domain_check",
        lambda: (_ for _ in ()).throw(PermissionError("launchctl list is unavailable")),
    )

    with pytest.raises(PermissionError, match="launchctl list is unavailable"):
        doctor._probe_jobs_loaded(context)


def test_plist_sandbox_failure_propagates_for_unknown_mapping(monkeypatch, context):
    _write_plist(context, "com.dex.meeting-intel")
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    monkeypatch.setattr(doctor, "_launchctl_domain_check", lambda: None)
    monkeypatch.setattr(
        doctor,
        "_plist_data",
        lambda _plist: (_ for _ in ()).throw(PermissionError("sandbox denied plist read")),
    )

    with pytest.raises(PermissionError, match="sandbox denied plist read"):
        doctor._probe_jobs_loaded(context)


def test_empty_plutil_failure_is_unknown_not_malformed(monkeypatch, context):
    plist = _write_plist(context, "com.dex.meeting-intel")
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, stdout="", stderr=""),
    )

    with pytest.raises(PermissionError, match="plutil could not run"):
        doctor._plist_interpreter(plist)


def test_launchctl_status_adapter_parses_last_exit_status(monkeypatch):
    output = '{\n    "LastExitStatus" = 7;\n}\n'
    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 0, stdout=output, stderr=""),
    )

    assert doctor._launchctl_status("com.dex.test") == {"loaded": True, "last_exit_status": 7}

    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            1,
            stdout="",
            stderr="Could not find service",
        ),
    )
    assert doctor._launchctl_status("com.dex.missing") == {"loaded": False, "last_exit_status": None}


def test_jobs_loaded_degrades_to_unknown_off_macos(monkeypatch, context):
    _write_plist(context, "com.dex.meeting-intel")
    monkeypatch.setattr(doctor, "_is_macos", lambda: False)

    result = doctor._probe_jobs_loaded(context)

    assert result.verdict == "UNKNOWN"


@pytest.mark.parametrize(
    ("label", "expected_max_age"),
    [
        ("com.dex.meeting-intel", timedelta(hours=48)),
        ("com.dex.changelog-checker", timedelta(days=7)),
        ("com.dex.learning-review", timedelta(days=7)),
    ],
)
def test_freshness_thresholds_are_strictly_greater_than_the_limit(label, expected_max_age, context):
    _write_plist(context, label)
    policy = doctor.JOB_FRESHNESS[label]
    assert policy.max_age == expected_max_age
    log = context.vault_root / policy.log_path
    log.parent.mkdir(parents=True, exist_ok=True)
    log.touch()

    fresh_mtime = (NOW - expected_max_age + timedelta(seconds=1)).timestamp()
    os.utime(log, (fresh_mtime, fresh_mtime))
    assert doctor._probe_jobs_fresh(context).verdict == "OK"

    exact_mtime = (NOW - expected_max_age).timestamp()
    os.utime(log, (exact_mtime, exact_mtime))
    assert doctor._probe_jobs_fresh(context).verdict == "OK"

    stale_mtime = (NOW - expected_max_age - timedelta(seconds=1)).timestamp()
    os.utime(log, (stale_mtime, stale_mtime))
    result = doctor._probe_jobs_fresh(context)
    assert result.verdict == "BROKEN"
    assert datetime.fromtimestamp(stale_mtime, tz=timezone.utc).date().isoformat() in result.detail


def test_freshness_is_off_when_job_is_not_installed_even_if_log_is_stale(context):
    policy = doctor.JOB_FRESHNESS["com.dex.meeting-intel"]
    log = context.vault_root / policy.log_path
    log.parent.mkdir(parents=True)
    log.touch()
    stale_mtime = (NOW - timedelta(days=100)).timestamp()
    os.utime(log, (stale_mtime, stale_mtime))

    assert doctor._probe_jobs_fresh(context).verdict == "OFF"


def test_freshness_is_broken_when_installed_job_has_no_log(context):
    _write_plist(context, "com.dex.meeting-intel")

    result = doctor._probe_jobs_fresh(context)

    assert result.verdict == "BROKEN"
    assert "no run log" in result.detail


def test_preflight_queue_maps_server_and_queued_errors_to_broken(monkeypatch, context):
    monkeypatch.setattr(
        doctor,
        "_preflight_snapshot",
        lambda _context: ({"servers": {"work-mcp": {"status": "ok"}}}, []),
    )
    assert doctor._probe_preflight_queue(context).verdict == "OK"

    monkeypatch.setattr(
        doctor,
        "_preflight_snapshot",
        lambda _context: (
            {"servers": {"work-mcp": {"status": "error", "humanError": "Task Manager cannot start"}}},
            [],
        ),
    )
    assert doctor._probe_preflight_queue(context).verdict == "BROKEN"

    monkeypatch.setattr(
        doctor,
        "_preflight_snapshot",
        lambda _context: ({"servers": {}}, [{"acknowledged": False, "humanMessage": "Background failure"}]),
    )
    queued = doctor._probe_preflight_queue(context)
    assert queued.verdict == "BROKEN"
    assert queued.heal is None


def test_preflight_surfaces_unknown_registered_core_server(monkeypatch, context):
    server = context.vault_root / "core" / "mcp" / "session_memory_server.py"
    server.parent.mkdir(parents=True)
    server.touch()
    _write_mcp_config(
        context,
        {"session-memory": {"command": sys.executable, "args": [str(server)]}},
    )
    monkeypatch.setattr(
        doctor,
        "_preflight_snapshot",
        lambda _context: (
            {"servers": {"session-memory": {"status": "unknown", "note": "Not a core Dex server"}}},
            [],
        ),
    )

    result = doctor._probe_preflight_queue(context)

    assert result.verdict == "UNKNOWN"
    assert "session-memory" in result.detail


def test_granola_no_key_is_off_and_api_400_is_broken(monkeypatch, context):
    monkeypatch.setattr(doctor, "_granola_api_key", lambda _context: None)
    monkeypatch.setattr(
        doctor,
        "_granola_filtered_query",
        lambda _context: pytest.fail("query must not run without a key"),
    )
    assert doctor._probe_granola_query_path(context).verdict == "OFF"

    from core.mcp.granola_server import GranolaAPIError

    monkeypatch.setattr(doctor, "_granola_api_key", lambda _context: "grn_test")

    def api_400(_context):
        raise GranolaAPIError(status_code=400, body="created_after is invalid")

    monkeypatch.setattr(doctor, "_granola_filtered_query", api_400)
    result = doctor._probe_granola_query_path(context)
    assert result.verdict == "BROKEN"
    assert result.detail == (
        "Granola query failed (HTTP 400) — the connector may need updating. "
        "Response: created_after is invalid"
    )


def test_granola_key_adapter_reads_exported_quoted_env_file(monkeypatch, context):
    monkeypatch.delenv("GRANOLA_API_KEY", raising=False)
    (context.vault_root / ".env").write_text('export GRANOLA_API_KEY="grn_file_key"\n')

    assert doctor._granola_api_key(context) == "grn_file_key"

    monkeypatch.setenv("GRANOLA_API_KEY", "grn_environment_key")
    assert doctor._granola_api_key(context) == "grn_environment_key"


def test_granola_live_wrapper_uses_the_filtered_real_query_path(monkeypatch, context):
    from core.mcp import granola_server

    calls = {}

    def cutoff(days):
        calls["days"] = days
        return "cutoff"

    monkeypatch.setattr(granola_server, "_cutoff_iso", cutoff)

    def list_notes(**kwargs):
        calls["list"] = kwargs
        return []

    monkeypatch.setattr(granola_server, "_list_notes", list_notes)

    doctor._granola_filtered_query(context)

    assert calls == {
        "days": 7,
        "list": {"created_after": "cutoff", "max_notes": 1, "page_size": 1},
    }


def test_calendar_permission_boundaries_and_configured_name(monkeypatch, context):
    _write_valid_configs(context)
    monkeypatch.setattr(doctor, "_calendar_permission_status", lambda _context: "not_determined")
    monkeypatch.setattr(
        doctor,
        "_calendar_list_result",
        lambda _context: pytest.fail("unused calendar must not prompt for permission"),
    )
    assert doctor._probe_calendar_access(context).verdict == "OFF"

    (context.vault_root / "System" / "user-profile.yaml").write_text(
        "calendar:\n  work_calendar: Team Calendar\n"
    )
    assert doctor._probe_calendar_access(context).verdict == "BROKEN"

    monkeypatch.setattr(doctor, "_calendar_permission_status", lambda _context: "denied")
    assert doctor._probe_calendar_access(context).verdict == "BROKEN"

    monkeypatch.setattr(doctor, "_calendar_permission_status", lambda _context: "authorized")
    monkeypatch.setattr(
        doctor,
        "_calendar_list_result",
        lambda _context: {"success": True, "calendars": ["Home", "Holidays"]},
    )
    missing = doctor._probe_calendar_access(context)
    assert missing.verdict == "BROKEN"
    assert "Home, Holidays" in missing.detail

    monkeypatch.setattr(
        doctor,
        "_calendar_list_result",
        lambda _context: {"success": True, "calendars": ["Team Calendar", "Home"]},
    )
    assert doctor._probe_calendar_access(context).verdict == "OK"


def test_calendar_sandbox_failure_is_unknown(monkeypatch, context):
    _write_valid_configs(context, calendar="Team Calendar")
    monkeypatch.setattr(doctor, "_calendar_permission_status", lambda _context: "authorized")
    monkeypatch.setattr(
        doctor,
        "_calendar_list_result",
        lambda _context: {"success": False, "error": "sandbox: Operation not permitted"},
    )

    assert doctor._probe_calendar_access(context).verdict == "UNKNOWN"


def test_calendar_permission_adapter_preserves_eventkit_status(monkeypatch, context):
    monkeypatch.setattr(doctor, "_is_macos", lambda: True)
    for raw_status, expected in (
        ("0\n", "not_determined"),
        ("1\n", "restricted"),
        ("2\n", "denied"),
        ("3\n", "authorized"),
    ):
        monkeypatch.setattr(
            doctor.subprocess,
            "run",
            lambda command, _raw=raw_status, **_kwargs: subprocess.CompletedProcess(
                command,
                0,
                stdout=_raw,
                stderr="",
            ),
        )
        assert doctor._calendar_permission_status(context) == expected


def test_calendar_list_adapter_calls_the_real_mcp_helper(monkeypatch, context):
    from core.mcp import calendar_server

    expected = {"success": True, "calendars": ["Team Calendar"]}
    monkeypatch.setattr(calendar_server, "_get_calendar_list_result", lambda: expected)

    assert doctor._calendar_list_result(context) is expected


def test_qmd_respects_opt_in_and_reports_live_status_failures(monkeypatch, context):
    _write_mcp_config(context, {})
    assert doctor._probe_qmd_live(context).verdict == "OFF"

    _write_mcp_config(context, {"qmd": {"command": "qmd", "args": ["mcp"]}})
    monkeypatch.setattr(doctor, "_qmd_binary", lambda _context: None)
    assert doctor._probe_qmd_live(context).verdict == "BROKEN"

    monkeypatch.setattr(doctor, "_qmd_binary", lambda _context: "/tmp/qmd")
    monkeypatch.setattr(doctor, "_qmd_status", lambda _binary: (False, "index metadata is corrupt"))
    failed = doctor._probe_qmd_live(context)
    assert failed.verdict == "BROKEN"
    assert "index metadata is corrupt" in failed.detail

    monkeypatch.setattr(doctor, "_qmd_status", lambda _binary: (False, "GPU unavailable in sandbox"))
    assert doctor._probe_qmd_live(context).verdict == "UNKNOWN"

    monkeypatch.setattr(doctor, "_qmd_status", lambda _binary: (True, "3 collections"))
    assert doctor._probe_qmd_live(context).verdict == "OK"


def test_qmd_adapters_use_existing_discovery_and_status_command(monkeypatch, context):
    from core.utils import qmd_query

    monkeypatch.setattr(qmd_query, "_find_qmd", lambda: "/tmp/qmd")
    assert doctor._qmd_binary(context) == "/tmp/qmd"

    observed = []

    def run(command, **_kwargs):
        observed.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="healthy\n", stderr="")

    monkeypatch.setattr(doctor.subprocess, "run", run)
    assert doctor._qmd_status("/tmp/qmd") == (True, "healthy")
    assert observed == [["/tmp/qmd", "status"]]

    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, stdout="", stderr="status failed\n"),
    )
    assert doctor._qmd_status("/tmp/qmd") == (False, "status failed")


def test_integrations_check_only_enabled_entries(monkeypatch, context):
    assert doctor._probe_integrations_enabled(context).verdict == "OFF"

    config = context.vault_root / "System" / "integrations" / "config.yaml"
    config.parent.mkdir()
    config.write_text("teams:\n  enabled: true\nnotion:\n  enabled: false\n")
    calls = []
    monkeypatch.setattr(
        doctor,
        "_integration_health_check",
        lambda _context, name, _settings: calls.append(name) or (False, "sign-in expired"),
    )
    broken = doctor._probe_integrations_enabled(context)
    assert broken.verdict == "BROKEN"
    assert calls == ["teams"]

    monkeypatch.setattr(
        doctor,
        "_integration_health_check",
        lambda _context, _name, _settings: (False, "sandbox: Operation not permitted"),
    )
    assert doctor._probe_integrations_enabled(context).verdict == "UNKNOWN"

    monkeypatch.setattr(
        doctor,
        "_integration_health_check",
        lambda _context, _name, _settings: (True, "connected"),
    )
    assert doctor._probe_integrations_enabled(context).verdict == "OK"


def test_integrations_support_legacy_enabled_map(monkeypatch, context):
    config = context.vault_root / "System" / "integrations" / "config.yaml"
    config.parent.mkdir()
    config.write_text("enabled:\n  slack: true\n  notion: false\n")
    calls = []
    monkeypatch.setattr(
        doctor,
        "_integration_health_check",
        lambda _context, name, _settings: calls.append(name) or (True, "connected"),
    )

    assert doctor._probe_integrations_enabled(context).verdict == "OK"
    assert calls == ["slack"]


def test_enabled_integration_without_existing_checker_is_unknown(context):
    config = context.vault_root / "System" / "integrations" / "config.yaml"
    config.parent.mkdir()
    config.write_text("teams:\n  enabled: true\n")

    result = doctor._probe_integrations_enabled(context)

    assert result.verdict == "UNKNOWN"
    assert "no existing teams connection health checker" in result.detail


def test_integration_adapter_runs_configured_connection_checker(monkeypatch, context):
    checker = context.vault_root / "teams" / "connection.cjs"
    checker.parent.mkdir()
    checker.touch()
    monkeypatch.setattr(doctor.shutil, "which", lambda command: "/usr/local/bin/node" if command == "node" else None)
    observed = []

    def run(command, **kwargs):
        observed.append((command, kwargs["cwd"]))
        return subprocess.CompletedProcess(command, 0, stdout='{"connected": true}\n', stderr="")

    monkeypatch.setattr(doctor.subprocess, "run", run)

    assert doctor._integration_health_check(
        context,
        "teams",
        {"health_checker": str(checker)},
    ) == (True, '{"connected": true}')
    assert observed == [(["/usr/local/bin/node", str(checker)], context.vault_root)]

    monkeypatch.setattr(
        doctor.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, stdout="", stderr="not connected\n"),
    )
    assert doctor._integration_health_check(
        context,
        "teams",
        {"health_checker": str(checker)},
    ) == (False, "not connected")


def test_mcp_importable_runs_registered_core_servers_in_subprocess(monkeypatch, context):
    mcp_dir = context.vault_root / "core" / "mcp"
    mcp_dir.mkdir(parents=True)
    server = mcp_dir / "work_server.py"
    server.touch()
    _write_mcp_config(
        context,
        {"work-mcp": {"command": sys.executable, "args": [str(server)]}},
    )
    calls = []
    monkeypatch.setattr(
        doctor,
        "_mcp_import_check",
        lambda _context, module, interpreter: calls.append((module, interpreter)) or (True, ""),
    )

    assert doctor._probe_mcp_importable(context).verdict == "OK"
    assert calls == [("core.mcp.work_server", sys.executable)]

    monkeypatch.setattr(
        doctor,
        "_mcp_import_check",
        lambda _context, _module, _interpreter: (False, "ImportError: missing package"),
    )
    result = doctor._probe_mcp_importable(context)
    assert result.verdict == "BROKEN"
    assert "ImportError" in result.detail


def test_mcp_import_subprocess_uses_an_ephemeral_vault(monkeypatch, context):
    observed = {}

    def run(command, **kwargs):
        sandbox = Path(kwargs["env"]["VAULT_PATH"])
        observed["sandbox"] = sandbox
        assert sandbox != context.vault_root
        assert sandbox.is_dir()
        assert "import_module" in command[2]
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(doctor.subprocess, "run", run)

    assert doctor._mcp_import_check(context, "core.mcp.resume_server", sys.executable) == (True, "exit 0")
    assert not observed["sandbox"].exists()
