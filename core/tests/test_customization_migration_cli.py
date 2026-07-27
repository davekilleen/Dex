"""Lane D consent-side customization-migration CLI journeys."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from core.customization_migration.capsule import (
    CAPSULE_ROOT,
    read_capsule_status,
    validate_capsule,
)
from core.tests.test_customization_assessment import _linked_customized_vault
from core.tests.test_customization_capsule_create import _manifest_only_vault
from core.tests.test_customization_verification import _candidate_with_contract
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


def _candidate_file(tmp_path: Path, candidate) -> Path:
    path = tmp_path / "candidate.json"
    path.write_text(
        json.dumps(
            candidate.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def _rendered(value: object) -> str:
    if isinstance(value, (dict, list)) or value is None or type(value) is bool:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    return str(value)


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
    capsule_id = status.capsules[0].capsule_id
    assert validate_capsule(vault, capsule_id).status == "OK"
    receipt = json.loads(
        (
            vault
            / "System/.dex/customization-migrations"
            / capsule_id
            / "receipts/capsule.json"
        ).read_text(encoding="utf-8")
    )
    for field in ("capsule_id", "file_count", "byte_count", "transaction_id"):
        assert f"{field}: {receipt[field]}" in created.stdout


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
        "customization-migration-mcp": {
            "command": "{{VAULT_PATH}}/.venv/bin/python",
            "args": [
                "{{VAULT_PATH}}/core/mcp/customization_migration_server.py"
            ],
            "env": {"VAULT_PATH": "{{VAULT_PATH}}"},
        }
    }


def test_rebuild_doorway_runs_real_happy_path_and_renders_every_receipt(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    candidate_path = _candidate_file(tmp_path, candidate)

    before_stage = snapshot_vault(vault)
    refused_stage = _run(vault, "stage", str(candidate_path))
    assert refused_stage.returncode != 0
    assert snapshot_vault(vault) == before_stage
    staging_token = _token(refused_stage.stdout)

    stale_stage = _run(
        vault,
        "stage",
        str(candidate_path),
        "--confirm-token",
        "0" * 64,
    )
    assert stale_stage.returncode != 0
    assert _token(stale_stage.stdout) == staging_token
    assert snapshot_vault(vault) == before_stage

    staged = _run(
        vault,
        "stage",
        str(candidate_path),
        "--confirm-token",
        staging_token,
    )
    assert staged.returncode == 0, staged.stdout
    for field in (
        "capsule_id",
        "proposal_id",
        "staged_file_count",
        "staged_byte_count",
        "staging_digest",
        "transaction_id",
    ):
        assert f"{field}:" in staged.stdout

    verified = _run(
        vault,
        "verify",
        candidate.capsule_id,
        candidate.proposal_id,
    )
    assert verified.returncode == 0, verified.stdout
    report = json.loads(
        (
            vault
            / CAPSULE_ROOT
            / candidate.capsule_id
            / "verification"
            / f"{candidate.proposal_id}.json"
        ).read_text(encoding="utf-8")
    )
    for field, value in report.items():
        assert f"{field}: {_rendered(value)}" in verified.stdout
    for field in (
        "capsule_id",
        "staging_id",
        "report_path",
        "report_sha256",
        "transaction_id",
    ):
        assert f"{field}:" in verified.stdout

    previewed_activation = _run(
        vault,
        "preview-activation",
        candidate.capsule_id,
        candidate.proposal_id,
    )
    assert previewed_activation.returncode == 0, previewed_activation.stdout
    activation_token = _token(previewed_activation.stdout)
    before_activation = snapshot_vault(vault)

    missing_activation = _run(
        vault,
        "activate",
        candidate.capsule_id,
        candidate.proposal_id,
    )
    assert missing_activation.returncode != 0
    assert _token(missing_activation.stdout) == activation_token
    assert snapshot_vault(vault) == before_activation

    stale_activation = _run(
        vault,
        "activate",
        candidate.capsule_id,
        candidate.proposal_id,
        "--confirm-token",
        "0" * 64,
    )
    assert stale_activation.returncode != 0
    assert _token(stale_activation.stdout) == activation_token
    assert snapshot_vault(vault) == before_activation

    activated = _run(
        vault,
        "activate",
        candidate.capsule_id,
        candidate.proposal_id,
        "--confirm-token",
        activation_token,
    )
    assert activated.returncode == 0, activated.stdout
    activation_receipt = json.loads(
        (
            vault
            / "System/.dex/customization-migrations"
            / candidate.capsule_id
            / "receipts/activation.json"
        ).read_text(encoding="utf-8")
    )
    for field, value in activation_receipt.items():
        assert f"{field}: {_rendered(value)}" in activated.stdout

    status = _run(vault, "activation-status", candidate.capsule_id)
    assert status.returncode == 0
    assert "state: activated" in status.stdout
    assert "rewindable: true" in status.stdout

    previewed_rewind = _run(vault, "preview-rewind", candidate.capsule_id)
    assert previewed_rewind.returncode == 0
    rewind_token = _token(previewed_rewind.stdout)
    before_rewind = snapshot_vault(vault)

    missing_rewind = _run(vault, "rewind", candidate.capsule_id)
    assert missing_rewind.returncode != 0
    assert _token(missing_rewind.stdout) == rewind_token
    assert snapshot_vault(vault) == before_rewind

    stale_rewind = _run(
        vault,
        "rewind",
        candidate.capsule_id,
        "--acknowledge-token",
        "0" * 64,
    )
    assert stale_rewind.returncode != 0
    assert _token(stale_rewind.stdout) == rewind_token
    assert snapshot_vault(vault) == before_rewind

    rewound = _run(
        vault,
        "rewind",
        candidate.capsule_id,
        "--acknowledge-token",
        rewind_token,
    )
    assert rewound.returncode == 0, rewound.stdout
    rewind_receipt = json.loads(
        (
            vault
            / "System/.dex/customization-migrations"
            / candidate.capsule_id
            / "receipts/rewind.json"
        ).read_text(encoding="utf-8")
    )
    for field, value in rewind_receipt.items():
        assert f"{field}: {_rendered(value)}" in rewound.stdout
    final_status = _run(vault, "activation-status", candidate.capsule_id)
    assert "state: rewound" in final_status.stdout
    assert "rewindable: false" in final_status.stdout
