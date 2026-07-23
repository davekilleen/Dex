"""D2 Doctor journey: adoption choices, recovery, and rewind evidence."""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.lifecycle.catalog import with_catalog_identity
from core.lifecycle.engine import AdoptionReceipt, canonical_adoption_receipt_bytes
from core.lifecycle.ledger import record_adoption, record_holdback
from core.tests.lifecycle_test_helpers import SOURCE_COMMIT, write_file, write_manifest
from core.transaction.journal import Journal
from core.transaction.snapshot import Snapshot
from core.utils import doctor

NOW = datetime(2026, 7, 21, 14, 30, tzinfo=timezone.utc)
ADOPTION_TX_ID = "20260721T120000-00000001"
INTERRUPTED_TX_ID = "20260721T121500-00000002"


def _tree_snapshot(root: Path) -> dict[str, tuple[object, ...]]:
    snapshot: dict[str, tuple[object, ...]] = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        mode = stat.S_IMODE(path.stat().st_mode)
        snapshot[relative] = (
            ("dir", mode) if path.is_dir() else ("file", mode, path.read_bytes())
        )
    return snapshot


def _catalog_document(vault: Path, contents: dict[str, bytes]) -> dict[str, object]:
    manifest = write_manifest(
        vault,
        sorted(f".claude/skills/{item_id}/SKILL.md" for item_id in contents),
    )
    items = []
    for item_id, content in sorted(contents.items()):
        path = f".claude/skills/{item_id}/SKILL.md"
        items.append(
            {
                "id": item_id,
                "kind": "skill",
                "version": "1.0.0",
                "files": [
                    {
                        "path": path,
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "ownership_class": "brain",
                    }
                ],
                "dependencies": [],
                "capabilities": [],
                "rewind": {
                    "acknowledgement_required": True,
                    "token": f"rewind:{item_id}@1.0.0",
                },
            }
        )
    return with_catalog_identity(
        {
            "catalog_version": 1,
            "release": {
                "version": "1.67.0",
                "channel": "release",
                "immutable_distribution_tag": "dist/release/v1.67.0-0123456",
                "source_commit": SOURCE_COMMIT,
                "manifest": {
                    "path": "System/.installed-files.manifest",
                    "sha256": hashlib.sha256(manifest).hexdigest(),
                },
            },
            "items": items,
            "integrity": {"catalog_sha256": "0" * 64, "signatures": []},
        }
    )


def _adoption_receipt(item_id: str) -> AdoptionReceipt:
    content = b"# adopted\n"
    return AdoptionReceipt.from_dict(
        {
            "receipt_version": 1,
            "items_adopted": [item_id],
            "files_written": [
                {
                    "item_id": item_id,
                    "path": f".claude/skills/{item_id}/SKILL.md",
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "byte_size": len(content),
                }
            ],
            "transaction_id": ADOPTION_TX_ID,
            "snapshot_ref": f"System/.dex/tx/{ADOPTION_TX_ID}/snapshot",
            "catalog_sha256": "a" * 64,
            "inventory_sha256": "b" * 64,
            "preview_sha256": "c" * 64,
        }
    )


def _journey_vault(tmp_path: Path) -> tuple[doctor.DoctorContext, Path]:
    vault = tmp_path / "vault"
    vault.mkdir()
    contents = {
        "adoptable": b"# adoptable\n",
        "adopted-receipt": b"# adopted\n",
        "conflicted": b"# stock conflict\n",
        "held-back": b"# held\n",
    }
    for item_id, content in contents.items():
        write_file(vault, f".claude/skills/{item_id}/SKILL.md", content)
    document = _catalog_document(vault, contents)
    catalog_path = vault / "System/.release-catalog.json"
    catalog_path.write_text(json.dumps(document), encoding="utf-8")

    # A real customization: installed bytes no longer match the catalog.
    write_file(vault, ".claude/skills/conflicted/SKILL.md", b"# user customization\n")

    record_holdback(vault, "held-back")
    adoption_receipt = _adoption_receipt("adopted-receipt")
    record_adoption(
        vault,
        adoption_receipt,
        {"adopted-receipt": "1.0.0"},
    )
    adoption_tx = vault / f"System/.dex/tx/{ADOPTION_TX_ID}"
    Snapshot(adoption_tx / "snapshot").capture(
        vault,
        [".claude/skills/adopted-receipt/SKILL.md"],
    )
    adoption_journal = Journal(adoption_tx / "journal.jsonl")
    adoption_journal.append("BEGIN", {"tx_id": ADOPTION_TX_ID, "plan": []})
    adoption_journal.append("COMMITTED")
    receipt_path = vault / f"System/.dex/adoptions/{ADOPTION_TX_ID}.receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_bytes(canonical_adoption_receipt_bytes(adoption_receipt))

    # Fabricate the same mid-state journal shape used by txcore tests, but do
    # not call Transaction.resume: collection must remain inspection-only.
    journal = Journal(vault / f"System/.dex/tx/{INTERRUPTED_TX_ID}/journal.jsonl")
    journal.append(
        "BEGIN",
        {
            "tx_id": INTERRUPTED_TX_ID,
            "plan": [
                {
                    "relative": "System/.installed-files.manifest",
                    "operation": "write",
                    "sha256": "d" * 64,
                    "mode": 0o644,
                    "size": 8,
                    "expected_current_sha256": None,
                }
            ],
        },
    )
    journal.append("STAGED")
    journal.append("SNAPSHOT-START")

    home = tmp_path / "home"
    home.mkdir()
    return doctor.DoctorContext(vault, vault, home, NOW), catalog_path


def _groups(report: doctor.AdoptionReport) -> dict[str, dict[str, object]]:
    return {group["id"]: group for group in report.to_dict()["groups"]}


def test_adoption_report_binds_all_five_groups_and_degrades_honestly(
    tmp_path: Path,
) -> None:
    context, catalog_path = _journey_vault(tmp_path)
    before = _tree_snapshot(context.vault_root)

    report = doctor.collect_adoption_report(context)

    assert _tree_snapshot(context.vault_root) == before
    assert report.verdict == "BROKEN"
    groups = _groups(report)
    assert list(groups) == [
        "new-and-safe",
        "needs-your-review",
        "preserved-for-now",
        "continue-or-recover",
        "receipts-and-rewind",
    ]
    assert groups["new-and-safe"]["items"] == [
        {"item_id": "adoptable", "item_version": "1.0.0", "action": "adopt"}
    ]
    assert groups["new-and-safe"]["count"] == 1

    review = groups["needs-your-review"]
    assert review["count"] == 1
    assert review["items"][0]["item_id"] == "conflicted"
    assert review["items"][0]["action"] == "conflict"
    assert review["items"][0]["files"] == [
        {
            "path": ".claude/skills/conflicted/SKILL.md",
            "reason": "release-files-modified",
        }
    ]

    preserved = groups["preserved-for-now"]
    assert preserved["count"] == 2
    assert preserved["held_back_items"] == [
        {"item_id": "held-back", "item_version": "1.0.0", "action": "skip-held-back"}
    ]
    assert preserved["customized_files"] == [
        {
            "path": ".claude/skills/conflicted/SKILL.md",
            "state": "stock-modified",
            "reason": "installed bytes differ from the verified release catalog",
        }
    ]

    recovery = groups["continue-or-recover"]
    assert recovery["count"] == 1
    assert recovery["transactions"] == [
        {
            "tx_id": INTERRUPTED_TX_ID,
            "verdict": "BROKEN",
            "last_event": "SNAPSHOT-START",
            "snapshot_present": False,
        }
    ]
    assert recovery["ledger"] is None

    receipts = groups["receipts-and-rewind"]
    assert receipts["count"] == 1
    assert receipts["receipts"] == [
        {
            "item_id": "adopted-receipt",
            "item_version": "1.0.0",
            "status": "adopted",
            "transaction_id": ADOPTION_TX_ID,
            "when": "2026-07-21T12:00:00",
            "rewindable": True,
            "rewind_verdict": "OK",
        }
    ]

    canonical = doctor.canonical_adoption_report_bytes(report)
    assert canonical == (
        json.dumps(
            report.to_dict(),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    assert json.loads(canonical)["groups"] == report.to_dict()["groups"]

    catalog_bytes = catalog_path.read_bytes()
    catalog_path.unlink()
    off = doctor.collect_adoption_report(context)
    assert off.verdict == "OFF"
    assert all(group["count"] == 0 for group in off.to_dict()["groups"])

    catalog_path.write_bytes(catalog_bytes)
    first_event = sorted((context.vault_root / "System/.dex/ledger/events").glob("*.json"))[0]
    first_event_bytes = first_event.read_bytes()
    first_event.write_bytes(b"{corrupt ledger")
    unknown = doctor.collect_adoption_report(context)
    assert unknown.verdict == "UNKNOWN"
    recovery = _groups(unknown)["continue-or-recover"]
    assert recovery["ledger"]["verdict"] == "UNKNOWN"
    assert recovery["ledger"]["incomplete_publication"] is False
    assert recovery["ledger"]["repair_command"] == (
        f"python3 -m core.lifecycle.cli --vault-root {context.vault_root} rebuild-state"
    )
    assert "rebuild-state" in recovery["surface"]

    first_event.write_bytes(first_event_bytes)
    terminal_commitment = sorted(
        (context.vault_root / "System/.dex/ledger/commitments").glob("*.sha256")
    )[-1]
    terminal_commitment.unlink()
    incomplete = doctor.collect_adoption_report(context)
    incomplete_recovery = _groups(incomplete)["continue-or-recover"]["ledger"]
    assert incomplete.verdict == "UNKNOWN"
    assert incomplete_recovery["incomplete_publication"] is True
    assert "rebuild-state" in incomplete_recovery["repair_command"]


def test_receipt_rewindable_fails_closed_when_snapshot_evidence_is_damaged(
    tmp_path: Path,
) -> None:
    context, _catalog_path = _journey_vault(tmp_path)
    manifest = context.vault_root / f"System/.dex/tx/{ADOPTION_TX_ID}/snapshot/manifest.json"
    manifest.unlink()

    receipt = _groups(doctor.collect_adoption_report(context))["receipts-and-rewind"][
        "receipts"
    ][0]

    assert receipt["rewindable"] is False
    assert receipt["rewind_verdict"] == "UNKNOWN"


def test_unknown_planner_item_is_visible_and_makes_report_unknown(tmp_path: Path) -> None:
    context, _catalog_path = _journey_vault(tmp_path)
    Journal(
        context.vault_root / f"System/.dex/tx/{INTERRUPTED_TX_ID}/journal.jsonl"
    ).append("ROLLED-BACK")
    adoptable = context.vault_root / ".claude/skills/adoptable/SKILL.md"
    adoptable.unlink()
    adoptable.symlink_to("../conflicted/SKILL.md")

    report = doctor.collect_adoption_report(context)
    review = _groups(report)["needs-your-review"]

    assert report.verdict == "UNKNOWN"
    assert review["verdict"] == "UNKNOWN"
    assert review["count"] == 2
    unknown = next(item for item in review["items"] if item["item_id"] == "adoptable")
    assert unknown["action"] == "unknown"
    assert unknown["reasons"] == ["release-files-unknown"]
    assert unknown["files"] == [
        {
            "path": ".claude/skills/adoptable/SKILL.md",
            "reason": "release-files-unknown",
        }
    ]


def test_adoption_authority_dataclasses_reject_invalid_vocabulary_and_shape(
    tmp_path: Path,
) -> None:
    context, _catalog_path = _journey_vault(tmp_path)
    report = doctor.collect_adoption_report(context)

    with pytest.raises(ValueError, match="action"):
        doctor.AdoptionItem("adoptable", "1.0.0", "invented-action")
    with pytest.raises(ValueError, match="status"):
        doctor.AdoptionReceiptSummary(
            "adopted-receipt",
            "1.0.0",
            "invented-status",
            ADOPTION_TX_ID,
            "2026-07-21T12:00:00",
            True,
            "OK",
        )

    mismatched_count = replace(report.groups[0], count=999)
    with pytest.raises(ValueError, match="count"):
        replace(report, groups=(mismatched_count, *report.groups[1:]))

    boolean_count = replace(report.groups[0], count=True)
    with pytest.raises(ValueError, match="count"):
        replace(report, groups=(boolean_count, *report.groups[1:]))

    wrong_group_type = doctor.NeedsReviewGroup(
        "new-and-safe",
        "OK",
        0,
        (),
        "Wrong authority type.",
    )
    with pytest.raises(ValueError, match="group types"):
        replace(report, groups=(wrong_group_type, *report.groups[1:]))
