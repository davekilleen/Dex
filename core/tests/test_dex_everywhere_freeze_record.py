"""The 77242824 record names the two GitHub runs and does not claim a person opened a host."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPO_ROOT / "docs" / "plans" / "2026-08-27-dex-everywhere-codex-evidence.md"

DEX_CI_RUN = "https://github.com/davekilleen/Dex/actions/runs/33247935335"
FLEET_CANARY_RUN = "https://github.com/davekilleen/Dex/actions/runs/33247935319"
RECORDED_SHA = "77242824"


def test_evidence_names_77242824_runs_and_does_not_claim_a_person_opened_a_host() -> None:
    text = EVIDENCE.read_text(encoding="utf-8")
    lowered = text.lower()

    assert DEX_CI_RUN in text
    assert FLEET_CANARY_RUN in text
    assert RECORDED_SHA in text
    assert "green" in lowered
    assert "pending" in lowered
    assert "in_progress" in lowered
    assert "not a person-can-open win" in lowered
    assert "no person opened a host" in lowered
    assert "does not claim" in lowered
    assert "77242824` is the freeze" in lowered or "77242824 is the freeze" in lowered
    assert "a person opened a host" not in lowered
    assert "someone opened a host" not in lowered
    assert "opened a live install" not in lowered
