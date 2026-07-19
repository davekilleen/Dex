import json
import os
import socket
from pathlib import Path

import pytest

from core.utils.credential_remediation import (
    CAPABILITIES,
    migrate_legacy_credentials,
    probe_atomic_migration,
    render_credential_status,
    rewind_credential_migration,
)


def _vault(tmp_path: Path, raw: bytes | None = None) -> Path:
    config = tmp_path / "System" / "integrations" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_bytes(raw or b"# preserved\r\ntodoist:\r\n  enabled: true\r\n  api_key: synthetic-old-key\r\n")
    return tmp_path


def test_live_probe_is_complete_and_class_agnostic(tmp_path):
    root = _vault(tmp_path)
    result = probe_atomic_migration(root, root / "System/.dex/adoption/credential-journals")
    assert set(result.results) == set(CAPABILITIES)
    assert result.authorized


def test_not_needed_creates_no_migration_state(tmp_path):
    root = _vault(tmp_path, b"todoist:\n  enabled: false\n  api_key_env_var: TODOIST_API_KEY\n")
    assert migrate_legacy_credentials(root).state == "not-needed"
    assert not (root / "System/.dex").exists()


def test_atomic_migration_preserves_yaml_bytes_and_exact_rewind(tmp_path):
    root = _vault(tmp_path)
    config = root / "System/integrations/config.yaml"
    before = config.read_bytes()
    result = migrate_legacy_credentials(root)
    assert result.state == "migrated-local-config"
    assert config.read_bytes() == before.replace(b"api_key: synthetic-old-key", b"api_key_env_var: TODOIST_API_KEY")
    assert (root / ".env").read_text() == "TODOIST_API_KEY=synthetic-old-key\n"
    rewind = rewind_credential_migration(root, result.journal_id)
    assert rewind.state == "rewound"
    assert config.read_bytes() == before
    assert not (root / ".env").exists()


def test_conflict_symlink_and_mcp_residual_are_honest(tmp_path):
    root = _vault(tmp_path)
    (root / ".env").write_text("TODOIST_API_KEY=different\n")
    assert migrate_legacy_credentials(root).state == "refused"
    (root / ".env").unlink()
    mcp = root / ".mcp.json"
    mcp.write_text('{"env":{"TODOIST_API_KEY":"synthetic-old-key"}}')
    before = mcp.read_bytes()
    assert migrate_legacy_credentials(root).state == "partial"
    assert mcp.read_bytes() == before


@pytest.mark.parametrize("external", [False, True])
def test_symlinked_mcp_is_partial_or_refused_and_explicitly_uninspected(tmp_path, external):
    root = _vault(tmp_path, b"todoist:\n  api_key_env_var: TODOIST_API_KEY\n")
    target = (tmp_path.parent / "outside-mcp.json") if external else (root / "inside-mcp.json")
    target.write_text('{"env":{"TODOIST_API_KEY":"outside-value"}}')
    (root / ".mcp.json").symlink_to(target)
    result = migrate_legacy_credentials(root)
    assert result.state == "partial"
    assert result.active_residual_state == "unrevoked-or-unclassified"
    assert result.uninspected_scopes == ("worktree",)
    assert result.uninspected_reasons == ("unsafe-active-config",)


def test_nonregular_and_hardlinked_mcp_fail_closed(tmp_path):
    root = _vault(tmp_path, b"todoist:\n  api_key_env_var: TODOIST_API_KEY\n")
    os.mkfifo(root / ".mcp.json")
    assert migrate_legacy_credentials(root).state == "partial"
    (root / ".mcp.json").unlink()
    source = root / "mcp-source"
    source.write_text("{}")
    os.link(source, root / ".mcp.json")
    assert migrate_legacy_credentials(root).active_residual_state == "unrevoked-or-unclassified"


@pytest.mark.parametrize("kind", ["directory", "unreadable", "oversized", "socket"])
def test_other_unsafe_active_config_types_fail_closed(tmp_path, kind):
    root = _vault(tmp_path, b"todoist:\n  api_key_env_var: TODOIST_API_KEY\n")
    path = root / ".mcp.json"
    listener = None
    if kind == "directory":
        path.mkdir()
    elif kind == "unreadable":
        path.write_text("{}")
        path.chmod(0)
    elif kind == "oversized":
        path.write_bytes(b"x" * (1024 * 1024 + 1))
    else:
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(path))
    try:
        result = migrate_legacy_credentials(root)
        assert result.state == "partial"
        assert result.active_residual_state == "unrevoked-or-unclassified"
        assert result.uninspected_scopes == ("worktree",)
    finally:
        if listener:
            listener.close()


def test_active_config_identity_race_is_uninspected(tmp_path, monkeypatch):
    root = _vault(tmp_path, b"todoist:\n  api_key_env_var: TODOIST_API_KEY\n")
    (root / ".mcp.json").write_text("{}")
    from core.utils.integration_credentials import ActiveConfigInspection

    monkeypatch.setattr(
        "core.utils.credential_remediation.inspect_active_mcp_config",
        lambda _: ActiveConfigInspection(None, False, "active-config-identity-change"),
    )
    result = migrate_legacy_credentials(root)
    assert result.state == "partial"
    assert result.uninspected_reasons == ("active-config-identity-change",)


def test_renderer_exact_copy_and_impossible_combinations():
    status = render_credential_status(
        "partial",
        "remediated",
        "proven-revoked",
        "history-cleanup-pending",
        (
            "old-key-revocation",
            "replacement-present",
            "replacement-health",
            "active-copy",
            "provider-binding",
        ),
        (),
    )
    assert status.security_and_current_config == (
        "Your old key was rotated and is no longer usable. Security is fixed. Setup cleanup is incomplete because "
        "`.mcp.json` still contains the revoked value; remove it manually to complete local-config cleanup. Dex did not edit this file."
    )
    assert status.history == "Copies remain in inspected local Git history. Cleaning them is optional privacy hygiene."
    with pytest.raises(ValueError):
        render_credential_status(
            "migrated-local-config", "remediated", "proven-revoked", "history-clean", ("provider-binding",), ()
        )
    with pytest.raises(ValueError):
        render_credential_status("partial", "remediated", "unrevoked-or-unclassified", "history-clean", (), ())
    with pytest.raises(ValueError, match="complete bound"):
        render_credential_status("not-needed", "remediated", "none", "history-clean", (), ())
    with pytest.raises(ValueError, match="complete bound"):
        render_credential_status("not-needed", "remediated", "none", "history-clean", ("provider-binding",), ())
    with pytest.raises(ValueError):
        render_credential_status("not-needed", "unknown", "none", "history-scope-unknown", (), ())


def test_journal_contains_exact_preimage_but_no_absolute_path(tmp_path):
    root = _vault(tmp_path)
    result = migrate_legacy_credentials(root)
    journal = root / "System/.dex/adoption/credential-journals" / f"{result.journal_id}.json"
    payload = json.loads(journal.read_text())
    assert bytes.fromhex(payload["config"]["bytes_hex"]).endswith(b"synthetic-old-key\r\n")
    assert str(root) not in journal.read_text()
    assert journal.stat().st_mode & 0o777 == 0o600
