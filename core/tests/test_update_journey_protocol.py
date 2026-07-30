"""The release-owned updater journey protocol at its public seams."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from core import portable_contract
from core.update.journey_protocol import (
    PROTOCOL_RELATIVE,
    JourneyProtocolError,
    load_update_journey_protocol,
)
from scripts import dex_update_bridge

REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL_PATH = REPO_ROOT / "core/update/journey-protocol-v1.json"
GENERATOR = REPO_ROOT / "scripts/generate-update-journey-protocol.py"


def test_protocol_uses_the_foundation_classified_brain_tree() -> None:
    resolution = portable_contract.resolve(PROTOCOL_RELATIVE)

    assert PROTOCOL_RELATIVE == "core/update/journey-protocol-v1.json"
    assert resolution.rule_id == "brain-core"
    assert resolution.ownership == "brain"
    assert portable_contract.update_write_verdict(
        PROTOCOL_RELATIVE,
        exists=False,
    ).action == "replace"


def test_release_owned_protocol_binds_only_the_reviewed_update_adapters() -> None:
    protocol = load_update_journey_protocol(PROTOCOL_PATH.read_bytes())

    assert protocol.foundation == dex_update_bridge.FOUNDATION.identity()
    assert protocol.platforms == ("darwin",)
    assert protocol.bridge.adapter == "pinned-foundation-bridge-v1"
    assert protocol.follow_up.adapter == "lifecycle-delivered-release-v1"
    assert protocol.follow_up.operations == (
        "deliver_latest_release",
        "build_and_preview_delivered_release",
        "execute_approved_delivered_release",
    )
    assert protocol.bridge.approval_word == protocol.follow_up.approval_word == "APPLY"
    assert protocol.bridge.approval_count == 2
    assert protocol.follow_up.approval_count == 1
    assert protocol.executor.source_path == "scripts/release_fleet_executor.py"
    for artifact in (protocol.bridge.artifact, protocol.runner, protocol.executor):
        source = REPO_ROOT / artifact.source_path
        assert artifact.sha256 == hashlib.sha256(source.read_bytes()).hexdigest()


def test_protocol_rejects_an_arbitrary_command_adapter() -> None:
    document = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    document["historic_to_foundation"]["adapter"] = "shell-command"
    document["historic_to_foundation"]["command"] = ["sh", "-c", "anything"]

    with pytest.raises(JourneyProtocolError, match="invalid shape|unsupported adapter"):
        load_update_journey_protocol(json.dumps(document).encode())


def test_generator_reproduces_the_committed_root_protocol(tmp_path: Path) -> None:
    generated = tmp_path / "update-journey.json"

    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--output", str(generated)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert generated.read_bytes() == PROTOCOL_PATH.read_bytes()
