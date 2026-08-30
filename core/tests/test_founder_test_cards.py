"""Founder test cards stay aligned with written harness adapter paths."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = REPO_ROOT / "scripts" / "generate-founder-test-cards.py"
ADAPTERS = REPO_ROOT / "core" / "harnesses" / "adapters"
CARDS = REPO_ROOT / "docs" / "founder-test-cards"
WORK_ID = "chatgpt-work"
LAB_ISSUE = "https://github.com/davekilleen/dex-product-gtm-lab/issues/460"


def _load_generator():
    spec = importlib.util.spec_from_file_location(
        "generate_founder_test_cards", GENERATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_written_cards_are_current() -> None:
    assert _load_generator().check_pages(REPO_ROOT) == 0


def test_one_card_per_adapter_with_written_install_prose() -> None:
    generator = _load_generator()
    adapters = generator.load_written_adapters(REPO_ROOT)
    ids = [adapter["harness_id"] for adapter in adapters]
    assert WORK_ID in ids
    assert "agent-plugin" not in ids
    assert ids == sorted(ids)
    for adapter in adapters:
        prose = adapter["example"].get("install_guide") or adapter["example"].get("note")
        assert prose
        card = (CARDS / f"{adapter['harness_id']}.md").read_text(encoding="utf-8")
        assert prose in card
        assert LAB_ISSUE in card
        assert "Do not publish." in card
        assert "Not a live install." in card
        assert "- [ ] I saw that." in card
        assert "If this fails, send back this exact sentence:" in card
        for key, value in generator._named_fields(adapter["example"]):
            assert f"`{key}`: `{value}`" in card


def test_work_card_stops_at_the_folder_grant_and_does_not_invent_it() -> None:
    generator = _load_generator()
    adapter = json.loads((ADAPTERS / f"{WORK_ID}.json").read_text(encoding="utf-8"))
    card = (CARDS / f"{WORK_ID}.md").read_text(encoding="utf-8")
    grant = adapter["example"]["vault_grant"]
    steps, limits, stopped = generator.split_guide(
        {**adapter, "_source_path": f"core/harnesses/adapters/{WORK_ID}.json"}
    )

    assert stopped is True
    assert grant in steps[-1]
    assert card.index("### Step ") < card.index("## This card stops at the folder grant")
    last_step_heading = [line for line in card.splitlines() if line.startswith("### Step ")][-1]
    assert last_step_heading == f"### Step {len(steps)}"
    after_stop = card.split("## This card stops at the folder grant", 1)[1]
    assert "### Step " not in after_stop
    assert "lab 455" in card.lower()
    assert "does not invent that grant" in card.lower()
    assert "live install" in card.lower()
    assert "not a live install" in card.lower()
    for forbidden in (
        "live session",
        "person opened",
        "dex answered",
        "publish to",
        "submit to",
    ):
        assert forbidden not in card.lower()
    assert any("ubuntu cloud" in item.lower() for item in limits)
    assert any("web cannot" in item.lower() for item in limits)


def test_no_card_has_a_publish_or_invite_step() -> None:
    generator = _load_generator()
    for adapter in generator.load_written_adapters(REPO_ROOT):
        steps, _limits, _stopped = generator.split_guide(adapter)
        for sentence in steps:
            assert generator.FORBIDDEN_STEP_ACTION.search(sentence) is None
            lower = sentence.lower()
            assert "publish" not in lower
            assert "invite" not in lower


def test_generator_check_detects_drift_in_a_fixture(tmp_path: Path) -> None:
    generator = _load_generator()
    fixture = tmp_path / "repo"
    shutil.copytree(ADAPTERS, fixture / "core" / "harnesses" / "adapters")
    shutil.copytree(CARDS, fixture / "docs" / "founder-test-cards")

    drifted = fixture / "docs" / "founder-test-cards" / f"{WORK_ID}.md"
    drifted.write_text(drifted.read_text(encoding="utf-8") + "\nextra\n", encoding="utf-8")
    assert generator.check_pages(fixture) == 1

    shutil.copytree(
        CARDS, fixture / "docs" / "founder-test-cards", dirs_exist_ok=True
    )
    adapter = fixture / "core" / "harnesses" / "adapters" / f"{WORK_ID}.json"
    payload = json.loads(adapter.read_text(encoding="utf-8"))
    payload["example"]["install_guide"] += " Extra written sentence."
    adapter.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    assert generator.check_pages(fixture) == 1


def test_work_split_does_not_continue_past_the_grant() -> None:
    generator = _load_generator()
    adapter = json.loads((ADAPTERS / f"{WORK_ID}.json").read_text(encoding="utf-8"))
    adapter["_source_path"] = f"core/harnesses/adapters/{WORK_ID}.json"
    steps, limits, stopped = generator.split_guide(adapter)
    assert stopped is True
    joined_steps = " ".join(steps).lower()
    joined_limits = " ".join(limits).lower()
    assert "grant the dex vault folder" in joined_steps
    assert joined_steps.strip().endswith("grant the dex vault folder.")
    assert "already opened" in joined_limits
    assert "ubuntu cloud" in joined_limits
    assert "web cannot" in joined_limits
    assert "already opened" not in joined_steps
    assert "live install" not in joined_steps


def test_index_lists_every_written_card_and_keeps_work_as_stop() -> None:
    index = (CARDS / "README.md").read_text(encoding="utf-8")
    generator = _load_generator()
    for adapter in generator.load_written_adapters(REPO_ROOT):
        harness_id = adapter["harness_id"]
        assert f"[`{harness_id}`](./{harness_id}.md)" in index
    assert "stops at the folder grant" in index
    assert LAB_ISSUE in index
    assert "Do not publish." in index
    assert "agent-plugin" not in index


def test_ci_quality_job_runs_the_founder_card_drift_gate() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "python scripts/generate-founder-test-cards.py --check" in workflow


def test_unreleased_cards_are_kept_out_of_user_distribution() -> None:
    ignored = (REPO_ROOT / ".distignore").read_text(encoding="utf-8")
    assert "docs/founder-test-cards/" in ignored
