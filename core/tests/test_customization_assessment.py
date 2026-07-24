"""Read-only customization assessment journey and safety contracts."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.customization_migration import inventory as assessment_inventory
from core.customization_migration.model import (
    AssessmentGroup,
    CustomizationKind,
)
from core.customization_migration.references import extract_reference_edges
from core.customization_migration.service import assess, assessment_to_dict
from core.lifecycle.catalog import canonical_catalog_bytes, with_catalog_identity
from core.lifecycle.inventory import InventoryEntry
from core.tests.lifecycle_test_helpers import SOURCE_COMMIT, write_file, write_manifest
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
        "Work/Projects",
        "literal-path",
    ) in edge_pairs

    groups = _groups_by_id(first)
    assert groups[records[SHIPPED_SKILL].customization_id] is AssessmentGroup.NEEDS_INTERPRETATION
    assert (
        groups[records[".scripts/custom-plan.py"].customization_id]
        is AssessmentGroup.NEEDS_INTERPRETATION
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


def test_hard_denied_customization_is_restricted_without_content_leak(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    secret = b"PRIVATE KEY SENTINEL MUST NEVER APPEAR"
    write_file(vault, ".claude/skills-custom/secret/fake.pem", secret)

    assessment = assess(vault)

    record = _records_by_path(assessment)[".claude/skills-custom/secret/fake.pem"]
    assert record.live.model_readability == "restricted"
    assert record.live.sha256 is None
    assert record.live.byte_size is None
    assert _groups_by_id(assessment)[record.customization_id] is AssessmentGroup.BLOCKED
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

    assessment = assess(vault)

    record = _records_by_path(assessment)[path]
    assert record.live.model_readability == "excluded"
    assert record.live.sha256 is None
    assert _groups_by_id(assessment)[record.customization_id] is AssessmentGroup.BLOCKED
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

    assessment = assess(vault)

    record = _records_by_path(assessment)[path]
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

    assessment = assess(vault)

    record = _records_by_path(assessment)[".scripts/secret.py"]
    assert record.live.model_readability == "restricted"
    assert record.live.sha256 is None
    assert _groups_by_id(assessment)[record.customization_id] is AssessmentGroup.BLOCKED
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

    assessment = assess(vault)

    record = _records_by_path(assessment)[".scripts/custom.py"]
    assert _groups_by_id(assessment)[record.customization_id] is AssessmentGroup.BLOCKED


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
        b'GITHUB_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz123456"\n',
        b"AWS_ACCESS_KEY_ID=AKIAABCDEFGHIJKLMNOP\n",
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

    record = _records_by_path(assess(vault))[".scripts/secret.sh"]

    assert record.live.model_readability == "restricted"
    assert record.live.sha256 is None


@pytest.mark.parametrize(
    ("literal", "target"),
    [
        ("/etc/passwd", "unsafe-absolute:/etc/passwd"),
        ("../../outside/helper.py", "unsafe-escape:../../outside/helper.py"),
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
        is AssessmentGroup.NEEDS_INTERPRETATION
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

    record = _records_by_path(assess(vault))[".scripts/credentials.json"]

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


def test_mcp_bare_command_is_recorded_as_server_dependency() -> None:
    edges = extract_reference_edges(
        ".mcp.json",
        b'{"mcpServers":{"local":{"command":"python3","args":[]}}}',
        skill_paths={},
    )

    assert any(
        edge.target == "command:python3"
        and edge.edge_kind.value == "mcp-to-server"
        for edge in edges
    )


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

    assessment = assess(vault)

    record = _records_by_path(assessment)[
        ".claude/skills-custom/caller/SKILL.md"
    ]
    assert _groups_by_id(assessment)[record.customization_id] is AssessmentGroup.BLOCKED


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
        is AssessmentGroup.NEEDS_INTERPRETATION
    )
