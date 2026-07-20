import json
import os
import socket
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from core.utils import credential_remediation
from core.utils.credential_remediation import (
    CAPABILITIES,
    CredentialEvidence,
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
    monkeypatch.setattr(
        "core.utils.credential_remediation.load_yaml_bytes",
        lambda raw, **_kwargs: yaml.safe_load(raw),
    )

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
    assert (root / ".env").read_text() == 'TODOIST_API_KEY="synthetic-old-key"\n'
    rewind = rewind_credential_migration(root, result.journal_id)
    assert rewind.state == "rewound"
    assert config.read_bytes() == before
    assert not (root / ".env").exists()


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("boundary", ["before-env", "after-env", "before-config", "after-config"])
def test_baseexception_at_every_mutation_boundary_rewinds_exactly(tmp_path, monkeypatch, interruption, boundary):
    root = _vault(tmp_path)
    config = root / "System/integrations/config.yaml"
    before = config.read_bytes()
    real_update = credential_remediation.update_vault_env
    real_replace = credential_remediation._atomic_replace_at

    if boundary in {"before-env", "after-env"}:
        def interrupt_env(*args, **kwargs):
            if boundary == "after-env":
                real_update(*args, **kwargs)
            raise interruption()

        monkeypatch.setattr(credential_remediation, "update_vault_env", interrupt_env)
    else:
        interrupted = False

        def interrupt_config(directory, name, data, mode, **kwargs):
            nonlocal interrupted
            if name != "config.yaml" or interrupted:
                return real_replace(directory, name, data, mode, **kwargs)
            interrupted = True
            if boundary == "after-config":
                real_replace(directory, name, data, mode, **kwargs)
            raise interruption()

        monkeypatch.setattr(credential_remediation, "_atomic_replace_at", interrupt_config)

    with pytest.raises(interruption):
        migrate_legacy_credentials(root)
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
        (root / ".env").chmod(0o600)
        subprocess.run(["git", "add", "-f", ".env"], cwd=root, check=True)

    result = migrate_legacy_credentials(root)

    assert result.state == expected
    if expected == "refused":
        assert b"api_key: synthetic-old-key" in (root / "System/integrations/config.yaml").read_bytes()


def test_conflict_symlink_and_mcp_residual_are_honest(tmp_path):
    root = _vault(tmp_path)
    (root / ".env").write_text("TODOIST_API_KEY=different\n")
    (root / ".env").chmod(0o600)
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


def test_read_only_existing_config_refuses_migration_without_mutation(tmp_path):
    root = _vault(tmp_path)
    config = root / "System/integrations/config.yaml"
    before = config.read_bytes()
    config.chmod(0o400)

    result = migrate_legacy_credentials(root)

    assert result.state == "refused"
    assert config.read_bytes() == before
    assert stat.S_IMODE(config.stat().st_mode) == 0o400
    assert not (root / ".env").exists()


def test_writable_existing_config_is_required_for_capability_authorization(tmp_path, monkeypatch):
    root = _vault(tmp_path)
    config = root / "System/integrations/config.yaml"
    config.chmod(0o400)
    original = credential_remediation._contained_regular
    monkeypatch.setattr(
        credential_remediation,
        "_contained_regular",
        lambda path, vault_root, **kwargs: original(
            path,
            vault_root,
            **{key: value for key, value in kwargs.items() if key != "writable_if_present"},
        ),
    )

    assert probe_atomic_migration(root, root / "System/.dex/adoption/credential-journals").authorized


@pytest.mark.parametrize(
    ("security_state", "active_residual_state", "evidence_codes", "valid"),
    [
        ("rotation-pending", "none", (), False),
        ("rotation-pending", "none", ("replacement-health",), True),
        ("rotation-pending", "unrevoked-or-unclassified", (), True),
        ("unknown", "none", (), False),
        ("unknown", "none", ("provider-binding",), True),
        ("unknown", "unrevoked-or-unclassified", (), False),
        ("unknown", "unrevoked-or-unclassified", ("active-copy",), True),
    ],
)
def test_pending_and_unknown_status_require_explicit_reason(
    security_state,
    active_residual_state,
    evidence_codes,
    valid,
):
    migration_state = "partial" if active_residual_state != "none" else "not-needed"

    def call():
        return render_credential_status(
            migration_state,
            security_state,
            active_residual_state,
            "history-cleanup-pending",
            evidence_codes,
            (),
        )

    if valid:
        assert call().security_and_current_config
    else:
        with pytest.raises(ValueError):
            call()


def test_typed_evidence_polarity_distinguishes_present_missing_and_unavailable():
    pending = render_credential_status(
        "not-needed",
        "rotation-pending",
        "none",
        "history-clean",
        CredentialEvidence(missing=("provider-binding",)),
    )
    assert "incomplete: provider-binding" in pending.security_and_current_config
    unknown = render_credential_status(
        "not-needed",
        "unknown",
        "none",
        "history-clean",
        CredentialEvidence(unavailable=("provider-binding",), unknown_causes=("inconsistent",)),
    )
    assert "unavailable or inconsistent: provider-binding" in unknown.security_and_current_config
    with pytest.raises(ValueError, match="polarity"):
        render_credential_status(
            "not-needed",
            "unknown",
            "none",
            "history-clean",
            CredentialEvidence(
                present=("provider-binding",),
                unavailable=("provider-binding",),
                unknown_causes=("inconsistent",),
            ),
        )


@pytest.mark.parametrize("history_state", ["history-clean", "history-cleanup-pending"])
def test_only_unknown_history_accepts_uninspected_scopes(history_state):
    with pytest.raises(ValueError, match="uninspected scopes"):
        render_credential_status(
            "not-needed",
            "rotation-pending",
            "none",
            history_state,
            ("replacement-health",),
            ("tags",),
        )


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
    assert set(payload) == credential_remediation.CredentialJournal.TOP_LEVEL_KEYS
    assert set(payload["postimages"]) == credential_remediation.CredentialJournal.POSTIMAGE_KEYS
    assert payload["rewind"] == {"phase": "ready"}
    assert credential_remediation.CredentialJournal.parse(journal.read_bytes()).serialize() == journal.read_bytes()
    assert str(root) not in journal.read_text()
    assert journal.stat().st_mode & 0o777 == 0o600


def test_closed_credential_journal_owns_valid_rewind_transitions(tmp_path):
    root = _vault(tmp_path)
    result = migrate_legacy_credentials(root)
    journal_path = root / "System/.dex/adoption/credential-journals" / f"{result.journal_id}.json"
    journal = credential_remediation.CredentialJournal.parse(journal_path.read_bytes())

    journal.begin_publication()
    assert journal.phase == "publishing"
    journal.begin_recovery()
    assert journal.phase == "recovery"
    journal.finish_recovery()
    assert journal.phase == "ready"
    journal.begin_publication()
    journal.complete()
    assert journal.phase == "completed"
    with pytest.raises(OSError, match="transition"):
        journal.begin_publication()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.pop("rewind"),
        lambda value: value.update(extra=True),
        lambda value: value["rewind"].update(extra=True),
        lambda value: value["rewind"].update(phase="rewound"),
        lambda value: value["postimages"].update(extra=True),
        lambda value: value["config"].update(extra=True),
    ],
)
def test_closed_credential_journal_rejects_missing_unknown_and_legacy_state(tmp_path, mutation):
    root = _vault(tmp_path)
    result = migrate_legacy_credentials(root)
    journal_path = root / "System/.dex/adoption/credential-journals" / f"{result.journal_id}.json"
    value = json.loads(journal_path.read_text())
    mutation(value)

    with pytest.raises(OSError):
        credential_remediation.CredentialJournal.parse(
            (json.dumps(value, sort_keys=True) + "\n").encode()
        )


def test_missing_rewind_guard_bypass_mutant_would_accept_corrupt_journal(tmp_path, monkeypatch):
    root = _vault(tmp_path)
    result = migrate_legacy_credentials(root)
    config = root / "System/integrations/config.yaml"
    migrated = config.read_bytes()
    journal_path = root / "System/.dex/adoption/credential-journals" / f"{result.journal_id}.json"
    value = json.loads(journal_path.read_text())
    value.pop("rewind")
    journal_path.write_text(json.dumps(value, sort_keys=True) + "\n")
    journal_path.chmod(0o600)

    with pytest.raises(OSError):
        rewind_credential_migration(root, result.journal_id)
    assert config.read_bytes() == migrated

    real_parse = credential_remediation.CredentialJournal.parse

    def permissive_parse(raw):
        legacy = json.loads(raw)
        legacy["rewind"] = {"phase": "ready"}
        return real_parse((json.dumps(legacy, sort_keys=True) + "\n").encode())

    monkeypatch.setattr(credential_remediation.CredentialJournal, "parse", permissive_parse)
    assert rewind_credential_migration(root, result.journal_id).state == "rewound"
    assert b"api_key: synthetic-old-key" in config.read_bytes()


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


def test_rewind_refuses_replaced_env_symlink_without_touching_its_target(tmp_path):
    root = _vault(tmp_path)
    (root / ".env").write_text("TODOIST_API_KEY=synthetic-old-key\n")
    (root / ".env").chmod(0o600)
    result = migrate_legacy_credentials(root)
    outside = tmp_path.parent / "outside-env"
    outside.write_text("outside-safe\n")
    (root / ".env").unlink()
    (root / ".env").symlink_to(outside)

    with pytest.raises(OSError):
        rewind_credential_migration(root, result.journal_id)
    assert (root / ".env").is_symlink()
    assert outside.read_text() == "outside-safe\n"
    config = (root / "System/integrations/config.yaml").read_bytes()
    assert b"api_key_env_var: TODOIST_API_KEY" in config
    assert b"api_key: synthetic-old-key" not in config


@pytest.mark.parametrize("race", ["modify", "replace", "hardlink", "symlink", "later-created"])
def test_rewind_never_deletes_or_overwrites_later_env_edits(tmp_path, race):
    root = _vault(tmp_path)
    result = migrate_legacy_credentials(root)
    env = root / ".env"
    migrated = env.read_bytes()
    outside = tmp_path.parent / f"outside-{race}"
    if race == "modify":
        env.write_bytes(b'TODOIST_API_KEY="later-user-value"\n')
        env.chmod(0o600)
    elif race == "replace":
        replacement = root / ".env.replacement"
        replacement.write_bytes(migrated)
        replacement.chmod(0o600)
        replacement.replace(env)
    elif race == "hardlink":
        outside.write_bytes(migrated)
        env.unlink()
        os.link(outside, env)
    elif race == "symlink":
        outside.write_bytes(migrated)
        env.unlink()
        env.symlink_to(outside)
    else:
        env.unlink()
        env.write_bytes(b'LATER_CREATED="must-survive"\n')
        env.chmod(0o600)

    with pytest.raises(OSError):
        rewind_credential_migration(root, result.journal_id)
    assert env.exists()
    config = (root / "System/integrations/config.yaml").read_bytes()
    assert b"api_key_env_var: TODOIST_API_KEY" in config
    assert b"api_key: synthetic-old-key" not in config


@pytest.mark.parametrize("boundary", ["before-env", "after-env", "before-config", "after-config"])
def test_rewind_fault_between_publications_restores_all_migrated_postimages(
    tmp_path, monkeypatch, boundary
):
    root = _vault(tmp_path)
    env = root / ".env"
    env.write_text("PRESERVED=before\n")
    env.chmod(0o600)
    result = migrate_legacy_credentials(root)
    config = root / "System/integrations/config.yaml"
    migrated_config = config.read_bytes()
    migrated_env = env.read_bytes()
    real_replace = credential_remediation._atomic_replace_at
    interrupted = False

    def fault(directory, name, data, mode, **kwargs):
        nonlocal interrupted
        selected = (boundary.endswith("env") and name == ".env") or (
            boundary.endswith("config") and name == "config.yaml"
        )
        if not selected or interrupted:
            return real_replace(directory, name, data, mode, **kwargs)
        interrupted = True
        if boundary.startswith("after"):
            real_replace(directory, name, data, mode, **kwargs)
        raise OSError(f"injected {boundary} rewind fault")

    monkeypatch.setattr(credential_remediation, "_atomic_replace_at", fault)
    with pytest.raises(OSError, match="injected"):
        rewind_credential_migration(root, result.journal_id)

    assert config.read_bytes() == migrated_config
    assert env.read_bytes() == migrated_env
    assert b"api_key: synthetic-old-key" not in migrated_config
    journal = root / "System/.dex/adoption/credential-journals" / f"{result.journal_id}.json"
    assert json.loads(journal.read_text())["rewind"] == {"phase": "ready"}


@pytest.mark.parametrize("phase", ["publishing", "recovery"])
def test_rewind_restart_resolves_explicit_interrupted_state_before_retry(tmp_path, phase):
    root = _vault(tmp_path)
    result = migrate_legacy_credentials(root)
    config = root / "System/integrations/config.yaml"
    migrated_config = config.read_bytes()
    journal = root / "System/.dex/adoption/credential-journals" / f"{result.journal_id}.json"
    record = json.loads(journal.read_text())
    config.write_bytes(bytes.fromhex(record["config"]["bytes_hex"]))
    config.chmod(record["config"]["mode"])
    record["rewind"] = {"phase": phase}
    journal.write_text(json.dumps(record, sort_keys=True) + "\n")
    journal.chmod(0o600)

    rewind = rewind_credential_migration(root, result.journal_id)

    assert rewind.state == "rewound"
    assert config.read_bytes() != migrated_config
    assert config.read_bytes() == bytes.fromhex(record["config"]["bytes_hex"])
    assert not (root / ".env").exists()


def test_rewind_prevalidation_guard_removal_recreates_rejected_raw_yaml_mutant(
    tmp_path, monkeypatch
):
    root = _vault(tmp_path)
    result = migrate_legacy_credentials(root)
    env = root / ".env"
    env.write_bytes(b'LATER_CREATED="must-survive"\n')
    env.chmod(0o600)

    monkeypatch.setattr(credential_remediation, "_require_image", lambda *args, **kwargs: None)
    rewind = rewind_credential_migration(root, result.journal_id)

    assert rewind.state == "rewound"
    assert b"api_key: synthetic-old-key" in (root / "System/integrations/config.yaml").read_bytes()
    assert not env.exists()
