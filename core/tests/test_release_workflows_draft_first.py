"""Workflow-shape contract: nothing in CI may publish a release before its assets.

scripts/release_publish.py enforces the ordering at runtime. These tests enforce
that the workflows actually GO THROUGH it -- because the v1.94.0 incident was not a
bug inside a script, it was two workflows each doing something reasonable on its own.
A future edit that reintroduces a bare `gh release create` without `--draft`, or a
bare `gh release upload`, fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = REPO_ROOT / ".github/workflows"
RELEASE_WORKFLOW = WORKFLOWS / "release.yml"
CI_WORKFLOW = WORKFLOWS / "ci.yml"
PROBER_WORKFLOW = WORKFLOWS / "release-asset-prober.yml"
PUBLISH_SCRIPT = REPO_ROOT / "scripts/release_publish.py"
PROBER_SCRIPT = REPO_ROOT / "scripts/check_release_assets.py"

PINNED_ACTION = re.compile(r"^[^@]+@[0-9a-f]{40}$")


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict):
    # PyYAML parses a bare `on:` key as the boolean True.
    return workflow.get("on", workflow.get(True))


def _all_run_blocks(workflow: dict) -> list[str]:
    blocks = []
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if "run" in step:
                blocks.append(step["run"])
    return blocks


def _every_run_block_in_repo() -> list[tuple[str, str]]:
    found = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        for block in _all_run_blocks(_load(path)):
            found.append((path.name, block))
    return found


# --------------------------------------------------------------------------- #
# The scripts exist and are the only publishing route
# --------------------------------------------------------------------------- #


def test_the_publish_and_prober_scripts_exist() -> None:
    assert PUBLISH_SCRIPT.is_file()
    assert PROBER_SCRIPT.is_file()


def test_no_workflow_creates_a_release_without_draft() -> None:
    """A `gh release create` without `--draft` is the empty-window bug itself."""
    offenders = []
    for name, block in _every_run_block_in_repo():
        for match in re.finditer(r"gh release create\b[^\n]*(?:\\\n[^\n]*)*", block):
            if "--draft" not in match.group(0):
                offenders.append(f"{name}: {match.group(0).strip()[:120]}")
    assert offenders == [], (
        "every release must be created as a draft and made public only after its "
        f"assets are verified; found: {offenders}"
    )


def test_no_workflow_uploads_release_assets_outside_the_verified_path() -> None:
    """`gh release upload` bypasses the read-back proof, so it must not appear."""
    offenders = [
        f"{name}: {block.strip()[:120]}"
        for name, block in _every_run_block_in_repo()
        if re.search(r"gh release upload\b", block)
    ]
    assert offenders == [], (
        "asset uploads must go through scripts/release_publish.py, which reads every "
        f"asset back off the release before publishing; found: {offenders}"
    )


def test_only_the_publish_script_flips_a_release_public() -> None:
    offenders = [
        f"{name}: {block.strip()[:120]}"
        for name, block in _every_run_block_in_repo()
        if "--draft=false" in block
    ]
    assert offenders == [], (
        "making a release public is scripts/release_publish.py's job alone; "
        f"found: {offenders}"
    )


# --------------------------------------------------------------------------- #
# release.yml drafts, and never publishes
# --------------------------------------------------------------------------- #


def test_release_workflow_only_ever_creates_a_draft() -> None:
    workflow = _load(RELEASE_WORKFLOW)
    triggers = _triggers(workflow)
    assert set(triggers) == {"push"}
    assert triggers["push"]["tags"] == ["v*"]

    blocks = _all_run_blocks(workflow)
    assert len(blocks) == 1, "the tag workflow should do exactly one thing"
    body = blocks[0]
    assert "scripts/release_publish.py draft" in body
    assert "publish" not in body.replace("release_publish.py", ""), (
        "the tag workflow must never run the publish step"
    )

    text = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    assert "draft: false" not in text
    assert "prerelease: false" not in text
    assert "softprops" not in text, (
        "the release-creating action was replaced precisely because it published "
        "immediately; do not reintroduce it"
    )


def test_release_workflow_routes_prerelease_versions_to_the_beta_channel() -> None:
    body = _all_run_blocks(_load(RELEASE_WORKFLOW))[0]
    assert "CHANNEL=stable" in body
    assert "*-*) CHANNEL=beta" in body


def test_release_workflow_actions_are_pinned() -> None:
    for job in _load(RELEASE_WORKFLOW)["jobs"].values():
        for step in job.get("steps", []):
            if "uses" in step:
                assert PINNED_ACTION.fullmatch(step["uses"]), step["uses"]


# --------------------------------------------------------------------------- #
# ci.yml publishes only through the verified script
# --------------------------------------------------------------------------- #


def test_both_release_lanes_publish_through_the_verified_script() -> None:
    workflow = _load(CI_WORKFLOW)

    stable = {s["name"]: s for s in workflow["jobs"]["build-release"]["steps"] if "name" in s}
    stable_step = stable["Attach assets, verify them, then make the release public"]
    assert "scripts/release_publish.py publish" in stable_step["run"]
    assert "--channel stable" in stable_step["run"]
    assert stable_step["env"]["GH_TOKEN"] == "${{ github.token }}"

    beta_job = workflow["jobs"]["build-release-beta"]
    beta = {s["name"]: s for s in beta_job["steps"] if "name" in s}
    beta_step = beta["Attach beta assets, verify them, then publish the prerelease"]
    assert "scripts/release_publish.py publish" in beta_step["run"]
    assert "--channel beta" in beta_step["run"]


def test_the_publishing_step_still_runs_only_after_the_full_suite() -> None:
    """Draft-first changes WHEN a release goes public, never WHETHER it was tested."""
    workflow = _load(CI_WORKFLOW)
    for job_name in ("build-release", "build-release-beta"):
        assert workflow["jobs"][job_name]["needs"] == ["quality", "test-results"]


def test_stable_release_verifies_catalog_identity_before_publication() -> None:
    workflow = _load(CI_WORKFLOW)
    steps = workflow["jobs"]["build-release"]["steps"]
    named = {step["name"]: step for step in steps if "name" in step}
    build = named["Build release branch"]["run"]
    push = named["Push release branch and immutable tag"]["run"]
    names = [step["name"] for step in steps if "name" in step]

    assert "set -euo pipefail" in build
    assert "--release-ref release --print-release-tag" in build
    assert "test -n \"$RELEASE_TAG\"" in build
    assert "check-release-catalog-tag-identity.py --release-ref release" in build
    assert "set -euo pipefail" in push
    assert "--release-ref release --remote origin" in push
    assert names.index("Push release branch and immutable tag") < names.index(
        "Attach assets, verify them, then make the release public"
    )


def test_beta_release_verifies_both_catalog_identities_before_push() -> None:
    workflow = _load(CI_WORKFLOW)
    steps = workflow["jobs"]["build-release-beta"]["steps"]
    named = {step["name"]: step for step in steps if "name" in step}
    build = named["Build beta release branch"]["run"]

    assert "set -euo pipefail" in build
    assert (
        "--release-ref release-beta --source-ref beta --print-release-tag"
        in build
    )
    assert "--release-ref release-beta --source-ref beta" in build
    assert 'test -n "$IDENTITY"' in build


def test_the_stable_lane_keeps_the_non_cancelling_publish_lock() -> None:
    """The fleet proof shares this lock; a queued release must wait, not be cancelled."""
    stable = _load(CI_WORKFLOW)["jobs"]["build-release"]
    assert stable["concurrency"] == {
        "group": "stable-public-route",
        "cancel-in-progress": False,
    }


def test_lens_catalog_release_environment_has_a_pr_dry_run() -> None:
    """The release-only Lens step must be exercised before it can burn a version."""
    workflow = _load(CI_WORKFLOW)
    triggers = _triggers(workflow)
    assert "workflow_dispatch" in triggers

    dry_run = workflow["jobs"]["lens-catalog-release-dry-run"]
    assert dry_run["runs-on"] == "macos-latest"
    assert dry_run["permissions"] == {"contents": "read"}
    assert dry_run["if"] == (
        "github.event_name == 'workflow_dispatch' || github.event_name == 'pull_request'"
    )

    steps = {s["name"]: s for s in dry_run["steps"] if "name" in s}
    changed = steps["Decide whether the Lens catalogue release path changed"]["run"]
    assert "python3 scripts/lens-catalog-release-path.py" in changed
    assert '--event-name "$GITHUB_EVENT_NAME"' in changed
    assert '--changed-files "$CHANGED_FILES"' in changed
    assert 'echo "$DECISION" >> "$GITHUB_OUTPUT"' in changed

    release_step = steps["Dry-run the Lens catalogue release environment"]
    assert release_step["if"] == "steps.changes.outputs.should_run == 'true'"
    run = release_step["run"]
    assert "python3 -m venv .lens-venv" in run
    assert ".lens-venv/bin/python -m pip install --quiet 'cryptography>=42' jsonschema" in run
    assert ".lens-venv/bin/python scripts/generate-dex-lens-catalog.py" in run
    assert "--release-root \"$PWD\"" in run
    assert "--output-dir \"$OUTPUT_DIR\"" in run
    assert "--enriched" in run
    assert "--sign" not in run
    assert "dex-lens-catalog-latest.json" in run


def test_stable_release_signs_the_enriched_catalogue_path() -> None:
    workflow = _load(CI_WORKFLOW)
    steps = {
        step["name"]: step
        for step in workflow["jobs"]["build-release"]["steps"]
        if "name" in step
    }
    run = steps["Generate signed Dex Lens catalog"]["run"]

    assert "--enriched" in run
    assert "--sign" in run
    assert "--key-id dex-core-lens-1" in run


def test_lens_catalog_is_generated_before_the_immutable_release_tag_is_pushed() -> None:
    """A catalogue failure must fail the run before a version marker is burned."""
    workflow = _load(CI_WORKFLOW)
    steps = [
        step["name"]
        for step in workflow["jobs"]["build-release"]["steps"]
        if "name" in step
    ]
    assert steps.index("Build self-contained vault bundle") < steps.index(
        "Push release branch and immutable tag"
    )
    assert steps.index("Generate signed Dex Lens catalog") < steps.index(
        "Push release branch and immutable tag"
    )
    assert steps.index("Push release branch and immutable tag") < steps.index(
        "Attach assets, verify them, then make the release public"
    )


def test_the_draft_explains_the_queue_when_the_fleet_proof_holds_the_lock() -> None:
    """A release waiting hours behind the proof must say so, not look stalled."""
    source = PUBLISH_SCRIPT.read_text(encoding="utf-8")
    assert "historic-fleet-darwin.yml" in source
    assert "queued behind it" in source


# --------------------------------------------------------------------------- #
# The prober workflow
# --------------------------------------------------------------------------- #


def test_the_prober_runs_on_a_schedule_and_can_be_run_by_hand() -> None:
    workflow = _load(PROBER_WORKFLOW)
    triggers = _triggers(workflow)
    assert "schedule" in triggers, "a backstop nobody schedules is not a backstop"
    assert triggers["schedule"], "the schedule must actually contain a cron entry"
    assert "workflow_dispatch" in triggers
    assert workflow["permissions"] == {"contents": "read"}


def test_the_prober_schedule_is_slack_enough_to_actually_fire() -> None:
    """An hourly cron here fires NEVER, so asking for one is asking for nothing.

    GitHub's scheduled runs are best-effort, and this repository's are consistently
    very late: measured 2026-08-12 against `nightly-quality.yml` (cron `0 3 * * *`),
    its last eight scheduled runs began 65, 70, 71, 82, 108, 156, 159 and 159 minutes
    after the hour. A tick that is already overdue when the next one arrives gets
    dropped rather than queued -- this workflow's own first two hourly attempts
    (02:17Z and 03:17Z) both failed to run at all.

    So the interval must comfortably exceed the observed slippage. This asserts a
    floor of four hours, which the worst observed delay (159 min) still fits inside.
    """
    schedule = _triggers(_load(PROBER_WORKFLOW))["schedule"]
    assert schedule, "the backstop needs a schedule"
    for entry in schedule:
        hour_field = entry["cron"].split()[1]
        assert hour_field != "*", (
            "an hourly cron cannot fire in this repository -- GitHub's scheduler "
            f"slips well over an hour here. Saw: {entry['cron']!r}"
        )
        if hour_field.startswith("*/"):
            assert int(hour_field[2:]) >= 4, (
                "the interval must exceed GitHub's observed ~2.5h worst-case delay; "
                f"saw {entry['cron']!r}"
            )


def test_the_prober_is_exercised_when_the_prober_itself_changes() -> None:
    """Otherwise the check that watches the release route is the thing nobody watches."""
    paths = _triggers(_load(PROBER_WORKFLOW))["pull_request"]["paths"]
    assert "scripts/check_release_assets.py" in paths
    assert ".github/workflows/release-asset-prober.yml" in paths


def test_the_prober_fails_the_run_when_the_release_is_broken() -> None:
    steps = {s["name"]: s for s in _load(PROBER_WORKFLOW)["jobs"]["probe"]["steps"] if "name" in s}
    fail_step = steps["Fail when the release is not fully downloadable"]
    assert "steps.probe.outputs.status != '0'" in fail_step["if"]
    assert "exit 1" in fail_step["run"]


def test_the_prober_stays_green_when_it_simply_could_not_check() -> None:
    """Crying wolf over a network blip is how a check earns being ignored."""
    steps = {s["name"]: s for s in _load(PROBER_WORKFLOW)["jobs"]["probe"]["steps"] if "name" in s}
    fail_step = steps["Fail when the release is not fully downloadable"]
    assert "steps.probe.outputs.status != '2'" in fail_step["if"]


def test_the_prober_workflow_actions_are_pinned() -> None:
    for job in _load(PROBER_WORKFLOW)["jobs"].values():
        for step in job.get("steps", []):
            if "uses" in step:
                assert PINNED_ACTION.fullmatch(step["uses"]), step["uses"]
