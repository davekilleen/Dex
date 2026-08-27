"""GitHub Copilot CLI is not ChatGPT Work, and Doctor must name the hook limit."""

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


def test_copilot_cli_markers_do_not_select_chatgpt_work() -> None:
    for env in (
        {"COPILOT_CLI": "1"},
        {"GH_COPILOT": "1"},
        {"GITHUB_COPILOT": "1"},
    ):
        detected = [profile.id for profile in detect_harnesses(env=env)]
        assert detected == ["copilot-cli"]

    for path in (Path("/tmp/.copilot/session"), Path("/tmp/copilot/bin")):
        detected = [profile.id for profile in detect_harnesses(env={}, paths=[path])]
        assert detected == ["copilot-cli"]

    assert [profile.id for profile in detect_harnesses(env={"CHATGPT_WORK": "1"})] == [
        "chatgpt-work"
    ]


def test_doctor_names_copilot_hook_limit_without_calling_it_chatgpt_work(
    context: doctor.DoctorContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("core.harnesses.registry.platform_module.system", lambda: "Linux")
    receipt = build_receipt_for_ids(
        ["copilot-cli"],
        detected_ids=("copilot-cli",),
        source="user-confirmed",
        generated_at=NOW,
    )
    receipt_path = context.vault_root / "System/.dex/harness-profile.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(canonical_receipt_bytes(receipt))

    result = doctor._probe_harness_capabilities(context)

    assert result.verdict == "OK"
    assert "GitHub Copilot CLI" in result.detail
    assert "ChatGPT Work" not in result.detail
    assert "hook" in result.detail.lower()
    assert "fully automatic" not in result.detail.lower()
    assert result.structured_detail["selected"] == ["copilot-cli"]
    assert result.structured_detail["limitations"] == {
        "copilot-cli": list(get_profile("copilot-cli").limitations),
    }
    rows = {row["id"]: row for row in get_profile("copilot-cli").capability_rows()}
    assert rows["hooks"]["status"] == "not-verified"
    assert rows["hooks"]["mode"] == "unavailable"


def test_setup_preview_keeps_copilot_cli_separate_from_chatgpt_work() -> None:
    inspected = onboarding_server.inspect_harnesses(["copilot-cli"])

    assert inspected["selected"] == ["copilot-cli"]
    assert "chatgpt-work" not in inspected["selected"]
    by_id = {row["id"]: row for row in inspected["profiles"]}
    assert by_id["copilot-cli"]["limitations"] == list(
        get_profile("copilot-cli").limitations
    )
    joined = " ".join(by_id["copilot-cli"]["limitations"]).lower()
    assert "hook" in joined
    assert "chatgpt" not in joined
    assert "microsoft 365" not in joined
