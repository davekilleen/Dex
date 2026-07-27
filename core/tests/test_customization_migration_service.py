"""Service façade journeys for the customization rebuild doorway."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from core.customization_migration import sensitivity as sensitivity_module
from core.customization_migration import service as migration_service
from core.customization_migration import staging as staging_module
from core.customization_migration.capsule import create_capsule, preview_capsule
from core.customization_migration.planning import Disposition
from core.tests.lifecycle_test_helpers import write_file
from core.tests.test_customization_assessment import _linked_customized_vault
from core.tests.test_customization_verification import _candidate_with_contract
from core.tests.vault_observed_writes import snapshot_vault


def test_service_runs_real_stage_verify_activate_status_and_rewind(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    original = b"# Original custom instructions\r\n"
    write_file(vault, "CLAUDE-custom.md", original)

    before_preview = snapshot_vault(vault)
    staging_preview = migration_service.preview_staging_to_dict(vault, candidate)
    assert snapshot_vault(vault) == before_preview
    assert staging_preview["preview_sha256"]
    assert staging_preview["candidate"] == candidate.to_dict()

    with pytest.raises(migration_service.MigrationServiceError) as refused_stage:
        migration_service.stage_confirmed_candidate(vault, candidate, "0" * 64)
    assert refused_stage.value.code == "staging-refused"
    assert snapshot_vault(vault) == before_preview

    staging_receipt = migration_service.stage_confirmed_candidate(
        vault,
        candidate,
        staging_preview["preview_sha256"],
    )
    assert staging_receipt.to_dict()["staging_digest"] == (
        staging_preview["preview_sha256"]
    )

    verification_preview = migration_service.preview_verification_to_dict(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    )
    before_verification = snapshot_vault(vault)
    with pytest.raises(migration_service.MigrationServiceError) as refused_verification:
        migration_service.verify_staging_to_dict(
            vault,
            candidate.capsule_id,
            candidate.proposal_id,
            "0" * 64,
        )
    assert refused_verification.value.code == "verification-refused"
    assert snapshot_vault(vault) == before_verification

    verification = migration_service.verify_staging_to_dict(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
        verification_preview["confirm_token"],
    )
    assert verification["report"]["verdict"] == "OK"
    assert verification["report"]["reported_verifications"][0]["status"] == (
        "verified"
    )
    assert verification["receipt"]["report_sha256"]

    before_activation_preview = snapshot_vault(vault)
    activation_preview = migration_service.preview_activation_to_dict(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    )
    assert snapshot_vault(vault) == before_activation_preview
    assert activation_preview["approval_token"]
    assert activation_preview["dispositions"] == [
        item.to_dict() for item in candidate.dispositions
    ]

    with pytest.raises(migration_service.MigrationServiceError) as refused_activation:
        migration_service.activate_confirmed(
            vault,
            candidate.capsule_id,
            candidate.proposal_id,
            "0" * 64,
        )
    assert refused_activation.value.code == "activation-refused"
    assert snapshot_vault(vault) == before_activation_preview

    activation_receipt = migration_service.activate_confirmed(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
        activation_preview["approval_token"],
    )
    assert (vault / "CLAUDE-custom.md").read_bytes() == candidate.files[0].content
    assert activation_receipt.rewind_available is True

    status = migration_service.activation_status_to_dict(
        vault,
        candidate.capsule_id,
    )
    assert status == {
        "capsule_id": candidate.capsule_id,
        "proposal_id": candidate.proposal_id,
        "state": "activated",
        "reason": "activated",
        "activation_receipt_present": True,
        "rewindable": True,
    }

    before_rewind_preview = snapshot_vault(vault)
    rewind_preview = migration_service.preview_rewind_to_dict(
        vault,
        candidate.capsule_id,
    )
    assert snapshot_vault(vault) == before_rewind_preview
    assert rewind_preview["status"] == "OK"
    assert rewind_preview["acknowledgement_token"]

    with pytest.raises(migration_service.MigrationServiceError) as refused_rewind:
        migration_service.rewind_acknowledged(
            vault,
            candidate.capsule_id,
            "0" * 64,
        )
    assert refused_rewind.value.code == "rewind-refused"
    assert snapshot_vault(vault) == before_rewind_preview

    rewind_receipt = migration_service.rewind_acknowledged(
        vault,
        candidate.capsule_id,
        rewind_preview["acknowledgement_token"],
    )
    assert rewind_receipt.status == "OK"
    assert (vault / "CLAUDE-custom.md").read_bytes() == original
    assert migration_service.activation_status_to_dict(
        vault,
        candidate.capsule_id,
    )["state"] == "rewound"


def test_candidate_file_is_bounded_canonical_and_closed(tmp_path: Path) -> None:
    _vault, candidate = _candidate_with_contract(tmp_path)
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_bytes(
        migration_service.canonical_json_bytes(candidate.to_dict())
    )

    loaded = migration_service.load_regeneration_candidate(candidate_path)

    assert loaded == candidate

    noncanonical_path = tmp_path / "noncanonical.json"
    noncanonical_path.write_text(
        json.dumps(candidate.to_dict(), indent=2),
        encoding="utf-8",
    )
    with pytest.raises(migration_service.MigrationServiceError) as noncanonical:
        migration_service.load_regeneration_candidate(noncanonical_path)
    assert noncanonical.value.code == "invalid-candidate"

    extra = candidate.to_dict()
    extra["unexpected"] = True
    extra_path = tmp_path / "extra.json"
    extra_path.write_bytes(migration_service.canonical_json_bytes(extra))
    with pytest.raises(migration_service.MigrationServiceError) as closed:
        migration_service.load_regeneration_candidate(extra_path)
    assert closed.value.code == "invalid-candidate"


def test_activation_preview_refuses_dispositions_not_bound_to_its_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    staging_preview = migration_service.preview_staging_to_dict(vault, candidate)
    migration_service.stage_confirmed_candidate(
        vault,
        candidate,
        staging_preview["preview_sha256"],
    )
    verification_preview = migration_service.preview_verification_to_dict(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    )
    migration_service.verify_staging_to_dict(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
        verification_preview["confirm_token"],
    )
    altered_disposition = replace(
        candidate.dispositions[0],
        disposition=Disposition.KEEP_DISABLED,
        evidence_edge_ids=(),
        behaviour_contract_ids=(),
    )
    altered_candidate = replace(candidate, dispositions=(altered_disposition,))
    original_load = staging_module.load_staged_candidate

    def load_different_candidate(*args, **kwargs):
        _candidate, receipt, staging = original_load(*args, **kwargs)
        return altered_candidate, receipt, staging

    monkeypatch.setattr(
        staging_module,
        "load_staged_candidate",
        load_different_candidate,
    )

    with pytest.raises(migration_service.MigrationServiceError) as refused:
        migration_service.preview_activation_to_dict(
            vault,
            candidate.capsule_id,
            candidate.proposal_id,
        )

    assert refused.value.code == "activation-refused"


def test_read_capsule_blob_is_digest_bound_utf8_and_sensitivity_gated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault = _linked_customized_vault(tmp_path)
    preview = preview_capsule(vault)
    create_capsule(vault, preview, preview.preview_sha256)
    source = preview.blob_sources[0]
    expected = (vault / source.source_path).read_text(encoding="utf-8")

    result = migration_service.read_capsule_blob_text(
        vault,
        preview.capsule_id,
        source.sha256,
    )

    assert result == {
        "capsule_id": preview.capsule_id,
        "sha256": source.sha256,
        "byte_size": source.byte_size,
        "text": expected,
    }

    with pytest.raises(migration_service.MigrationServiceError) as unknown:
        migration_service.read_capsule_blob_text(
            vault,
            preview.capsule_id,
            "0" * 64,
        )
    assert unknown.value.code == "unreadable-blob"

    monkeypatch.setattr(
        sensitivity_module,
        "capsule_readability",
        lambda _path: "restricted",
    )
    with pytest.raises(migration_service.MigrationServiceError) as restricted:
        migration_service.read_capsule_blob_text(
            vault,
            preview.capsule_id,
            source.sha256,
        )
    assert restricted.value.code == "unreadable-blob"


def test_read_capsule_blob_refuses_binary_bytes(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)
    binary_source = vault / ".scripts/custom-binary.bin"
    binary_source.write_bytes(b"\xff\x00not-text")
    preview = preview_capsule(vault)
    source = next(
        item
        for item in preview.blob_sources
        if item.source_path == ".scripts/custom-binary.bin"
    )
    create_capsule(vault, preview, preview.preview_sha256)

    with pytest.raises(migration_service.MigrationServiceError) as refused:
        migration_service.read_capsule_blob_text(
            vault,
            preview.capsule_id,
            source.sha256,
        )

    assert refused.value.code == "binary-blob"


def test_rewound_journal_without_rewind_receipt_requires_recovery(
    tmp_path: Path,
) -> None:
    vault, candidate = _candidate_with_contract(tmp_path)
    staging_preview = migration_service.preview_staging_to_dict(vault, candidate)
    migration_service.stage_confirmed_candidate(
        vault,
        candidate,
        staging_preview["preview_sha256"],
    )
    verification_preview = migration_service.preview_verification_to_dict(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    )
    migration_service.verify_staging_to_dict(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
        verification_preview["confirm_token"],
    )
    activation_preview = migration_service.preview_activation_to_dict(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    )
    migration_service.activate_confirmed(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
        activation_preview["approval_token"],
    )
    rewind_preview = migration_service.preview_rewind_to_dict(
        vault,
        candidate.capsule_id,
    )
    migration_service.rewind_acknowledged(
        vault,
        candidate.capsule_id,
        rewind_preview["acknowledgement_token"],
    )
    (
        vault
        / "System/.dex/customization-migrations"
        / candidate.capsule_id
        / "receipts/rewind.json"
    ).unlink()

    activation_status = migration_service.activation_status_to_dict(
        vault,
        candidate.capsule_id,
    )
    migration_status = migration_service.migration_status_to_dict(vault)

    assert activation_status["state"] == "recovery-required"
    assert activation_status["reason"] == "rewind-receipt-missing"
    assert activation_status["rewindable"] is False
    assert migration_status["capsules"][0]["pending_rebuild"] is True
