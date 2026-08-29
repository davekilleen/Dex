"""The 65a8d056 record names the green Dex CI run and does not claim a person opened VS Code or Kiro."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPO_ROOT / "docs" / "plans" / "2026-08-27-dex-everywhere-codex-evidence.md"

DEX_CI_RUN = "https://github.com/davekilleen/Dex/actions/runs/33249674554"
RECORDED_SHA = "65a8d056"


def test_evidence_names_65a8d056_dex_ci_and_does_not_claim_a_person_opened_vscode_or_kiro() -> None:
    text = EVIDENCE.read_text(encoding="utf-8")
    lowered = text.lower()

    assert DEX_CI_RUN in text
    assert RECORDED_SHA in text
    assert "65a8d056a431ddb03df34c3281082410d4b113cd" in text
    assert "green" in lowered
    assert "success" in lowered
    assert "ci freeze" in lowered
    assert "not a person-can-open win" in lowered
    assert "no person opened a host" in lowered
    assert "not itself the freeze" in lowered
    assert "opening visual studio code or kiro on a real machine stays dave's" in lowered
    assert "do not add hooks" in lowered
    assert "do not invent a new host" in lowered
    assert "someone opened a host" not in lowered
    assert "opened a live install" not in lowered
    assert "pending" not in lowered
    assert "in_progress" not in lowered
