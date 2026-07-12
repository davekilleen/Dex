"""Guard the diff-gate scripts against re-shallowing the base ref.

The PR diff gates (path-contract, doc-drift, test-delta, coverage) compute
`git merge-base HEAD origin/<base>`. Fetching the base ref with `--depth=1`
grafts it with no parents, so merge-base can't find the common ancestor and the
gate fails with a spurious "no common ancestor" error — which is exactly what
happened in CI (a `--depth=1`-in-CI fetch from an earlier fix). These tests pin
the base-ref fetch to a plain fetch so that regression can't return.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"

SHELL_GATES = [
    "check-path-contract-usage.sh",
    "check-doc-drift.sh",
    "check-test-delta.sh",
]
PY_GATE = "check-coverage-threshold.py"


def test_shell_gates_do_not_shallow_fetch_the_base_ref():
    for name in SHELL_GATES:
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        assert 'git fetch origin "$BASE_REF"' in text, f"{name} must fetch the base ref"
        offenders = [
            line.strip()
            for line in text.splitlines()
            if "git fetch" in line and "$BASE_REF" in line and "--depth" in line
        ]
        assert offenders == [], f"{name} must not --depth-fetch the base ref: {offenders}"


def test_coverage_gate_does_not_shallow_fetch_the_base_ref():
    text = (SCRIPTS / PY_GATE).read_text(encoding="utf-8")
    # The base-ref fetch must not append --depth (which grafts away ancestry).
    assert not re.search(r'"--depth', text), f"{PY_GATE} must not --depth-fetch the base ref"
    assert '"fetch", "origin", base_ref' in text, f"{PY_GATE} must fetch the base ref"
