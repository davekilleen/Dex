"""Obsidian notes-panel founder card stays aligned with the adapter."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = REPO_ROOT / "scripts" / "generate-founder-test-cards.py"
ADAPTERS = REPO_ROOT / "core" / "harnesses" / "adapters"
CARDS = REPO_ROOT / "docs" / "founder-test-cards"
HOST_ID = "obsidian"
LAB_ISSUE = "https://github.com/davekilleen/dex-product-gtm-lab/issues/570"
LEAVE_MARKERS = (
    "disable dex",
    ".obsidian/plugins/dex-readonly",
    "leftover",
    "community-plugins.json",
)
FENCE_MARKERS = (
    "today's brief, then who today's plan names, then decided lately, then a topic ask, then a person name",
    "does not edit notes",
    "does not use the internet",
    "not on any community list",
)


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_founder_test_cards", GENERATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize(text: str) -> str:
    return " ".join(text.replace("`", "").lower().split())


def test_written_cards_are_current() -> None:
    assert _load_generator().check_pages(REPO_ROOT) == 0


def test_this_lot_covers_only_the_obsidian_notes_panel() -> None:
    generator = _load_generator()
    adapters = generator.load_written_adapters(REPO_ROOT)
    ids = [adapter["harness_id"] for adapter in adapters]
    assert ids == [HOST_ID]
    assert "chatgpt-work" not in ids
    assert "agent-plugin" not in ids


def test_obsidian_card_quotes_adapter_and_restates_the_fence() -> None:
    generator = _load_generator()
    adapter = json.loads((ADAPTERS / f"{HOST_ID}.json").read_text(encoding="utf-8"))
    card = (CARDS / f"{HOST_ID}.md").read_text(encoding="utf-8")
    prose = adapter["example"]["install_guide"]
    leave = adapter["example"]["uninstall_guide"]

    assert prose in card
    assert leave in card
    assert LAB_ISSUE in card
    assert "Do not publish." in card
    assert "Not a live install." in card
    assert "Nobody has walked this" in card
    assert "- [ ] I saw that." in card
    lowered = card.lower()
    for marker in FENCE_MARKERS:
        assert marker in lowered
    for marker in LEAVE_MARKERS:
        assert marker in lowered
    assert "nobody has walked this on a real desktop" in lowered
    assert "not on any community list" in lowered
    for key, value in generator._named_fields(adapter["example"]):
        assert f"`{key}`: `{value}`" in card


def test_obsidian_steps_include_the_brief_and_skip_publish() -> None:
    generator = _load_generator()
    adapter = json.loads((ADAPTERS / f"{HOST_ID}.json").read_text(encoding="utf-8"))
    adapter["_source_path"] = f"core/harnesses/adapters/{HOST_ID}.json"
    steps, limits, stopped = generator.split_guide(adapter)
    joined_steps = " ".join(steps).lower()
    joined_limits = " ".join(limits).lower()

    assert stopped is False
    assert any("open the dex folder" in item.lower() for item in steps)
    assert any("dex-readonly" in item.lower() for item in steps)
    assert any("restricted mode" in item.lower() for item in steps)
    assert any("enable dex" in item.lower() for item in steps)
    assert any("today's brief appears" in item.lower() for item in steps)
    assert any("who today's plan names" in item.lower() for item in steps)
    assert any("decided lately" in item.lower() for item in steps)
    assert any("type a topic" in item.lower() for item in steps)
    assert any("type a person's name" in item.lower() for item in steps)
    assert "does not edit notes" in joined_limits
    assert "community store" in joined_limits
    assert "chatgpt work folder grant" in joined_limits
    assert "ubuntu cloud" in joined_limits
    assert "publish" not in joined_steps
    assert "invite" not in joined_steps
    for sentence in steps:
        assert generator.FORBIDDEN_STEP_ACTION.search(sentence) is None


def test_no_card_has_a_publish_or_invite_step() -> None:
    generator = _load_generator()
    for adapter in generator.load_written_adapters(REPO_ROOT):
        steps, _limits, _stopped = generator.split_guide(adapter)
        for sentence in steps:
            assert generator.FORBIDDEN_STEP_ACTION.search(sentence) is None
            lower = sentence.lower()
            assert "publish" not in lower
            assert "invite" not in lower
            assert "sign" not in lower


def test_generator_check_detects_drift_in_a_fixture(tmp_path: Path) -> None:
    generator = _load_generator()
    fixture = tmp_path / "repo"
    shutil.copytree(ADAPTERS, fixture / "core" / "harnesses" / "adapters")
    shutil.copytree(CARDS, fixture / "docs" / "founder-test-cards")

    drifted = fixture / "docs" / "founder-test-cards" / f"{HOST_ID}.md"
    drifted.write_text(drifted.read_text(encoding="utf-8") + "\nextra\n", encoding="utf-8")
    assert generator.check_pages(fixture) == 1

    shutil.copytree(
        CARDS, fixture / "docs" / "founder-test-cards", dirs_exist_ok=True
    )
    adapter = fixture / "core" / "harnesses" / "adapters" / f"{HOST_ID}.json"
    payload = json.loads(adapter.read_text(encoding="utf-8"))
    payload["example"]["install_guide"] += " Extra written sentence."
    adapter.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    assert generator.check_pages(fixture) == 1


def test_index_lists_obsidian_and_keeps_lab_558_open() -> None:
    index = (CARDS / "README.md").read_text(encoding="utf-8")
    assert f"[`{HOST_ID}`](./{HOST_ID}.md)" in index
    assert LAB_ISSUE in index
    assert "Do not publish." in index
    assert "chatgpt-work" not in index
    assert "agent-plugin" not in index
    assert "Nobody has walked this on a real desktop." in index


def test_ci_quality_job_runs_the_founder_card_drift_gate() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "python scripts/generate-founder-test-cards.py --check" in workflow


def test_unreleased_cards_are_kept_out_of_user_distribution() -> None:
    ignored = (REPO_ROOT / ".distignore").read_text(encoding="utf-8")
    assert "docs/founder-test-cards/" in ignored


def test_portability_leave_line_matches_the_adapter() -> None:
    generator = _load_generator()
    adapter = json.loads((ADAPTERS / f"{HOST_ID}.json").read_text(encoding="utf-8"))
    guide = (REPO_ROOT / "docs" / "HARNESS-PORTABILITY.md").read_text(encoding="utf-8")
    leave = adapter["example"]["uninstall_guide"]
    assert _normalize(leave) in _normalize(guide)
    assert "| Harness | How to leave |" in guide
    assert "leftover" in leave.lower()
    for marker in LEAVE_MARKERS:
        assert marker in _normalize(guide)
    card = (CARDS / f"{HOST_ID}.md").read_text(encoding="utf-8")
    assert leave in card
    steps, _limits, _stopped = generator.split_guide(
        {**adapter, "_source_path": f"core/harnesses/adapters/{HOST_ID}.json"}
    )
    assert not any("disable dex" in item.lower() for item in steps)
