"""Path contract tests — every constant must map to a real directory or file."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core import paths

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dir_constants() -> list[tuple[str, Path]]:
    """Return all module-level Path constants ending in _DIR."""
    return [
        (name, value)
        for name, value in vars(paths).items()
        if name.endswith("_DIR") and isinstance(value, Path) and not name.startswith("_")
    ]


def _file_constants() -> list[tuple[str, Path]]:
    """Return all module-level Path constants ending in _FILE."""
    return [
        (name, value)
        for name, value in vars(paths).items()
        if name.endswith("_FILE") and isinstance(value, Path) and not name.startswith("_")
    ]


# ---------------------------------------------------------------------------
# TestDirectoryConstants
# ---------------------------------------------------------------------------

class TestDirectoryConstants:
    """Every *_DIR constant must point to a real directory."""

    @pytest.mark.parametrize(
        "name,path",
        _dir_constants(),
        ids=[name for name, _ in _dir_constants()],
    )
    def test_directory_exists(self, name: str, path: Path):
        assert path.is_dir(), f"{name} = {path} does not exist as a directory"


# ---------------------------------------------------------------------------
# TestDerivedPaths
# ---------------------------------------------------------------------------

class TestDerivedPaths:
    """Verify parent relationships between derived paths."""

    def test_people_dir_parent_is_areas(self):
        assert paths.PEOPLE_DIR.parent == paths.AREAS_DIR

    def test_companies_dir_parent_is_areas(self):
        assert paths.COMPANIES_DIR.parent == paths.AREAS_DIR

    def test_career_dir_parent_is_areas(self):
        assert paths.CAREER_DIR.parent == paths.AREAS_DIR

    def test_meetings_dir_parent_is_inbox(self):
        assert paths.MEETINGS_DIR.parent == paths.INBOX_DIR

    def test_tracked_meetings_dir_parent_is_areas(self):
        assert paths.TRACKED_MEETINGS_DIR.parent == paths.AREAS_DIR

    def test_meeting_daily_logs_dir_parent_is_tracked_meetings(self):
        assert paths.MEETING_DAILY_LOGS_DIR.parent == paths.TRACKED_MEETINGS_DIR

    def test_legacy_meetings_dir_matches_meetings_dir(self):
        assert paths.LEGACY_MEETINGS_DIR == paths.MEETINGS_DIR

    def test_ideas_dir_parent_is_inbox(self):
        assert paths.IDEAS_DIR.parent == paths.INBOX_DIR

    def test_daily_plans_dir_parent_is_inbox(self):
        assert paths.DAILY_PLANS_DIR.parent == paths.INBOX_DIR

    def test_tasks_file_parent_is_tasks_dir(self):
        assert paths.TASKS_FILE.parent == paths.TASKS_DIR

    def test_evidence_dir_parent_is_career(self):
        assert paths.EVIDENCE_DIR.parent == paths.CAREER_DIR

    def test_system_dir_parent_is_vault_root(self):
        assert paths.SYSTEM_DIR.parent == paths.VAULT_ROOT

    def test_dex_runtime_dir_parent_is_system_dir(self):
        assert paths.DEX_RUNTIME_DIR.parent == paths.SYSTEM_DIR

    def test_ritual_intelligence_db_parent_is_runtime_dir(self):
        assert paths.RITUAL_INTELLIGENCE_DB_FILE.parent == paths.DEX_RUNTIME_DIR


# ---------------------------------------------------------------------------
# TestNoBarePaths
# ---------------------------------------------------------------------------

class TestNoBarePaths:
    """No .py file should reference bare PARA folder names without numbered prefix."""

    BARE_PATTERNS = [
        r"\bInbox\b",
        r"\bQuarter_Goals\b",
        r"\bWeek_Priorities\b",
        r"\bTasks\b",
        r"\bProjects\b",
        r"\bAreas\b",
        r"\bResources\b",
        r"\bArchives\b",
    ]

    # Folders that are referenced as string literals with numbered prefix are OK.
    # We look for bare references that skip the numbered prefix (e.g. "Inbox" instead of "00-Inbox").
    NUMBERED_FOLDERS = {
        "Inbox": "00-Inbox",
        "Quarter_Goals": "01-Quarter_Goals",
        "Week_Priorities": "02-Week_Priorities",
        "Tasks": "03-Tasks",
        "Projects": "04-Projects",
        "Areas": "05-Areas",
        "Resources": "06-Resources",
        "Archives": "07-Archives",
    }

    def test_no_bare_para_references(self):
        """Grep .py files for bare PARA folder names used as path segments."""
        core_dir = Path(__file__).resolve().parent.parent
        violations = []

        for bare, numbered in self.NUMBERED_FOLDERS.items():
            # Look for path-like usage: slash + bare name or bare name + slash
            # Skip: the paths.py definition itself, test files, __pycache__
            result = subprocess.run(
                [
                    sys.executable, "-c",
                    f"""
import re, pathlib
core = pathlib.Path({str(core_dir)!r})
pattern = re.compile(r"['\"/]{bare}['\"/]|/{bare}/")
for py in core.rglob("*.py"):
    if "__pycache__" in str(py) or "test_" in py.name:
        continue
    if py.name == "paths.py":
        continue
    for i, line in enumerate(py.read_text().splitlines(), 1):
        # Skip lines that already use the numbered prefix
        if "{numbered}" in line:
            continue
        # Skip comments and docstrings (simple heuristic)
        stripped = line.lstrip()
        if stripped.startswith("#") or stripped.startswith('\"\"\"') or stripped.startswith("'''"):
            continue
        if pattern.search(line):
            print(f"{{py}}:{{i}}: {{line.strip()}}")
""",
                ],
                capture_output=True,
                text=True,
            )
            if result.stdout.strip():
                violations.append(result.stdout.strip())

        assert not violations, (
            "Found bare PARA folder references (use core.paths constants instead):\n"
            + "\n".join(violations)
        )


# ---------------------------------------------------------------------------
# TestPathsJson
# ---------------------------------------------------------------------------

class TestPathsJson:
    """Verify export_json() round-trip."""

    def test_export_json_returns_dict(self):
        data = paths.export_json()
        assert isinstance(data, dict)
        assert len(data) > 0

    def test_export_json_keys_are_module_constants(self):
        data = paths.export_json()
        for key in data:
            assert hasattr(paths, key), f"{key} not found in paths module"
            assert isinstance(getattr(paths, key), Path)

    def test_export_json_values_are_strings(self):
        data = paths.export_json()
        for key, value in data.items():
            assert isinstance(value, str), f"{key} value is not a string"

    def test_export_json_roundtrip(self, tmp_path):
        out_file = tmp_path / "paths.json"
        data = paths.export_json(out_file)

        # Read back and verify
        loaded = json.loads(out_file.read_text())
        assert loaded == data

    def test_export_json_contains_vault_root(self):
        data = paths.export_json()
        assert "VAULT_ROOT" in data
