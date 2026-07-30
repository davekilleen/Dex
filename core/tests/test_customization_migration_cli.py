"""Lane D consent-side customization-migration CLI journeys."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from core.customization_migration import cli
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


def _run(
    vault: Path,
    *arguments: str,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(REPO_ROOT),
            "VAULT_PATH": str(vault),
        }
    )
    if extra_env is not None:
        env.update(extra_env)
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


def _run_in_process(
    vault: Path,
    capsys,
    monkeypatch,
    *arguments: str,
) -> tuple[int, str]:
    monkeypatch.setenv("VAULT_PATH", str(vault))
    return_code = cli.run(list(arguments))
    captured = capsys.readouterr()
    assert captured.err == ""
    return return_code, captured.out


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


def test_assess_partial_prints_observed_count_and_exclusion_guidance(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    vault = _manifest_only_vault(tmp_path)
    monkeypatch.setattr(
        cli.migration_service,
        "assess_to_dict",
        lambda _root: {
            "verdict": "UNKNOWN",
            "records": [{"customization_id": "custom-1"}],
            "exclusions": [
                {
                    "path": "custom/large.md",
                    "reason": "read-bound-exceeded",
                    "guidance": "Split the file, then reassess.",
                }
            ],
        },
    )

    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "assess",
    )

    assert return_code == 0
    assert "Observed 1 customizations" in output
    assert (
        "Excluded custom/large.md [read-bound-exceeded]: "
        "Split the file, then reassess."
    ) in output


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
            "type": "stdio",
            "command": "{{VAULT_PATH}}/.venv/bin/python",
            "args": [
                "{{VAULT_PATH}}/core/mcp/customization_migration_server.py"
            ],
            "env": {"VAULT_PATH": "{{VAULT_PATH}}"},
        }
    }


def test_cli_run_covers_rebuild_confirmation_receipts_and_status(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    candidate_path = _candidate_file(tmp_path, candidate)

    before_stage = snapshot_vault(vault)
    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "stage",
        str(candidate_path),
    )
    staging_token = _token(output)
    assert return_code == 2
    assert "Live path after activation:" in output
    assert "Disposition:" in output
    assert "Nothing was staged." in output
    assert snapshot_vault(vault) == before_stage

    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "stage",
        str(candidate_path),
        "--confirm-token",
        "0" * 64,
    )
    assert return_code == 2
    assert _token(output) == staging_token
    assert snapshot_vault(vault) == before_stage

    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "stage",
        str(candidate_path),
        "--confirm-token",
        staging_token,
    )
    assert return_code == 0
    for field in (
        "capsule_id",
        "proposal_id",
        "staged_file_count",
        "staged_byte_count",
        "staging_digest",
        "transaction_id",
    ):
        assert f"{field}:" in output

    before_verification = snapshot_vault(vault)
    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "verify",
        candidate.capsule_id,
        candidate.proposal_id,
    )
    verification_token = _token(output)
    assert return_code == 2
    for field in (
        "confirm_token",
        "capsule_id",
        "proposal_id",
        "staging_receipt_sha256",
        "report_sha256",
        "verdict",
        "static_file_count",
        "behavioural_contract_count",
    ):
        assert f"{field}:" in output
    assert "Nothing was sealed." in output
    assert snapshot_vault(vault) == before_verification

    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "verify",
        candidate.capsule_id,
        candidate.proposal_id,
        "--confirm-token",
        "0" * 64,
    )
    assert return_code == 2
    assert _token(output) == verification_token
    assert snapshot_vault(vault) == before_verification

    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "verify",
        candidate.capsule_id,
        candidate.proposal_id,
        "--confirm-token",
        verification_token,
    )
    assert return_code == 0
    for field in (
        "capsule_id",
        "proposal_id",
        "verdict",
        "staging_id",
        "report_sha256",
        "transaction_id",
    ):
        assert f"{field}:" in output
    assert "static_results:" not in output
    assert "reported_verifications:" not in output
    assert "notes:" not in output

    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "preview-activation",
        candidate.capsule_id,
        candidate.proposal_id,
    )
    activation_token = _token(output)
    assert return_code == 0
    assert "Live path:" in output
    assert "Disposition:" in output
    assert "Snapshot retention:" in output
    assert "Rewind:" in output
    assert "Approval token:" in output

    before_activation = snapshot_vault(vault)
    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "activate",
        candidate.capsule_id,
        candidate.proposal_id,
    )
    assert return_code == 2
    assert _token(output) == activation_token
    assert "Nothing was activated." in output
    assert snapshot_vault(vault) == before_activation

    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "activate",
        candidate.capsule_id,
        candidate.proposal_id,
        "--confirm-token",
        "0" * 64,
    )
    assert return_code == 2
    assert _token(output) == activation_token
    assert snapshot_vault(vault) == before_activation

    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "activate",
        candidate.capsule_id,
        candidate.proposal_id,
        "--confirm-token",
        activation_token,
    )
    assert return_code == 0
    for field in (
        "capsule_id",
        "proposal_id",
        "verification_report_sha256",
        "candidate_sha256",
        "file_count",
        "transaction_id",
        "activated_epoch_seconds",
        "rewind_available",
    ):
        assert f"{field}:" in output
    assert "files_written:" not in output
    assert "snapshot_ref:" not in output

    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "activation-status",
        candidate.capsule_id,
    )
    assert return_code == 0
    for expected in (
        "state: activated",
        "activation_receipt_present: true",
        "rewindable: true",
    ):
        assert expected in output

    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "preview-rewind",
        candidate.capsule_id,
    )
    rewind_token = _token(output)
    assert return_code == 0
    assert "Status: OK" in output
    assert "Restore path:" in output
    assert "Acknowledgement token:" in output

    before_rewind = snapshot_vault(vault)
    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "rewind",
        candidate.capsule_id,
    )
    assert return_code == 2
    assert _token(output) == rewind_token
    assert "Nothing was rewound." in output
    assert snapshot_vault(vault) == before_rewind

    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "rewind",
        candidate.capsule_id,
        "--acknowledge-token",
        "0" * 64,
    )
    assert return_code == 2
    assert _token(output) == rewind_token
    assert snapshot_vault(vault) == before_rewind

    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "rewind",
        candidate.capsule_id,
        "--acknowledge-token",
        rewind_token,
    )
    assert return_code == 0
    for field in (
        "capsule_id",
        "proposal_id",
        "activation_transaction_id",
        "rewind_transaction_id",
        "status",
        "reason",
        "file_count",
        "rewound_epoch_seconds",
    ):
        assert f"{field}:" in output
    assert "files_restored:" not in output

    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "activation-status",
        candidate.capsule_id,
    )
    assert return_code == 0
    assert "state: rewound" in output
    assert "rewindable: false" in output

    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "rewind",
        candidate.capsule_id,
    )
    assert return_code == 2
    assert "Nothing was rewound because rewind is not available." in output


def test_cli_run_covers_recovery_refusals_and_result_rendering(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    candidate_path = _candidate_file(tmp_path, candidate)
    stage_preview = _run(vault, "stage", str(candidate_path))
    staged = _run(
        vault,
        "stage",
        str(candidate_path),
        "--confirm-token",
        _token(stage_preview.stdout),
    )
    assert staged.returncode == 0
    verification_preview = _run(
        vault,
        "verify",
        candidate.capsule_id,
        candidate.proposal_id,
    )
    verified = _run(
        vault,
        "verify",
        candidate.capsule_id,
        candidate.proposal_id,
        "--confirm-token",
        _token(verification_preview.stdout),
    )
    assert verified.returncode == 0
    activation_preview = _run(
        vault,
        "preview-activation",
        candidate.capsule_id,
        candidate.proposal_id,
    )
    interrupted = _run(
        vault,
        "activate",
        candidate.capsule_id,
        candidate.proposal_id,
        "--confirm-token",
        _token(activation_preview.stdout),
        extra_env={"DEX_TX_TEST_STOP_AFTER": "mid-apply:0"},
    )
    assert interrupted.returncode == 137
    after_interrupt = snapshot_vault(vault)

    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "recover",
    )
    recovery_token = _token(output)
    assert return_code == 2
    assert "Recovery phase: activation" in output
    assert f"Recovery capsule: {candidate.capsule_id}" in output
    assert f"Recovery proposal: {candidate.proposal_id}" in output
    assert "Recovery action:" in output
    assert "Nothing was recovered." in output
    assert snapshot_vault(vault) == after_interrupt

    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "recover",
        "--confirm-token",
        "0" * 64,
    )
    assert return_code == 2
    assert _token(output) == recovery_token
    assert snapshot_vault(vault) == after_interrupt

    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "recover",
        "--confirm-token",
        recovery_token,
    )
    assert return_code == 0
    assert "Recovered phase: activation" in output
    assert "Recovery status: restored" in output
    assert "Restored file count:" in output

    return_code, output = _run_in_process(
        vault,
        capsys,
        monkeypatch,
        "recover",
    )
    assert return_code == 0
    assert output.strip() == (
        "No interrupted customization transaction needs recovery."
    )


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

    before_verification = snapshot_vault(vault)
    missing_verification = _run(
        vault,
        "verify",
        candidate.capsule_id,
        candidate.proposal_id,
    )
    assert missing_verification.returncode != 0
    verification_token = _token(missing_verification.stdout)
    assert snapshot_vault(vault) == before_verification

    stale_verification = _run(
        vault,
        "verify",
        candidate.capsule_id,
        candidate.proposal_id,
        "--confirm-token",
        "0" * 64,
    )
    assert stale_verification.returncode != 0
    assert _token(stale_verification.stdout) == verification_token
    assert snapshot_vault(vault) == before_verification

    verified = _run(
        vault,
        "verify",
        candidate.capsule_id,
        candidate.proposal_id,
        "--confirm-token",
        verification_token,
    )
    assert verified.returncode == 0, verified.stdout
    for field in (
        "capsule_id",
        "staging_id",
        "report_sha256",
        "transaction_id",
    ):
        assert f"{field}:" in verified.stdout
    assert "static_results:" not in verified.stdout
    assert "reported_verifications:" not in verified.stdout
    assert "notes:" not in verified.stdout

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
    for field in (
        "capsule_id",
        "proposal_id",
        "verification_report_sha256",
            "candidate_sha256",
            "file_count",
            "transaction_id",
            "activated_epoch_seconds",
            "rewind_available",
    ):
        assert f"{field}:" in activated.stdout
    assert "files_written:" not in activated.stdout
    assert "snapshot_ref:" not in activated.stdout

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
    for field in (
        "capsule_id",
        "proposal_id",
        "activation_transaction_id",
        "rewind_transaction_id",
        "status",
            "reason",
            "file_count",
            "rewound_epoch_seconds",
        ):
        assert f"{field}:" in rewound.stdout
    assert "files_restored:" not in rewound.stdout
    final_status = _run(vault, "activation-status", candidate.capsule_id)
    assert "state: rewound" in final_status.stdout
    assert "rewindable: false" in final_status.stdout


def test_verification_output_does_not_print_candidate_controlled_free_text(
    tmp_path: Path,
) -> None:
    sentinel = "DO-NOT-PRINT-CANDIDATE-CONTROLLED-TEXT"
    vault, candidate = _candidate_with_contract(tmp_path, statement=sentinel)
    candidate_path = _candidate_file(tmp_path, candidate)
    stage_preview = _run(vault, "stage", str(candidate_path))
    stage_token = _token(stage_preview.stdout)
    staged = _run(
        vault,
        "stage",
        str(candidate_path),
        "--confirm-token",
        stage_token,
    )
    assert staged.returncode == 0
    verify_preview = _run(
        vault,
        "verify",
        candidate.capsule_id,
        candidate.proposal_id,
    )
    verification_token = _token(verify_preview.stdout)

    verified = _run(
        vault,
        "verify",
        candidate.capsule_id,
        candidate.proposal_id,
        "--confirm-token",
        verification_token,
    )

    assert verified.returncode == 0
    assert sentinel not in verify_preview.stdout
    assert sentinel not in verified.stdout


def test_recover_cli_restores_one_interrupted_activation_with_bound_token(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    candidate_path = _candidate_file(tmp_path, candidate)
    stage_preview = _run(vault, "stage", str(candidate_path))
    staged = _run(
        vault,
        "stage",
        str(candidate_path),
        "--confirm-token",
        _token(stage_preview.stdout),
    )
    assert staged.returncode == 0
    verification_preview = _run(
        vault,
        "verify",
        candidate.capsule_id,
        candidate.proposal_id,
    )
    verified = _run(
        vault,
        "verify",
        candidate.capsule_id,
        candidate.proposal_id,
        "--confirm-token",
        _token(verification_preview.stdout),
    )
    assert verified.returncode == 0
    activation_preview = _run(
        vault,
        "preview-activation",
        candidate.capsule_id,
        candidate.proposal_id,
    )

    interrupted = _run(
        vault,
        "activate",
        candidate.capsule_id,
        candidate.proposal_id,
        "--confirm-token",
        _token(activation_preview.stdout),
        extra_env={"DEX_TX_TEST_STOP_AFTER": "mid-apply:0"},
    )

    assert interrupted.returncode == 137
    after_interrupt = snapshot_vault(vault)
    status = _run(vault, "status")
    assert "Recovery phase: activation" in status.stdout
    assert (
        "Recovery action: python3 -m core.customization_migration.cli "
        "recover --confirm-token "
    ) in status.stdout

    missing = _run(vault, "recover")
    assert missing.returncode != 0
    recovery_token = _token(missing.stdout)
    assert snapshot_vault(vault) == after_interrupt

    stale = _run(vault, "recover", "--confirm-token", "0" * 64)
    assert stale.returncode != 0
    assert _token(stale.stdout) == recovery_token
    assert snapshot_vault(vault) == after_interrupt

    recovered = _run(
        vault,
        "recover",
        "--confirm-token",
        recovery_token,
    )

    assert recovered.returncode == 0, recovered.stdout
    assert "Recovered phase: activation" in recovered.stdout
    assert not (vault / candidate.files[0].target_path).exists()
    assert not (
        vault
        / CAPSULE_ROOT
        / candidate.capsule_id
        / "receipts/activation.json"
    ).exists()
    assert "Recovery phase:" not in _run(vault, "status").stdout
