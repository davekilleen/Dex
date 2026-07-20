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
    "raw_value",
    [
        "$abc123raw",  # starts with $ but is not a ${VAR} reference
        "{abc123raw",  # starts with { — old first-char exclusion skipped it
        "<abc123raw",  # starts with < but has no closing > (not a <placeholder>)
        "${CUSTOM_TODOIST_KEY}tail",  # ${VAR} prefix but a live raw tail follows
    ],
)
def test_bracket_or_dollar_prefixed_raw_value_is_flagged_not_masqueraded_as_reference(
    tmp_path, raw_value
):
    """A raw secret whose first byte is $/</{ must NOT dodge residual detection.

    The old detector excluded any value whose first char was in [\"$<{], so a live
    raw value starting with one of those bytes reported clean. A reference is now
    recognised ONLY by a full ${VAR}/<placeholder> template match, so these evasion
    shapes fail safe as residual.
    """
    root = _vault(tmp_path, b"todoist:\n  enabled: true\n  api_key_env_var: CUSTOM_TODOIST_KEY\n")
    mcp = root / ".mcp.json"
    mcp.write_text(json.dumps({"mcpServers": {"todoist": {"env": {"CUSTOM_TODOIST_KEY": raw_value}}}}))
    before = mcp.read_bytes()

    result = migrate_legacy_credentials(root)

    assert result.state == "partial"
    assert result.active_residual_state == "unrevoked-or-unclassified"
    assert mcp.read_bytes() == before  # .mcp.json remains report-only, never edited


def test_genuine_placeholder_and_var_references_stay_clean(tmp_path):
    """The structural detector must not raise false residuals on real reference configs."""
    root = _vault(tmp_path, b"todoist:\n  enabled: true\n  api_key_env_var: CUSTOM_TODOIST_KEY\n")
    mcp = root / ".mcp.json"
    for reference in ("${CUSTOM_TODOIST_KEY}", "<your-todoist-key>", "${TODOIST_API_KEY}", "<placeholder>"):
        mcp.write_text(json.dumps({"mcpServers": {"todoist": {"env": {"CUSTOM_TODOIST_KEY": reference}}}}))
        result = migrate_legacy_credentials(root)
        assert result.active_residual_state == "none", reference


def test_json_escaped_credential_key_name_with_raw_value_is_flagged(tmp_path):
    """The worse evasion: a JSON-escaped KEY name decodes to a real credential key, so a
    normal-shaped raw value under it stays live. A byte-level name match never saw the
    escaped key; structural JSON parsing decodes it and flags the raw value."""
    root = _vault(tmp_path, b"todoist:\n  enabled: true\n  api_key_env_var: TODOIST_API_KEY\n")
    mcp = root / ".mcp.json"
    # "TODOIST_API_KEY" decodes to "TODOIST_API_KEY"; value is a normal raw secret.
    mcp.write_text('{"mcpServers":{"todoist":{"env":{"\\u0054ODOIST_API_KEY":"abc123rawsecret"}}}}')
    before = mcp.read_bytes()

    result = migrate_legacy_credentials(root)

    assert result.state == "partial"
    assert result.active_residual_state == "unrevoked-or-unclassified"
    assert mcp.read_bytes() == before


def test_unparseable_active_mcp_config_fails_closed_as_residual(tmp_path):
    """A safe regular .mcp.json whose content is not valid JSON must fail closed
    (unknown residual), never be reported silently clean."""
    root = _vault(tmp_path, b"todoist:\n  enabled: true\n  api_key_env_var: TODOIST_API_KEY\n")
    (root / ".mcp.json").write_text('{ this is not valid json "TODOIST_API_KEY": rawsecret ')

    result = migrate_legacy_credentials(root)

    assert result.state == "partial"
    assert result.active_residual_state == "unrevoked-or-unclassified"


def test_end_to_end_reference_config_with_mcp_only_raw_secret_reports_residual(tmp_path):
    """Reviewer's demonstrated false-clean, end-to-end through the workflow: config in
    reference form + .env holding the current key + .mcp.json carrying a DIFFERENT raw
    secret under an escaped/$-prefixed shape. Status previously returned
    not-needed/none; it must now report a residual."""
    from core.utils.credential_workflow import run_credential_workflow

    root = _vault(tmp_path, b"todoist:\n  enabled: true\n  api_key_env_var: TODOIST_API_KEY\n")
    (root / ".env").write_text('TODOIST_API_KEY="current-live-key-value"\n')
    (root / ".env").chmod(0o600)
    # Two evasion shapes, values distinct from .env so the needle scanner cannot see them.
    (root / ".mcp.json").write_text(
        '{"mcpServers":{"todoist":{"env":{"\\u0054ODOIST_API_KEY":"escaped-key-raw-secret"}},'
        '"trello":{"env":{"TRELLO_API_KEY":"$dollar-prefixed-raw-secret"}}}}'
    )

    status = run_credential_workflow(root, "status")

    assert status["migration_state"] == "partial"
    assert status["active_residual_state"] == "unrevoked-or-unclassified"


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
    selected_target = "env" if boundary.endswith("env") else "config"
    selected_phase = "before-prepared-record" if boundary.startswith("before") else "after-readback"

    def interrupt(phase, target):
        if (phase, target) == (selected_phase, selected_target):
            raise interruption()

    monkeypatch.setattr(credential_remediation, "_migration_fault", interrupt)

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


def test_existing_env_requires_owner_only_authority_before_migration(tmp_path):
    root = _vault(tmp_path)
    env = root / ".env"
    env.write_text("PRESERVED=value\n")
    env.chmod(0o644)
    before = (root / "System/integrations/config.yaml").read_bytes()

    assert migrate_legacy_credentials(root).state == "refused"
    assert (root / "System/integrations/config.yaml").read_bytes() == before
    assert env.read_text() == "PRESERVED=value\n"


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
def test_other_unsafe_active_config_types_fail_closed(tmp_path, kind, monkeypatch):
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
        # AF_UNIX sun_path is capped near 104 bytes (macOS); pytest's absolute
        # tmp_path routinely exceeds it, so binding str(path) raised a spurious
        # "AF_UNIX path too long" env artifact unrelated to the guard under test.
        # Bind a short *relative* name from inside the vault root: the socket file
        # still lands at root/.mcp.json (what migration inspects) while sun_path
        # stays tiny. monkeypatch.chdir auto-restores cwd, keeping this hermetic.
        monkeypatch.chdir(root)
        listener.bind(path.name)
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
    ("security_state", "active_residual_state", "evidence_categories", "valid"),
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
    evidence_categories,
    valid,
):
    migration_state = "partial" if active_residual_state != "none" else "not-needed"

    def call():
        evidence = (
            CredentialEvidence(missing=evidence_categories)
            if security_state == "rotation-pending"
            else CredentialEvidence(
                unavailable=evidence_categories,
                unknown_causes=("unavailable",) if evidence_categories else (),
            )
        )
        return render_credential_status(
            migration_state,
            security_state,
            active_residual_state,
            "history-cleanup-pending",
            evidence,
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


def test_status_renderer_rejects_removed_tuple_evidence_compatibility():
    with pytest.raises(TypeError, match="typed evidence"):
        render_credential_status(
            "not-needed",
            "rotation-pending",
            "none",
            "history-clean",
            ("replacement-health",),  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("history_state", ["history-clean", "history-cleanup-pending"])
def test_only_unknown_history_accepts_uninspected_scopes(history_state):
    with pytest.raises(ValueError, match="uninspected scopes"):
        render_credential_status(
            "not-needed",
            "rotation-pending",
            "none",
            history_state,
            CredentialEvidence(missing=("replacement-health",)),
            ("tags",),
        )


def test_renderer_exact_copy_and_impossible_combinations():
    status = render_credential_status(
        "partial",
        "remediated",
        "proven-revoked",
        "history-cleanup-pending",
        CredentialEvidence(
            present=(
                "old-key-revocation",
                "replacement-present",
                "replacement-health",
                "active-copy",
                "provider-binding",
            )
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
        CredentialEvidence(),
    )
    assert active.security_and_current_config == (
        "An active `.mcp.json` value may still be usable. Security is not fixed; rotate/revoke it at the provider "
        "or remove it manually. Dex did not edit this file."
    )
    with pytest.raises(ValueError):
        render_credential_status(
            "migrated-local-config", "remediated", "proven-revoked", "history-clean",
            CredentialEvidence(present=("provider-binding",)), ()
        )
    with pytest.raises(ValueError):
        render_credential_status(
            "partial", "remediated", "unrevoked-or-unclassified", "history-clean", CredentialEvidence(), ()
        )
    with pytest.raises(ValueError, match="complete bound"):
        render_credential_status("not-needed", "remediated", "none", "history-clean", CredentialEvidence(), ())
    with pytest.raises(ValueError, match="complete bound"):
        render_credential_status(
            "not-needed", "remediated", "none", "history-clean",
            CredentialEvidence(present=("provider-binding",)), ()
        )
    with pytest.raises(ValueError):
        render_credential_status(
            "not-needed", "unknown", "none", "history-scope-unknown", CredentialEvidence(), ()
        )


def test_remediated_status_with_live_unrevoked_residual_is_refused_as_overclaim():
    """Paired inverse test for the over-claim guard (audit §5 P2 / guard 8).

    render_credential_status raises when a caller claims security="remediated"
    while a live `.mcp.json` residual is still "unrevoked-or-unclassified" — a
    "fixed, but a usable key may remain" contradiction the status vocabulary must
    never emit.

    Red-when-removed proof: the evidence below is *complete* remediation evidence
    (all five required categories present; no missing/unavailable/unknown causes),
    so the downstream "remediated security requires complete bound rotation and
    replacement evidence" guard does NOT fire on it. The ONLY thing that rejects
    this call is the over-claim guard itself. Delete
    `if security_state == "remediated" and active_residual_state ==
    "unrevoked-or-unclassified": raise ...` and this test fails (no exception is
    raised); restore it and the test passes.

    The prior coverage (`test_renderer_exact_copy_and_impossible_combinations`,
    the `CredentialEvidence()` case) could not prove this: with empty evidence the
    completeness guard also raised, so removing the over-claim guard left the test
    green. This is why a dedicated complete-evidence inverse test is required.

    render_credential_status / CredentialEvidence are the public construction path
    (both are module-level exports used throughout this file). Reaching this exact
    combination via the CLI workflow is defense-in-depth: inspect_credential_migration
    never yields security="remediated" alongside a live residual (a live residual
    forces rotation-pending/unknown), so the guard protects an input the CLI cannot
    currently produce — which is precisely why it needs its own test rather than
    an end-to-end one.
    """
    complete_remediation_evidence = CredentialEvidence(
        present=(
            "old-key-revocation",
            "replacement-present",
            "replacement-health",
            "active-copy",
            "provider-binding",
        )
    )
    with pytest.raises(ValueError, match="potentially usable residual"):
        render_credential_status(
            "partial",
            "remediated",
            "unrevoked-or-unclassified",
            "history-clean",
            complete_remediation_evidence,
            (),
        )


def test_journal_contains_exact_preimage_but_no_absolute_path(tmp_path):
    root = _vault(tmp_path)
    result = migrate_legacy_credentials(root)
    journal = root / "System/.dex/adoption/credential-journals" / f"{result.journal_id}.json"
    payload = json.loads(journal.read_text())
    assert bytes.fromhex(payload["config"]["bytes_hex"]).endswith(b"synthetic-old-key\r\n")
    assert set(payload) == credential_remediation.CredentialJournal.TOP_LEVEL_KEYS
    assert set(payload["postimages"]) == credential_remediation.CredentialJournal.POSTIMAGE_KEYS
    assert payload["migration"] == {"phase": "migrated"}
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
        lambda value: value.pop("migration"),
        lambda value: value.update(extra=True),
        lambda value: value["rewind"].update(extra=True),
        lambda value: value["rewind"].update(phase="rewound"),
        lambda value: value["migration"].update(phase="completed"),
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


def _only_journal(root: Path) -> tuple[str, Path]:
    paths = list((root / "System/.dex/adoption/credential-journals").glob("*.json"))
    assert len(paths) == 1
    return paths[0].stem, paths[0]


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires forked process-death injection")
@pytest.mark.parametrize(
    ("boundary", "target"),
    [
        ("before-prepared-record", "config"),
        ("after-prepared-record", "config"),
        ("after-replace", "config"),
        ("after-readback", "config"),
        ("between-targets", "env"),
        ("before-prepared-record", "env"),
        ("after-prepared-record", "env"),
        ("after-replace", "env"),
        ("after-readback", "env"),
        ("after-targets", "all"),
    ],
)
def test_restart_recovers_process_death_at_every_initial_publication_boundary(
    tmp_path, monkeypatch, boundary, target
):
    root = _vault(tmp_path)
    config = root / "System/integrations/config.yaml"
    before = config.read_bytes()

    def die(phase, selected_target):
        if (phase, selected_target) == (boundary, target):
            os._exit(91)

    monkeypatch.setattr(credential_remediation, "_migration_fault", die)
    child = os.fork()
    if child == 0:
        migrate_legacy_credentials(root)
        os._exit(92)
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 91
    monkeypatch.setattr(credential_remediation, "_migration_fault", lambda *_: None)
    journal_id, _ = _only_journal(root)

    assert rewind_credential_migration(root, journal_id).state == "rewound"
    assert config.read_bytes() == before
    assert not (root / ".env").exists()
    assert not list(root.glob(".env.*"))
    assert not list((root / "System/integrations").glob(".config.yaml.*"))


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires forked process-death injection")
@pytest.mark.parametrize(
    ("boundary", "target"),
    [
        ("rollback-after-phase", "all"),
        ("rollback-before-target", "env"),
        ("rollback-after-target", "env"),
        ("rollback-after-journal", "env"),
        ("rollback-before-target", "config"),
        ("rollback-after-replace", "config"),
        ("rollback-after-readback", "config"),
        ("rollback-after-target", "config"),
        ("rollback-after-journal", "config"),
    ],
)
def test_restart_recovers_process_death_throughout_initial_migration_rollback(
    tmp_path, monkeypatch, boundary, target
):
    root = _vault(tmp_path)
    config = root / "System/integrations/config.yaml"
    before = config.read_bytes()

    def stop_between(phase, selected_target):
        if (phase, selected_target) == ("between-targets", "env"):
            os._exit(93)

    monkeypatch.setattr(credential_remediation, "_migration_fault", stop_between)
    child = os.fork()
    if child == 0:
        migrate_legacy_credentials(root)
        os._exit(94)
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 93
    journal_id, _ = _only_journal(root)

    def die_during_rollback(phase, selected_target):
        if (phase, selected_target) == (boundary, target):
            os._exit(95)

    monkeypatch.setattr(credential_remediation, "_migration_fault", die_during_rollback)
    child = os.fork()
    if child == 0:
        rewind_credential_migration(root, journal_id)
        os._exit(96)
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 95
    monkeypatch.setattr(credential_remediation, "_migration_fault", lambda *_: None)

    assert rewind_credential_migration(root, journal_id).state == "rewound"
    assert config.read_bytes() == before
    assert not (root / ".env").exists()


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires forked process-death injection")
def test_restart_recovers_death_after_env_unlink_before_rollback_directory_fsync(
    tmp_path, monkeypatch
):
    root = _vault(tmp_path)
    before = (root / "System/integrations/config.yaml").read_bytes()

    def stop_after_env_readback(phase, target):
        if (phase, target) == ("after-readback", "env"):
            os._exit(97)

    monkeypatch.setattr(credential_remediation, "_migration_fault", stop_after_env_readback)
    child = os.fork()
    if child == 0:
        migrate_legacy_credentials(root)
        os._exit(98)
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 97
    journal_id, _ = _only_journal(root)

    def stop_after_unlink(phase, target):
        if (phase, target) == ("rollback-after-unlink", "env"):
            os._exit(99)

    monkeypatch.setattr(credential_remediation, "_migration_fault", stop_after_unlink)
    child = os.fork()
    if child == 0:
        rewind_credential_migration(root, journal_id)
        os._exit(100)
    _, status = os.waitpid(child, 0)
    assert os.waitstatus_to_exitcode(status) == 99
    monkeypatch.setattr(credential_remediation, "_migration_fault", lambda *_: None)

    assert rewind_credential_migration(root, journal_id).state == "rewound"
    assert (root / "System/integrations/config.yaml").read_bytes() == before
    assert not (root / ".env").exists()


def test_prepared_temporary_identity_is_not_named_postimage_authority(tmp_path, monkeypatch):
    root = _vault(tmp_path)

    def interrupt(phase, target):
        if (phase, target) == ("after-prepared-record", "env"):
            raise OSError("prepared-only")

    # Bypass caught rollback once so the exact prepared journal can be inspected.
    monkeypatch.setattr(credential_remediation, "_migration_fault", interrupt)
    monkeypatch.setattr(
        credential_remediation,
        "_recover_migration_journal",
        lambda *_: (_ for _ in ()).throw(OSError("hold")),
    )
    result = migrate_legacy_credentials(root)
    _, journal_path = _only_journal(root)
    journal = credential_remediation.CredentialJournal.parse(journal_path.read_bytes())
    assert result.state == "refused"
    assert journal.config.publication_state == "published"
    assert journal.env.publication_state == "prepared"
    assert not journal.fully_published
    assert journal.env.postimage.identity is None

    # This reproduces the removed model: temporary identity is falsely promoted
    # to named-target authority. Recovery then fails closed on the still-raw YAML.
    payload = json.loads(journal_path.read_text())
    postimages = payload["postimages"]
    postimages["env_publication_state"] = "published"
    postimages["env_identity"] = postimages["env_prepared_identity"]
    postimages["env_prepared_identity"] = None
    postimages["env_prepared_name"] = None
    journal_path.write_text(json.dumps(payload, sort_keys=True) + "\n")
    journal_path.chmod(0o600)
    with pytest.raises(OSError):
        rewind_credential_migration(root, result.journal_id)


def _migrated_journal_payload(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    root = _vault(tmp_path)
    result = migrate_legacy_credentials(root)
    path = root / "System/.dex/adoption/credential-journals" / f"{result.journal_id}.json"
    return path, json.loads(path.read_text())


def _parse_payload(payload: dict) -> credential_remediation.CredentialJournal:
    return credential_remediation.CredentialJournal.parse(
        (json.dumps(payload, sort_keys=True) + "\n").encode()
    )


# --- PublicationState cross-field invariants (CredentialTarget.__post_init__ /
# mark_prepared). These invariants are live at runtime through the journal-parse
# path but were previously unpaired: mutating them out left every test green. Each
# test below tampers a real migrated journal so that ONLY the named invariant gates
# the parse (migration phase set to "publishing" where a non-published target would
# otherwise trip the journal-level fully_published guard first), and each is proven
# red-when-removed. ---


def test_pending_target_with_publication_identity_is_rejected(tmp_path):
    """pending-no-authority: a pending target must carry no published identity."""
    _, payload = _migrated_journal_payload(tmp_path)
    payload["migration"]["phase"] = "publishing"
    # env is published with an identity; relabel it pending while keeping that identity.
    payload["postimages"]["env_publication_state"] = "pending"
    with pytest.raises(OSError, match="pending credential target has publication authority"):
        _parse_payload(payload)


def test_published_target_without_identity_is_rejected(tmp_path):
    """published-needs-identity: a published target must carry its postimage identity."""
    _, payload = _migrated_journal_payload(tmp_path)
    payload["postimages"]["env_identity"] = None
    with pytest.raises(OSError, match="published credential target has invalid authority"):
        _parse_payload(payload)


def test_prepared_target_missing_prepared_name_is_rejected(tmp_path):
    """prepared-needs-fields: a prepared target must carry name + prepared identity."""
    _, payload = _migrated_journal_payload(tmp_path)
    payload["migration"]["phase"] = "publishing"
    postimages = payload["postimages"]
    # Build a valid prepared config target, then drop its prepared_name.
    postimages["config_publication_state"] = "prepared"
    postimages["config_prepared_name"] = ".config.yaml." + "0" * 32
    postimages["config_prepared_identity"] = list(postimages["config_identity"])
    postimages["config_identity"] = None
    postimages["config_prepared_name"] = None
    with pytest.raises(OSError, match="prepared credential target has invalid authority"):
        _parse_payload(payload)


def test_mark_prepared_refuses_a_non_pending_target(tmp_path):
    """mark_prepared-needs-pending: a published target cannot transition to prepared."""
    path, _ = _migrated_journal_payload(tmp_path)
    journal = credential_remediation.CredentialJournal.parse(path.read_bytes())
    assert journal.config.publication_state == "published"
    # A valid temporary name + real metadata so ONLY the pending-state guard can gate.
    valid_temporary = ".config.yaml." + "0" * 32
    metadata = path.stat()
    with pytest.raises(OSError, match="invalid credential target prepare transition"):
        journal.config.mark_prepared(valid_temporary, metadata)


@pytest.mark.parametrize("section", ["config", "env"])
@pytest.mark.parametrize("field", ["mode", "uid", "gid"])
@pytest.mark.parametrize("malformed", ["1", True, False, 1.0, None, -1, 1 << 80])
def test_journal_rejects_noncanonical_preimage_numeric_fields(tmp_path, section, field, malformed):
    path, payload = _migrated_journal_payload(tmp_path)
    if payload[section] is None:
        postimages = payload["postimages"]
        payload[section] = {
            "bytes_hex": postimages["env_bytes_hex"],
            "sha256": postimages["env_sha256"],
            "mode": 0o600,
            "uid": postimages["env_uid"],
            "gid": postimages["env_gid"],
        }
    payload[section][field] = malformed
    with pytest.raises(OSError):
        credential_remediation.CredentialJournal.parse(
            (json.dumps(payload, sort_keys=True) + "\n").encode()
        )


@pytest.mark.parametrize("section", ["config", "env"])
@pytest.mark.parametrize("field", ["mode", "uid", "gid"])
@pytest.mark.parametrize("malformed", ["1", True, False, 1.0, None, -1, 1 << 80])
def test_journal_rejects_noncanonical_postimage_numeric_fields(tmp_path, section, field, malformed):
    _, payload = _migrated_journal_payload(tmp_path)
    payload["postimages"][f"{section}_{field}"] = malformed
    with pytest.raises(OSError):
        credential_remediation.CredentialJournal.parse(
            (json.dumps(payload, sort_keys=True) + "\n").encode()
        )


@pytest.mark.parametrize("index", range(7))
@pytest.mark.parametrize("malformed", ["1", True, False, 1.0, None, -1, 1 << 80])
def test_journal_rejects_noncanonical_identity_numeric_fields(tmp_path, index, malformed):
    _, payload = _migrated_journal_payload(tmp_path)
    payload["postimages"]["config_identity"][index] = malformed
    with pytest.raises(OSError):
        credential_remediation.CredentialJournal.parse(
            (json.dumps(payload, sort_keys=True) + "\n").encode()
        )


@pytest.mark.parametrize(
    ("field", "malformed"),
    [
        ("bytes_hex", None),
        ("bytes_hex", 17),
        ("bytes_hex", "0"),
        ("bytes_hex", "zz"),
        ("bytes_hex", "AA"),
        ("sha256", None),
        ("sha256", 17),
        ("sha256", "0" * 63),
        ("sha256", "A" * 64),
        ("sha256", "0" * 64),
    ],
)
def test_journal_rejects_noncanonical_preimage_bytes_and_hash(tmp_path, field, malformed):
    _, payload = _migrated_journal_payload(tmp_path)
    payload["config"][field] = malformed
    with pytest.raises(OSError):
        credential_remediation.CredentialJournal.parse(
            (json.dumps(payload, sort_keys=True) + "\n").encode()
        )


def test_permissive_numeric_parser_mutant_reaches_rewind(tmp_path, monkeypatch):
    root = _vault(tmp_path)
    result = migrate_legacy_credentials(root)
    path = root / "System/.dex/adoption/credential-journals" / f"{result.journal_id}.json"
    payload = json.loads(path.read_text())
    payload["postimages"]["config_identity"][1] = str(
        payload["postimages"]["config_identity"][1]
    )
    malformed = (json.dumps(payload, sort_keys=True) + "\n").encode()
    with pytest.raises(OSError):
        credential_remediation.CredentialJournal.parse(malformed)
    path.write_bytes(malformed)
    path.chmod(0o600)

    monkeypatch.setattr(
        credential_remediation,
        "_exact_int",
        lambda value, maximum=credential_remediation.MAX_IDENTITY_VALUE: int(value),
    )
    assert rewind_credential_migration(root, result.journal_id).state == "rewound"


def test_migration_consumes_the_public_typed_inspection_authority_once(tmp_path, monkeypatch):
    root = _vault(tmp_path)
    real_inspect = credential_remediation.inspect_credential_migration
    calls = []

    def inspect(vault_root):
        calls.append(vault_root)
        return real_inspect(vault_root)

    monkeypatch.setattr(credential_remediation, "inspect_credential_migration", inspect)

    assert migrate_legacy_credentials(root).state == "migrated-local-config"
    assert calls == [root]


def test_typed_inspection_snapshot_mappings_are_read_only(tmp_path):
    inspection = credential_remediation.inspect_credential_migration(_vault(tmp_path))
    with pytest.raises(TypeError):
        inspection.values["TODOIST_API_KEY"] = "changed"  # type: ignore[index]
    with pytest.raises(TypeError):
        inspection.refs["todoist.api_key"] = "changed"  # type: ignore[index]


@pytest.mark.parametrize("section", ["config", "env"])
@pytest.mark.parametrize(
    ("field", "malformed"),
    [
        ("bytes_hex", None),
        ("bytes_hex", 17),
        ("bytes_hex", "0"),
        ("bytes_hex", "zz"),
        ("bytes_hex", "AA"),
        ("sha256", None),
        ("sha256", 17),
        ("sha256", "0" * 63),
        ("sha256", "A" * 64),
        ("sha256", "0" * 64),
    ],
)
def test_journal_rejects_noncanonical_postimage_bytes_and_hash(tmp_path, section, field, malformed):
    _, payload = _migrated_journal_payload(tmp_path)
    payload["postimages"][f"{section}_{field}"] = malformed
    with pytest.raises(OSError):
        credential_remediation.CredentialJournal.parse(
            (json.dumps(payload, sort_keys=True) + "\n").encode()
        )


@pytest.mark.parametrize("section", ["config", "env"])
@pytest.mark.parametrize("index", range(7))
def test_every_named_identity_integer_requires_an_exact_json_integer(tmp_path, section, index):
    _, payload = _migrated_journal_payload(tmp_path)
    payload["postimages"][f"{section}_identity"][index] = str(
        payload["postimages"][f"{section}_identity"][index]
    )
    with pytest.raises(OSError):
        credential_remediation.CredentialJournal.parse(
            (json.dumps(payload, sort_keys=True) + "\n").encode()
        )


@pytest.mark.parametrize("index", range(7))
def test_every_prepared_identity_integer_requires_an_exact_json_integer(tmp_path, index):
    _, payload = _migrated_journal_payload(tmp_path)
    postimages = payload["postimages"]
    postimages["config_publication_state"] = "prepared"
    postimages["config_prepared_name"] = ".config.yaml." + "0" * 32
    postimages["config_prepared_identity"] = list(postimages["config_identity"])
    postimages["config_identity"] = None
    postimages["config_prepared_identity"][index] = str(
        postimages["config_prepared_identity"][index]
    )
    with pytest.raises(OSError):
        credential_remediation.CredentialJournal.parse(
            (json.dumps(payload, sort_keys=True) + "\n").encode()
        )


@pytest.mark.parametrize("mutation", ["directory-mode", "multiple-links", "wrong-size"])
def test_journal_rejects_impossible_identity_semantics(tmp_path, mutation):
    _, payload = _migrated_journal_payload(tmp_path)
    identity = payload["postimages"]["config_identity"]
    if mutation == "directory-mode":
        identity[2] = stat.S_IFDIR | 0o600
    elif mutation == "multiple-links":
        identity[3] = 2
    else:
        identity[6] += 1
    with pytest.raises(OSError):
        credential_remediation.CredentialJournal.parse(
            (json.dumps(payload, sort_keys=True) + "\n").encode()
        )
