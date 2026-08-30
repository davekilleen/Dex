"""Capability-aware onboarding receipts stay small, private, and truthful."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.onboarding.harness_receipt import (
    HarnessReceiptError,
    build_receipt,
    canonical_receipt_bytes,
    read_receipt,
    summarize_receipt,
)


def _profile(profile_id: str, *, pre_tool: str = "unavailable") -> dict[str, object]:
    return {
        "id": profile_id,
        "display_name": profile_id.replace("-", " ").title(),
        "capabilities": [
            {"id": "vault", "mode": "automatic"},
            {"id": "mcp", "mode": "on_demand"},
            {"id": "pre_tool", "mode": pre_tool},
        ],
    }


def test_receipt_is_deterministic_and_contains_no_environment_paths() -> None:
    receipt = build_receipt(
        [_profile("codex", pre_tool="automatic"), _profile("pi")],
        detected_ids=("pi", "codex"),
        source="user-confirmed",
        generated_at=datetime(2026, 8, 25, 8, 30, tzinfo=timezone.utc),
    )

    assert receipt["schema_version"] == 1
    assert receipt["selected"] == ["codex", "pi"]
    assert receipt["detected"] == ["codex", "pi"]
    assert receipt["source"] == "user-confirmed"
    assert receipt["generated_at"] == "2026-08-25T08:30:00+00:00"
    assert "/home/" not in canonical_receipt_bytes(receipt).decode()


def test_receipt_rejects_unknown_modes_and_duplicate_profiles() -> None:
    invalid = _profile("codex")
    invalid["capabilities"][0]["mode"] = "magic"  # type: ignore[index]
    with pytest.raises(HarnessReceiptError, match="mode"):
        build_receipt([invalid], detected_ids=(), source="detected")

    with pytest.raises(HarnessReceiptError, match="duplicate"):
        build_receipt(
            [_profile("codex"), _profile("codex")],
            detected_ids=(),
            source="user-confirmed",
        )


def test_read_receipt_refuses_symlinks_and_malformed_json(tmp_path: Path) -> None:
    runtime = tmp_path / "System/.dex"
    runtime.mkdir(parents=True)
    target = tmp_path / "outside.json"
    target.write_text("{}\n", encoding="utf-8")
    receipt_path = runtime / "harness-profile.json"
    receipt_path.symlink_to(target)

    with pytest.raises(HarnessReceiptError, match="symlink"):
        read_receipt(tmp_path)

    receipt_path.unlink()
    receipt_path.write_text("not json\n", encoding="utf-8")
    with pytest.raises(HarnessReceiptError, match="valid JSON"):
        read_receipt(tmp_path)


def test_read_and_summarize_preserves_automatic_vs_advisory_truth(tmp_path: Path) -> None:
    receipt = build_receipt(
        [_profile("codex", pre_tool="automatic"), _profile("pi")],
        detected_ids=("codex",),
        source="user-confirmed",
    )
    runtime = tmp_path / "System/.dex"
    runtime.mkdir(parents=True)
    (runtime / "harness-profile.json").write_bytes(canonical_receipt_bytes(receipt))

    loaded = read_receipt(tmp_path)
    summary = summarize_receipt(loaded)

    assert loaded == receipt
    assert summary["selected"] == ["codex", "pi"]
    assert summary["modes"] == {
        "automatic": 3,
        "on_demand": 2,
        "guided": 0,
        "unavailable": 1,
    }
    assert summary["fully_automatic"] is False


def test_read_receipt_rejects_unexpected_fields(tmp_path: Path) -> None:
    runtime = tmp_path / "System/.dex"
    runtime.mkdir(parents=True)
    (runtime / "harness-profile.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": "2026-08-25T08:30:00+00:00",
                "source": "detected",
                "selected": ["codex"],
                "detected": ["codex"],
                "profiles": [_profile("codex")],
                "secret": "must not survive",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(HarnessReceiptError, match="unexpected fields"):
        read_receipt(tmp_path)


@pytest.mark.parametrize("detected", ("codex", None, 1, {}))
def test_read_receipt_rejects_non_list_detected_ids(
    tmp_path: Path,
    detected: object,
) -> None:
    receipt = build_receipt(
        [_profile("codex")],
        detected_ids=("codex",),
        source="detected",
        generated_at="2026-08-25T08:30:00+00:00",
    )
    receipt["detected"] = detected
    runtime = tmp_path / "System/.dex"
    runtime.mkdir(parents=True)
    (runtime / "harness-profile.json").write_bytes(
        (json.dumps(receipt) + "\n").encode("utf-8")
    )

    with pytest.raises(HarnessReceiptError, match="detected.*list"):
        read_receipt(tmp_path)


def test_doctor_instructions_preserve_delivery_mode_truth() -> None:
    skill = (
        Path(__file__).resolve().parents[2] / ".claude/skills/dex-doctor/SKILL.md"
    ).read_text(encoding="utf-8")

    section = skill.split("For **Agent harness capabilities**", 1)[1].split(
        "For the **Entity engine**",
        1,
    )[0]
    for mode in ("automatic", "on_demand", "guided", "unavailable"):
        assert mode in section
    assert "Never describe a guided MCP safety check as an automatic block" in section
    assert "personal Work copy is behind this folder" in section
    assert "sentence is absent, stay silent" in section
    assert "Never invent a folder grant" in section
