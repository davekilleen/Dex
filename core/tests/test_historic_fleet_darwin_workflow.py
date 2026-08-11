"""Static safety contract for the first-party macOS historic fleet workflow."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/historic-fleet-darwin.yml"
CI_WORKFLOW_PATH = REPO_ROOT / ".github/workflows/ci.yml"
RUNNER_PATH = REPO_ROOT / "scripts/run-historic-fleet-darwin.sh"
PINNED_ACTION = re.compile(r"^[^@]+@[0-9a-f]{40}$")


def _workflow() -> dict[str, object]:
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_formal_workflow_is_manual_read_only_and_pinned() -> None:
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    assert workflow["name"] == "historic-fleet-darwin"
    assert set(triggers) == {"workflow_dispatch", "pull_request"}
    inputs = triggers["workflow_dispatch"]["inputs"]
    assert inputs["foundation_tag"]["required"] is True
    assert (
        inputs["foundation_tag"]["default"] == "dist/release/v1.81.16-281202d"
    )
    assert inputs["follow_up_tag"]["required"] is True
    assert workflow["permissions"] == {"contents": "read"}

    for job in workflow["jobs"].values():
        assert job["runs-on"] == "macos-14"
        assert 1 <= job["timeout-minutes"] <= 360
        for step in job["steps"]:
            if "uses" in step:
                assert PINNED_ACTION.fullmatch(step["uses"])
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False

    formal = workflow["jobs"]["historic-fleet-darwin"]
    assert formal["name"] == "historic-fleet-darwin"
    assert formal["if"] == "github.event_name == 'workflow_dispatch'"
    assert any(
        step.get("run") == "bash scripts/run-historic-fleet-darwin.sh formal"
        for step in formal["steps"]
    )
    upload = formal["steps"][-1]
    assert upload["if"] == "always()"
    assert upload["with"]["if-no-files-found"] == "warn"


def test_stable_release_and_formal_fleet_share_non_cancelling_route_lock() -> None:
    fleet_workflow = _workflow()
    ci_workflow = yaml.safe_load(CI_WORKFLOW_PATH.read_text(encoding="utf-8"))
    expected_lock = {
        "group": "stable-public-route",
        "cancel-in-progress": False,
    }

    assert fleet_workflow["jobs"]["historic-fleet-darwin"]["concurrency"] == expected_lock
    assert ci_workflow["jobs"]["build-release"]["concurrency"] == expected_lock
    assert "concurrency" not in fleet_workflow["jobs"]["historic-fleet-darwin-pr-canary"]
    assert "concurrency" not in ci_workflow["jobs"]["build-release-beta"]


def test_release_version_bump_triggers_the_pr_canary() -> None:
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    pull_request_paths = set(triggers["pull_request"]["paths"])

    assert "package.json" in pull_request_paths


def test_twelve_start_pr_canary_is_release_shaped_and_cannot_publish() -> None:
    workflow = _workflow()
    canary = workflow["jobs"]["historic-fleet-darwin-pr-canary"]
    assert canary["if"] == "github.event_name == 'pull_request'"
    assert any(
        step.get("name") == "Run twelve release-shaped macOS journeys"
        for step in canary["steps"]
    )
    assert any(
        step.get("run") == "bash scripts/run-historic-fleet-darwin.sh canary"
        for step in canary["steps"]
    )
    source = RUNNER_PATH.read_text(encoding="utf-8")
    canary_block = re.search(
        r'^CANARY_STARTS=\(\n(?P<body>(?:  "[^"]+"\n)+)\)$',
        source,
        re.MULTILINE,
    )
    assert canary_block is not None
    canary_starts = tuple(
        re.findall(r'^  "([^"]+)"$', canary_block.group("body"), re.MULTILINE)
    )
    assert len(canary_starts) == 12
    assert canary_starts == (
        "v1.51.0",
        "dist/release/v1.61.0-dc7d332",
        "dist/archive/v1.61.0-1ec1387",
        "v1.62.0",
        "dist/archive/v1.63.0-08ce719",
        "dist/archive/v1.65.0-c5ec161",
        "dist/archive/v1.72.0-7d75da9",
        "dist/archive/v1.76.0-d0bb932",
        "v1.81.1",
        # The release-tag archive renamed this exact annotated tag (object
        # 8fe3516f, commit b17ef028) from dist/release/ to dist/archive/.
        "dist/archive/v1.81.1-b17ef02",
        "v1.81.7",
        "v1.81.11",
    )
    assert "build-release.sh --source candidate --target release" in source
    assert "build-vault-bundle.sh" in source
    assert source.count("--controlled-approvals") == 1
    assert source.count("--follow-up-cache") == 1
    assert "--follow-up-cache" not in source.split("run_canary()", 1)[0]
    assert "git push" not in source
    assert "gh release" not in source
    assert "GH_TOKEN" not in WORKFLOW_PATH.read_text(encoding="utf-8")


def test_formal_runner_freezes_public_cohort_and_retains_exact_counts() -> None:
    source = RUNNER_PATH.read_text(encoding="utf-8")
    assert 'PINNED_FOUNDATION_TAG="dist/release/v1.81.16-281202d"' in source
    assert 'MAX_DISK_KIB=$((50 * 1024 * 1024))' in source
    assert "release_fleet_acceptance.py cohort" in source
    assert "release_fleet_acceptance.py session" in source
    assert '"platform"' in source
    assert "release_fleet_acceptance.py aggregate" in source
    assert "CANONICAL_PUBLIC_REMOTE" in source
    assert "shasum -a 256 -c" in source
    for count in ("discovered", "started", "completed", "passed", "failed"):
        assert f'"{count}"' in source


def test_runner_has_valid_bash_syntax() -> None:
    subprocess.run(["bash", "-n", str(RUNNER_PATH)], check=True)
