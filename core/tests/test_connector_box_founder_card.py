"""Hand-written founder card for the unpublished MCP connector box."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CARD = REPO_ROOT / "docs" / "founder-cards" / "connector-box.md"
LAB_ISSUE = "https://github.com/davekilleen/dex-product-gtm-lab/issues/486"
ASK_ISSUE = "https://github.com/davekilleen/dex-product-gtm-lab/issues/515"
LATELY_ISSUE = "https://github.com/davekilleen/dex-product-gtm-lab/issues/537"
OPEN_ITEMS_ISSUE = "https://github.com/davekilleen/dex-product-gtm-lab/issues/559"
TODAY_PEOPLE_ISSUE = "https://github.com/davekilleen/dex-product-gtm-lab/issues/571"
PACK_COMMAND = "python3 scripts/build-mcp-registry-artifact.py --output-dir build/mcp-registry-artifact"
LEAVE_SENTENCE = "delete the packed file and build folder"
MODEL_OR_VENDOR = re.compile(
    r"(?i)\b(openai|anthropic|anysphere|gpt-4|gpt-5|grok|sonnet|opus|haiku|llama)\b"
)
FORBIDDEN_STEP = re.compile(r"(?i)\b(publish|sign|store the secret|invite)\b")
CATALOGUE_INSTALL = re.compile(
    r"(?i)(npx -y dex-mcp|add this one line|install from the (official |public )?catalogue|"
    r"mcp-publisher publish|npm publish)"
)


def test_founder_card_walks_pack_checksum_and_future_name() -> None:
    card = CARD.read_text(encoding="utf-8")
    assert LAB_ISSUE in card
    assert ASK_ISSUE in card
    assert LATELY_ISSUE in card
    assert OPEN_ITEMS_ISSUE in card
    assert TODAY_PEOPLE_ISSUE in card
    assert PACK_COMMAND in card
    assert "SHA-256 sidecar" in card
    assert "io.github.davekilleen/dex" in card
    assert "one_line_after_publish" in card
    assert "decision record" in card
    assert "what was decided" in card
    assert "no topic" in card
    assert "lately" in card
    assert "still open with people" in card
    assert "person pages" in card
    assert "who is in today's plan" in card
    assert "plan order" in card
    assert "never guessed" in card
    assert LEAVE_SENTENCE in card
    assert "Nobody has walked this card" in card
    assert "Do not publish" in card
    assert "Decision ask answered from a decision record" in card
    assert "Lately ask answered with no topic" in card
    assert "Open items with people listed from person pages" in card
    assert "People in today's plan listed from the plan and person pages" in card
    headings = [line for line in card.splitlines() if line.startswith("### Step ")]
    assert headings == [
        "### Step 1",
        "### Step 2",
        "### Step 3",
        "### Step 4",
        "### Step 5",
        "### Step 6",
        "### Step 7",
    ]
    assert card.count("- [ ] I saw that.") == 7


def test_founder_card_has_no_catalogue_install_or_publish_step() -> None:
    card = CARD.read_text(encoding="utf-8")
    steps = card.split("## After the last checkbox", 1)[0]
    assert CATALOGUE_INSTALL.search(steps) is None
    assert "Do not add that line to an app" in card
    for line in steps.splitlines():
        if line.startswith("1. "):
            assert FORBIDDEN_STEP.search(line) is None
    assert MODEL_OR_VENDOR.search(card) is None


def test_unreleased_card_is_kept_out_of_user_distribution() -> None:
    ignored = (REPO_ROOT / ".distignore").read_text(encoding="utf-8")
    assert "docs/founder-cards/" in ignored
    assert CARD.is_file()


def test_live_publish_refusal_guard_source_is_still_present() -> None:
    tests = (REPO_ROOT / "core" / "tests" / "test_mcp_registry_artifact.py").read_text(
        encoding="utf-8"
    )
    builder = (REPO_ROOT / "scripts" / "build-mcp-registry-artifact.py").read_text(encoding="utf-8")
    hook = (REPO_ROOT / "packages" / "dex-mcp" / "scripts" / "refuse-live-npm-publish.mjs").read_text(
        encoding="utf-8"
    )
    assert "def test_live_npm_publish_is_refused" in tests
    assert (
        'builder._forbid_live_publish(["mcp-publisher", "publish", "server.json", "--dry-run"])'
        in tests
    )
    assert 'raise RegistryArtifactError(f"refusing mcp-publisher publish: {joined}")' in builder
    assert "Dex MCP is unreleased. Use npm publish --dry-run only. Do not publish." in hook
