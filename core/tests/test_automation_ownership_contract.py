"""Frozen lifecycle contract for handing one launchd automation to Dex Solo."""

from __future__ import annotations

import hashlib
import json
import plistlib
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from core.lifecycle import service
from core.transaction.engine import PlanRejected, Transaction
from core.transaction.lock import LockBusyError, acquire_owned_lock
from core.utils import automation_ownership

LABEL = "com.dex.smoke-nightly"
PLIST_RELATIVE = f"Library/LaunchAgents/{LABEL}.plist"
SIDECAR_SCHEMA = Path(__file__).resolve().parents[1] / "lifecycle/schemas/automation-ownership-v1.schema.json"
API_SCHEMA = Path(__file__).resolve().parents[1] / "lifecycle/contracts/api.schema.json"


def _canonical(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, object]]:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    home = tmp_path / "home"
    plist = home / PLIST_RELATIVE
    plist.parent.mkdir(parents=True)
    with plist.open("wb") as handle:
        plistlib.dump(
            {
                "Label": LABEL,
                "ProgramArguments": ["/bin/bash", str(vault / ".scripts/smoke-nightly.sh")],
            },
            handle,
        )
    monkeypatch.setattr(automation_ownership, "_home_root", lambda: home)
    claim = {
        "automation_id": LABEL,
        "owner_id": "dex-solo",
        "plist_relative_path": PLIST_RELATIVE,
        "plist_sha256": hashlib.sha256(plist.read_bytes()).hexdigest(),
        "launchd_state": "unloaded",
    }
    return vault, claim


def _claim(vault: Path, request: dict[str, object]) -> dict[str, object]:
    previewed = service.build_and_preview_automation_claim(vault, request)
    return service.execute_approved_automation_claim(
        vault,
        previewed["preview"],
        previewed["approval_token"],
    )


def test_claim_preview_binds_exact_plist_and_sidecar_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault, request = _fixture(tmp_path, monkeypatch)

    response = service.build_and_preview_automation_claim(vault, request)

    assert response["api_version"] == "1.5.0"
    assert response["needed"] is True
    assert response["preview"] == {
        "automation_ownership_version": 1,
        "operation": "claim",
        "claim": {
            "automation_id": LABEL,
            "owner_id": "dex-solo",
            "plist_relative_path": PLIST_RELATIVE,
            "plist_sha256": request["plist_sha256"],
        },
        "launchd_state": "unloaded",
        "current_sidecar_sha256": None,
        "next_sidecar_sha256": hashlib.sha256(
            _canonical(
                {
                    "schema_version": 1,
                    "claims": [
                        {
                            "automation_id": LABEL,
                            "owner_id": "dex-solo",
                            "plist_relative_path": PLIST_RELATIVE,
                            "plist_sha256": request["plist_sha256"],
                        }
                    ],
                }
            )
        ).hexdigest(),
    }
    expected_token = hashlib.sha256(_canonical(response["preview"])).hexdigest()
    assert response["approval_token"] == expected_token
    assert not (vault / automation_ownership.SIDECAR_RELATIVE).exists()


def test_transaction_rereads_the_sidecar_with_the_closed_size_bound() -> None:
    assert service._internal_transaction_read_limits("automation-ownership") == {
        automation_ownership.SIDECAR_RELATIVE: automation_ownership.SIDECAR_MAX_BYTES,
    }


def test_public_preview_schema_keeps_claim_and_release_shapes_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    vault, request = _fixture(tmp_path, monkeypatch)
    preview = service.build_and_preview_automation_claim(vault, request)["preview"]
    document = json.loads(API_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(document)
    preview_schema = {
        "$schema": document["$schema"],
        "$ref": "#/$defs/automationPreview",
        "$defs": document["$defs"],
    }
    validator = Draft202012Validator(preview_schema)

    assert list(validator.iter_errors(preview)) == []
    assert list(validator.iter_errors({**preview, "scheduler_state": "stopped"}))
    assert list(validator.iter_errors({key: value for key, value in preview.items() if key != "launchd_state"}))

    noncanonical = {
        **preview,
        "claim": {**preview["claim"], "plist_relative_path": "Library/LaunchAgents/..plist"},
    }
    assert list(validator.iter_errors(noncanonical))


def test_claim_executes_only_through_transaction_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, request = _fixture(tmp_path, monkeypatch)

    previewed = service.build_and_preview_automation_claim(vault, request)
    executed = service.execute_approved_automation_claim(
        vault,
        previewed["preview"],
        previewed["approval_token"],
    )

    sidecar = vault / automation_ownership.SIDECAR_RELATIVE
    assert json.loads(sidecar.read_text()) == {
        "schema_version": 1,
        "claims": [
            {
                "automation_id": LABEL,
                "owner_id": "dex-solo",
                "plist_relative_path": PLIST_RELATIVE,
                "plist_sha256": request["plist_sha256"],
            }
        ],
    }
    schema = json.loads(SIDECAR_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    sidecar_validator = Draft202012Validator(schema)
    sidecar_state = json.loads(sidecar.read_text())
    assert list(sidecar_validator.iter_errors(sidecar_state)) == []
    noncanonical_sidecar = json.loads(sidecar.read_text())
    noncanonical_sidecar["claims"][0]["plist_relative_path"] = "Library/LaunchAgents/..plist"
    assert list(sidecar_validator.iter_errors(noncanonical_sidecar))
    assert executed["receipt"]["status"] == "claimed"
    assert executed["receipt"]["transaction_id"]
    assert not (vault / "System/.dex/ledger").exists()

    repeated_execution = service.execute_approved_automation_claim(
        vault,
        previewed["preview"],
        previewed["approval_token"],
    )
    assert repeated_execution["receipt"]["status"] == "already-claimed"
    assert repeated_execution["receipt"]["transaction_id"] is None

    repeated = service.build_and_preview_automation_claim(vault, request)
    assert repeated == {
        "api_version": "1.5.0",
        "needed": False,
        "preview": None,
        "approval_token": None,
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("automation_id", "../smoke", "automation_id"),
        ("owner_id", "another-app", "Dex Solo"),
        ("plist_relative_path", "/Library/LaunchAgents/x.plist", "relative"),
        ("plist_relative_path", "Library/LaunchAgents/..plist", "canonical"),
        ("plist_sha256", "A" * 64, "sha256"),
        ("launchd_state", "loaded", "unloaded"),
    ],
)
def test_claim_validation_is_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    message: str,
) -> None:
    vault, request = _fixture(tmp_path, monkeypatch)
    request[field] = value

    with pytest.raises(PlanRejected, match=message):
        service.build_and_preview_automation_claim(vault, request)

    assert not (vault / automation_ownership.SIDECAR_RELATIVE).exists()


def test_claim_rejects_unknown_fields_and_conflicting_reuse(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault, request = _fixture(tmp_path, monkeypatch)
    with pytest.raises(PlanRejected, match="unsupported fields"):
        service.build_and_preview_automation_claim(vault, {**request, "extra": True})

    _claim(vault, request)
    conflict = dict(request)
    conflict["plist_relative_path"] = "Library/LaunchAgents/other.plist"
    with pytest.raises(PlanRejected, match="conflicting reuse"):
        service.build_and_preview_automation_claim(vault, conflict)


def test_claim_recomputes_token_and_rejects_plist_or_sidecar_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, request = _fixture(tmp_path, monkeypatch)
    previewed = service.build_and_preview_automation_claim(vault, request)
    plist = automation_ownership._home_root() / PLIST_RELATIVE
    plist.write_bytes(plist.read_bytes() + b"\n")

    with pytest.raises(PlanRejected, match="plist evidence changed"):
        service.execute_approved_automation_claim(vault, previewed["preview"], previewed["approval_token"])

    assert not (vault / automation_ownership.SIDECAR_RELATIVE).exists()


def test_claim_rejects_sidecar_state_that_appears_after_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, request = _fixture(tmp_path, monkeypatch)
    previewed = service.build_and_preview_automation_claim(vault, request)
    sidecar = vault / automation_ownership.SIDECAR_RELATIVE
    sidecar.parent.mkdir(parents=True)
    sidecar.write_bytes(_canonical({"schema_version": 1, "claims": []}))

    with pytest.raises(PlanRejected, match="state changed since preview"):
        service.execute_approved_automation_claim(
            vault,
            previewed["preview"],
            previewed["approval_token"],
        )

    assert json.loads(sidecar.read_text()) == {"schema_version": 1, "claims": []}


def test_claim_idempotent_replay_rejects_unrelated_sidecar_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, request = _fixture(tmp_path, monkeypatch)
    previewed = service.build_and_preview_automation_claim(vault, request)
    service.execute_approved_automation_claim(vault, previewed["preview"], previewed["approval_token"])
    sidecar = vault / automation_ownership.SIDECAR_RELATIVE
    state = json.loads(sidecar.read_text())
    state["claims"].append(
        {
            "automation_id": "com.dex.zzz",
            "owner_id": "dex-solo",
            "plist_relative_path": "Library/LaunchAgents/com.dex.zzz.plist",
            "plist_sha256": "0" * 64,
        }
    )
    sidecar.write_bytes(_canonical(state))

    with pytest.raises(PlanRejected, match="state changed since preview"):
        service.execute_approved_automation_claim(
            vault,
            previewed["preview"],
            previewed["approval_token"],
        )


def test_claim_obeys_transaction_lock_and_rolls_back_commit_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, request = _fixture(tmp_path, monkeypatch)
    previewed = service.build_and_preview_automation_claim(vault, request)
    release = acquire_owned_lock(vault, "test-owner")
    try:
        with pytest.raises(LockBusyError):
            service.execute_approved_automation_claim(vault, previewed["preview"], previewed["approval_token"])
    finally:
        release()

    def fail_commit(_transaction: Transaction) -> dict[str, object]:
        raise RuntimeError("deliberate commit failure")

    monkeypatch.setattr(Transaction, "_commit_phase", fail_commit)
    with pytest.raises(RuntimeError, match="deliberate commit failure"):
        service.execute_approved_automation_claim(vault, previewed["preview"], previewed["approval_token"])
    assert not (vault / automation_ownership.SIDECAR_RELATIVE).exists()


def test_release_requires_stopped_scheduler_and_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault, request = _fixture(tmp_path, monkeypatch)
    _claim(vault, request)
    release_request = {
        "automation_id": LABEL,
        "owner_id": "dex-solo",
        "scheduler_state": "stopped",
    }

    previewed = service.build_and_preview_automation_release(vault, release_request)
    assert previewed["preview"]["scheduler_state"] == "stopped"
    released = service.execute_approved_automation_release(vault, previewed["preview"], previewed["approval_token"])
    assert released["receipt"]["status"] == "released"
    assert json.loads((vault / automation_ownership.SIDECAR_RELATIVE).read_text()) == {
        "schema_version": 1,
        "claims": [],
    }
    repeated_release = service.execute_approved_automation_release(
        vault,
        previewed["preview"],
        previewed["approval_token"],
    )
    assert repeated_release["receipt"]["status"] == "already-released"
    assert repeated_release["receipt"]["transaction_id"] is None
    assert service.build_and_preview_automation_release(vault, release_request) == {
        "api_version": "1.5.0",
        "needed": False,
        "preview": None,
        "approval_token": None,
    }

    with pytest.raises(PlanRejected, match="stopped"):
        service.build_and_preview_automation_release(vault, {**release_request, "scheduler_state": "running"})


def test_release_idempotent_replay_rejects_unrelated_sidecar_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault, request = _fixture(tmp_path, monkeypatch)
    _claim(vault, request)
    release_request = {
        "automation_id": LABEL,
        "owner_id": "dex-solo",
        "scheduler_state": "stopped",
    }
    previewed = service.build_and_preview_automation_release(vault, release_request)
    service.execute_approved_automation_release(vault, previewed["preview"], previewed["approval_token"])
    sidecar = vault / automation_ownership.SIDECAR_RELATIVE
    sidecar.write_bytes(
        _canonical(
            {
                "schema_version": 1,
                "claims": [
                    {
                        "automation_id": "com.dex.zzz",
                        "owner_id": "dex-solo",
                        "plist_relative_path": "Library/LaunchAgents/com.dex.zzz.plist",
                        "plist_sha256": "0" * 64,
                    }
                ],
            }
        )
    )

    with pytest.raises(PlanRejected, match="state changed since preview"):
        service.execute_approved_automation_release(
            vault,
            previewed["preview"],
            previewed["approval_token"],
        )


def test_release_rejects_foreign_owner_and_tampered_approval(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault, request = _fixture(tmp_path, monkeypatch)
    _claim(vault, request)
    release_request = {
        "automation_id": LABEL,
        "owner_id": "dex-solo",
        "scheduler_state": "stopped",
    }
    previewed = service.build_and_preview_automation_release(vault, release_request)

    with pytest.raises(PlanRejected, match="approval token"):
        service.execute_approved_automation_release(vault, previewed["preview"], "0" * 64)
    with pytest.raises(PlanRejected, match="Dex Solo"):
        service.build_and_preview_automation_release(vault, {**release_request, "owner_id": "foreign-owner"})
