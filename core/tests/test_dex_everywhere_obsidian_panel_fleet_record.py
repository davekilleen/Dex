"""The 5a668005 record names green Dex CI and the named reason fleet did not run."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPO_ROOT / "docs" / "plans" / "2026-08-27-dex-everywhere-codex-evidence.md"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "historic-fleet-darwin.yml"

DEX_CI_RUN = "https://github.com/davekilleen/Dex/actions/runs/33257882657"
SUCCESSOR_FLEET_CANARY_RUN = "https://github.com/davekilleen/Dex/actions/runs/33247935319"
RECORDED_SHA = "5a668005"
FULL_SHA = "5a6680050c308eacf01ba2247b3d153a78b2b307"
SUCCESSOR_SHA = "77242824"

FLEET_WATCHED_PATHS = {
    ".github/workflows/historic-fleet-darwin.yml",
    "package.json",
    "core/update/journey-protocol-v1.json",
    "scripts/build-release.sh",
    "scripts/build-vault-bundle.sh",
    "scripts/check-release-catalog-tag-identity.py",
    "scripts/compose-vault-gitignore.py",
    "scripts/dex_update_bridge.py",
    "scripts/release_fleet.py",
    "scripts/release_fleet_acceptance.py",
    "scripts/release_fleet_executor.py",
    "scripts/run-historic-fleet-darwin.sh",
}


def test_evidence_names_5a668005_dex_ci_and_the_path_filter_reason_fleet_did_not_run() -> None:
    text = EVIDENCE.read_text(encoding="utf-8")
    lowered = text.lower()
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    watched = set(triggers["pull_request"]["paths"])

    assert watched == FLEET_WATCHED_PATHS
    assert DEX_CI_RUN in text
    assert SUCCESSOR_FLEET_CANARY_RUN in text
    assert RECORDED_SHA in text
    assert FULL_SHA in text
    assert SUCCESSOR_SHA in text
    assert "green" in lowered
    assert "success" in lowered
    assert "did not run" in lowered
    assert "watched release/fleet files" in lowered
    assert "read-only" in lowered
    assert "community store" in lowered
    assert "do not bump a watched path" in lowered
    assert "not a person-can-open win" in lowered
    assert "no person opened a host" in lowered
    assert "not itself the freeze" in lowered
    assert "that is not this head" in lowered
    assert "ubuntu cloud is not a person opening obsidian" in lowered
    assert "someone opened a host" not in lowered
    assert "opened a live install" not in lowered
    assert "pending" not in lowered
    assert "in_progress" not in lowered
