"""Tests for the portable skill manifest and adapter generator."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = REPO_ROOT / "scripts" / "generate-agents-skills.py"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_agents_skills", GENERATOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_classifies_every_canonical_skill() -> None:
    generator = _load_generator()
    skills = generator.discover_canonical_skills()
    manifest = generator.load_portability_manifest(REPO_ROOT)
    assert {path.parent.relative_to(REPO_ROOT / ".claude" / "skills").as_posix() for path in skills} == set(
        manifest["skills"]
    )
    assert {entry["classification"] for entry in manifest["skills"].values()} <= {
        "portable",
        "conditional",
        "claude-only",
        "broken",
    }
    assert manifest["skills"]["anthropic-canvas-design"] == {
        "classification": "claude-only",
        "reason": "bundled font licences contain third-party personal contact details",
    }


def test_generator_copies_resources_and_rewrites_only_existing_paths(tmp_path: Path) -> None:
    generator = _load_generator()
    repo = tmp_path / "repo"
    source = repo / ".claude" / "skills" / "demo"
    (source / "scripts").mkdir(parents=True)
    (source / "assets").mkdir()
    (source / "scripts" / "run.sh").write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    (source / "assets" / "logo.txt").write_text("logo\n", encoding="utf-8")
    (source / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo. Use when testing.\n---\n\n"
        "Run `.claude/skills/demo/scripts/run.sh` and read `assets/logo.txt`.\n",
        encoding="utf-8",
    )
    manifest = repo / "core" / "harnesses"
    manifest.mkdir(parents=True)
    (manifest / "portability.json").write_text(
        '{"schema_version":"1.0.0","skills":{"demo":{"classification":"portable"}}}\n',
        encoding="utf-8",
    )
    generator.write_adapters(repo)
    adapter = repo / ".agents" / "skills" / "demo"
    assert (adapter / "scripts" / "run.sh").is_file()
    assert (adapter / "assets" / "logo.txt").is_file()
    text = (adapter / "SKILL.md").read_text(encoding="utf-8")
    assert ".agents/skills/demo/scripts/run.sh" in text
    assert ".agents/skills/demo/assets/logo.txt" not in text
    assert "assets/logo.txt" in text


def test_generator_preserves_custom_skills_and_rejects_missing_references(tmp_path: Path) -> None:
    generator = _load_generator()
    repo = tmp_path / "repo"
    source = repo / ".claude" / "skills" / "demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo. Use when testing.\n---\n\n"
        "Read `.claude/skills/demo/references/missing.md`.\n",
        encoding="utf-8",
    )
    custom = repo / ".agents" / "skills" / "demo-custom"
    custom.mkdir(parents=True)
    marker = custom / "SKILL.md"
    marker.write_text("user-owned\n", encoding="utf-8")
    manifest = repo / "core" / "harnesses"
    manifest.mkdir(parents=True)
    (manifest / "portability.json").write_text(
        '{"schema_version":"1.0.0","skills":{"demo":{"classification":"portable"}}}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing|reference"):
        generator.write_adapters(repo)
    assert marker.read_text(encoding="utf-8") == "user-owned\n"


def test_generator_rejects_host_only_body_commands(tmp_path: Path) -> None:
    generator = _load_generator()
    repo = tmp_path / "repo"
    source = repo / ".claude" / "skills" / "demo"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: demo\ndescription: Demo. Use when testing.\n---\n\n"
        "```bash\nnode .claude/hooks/private.cjs\n```\n",
        encoding="utf-8",
    )
    manifest = repo / "core" / "harnesses"
    manifest.mkdir(parents=True)
    (manifest / "portability.json").write_text(
        '{"schema_version":"1.0.0","skills":{"demo":{"classification":"portable"}}}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="host-only"):
        generator.write_adapters(repo)
