"""Safety contract for the advisory native Windows install journey.

The job is a signal, not a merge gate. These tests lock the properties that
keep it from starving Dex CI, leaking credentials, or accidentally becoming a
required check named quality / tests / portable-plugin-platforms.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/windows-install.yml"
CI_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/ci.yml"
PROTECTION_SCRIPT = REPO_ROOT / "scripts/configure-branch-protection.sh"
JOURNEY_SCRIPT = REPO_ROOT / "scripts/run-windows-install-journey.sh"
LIFECYCLE_SCRIPT = REPO_ROOT / "scripts/run-windows-lifecycle-journey.py"
PINNED_ACTION = re.compile(r"^[^@]+@[0-9a-f]{40}$")
REQUIRED_CI_JOBS = ("quality", "tests", "portable-plugin-platforms")
ENGINE_TEST_FILES = (
    "core/tests/test_transaction_core.py",
    "core/tests/test_adoption_transaction.py",
    "core/tests/test_provision_transaction.py",
    "core/tests/test_lifecycle_bridge.py",
    "core/tests/test_lifecycle_official_capabilities.py",
    "core/tests/test_lifecycle_relocated_vault.py",
    "core/tests/test_lifecycle_service_contract.py",
    "core/tests/test_lifecycle_topology_migration.py",
)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    return workflow.get("on", workflow.get(True))


def _journey_job() -> dict:
    return _load(WORKFLOW_PATH)["jobs"]["windows-install-journey"]


def _named_steps() -> dict[str, dict]:
    return {
        step["name"]: step
        for step in _journey_job()["steps"]
        if "name" in step
    }


def test_workflow_is_separate_from_required_dex_ci() -> None:
    workflow = _load(WORKFLOW_PATH)
    ci = _load(CI_WORKFLOW_PATH)

    assert workflow["name"] == "Windows install"
    assert set(workflow["jobs"]) == {"windows-install-journey"}
    for job_name in REQUIRED_CI_JOBS:
        assert job_name in ci["jobs"]
        assert job_name not in workflow["jobs"]
    assert "windows-install" not in ci["jobs"]
    assert "windows-install-journey" not in ci["jobs"]


def test_required_release_gates_do_not_depend_on_this_job() -> None:
    ci = _load(CI_WORKFLOW_PATH)
    for job_name in ("build-release", "build-release-beta"):
        assert ci["jobs"][job_name]["needs"] == [
            "quality",
            "test-results",
            "portable-plugin-platforms",
        ]


def test_branch_protection_floor_does_not_require_windows_install() -> None:
    source = PROTECTION_SCRIPT.read_text(encoding="utf-8")
    match = re.search(
        r"^REQUIRED_CONTEXTS=\(\n(?P<body>(?:  \"[^\"]+\"\n)+)\)$",
        source,
        re.MULTILINE,
    )
    assert match is not None
    floor = re.findall(r'^  "([^"]+)"$', match.group("body"), re.MULTILINE)
    assert "windows-install" not in floor
    assert "windows-install-journey" not in floor
    assert "quality" in floor
    assert "test-results" in floor


def test_job_is_advisory_windows_latest_and_bounded() -> None:
    job = _journey_job()
    assert job["runs-on"] == "windows-latest"
    assert job["continue-on-error"] is True
    assert 1 <= job["timeout-minutes"] <= 40
    assert "strategy" not in job


def test_concurrency_cancels_stale_prs_without_grouping_main_by_ref() -> None:
    workflow = _load(WORKFLOW_PATH)
    group = workflow["concurrency"]["group"]
    assert "windows-install-" in group
    assert "github.event.pull_request.number" in group
    assert "github.run_id" in group
    assert "github.ref" not in group
    assert workflow["concurrency"]["cancel-in-progress"] is True
    assert "stable-public-route" not in group


def test_triggers_are_pull_request_main_and_manual_only() -> None:
    triggers = _triggers(_load(WORKFLOW_PATH))
    assert set(triggers) == {"pull_request", "push", "workflow_dispatch"}
    assert triggers["push"] == {"branches": ["main"]}
    assert "pull_request_target" not in triggers
    assert "merge_group" not in triggers


def test_token_is_read_only_and_checkout_cannot_push() -> None:
    workflow = _load(WORKFLOW_PATH)
    job = _journey_job()
    source = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert workflow["permissions"] == {"contents": "read"}
    assert "secrets." not in source
    assert "github.token" not in source
    assert "pull_request_target" not in source
    assert all(
        line.strip() in {'GITHUB_TOKEN: ""', "GITHUB_TOKEN: ''"}
        or "GITHUB_TOKEN" not in line
        for line in source.splitlines()
    )

    checkout = next(
        step for step in job["steps"] if str(step.get("uses", "")).startswith("actions/checkout@")
    )
    assert checkout["with"]["persist-credentials"] is False
    assert checkout["with"]["fetch-depth"] == 1


def test_actions_are_sha_pinned() -> None:
    for step in _journey_job()["steps"]:
        uses = step.get("uses")
        if uses:
            assert PINNED_ACTION.fullmatch(uses), uses


def test_setup_python_covers_312_and_313() -> None:
    versions = [
        step["with"]["python-version"]
        for step in _journey_job()["steps"]
        if str(step.get("uses", "")).startswith("actions/setup-python@")
    ]
    assert versions.count("3.12") >= 2
    assert "3.13" in versions


def test_runs_real_install_paths_and_engine_suites() -> None:
    steps = _named_steps()
    cygwin = steps["install.sh Git Bash OSTYPE=cygwin with Store python3 stub"]
    msys = steps["install.sh Git Bash OSTYPE=msys then activate/adopt/rewind"]
    ps1 = steps["install.ps1 in PowerShell"]
    engine_312 = steps["Transaction engine and lifecycle tests (Python 3.12)"]
    engine_313 = steps["Transaction engine and lifecycle tests (Python 3.13)"]

    assert cygwin["shell"] == "bash"
    assert "install-cygwin-stub" in cygwin["run"]
    assert cygwin["continue-on-error"] is True
    assert cygwin["env"]["GITHUB_TOKEN"] == ""

    assert msys["shell"] == "bash"
    assert "install-msys-journey" in msys["run"]
    assert msys["continue-on-error"] is True

    assert ps1["shell"] == "pwsh"
    assert r"Dex Vault\install-ps1" in ps1["run"]
    assert r".\install.ps1" in ps1["run"]
    assert ps1["continue-on-error"] is True

    for engine in (engine_312, engine_313):
        assert engine["shell"] == "bash"
        assert engine["continue-on-error"] is True
        for path in ENGINE_TEST_FILES:
            assert path in engine["run"]
        assert '-m "not fuzz"' in engine["run"]


def test_journey_script_covers_store_stub_spaced_path_and_both_ostypes() -> None:
    source = JOURNEY_SCRIPT.read_text(encoding="utf-8")
    assert "Dex Vault" in source
    assert "exit 9009" in source
    assert "Microsoft Store" in source
    assert "run_install_sh cygwin" in source
    assert "run_install_sh msys" in source
    assert "run-windows-lifecycle-journey.py" in source
    subprocess.run(["bash", "-n", str(JOURNEY_SCRIPT)], check=True)


def test_lifecycle_journey_script_activates_adopts_rewinds_and_scans_crlf() -> None:
    source = LIFECYCLE_SCRIPT.read_text(encoding="utf-8")
    assert "prepare_vault" in source
    assert "execute_approved_adoption" in source
    assert "rewind_adoption_by_receipt" in source
    assert "\\r\\n" in source or r"\r\n" in source


def test_crlf_scan_flags_crlf_under_system_dex(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "windows_lifecycle_journey",
        LIFECYCLE_SCRIPT,
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    vault = tmp_path / "vault"
    dex = vault / "System" / ".dex"
    dex.mkdir(parents=True)
    (dex / "ok.json").write_bytes(b'{"a":1}\n')
    assert module._scan_crlf(vault) == []
    (dex / "bad.json").write_bytes(b'{"a":1}\r\n')
    assert "System/.dex/bad.json" in module._scan_crlf(vault)


def test_verdict_fails_the_job_when_any_leg_fails() -> None:
    verdict = _named_steps()["Windows install verdict"]
    assert verdict["if"] == "always()"
    assert "INSTALL_CYGWIN" in verdict["env"]
    assert "ENGINE313" in verdict["env"]
    assert "exit 1" in verdict["run"]


def test_header_says_the_job_must_become_required_later() -> None:
    source = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "not a merge gate" in source
    assert "Follow-up" in source
    assert "portable-plugin-platforms" in source
    assert "windows-install-journey" in source
