"""The b4b4f570 record names green Dex CI and the named reason fleet did not run."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = REPO_ROOT / "docs" / "plans" / "2026-08-27-dex-everywhere-codex-evidence.md"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "historic-fleet-darwin.yml"

DEX_CI_RUN = "https://github.com/davekilleen/Dex/actions/runs/33257694720"
SUCCESSOR_FLEET_CANARY_RUN = "https://github.com/davekilleen/Dex/actions/runs/33247935319"
RECORDED_SHA = "b4b4f570"
FULL_SHA = "b4b4f57055de0abb2cba628ad8e917dc65522294"
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


def test_evidence_names_b4b4f570_dex_ci_and_the_path_filter_reason_fleet_did_not_run() -> None:
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
    assert "packages/dex-mcp/package.json" in text
    assert "not the watched root" in lowered
    assert "unpublished" in lowered
    assert "do not npm publish" in lowered
    assert "do not bump a watched path" in lowered
    assert "not a person-can-open win" in lowered
    assert "no person opened a host" in lowered
    assert "not itself the freeze" in lowered
    assert "that is not this head" in lowered
    assert "someone opened a host" not in lowered
    assert "opened a live install" not in lowered
    assert "pending" not in lowered
    assert "in_progress" not in lowered
