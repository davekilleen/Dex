"""The branch-protection script must never remove a required check.

`scripts/configure-branch-protection.sh` submits the whole protection object
with a `PUT`, so whatever it omits is deleted. It used to name only
`Dex CI / quality` — a job that runs no pytest — while the live branch also
required `Dex CI / test-results`, which carries the Python suite verdict and
both coverage gates. Running the repository's own protection script would have
stopped a red test suite from blocking a merge.

These tests pin the two properties that make that impossible: the floor names
both checks, and the merge is a union of the floor with whatever is already
live.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts/configure-branch-protection.sh"

# Protection contexts match the name a check run *reports*, which for these is
# the bare job name. Verified against
# `gh api repos/davekilleen/Dex/commits/main/check-runs --jq '.check_runs[].name'`,
# which lists quality, test-results, tests (1..3), pr-report and the rest — and
# no "Dex CI / …" name at all.
REQUIRED_FLOOR = ("quality", "test-results")


def _source() -> str:
    return SCRIPT_PATH.read_text(encoding="utf-8")


def _floor_contexts() -> list[str]:
    """Read the contexts the script insists on, from the array itself."""

    match = re.search(
        r"^REQUIRED_CONTEXTS=\(\n(?P<body>(?:  \"[^\"]+\"\n)+)\)$",
        _source(),
        re.MULTILINE,
    )
    assert match is not None, "the script no longer declares a required floor"
    return re.findall(r'^  "([^"]+)"$', match.group("body"), re.MULTILINE)


def _merge_program() -> str:
    """Extract the embedded merge step so it can be run on its own."""

    match = re.search(
        r"python3 <<'PY'\n(?P<body>.*?)\nPY\n",
        _source(),
        re.DOTALL,
    )
    assert match is not None, "the script no longer embeds a merge step"
    return match.group("body")


def _merge(required: tuple[str, ...], live: object) -> list[str]:
    completed = subprocess.run(
        ["python3", "-c", _merge_program()],
        capture_output=True,
        text=True,
        check=True,
        env={
            "REQUIRED": "\n".join(required),
            "LIVE": json.dumps(live),
            "PATH": "/usr/bin:/bin",
        },
    )
    return json.loads(completed.stdout)


def test_script_has_valid_bash_syntax() -> None:
    subprocess.run(["bash", "-n", str(SCRIPT_PATH)], check=True)


def test_the_floor_names_the_job_that_actually_runs_the_tests() -> None:
    assert _floor_contexts() == list(REQUIRED_FLOOR)
    # The live value is read before the PUT; without that read the script can
    # only ever replace, which is how it became a booby trap.
    assert "required_status_checks.contexts" in _source()


def test_the_floor_uses_reported_job_names_not_workflow_display_names() -> None:
    """A required context nothing reports blocks every merge forever.

    The first version of this script required "Dex CI / quality". No check run
    reports that name, so the branch would have waited on a status that can
    never arrive — a protection script that had never been run against reality.
    """

    assert _floor_contexts() == list(REQUIRED_FLOOR)
    # The prose may still cite the broken name as a warning; the array may not.
    assert not any("/" in context for context in _floor_contexts())
    # The script must check its own names against real check runs before writing.
    assert "check-runs" in _source()


def test_a_live_check_outside_the_floor_survives_a_run() -> None:
    merged = _merge(
        REQUIRED_FLOOR,
        ["quality", "historic-fleet-darwin-pr-canary"],
    )

    assert "historic-fleet-darwin-pr-canary" in merged
    for context in REQUIRED_FLOOR:
        assert context in merged


def test_the_floor_is_applied_when_the_branch_has_no_protection() -> None:
    assert _merge(REQUIRED_FLOOR, []) == list(REQUIRED_FLOOR)


def test_an_unreadable_live_value_still_yields_the_floor() -> None:
    """A token without administration scope must not silently drop the floor."""

    assert _merge(REQUIRED_FLOOR, None) == list(REQUIRED_FLOOR)
    assert _merge(REQUIRED_FLOOR, {"unexpected": True}) == list(REQUIRED_FLOOR)


def test_the_merge_never_shrinks_and_never_duplicates() -> None:
    live = ["test-results", "quality", "some/other-check"]
    merged = _merge(REQUIRED_FLOOR, live)

    assert set(live).issubset(set(merged))
    assert len(merged) == len(set(merged))
