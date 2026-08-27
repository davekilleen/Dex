"""ChatGPT Work desktop is not Codex, and Doctor must name the web limit."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.harnesses.registry import detect_harnesses, get_profile
from core.mcp import onboarding_server
from core.onboarding.harness_receipt import (
    build_receipt_for_ids,
    canonical_receipt_bytes,
)
from core.utils import doctor

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def context(tmp_path: Path) -> doctor.DoctorContext:
    vault = tmp_path / "vault"
    (vault / "System").mkdir(parents=True)
    (vault / "core").mkdir()
    home = tmp_path / "home"
    home.mkdir()
    return doctor.DoctorContext(vault_root=vault, repo_root=vault, home=home, now=NOW)


def test_chatgpt_work_markers_do_not_select_codex() -> None:
    for env in (
        {"CHATGPT_WORK": "1"},
        {"OPENAI_WORK": "1"},
        {"CHATGPT_WORK_COMPANION": "1"},
    ):
        detected = [profile.id for profile in detect_harnesses(env=env)]
        assert detected == ["chatgpt-work"]

    detected = [
        profile.id
        for profile in detect_harnesses(env={}, paths=[Path("/tmp/.chatgpt-work/app")])
    ]
    assert detected == ["chatgpt-work"]

    assert [profile.id for profile in detect_harnesses(env={"CODEX_CLI": "1"})] == ["codex"]
    assert [
        profile.id
        for profile in detect_harnesses(env={}, paths=[Path("/tmp/.codex/session")])
    ] == ["codex"]


def test_doctor_names_chatgpt_work_web_limit_without_calling_it_codex(
    context: doctor.DoctorContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.harnesses.registry.platform_module.system", lambda: "Linux")
    receipt = build_receipt_for_ids(
        ["chatgpt-work"],
        detected_ids=("chatgpt-work",),
        source="user-confirmed",
        generated_at=NOW,
    )
    receipt_path = context.vault_root / "System/.dex/harness-profile.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(canonical_receipt_bytes(receipt))

    result = doctor._probe_harness_capabilities(context)

    assert result.verdict == "OK"
    assert "ChatGPT Work" in result.detail
    assert "Codex" not in result.detail
    assert "web" in result.detail.lower()
    assert "https" in result.detail.lower()
    assert result.structured_detail["selected"] == ["chatgpt-work"]
    assert result.structured_detail["limitations"] == {
        "chatgpt-work": list(get_profile("chatgpt-work").limitations),
    }


def test_setup_preview_keeps_chatgpt_work_separate_from_codex() -> None:
    inspected = onboarding_server.inspect_harnesses(["chatgpt-work"])

    assert inspected["selected"] == ["chatgpt-work"]
    assert "codex" not in inspected["selected"]
    by_id = {row["id"]: row for row in inspected["profiles"]}
    assert by_id["chatgpt-work"]["limitations"] == list(
        get_profile("chatgpt-work").limitations
    )
    joined = " ".join(by_id["chatgpt-work"]["limitations"]).lower()
    assert "web" in joined
    assert "https" in joined
    assert "codex" not in joined
