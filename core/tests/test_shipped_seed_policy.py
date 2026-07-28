"""The starter pages Dex ships must actually ship, and must stay ship-checked.

Dex hands the user starter pages — a goals page, a career evidence page, a
companies page — and users write real work into them. Those paths are covered by
.gitignore (they are user PARA folders), so each one is tracked only because it
was force-added. Dropping one from the index is therefore invisible: no diff
noise, no warning, nothing red. It has happened, and it cost a user their
quarter's goals — their update refused to run rather than touch a file Dex no
longer recognised as its own.

The policy in ``core/migrations/tracked-ignored-policy.yaml`` already declares
what must ship. These tests make the declaration binding.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPO_ROOT / "scripts/check-tracked-ignored.py"
POLICY = REPO_ROOT / "core/migrations/tracked-ignored-policy.yaml"
WORKFLOW = REPO_ROOT / ".github/workflows/ci.yml"


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_tracked_ignored", CHECKER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_tracked_ignored"] = module
    spec.loader.exec_module(module)
    return module


def test_every_declared_seed_is_actually_tracked() -> None:
    """The real repository satisfies its own shipped-seed policy.

    This is the check that would have caught the original defect. It runs
    against the working repository, not a fixture, because a fixture cannot
    decay the way the real index did.
    """
    checker = _load_checker()

    result = checker.check(REPO_ROOT, POLICY)

    assert result["ok"], (
        "Shipped-seed policy is not satisfied. "
        f"errors={result['errors']} "
        f"(expected {result['expected_tracked']} tracked, "
        f"found {result['actual_tracked_ignored']}). "
        "A declared seed must be tracked at its real vault path via `git add -f`; "
        "a copy under .claude/skills/_available/capabilities/ does not count."
    )


def test_the_gate_runs_in_ci_on_every_build() -> None:
    """The guard is only worth anything if it is not optional.

    It must run unconditionally in the quality job — not behind an `if`, and
    not only on pull requests, so a direct push to main cannot drop a seed.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["quality"]["steps"]

    matching = [
        step
        for step in steps
        if "check-tracked-ignored.py" in str(step.get("run", ""))
    ]

    assert len(matching) == 1, "CI must run the shipped-seed gate exactly once"
    assert "if" not in matching[0], "the shipped-seed gate must not be conditional"


@pytest.mark.parametrize(
    "code",
    ["stale-policy-row", "unknown-tracked-ignored", "local-only-still-tracked"],
)
def test_failure_output_states_the_convention(code: str) -> None:
    """A bare error code leaves the next person guessing which copy counts.

    Two placement conventions exist side by side — the vault-root seed and the
    dormant room-pack copy — and only one satisfies the policy. The failure
    message has to say so.
    """
    checker = _load_checker()

    explanation = "\n".join(checker._explain([{"code": code, "paths": ["some/path.md"]}]))

    assert code in explanation
    assert "some/path.md" in explanation
    assert len(checker.CONVENTIONS[code]) > 80


def test_stale_row_message_names_both_placements() -> None:
    checker = _load_checker()

    message = checker.CONVENTIONS["stale-policy-row"]

    assert "git add -f" in message
    assert ".claude/skills/_available/capabilities" in message
    assert "does NOT satisfy" in message


def test_policy_declares_the_three_room_starters() -> None:
    """The pages this whole guard exists to protect are the ones declared."""
    policy = yaml.safe_load(POLICY.read_text(encoding="utf-8"))
    active = next(
        baseline
        for baseline in policy["baselines"]
        if baseline["baseline_version"] == policy["active_baseline_version"]
    )
    declared = {
        row["path"]
        for row in active["paths"]
        if row["classification"] == "intentional-seed"
    }

    for seed in (
        "01-Quarter_Goals/Quarter_Goals.md",
        "05-Areas/Career/Evidence/README.md",
        "05-Areas/Companies/README.md",
    ):
        assert seed in declared
