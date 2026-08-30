"""Contract tests for the product-facing AGENTS.md distribution bootstrap."""

from __future__ import annotations

from pathlib import Path

from core import portable_contract
from core.utils.manifest import REQUIRED_LIFECYCLE_RELEASE_PATHS

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_AGENTS = REPO_ROOT / "AGENTS.md"
PRODUCT_AGENTS_TEMPLATE = (
    REPO_ROOT / "core/harnesses/templates/product-AGENTS.md"
)


def test_source_contributor_guidance_and_product_template_are_distinct() -> None:
    source_bytes = SOURCE_AGENTS.read_bytes()
    template_bytes = PRODUCT_AGENTS_TEMPLATE.read_bytes()

    assert source_bytes != template_bytes
    assert 0 < len(template_bytes) <= 4096
    assert "AGENTS.md" in (REPO_ROOT / ".distignore").read_text(encoding="utf-8").splitlines()

    template = template_bytes.decode("utf-8")
    assert "installed Dex vault" in template
    assert "not the dex-core development checkout" in template
    assert "read the complete root `CLAUDE.md`" in template
    assert "CLAUDE.md" in template and "missing" in template
    assert "fail loudly" in template


def test_product_template_has_an_explicit_brain_contract_rule() -> None:
    resolution = portable_contract.resolve(
        "core/harnesses/templates/product-AGENTS.md"
    )

    assert resolution.ownership == "brain"
    assert resolution.rule_id == "brain-product-agents-template"
    assert "AGENTS.md" in REQUIRED_LIFECYCLE_RELEASE_PATHS


def test_builders_materialize_the_same_template_before_manifest() -> None:
    for script_name in ("build-release.sh", "build-vault-bundle.sh"):
        script = (REPO_ROOT / "scripts" / script_name).read_text(encoding="utf-8")
        assert "core/harnesses/templates/product-AGENTS.md" in script
        assert "AGENTS.md" in script
        assert "chmod 0644" in script
        assert "cmp -s" in script
        assert "installed-files.manifest" in script
    release_builder = (REPO_ROOT / "scripts" / "build-release.sh").read_text()
    assert "PRODUCT_AGENTS_TEMPLATE_MODE" in release_builder
    assert '!= "100644"' in release_builder
