"""Lane D consent-side customization-migration CLI journeys."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from core.customization_migration.capsule import read_capsule_status, validate_capsule
from core.tests.test_customization_assessment import _linked_customized_vault
from core.tests.test_customization_capsule_create import _manifest_only_vault
from core.tests.vault_observed_writes import snapshot_vault

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(vault: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(REPO_ROOT),
            "VAULT_PATH": str(vault),
        }
    )
    return subprocess.run(
        [sys.executable, "-m", "core.customization_migration.cli", *arguments],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )


def _token(output: str) -> str:
    match = re.search(r"\b[0-9a-f]{64}\b", output)
    assert match, output
    return match.group(0)


def test_status_assess_and_preview_are_plain_and_write_nothing(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)

    for command in ("status", "assess", "preview"):
        before = snapshot_vault(vault)
        result = _run(vault, command)
        after = snapshot_vault(vault)
        assert result.returncode == 0, result.stderr
        assert before == after
        assert result.stdout.strip()

    assert "No customization capsules exist." in _run(vault, "status").stdout
    assert "3 customizations" in _run(vault, "assess").stdout
    preview = _run(vault, "preview").stdout
    assert "Capsule ID:" in preview
    assert "Preview SHA-256:" in preview


def test_assess_unknown_prints_no_counts(tmp_path: Path) -> None:
    vault = _manifest_only_vault(tmp_path)

    result = _run(vault, "assess")

    assert result.returncode == 0
    assert result.stdout.strip() == (
        "Nothing could be verified, so no customization counts are shown."
    )


def test_create_requires_current_printed_token_and_stale_token_writes_nothing(
    tmp_path: Path,
) -> None:
    vault = _linked_customized_vault(tmp_path)

    before = snapshot_vault(vault)
    missing = _run(vault, "create")
    assert missing.returncode != 0
    assert snapshot_vault(vault) == before
    current = _token(missing.stdout)

    stale = _run(vault, "create", "--confirm-token", "0" * 64)
    assert stale.returncode != 0
    assert _token(stale.stdout) == current
    assert snapshot_vault(vault) == before

    created = _run(vault, "create", "--confirm-token", current)
    assert created.returncode == 0, created.stderr
    status = read_capsule_status(vault)
    assert len(status.capsules) == 1
    assert validate_capsule(vault, status.capsules[0].capsule_id).status == "OK"


def test_abandon_requires_acknowledgement(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)
    token = _token(_run(vault, "preview").stdout)
    created = _run(vault, "create", "--confirm-token", token)
    assert created.returncode == 0
    capsule_id = read_capsule_status(vault).capsules[0].capsule_id
    before = snapshot_vault(vault)

    refused = _run(vault, "abandon", capsule_id)

    assert refused.returncode != 0
    assert "would abandon" in refused.stdout.lower()
    assert snapshot_vault(vault) == before

    accepted = _run(vault, "abandon", capsule_id, "--acknowledge")
    assert accepted.returncode == 0
    assert read_capsule_status(vault).capsules[0].state.value == "abandoned"


def test_cli_has_no_force_shortcuts_and_never_reads_stdin(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)

    for option in ("--yes", "--force"):
        result = _run(vault, "create", option)
        assert result.returncode != 0
    source = (REPO_ROOT / "core/customization_migration/cli.py").read_text()
    assert "input(" not in source
    assert "sys.stdin" not in source


def test_mcp_and_cli_assessment_dicts_are_canonical_json_identical(
    tmp_path: Path, monkeypatch
) -> None:
    from core.customization_migration import cli
    from core.mcp import customization_migration_server as server

    vault = _linked_customized_vault(tmp_path)
    monkeypatch.setenv("VAULT_PATH", str(vault))

    cli_bytes = cli.canonical_assessment_bytes(vault)
    mcp_bytes = server.canonical_assessment_bytes(vault)

    assert cli_bytes == mcp_bytes
    assert cli_bytes == (
        json.dumps(
            json.loads(cli_bytes),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()


def test_registration_snippet_shape_is_pinned() -> None:
    from core.customization_migration.registration import mcp_registration_snippet

    assert mcp_registration_snippet() == {
        "customization-migration": {
            "command": "python3",
            "args": ["-m", "core.mcp.customization_migration_server"],
            "env": {"VAULT_PATH": "{{VAULT_PATH}}"},
        }
    }
