#!/usr/bin/env python3
"""Build truthful, release-specific health data from CI artifacts."""

from __future__ import annotations

import argparse
import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

UNKNOWN = "unknown"
PR_ONLY_DETAIL = "not run on release build (PR-only)"

MAIN_PUSH_GATES = (
    "Governance docs present",
    "Hook harness tests",
    "Script library tests",
    "Instructed-tool existence gate",
    "Test suites + coverage",
    "Large-vault performance budget",
    "Security gate",
    "Ruff linting",
    "Distribution safety check",
    "Path consistency check",
)

PR_ONLY_GATES = (
    "Diff-aware test gate",
    "Path-contract usage gate",
    "Documentation drift gate",
    "Touched-file coverage gate",
)


def _unknown_counts() -> dict[str, str]:
    return {"passed": UNKNOWN, "skipped": UNKNOWN, "failed": UNKNOWN, "total": UNKNOWN}


def parse_pytest_report(path: Path) -> dict[str, int | str]:
    """Return aggregate pytest counts from JUnit XML, or explicit unknowns."""
    if not path.is_file():
        return _unknown_counts()

    try:
        root = ET.parse(path).getroot()
        totals = root.attrib
        if "tests" not in totals and root.tag == "testsuites":
            suites = root.findall("testsuite")
            totals = {
                key: sum(int(suite.attrib.get(key, 0)) for suite in suites)
                for key in ("tests", "failures", "errors", "skipped")
            }

        total = int(totals["tests"])
        skipped = int(totals.get("skipped", 0))
        failed = int(totals.get("failures", 0)) + int(totals.get("errors", 0))
        passed = total - skipped - failed
        if min(total, skipped, failed, passed) < 0:
            raise ValueError("invalid negative JUnit count")
    except (ET.ParseError, KeyError, TypeError, ValueError):
        return _unknown_counts()

    return {"passed": passed, "skipped": skipped, "failed": failed, "total": total}


def parse_coverage(path: Path) -> dict[str, float | str]:
    """Return coverage.py's total percentage, or an explicit unknown."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        percent = float(data["totals"]["percent_covered"])
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return {"total_percent": UNKNOWN}
    return {"total_percent": round(percent, 2)}


def read_version(path: Path) -> str:
    try:
        version = json.loads(path.read_text(encoding="utf-8"))["version"]
    except (FileNotFoundError, json.JSONDecodeError, KeyError, TypeError):
        return UNKNOWN
    return version if isinstance(version, str) and version else UNKNOWN


def read_changelog_headline(path: Path, version: str) -> str:
    if version == UNKNOWN:
        return UNKNOWN
    try:
        changelog = path.read_text(encoding="utf-8")
    except OSError:
        return UNKNOWN

    match = re.search(
        rf"^## \[{re.escape(version)}\]\s+-\s+(.+?)(?:\s+\(\d{{4}}-\d{{2}}-\d{{2}}\))?$",
        changelog,
        flags=re.MULTILINE,
    )
    return match.group(1).strip() if match else UNKNOWN


def build_gate_matrix(quality_conclusion: str | None) -> list[dict[str, str]]:
    if quality_conclusion == "success":
        main_status = "passed"
        main_detail = "completed on the successful main release build"
    elif quality_conclusion == "skipped":
        main_status = "skipped"
        main_detail = "quality job was skipped"
    else:
        main_status = UNKNOWN
        main_detail = "quality-job result was not available"

    gates = [
        {"name": name, "status": main_status, "detail": main_detail}
        for name in MAIN_PUSH_GATES
    ]
    gates.extend(
        {"name": name, "status": "not-applicable", "detail": PR_ONLY_DETAIL}
        for name in PR_ONLY_GATES
    )
    return gates


def build_health_data(
    *,
    package_path: Path,
    junit_path: Path,
    coverage_path: Path,
    changelog_path: Path,
    source_sha: str | None,
    release_sha: str | None,
    generated_at: str,
    workflow_run_url: str | None,
    quality_conclusion: str | None,
) -> dict[str, Any]:
    version = read_version(package_path)
    return {
        "schema_version": 1,
        "label": "Last successful release build",
        "release": {
            "version": version,
            "source_sha": source_sha or UNKNOWN,
            "release_sha": release_sha or UNKNOWN,
            "generated_at": generated_at,
            "workflow_run_url": workflow_run_url or UNKNOWN,
        },
        "automated_checks": parse_pytest_report(junit_path),
        "coverage": parse_coverage(coverage_path),
        "gates": build_gate_matrix(quality_conclusion),
        "changelog_headline": read_changelog_headline(changelog_path, version),
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=Path("package.json"))
    parser.add_argument("--junit", type=Path, default=Path(".logs/pytest-report.xml"))
    parser.add_argument("--coverage", type=Path, default=Path("coverage.json"))
    parser.add_argument("--changelog", type=Path, default=Path("CHANGELOG.md"))
    parser.add_argument("--source-sha")
    parser.add_argument("--release-sha")
    parser.add_argument("--generated-at", default=None)
    parser.add_argument("--workflow-run-url")
    parser.add_argument("--quality-conclusion")
    parser.add_argument("--output", type=Path, default=Path("health.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    data = build_health_data(
        package_path=args.package,
        junit_path=args.junit,
        coverage_path=args.coverage,
        changelog_path=args.changelog,
        source_sha=args.source_sha,
        release_sha=args.release_sha,
        generated_at=args.generated_at or _utc_now(),
        workflow_run_url=args.workflow_run_url,
        quality_conclusion=args.quality_conclusion,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
