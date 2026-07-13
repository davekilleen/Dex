"""Direct contract and safety tests for the shipped smoke runner."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

from core.utils import smoke

REPO_ROOT = Path(__file__).resolve().parents[2]


def _write_valid_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    (vault / "System" / "integrations").mkdir(parents=True)
    (vault / "03-Tasks").mkdir()
    (vault / ".claude").mkdir()
    (vault / "System" / "user-profile.yaml").write_text(
        "name: Smoke User\nanalytics:\n  enabled: false\n",
        encoding="utf-8",
    )
    (vault / "System" / "pillars.yaml").write_text("pillars: []\n", encoding="utf-8")
    (vault / "System" / ".onboarding-complete").write_text("{}\n", encoding="utf-8")
    (vault / "System" / "integrations" / "config.yaml").write_text(
        "enabled:\n  slack: false\nhooks: {}\n",
        encoding="utf-8",
    )
    (vault / "03-Tasks" / "Tasks.md").write_text(
        "# Tasks\n\n- [ ] Existing task ^task-20260711-001\n",
        encoding="utf-8",
    )
    (vault / ".mcp.json").write_text('{"mcpServers": {}}\n', encoding="utf-8")
    (vault / ".claude" / "settings.json").write_text('{"hooks": {}}\n', encoding="utf-8")
    return vault


def _write_fresh_release_vault(tmp_path: Path) -> Path:
    """Materialize shipped surfaces without any onboarding-created state."""
    vault = tmp_path / "fresh-release"
    (vault / "System").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "System" / ".mcp.json.example", vault / "System" / ".mcp.json.example")

    skill = vault / ".claude" / "skills" / "shipped-skill" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: shipped-skill\ndescription: Fresh release smoke fixture.\n---\n",
        encoding="utf-8",
    )
    hook = vault / ".claude" / "hooks" / "fresh-release.sh"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    hook.chmod(0o755)
    (vault / ".claude" / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"command": "bash .claude/hooks/fresh-release.sh"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    return vault


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode())
        digest.update(str(stat.S_IMODE(path.stat().st_mode)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


def _definition(journey_id: str, timeout: float = 5.0) -> smoke.JourneyDefinition:
    return smoke.JourneyDefinition(journey_id, timeout)


def _release_repo(tmp_path: Path, *, release_validators: str | None = None) -> Path:
    repo = tmp_path / "release-repo"
    repo.mkdir()
    shutil.copytree(
        REPO_ROOT / "core",
        repo / "core",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "paths.json"),
    )
    if release_validators is not None:
        (repo / "core" / "utils" / "validators.py").write_text(
            release_validators,
            encoding="utf-8",
        )
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Smoke Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "smoke@example.test"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "add", "--", "core"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "release fixture"], cwd=repo, check=True)
    subprocess.run(
        ["git", "update-ref", "refs/remotes/upstream/release", "HEAD"],
        cwd=repo,
        check=True,
    )
    if release_validators is not None:
        shutil.copy2(
            REPO_ROOT / "core" / "utils" / "validators.py",
            repo / "core" / "utils" / "validators.py",
        )
        subprocess.run(
            ["git", "add", "--", "core/utils/validators.py"],
            cwd=repo,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "--quiet", "-m", "head fixture"],
            cwd=repo,
            check=True,
        )
    return repo


def test_report_schema_exit_zero_and_no_live_write(tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    before = _tree_hash(vault)

    run = smoke.run_smoke(vault_root=vault, repo_root=REPO_ROOT)

    assert run.exit_code == 0
    assert run.harness_failed is False
    assert set(run.report) == {"schema_version", "generated_at", "journeys", "summary"}
    assert run.report["schema_version"] == 1
    assert run.report["generated_at"].endswith("+00:00")
    assert [journey["id"] for journey in run.report["journeys"]] == [
        "configs",
        "task_lifecycle",
        "mcp_startup",
        "skills",
        "hooks",
    ]
    assert run.report["summary"] == {"ok": 2, "broken": 0, "unknown": 1, "off": 2}
    for journey in run.report["journeys"]:
        assert set(journey) == {"id", "verdict", "detail", "duration_ms"}
        assert journey["verdict"] in smoke.VERDICTS
        assert isinstance(journey["detail"], str) and journey["detail"]
        assert isinstance(journey["duration_ms"], int) and journey["duration_ms"] >= 0
    assert _tree_hash(vault) == before


def test_fresh_release_without_onboarding_or_python_packages_has_clean_verdicts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = _write_fresh_release_vault(tmp_path)
    missing_site_packages = str(tmp_path / "missing-site-packages")
    monkeypatch.setattr(
        smoke.sysconfig,
        "get_paths",
        lambda: {"purelib": missing_site_packages, "platlib": missing_site_packages},
    )

    run = smoke.run_smoke(vault_root=vault, repo_root=REPO_ROOT)

    journeys = {journey["id"]: journey for journey in run.report["journeys"]}
    assert run.exit_code == 0
    assert run.harness_failed is False
    assert [journeys[journey_id]["verdict"] for journey_id in ("configs", "task_lifecycle", "mcp_startup")] == [
        "OFF",
        "OFF",
        "OFF",
    ]
    for journey_id in ("configs", "task_lifecycle", "mcp_startup"):
        assert "not set up yet — complete onboarding first" in journeys[journey_id]["detail"]
    assert journeys["skills"]["verdict"] == "UNKNOWN"
    assert "Python packages not installed" in journeys["skills"]["detail"]
    assert journeys["hooks"]["verdict"] == "OK"
    assert all("harness failed" not in journey["detail"] for journey in journeys.values())


def test_ambient_tmpdir_inside_vault_is_never_used(monkeypatch, tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    monkeypatch.setenv("TMPDIR", str(vault))
    monkeypatch.setattr(smoke.tempfile, "tempdir", None)
    observed_parents = []
    original = smoke.tempfile.TemporaryDirectory

    def temporary_directory(*args, **kwargs):
        observed_parents.append(Path(kwargs["dir"]).resolve())
        return original(*args, **kwargs)

    monkeypatch.setattr(smoke.tempfile, "TemporaryDirectory", temporary_directory)

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=REPO_ROOT,
        journey_definitions=(_definition("configs"),),
    )

    assert run.exit_code == 0
    assert observed_parents
    for parent in observed_parents:
        try:
            parent.relative_to(vault.resolve())
        except ValueError:
            pass
        else:
            raise AssertionError(f"smoke temp parent was inside the vault: {parent}")
    assert not list(vault.glob("dex-smoke-*"))


def test_early_harness_failure_keeps_json_schema_and_exits_two(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    vault = _write_valid_vault(tmp_path)
    monkeypatch.setattr(
        smoke,
        "_safe_temporary_parent",
        lambda _source: (_ for _ in ()).throw(OSError("no safe temp root")),
    )

    exit_code = smoke.main(
        ["--json"],
        vault_root=vault,
        repo_root=REPO_ROOT,
        journey_definitions=(_definition("configs"),),
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert report["schema_version"] == 1
    assert report["summary"] == {"ok": 0, "broken": 0, "unknown": 1, "off": 0}
    assert report["journeys"][0]["verdict"] == "UNKNOWN"
    assert "no safe temp root" in report["journeys"][0]["detail"]


def test_main_exit_one_for_a_broken_journey(tmp_path: Path, capsys) -> None:
    vault = _write_valid_vault(tmp_path)
    repo = _release_repo(tmp_path)
    (vault / "System" / "pillars.yaml").write_text("pillars: [\n", encoding="utf-8")

    exit_code = smoke.main(
        ["--json"],
        vault_root=vault,
        repo_root=repo,
        journey_definitions=(_definition("configs"),),
    )
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert report["summary"] == {"ok": 0, "broken": 1, "unknown": 0, "off": 0}


def test_ledger_writes_latest_and_versioned_history(tmp_path: Path, capsys) -> None:
    vault = _write_valid_vault(tmp_path)

    exit_code = smoke.main(
        ["--json", "--ledger"],
        vault_root=vault,
        repo_root=REPO_ROOT,
        journey_definitions=(_definition("configs"),),
    )
    emitted = json.loads(capsys.readouterr().out)
    latest = json.loads((vault / "System" / ".smoke-last-run.json").read_text())
    history = [
        json.loads(line)
        for line in (vault / "System" / ".dex" / "smoke-history.jsonl").read_text().splitlines()
    ]

    assert exit_code == 0
    assert latest == emitted
    expected_version = json.loads((REPO_ROOT / "package.json").read_text())["version"]
    assert history[0] == {**emitted, "dex_version": expected_version}


def test_ledger_history_rotates_at_cap(tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    history_path = vault / "System" / ".dex" / "smoke-history.jsonl"
    history_path.parent.mkdir(parents=True)
    old_entries = [
        json.dumps({"schema_version": 1, "generated_at": f"old-{index}"})
        for index in range(smoke.HISTORY_LIMIT)
    ]
    history_path.write_text("\n".join(old_entries) + "\n")
    report = {
        "schema_version": 1,
        "generated_at": "new",
        "journeys": [],
        "summary": {"ok": 0, "broken": 0, "unknown": 0, "off": 0},
    }

    smoke._write_ledger(report, vault, REPO_ROOT)

    entries = [json.loads(line) for line in history_path.read_text().splitlines()]
    assert len(entries) == smoke.HISTORY_LIMIT
    assert entries[0]["generated_at"] == "old-1"
    assert entries[-1]["generated_at"] == "new"


def test_atomic_ledger_failure_preserves_target_and_removes_temp(
    monkeypatch,
    tmp_path: Path,
) -> None:
    target = tmp_path / "ledger.json"
    target.write_text("original\n")

    def fail_replace(_source, _target):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(smoke.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated replace failure"):
        smoke._atomic_write(target, "replacement\n")

    assert target.read_text() == "original\n"
    assert list(tmp_path.glob(".ledger.json.*.tmp")) == []


def test_json_without_ledger_writes_nothing(tmp_path: Path, capsys) -> None:
    vault = _write_valid_vault(tmp_path)

    exit_code = smoke.main(
        ["--json"],
        vault_root=vault,
        repo_root=REPO_ROOT,
        journey_definitions=(_definition("configs"),),
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["summary"]["ok"] == 1
    assert not (vault / "System" / ".smoke-last-run.json").exists()
    assert not (vault / "System" / ".dex" / "smoke-history.jsonl").exists()


def test_head_runner_generation_stays_coherent_when_release_is_older(tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    repo = _release_repo(
        tmp_path,
        release_validators='"""Older release validator surface."""\n',
    )

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=repo,
        journey_definitions=(
            _definition("configs"),
            _definition("task_lifecycle", 8.0),
        ),
    )

    configs, task_lifecycle = run.report["journeys"]
    assert run.harness_failed is False
    assert run.exit_code == 0
    assert configs["verdict"] == "OK"
    assert task_lifecycle["verdict"] == "UNKNOWN"
    assert "Dex-owned core differs from" in task_lifecycle["detail"]


def test_release_snapshot_is_absent_from_every_child_pythonpath(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = _write_valid_vault(tmp_path)
    repo = _release_repo(tmp_path)
    observed = []
    original = smoke._run_json_process

    def capture(command, **kwargs):
        observed.append((list(command), dict(kwargs["env"])))
        return original(command, **kwargs)

    monkeypatch.setattr(smoke, "_run_json_process", capture)

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=repo,
        journey_definitions=(_definition("configs"),),
    )

    assert run.exit_code == 0
    assert len(observed) == 2
    for command, env in observed:
        python_paths = env["PYTHONPATH"].split(os.pathsep)
        runner_root = Path(command[2]).parents[2]
        release_root = Path(command[command.index("--release-root") + 1])
        assert python_paths[0] == str(runner_root)
        assert str(release_root) not in python_paths


def test_runner_materialization_excludes_untracked_core_files(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    tracked = source / "core" / "mcp" / "work_server.py"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("# tracked runner module\n", encoding="utf-8")
    (source / "core" / "__init__.py").write_text("", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Smoke Test"], cwd=source, check=True)
    subprocess.run(
        ["git", "config", "user.email", "smoke@example.test"],
        cwd=source,
        check=True,
    )
    subprocess.run(["git", "add", "--", "core"], cwd=source, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "tracked fixture"], cwd=source, check=True)
    evil_shadow = source / "core" / "utils" / "evil_shadow.py"
    evil_shadow.parent.mkdir(parents=True, exist_ok=True)
    evil_shadow.write_text("raise RuntimeError('untracked code executed')\n", encoding="utf-8")
    evil_server = source / "core" / "mcp" / "evil_server.py"
    evil_server.write_text("raise RuntimeError('untracked code executed')\n", encoding="utf-8")
    monkeypatch.setattr(smoke, "RUNNER_ROOT", source)

    runner = smoke._materialize_runner(tmp_path / "runner")

    assert (runner / "core" / "mcp" / "work_server.py").is_file()
    assert not (runner / "core" / "utils" / "evil_shadow.py").exists()
    assert not (runner / "core" / "mcp" / "evil_server.py").exists()


def test_release_gate_ignores_untracked_runtime_artifacts(monkeypatch, tmp_path: Path) -> None:
    repo = _release_repo(tmp_path)
    release_root = tmp_path / "release"
    reference, detail = smoke._materialize_release_core(
        repo,
        release_root,
        timeout_seconds=3.0,
    )
    assert detail == "verified installed release snapshot"
    assert reference is not None

    (repo / "core" / "paths.json").write_text("{}\n", encoding="utf-8")
    cache = repo / "core" / "__pycache__"
    cache.mkdir()
    (cache / "x.pyc").write_bytes(b"runtime cache")
    monkeypatch.setattr(smoke, "RUNNER_ROOT", repo)

    assert smoke._release_execution_reason(repo, release_root, reference) is None


def test_runtime_artifacts_and_untracked_code_do_not_enter_verified_journeys(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = _write_valid_vault(tmp_path)
    repo = _release_repo(tmp_path)
    (vault / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "work-mcp": {
                        "command": sys.executable,
                        "args": [str(repo / "core" / "mcp" / "work_server.py")],
                        "env": {"VAULT_PATH": str(vault)},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (repo / "core" / "paths.json").write_text("{}\n", encoding="utf-8")
    cache = repo / "core" / "__pycache__"
    cache.mkdir()
    (cache / "x.pyc").write_bytes(b"runtime cache")
    evil_shadow = repo / "core" / "utils" / "evil_shadow.py"
    evil_shadow.write_text("raise RuntimeError('untracked code executed')\n", encoding="utf-8")
    evil_server = repo / "core" / "mcp" / "evil_server.py"
    evil_server.write_text("raise RuntimeError('untracked code executed')\n", encoding="utf-8")
    monkeypatch.setattr(smoke, "RUNNER_ROOT", repo)
    original = smoke._run_smoke_journeys
    snapshot_checked = False

    def run_with_snapshot_check(**kwargs):
        nonlocal snapshot_checked
        runner_root = kwargs["runner_root"]
        assert not (runner_root / evil_shadow.relative_to(repo)).exists()
        assert not (runner_root / evil_server.relative_to(repo)).exists()
        assert not (runner_root / "core" / "paths.json").exists()
        assert not (runner_root / "core" / "__pycache__" / "x.pyc").exists()
        snapshot_checked = True
        return original(**kwargs)

    monkeypatch.setattr(smoke, "_run_smoke_journeys", run_with_snapshot_check)

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=repo,
        journey_definitions=(
            _definition("task_lifecycle", 8.0),
            _definition("mcp_startup", 8.0),
        ),
    )

    assert snapshot_checked is True
    assert run.harness_failed is False
    assert run.exit_code == 0
    assert [journey["verdict"] for journey in run.report["journeys"]] == ["OK", "OK"]


def test_runner_symlink_swap_cannot_touch_an_external_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    tracked = source / "core" / "utils" / "smoke.py"
    tracked.parent.mkdir(parents=True)
    tracked.write_text("# tracked runner module\n", encoding="utf-8")
    (source / "core" / "__init__.py").write_text("", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Smoke Test"], cwd=source, check=True)
    subprocess.run(
        ["git", "config", "user.email", "smoke@example.test"],
        cwd=source,
        check=True,
    )
    subprocess.run(["git", "add", "--", "core"], cwd=source, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "tracked fixture"], cwd=source, check=True)
    external = tmp_path / "external.py"
    external.write_text("external content\n", encoding="utf-8")
    external.chmod(0o600)
    original_mode = stat.S_IMODE(external.stat().st_mode)
    original_ensure = smoke._ensure_safe_source

    def swap_after_validation(path: Path, source_root: Path) -> None:
        original_ensure(path, source_root)
        if path == tracked:
            path.unlink()
            path.symlink_to(external)

    monkeypatch.setattr(smoke, "RUNNER_ROOT", source)
    monkeypatch.setattr(smoke, "_ensure_safe_source", swap_after_validation)

    try:
        try:
            runner = smoke._materialize_runner(tmp_path / "runner")
            smoke._set_runtime_tree_writable(runner, writable=False)
        except smoke.JourneySafetySkip:
            pass
        assert external.read_text(encoding="utf-8") == "external content\n"
        assert stat.S_IMODE(external.stat().st_mode) == original_mode
    finally:
        external.chmod(original_mode)


def test_runner_materialization_rejects_a_mid_copy_checkout_change(
    monkeypatch,
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    first = source / "core" / "__init__.py"
    second = source / "core" / "utils" / "validators.py"
    second.parent.mkdir(parents=True)
    first.write_text("GENERATION = 'first'\n", encoding="utf-8")
    second.write_text("VALIDATOR_GENERATION = 'first'\n", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Smoke Test"], cwd=source, check=True)
    subprocess.run(
        ["git", "config", "user.email", "smoke@example.test"],
        cwd=source,
        check=True,
    )
    subprocess.run(["git", "add", "--", "core"], cwd=source, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "tracked fixture"], cwd=source, check=True)
    original_copy = smoke._copy_runner_file

    def mutate_after_copy(source_root: Path, relative: Path, destination: Path) -> None:
        original_copy(source_root, relative, destination)
        if relative == Path("core/__init__.py"):
            first.write_text("GENERATION = 'second'\n", encoding="utf-8")

    monkeypatch.setattr(smoke, "RUNNER_ROOT", source)
    monkeypatch.setattr(smoke, "_copy_runner_file", mutate_after_copy)

    try:
        smoke._materialize_runner(tmp_path / "runner")
    except smoke.JourneySafetySkip:
        pass
    else:
        raise AssertionError("mixed checkout generations were materialized")


def test_release_gate_compares_the_materialized_runner_snapshot(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = _write_valid_vault(tmp_path)
    repo = _release_repo(tmp_path)
    original = smoke._materialize_runner

    def materialize_drifted_runner(destination: Path) -> Path:
        runner = original(destination)
        work_server = runner / "core" / "mcp" / "work_server.py"
        work_server.write_text(
            work_server.read_text(encoding="utf-8") + "\n# runner snapshot drift\n",
            encoding="utf-8",
        )
        return runner

    monkeypatch.setattr(smoke, "_materialize_runner", materialize_drifted_runner)

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=repo,
        journey_definitions=(_definition("task_lifecycle", 8.0),),
    )

    result = run.report["journeys"][0]
    assert run.harness_failed is False
    assert run.exit_code == 0
    assert result["verdict"] == "UNKNOWN"
    assert "Dex-owned core differs from" in result["detail"]


def test_all_journeys_share_one_runner_generation(monkeypatch, tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    skill = vault / ".claude" / "skills" / "weekly-custom" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: weekly-custom\ndescription: Valid smoke fixture.\n---\n",
        encoding="utf-8",
    )
    original = smoke._materialize_runner
    materializations = 0

    def materialize_generation(destination: Path) -> Path:
        nonlocal materializations
        materializations += 1
        runner = original(destination)
        if materializations > 1:
            validators = runner / "core" / "utils" / "validators.py"
            validators.write_text(
                validators.read_text(encoding="utf-8")
                + "\ndef validate_skill_frontmatter(_path):\n"
                + "    return ['mixed runner generation']\n",
                encoding="utf-8",
            )
        return runner

    monkeypatch.setattr(smoke, "_materialize_runner", materialize_generation)

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=REPO_ROOT,
        journey_definitions=(
            _definition("configs"),
            _definition("skills"),
        ),
    )

    assert materializations == 1
    assert run.harness_failed is False
    assert [journey["verdict"] for journey in run.report["journeys"]] == ["OK", "OK"]


def test_hanging_journey_is_killed_and_returns_exit_two(monkeypatch, tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)

    monkeypatch.setattr(
        smoke,
        "_journey_command",
        lambda *_args: [
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
        ],
    )
    started = time.monotonic()
    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=REPO_ROOT,
        journey_definitions=(_definition("configs", 0.5),),
    )

    assert time.monotonic() - started < 2
    assert run.exit_code == 2
    assert run.harness_failed is True
    assert run.report["journeys"][0]["verdict"] == "UNKNOWN"
    assert "journey timed out after" in run.report["journeys"][0]["detail"]


def test_timed_out_journey_kills_delayed_descendants(monkeypatch, tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    sentinel = tmp_path / "timed-out-descendant-survived"
    descendant = (
        "import time; from pathlib import Path; time.sleep(0.7); "
        f"Path({str(sentinel)!r}).touch()"
    )
    parent = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {descendant!r}]); "
        "time.sleep(60)"
    )
    monkeypatch.setattr(
        smoke,
        "_journey_command",
        lambda *_args: [sys.executable, "-c", parent],
    )

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=REPO_ROOT,
        journey_definitions=(_definition("configs", 0.4),),
    )
    time.sleep(0.8)

    assert run.exit_code == 2
    assert "timed out" in run.report["journeys"][0]["detail"]
    assert not sentinel.exists()


def test_hanging_preparation_is_killed_within_the_journey_budget(monkeypatch, tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    monkeypatch.setattr(
        smoke,
        "_preparation_command",
        lambda *_args: [
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
        ],
    )

    started = time.monotonic()
    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=REPO_ROOT,
        journey_definitions=(_definition("configs", 0.5),),
    )

    assert time.monotonic() - started < 2
    assert run.exit_code == 2
    assert run.harness_failed is True
    assert "preparation timed out" in run.report["journeys"][0]["detail"]


def test_normal_journey_exit_cleans_up_same_group_descendants(monkeypatch, tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    sentinel = tmp_path / "orphan-survived"
    descendant = (
        "import time; from pathlib import Path; time.sleep(0.5); "
        f"Path({str(sentinel)!r}).touch()"
    )
    parent = (
        "import json, subprocess, sys; "
        f"subprocess.Popen([sys.executable, '-c', {descendant!r}], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
        "print(json.dumps({'verdict': 'OK', 'detail': 'parent exited'}))"
    )
    monkeypatch.setattr(
        smoke,
        "_journey_command",
        lambda *_args: [sys.executable, "-c", parent],
    )

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=REPO_ROOT,
        journey_definitions=(_definition("configs"),),
    )
    time.sleep(0.7)

    assert run.exit_code == 0
    assert not sentinel.exists()


def test_subprocess_environment_does_not_inherit_unapproved_values(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = _write_valid_vault(tmp_path)
    monkeypatch.setenv("DEX_SMOKE_ENV_SENTINEL", "must-not-leak")
    source = (
        "import json, os; "
        "leaked = 'DEX_SMOKE_ENV_SENTINEL' in os.environ; "
        "print(json.dumps({'verdict': 'BROKEN' if leaked else 'OK', "
        "'detail': 'environment leaked' if leaked else 'environment isolated'}))"
    )
    monkeypatch.setattr(
        smoke,
        "_journey_command",
        lambda *_args: [sys.executable, "-c", source],
    )

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=REPO_ROOT,
        journey_definitions=(_definition("configs"),),
    )

    assert run.exit_code == 0
    assert run.report["journeys"][0]["verdict"] == "OK"


def test_subprocess_network_guard_blocks_dns_and_udp(monkeypatch, tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    source = """
import json
import socket

blocked = []
try:
    socket.getaddrinfo("example.com", 443)
except OSError:
    blocked.append("dns")
udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    udp.sendto(b"smoke", ("127.0.0.1", 9))
except OSError:
    blocked.append("udp")
finally:
    udp.close()
ok = blocked == ["dns", "udp"]
print(json.dumps({"verdict": "OK" if ok else "BROKEN", "detail": repr(blocked)}))
"""
    monkeypatch.setattr(
        smoke,
        "_journey_command",
        lambda *_args: [sys.executable, "-c", source],
    )

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=REPO_ROOT,
        journey_definitions=(_definition("configs"),),
    )

    assert run.exit_code == 0
    assert run.report["journeys"][0]["verdict"] == "OK"


def test_journey_process_never_imports_or_runs_from_live_repo(monkeypatch, tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    fake_repo = tmp_path / "writable-live-repo"
    fake_repo.mkdir()
    sentinel = tmp_path / "live-sitecustomize-ran"
    (fake_repo / "sitecustomize.py").write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).touch()\n",
        encoding="utf-8",
    )
    observed = []
    original = smoke._run_json_process

    def capture(command, **kwargs):
        observed.append((kwargs["label"], list(command), kwargs["cwd"], dict(kwargs["env"])))
        return original(command, **kwargs)

    monkeypatch.setattr(smoke, "_run_json_process", capture)

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=fake_repo,
        journey_definitions=(_definition("configs"),),
    )

    assert run.exit_code == 0
    journey = next(call for call in observed if call[0] == "journey")
    _label, command, cwd, env = journey
    assert str(fake_repo) not in env["PYTHONPATH"].split(os.pathsep)
    assert cwd != fake_repo
    assert str(fake_repo) not in command
    assert command[1] == "-S"
    assert "/runner/core/utils/smoke.py" in command[2]
    assert not sentinel.exists()


def test_ambient_path_cannot_replace_git_or_node(monkeypatch, tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    repo = _release_repo(tmp_path)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    sentinel = tmp_path / "ambient-command-ran"
    for name in ("git", "node"):
        executable = fake_bin / name
        executable.write_text(
            f"#!/bin/sh\n/usr/bin/touch {str(sentinel)!r}\nexit 0\n",
            encoding="utf-8",
        )
        executable.chmod(0o755)
    hook = vault / ".claude" / "hooks" / "check.js"
    hook.parent.mkdir()
    hook.write_text("console.log('syntax only');\n", encoding="utf-8")
    (vault / ".claude" / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {"hooks": [{"command": "node .claude/hooks/check.js"}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PATH", str(fake_bin))

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=repo,
        journey_definitions=(_definition("hooks"),),
    )

    assert run.exit_code == 0
    assert run.report["journeys"][0]["verdict"] in {"OK", "UNKNOWN"}
    assert not sentinel.exists()


def test_custom_mcp_command_is_structural_only_and_never_launched(tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    sentinel = tmp_path / "custom-command-ran"
    command = f"from pathlib import Path; Path({str(sentinel)!r}).write_text('unsafe')"
    (vault / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "custom-sentinel": {
                        "command": sys.executable,
                        "args": ["-c", command],
                        "env": {},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=REPO_ROOT,
        journey_definitions=(_definition("mcp_startup"),),
    )

    result = run.report["journeys"][0]
    assert run.exit_code == 0
    assert result["verdict"] == "UNKNOWN"
    assert "custom-sentinel" in result["detail"]
    assert "not executed for safety" in result["detail"]
    assert not sentinel.exists()


def test_mcp_credentials_are_absent_from_child_plan_environment_and_argv(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = _write_valid_vault(tmp_path)
    secret = f"dex-smoke-secret-{os.urandom(8).hex()}"
    (vault / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "custom-secret": {
                        "command": "custom-command",
                        "args": [secret],
                        "env": {"API_TOKEN": secret},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    original = smoke._run_journey_process

    def inspect_before_journey(definition, **kwargs):
        encoded = secret.encode()
        for path in kwargs["cwd"].rglob("*"):
            if path.is_file() and not path.is_symlink():
                assert encoded not in path.read_bytes(), path
        assert secret not in "\0".join(kwargs["env"].values())
        return original(definition, **kwargs)

    monkeypatch.setattr(smoke, "_run_journey_process", inspect_before_journey)

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=REPO_ROOT,
        journey_definitions=(_definition("mcp_startup"),),
    )

    assert run.exit_code == 0
    assert run.report["journeys"][0]["verdict"] == "UNKNOWN"
    assert "not executed for safety" in run.report["journeys"][0]["detail"]


def test_symlinked_mcp_config_is_not_read_or_executed(tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    sentinel = tmp_path / "symlinked-command-ran"
    external_config = tmp_path / "external-mcp.json"
    external_config.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "custom-sentinel": {
                        "command": sys.executable,
                        "args": [
                            "-c",
                            f"from pathlib import Path; Path({str(sentinel)!r}).touch()",
                        ],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    (vault / ".mcp.json").unlink()
    (vault / ".mcp.json").symlink_to(external_config)

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=REPO_ROOT,
        journey_definitions=(_definition("mcp_startup"),),
    )

    result = run.report["journeys"][0]
    assert run.exit_code == 0
    assert result["verdict"] == "UNKNOWN"
    assert ".mcp.json is symlinked and was not read for safety" in result["detail"]
    assert not sentinel.exists()


def test_no_release_ref_cannot_vouch_for_an_owned_server(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    server = repo / "core" / "mcp" / "work_server.py"
    server.parent.mkdir(parents=True)
    server.write_text("print('would execute')\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "smoke@example.test"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Smoke Test"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "core/mcp/work_server.py"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "test fixture"], check=True)

    safe, reason = smoke._script_is_unmodified(server, repo)

    assert safe is False
    assert "no upstream/release or origin/release" in reason


def test_task_lifecycle_without_release_ref_never_imports_live_work_server(tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    repo = tmp_path / "untrusted-repo"
    server = repo / "core" / "mcp" / "work_server.py"
    server.parent.mkdir(parents=True)
    sentinel = tmp_path / "live-work-server-imported"
    server.write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).touch()\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=repo,
        journey_definitions=(_definition("task_lifecycle"),),
    )

    assert run.exit_code == 0
    assert run.report["journeys"][0]["verdict"] == "UNKNOWN"
    assert "not executed for safety" in run.report["journeys"][0]["detail"]
    assert not sentinel.exists()


def test_task_lifecycle_runs_verified_release_and_refuses_dependency_drift(tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    repo = _release_repo(tmp_path)

    verified = smoke.run_smoke(
        vault_root=vault,
        repo_root=repo,
        journey_definitions=(_definition("task_lifecycle", 8.0),),
    )

    assert verified.exit_code == 0
    assert verified.report["journeys"][0]["verdict"] == "OK"

    paths_module = repo / "core" / "paths.py"
    paths_module.write_text(paths_module.read_text(encoding="utf-8") + "\n# user drift\n")
    drifted = smoke.run_smoke(
        vault_root=vault,
        repo_root=repo,
        journey_definitions=(_definition("task_lifecycle", 8.0),),
    )

    assert drifted.exit_code == 0
    assert drifted.report["journeys"][0]["verdict"] == "UNKNOWN"
    assert "Dex-owned core differs" in drifted.report["journeys"][0]["detail"]


def test_repo_fsmonitor_command_is_never_executed(tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    repo = _release_repo(tmp_path)
    sentinel = tmp_path / "fsmonitor-ran"
    fsmonitor = tmp_path / "user-fsmonitor.sh"
    fsmonitor.write_text(
        f"#!/bin/sh\n/usr/bin/touch {str(sentinel)!r}\nprintf '0\\n'\n",
        encoding="utf-8",
    )
    fsmonitor.chmod(0o755)
    subprocess.run(
        ["git", "config", "core.fsmonitor", str(fsmonitor)],
        cwd=repo,
        check=True,
    )

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=repo,
        journey_definitions=(_definition("task_lifecycle", 8.0),),
    )

    assert run.exit_code == 0
    assert run.report["journeys"][0]["verdict"] == "OK"
    assert not sentinel.exists()


def test_mcp_launch_uses_release_snapshot_after_live_entrypoint_changes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = _write_valid_vault(tmp_path)
    repo = _release_repo(tmp_path)
    live_server = repo / "core" / "mcp" / "work_server.py"
    sentinel = tmp_path / "drifted-live-server-ran"
    (vault / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "work-mcp": {
                        "command": sys.executable,
                        "args": [str(live_server)],
                        "env": {"VAULT_PATH": str(vault)},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    original = smoke._run_journey_process

    def mutate_live_after_plan(definition, **kwargs):
        live_server.write_text(
            f"from pathlib import Path\nPath({str(sentinel)!r}).touch()\n",
            encoding="utf-8",
        )
        return original(definition, **kwargs)

    monkeypatch.setattr(smoke, "_run_journey_process", mutate_live_after_plan)

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=repo,
        journey_definitions=(_definition("mcp_startup", 8.0),),
    )

    assert run.exit_code == 0
    assert run.report["journeys"][0]["verdict"] == "OK"
    assert "work-mcp: OK" in run.report["journeys"][0]["detail"]
    assert not sentinel.exists()


def test_symlinked_owned_mcp_server_is_never_executed(tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    repo = _release_repo(tmp_path)
    live_server = repo / "core" / "mcp" / "work_server.py"
    sentinel = tmp_path / "symlinked-owned-server-ran"
    external = tmp_path / "external_server.py"
    external.write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).touch()\n",
        encoding="utf-8",
    )
    live_server.unlink()
    live_server.symlink_to(external)
    (vault / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "work-mcp": {
                        "command": sys.executable,
                        "args": [str(live_server)],
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=repo,
        journey_definitions=(_definition("mcp_startup", 8.0),),
    )

    assert run.exit_code == 0
    assert run.report["journeys"][0]["verdict"] == "UNKNOWN"
    assert "not executed for safety" in run.report["journeys"][0]["detail"]
    assert not sentinel.exists()


def test_broken_custom_skill_names_exact_user_file(tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    repo = _release_repo(tmp_path)
    skill = vault / ".claude" / "skills" / "weekly-custom" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("not frontmatter\n", encoding="utf-8")

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=repo,
        journey_definitions=(_definition("skills"),),
    )

    result = run.report["journeys"][0]
    assert run.exit_code == 1
    assert result["verdict"] == "BROKEN"
    assert ".claude/skills/weekly-custom/SKILL.md (user)" in result["detail"]


def test_read_only_tasks_directory_makes_task_lifecycle_broken(tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    tasks = vault / "03-Tasks"
    original_mode = stat.S_IMODE(tasks.stat().st_mode)
    tasks.chmod(0o555)
    try:
        run = smoke.run_smoke(
            vault_root=vault,
            repo_root=REPO_ROOT,
            journey_definitions=(_definition("task_lifecycle"),),
        )
    finally:
        tasks.chmod(original_mode)

    result = run.report["journeys"][0]
    assert run.exit_code == 1
    assert result["verdict"] == "BROKEN"
    assert "03-Tasks is not writable" in result["detail"]


def test_hooks_are_syntax_checked_without_executing_commands(tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    sentinel = tmp_path / "hook-command-ran"
    command = f"python -c \"from pathlib import Path; Path({str(sentinel)!r}).touch()\""
    (vault / ".claude" / "settings.json").write_text(
        json.dumps({"hooks": {"SessionStart": [{"hooks": [{"command": command}]}]}}),
        encoding="utf-8",
    )

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=REPO_ROOT,
        journey_definitions=(_definition("hooks"),),
    )

    assert run.exit_code == 0
    assert run.report["journeys"][0]["verdict"] == "UNKNOWN"
    assert not sentinel.exists()


def test_hooks_report_dynamic_targets_and_each_compound_executable(tmp_path: Path) -> None:
    vault = _write_valid_vault(tmp_path)
    (vault / ".claude" / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {"command": 'bash "$HOME/custom.sh"'},
                                {"command": "true && definitely-not-a-dex-command"},
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    run = smoke.run_smoke(
        vault_root=vault,
        repo_root=REPO_ROOT,
        journey_definitions=(_definition("hooks"),),
    )

    result = run.report["journeys"][0]
    assert run.exit_code == 0
    assert result["verdict"] == "UNKNOWN"
    assert "$HOME/custom.sh" in result["detail"]
    assert "definitely-not-a-dex-command" in result["detail"]


def test_internal_task_journey_refuses_a_live_vault(monkeypatch, tmp_path: Path, capsys) -> None:
    vault = _write_valid_vault(tmp_path)
    before = _tree_hash(vault)
    monkeypatch.setenv("VAULT_PATH", str(vault))

    exit_code = smoke.main(
        ["--_journey", "task_lifecycle", "--repo-root", str(REPO_ROOT)]
    )

    assert exit_code == 2
    assert "refused" in capsys.readouterr().err
    assert _tree_hash(vault) == before
