"""Lane G live activation and receipt-backed rewind journeys."""

from __future__ import annotations

import hashlib
import os
import pickle
import stat
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from core import portable_contract
from core.customization_migration.activation import (
    ActivatedFile,
    ActivationError,
    ActivationFile,
    ActivationPreview,
    ActivationReceipt,
    activate,
    preview_activation,
    preview_rewind,
    read_activation_status,
    rewind,
)
from core.customization_migration.capsule import CAPSULE_ROOT
from core.customization_migration.planning import CandidateFile, Disposition
from core.customization_migration.staging import preview_staging, stage_candidate
from core.customization_migration.state import MigrationState
from core.customization_migration.verification import (
    verify_staging,
    write_verification_report,
)
from core.tests.lifecycle_test_helpers import write_file
from core.tests.test_customization_staging import REPO_ROOT
from core.tests.test_customization_verification import _candidate_with_contract
from core.transaction.engine import PlanEntry, Transaction

SECOND_TEST_SEAM = "System/Templates/activation-new.md"


def test_activation_public_exports_are_available() -> None:
    import core.customization_migration as customization_migration

    assert customization_migration.ActivationPreview is not None
    assert customization_migration.ActivationReceipt is not None
    assert customization_migration.RewindReceipt is not None
    assert customization_migration.preview_activation is preview_activation
    assert customization_migration.activate is activate
    assert customization_migration.preview_rewind is preview_rewind
    assert customization_migration.rewind is rewind
    assert customization_migration.read_activation_status is read_activation_status


def test_activation_canonical_bytes_ignore_dict_order_with_non_ascii_path_and_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target_path = "System/Templates/équipe-☕.md"
    content = "# Café — déjà vu ☕\n".encode()
    content_sha256 = hashlib.sha256(content).hexdigest()
    activation_file = ActivationFile(
        target_path,
        None,
        content_sha256,
        0o644,
        True,
    )
    preview = ActivationPreview(
        0,
        "cap-0123456789abcdef",
        "prop-fedcba9876543210",
        "1" * 64,
        "2" * 64,
        (activation_file,),
        "The transaction engine keeps only the newest three committed snapshots.",
        (
            "Rewind is available only while this snapshot remains retained and every "
            "activated live file still matches the receipt."
        ),
        "3" * 64,
    )
    receipt = ActivationReceipt(
        0,
        preview.capsule_id,
        preview.proposal_id,
        preview.verification_report_sha256,
        preview.candidate_sha256,
        (ActivatedFile(target_path, content_sha256, len(content), 0o644),),
        "tx-canonical",
        "System/.dex/tx/tx-canonical/snapshot",
        1_760_000_000,
        True,
    )
    preview_bytes = preview.canonical_preview_bytes()
    receipt_bytes = receipt.canonical_bytes()
    original_preview_dict = ActivationPreview._unsigned_dict
    original_receipt_dict = ActivationReceipt.to_dict

    def reverse_dict_order(value):
        if isinstance(value, dict):
            return {
                key: reverse_dict_order(value[key])
                for key in reversed(tuple(value))
            }
        if isinstance(value, list):
            return [reverse_dict_order(item) for item in value]
        return value

    monkeypatch.setattr(
        ActivationPreview,
        "_unsigned_dict",
        lambda self: reverse_dict_order(original_preview_dict(self)),
    )
    monkeypatch.setattr(
        ActivationReceipt,
        "to_dict",
        lambda self: reverse_dict_order(original_receipt_dict(self)),
    )

    assert preview.canonical_preview_bytes() == preview_bytes
    assert receipt.canonical_bytes() == receipt_bytes
    assert target_path.encode() in preview_bytes
    assert target_path.encode() in receipt_bytes
    assert content_sha256.encode() in preview_bytes
    assert content_sha256.encode() in receipt_bytes


def _authorize_second_test_seam(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exercise a mixed plan without widening the committed v0 seam contract."""
    monkeypatch.setattr(
        portable_contract,
        "CUSTOMIZATION_MIGRATION_SEAM_PATHS",
        (*portable_contract.CUSTOMIZATION_MIGRATION_SEAM_PATHS, SECOND_TEST_SEAM),
    )


def _prepared_verified_candidate(
    tmp_path: Path,
    *,
    existing_target: bool,
    monkeypatch: pytest.MonkeyPatch | None = None,
    second_target: bool = False,
    blocked_disposition: bool = False,
):
    vault, candidate = _candidate_with_contract(tmp_path)
    if second_target:
        assert monkeypatch is not None
        _authorize_second_test_seam(monkeypatch)
        generated_id = candidate.files[0].customization_ids[0]
        candidate = replace(
            candidate,
            files=tuple(
                sorted(
                    (
                        *candidate.files,
                        CandidateFile.create(
                            SECOND_TEST_SEAM,
                            b"# Newly generated seam\n",
                            (generated_id,),
                        ),
                    ),
                    key=lambda item: item.target_path,
                )
            ),
        )
    if blocked_disposition:
        generated_id = candidate.files[0].customization_ids[0]
        blocked = next(
            item
            for item in candidate.dispositions
            if item.customization_id != generated_id
        )
        candidate = replace(
            candidate,
            dispositions=tuple(
                replace(item, disposition=Disposition.BLOCKED)
                if item.customization_id == blocked.customization_id
                else item
                for item in candidate.dispositions
            ),
        )
    if existing_target:
        write_file(vault, "CLAUDE-custom.md", b"# User's original bytes\r\n")
        os.chmod(vault / "CLAUDE-custom.md", 0o640)
    staging_preview = preview_staging(vault, candidate.capsule_id, candidate)
    stage_candidate(vault, staging_preview, staging_preview.preview_sha256)
    report = verify_staging(vault, candidate.capsule_id, candidate.proposal_id)
    write_verification_report(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
        report,
    )
    return vault, candidate, report


def _activation_receipt_path(vault: Path, capsule_id: str) -> Path:
    return (
        vault
        / CAPSULE_ROOT
        / capsule_id
        / "receipts"
        / "activation.json"
    )


def _proposal_journal(vault: Path, capsule_id: str, proposal_id: str) -> Path:
    return (
        vault
        / CAPSULE_ROOT
        / capsule_id
        / "candidates"
        / proposal_id
        / "staging"
        / "journal.jsonl"
    )


def _live_state(vault: Path, paths: tuple[str, ...]) -> dict[str, object]:
    result: dict[str, object] = {}
    for relative in paths:
        target = vault / relative
        result[relative] = (
            (target.read_bytes(), stat.S_IMODE(target.stat().st_mode))
            if target.exists()
            else None
        )
    return result


def test_activation_commits_existing_and_absent_authorized_targets_together(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault, candidate, report = _prepared_verified_candidate(
        tmp_path,
        existing_target=True,
        monkeypatch=monkeypatch,
        second_target=True,
    )

    preview = preview_activation(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    )
    receipt = activate(
        vault,
        preview,
        preview.approval_token,
        clock=lambda: 1_760_000_000,
    )

    assert tuple(item.target_path for item in preview.files) == (
        "CLAUDE-custom.md",
        SECOND_TEST_SEAM,
    )
    assert preview.files[0].previous_sha256 is not None
    assert preview.files[0].expected_absent is False
    assert preview.files[1].previous_sha256 is None
    assert preview.files[1].expected_absent is True
    assert {
        item.path: (item.sha256, item.mode)
        for item in receipt.files_written
    } == {
        item.target_path: (item.sha256, 0o644)
        for item in candidate.files
    }
    for item in candidate.files:
        assert (vault / item.target_path).read_bytes() == item.content
        assert stat.S_IMODE((vault / item.target_path).stat().st_mode) == 0o644
    assert receipt.verification_report_sha256 == preview.verification_report_sha256
    assert receipt.verification_report_sha256 == hashlib.sha256(
        report.canonical_bytes()
    ).hexdigest()
    assert receipt.rewind_available is True
    assert receipt.activated_epoch_seconds == 1_760_000_000
    assert _activation_receipt_path(
        vault,
        candidate.capsule_id,
    ).read_bytes() == receipt.canonical_bytes()
    assert read_activation_status(
        vault,
        candidate.capsule_id,
    ).state is MigrationState.ACTIVATED


def test_existing_target_edit_after_preview_wins_without_other_live_write(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault, candidate, _report = _prepared_verified_candidate(
        tmp_path,
        existing_target=True,
        monkeypatch=monkeypatch,
        second_target=True,
    )
    preview = preview_activation(vault, candidate.capsule_id, candidate.proposal_id)
    journal = _proposal_journal(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    )
    journal_before = journal.read_bytes()
    (vault / "CLAUDE-custom.md").write_bytes(b"# User edited after preview\n")

    with pytest.raises(ActivationError, match="existing file wins"):
        activate(vault, preview, preview.approval_token)

    assert (vault / "CLAUDE-custom.md").read_bytes() == (
        b"# User edited after preview\n"
    )
    assert not (vault / SECOND_TEST_SEAM).exists()
    assert journal.read_bytes() == journal_before
    assert not _activation_receipt_path(vault, candidate.capsule_id).exists()


def test_absent_target_created_after_preview_wins(
    tmp_path: Path,
) -> None:
    vault, candidate, _report = _prepared_verified_candidate(
        tmp_path,
        existing_target=False,
    )
    preview = preview_activation(vault, candidate.capsule_id, candidate.proposal_id)
    target = vault / "CLAUDE-custom.md"
    target.write_bytes(b"# User created after preview\n")

    with pytest.raises(ActivationError, match="existing file wins"):
        activate(vault, preview, preview.approval_token)

    assert target.read_bytes() == b"# User created after preview\n"
    assert not _activation_receipt_path(vault, candidate.capsule_id).exists()


def test_blocked_verification_refuses_before_any_live_write(
    tmp_path: Path,
) -> None:
    vault, candidate, report = _prepared_verified_candidate(
        tmp_path,
        existing_target=False,
        blocked_disposition=True,
    )
    assert report.verdict == "BLOCKED"

    with pytest.raises(ActivationError, match="verification verdict is not OK"):
        preview_activation(vault, candidate.capsule_id, candidate.proposal_id)

    assert not (vault / "CLAUDE-custom.md").exists()
    assert not _activation_receipt_path(vault, candidate.capsule_id).exists()


def test_approval_token_mismatch_is_load_bearing(
    tmp_path: Path,
) -> None:
    """Red-when-removed: without the token comparison this would write live."""
    vault, candidate, _report = _prepared_verified_candidate(
        tmp_path,
        existing_target=True,
    )
    before = (vault / "CLAUDE-custom.md").read_bytes()
    preview = preview_activation(vault, candidate.capsule_id, candidate.proposal_id)

    with pytest.raises(ActivationError, match="approval token"):
        activate(vault, preview, "0" * 64)

    assert (vault / "CLAUDE-custom.md").read_bytes() == before
    assert not _activation_receipt_path(vault, candidate.capsule_id).exists()


def test_verification_ok_gate_is_load_bearing(
    tmp_path: Path,
) -> None:
    """Red-when-removed: a persisted BLOCKED report must never reach live."""
    vault, candidate, report = _prepared_verified_candidate(
        tmp_path,
        existing_target=True,
        blocked_disposition=True,
    )
    before = (vault / "CLAUDE-custom.md").read_bytes()
    assert report.verdict == "BLOCKED"

    with pytest.raises(ActivationError, match="verification verdict is not OK"):
        preview_activation(vault, candidate.capsule_id, candidate.proposal_id)

    assert (vault / "CLAUDE-custom.md").read_bytes() == before


@pytest.mark.parametrize(
    "seam",
    (
        "after-begin",
        "after-snapshot",
        "mid-apply:0",
        "mid-apply:1",
        "mid-apply:2",
        "mid-apply:3",
        "after-apply",
        "after-verify",
        "before-finalize",
        "activation-after-previewed",
        "activation-mid-finalize",
        "after-commit-record",
    ),
)
def test_activation_crash_converges_to_pre_state_or_full_commit(
    seam: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault, candidate, _report = _prepared_verified_candidate(
        tmp_path,
        existing_target=True,
        monkeypatch=monkeypatch,
        second_target=True,
    )
    preview = preview_activation(vault, candidate.capsule_id, candidate.proposal_id)
    preview_pickle = tmp_path / "activation-preview.pickle"
    preview_pickle.write_bytes(pickle.dumps(preview))
    live_paths = tuple(item.target_path for item in candidate.files)
    before = _live_state(vault, live_paths)
    script = (
        "from pathlib import Path\n"
        "import pickle,sys\n"
        "from core import portable_contract\n"
        "from core.customization_migration.activation import activate\n"
        f"extra={SECOND_TEST_SEAM!r}\n"
        "portable_contract.CUSTOMIZATION_MIGRATION_SEAM_PATHS=("
        "*portable_contract.CUSTOMIZATION_MIGRATION_SEAM_PATHS,extra)\n"
        "preview=pickle.loads(Path(sys.argv[2]).read_bytes())\n"
        "activate(Path(sys.argv[1]),preview,preview.approval_token)\n"
    )
    environment = dict(os.environ)
    environment["DEX_TX_TEST_STOP_AFTER"] = seam
    environment["PYTHONPATH"] = str(REPO_ROOT)

    child = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(vault),
            str(preview_pickle),
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert child.returncode == 137, (seam, child.stderr[-500:])
    if seam == "activation-mid-finalize":
        assert read_activation_status(
            vault,
            candidate.capsule_id,
        ).state is not MigrationState.ACTIVATED
    Transaction.resume(vault)
    after = _live_state(vault, live_paths)
    if seam == "after-commit-record":
        assert after == {
            item.target_path: (item.content, 0o644)
            for item in candidate.files
        }
        assert read_activation_status(
            vault,
            candidate.capsule_id,
        ).state is MigrationState.ACTIVATED
    else:
        assert after == before
        assert not _activation_receipt_path(vault, candidate.capsule_id).exists()


def test_narrowed_activation_receipt_cannot_authorize_partial_rewind(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault, candidate, _report = _prepared_verified_candidate(
        tmp_path,
        existing_target=True,
        monkeypatch=monkeypatch,
        second_target=True,
    )
    activation_preview = preview_activation(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    )
    receipt = activate(
        vault,
        activation_preview,
        activation_preview.approval_token,
    )
    narrowed = replace(receipt, files_written=(receipt.files_written[0],))
    _activation_receipt_path(
        vault,
        candidate.capsule_id,
    ).write_bytes(narrowed.canonical_bytes())

    rewind_preview = preview_rewind(vault, narrowed)

    assert rewind_preview.status == "UNKNOWN"
    assert rewind_preview.acknowledgement_token is None
    assert read_activation_status(
        vault,
        candidate.capsule_id,
    ).state is MigrationState.RECOVERY_REQUIRED
    assert (vault / candidate.files[0].target_path).read_bytes() == (
        candidate.files[0].content
    )
    assert (vault / candidate.files[1].target_path).read_bytes() == (
        candidate.files[1].content
    )


def test_rewind_restores_exact_pre_activation_state_and_second_is_clean(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault, candidate, _report = _prepared_verified_candidate(
        tmp_path,
        existing_target=True,
        monkeypatch=monkeypatch,
        second_target=True,
    )
    live_paths = tuple(item.target_path for item in candidate.files)
    before = _live_state(vault, live_paths)
    activation_preview = preview_activation(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    )
    activation_receipt = activate(
        vault,
        activation_preview,
        activation_preview.approval_token,
    )

    rewind_preview = preview_rewind(vault, activation_receipt)
    assert rewind_preview.status == "OK"
    assert rewind_preview.acknowledgement_token is not None
    rewind_receipt = rewind(
        vault,
        activation_receipt,
        rewind_preview.acknowledgement_token,
        clock=lambda: 1_760_000_100,
    )

    assert rewind_receipt.status == "OK"
    assert rewind_receipt.rewound_epoch_seconds == 1_760_000_100
    assert _live_state(vault, live_paths) == before
    assert read_activation_status(
        vault,
        candidate.capsule_id,
    ).state is MigrationState.REWOUND

    state_after_first = _live_state(vault, live_paths)
    second = rewind(
        vault,
        activation_receipt,
        rewind_preview.acknowledgement_token,
    )
    assert second.status == "UNKNOWN"
    assert second.reason == "already-rewound"
    assert _live_state(vault, live_paths) == state_after_first


def test_live_drift_during_rewind_is_reported_unknown_and_user_bytes_win(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault, candidate, _report = _prepared_verified_candidate(
        tmp_path,
        existing_target=True,
    )
    activation_preview = preview_activation(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    )
    activation_receipt = activate(
        vault,
        activation_preview,
        activation_preview.approval_token,
    )
    rewind_preview = preview_rewind(vault, activation_receipt)
    original_snapshot = Transaction._snapshot_phase

    def drift_then_snapshot(transaction: Transaction) -> None:
        (vault / "CLAUDE-custom.md").write_bytes(b"# User changed during rewind\n")
        original_snapshot(transaction)

    monkeypatch.setattr(Transaction, "_snapshot_phase", drift_then_snapshot)

    receipt = rewind(
        vault,
        activation_receipt,
        rewind_preview.acknowledgement_token,
    )

    assert receipt.status == "UNKNOWN"
    assert receipt.reason == "live-drift"
    assert (vault / "CLAUDE-custom.md").read_bytes() == (
        b"# User changed during rewind\n"
    )


@pytest.mark.parametrize(
    "seam",
    (
        "after-begin",
        "after-snapshot",
        "mid-apply:0",
        "mid-apply:1",
        "mid-apply:2",
        "mid-apply:3",
        "after-apply",
        "after-verify",
        "before-finalize",
        "rewind-before-journal",
        "rewind-mid-finalize",
        "after-commit-record",
    ),
)
def test_rewind_crash_converges_to_active_state_or_full_rewind(
    seam: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    vault, candidate, _report = _prepared_verified_candidate(
        tmp_path,
        existing_target=True,
        monkeypatch=monkeypatch,
        second_target=True,
    )
    live_paths = tuple(item.target_path for item in candidate.files)
    before_activation = _live_state(vault, live_paths)
    activation_preview = preview_activation(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    )
    activation_receipt = activate(
        vault,
        activation_preview,
        activation_preview.approval_token,
    )
    active = _live_state(vault, live_paths)
    rewind_preview = preview_rewind(vault, activation_receipt)
    payload_path = tmp_path / "rewind-input.pickle"
    payload_path.write_bytes(
        pickle.dumps(
            (activation_receipt, rewind_preview.acknowledgement_token)
        )
    )
    script = (
        "from pathlib import Path\n"
        "import pickle,sys\n"
        "from core import portable_contract\n"
        "from core.customization_migration.activation import rewind\n"
        f"extra={SECOND_TEST_SEAM!r}\n"
        "portable_contract.CUSTOMIZATION_MIGRATION_SEAM_PATHS=("
        "*portable_contract.CUSTOMIZATION_MIGRATION_SEAM_PATHS,extra)\n"
        "receipt,token=pickle.loads(Path(sys.argv[2]).read_bytes())\n"
        "rewind(Path(sys.argv[1]),receipt,token)\n"
    )
    environment = dict(os.environ)
    environment["DEX_TX_TEST_STOP_AFTER"] = seam
    environment["PYTHONPATH"] = str(REPO_ROOT)

    child = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(vault),
            str(payload_path),
        ],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert child.returncode == 137, (seam, child.stderr[-500:])
    if seam == "rewind-mid-finalize":
        assert read_activation_status(
            vault,
            candidate.capsule_id,
        ).state is not MigrationState.REWOUND
    Transaction.resume(vault)
    if seam == "after-commit-record":
        assert _live_state(vault, live_paths) == before_activation
        assert read_activation_status(
            vault,
            candidate.capsule_id,
        ).state is MigrationState.REWOUND
    else:
        assert _live_state(vault, live_paths) == active
        assert read_activation_status(
            vault,
            candidate.capsule_id,
        ).state is MigrationState.ACTIVATED


def test_pruned_activation_snapshot_reports_honest_non_rewindable_status(
    tmp_path: Path,
) -> None:
    vault, candidate, _report = _prepared_verified_candidate(
        tmp_path,
        existing_target=True,
    )
    activation_preview = preview_activation(
        vault,
        candidate.capsule_id,
        candidate.proposal_id,
    )
    activation_receipt = activate(
        vault,
        activation_preview,
        activation_preview.approval_token,
    )
    activated = (vault / "CLAUDE-custom.md").read_bytes()
    for index in range(3):
        Transaction._begin_with_id(
            vault,
            [
                PlanEntry(
                    "System/.installed-files.manifest",
                    f"later {index}\n".encode(),
                )
            ],
            allow_empty=False,
            operation="update",
            tx_id=f"zzzzzzzzTzzzzzz-{index}",
        ).run()

    rewind_preview = preview_rewind(vault, activation_receipt)
    rewind_receipt = rewind(
        vault,
        activation_receipt,
        rewind_preview.acknowledgement_token,
    )

    assert rewind_preview.status == "UNKNOWN"
    assert rewind_preview.reason == "snapshot-pruned"
    assert rewind_preview.acknowledgement_token is None
    assert rewind_receipt.status == "UNKNOWN"
    assert rewind_receipt.reason == "snapshot-pruned"
    assert (vault / "CLAUDE-custom.md").read_bytes() == activated
