from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import pytest

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, settings  # noqa: E402
from hypothesis import strategies as st

from core.mcp import work_server
from core.mcp.update_checker import parse_version
from core.utils.manifest import ManifestError, generate_manifest
from core.utils.validators import validate_skill_frontmatter


@given(
    major=st.integers(min_value=0, max_value=999),
    minor=st.integers(min_value=0, max_value=999),
    patch=st.integers(min_value=0, max_value=999),
    prerelease=st.sampled_from(("alpha", "beta", "rc")),
    prerelease_number=st.integers(min_value=0, max_value=999),
    leading_v=st.booleans(),
)
@settings(max_examples=50, deadline=None)
def test_parse_version_preserves_numeric_release_components(
    major, minor, patch, prerelease, prerelease_number, leading_v
):
    version = f"{major}.{minor}.{patch}-{prerelease}.{prerelease_number}"
    if leading_v:
        version = f"v{version}"

    assert parse_version(version) == (major, minor, patch)


@given(
    title=st.text(
        alphabet=st.characters(
            # Punctuation belongs to the task-line grammar (IDs, refs, tags,
            # and legacy .md links), so this invariant generates title text
            # rather than parser directives.
            whitelist_categories=("L", "N", "Zs"),
        ),
        min_size=1,
        max_size=80,
    ).filter(lambda value: value.strip() != ""),
    completed=st.booleans(),
)
@settings(max_examples=50, deadline=None)
def test_task_line_parsing_round_trips_unicode_titles(title: str, completed: bool):
    with tempfile.TemporaryDirectory(prefix="dex-task-fuzz-") as directory:
        tasks_file = Path(directory) / "Tasks.md"
        marker = "x" if completed else " "
        tasks_file.write_text(f"# Tasks\n\n## P2\n- [{marker}] {title} ^task-20260713-001\n", encoding="utf-8")

        [parsed] = work_server.parse_tasks_file(tasks_file)

        assert parsed["title"] == title.strip()
        assert parsed["completed"] is completed
        assert parsed["task_id"] == "task-20260713-001"


@pytest.mark.fuzz
@given(
    prefix=st.text(alphabet="abc XYZé東京", min_size=1, max_size=20),
    suffix=st.text(alphabet="abc XYZé東京", min_size=1, max_size=20),
)
@settings(max_examples=15, deadline=None)
def test_manifest_rejects_newline_containing_paths(prefix: str, suffix: str):
    with tempfile.TemporaryDirectory(prefix="dex-manifest-fuzz-") as directory:
        repo = Path(directory)
        subprocess.run(["git", "init", "--quiet"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.name", "Dex Fuzz"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "noreply@example.com"], cwd=repo, check=True)
        path = repo / f"{prefix}\n{suffix}.md"
        path.write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "--", path.name], cwd=repo, check=True)
        subprocess.run(["git", "commit", "--quiet", "-m", "newline path"], cwd=repo, check=True)

        with pytest.raises(ManifestError, match="newline manifest"):
            generate_manifest(repo)


@given(
    skill_name=st.from_regex(r"[a-z][a-z0-9-]{0,30}", fullmatch=True),
    description=st.text(
        alphabet=st.characters(blacklist_categories=("Cc", "Cs"), blacklist_characters="\r\n"),
        min_size=1,
        max_size=120,
    ).filter(lambda value: value.strip() != ""),
)
@settings(max_examples=50, deadline=None)
def test_skill_frontmatter_accepts_valid_unicode_descriptions(skill_name: str, description: str):
    with tempfile.TemporaryDirectory(prefix="dex-skill-fuzz-") as directory:
        skill_dir = Path(directory) / skill_name
        skill_dir.mkdir()
        skill = skill_dir / "SKILL.md"
        serialized_description = json.dumps(description, ensure_ascii=False)
        skill.write_text(
            f"---\nname: {skill_name}\ndescription: {serialized_description}\n---\n\n# Fixture\n",
            encoding="utf-8",
        )

        assert validate_skill_frontmatter(skill) == []
