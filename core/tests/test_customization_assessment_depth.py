"""Lane B depth contracts for the read-only customization assessment."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
from pathlib import Path

import pytest

from core.customization_migration import inventory as assessment_inventory
from core.customization_migration import references
from core.customization_migration.model import (
    AssessmentGroup,
    CustomizationKind,
    EdgeKind,
    LiveInfo,
    ReferenceConfidence,
    ReferenceEdge,
)
from core.customization_migration.references import extract_reference_edges
from core.customization_migration.report import assessment_report
from core.customization_migration.service import assess, assessment_to_dict
from core.tests.lifecycle_test_helpers import write_file
from core.tests.test_customization_assessment import (
    SHIPPED_BYTES,
    SHIPPED_SKILL,
    _install_verified_catalog,
)
from core.utils.trust_registry import TrustedMcpEntry, TrustedMcpRegistry
from scripts.benchmark_adoption_engine import run_benchmark


def _edge_set(value) -> set[tuple[str, str, str]]:
    return {
        (edge.source_path, edge.target, edge.edge_kind.value)
        for edge in value.edges
    }


def _record_kinds(value) -> dict[str, CustomizationKind]:
    return {
        record.source_paths[0]: record.kind
        for record in value.records
    }


def _group_set(value) -> set[tuple[str, str]]:
    paths_by_id = {
        record.customization_id: record.source_paths[0]
        for record in value.records
    }
    return {
        (paths_by_id[group.customization_id], group.group.value)
        for group in value.groups
    }


def test_live_info_executable_is_emitted_only_when_known() -> None:
    readable = LiveInfo("a" * 64, 7, "readable", executable=True)
    restricted = LiveInfo(None, None, "restricted")

    assert readable.to_dict()["executable"] is True
    assert "executable" not in restricted.to_dict()
    with pytest.raises(ValueError, match="restricted or missing"):
        LiveInfo(None, None, "restricted", executable=False)
    with pytest.raises(ValueError, match="boolean or null"):
        LiveInfo("a" * 64, 7, "readable", executable=1)


def test_package_symbolic_target_grammar_is_closed_and_bounded() -> None:
    edge = ReferenceEdge.create(
        ".scripts/requirements.txt",
        "package:@scope/example_pkg",
        EdgeKind.PACKAGE_DEPENDENCY,
        ReferenceConfidence.PROVED,
    )

    assert edge.target == "package:@scope/example_pkg"
    for invalid in (
        "package:",
        "package:name with spaces",
        "package:name\x00suffix",
        f"package:{'a' * 257}",
    ):
        with pytest.raises(ValueError):
            ReferenceEdge.create(
                ".scripts/requirements.txt",
                invalid,
                EdgeKind.PACKAGE_DEPENDENCY,
                ReferenceConfidence.PROVED,
            )


def test_shell_extraction_emits_static_paths_and_skips_interpolation() -> None:
    edges = extract_reference_edges(
        ".scripts/run.sh",
        (
            b'python3 "./helper.py"\n'
            b'node scripts/static.js\n'
            b'python3 "$ROOT/scripts/private.py"\n'
            b"python3 ${ROOT}/scripts/also-private.py\n"
            b"/daily-plan\n"
        ),
        skill_paths={"daily-plan": SHIPPED_SKILL},
    )

    assert {
        (edge.target, edge.edge_kind.value)
        for edge in edges
    } == {
        (".scripts/helper.py", "literal-path"),
        ("scripts/static.js", "literal-path"),
        (SHIPPED_SKILL, "instructions-to-skill"),
        ("env:ROOT", "env-var-name"),
    }


def test_plist_extraction_emits_only_vault_relative_launch_paths() -> None:
    raw = plistlib.dumps(
        {
            "ProgramArguments": [
                "/usr/bin/python3",
                "scripts/worker.py",
                "--flag",
                "System/config.json",
            ],
            "WorkingDirectory": "core/mcp-custom",
        }
    )

    edges = extract_reference_edges(
        "LaunchAgents/com.example.worker.plist",
        raw,
        skill_paths={},
    )

    assert {
        (edge.target, edge.edge_kind.value)
        for edge in edges
    } == {
        ("scripts/worker.py", "launch-agent-to-executable"),
        ("System/config.json", "launch-agent-to-executable"),
        ("core/mcp-custom", "launch-agent-to-executable"),
    }


def test_malformed_plist_becomes_read_error_exclusion(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, "LaunchAgents/broken.plist", b"not a plist")

    discovery = assessment_inventory.discover(vault)

    assert _record_kinds(discovery) == {
        "LaunchAgents/broken.plist": CustomizationKind.CUSTOM_CONFIG,
    }
    assert {
        (item.path, item.reason)
        for item in discovery.exclusions
    } == {("LaunchAgents/broken.plist", "read-error")}


def test_settings_hooks_emit_existing_paths_without_leaking_command_canary(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    canary = "CANARY-tenant/SUPERSECRET0123456789"
    write_file(vault, ".claude/hooks/run.sh", b"#!/bin/sh\nexit 0\n")
    write_file(
        vault,
        ".claude/settings.json",
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        f"{canary} .claude/hooks/run.sh "
                                        "missing/not-real.sh"
                                    ),
                                }
                            ]
                        }
                    ]
                },
                "env": {"SECRET": canary},
            }
        ).encode(),
    )

    discovery = assessment_inventory.discover(vault)
    assessment = assess(vault)
    outputs = (
        discovery.records,
        discovery.edges,
        discovery.exclusions,
        assessment_to_dict(assessment),
        assessment_report(assessment),
        assessment.canonical_assessment_bytes(),
    )

    assert (
        ".claude/settings.json",
        ".claude/hooks/run.sh",
        "hook-to-script",
    ) in _edge_set(discovery)
    assert not any(edge.target == "missing/not-real.sh" for edge in discovery.edges)
    assert canary not in repr(outputs)
    settings = next(
        record
        for record in discovery.records
        if record.source_paths == (".claude/settings.json",)
    )
    assert settings.live.model_readability == "restricted"
    assert settings.live.executable is None


def test_deeply_nested_settings_json_becomes_read_error_exclusion(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    raw = b'{"nested":' * 40_000 + b"null" + b"}" * 40_000
    write_file(vault, ".claude/settings.json", raw)

    discovery = assessment_inventory.discover(vault)

    assert (".claude/settings.json", "read-error") in {
        (item.path, item.reason)
        for item in discovery.exclusions
    }


def test_deep_settings_hooks_walker_becomes_read_error_exclusion(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, ".claude/settings.json", b'{"hooks":{"custom":true}}')
    nested: object = {"command": ".claude/hooks/run.sh"}
    for _ in range(5_000):
        nested = {"nested": nested}
    payload = {"hooks": nested}
    monkeypatch.setattr(
        references,
        "_load_json",
        lambda _raw, _description: payload,
    )

    discovery = assessment_inventory.discover(vault)

    assert (".claude/settings.json", "read-error") in {
        (item.path, item.reason)
        for item in discovery.exclusions
    }


def test_deeply_nested_mcp_json_becomes_read_error_exclusion(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    raw = b'{"nested":' * 40_000 + b"null" + b"}" * 40_000
    write_file(vault, ".mcp.json", raw)

    discovery = assessment_inventory.discover(vault)

    assert (".mcp.json", "read-error") in {
        (item.path, item.reason)
        for item in discovery.exclusions
    }


@pytest.mark.parametrize(
    ("source_path", "raw", "targets"),
    [
        (
            ".scripts/requirements.txt",
            (
                b"# comment\n"
                b"requests[security]>=2.31  # pinned elsewhere\n"
                b"my_pkg~=1.2\n"
                b"-r other.txt\n"
            ),
            {"package:my_pkg", "package:requests"},
        ),
        (
            ".scripts/package.json",
            json.dumps(
                {
                    "dependencies": {"@scope/tool": "^1.0.0"},
                    "devDependencies": {"test_helper": "2.0.0"},
                    "scripts": {"secret": "tenant/SUPERSECRET0123456789"},
                }
            ).encode(),
            {"package:@scope/tool", "package:test_helper"},
        ),
    ],
)
def test_package_manifests_emit_names_only(
    source_path: str,
    raw: bytes,
    targets: set[str],
) -> None:
    edges = extract_reference_edges(source_path, raw, skill_paths={})

    assert {edge.target for edge in edges} == targets
    assert {edge.edge_kind for edge in edges} == {EdgeKind.PACKAGE_DEPENDENCY}
    assert "SUPERSECRET" not in repr(edges)


def test_requirements_skips_overlong_name_and_keeps_other_packages(
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    overlong_name = "a" * 300
    write_file(
        vault,
        ".scripts/requirements.txt",
        f"{overlong_name}==1.0\nrequests>=2\n".encode(),
    )

    discovery = assessment_inventory.discover(vault)

    package_targets = {
        edge.target
        for edge in discovery.edges
        if edge.edge_kind is EdgeKind.PACKAGE_DEPENDENCY
    }
    assert package_targets == {"package:requests"}


def test_readable_files_capture_executable_mode(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, ".scripts/run.sh", b"#!/bin/sh\nexit 0\n")
    os.chmod(vault / ".scripts/run.sh", 0o755)
    write_file(vault, ".scripts/plain.py", b"VALUE = 1\n")

    discovery = assessment_inventory.discover(vault)
    records = {
        record.source_paths[0]: record
        for record in discovery.records
    }

    assert records[".scripts/run.sh"].live.executable is True
    assert records[".scripts/plain.py"].live.executable is False


def test_nested_git_is_reported_at_embedded_repository_root(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, "tools/vendor/.git/config", b"[core]\n")
    write_file(vault, "tools/vendor/run.py", b"VALUE = 1\n")

    discovery = assessment_inventory.discover(vault)

    assert {
        (item.path, item.reason)
        for item in discovery.exclusions
    } == {("tools/vendor", "embedded-repository")}
    assert "tools/vendor/.git/config" not in _record_kinds(discovery)


def test_light_corpus_exact_shape(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, "CLAUDE-custom.md", b"# My instructions\n")

    assessment = assess(vault)

    assert _record_kinds(assessment) == {
        "CLAUDE-custom.md": CustomizationKind.CUSTOM_INSTRUCTIONS,
    }
    assert _edge_set(assessment) == set()
    assert _group_set(assessment) == {
        ("CLAUDE-custom.md", "update-untouched-location"),
    }
    assert assessment.exclusions == ()
    assert assessment.completeness == "OK"
    assert assessment.verdict == "OK"


def test_medium_corpus_exact_shape(monkeypatch, tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(
        vault,
        SHIPPED_SKILL,
        SHIPPED_BYTES + b"\n```sh\n.scripts/custom.sh\n```\n",
    )
    write_file(
        vault,
        ".scripts/custom.sh",
        b"#!/bin/sh\ncat System/folder-paths.yaml\n",
    )
    write_file(vault, "System/folder-paths.yaml", b'projects: "Work/Projects"\n')
    server = b"TOOLS = ()\n"
    write_file(vault, "core/mcp-custom/server.py", server)
    write_file(
        vault,
        ".mcp.json",
        b'{"mcpServers":{"custom-local":{"args":["core/mcp-custom/server.py"]}}}',
    )

    monkeypatch.setattr(
        assessment_inventory,
        "_load_trusted_registry",
        lambda _root: TrustedMcpRegistry(
            entries={
                "custom-local": TrustedMcpEntry(
                    "custom-local",
                    "core/mcp-custom/server.py",
                    hashlib.sha256(server).hexdigest(),
                )
            },
            present=True,
        ),
    )

    assessment = assess(vault)

    assert _record_kinds(assessment) == {
        ".mcp.json": CustomizationKind.CUSTOM_MCP,
        ".scripts/custom.sh": CustomizationKind.CUSTOM_SCRIPT,
        SHIPPED_SKILL: CustomizationKind.MODIFIED_SKILL,
        "System/folder-paths.yaml": CustomizationKind.CUSTOM_CONFIG,
        "core/mcp-custom/server.py": CustomizationKind.CUSTOM_MCP,
    }
    assert _edge_set(assessment) == {
        (".mcp.json", "core/mcp-custom/server.py", "mcp-to-server"),
        (".scripts/custom.sh", "System/folder-paths.yaml", "literal-path"),
        (SHIPPED_SKILL, ".scripts/custom.sh", "skill-to-script"),
        ("System/folder-paths.yaml", "04-Projects", "literal-path"),
    }
    assert _group_set(assessment) == {
        (".mcp.json", "update-untouched-location"),
        (".scripts/custom.sh", "update-replaceable-location"),
        (SHIPPED_SKILL, "update-replaceable-location"),
        ("System/folder-paths.yaml", "blocked"),
        ("core/mcp-custom/server.py", "update-untouched-location"),
    }
    assert assessment.exclusions == ()
    assert assessment.completeness == "OK"


def test_extreme_corpus_exact_exclusions_and_unknown_honesty(
    monkeypatch,
    tmp_path: Path,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    _install_verified_catalog(vault)
    write_file(vault, "CLAUDE-custom.md", b"# Extreme\n")
    write_file(
        vault,
        SHIPPED_SKILL,
        SHIPPED_BYTES + b"\n```sh\n.scripts/a-run.sh\n```\n",
    )
    write_file(
        vault,
        ".scripts/a-run.sh",
        b"scripts/worker.py\ncat System/folder-paths.yaml\n",
    )
    write_file(vault, "scripts/worker.py", b"VALUE = 1\n")
    write_file(vault, ".scripts/requirements.txt", b"requests>=2\n")
    write_file(vault, "System/folder-paths.yaml", b'projects: "Work/Projects"\n')
    server = b"TOOLS = ()\n"
    write_file(vault, "core/mcp-custom/server.py", server)
    write_file(
        vault,
        ".mcp.json",
        b'{"mcpServers":{"custom-local":{"args":["core/mcp-custom/server.py"]}}}',
    )
    write_file(
        vault,
        "LaunchAgents/worker.plist",
        plistlib.dumps({"ProgramArguments": ["scripts/worker.py"]}),
    )
    write_file(vault, "tools/vendor/.git/config", b"[core]\n")
    write_file(
        vault,
        ".claude/settings.json",
        b'{"hooks":{"Stop":[{"hooks":[{"command":"scripts/worker.py"}]}]}}',
    )
    write_file(
        vault,
        ".scripts/secret.py",
        b'API_KEY = "sk-live-SENTINEL0123456789"\n',
    )
    monkeypatch.setattr(
        assessment_inventory,
        "_load_trusted_registry",
        lambda _root: TrustedMcpRegistry(
            entries={
                "custom-local": TrustedMcpEntry(
                    "custom-local",
                    "core/mcp-custom/server.py",
                    hashlib.sha256(server).hexdigest(),
                )
            },
            present=True,
        ),
    )
    monkeypatch.setattr(assessment_inventory, "MAX_REFERENCE_FILES", 9)

    discovery = assessment_inventory.discover(vault)
    assessment = assess(vault)

    assert _record_kinds(discovery) == {
        ".claude/settings.json": CustomizationKind.CUSTOM_CONFIG,
        SHIPPED_SKILL: CustomizationKind.MODIFIED_SKILL,
        ".mcp.json": CustomizationKind.CUSTOM_MCP,
        ".scripts/a-run.sh": CustomizationKind.CUSTOM_SCRIPT,
        ".scripts/requirements.txt": CustomizationKind.UNKNOWN_ADDITION,
        ".scripts/secret.py": CustomizationKind.CUSTOM_SCRIPT,
        "CLAUDE-custom.md": CustomizationKind.CUSTOM_INSTRUCTIONS,
        "LaunchAgents/worker.plist": CustomizationKind.CUSTOM_CONFIG,
        "System/folder-paths.yaml": CustomizationKind.CUSTOM_CONFIG,
        "core/mcp-custom/server.py": CustomizationKind.CUSTOM_MCP,
    }
    assert _edge_set(discovery) == {
        (
            ".claude/settings.json",
            "scripts/worker.py",
            "hook-to-script",
        ),
        (
            ".scripts/a-run.sh",
            "scripts/worker.py",
            "literal-path",
        ),
        (
            ".scripts/a-run.sh",
            "System/folder-paths.yaml",
            "literal-path",
        ),
        (
            ".scripts/requirements.txt",
            "package:requests",
            "package-dependency",
        ),
        (
            "LaunchAgents/worker.plist",
            "scripts/worker.py",
            "launch-agent-to-executable",
        ),
        (
            SHIPPED_SKILL,
            ".scripts/a-run.sh",
            "skill-to-script",
        ),
        (
            ".mcp.json",
            "core/mcp-custom/server.py",
            "mcp-to-server",
        ),
        (
            "System/folder-paths.yaml",
            "04-Projects",
            "literal-path",
        ),
    }
    assert _group_set(discovery) == {
        (".claude/settings.json", "blocked"),
        (SHIPPED_SKILL, "update-replaceable-location"),
        (".mcp.json", "update-untouched-location"),
        (".scripts/a-run.sh", "update-replaceable-location"),
        (".scripts/requirements.txt", "update-replaceable-location"),
        (".scripts/secret.py", "blocked"),
        ("CLAUDE-custom.md", "update-untouched-location"),
        ("LaunchAgents/worker.plist", "needs-interpretation"),
        ("System/folder-paths.yaml", "blocked"),
        ("core/mcp-custom/server.py", "update-untouched-location"),
    }
    assert {
        (item.path, item.reason, item.uninspected_count)
        for item in discovery.exclusions
    } == {
        (".claude/settings.json", "restricted", None),
        (".scripts/secret.py", "embedded-secret", None),
        ("tools/vendor", "embedded-repository", None),
        ("scripts/worker.py", "reference-budget-exhausted", 1),
    }
    assert assessment.completeness == "UNKNOWN"
    assert assessment.verdict == "UNKNOWN"
    assert len(assessment.records) == 9
    assert len(assessment.edges) == 7
    assert len(assessment.groups) == 9
    assert assessment.identity.customization_count == 9
    assert assessment.identity.edge_count == 7
    assert "assessment-exclusions" in assessment.incomplete_reasons
    assert assessment.to_dict()["partial"] is True


def test_adoption_benchmark_reports_customization_assessment_stage() -> None:
    result = run_benchmark(1)

    assert "customization_assessment" in result["seconds"]
    assert result["seconds"]["total_measured"] == round(
        sum(
            seconds
            for stage, seconds in result["seconds"].items()
            if stage != "total_measured"
        ),
        6,
    )
