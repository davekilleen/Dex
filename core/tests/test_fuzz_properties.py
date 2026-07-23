from __future__ import annotations

import copy
import json
import random
import subprocess
import tempfile
from pathlib import Path

import pytest

try:
    from hypothesis import given, settings
    from hypothesis import strategies as st
except ModuleNotFoundError:
    class _MissingStrategy:
        def filter(self, _predicate):
            return self

    class _MissingStrategies:
        def __getattr__(self, _name):
            return lambda *args, **kwargs: _MissingStrategy()

    def given(**_strategies):
        return pytest.mark.skip(reason="hypothesis is not installed in this test environment")

    def settings(*_args, **_kwargs):
        return lambda function: function

    st = _MissingStrategies()

from core.lifecycle.catalog import CatalogError, loads_catalog, with_catalog_identity
from core.mcp import work_server
from core.mcp.update_checker import parse_version
from core.tests.test_release_catalog import MANIFEST_BYTES, valid_document
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


@pytest.mark.fuzz
def test_release_catalog_random_invalid_mutations_never_parse_silently():
    """E3: deterministic bounded mutations must all fail closed."""
    rng = random.Random(0xCA7A10B1)
    mutations = (
        lambda d: d.update({f"unknown_{rng.randrange(1_000_000)}": True}),
        lambda d: d.pop(rng.choice(tuple(d))),
        lambda d: d.update({"catalog_version": rng.choice((0, 2, 99, "1"))}),
        lambda d: d["release"].update({"source_commit": f"{rng.randrange(10**8):08d}"}),
        lambda d: d["release"]["manifest"].update({"sha256": "x" * rng.randrange(1, 63)}),
        lambda d: d["items"][0].update({"kind": rng.choice((None, 1, [], {}))}),
        lambda d: d["items"][0]["files"][0].update({"ownership_class": "user-ish"}),
        lambda d: d["items"][0]["rewind"].update({"token": f"guess-{rng.randrange(999)}"}),
        lambda d: d["integrity"].update({"catalog_sha256": "0" * 63}),
    )

    for _ in range(180):
        document = copy.deepcopy(valid_document())
        rng.choice(mutations)(document)
        # Recompute identity for structural/model mutations so the parser has
        # to reject the mutation itself rather than merely noticing stale hash.
        integrity = document.get("integrity")
        if isinstance(integrity, dict) and len(integrity.get("catalog_sha256", "")) == 64:
            document = with_catalog_identity(document)
        with pytest.raises(CatalogError, match="UNKNOWN"):
            loads_catalog(json.dumps(document), manifest_bytes=MANIFEST_BYTES)
