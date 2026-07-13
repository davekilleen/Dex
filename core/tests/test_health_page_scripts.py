"""Tests for the release health-data and page generators."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build-health-json.py"


def _load_script(path: Path, module_name: str):
    assert path.is_file(), f"missing script: {path}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_health_json_parses_pytest_counts(tmp_path):
    build_health = _load_script(BUILD_SCRIPT, "build_health_json")
    report = tmp_path / "pytest-report.xml"
    report.write_text(
        '<testsuites tests="9" failures="2" errors="1" skipped="2" time="1.0" />',
        encoding="utf-8",
    )

    counts = build_health.parse_pytest_report(report)

    assert counts == {"passed": 4, "skipped": 2, "failed": 3, "total": 9}


def test_build_health_json_marks_pr_only_gates_not_run(tmp_path):
    build_health = _load_script(BUILD_SCRIPT, "build_health_json")
    package = tmp_path / "package.json"
    package.write_text(json.dumps({"version": "1.53.0"}), encoding="utf-8")

    data = build_health.build_health_data(
        package_path=package,
        junit_path=tmp_path / "missing-report.xml",
        coverage_path=tmp_path / "missing-coverage.json",
        changelog_path=tmp_path / "missing-changelog.md",
        source_sha="a" * 40,
        release_sha="b" * 40,
        generated_at="2026-07-13T10:20:30Z",
        workflow_run_url="https://github.com/example/dex/actions/runs/123",
        quality_conclusion="success",
    )

    gates = {gate["name"]: gate for gate in data["gates"]}
    for name in (
        "Diff-aware test gate",
        "Path-contract usage gate",
        "Documentation drift gate",
        "Touched-file coverage gate",
    ):
        assert gates[name] == {
            "name": name,
            "status": "not-applicable",
            "detail": "not run on release build (PR-only)",
        }


def test_build_health_json_marks_missing_inputs_unknown(tmp_path):
    build_health = _load_script(BUILD_SCRIPT, "build_health_json")
    data = build_health.build_health_data(
        package_path=tmp_path / "missing-package.json",
        junit_path=tmp_path / "missing-report.xml",
        coverage_path=tmp_path / "missing-coverage.json",
        changelog_path=tmp_path / "missing-changelog.md",
        source_sha=None,
        release_sha=None,
        generated_at="2026-07-13T10:20:30Z",
        workflow_run_url=None,
        quality_conclusion=None,
    )

    assert data["release"]["version"] == "unknown"
    assert data["release"]["source_sha"] == "unknown"
    assert data["release"]["release_sha"] == "unknown"
    assert data["release"]["workflow_run_url"] == "unknown"
    assert data["automated_checks"] == {
        "passed": "unknown",
        "skipped": "unknown",
        "failed": "unknown",
        "total": "unknown",
    }
    assert data["coverage"]["total_percent"] == "unknown"
    assert data["changelog_headline"] == "unknown"
    assert all(
        gate["status"] != "passed"
        for gate in data["gates"]
        if gate["status"] != "not-applicable"
    )
