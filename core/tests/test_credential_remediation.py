import json
import os
import socket
import subprocess
from pathlib import Path

import pytest
import yaml

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


@pytest.mark.parametrize("reference_field", ["api_key_env_var", "token_env_var"])
def test_custom_configured_env_name_detects_active_mcp_residual_without_editing(tmp_path, reference_field):
    service = "todoist" if reference_field == "api_key_env_var" else "trello"
    custom_name = "CUSTOM_TODOIST_KEY" if service == "todoist" else "CUSTOM_TRELLO_TOKEN"
    root = _vault(
        tmp_path,
        f"{service}:\n  enabled: true\n  {reference_field}: {custom_name}\n".encode(),
    )
    mcp = root / ".mcp.json"
    mcp.write_text(
        json.dumps({"mcpServers": {service: {"env": {custom_name: "synthetic-custom-active"}}}})
    )
    before = mcp.read_bytes()

    result = migrate_legacy_credentials(root)

    assert result.state == "partial"
    assert result.active_residual_state == "unrevoked-or-unclassified"
    assert mcp.read_bytes() == before


def test_custom_configured_env_name_placeholder_is_not_a_raw_residual(tmp_path):
    root = _vault(tmp_path, b"todoist:\n  enabled: true\n  api_key_env_var: CUSTOM_TODOIST_KEY\n")
    mcp = root / ".mcp.json"
    mcp.write_text('{"mcpServers":{"todoist":{"env":{"CUSTOM_TODOIST_KEY":"${CUSTOM_TODOIST_KEY}"}}}}')
    before = mcp.read_bytes()

    result = migrate_legacy_credentials(root)

    assert result.state == "not-needed"
    assert result.active_residual_state == "none"
    assert mcp.read_bytes() == before


def test_custom_scan_set_is_enablement_independent_and_keeps_canonical_names(tmp_path):
    root = _vault(tmp_path, b"todoist:\n  enabled: false\n  api_key_env_var: CUSTOM_TODOIST_KEY\n")
    (root / ".mcp.json").write_text(
        '{"env":{"CUSTOM_TODOIST_KEY":"${CUSTOM_TODOIST_KEY}","TODOIST_API_KEY":"synthetic-canonical-active"}}'
    )

    result = migrate_legacy_credentials(root)

    assert result.state == "partial"
    assert result.active_residual_state == "unrevoked-or-unclassified"


@pytest.mark.parametrize(
    "configured_name",
    ["custom_lowercase", "1INVALID", "WITH-DASH", "${CUSTOM_TODOIST_KEY}", "", 7, ["CUSTOM"]],
)
def test_malformed_configured_env_reference_fails_closed(tmp_path, configured_name):
    root = _vault(
        tmp_path,
        ("todoist:\n  enabled: true\n  api_key_env_var: " + json.dumps(configured_name) + "\n").encode(),
    )
    mcp = root / ".mcp.json"
    mcp.write_text('{"mcpServers":{"todoist":{"env":{"TODOIST_API_KEY":"synthetic-active"}}}}')
    before = mcp.read_bytes()

    result = migrate_legacy_credentials(root)

    assert result.state == "refused"
    assert mcp.read_bytes() == before


def test_duplicate_or_oversized_configured_reference_fails_closed(tmp_path):
    duplicate = _vault(
        tmp_path / "duplicate",
        b"todoist:\n  api_key_env_var: CUSTOM_ONE\n  api_key_env_var: CUSTOM_TWO\n",
    )
    oversized = _vault(
        tmp_path / "oversized",
        b"todoist:\n  api_key_env_var: CUSTOM_TODOIST_KEY\n#" + b"x" * (1024 * 1024),
    )

    assert migrate_legacy_credentials(duplicate).state == "refused"
    assert migrate_legacy_credentials(oversized).state == "refused"


@pytest.mark.parametrize(
    ("service", "first_field", "second_field", "custom_name"),
    [
        ("todoist", "api_key_env_var", "token_env_var", "CUSTOM_TODOIST_FIRST"),
        ("trello", "api_key_env_var", "token_env_var", "CUSTOM_TRELLO_FIRST"),
    ],
)
def test_duplicate_top_level_service_mappings_with_different_references_fail_closed(
    tmp_path,
    service,
    first_field,
    second_field,
    custom_name,
):
    root = _vault(
        tmp_path,
        (
            f"{service}:\n  {first_field}: {custom_name}\n"
            f"{service}:\n  {second_field}: CUSTOM_SECOND_REFERENCE\n"
        ).encode(),
    )
    mcp = root / ".mcp.json"
    mcp.write_text(json.dumps({"env": {custom_name: "synthetic-duplicate-hidden-active"}}))
    before = mcp.read_bytes()

    result = migrate_legacy_credentials(root)

    assert result.state == "refused"
    assert mcp.read_bytes() == before


@pytest.mark.parametrize(
    "raw",
    [
        b"todoist:\n  api_key_env_var: CUSTOM_ONE\n  api_key_env_var: CUSTOM_TWO\n",
        b'"todo\\u0069st":\n  api_key_env_var: CUSTOM_ONE\ntodoist:\n  token_env_var: CUSTOM_TWO\n',
        b"trello:\n  nested:\n    duplicate: one\n    duplicate: two\n",
    ],
)
def test_ordinary_escaped_and_nested_duplicate_keys_fail_closed(tmp_path, raw):
    root = _vault(tmp_path, raw)
    assert migrate_legacy_credentials(root).state == "refused"


def test_permissive_yaml_loader_mutation_reproduces_hidden_custom_residual(tmp_path, monkeypatch):
    root = _vault(
        tmp_path,
        b"todoist:\n  api_key_env_var: CUSTOM_HIDDEN_FIRST\n"
        b"todoist:\n  token_env_var: CUSTOM_SECOND\n",
    )
    (root / ".mcp.json").write_text('{"env":{"CUSTOM_HIDDEN_FIRST":"synthetic-hidden-active"}}')
    monkeypatch.setattr("core.utils.credential_remediation._UniqueKeyLoader", yaml.SafeLoader)

    result = migrate_legacy_credentials(root)

    assert result.state == "not-needed"
    assert result.active_residual_state == "none"


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


@pytest.mark.parametrize(
    ("posture", "expected"),
    [("ignored", "migrated-local-config"), ("unignored", "refused"), ("tracked", "refused")],
)
def test_git_vault_requires_env_to_be_ignored_and_untracked(tmp_path, posture, expected):
    root = _vault(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    if posture in {"ignored", "tracked"}:
        (root / ".gitignore").write_text(".env\n")
    if posture == "tracked":
        (root / ".env").write_text("TODOIST_API_KEY=synthetic-old-key\n")
        subprocess.run(["git", "add", "-f", ".env"], cwd=root, check=True)

    result = migrate_legacy_credentials(root)

    assert result.state == expected
    if expected == "refused":
        assert b"api_key: synthetic-old-key" in (root / "System/integrations/config.yaml").read_bytes()


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


def test_config_reference_snapshot_swap_cannot_return_false_clean(tmp_path, monkeypatch):
    root = _vault(tmp_path, b"todoist:\n  api_key_env_var: CUSTOM_TODOIST_KEY\n")
    config = root / "System/integrations/config.yaml"
    (root / ".mcp.json").write_text("{}")
    from core.utils.integration_credentials import ActiveConfigInspection

    def inspect_and_swap(_root):
        replacement = config.with_suffix(".replacement")
        replacement.write_text("todoist:\n  api_key_env_var: OTHER_TODOIST_KEY\n")
        replacement.replace(config)
        return ActiveConfigInspection(b"{}", True)

    monkeypatch.setattr(
        "core.utils.credential_remediation.inspect_active_mcp_config",
        inspect_and_swap,
    )

    result = migrate_legacy_credentials(root)

    assert result.state == "partial"
    assert result.active_residual_state == "unrevoked-or-unclassified"
    assert result.uninspected_reasons == ("integration-config-identity-change",)


def test_config_snapshot_swap_after_capability_probe_refuses_before_env_write(tmp_path, monkeypatch):
    root = _vault(tmp_path)
    config = root / "System/integrations/config.yaml"
    original_probe = probe_atomic_migration

    def probe_and_swap(vault_root, journal_dir):
        result = original_probe(vault_root, journal_dir)
        replacement = config.with_suffix(".replacement")
        replacement.write_text("todoist:\n  api_key: synthetic-different-key\n")
        replacement.replace(config)
        return result

    monkeypatch.setattr(
        "core.utils.credential_remediation.probe_atomic_migration",
        probe_and_swap,
    )

    result = migrate_legacy_credentials(root)

    assert result.state == "refused"
    assert not (root / ".env").exists()
    assert b"synthetic-different-key" in config.read_bytes()


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
    active = render_credential_status(
        "partial",
        "rotation-pending",
        "unrevoked-or-unclassified",
        "history-clean",
    )
    assert active.security_and_current_config == (
        "An active `.mcp.json` value may still be usable. Security is not fixed; rotate/revoke it at the provider "
        "or remove it manually. Dex did not edit this file."
    )
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


def test_symlinked_journal_parent_refuses_without_writing_outside_vault(tmp_path):
    root = _vault(tmp_path / "vault")
    outside = tmp_path / "outside"
    outside.mkdir()
    dex_parent = root / "System/.dex"
    dex_parent.parent.mkdir(exist_ok=True)
    dex_parent.symlink_to(outside, target_is_directory=True)

    capability = probe_atomic_migration(root, root / "System/.dex/adoption/credential-journals")
    result = migrate_legacy_credentials(root)

    assert not capability.authorized
    assert result.state == "refused"
    assert list(outside.iterdir()) == []


def test_real_journal_parent_is_contained_and_authorized(tmp_path):
    root = _vault(tmp_path)
    journal_dir = root / "System/.dex/adoption/credential-journals"

    capability = probe_atomic_migration(root, journal_dir)

    assert capability.authorized
    assert journal_dir.is_dir()
    assert list(journal_dir.iterdir()) == []


def test_rewind_refuses_swapped_integration_parent_without_outside_write(tmp_path):
    root = _vault(tmp_path / "vault")
    result = migrate_legacy_credentials(root)
    integrations = root / "System/integrations"
    preserved = root / "System/integrations-preserved"
    integrations.rename(preserved)
    outside = tmp_path / "outside"
    outside.mkdir()
    integrations.symlink_to(outside, target_is_directory=True)

    with pytest.raises(OSError):
        rewind_credential_migration(root, result.journal_id)

    assert list(outside.iterdir()) == []
    assert b"synthetic-old-key" not in b"".join(path.read_bytes() for path in outside.iterdir())


def test_rewind_replaces_env_symlink_without_touching_its_target(tmp_path):
    root = _vault(tmp_path)
    (root / ".env").write_text("TODOIST_API_KEY=synthetic-old-key\n")
    result = migrate_legacy_credentials(root)
    outside = tmp_path.parent / "outside-env"
    outside.write_text("outside-safe\n")
    (root / ".env").unlink()
    (root / ".env").symlink_to(outside)

    assert rewind_credential_migration(root, result.journal_id).state == "rewound"
    assert not (root / ".env").is_symlink()
    assert (root / ".env").read_text() == "TODOIST_API_KEY=synthetic-old-key\n"
    assert outside.read_text() == "outside-safe\n"
