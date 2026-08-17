"""A later merge must never cancel a run that could be building a release.

`build-release` runs only on pushes to main. If a main run is cancelled by the next
merge, that release's download files are never built. Draft-first publishing makes
the result safe -- the release stays a hidden draft and the prober flags it -- but a
release nobody ships is still a release nobody gets.

Observed on 2026-08-12 before this was fixed: 10 of the last 15 main runs ended
`cancelled`, each at the exact second the following merge created its run, with no
jobs ever scheduled.

The rule is carried by the concurrency GROUP, not by a boolean expression: a pull
request groups by its number so its own later pushes supersede it, and every other
run groups by its unique run id so it shares a group with nothing.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"
FLEET_WORKFLOW = REPO_ROOT / ".github/workflows/historic-fleet-darwin.yml"


def _ci() -> dict:
    return yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))


def test_non_pull_request_runs_are_alone_in_their_concurrency_group() -> None:
    group = _ci()["concurrency"]["group"]
    assert "github.event.pull_request.number" in group, (
        "pull requests must group by number so their own pushes supersede each other"
    )
    assert "github.run_id" in group, (
        "everything that is not a pull request must group by its unique run id, so a "
        "later merge cannot cancel a run that might be building a release"
    )
    assert "github.ref" not in group, (
        "grouping by ref puts every push to main in ONE group, which is exactly how "
        "main runs were cancelling each other"
    )


def test_the_cancel_rule_is_a_literal_not_an_expression() -> None:
    """An expression here decides a boolean; a wrong answer silently kills releases.

    With the group above, `true` is safe: only pull-request runs ever share a group.
    """
    cancel = _ci()["concurrency"]["cancel-in-progress"]
    assert cancel is True, (
        "expected a literal true (safe, because only pull requests share a group); "
        f"saw {cancel!r}"
    )


def test_ci_matches_the_idiom_the_fleet_workflow_already_uses() -> None:
    """The repo already had this right in one place; the two should not diverge."""
    fleet_group = yaml.safe_load(FLEET_WORKFLOW.read_text(encoding="utf-8"))["concurrency"][
        "group"
    ]
    for token in ("github.event.pull_request.number", "github.run_id"):
        assert token in fleet_group
        assert token in _ci()["concurrency"]["group"]


def test_the_release_lane_is_still_serialised_by_its_own_lock() -> None:
    """Run-level serialisation was never what kept two releases apart.

    Publishing is serialised by the job-level `stable-public-route` lock, which does
    not cancel. Concurrent main runs are therefore safe.
    """
    build_release = _ci()["jobs"]["build-release"]
    assert build_release["concurrency"] == {
        "group": "stable-public-route",
        "cancel-in-progress": False,
    }


def test_build_release_still_only_runs_on_main_pushes() -> None:
    """The premise of this whole file: main is the only place releases get built."""
    condition = _ci()["jobs"]["build-release"]["if"]
    assert "refs/heads/main" in condition
    assert "github.event_name == 'push'" in condition
