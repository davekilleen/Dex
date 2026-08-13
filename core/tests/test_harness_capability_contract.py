"""Harness capability contract: documented tiers, generated adapters, honest claims.

Mirrors the discipline of ``test_instruction_honesty.py``: live docs cannot
promise a harness more than that tier delivers, and Tier ≤2 surfaces cannot
depend on Claude-only hooks frontmatter.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "generate-agents-skills.py"

TIER_NAMES = (
    "Tier 0 Vault",
    "Tier 1 Core",
    "Tier 2 Skills",
    "Tier 3 Full",
)

# Files that tell users or other harnesses what Dex will do for them.
LIVE_HARNESS_GUIDANCE = (
    "README.md",
    "AGENTS.md",
    ".agents/README.md",
    ".claude/skills/README.md",
    "docs/architecture/HARNESS-CAPABILITY.md",
    "docs/architecture/HOOK-INVENTORY.md",
    "docs/architecture/DEX-CORE-MAP.md",
    "docs/Dex_System/Background_Processing_Guide.md",
    "docs/Dex_System/Dex_Technical_Guide.md",
    "06-Resources/Dex_System/Background_Processing_Guide.md",
    "06-Resources/Dex_System/Dex_Technical_Guide.md",
)

# Claims that Dex itself works on a non-Claude harness. Historical mentions of
# Claude Code as a product, or a harness choosing an execution model, are fine
# without a tier — these phrases are the ones that over-promise.
CROSS_HARNESS_CLAIM = re.compile(
    r"cross-harness|harness-neutral|any MCP-capable harness|"
    r"works across AI assistants|powered by Claude\.",
    re.IGNORECASE,
)

TIER_MENTION = re.compile(r"Tier [0-3]")

# Python/JS surfaces that already qualify as Tier ≤2: they must not *require*
# `.claude/hooks` or `.claude/settings.json` to import or start.
TIER_LE_2_CODE_GLOBS = (
    "core/*.py",
    "core/mcp/*.py",
    "core/lifecycle/*.py",
    "core/utils/*.py",
    "core/context/*.py",
    ".scripts/**/*.cjs",
    ".scripts/**/*.js",
    ".scripts/**/*.py",
)


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_agents_skills", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _frontmatter_keys(text: str) -> set[str]:
    if not text.startswith("---\n"):
        return set()
    try:
        _, frontmatter, _ = text.split("---", 2)
    except ValueError:
        return set()
    keys: set[str] = set()
    for line in frontmatter.splitlines():
        match = re.match(r"^([A-Za-z0-9_-]+):", line)
        if match:
            keys.add(match.group(1))
    return keys


def test_readme_publishes_the_four_capability_tiers() -> None:
    readme = _read("README.md")
    for tier in TIER_NAMES:
        assert tier in readme, f"README.md is missing {tier}"
    assert "Claude Code" in readme
    assert "Tier 3" in readme
    assert "reference" in readme.lower()
    # Claude is the full-experience reference, not the whole product.
    assert "powered by Claude." not in readme


def test_architecture_doc_names_the_same_tiers_and_the_hooks_split() -> None:
    doc = _read("docs/architecture/HARNESS-CAPABILITY.md")
    for tier in TIER_NAMES:
        assert tier in doc
    assert "synchronous in-turn" in doc.lower()
    assert "scheduled" in doc.lower()
    assert "launchd" in doc.lower() or "OS-level" in doc or "operating system" in doc.lower()
    assert ".scripts/meeting-intel" in doc
    assert "Do not mass-migrate" in doc or "not migrated in this change" in doc.lower()
    assert "Claude Code" in doc
    assert "Tier 3" in doc
    assert "boot_today" in doc
    assert "get_person_context" in doc


def test_hook_inventory_has_three_buckets_and_does_not_mass_migrate() -> None:
    doc = _read("docs/architecture/HOOK-INVENTORY.md")
    lowered = doc.lower()
    assert "scheduled" in lowered
    assert "in-turn inject" in lowered or "in-turn inject" in doc.lower()
    assert "gates" in lowered
    assert "do not mass-migrate" in lowered
    assert "boot_today" in doc
    assert "get_person_context" in doc
    assert "session-start.sh" in doc
    assert "person-context-injector.cjs" in doc
    assert "dex-safety-guard.sh" in doc
    assert "com.dex.meeting-intel" in doc
    assert "Tier 1 Core" in doc
    assert "Tier 3 Full" in doc


def test_agents_readme_describes_generation_not_a_hand_mirror() -> None:
    readme = _read(".agents/README.md")
    assert "generate-agents-skills.py" in readme
    assert "adapters" in readme.lower()
    assert "not a second source of truth" in readme.lower()
    assert "Tier 2" in readme
    assert "hand-maintained" not in readme or "no hand-mirror" in readme.lower()


def test_cross_harness_claims_name_a_capability_tier() -> None:
    offenders: dict[str, str] = {}
    for relative in LIVE_HARNESS_GUIDANCE:
        text = _read(relative)
        if CROSS_HARNESS_CLAIM.search(text) and TIER_MENTION.search(text) is None:
            offenders[relative] = "cross-harness claim without a named tier"
    assert offenders == {}


def test_generated_adapters_cover_every_canonical_skill() -> None:
    generator = _load_generator()
    canonical = generator.discover_canonical_skills()
    assert len(canonical) >= 100, "canonical skill surface shrank unexpectedly"
    expected = generator.expected_adapters(REPO_ROOT)
    skill_adapters = [
        path
        for path in expected
        if path.name == "SKILL.md"
    ]
    assert len(skill_adapters) == len(canonical)
    for skill_md in canonical:
        rel = skill_md.parent.relative_to(REPO_ROOT / ".claude" / "skills")
        adapter = Path(".agents") / "skills" / rel / "SKILL.md"
        assert adapter in expected, f"missing adapter for {rel.as_posix()}"
        assert (REPO_ROOT / adapter).is_file()


def test_generated_adapters_strip_claude_only_frontmatter() -> None:
    generator = _load_generator()
    expected = generator.expected_adapters(REPO_ROOT)
    claude_only = generator.CLAUDE_ONLY_FRONTMATTER
    offenders: list[str] = []
    for relative, text in expected.items():
        if relative.name != "SKILL.md":
            continue
        keys = _frontmatter_keys(text)
        leaked = keys & claude_only
        if leaked:
            offenders.append(f"{relative.as_posix()}: {sorted(leaked)}")
        assert "Generated from" in text
    assert offenders == []


def test_tier_le_2_code_does_not_import_claude_hooks() -> None:
    """MCP, core, and scheduled scripts must not import `.claude/hooks`."""
    offenders: list[str] = []
    scanned = 0
    for pattern in TIER_LE_2_CODE_GLOBS:
        for path in REPO_ROOT.glob(pattern):
            if not path.is_file():
                continue
            if "tests" in path.parts or path.suffix not in {".py", ".cjs", ".js"}:
                continue
            scanned += 1
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".py":
                try:
                    tree = ast.parse(text)
                except SyntaxError:
                    continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        if ".claude" in node.module or node.module.startswith("claude"):
                            offenders.append(
                                f"{path.relative_to(REPO_ROOT).as_posix()} imports {node.module}"
                            )
            # A scheduled job or MCP server that *requires* settings.json to
            # start is a Claude-only dependency. Mentioning the path in a
            # comment or an optional diagnostic is allowed; `open(...)` of
            # that file as a module-level constant is not.
            if re.search(
                r"""(?:open|Path)\([^)]*['"]\.claude/(?:hooks/settings|settings\.json)""",
                text,
            ):
                offenders.append(
                    f"{path.relative_to(REPO_ROOT).as_posix()} opens Claude settings at import"
                )
    assert scanned > 20
    assert offenders == []


def test_scheduled_jobs_are_not_claude_hooks() -> None:
    """Launch-agent jobs that already run on a clock are Tier 1, not hooks."""
    promises = _read("docs/architecture/HEALTH-PROMISES.md")
    capability = _read("docs/architecture/HARNESS-CAPABILITY.md")
    for label in (
        "com.dex.meeting-intel",
        "com.dex.smoke-nightly",
        "com.dex.changelog-checker",
        "com.dex.learning-review",
    ):
        assert label in promises
        assert label in capability
    assert ".claude/hooks/" not in _read(".scripts/meeting-intel/install-automation.sh")


@pytest.mark.parametrize(
    "relative",
    (
        ".agents/skills/process-meetings/SKILL.md",
        ".agents/skills/getting-started/SKILL.md",
        ".agents/skills/daily-plan/SKILL.md",
    ),
)
def test_high_traffic_adapters_exist_without_hooks_frontmatter(relative: str) -> None:
    text = _read(relative)
    assert "name:" in text
    assert "hooks:" not in _frontmatter_keys(text)
    assert "context:" not in _frontmatter_keys(text)
    assert "model_routing:" not in _frontmatter_keys(text)
