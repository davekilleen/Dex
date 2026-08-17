"""Crash-safe first-run transaction seam."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from core.provision_transaction import ProvisionTransactionError, execute, recover


def _entry(
    path: str,
    content: bytes | None,
    *,
    current: bytes | None = None,
    mode: int = 0o644,
) -> dict[str, object]:
    return {
        "path": path,
        "action": "delete" if content is None else "write",
        "content_base64": (
            None if content is None else base64.b64encode(content).decode("ascii")
        ),
        "mode": mode,
        "expected_current_sha256": (
            None if current is None else hashlib.sha256(current).hexdigest()
        ),
        "expected_absent": current is None and content is not None,
    }


def _plan(entries: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "entries": entries,
    }


def test_execute_commits_marker_and_session_deletion_together(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    session = b'{"step":"finalize"}\n'
    (vault / "System/.onboarding-session.json").write_bytes(session)
    marker = b'{"completed":true}\n'

    result = execute(
        vault,
        _plan(
            [
                _entry("System/.onboarding-complete", marker),
                _entry(
                    "System/.onboarding-session.json",
                    None,
                    current=session,
                ),
            ]
        ),
    )

    assert result["receipt"]["transaction_id"]
    assert (vault / "System/.onboarding-complete").read_bytes() == marker
    assert not (vault / "System/.onboarding-session.json").exists()


def test_recover_restores_a_real_killed_first_run_transaction(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    session = b'{"step":"finalize"}\n'
    (vault / "System/.onboarding-session.json").write_bytes(session)
    plan = _plan(
        [
            _entry("System/.onboarding-complete", b'{"completed":true}\n'),
            _entry(
                "System/.onboarding-session.json",
                None,
                current=session,
            ),
        ]
    )
    worker = (
        "import json,sys; "
        "from pathlib import Path; "
        "from core.provision_transaction import execute; "
        "execute(Path(sys.argv[1]), json.loads(sys.stdin.read()))"
    )

    killed = subprocess.run(
        [sys.executable, "-c", worker, str(vault)],
        input=json.dumps(plan),
        text=True,
        capture_output=True,
        env={**os.environ, "DEX_TX_TEST_STOP_AFTER": "mid-apply:0"},
        check=False,
    )

    assert killed.returncode == 137, killed.stderr
    outcomes = recover(vault)
    assert outcomes and outcomes[0]["resumed"] is True
    assert not (vault / "System/.onboarding-complete").exists()
    assert (vault / "System/.onboarding-session.json").read_bytes() == session


def test_execute_refuses_an_adjacent_path_before_mutation(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()

    with pytest.raises(ProvisionTransactionError, match="outside-onboarding-provision"):
        execute(vault, _plan([_entry("README.md", b"not allowed\n")]))

    assert not (vault / "README.md").exists()


def test_corrupt_unfinished_recovery_fails_closed_before_a_new_plan(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    journal = vault / "System/.dex/tx/damaged/journal.jsonl"
    journal.parent.mkdir(parents=True)
    journal.write_text('{"event":"BEGIN"}\nnot-json\n', encoding="utf-8")

    with pytest.raises(ProvisionTransactionError, match="recovery.*quarantined"):
        execute(
            vault,
            _plan([_entry("System/.onboarding-complete", b'{"completed":true}\n')]),
        )

    assert not (vault / "System/.onboarding-complete").exists()
