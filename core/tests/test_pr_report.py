from __future__ import annotations

import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "pr_report.py"
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load_module():
    spec = importlib.util.spec_from_file_location("pr_report", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_area_mapping_uses_plain_english_and_deduplicates():
    report = _load_module()

    areas = report.areas_for_paths(
        [
            "core/mcp/work_server.py",
            "core/mcp/calendar_server.py",
            ".claude/skills/daily-plan/SKILL.md",
            ".claude/hooks/session-start.cjs",
            "scripts/build-release.sh",
            "core/utils/trust_registry.py",
            "core/utils/doctor.py",
            "core/tests/test_smoke.py",
        ]
    )

    assert [area.name for area in areas] == [
        "the task/meeting engine",
        "skills",
        "session hooks",
        "build & release",
        "the trust engine",
        "tests",
    ]


def test_report_render_for_synthetic_changed_files():
    report = _load_module()

    markdown = report.render_report(
        [
            "core/mcp/work_server.py",
            "core/utils/trust_registry.py",
            "core/tests/test_work_server.py",
        ]
    )

    assert markdown.startswith("<!-- dex-pr-report -->\n## What this pull request touches\n")
    assert "**the task/meeting engine**" in markdown
    assert "creating and updating tasks" in markdown
    assert "**the trust engine**" in markdown
    assert "safe diagnostics and health checks" in markdown
    assert "**tests**" in markdown
    assert "### Gates that will judge this change" in markdown
    assert "Personal-data gate" in markdown
    assert "Tests and coverage" in markdown


def test_report_explains_unmapped_changes():
    report = _load_module()

    markdown = report.render_report(["README.md"])

    assert "other parts of Dex" in markdown
    assert "No mapped product journey" in markdown


def test_workflow_reports_deletions_and_only_updates_the_bot_comment():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "--diff-filter=ACMRD" in workflow
    assert '.user.login == "github-actions[bot]"' in workflow
