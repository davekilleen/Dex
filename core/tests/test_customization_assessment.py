"""Read-only customization assessment journey and safety contracts."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from core.customization_migration import inventory as assessment_inventory
from core.customization_migration.model import (
    AssessmentGroup,
    CustomizationKind,
)
from core.customization_migration.references import extract_reference_edges
from core.customization_migration.report import assessment_report
from core.customization_migration.service import assess, assessment_to_dict
from core.lifecycle.catalog import canonical_catalog_bytes, with_catalog_identity
from core.lifecycle.inventory import InventoryEntry
from core.tests.lifecycle_test_helpers import SOURCE_COMMIT, write_file, write_manifest
from core.utils import doctor
from core.utils.trust_registry import TrustedMcpEntry, TrustedMcpRegistry

SHIPPED_SKILL = ".claude/skills/daily-plan/SKILL.md"
SHIPPED_BYTES = b"---\nname: daily-plan\ndescription: Daily plan\n---\nStock body.\n"


def _install_verified_catalog(vault: Path) -> None:
    write_file(vault, SHIPPED_SKILL, SHIPPED_BYTES)
    manifest = write_manifest(vault, [SHIPPED_SKILL])
    document = with_catalog_identity(
        {
            "catalog_version": 1,
            "release": {
                "version": "1.73.0",
                "channel": "release",
                "immutable_distribution_tag": "dist/release/v1.73.0-0123456",
                "source_commit": SOURCE_COMMIT,
                "manifest": {
                    "path": "System/.installed-files.manifest",
                    "sha256": hashlib.sha256(manifest).hexdigest(),
                },
            },
            "items": [
                {
                    "id": "daily-plan",
                    "kind": "skill",
                    "version": "1.0.0",
                    "files": [
                        {
                            "path": SHIPPED_SKILL,
                            "sha256": hashlib.sha256(SHIPPED_BYTES).hexdigest(),
                            "ownership_class": "brain",
                        }
                    ],
                    "dependencies": [],
                    "capabilities": [],
                    "rewind": {
                        "acknowledgement_required": True,
                        "token": "rewind:daily-plan@1.0.0",
                    },
                }
            ],
            "integrity": {"catalog_sha256": "0" * 64, "signatures": []},
        }
    )
    write_file(
        vault,
        "System/.release-catalog.json",
        canonical_catalog_bytes(document),
    )


def _linked_customized_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(
        vault,
        SHIPPED_SKILL,
        (
            b"---\nname: daily-plan\ndescription: Daily plan\n---\n"
            b"Run the local helper:\n\n```sh\npython3 .scripts/custom-plan.py\n```\n"
        ),
    )
    write_file(
        vault,
        ".scripts/custom-plan.py",
        (
            b"from pathlib import Path\n\n"
            b'FOLDER_MAP = "System/folder-paths.yaml"\n'
            b"print(Path(FOLDER_MAP))\n"
        ),
    )
    write_file(vault, "System/folder-paths.yaml", b'projects: "Work/Projects"\n')
    return vault


def _records_by_path(assessment):
    return {record.source_paths[0]: record for record in assessment.records}


def _groups_by_id(assessment):
    return {assignment.customization_id: assignment.group for assignment in assessment.groups}


def test_linked_triple_has_stable_records_edges_and_groups(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)

    first = assess(vault)
    second = assess(vault)

    assert len(first.records) == 3
    records = _records_by_path(first)
    assert set(records) == {
        SHIPPED_SKILL,
        ".scripts/custom-plan.py",
        "System/folder-paths.yaml",
    }
    assert records[SHIPPED_SKILL].kind is CustomizationKind.MODIFIED_SKILL
    assert records[".scripts/custom-plan.py"].kind is CustomizationKind.CUSTOM_SCRIPT
    assert records["System/folder-paths.yaml"].kind is CustomizationKind.CUSTOM_CONFIG

    edge_pairs = {(edge.source_path, edge.target, edge.edge_kind.value) for edge in first.edges}
    assert (
        SHIPPED_SKILL,
        ".scripts/custom-plan.py",
        "skill-to-script",
    ) in edge_pairs
    assert (
        ".scripts/custom-plan.py",
        "System/folder-paths.yaml",
        "literal-path",
    ) in edge_pairs
    assert (
        "System/folder-paths.yaml",
        "04-Projects",
        "literal-path",
    ) in edge_pairs

    groups = _groups_by_id(first)
    assert (
        groups[records[SHIPPED_SKILL].customization_id]
        is AssessmentGroup.UPDATE_REPLACEABLE_LOCATION
    )
    assert (
        groups[records[".scripts/custom-plan.py"].customization_id]
        is AssessmentGroup.UPDATE_REPLACEABLE_LOCATION
    )
    assert (
        groups[records["System/folder-paths.yaml"].customization_id]
        is AssessmentGroup.BLOCKED
    )
    assert [record.customization_id for record in first.records] == [
        record.customization_id for record in second.records
    ]
    assert [edge.edge_id for edge in first.edges] == [edge.edge_id for edge in second.edges]
    assert first.canonical_assessment_bytes() == second.canonical_assessment_bytes()


def test_missing_or_ambiguous_baseline_is_unknown_without_fabricated_records(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    write_file(
        vault,
        ".claude/skills-custom/my-skill/SKILL.md",
        b"---\nname: my-skill\ndescription: Mine\n---\n",
    )

    assessment = assess(vault)

    assert assessment.completeness == "UNKNOWN"
    assert assessment.verdict == "UNKNOWN"
    assert assessment.records == ()
    assert assessment.edges == ()
    assert assessment.groups == ()


def test_manifest_only_baseline_never_emits_zero_customization_all_clear(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_file(vault, SHIPPED_SKILL, b"locally modified without hash authority\n")
    write_manifest(vault, [SHIPPED_SKILL])

    assessment = assess(vault)
    emitted = assessment_to_dict(assessment)
    report = assessment_report(assessment)

    assert assessment.baseline_identity_state == "MANIFEST_ONLY"
    assert assessment.completeness == "UNKNOWN"
    assert assessment.verdict == "UNKNOWN"
    assert "baseline-not-verified" in assessment.incomplete_reasons
    assert "identity" not in emitted
    assert "records" not in emitted
    assert "customization_count" not in json.dumps(emitted, sort_keys=True)
    assert "counts" not in report
    assert "records" not in report
    assert report["incomplete_reasons"] == ["baseline-not-verified"]


def test_verified_partial_assessment_keeps_safe_inventory_and_exclusion_evidence(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, ".scripts/custom.py", b"VALUE = 1\n")
    external = tmp_path / "outside.py"
    external.write_text("PRIVATE = True\n", encoding="utf-8")
    link = vault / ".scripts" / "outside-link.py"
    link.symlink_to(external)

    assessment = assess(vault)
    emitted = assessment_to_dict(assessment)
    report = assessment_report(assessment)

    assert assessment.completeness == "UNKNOWN"
    assert assessment.verdict == "UNKNOWN"
    assert [record.source_paths for record in assessment.records] == [
        (".scripts/custom.py",)
    ]
    assert assessment.edges == ()
    assert len(assessment.groups) == 1
    assert emitted["partial"] is True
    assert emitted["identity"]["customization_count"] == 1
    assert emitted["records"][0]["source_paths"] == [".scripts/custom.py"]
    assert emitted["exclusions"] == [
        {
            "path": ".scripts/outside-link.py",
            "reason": "symlink-refused",
            "guidance": "Replace the link with a regular file inside the vault, then reassess.",
        }
    ]
    assert report["partial"] is True
    assert report["counts"]["total"] == 1
    assert report["exclusions"] == emitted["exclusions"]


def test_hard_denied_customization_is_restricted_without_content_leak(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    secret = b"PRIVATE KEY SENTINEL MUST NEVER APPEAR"
    write_file(vault, ".claude/skills-custom/secret/fake.pem", secret)

    discovery = assessment_inventory.discover(vault)
    assessment = assess(vault)

    record = _records_by_path(discovery)[".claude/skills-custom/secret/fake.pem"]
    assert record.live.model_readability == "restricted"
    assert record.live.sha256 is None
    assert record.live.byte_size is None
    assert _groups_by_id(discovery)[record.customization_id] is AssessmentGroup.BLOCKED
    assert assessment.records == ()
    encoded = json.dumps(assessment_to_dict(assessment), sort_keys=True).encode()
    assert secret not in encoded
    assert hashlib.sha256(secret).hexdigest().encode() not in encoded


def test_symlink_and_oversized_sources_are_refused_and_excluded_honestly(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    outside = tmp_path / "outside.py"
    outside.write_text("SENTINEL_FROM_OUTSIDE = True\n", encoding="utf-8")
    symlink = vault / ".claude/skills-custom/link.py"
    symlink.parent.mkdir(parents=True)
    symlink.symlink_to(outside)
    write_file(
        vault,
        ".claude/skills/oversize-custom/SKILL.md",
        b"x" * (1024 * 1024 + 1),
    )

    assessment = assess(vault)

    exclusions = {(item.path, item.reason) for item in assessment.exclusions}
    assert (".claude/skills-custom/link.py", "symlink-refused") in exclusions
    assert (
        ".claude/skills/oversize-custom/SKILL.md",
        "read-bound-exceeded",
    ) in exclusions
    assert assessment.completeness == "UNKNOWN"
    assert assessment.verdict == "UNKNOWN"
    assert b"SENTINEL_FROM_OUTSIDE" not in assessment.canonical_assessment_bytes()


def test_canonical_assessment_is_byte_identical_across_runs(tmp_path: Path) -> None:
    vault = _linked_customized_vault(tmp_path)

    first = assess(vault).canonical_assessment_bytes()
    second = assess(vault).canonical_assessment_bytes()

    assert first == second


def test_mcp_environment_records_names_only_and_never_values(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    secret_value = "VALUE_SENTINEL_MUST_NOT_LEAK"
    write_file(
        vault,
        ".mcp.json",
        json.dumps(
            {
                "mcpServers": {
                    "custom-local": {
                        "command": "python3",
                        "args": ["core/mcp-custom/local_server.py"],
                        "env": {"LOCAL_API_TOKEN": secret_value},
                    }
                }
            }
        ).encode(),
    )
    write_file(vault, "core/mcp-custom/local_server.py", b"TOOLS = ()\n")

    assessment = assess(vault)

    edges = {
        (edge.source_path, edge.target, edge.edge_kind.value)
        for edge in assessment.edges
    }
    assert (
        ".mcp.json",
        "core/mcp-custom/local_server.py",
        "mcp-to-server",
    ) in edges
    assert (".mcp.json", "env:LOCAL_API_TOKEN", "env-var-name") in edges
    assert secret_value.encode() not in assessment.canonical_assessment_bytes()


def test_assessment_outputs_never_leak_extracted_config_or_script_content(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    fake_key = "sk-FAKELEAK123456789"
    path_shaped_secrets = (
        "tenant/SUPERSECRET0123456789",
        ".scripts/xoxb-SLACKFAKE/inner",
    )
    write_file(
        vault,
        ".mcp.json",
        json.dumps(
            {
                "mcpServers": {
                    "custom-local": {
                        "command": "python3",
                        "args": ["core/mcp-custom/local_server.py"],
                        "env": {"LOCAL_API_TOKEN": fake_key},
                    }
                }
            }
        ).encode(),
    )
    write_file(vault, "core/mcp-custom/local_server.py", b"TOOLS = ()\n")
    write_file(
        vault,
        ".scripts/custom.py",
        (
            f'SECRET_LITERAL = "{fake_key}"\n'
            'HELPER = ".scripts/helper.py"\n'
            f"PATH_SECRETS = {path_shaped_secrets!r}\n"
        ).encode(),
    )
    write_file(
        vault,
        ".scripts/custom.cjs",
        (
            f"const first = {json.dumps(path_shaped_secrets[0])};\n"
            f"const second = {json.dumps(path_shaped_secrets[1])};\n"
        ).encode(),
    )
    write_file(
        vault,
        "System/user-profile.yaml",
        f"note: {path_shaped_secrets[0]}\n".encode(),
    )
    write_file(
        vault,
        ".claude/skills-custom/leak-check/SKILL.md",
        f"```sh\necho {path_shaped_secrets[1]}\n```\n".encode(),
    )
    write_file(vault, ".scripts/helper.py", b"VALUE = 1\n")
    monkeypatch.setattr(
        assessment_inventory,
        "_contains_embedded_secret",
        lambda _raw: False,
    )

    assessment = assess(vault)
    report = assessment_report(assessment)
    home = tmp_path / "home"
    home.mkdir()
    doctor_result = doctor._probe_customization_assessment(
        doctor.DoctorContext(
            vault_root=vault,
            repo_root=vault,
            home=home,
            now=datetime(2026, 7, 24, tzinfo=timezone.utc),
        )
    )
    serialized_outputs = (
        json.dumps(assessment_to_dict(assessment), sort_keys=True),
        json.dumps(report, sort_keys=True),
        json.dumps(doctor_result.structured_detail, sort_keys=True),
        assessment.canonical_assessment_bytes().decode("utf-8"),
    )

    assert all(fake_key not in encoded for encoded in serialized_outputs)
    assert all(fake_key not in edge.target for edge in assessment.edges)
    for secret in path_shaped_secrets:
        assert all(secret not in encoded for encoded in serialized_outputs)
        assert all(secret not in edge.target for edge in assessment.edges)


@pytest.mark.parametrize(
    "path",
    [
        ".claude/settings.json",
        ".claude/settings.local.json",
        "System/integrations/custom.yaml",
    ],
)
def test_credential_bearing_configs_are_restricted_before_reference_read(
    path: str,
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, path, b'helper: ".scripts/must-not-be-read.py"\n')
    original = assessment_inventory.bounded_read

    def refuse_sensitive_read(root, candidate, *, max_bytes):
        assert candidate != path
        return original(root, candidate, max_bytes=max_bytes)

    monkeypatch.setattr(assessment_inventory, "bounded_read", refuse_sensitive_read)

    discovery = assessment_inventory.discover(vault)
    record = _records_by_path(discovery)[path]

    assert record.live.model_readability == "restricted"
    assert not any(edge.source_path == path for edge in discovery.edges)


@pytest.mark.parametrize(
    "path",
    [
        ".claude/settings.json",
        ".claude/settings.local.json",
        "System/integrations/custom.yaml",
    ],
)
def test_reference_extractor_refuses_credential_bearing_configs(path: str) -> None:
    raw = b'{"token": "tenant/SUPERSECRET0123456789"}'

    assert extract_reference_edges(path, raw, skill_paths={}) == ()


def test_mcp_reference_extractor_emits_env_names_but_not_values() -> None:
    raw = json.dumps(
        {
            "mcpServers": {
                "local": {
                    "args": ["core/mcp-custom/local.py"],
                    "env": {"SAFE_TOKEN_NAME": "tenant/SUPERSECRET0123456789"},
                }
            }
        }
    ).encode()

    edges = extract_reference_edges(".mcp.json", raw, skill_paths={})

    assert {edge.target for edge in edges} == {
        "core/mcp-custom/local.py",
        "env:SAFE_TOKEN_NAME",
    }
    assert all("SUPERSECRET" not in edge.target for edge in edges)


def test_standalone_custom_script_is_not_silently_omitted(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, ".scripts/orphan.py", b"VALUE = 1\n")

    assessment = assess(vault)

    record = _records_by_path(assessment)[".scripts/orphan.py"]
    assert record.kind is CustomizationKind.CUSTOM_SCRIPT
    assert assessment.completeness == "OK"


def test_trusted_mcp_rehashes_live_bytes_and_blocks_stale_trust(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    path = "core/mcp-custom/local_server.py"
    write_file(vault, path, b"CHANGED = True\n")
    trusted_hash = hashlib.sha256(b"OLD = True\n").hexdigest()
    registry = TrustedMcpRegistry(
        entries={
            "custom-local": TrustedMcpEntry("custom-local", path, trusted_hash),
        },
        present=True,
    )
    monkeypatch.setattr(
        assessment_inventory,
        "_load_trusted_registry",
        lambda _root: registry,
        raising=False,
    )

    discovery = assessment_inventory.discover(vault)
    assessment = assess(vault)

    record = _records_by_path(discovery)[path]
    assert record.live.model_readability == "excluded"
    assert record.live.sha256 is None
    assert _groups_by_id(discovery)[record.customization_id] is AssessmentGroup.BLOCKED
    assert assessment.completeness == "UNKNOWN"
    assert trusted_hash.encode() not in assessment.canonical_assessment_bytes()


def test_trusted_mcp_never_leaks_registry_hash_for_hard_denied_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    path = ".claude/skills-custom/secret/fake.pem"
    write_file(vault, path, b"DENIED BYTES")
    registry_hash = "a" * 64
    registry = TrustedMcpRegistry(
        entries={
            "custom-secret": TrustedMcpEntry("custom-secret", path, registry_hash),
        },
        present=True,
    )
    monkeypatch.setattr(
        assessment_inventory,
        "_load_trusted_registry",
        lambda _root: registry,
        raising=False,
    )

    discovery = assessment_inventory.discover(vault)
    assessment = assess(vault)

    record = _records_by_path(discovery)[path]
    assert record.live.model_readability == "restricted"
    assert record.live.sha256 is None
    assert registry_hash.encode() not in assessment.canonical_assessment_bytes()


def test_embedded_secret_in_allowed_script_is_restricted_and_blocked(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    secret = b'API_KEY = "sk-live-SENTINEL0123456789"\n'
    write_file(vault, ".scripts/secret.py", secret)

    discovery = assessment_inventory.discover(vault)
    assessment = assess(vault)

    record = _records_by_path(discovery)[".scripts/secret.py"]
    assert record.live.model_readability == "restricted"
    assert record.live.sha256 is None
    assert _groups_by_id(discovery)[record.customization_id] is AssessmentGroup.BLOCKED
    assert _records_by_path(assessment)[".scripts/secret.py"] == record
    assert assessment.verdict == "OK"
    assert secret not in assessment.canonical_assessment_bytes()


def test_environment_variable_name_literal_is_not_treated_as_secret(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(
        vault,
        ".scripts/env_config.py",
        b'API_KEY_ENV_VAR = "TODOIST_API_KEY"\n',
    )

    assessment = assess(vault)

    record = _records_by_path(assessment)[".scripts/env_config.py"]
    assert record.live.model_readability == "readable"


def test_reference_through_symlinked_parent_is_missing_and_blocked(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "target.json").write_text("{}", encoding="utf-8")
    (vault / "linked").symlink_to(outside, target_is_directory=True)
    write_file(vault, ".scripts/custom.py", b'TARGET = "linked/target.json"\n')

    discovery = assessment_inventory.discover(vault)
    assessment = assess(vault)

    record = _records_by_path(discovery)[".scripts/custom.py"]
    assert _groups_by_id(discovery)[record.customization_id] is AssessmentGroup.BLOCKED
    assert [item.source_paths for item in assessment.records] == [
        (".scripts/custom.py",)
    ]
    assert len(assessment.edges) == 1
    assert _groups_by_id(assessment)[record.customization_id] is AssessmentGroup.BLOCKED
    assert assessment.to_dict()["partial"] is True


def test_remapped_edge_source_recomputes_its_stable_edge_id(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_file(
        vault,
        "Work/Projects/custom.py",
        b'TARGET = "System/folder-paths.yaml"\n',
    )
    write_file(vault, "System/folder-paths.yaml", b'projects: "Work/Projects"\n')

    class Baseline:
        identity_state = "VERIFIED"
        release_version = "1.73.0"
        errors = ()
        manifest_paths = frozenset()

        @staticmethod
        def expected_sha256(_path):
            return None

    entry = InventoryEntry(
        "Work/Projects/custom.py",
        "04-Projects/custom.py",
        "file",
        "brain",
        "brain-fixture",
        False,
        "stock-modified",
        False,
        "refuse",
        40,
        None,
    )

    class Inventory:
        baseline = Baseline()
        entries = (entry,)
        complete = True
        errors = ()
        unknown_paths = ()
        unproven_paths = ("Work/Projects/custom.py",)

    monkeypatch.setattr(assessment_inventory, "build_inventory", lambda *_args, **_kwargs: Inventory())
    monkeypatch.setattr(
        assessment_inventory,
        "_load_trusted_registry",
        lambda _root: TrustedMcpRegistry(entries={}, present=False),
        raising=False,
    )

    assessment = assess(vault)

    assert assessment.edges[0].source_path == "04-Projects/custom.py"
    assert assessment.records[0].evidence.reference_edge_ids == (
        assessment.edges[0].edge_id,
    )


def test_model_and_planning_import_without_third_party_packages() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            (
                "from core.customization_migration.model import AssessmentGroup;"
                "from core.customization_migration.planning import Disposition;"
                "assert AssessmentGroup.BLOCKED.value == 'blocked';"
                "assert Disposition.BLOCKED.value == 'blocked'"
            ),
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_dependency_tree_is_excluded_instead_of_becoming_customizations(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, "node_modules/example/index.js", b"module.exports = {};\n")

    assessment = assess(vault)

    assert "node_modules/example/index.js" not in _records_by_path(assessment)
    assert (
        "node_modules",
        "dependency-tree-excluded",
    ) in {(item.path, item.reason) for item in assessment.exclusions}
    assert assessment.completeness == "UNKNOWN"
    assert assessment.records == ()
    assert assessment.edges == ()
    assert assessment.groups == ()
    assert assessment.identity.inventory_path_count > 0
    assert assessment.identity.customization_count == 0
    assert assessment.identity.edge_count == 0
    assert assessment.to_dict()["partial"] is True


def test_remapped_edge_target_uses_same_canonical_path_as_its_record(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_file(
        vault,
        ".scripts/caller.py",
        b'TARGET = "Work/Projects/custom.py"\n',
    )
    write_file(vault, "Work/Projects/custom.py", b"VALUE = 1\n")

    class Baseline:
        identity_state = "VERIFIED"
        release_version = "1.73.0"
        errors = ()
        manifest_paths = frozenset()

        @staticmethod
        def expected_sha256(_path):
            return None

    entries = (
        InventoryEntry(
            ".scripts/caller.py",
            ".scripts/caller.py",
            "file",
            "brain",
            "brain-scripts",
            False,
            "unknown",
            False,
            "refuse",
            40,
            None,
        ),
        InventoryEntry(
            "Work/Projects/custom.py",
            "04-Projects/custom.py",
            "file",
            "brain",
            "brain-fixture",
            False,
            "stock-modified",
            False,
            "refuse",
            10,
            None,
        ),
    )

    class Inventory:
        baseline = Baseline()
        complete = True
        errors = ()
        unknown_paths = ()
        unproven_paths = (".scripts/caller.py",)

        def __init__(self):
            self.entries = entries

    monkeypatch.setattr(assessment_inventory, "build_inventory", lambda *_args, **_kwargs: Inventory())
    monkeypatch.setattr(
        assessment_inventory,
        "_load_trusted_registry",
        lambda _root: None,
    )

    assessment = assess(vault)

    assert any(
        edge.target == "04-Projects/custom.py" for edge in assessment.edges
    )
    assert "04-Projects/custom.py" in _records_by_path(assessment)


def test_missing_proved_target_edge_id_is_stable_across_folder_remap(
    tmp_path: Path,
) -> None:
    edge_ids: list[str] = []
    for name, target, folder_map in (
        ("default", "04-Projects/missing.md", None),
        ("remapped", "Work/Projects/missing.md", b'projects: "Work/Projects"\n'),
    ):
        vault = tmp_path / name
        vault.mkdir()
        _install_verified_catalog(vault)
        if folder_map is not None:
            write_file(vault, "System/folder-paths.yaml", folder_map)
        write_file(
            vault,
            ".claude/skills-custom/caller/SKILL.md",
            f"[missing]({target})\n".encode(),
        )

        assessment = assess(vault)
        edge = next(
            edge
            for edge in assessment.edges
            if edge.source_path == ".claude/skills-custom/caller/SKILL.md"
            and edge.edge_kind.value == "markdown-link"
        )
        assert edge.target == "04-Projects/missing.md"
        edge_ids.append(edge.edge_id)

    assert edge_ids[0] == edge_ids[1]


def test_inferred_missing_target_digest_is_stable_across_folder_remap(
    tmp_path: Path,
) -> None:
    edge_targets: list[str] = []
    edge_ids: list[str] = []
    for name, target, folder_map in (
        ("default", "04-Projects/missing.md", None),
        ("remapped", "Work/Projects/missing.md", b'projects: "Work/Projects"\n'),
    ):
        vault = tmp_path / name
        vault.mkdir()
        _install_verified_catalog(vault)
        if folder_map is not None:
            write_file(vault, "System/folder-paths.yaml", folder_map)
        write_file(vault, ".scripts/caller.py", f"TARGET = {target!r}\n".encode())

        assessment = assess(vault)
        edge = next(
            edge
            for edge in assessment.edges
            if edge.source_path == ".scripts/caller.py"
            and edge.edge_kind.value == "literal-path"
        )
        edge_targets.append(edge.target)
        edge_ids.append(edge.edge_id)

    expected = hashlib.sha256(b"04-Projects/missing.md").hexdigest()[:12]
    assert edge_targets == [f"unresolved:{expected}", f"unresolved:{expected}"]
    assert edge_ids[0] == edge_ids[1]


def test_reference_file_budget_stops_before_uninspected_candidate(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, ".scripts/a.py", b"VALUE=1\n")
    write_file(vault, ".scripts/b.py", b"VALUE=2\n")
    monkeypatch.setattr(assessment_inventory, "MAX_REFERENCE_FILES", 1)

    discovery = assessment_inventory.discover(vault)
    assessment = assess(vault)
    budget = next(
        item
        for item in discovery.exclusions
        if item.reason == "reference-budget-exhausted"
    )

    assert budget.uninspected_count == 1
    assert assessment.completeness == "UNKNOWN"
    assert [record.source_paths for record in assessment.records] == [
        (".scripts/a.py",)
    ]
    assert assessment.to_dict()["partial"] is True


def test_reference_byte_budget_allows_exact_boundary_then_stops(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, ".scripts/a.py", b"VALUE=1\n")
    write_file(vault, ".scripts/b.py", b"VALUE=2\n")
    monkeypatch.setattr(assessment_inventory, "MAX_TOTAL_SOURCE_BYTES", 8)

    discovery = assessment_inventory.discover(vault)
    budget = next(
        item
        for item in discovery.exclusions
        if item.reason == "reference-budget-exhausted"
    )

    assert budget.uninspected_count == 1
    assert _records_by_path(discovery)[".scripts/a.py"].live.byte_size == 8


def test_reference_byte_budget_counts_sources_rejected_after_read(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    secret = b'API_KEY = "sk-live-SENTINEL0123456789"\n'
    write_file(vault, ".scripts/a-secret.py", secret)
    write_file(vault, ".scripts/b.py", b"VALUE=2\n")
    monkeypatch.setattr(assessment_inventory, "MAX_TOTAL_SOURCE_BYTES", len(secret))

    discovery = assessment_inventory.discover(vault)
    budget = next(
        item
        for item in discovery.exclusions
        if item.reason == "reference-budget-exhausted"
    )

    assert budget.uninspected_count == 1


def test_reference_byte_budget_uses_live_descriptor_size(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, ".scripts/a.py", b"x")
    monkeypatch.setattr(assessment_inventory, "MAX_TOTAL_SOURCE_BYTES", 1)
    original = assessment_inventory.bounded_read
    grown = False

    def grow_before_assessment_read(root, path, *, max_bytes):
        nonlocal grown
        if path == ".scripts/a.py" and not grown:
            grown = True
            (root / path).write_bytes(b"xx")
        return original(root, path, max_bytes=max_bytes)

    monkeypatch.setattr(
        assessment_inventory,
        "bounded_read",
        grow_before_assessment_read,
    )

    discovery = assessment_inventory.discover(vault)
    budget = next(
        item
        for item in discovery.exclusions
        if item.reason == "reference-budget-exhausted"
    )

    assert budget.uninspected_count == 1


def test_reference_file_budget_counts_failed_read_attempts(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, ".scripts/a.py", b"VALUE=1\n")
    write_file(vault, ".scripts/b.py", b"VALUE=2\n")
    original = assessment_inventory.bounded_read

    def fail_custom_reads(root, path, *, max_bytes):
        if path.startswith(".scripts/"):
            raise assessment_inventory.FilesystemInspectionError("read failed")
        return original(root, path, max_bytes=max_bytes)

    monkeypatch.setattr(assessment_inventory, "MAX_REFERENCE_FILES", 1)
    monkeypatch.setattr(assessment_inventory, "bounded_read", fail_custom_reads)

    discovery = assessment_inventory.discover(vault)
    budget = next(
        item
        for item in discovery.exclusions
        if item.reason == "reference-budget-exhausted"
    )

    assert budget.uninspected_count == 1


def test_trusted_mcp_is_blocked_when_static_dependency_is_missing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    path = "core/mcp-custom/local_server.py"
    raw = b"import dependency_that_is_not_installed\n"
    write_file(vault, path, raw)
    registry = TrustedMcpRegistry(
        entries={
            "custom-local": TrustedMcpEntry(
                "custom-local",
                path,
                hashlib.sha256(raw).hexdigest(),
            ),
        },
        present=True,
    )
    monkeypatch.setattr(
        assessment_inventory,
        "_load_trusted_registry",
        lambda _root: registry,
    )

    assessment = assess(vault)

    record = _records_by_path(assessment)[path]
    assert record.live.model_readability == "hash-only"
    assert _groups_by_id(assessment)[record.customization_id] is AssessmentGroup.BLOCKED


@pytest.mark.parametrize(
    "raw",
    [
        b"export ACCESS_TOKEN=abcdefghijklmno123456\n",
        b'GITHUB_TOKEN = "gh' b'p_abcdefghijklmnopqrstuvwxyz123456"\n',
        b"AWS_ACCESS_KEY_ID=AK" b"IAABCDEFGHIJKLMNOP\n",
        b'AUTHORIZATION = "Bearer abcdefghijklmnopqrstuvwxyz123456"\n',
    ],
)
def test_common_embedded_secret_forms_are_restricted(
    raw: bytes,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, ".scripts/secret.sh", raw)

    discovery = assessment_inventory.discover(vault)
    record = _records_by_path(discovery)[".scripts/secret.sh"]

    assert record.live.model_readability == "restricted"
    assert record.live.sha256 is None


@pytest.mark.parametrize(
    ("literal", "target"),
    [
        ("/etc/passwd", "outside-vault:absolute"),
        ("../../outside/helper.py", "outside-vault:escape"),
    ],
)
def test_unsafe_reference_remains_visible_and_blocks_record(
    literal: str,
    target: str,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(
        vault,
        ".scripts/custom.py",
        f"TARGET = {literal!r}\n".encode(),
    )

    assessment = assess(vault)

    record = _records_by_path(assessment)[".scripts/custom.py"]
    assert any(edge.target == target for edge in assessment.edges)
    assert _groups_by_id(assessment)[record.customization_id] is AssessmentGroup.BLOCKED


def test_sibling_python_import_resolves_relative_to_custom_script(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, ".scripts/custom.py", b"import helper\n")
    write_file(vault, ".scripts/helper.py", b"VALUE = 1\n")

    assessment = assess(vault)

    record = _records_by_path(assessment)[".scripts/custom.py"]
    assert (
        _groups_by_id(assessment)[record.customization_id]
        is AssessmentGroup.UPDATE_REPLACEABLE_LOCATION
    )


def test_credential_named_path_is_restricted_before_reader_is_called(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, ".scripts/credentials.json", b'{"value":"not relevant"}\n')

    original = assessment_inventory.bounded_read

    def refuse_credential_read(root, path, *, max_bytes):
        assert "credential" not in path.lower()
        return original(root, path, max_bytes=max_bytes)

    monkeypatch.setattr(assessment_inventory, "bounded_read", refuse_credential_read)

    discovery = assessment_inventory.discover(vault)
    record = _records_by_path(discovery)[".scripts/credentials.json"]

    assert record.live.model_readability == "restricted"
    assert record.live.sha256 is None


def test_canonical_path_collision_is_excluded_without_raising(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_file(vault, "Work/Projects/one.py", b"ONE = 1\n")
    write_file(vault, "04-Projects/one.py", b"TWO = 2\n")

    class Baseline:
        identity_state = "VERIFIED"
        release_version = "1.73.0"
        errors = ()
        manifest_paths = frozenset()

        @staticmethod
        def expected_sha256(_path):
            return None

    entries = tuple(
        InventoryEntry(
            actual,
            "04-Projects/one.py",
            "file",
            None,
            None,
            False,
            "unknown",
            False,
            "refuse",
            8,
            None,
        )
        for actual in ("04-Projects/one.py", "Work/Projects/one.py")
    )

    class Inventory:
        baseline = Baseline()
        complete = False
        errors = ("folder map collision",)
        unknown_paths = tuple(entry.actual_path for entry in entries)
        unproven_paths = unknown_paths

        def __init__(self):
            self.entries = entries

    monkeypatch.setattr(
        assessment_inventory,
        "build_inventory",
        lambda *_args, **_kwargs: Inventory(),
    )
    monkeypatch.setattr(assessment_inventory, "_load_trusted_registry", lambda _root: None)

    assessment = assess(vault)

    assert assessment.records == ()
    assert assessment.completeness == "UNKNOWN"
    assert (
        "04-Projects/one.py",
        "canonical-path-collision",
    ) in {(item.path, item.reason) for item in assessment.exclusions}


def test_mcp_bare_command_is_not_copied_into_reference_output() -> None:
    edges = extract_reference_edges(
        ".mcp.json",
        b'{"mcpServers":{"local":{"command":"python3","args":[]}}}',
        skill_paths={},
    )

    assert edges == ()


def test_missing_relative_python_import_blocks_custom_script(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, ".scripts/custom.py", b"from . import missing_helper\n")

    assessment = assess(vault)

    record = _records_by_path(assessment)[".scripts/custom.py"]
    assert any(
        edge.target == "python-relative:1:missing_helper"
        for edge in assessment.edges
    )
    assert _groups_by_id(assessment)[record.customization_id] is AssessmentGroup.BLOCKED


def test_invalid_trust_registry_scope_is_visible_in_authority(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, "System/trusted-mcps.yaml", b"invalid: true\n")
    monkeypatch.setattr(
        assessment_inventory,
        "_load_trusted_registry",
        lambda _root: TrustedMcpRegistry(
            entries={},
            present=True,
            invalid_reason="invalid fixture",
        ),
    )

    assessment = assess(vault)

    assert assessment.completeness == "UNKNOWN"
    assert (
        "System/trusted-mcps.yaml",
        "invalid-trust-registry",
    ) in {(item.path, item.reason) for item in assessment.exclusions}


def test_incoming_reference_to_canonical_collision_is_blocked(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    write_file(
        vault,
        ".claude/skills-custom/caller/SKILL.md",
        b"[ambiguous](04-Projects/one.py)\n",
    )
    write_file(vault, "Work/Projects/one.py", b"ONE = 1\n")
    write_file(vault, "04-Projects/one.py", b"TWO = 2\n")

    class Baseline:
        identity_state = "VERIFIED"
        release_version = "1.73.0"
        errors = ()
        manifest_paths = frozenset()

        @staticmethod
        def expected_sha256(_path):
            return None

    entries = (
        InventoryEntry(
            ".claude/skills-custom/caller/SKILL.md",
            ".claude/skills-custom/caller/SKILL.md",
            "file",
            None,
            None,
            False,
            "unknown",
            False,
            "refuse",
            32,
            None,
        ),
        *tuple(
            InventoryEntry(
                actual,
                "04-Projects/one.py",
                "file",
                None,
                None,
                False,
                "unknown",
                False,
                "refuse",
                8,
                None,
            )
            for actual in ("04-Projects/one.py", "Work/Projects/one.py")
        ),
    )

    class Inventory:
        baseline = Baseline()
        complete = False
        errors = ("folder map collision",)
        unknown_paths = tuple(entry.actual_path for entry in entries)
        unproven_paths = unknown_paths

        def __init__(self):
            self.entries = entries

    monkeypatch.setattr(
        assessment_inventory,
        "build_inventory",
        lambda *_args, **_kwargs: Inventory(),
    )
    monkeypatch.setattr(assessment_inventory, "_load_trusted_registry", lambda _root: None)

    discovery = assessment_inventory.discover(vault)
    assessment = assess(vault)

    record = _records_by_path(discovery)[
        ".claude/skills-custom/caller/SKILL.md"
    ]
    assert _groups_by_id(discovery)[record.customization_id] is AssessmentGroup.BLOCKED
    assert [item.source_paths for item in assessment.records] == [
        (".claude/skills-custom/caller/SKILL.md",)
    ]
    assert len(assessment.edges) == 1
    assert _groups_by_id(assessment)[record.customization_id] is AssessmentGroup.BLOCKED
    assert assessment.to_dict()["partial"] is True


def test_multilevel_relative_python_import_resolves_from_parent_package(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, ".scripts/package/custom.py", b"from .. import helper\n")
    write_file(vault, ".scripts/helper.py", b"VALUE = 1\n")

    assessment = assess(vault)

    record = _records_by_path(assessment)[".scripts/package/custom.py"]
    assert any(
        edge.target == "python-relative:2:helper"
        for edge in assessment.edges
    )
    assert (
        _groups_by_id(assessment)[record.customization_id]
        is AssessmentGroup.UPDATE_REPLACEABLE_LOCATION
    )


def test_v0_vocabulary_is_mechanical_and_contains_no_reassurance_claims(
    tmp_path: Path,
) -> None:
    assessment = assess(_linked_customized_vault(tmp_path))
    report = assessment_report(assessment)
    skill = (
        Path(__file__).resolve().parents[2]
        / ".claude/skills/dex-doctor/SKILL.md"
    ).read_text(encoding="utf-8")
    section = skill.split("### Step 3b: Render the customization assessment", 1)[1].split(
        "### Step 3c:", 1
    )[0]
    rendered = json.dumps(
        {
            "model": assessment_to_dict(assessment),
            "report": report,
            "skill_section": section,
        },
        sort_keys=True,
    ).casefold()

    assert assessment.schema_version == 0
    assert set(AssessmentGroup) == {
        AssessmentGroup.UPDATE_REPLACEABLE_LOCATION,
        AssessmentGroup.UPDATE_UNTOUCHED_LOCATION,
        AssessmentGroup.NEEDS_INTERPRETATION,
        AssessmentGroup.BLOCKED,
    }
    for forbidden in ("already portable", "portable", "safe", "preserved"):
        assert forbidden not in rendered
