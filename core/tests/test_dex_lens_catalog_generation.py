"""Dex Lens catalog producer gates."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

from core.lens_catalog_discovery import discover_active_skills, discover_mcp_servers
from core.lens_catalog_sources import SkillSourceError, resolve_skill_source

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts/generate-dex-lens-catalog.py"
REAL_REGISTRY = REPO_ROOT / "core/lens-catalog/registry.json"
RELEASED_LENS_SCHEMA = REPO_ROOT / "core/lens-catalog/schemas/dex-lens-catalogue-v2.schema.json"
PROPOSED_SIGNIFICANT_LENS_SCHEMA = (
    REPO_ROOT
    / "core/tests/fixtures/dex-lens-catalogue-significant-preview.schema.json"
)
ENRICHED_EXAMPLE = REPO_ROOT / "docs/examples/dex-lens-catalog-enriched-preview.json"
# Lens v0.1.9 producer bytes plus the host-adapter pattern
# `^[a-z][a-z0-9-]{1,80}$`, which is required so two-character harness
# ids (`bb`, `pi`) can appear in compatibility.host_adapters.
LENS_PRODUCER_SCHEMA_SHA256 = (
    "030a3bdb4471e7bc57753fbb9bef3a12511bc08de726e5614f94da706de9fe0d"
)
PROPOSED_SIGNIFICANT_LENS_SCHEMA_SHA256 = (
    "c44e1802911e8db1d7c86f5cf8fc79a0ea4bacb1c9b2c0b1d1e483fed27e4ca7"
)

WAVE3_IDS = (
    "account-plan",
    "call-prep",
    "deal-review",
    "pipeline-health",
    "pipeline-sync",
    "customer-intel",
    "feature-decision",
    "roadmap",
    "audience-intel",
    "campaign-review",
    "content-calendar",
    "messaging-audit",
    "architecture-decision",
    "incident-review",
    "tech-debt",
    "board-prep",
    "close-status",
    "variance-analysis",
    "expansion-opportunities",
    "health-score",
    "renewal-prep",
    "metrics-review",
    "process-audit",
    "design-review",
    "design-system-audit",
    "career-setup",
    "career-coach",
    "resume-builder",
    "quarter-plan",
    "quarter-review",
)
WAVE3_ROOM_IDS = frozenset(
    {"career-setup", "career-coach", "resume-builder", "quarter-plan", "quarter-review"}
)
WAVE3_ACTIVE_IDS = frozenset({"pipeline-sync"})
WAVE3_LIFECYCLE_IDS = frozenset(WAVE3_IDS) - WAVE3_ROOM_IDS - WAVE3_ACTIVE_IDS
CANONICAL_JOB_IDS = (
    "capture-without-friction",
    "start-each-day-focused",
    "track-people-and-relationships",
    "manage-tasks-reliably",
    "reflect-and-improve-continuously",
    "keep-projects-on-track",
    "track-career-growth",
    "evolve-the-system-itself",
)


def _signed_payload(envelope: dict) -> str:
    return json.dumps(
        {"metadata": envelope["metadata"], "catalogue": envelope["catalogue"]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _skill(root: Path, skill_id: str, description: str = "Use when planning a day.") -> bytes:
    content = f"---\nname: {skill_id}\ndescription: {description}\n---\n\n# {skill_id}\n"
    path = root / ".claude/skills" / skill_id / "SKILL.md"
    _write(path, content)
    return content.encode("utf-8")


def _registry(root: Path) -> None:
    skill_bytes = _skill(root, "daily-plan")
    _write(root / "core/tests/test_commitments_skill.py", "# fixture test evidence\n")
    _write(root / "docs/backup-restore.md", "# fixture documentation evidence\n")
    schema_source = REPO_ROOT / "core/lens-catalog/schemas/dex-lens-catalogue-v2.schema.json"
    _write(
        root / "core/lens-catalog/schemas/dex-lens-catalogue-v2.schema.json",
        schema_source.read_text(encoding="utf-8"),
    )
    _write(
        root / "CHANGELOG.md",
        "# Changelog\n\n## [1.94.0] - Test release\n\n## [1.80.0] - Older release\n",
    )
    _write(root / "package.json", '{"version":"1.94.0"}\n')
    _write(
        root / "core/harnesses/registry.json",
        (REPO_ROOT / "core/harnesses/registry.json").read_text(encoding="utf-8"),
    )
    _write(
        root / "core/harnesses/portability.json",
        (REPO_ROOT / "core/harnesses/portability.json").read_text(encoding="utf-8"),
    )
    _write(
        root / "core/lens-catalog/registry.json",
        json.dumps(
            {
                "registry_version": 1,
                "catalog_version": 7,
                "jobs": [
                    {
                        "job_id": job_id,
                        "title": job_id.replace("-", " ").title(),
                        "description": f"Exercise the documented {job_id.replace('-', ' ')} job.",
                    }
                    for job_id in CANONICAL_JOB_IDS
                ],
                "entries": [
                    {
                        "id": "daily-plan",
                        "capability_class": "active-skill",
                        "impact_tier": "core",
                        "availability": "active",
                        "source": {
                            "kind": "active-skill",
                            "path": ".claude/skills/daily-plan/SKILL.md",
                            "sha256": hashlib.sha256(skill_bytes).hexdigest(),
                            "byte_size": len(skill_bytes),
                        },
                        "value": "Helps a person choose what matters today before work scatters.",
                        "jobs_served": ["start-each-day-focused"],
                        "foundation_capabilities": [
                            "context-orientation",
                            "scoped-agency-human-control",
                        ],
                        "prerequisites": ["A task list or calendar the host can inspect."],
                        "trade_offs": ["The plan is only as current as the source material."],
                        "evidence": [
                            {
                                "kind": "test",
                                "coverage": "behavioral",
                                "reference": "core/tests/test_commitments_skill.py",
                                "summary": "Daily planning skill coverage exercises task creation boundaries.",
                            }
                        ],
                        "brief": {
                            "goal": "Create a daily planning routine that combines commitments and calendar shape.",
                            "method_outline": [
                                "Read today's meetings and open tasks.",
                                "Choose a short focus list that fits the available time.",
                            ],
                            "verification_checklist": ["The output names a bounded set of actions for today."],
                            "rollback_advice": "Remove the routine or disable the command; it does not need to touch user content.",
                        },
                        "compatibility": {
                            "host_requirements": ["skills-directory"],
                            "needs_hooks": False,
                            "needs_mcp": True,
                            "platforms": ["macos", "linux", "windows"],
                        },
                        "docs_url": "https://github.com/davekilleen/Dex",
                        "since_release": "1.80.0",
                        "changed_in": [],
                    }
                ],
            },
            indent=2,
        )
        + "\n",
    )


def _generate(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--release-root",
            str(root),
            "--output-dir",
            str(root / "dist"),
            "--issued-at",
            "2026-08-11T12:00:00Z",
            *extra,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _generate_enriched(output_dir: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--release-root",
            str(REPO_ROOT),
            "--output-dir",
            str(output_dir),
            "--issued-at",
            "2026-08-25T12:00:00Z",
            "--enriched-preview",
            *extra,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )


def _generate_enriched_release(
    output_dir: Path, signing_key_b64: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--release-root",
            str(REPO_ROOT),
            "--output-dir",
            str(output_dir),
            "--issued-at",
            "2026-08-26T10:00:00Z",
            "--enriched",
            "--sign",
            "--signing-key-env",
            "DEX_LENS_TEST_KEY",
            "--key-id",
            "dex-core-lens-test",
        ],
        cwd=REPO_ROOT,
        env={"DEX_LENS_TEST_KEY": signing_key_b64},
        capture_output=True,
        text=True,
    )


def _load_generator_module():
    spec = importlib.util.spec_from_file_location("dex_lens_catalog_generator", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generates_canonical_unsigned_lens_catalog_payload(tmp_path: Path) -> None:
    _registry(tmp_path)

    result = _generate(tmp_path)

    assert result.returncode == 0, result.stderr
    envelope = json.loads((tmp_path / "dist/dex-lens-catalog-v1.94.0.json").read_text())
    assert set(envelope) == {"metadata", "catalogue", "signature"}
    assert envelope["signature"] == ""
    assert envelope["metadata"]["contract_version"] == "dex-lens-catalogue-v2"
    assert envelope["metadata"]["catalog_version"] == 7
    assert envelope["metadata"]["producer"] == "Dex Core release pipeline v1.94.0"
    assert envelope["metadata"]["core_release"] == "v1.94.0"
    assert envelope["metadata"]["key_id"] == "dex-core-lens-1"
    assert envelope["metadata"]["produced_at"] == "2026-08-11T12:00:00Z"
    assert tuple(job["job_id"] for job in envelope["catalogue"]["jobs_taxonomy"]) == CANONICAL_JOB_IDS
    capability = envelope["catalogue"]["capabilities"][0]
    assert "capability_class" not in capability
    assert "impact_tier" not in capability
    assert "availability" not in capability
    assert capability["capability_id"] == "daily-plan"
    assert capability["title"] == "Daily Plan"
    assert capability["summary"] == "Use when planning a day."
    assert capability["value"] == "Helps a person choose what matters today before work scatters."
    assert capability["summary"] != capability["value"]
    assert capability["prerequisites"] == ["A task list or calendar the host can inspect."]
    assert capability["trade_offs"] == ["The plan is only as current as the source material."]
    assert capability["docs_url"] == "https://github.com/davekilleen/Dex"
    assert capability["since_release"] == "1.80.0"
    assert capability["changed_in"] == []
    assert capability["release_provenance"] == "core-release"
    assert capability["evidence"][0]["level"] == "verified"
    assert capability["compatibility"]["minimum_lens_contract"] == "0.1.0"
    assert capability["compatibility"]["platforms"] == ["macos", "linux", "windows"]
    assert capability["compatibility"]["needs_hooks"] is False
    assert capability["compatibility"]["needs_mcp"] is True
    assert capability["compatibility"]["host_requirements"] == ["skills-directory"]
    assert capability["compatibility"]["host_adapters"] == [
        "agent-plugin",
        "bb",
        "chatgpt-work",
        "claude-code",
        "codex",
        "copilot-cli",
        "cowork",
        "cursor",
        "gemini-cli",
        "pi",
    ]
    assert "Needs hooks" not in " ".join(capability["compatibility"]["limitations"])
    assert capability["portable_brief"]["goal"].startswith("Create a daily planning routine")
    assert "adaptation_notes" not in capability["portable_brief"]
    assert capability["portable_brief"]["method_outline"] == [
        "Read today's meetings and open tasks.",
        "Choose a short focus list that fits the available time.",
    ]
    assert capability["portable_brief"]["verification_checklist"] == [
        "The output names a bounded set of actions for today."
    ]
    assert capability["portable_brief"]["rollback_advice"].startswith("Remove the routine")
    assert envelope["catalogue"]["portable_brief"]["format"] == "markdown"
    assert (tmp_path / "dist/dex-lens-catalog-latest.json").read_text() == json.dumps(
        envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ) + "\n"
    assert (tmp_path / "dist/dex-lens-catalog-v1.94.0.json.sha256").read_text().strip()


def test_claude_only_skill_catalogues_only_claude_plugin_hosts(tmp_path: Path) -> None:
    _registry(tmp_path)
    portability_path = tmp_path / "core/harnesses/portability.json"
    portability = json.loads(portability_path.read_text())
    portability["skills"]["daily-plan"]["classification"] = "claude-only"
    _write(portability_path, json.dumps(portability))

    result = _generate(tmp_path)

    assert result.returncode == 0, result.stderr
    envelope = json.loads((tmp_path / "dist/dex-lens-catalog-latest.json").read_text())
    capability = envelope["catalogue"]["capabilities"][0]
    assert capability["compatibility"]["host_adapters"] == ["claude-code", "cowork"]


def test_generator_rejects_unknown_fields_in_registry(tmp_path: Path) -> None:
    _registry(tmp_path)
    data = json.loads((tmp_path / "core/lens-catalog/registry.json").read_text())
    data["entries"][0]["capabilities"] = []
    _write(tmp_path / "core/lens-catalog/registry.json", json.dumps(data))

    result = _generate(tmp_path)

    assert result.returncode == 1
    assert "unknown capabilities" in result.stderr


def test_generator_rejects_non_kebab_host_requirement_ids(tmp_path: Path) -> None:
    _registry(tmp_path)
    registry_path = tmp_path / "core/lens-catalog/registry.json"
    data = json.loads(registry_path.read_text())
    data["entries"][0]["compatibility"]["host_requirements"] = [
        "quarter_goals-room-enabled"
    ]
    _write(registry_path, json.dumps(data))

    result = _generate(tmp_path)

    assert result.returncode == 1
    assert "host_requirements item must be kebab-case" in result.stderr


def test_generator_rejects_duplicate_host_requirement_ids(tmp_path: Path) -> None:
    _registry(tmp_path)
    registry_path = tmp_path / "core/lens-catalog/registry.json"
    data = json.loads(registry_path.read_text())
    data["entries"][0]["compatibility"]["host_requirements"] = [
        "skills-directory",
        "skills-directory",
    ]
    _write(registry_path, json.dumps(data))

    result = _generate(tmp_path)

    assert result.returncode == 1
    assert "host_requirements contains duplicate Lens catalogue ids" in result.stderr


def test_generator_rejects_unknown_job_and_foundation_references(tmp_path: Path) -> None:
    _registry(tmp_path)
    data = json.loads((tmp_path / "core/lens-catalog/registry.json").read_text())
    data["entries"][0]["jobs_served"] = ["missing-job"]
    data["entries"][0]["foundation_capabilities"] = ["invented-foundation"]
    _write(tmp_path / "core/lens-catalog/registry.json", json.dumps(data))

    result = _generate(tmp_path)

    assert result.returncode == 1
    assert "unknown job reference" in result.stderr


def test_generator_requires_the_documented_eight_job_taxonomy(tmp_path: Path) -> None:
    _registry(tmp_path)
    registry_path = tmp_path / "core/lens-catalog/registry.json"
    data = json.loads(registry_path.read_text())
    data["jobs"].append(
        {
            "job_id": "invented-ninth-job",
            "title": "Invented ninth job",
            "description": "This taxonomy must not drift from the documented eight.",
        }
    )
    _write(registry_path, json.dumps(data))

    result = _generate(tmp_path)

    assert result.returncode == 1
    assert "must contain the documented eight Jobs to Be Done" in result.stderr


def test_generator_rejects_discovered_active_skill_without_annotation(tmp_path: Path) -> None:
    _registry(tmp_path)
    _skill(tmp_path, "unannotated-skill")

    result = _generate(tmp_path)

    assert result.returncode == 1
    assert "active skill annotations do not match discovery" in result.stderr
    assert "missing annotations: unannotated-skill" in result.stderr


def test_generator_rejects_stale_active_annotation(tmp_path: Path) -> None:
    _registry(tmp_path)
    registry_path = tmp_path / "core/lens-catalog/registry.json"
    data = json.loads(registry_path.read_text())
    data["entries"][0]["id"] = "stale-skill"
    _write(registry_path, json.dumps(data))

    result = _generate(tmp_path)

    assert result.returncode == 1
    assert "active skill annotations do not match discovery" in result.stderr
    assert "stale annotations: stale-skill" in result.stderr


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("availability", "maybe", "availability must be active or dormant"),
        ("capability_class", "workflow", "capability_class must be active-skill"),
        ("impact_tier", "massive", "impact_tier must be core, high, medium, or niche"),
    ],
)
def test_generator_rejects_unknown_internal_classification(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    _registry(tmp_path)
    registry_path = tmp_path / "core/lens-catalog/registry.json"
    data = json.loads(registry_path.read_text())
    data["entries"][0][field] = value
    _write(registry_path, json.dumps(data))

    result = _generate(tmp_path)

    assert result.returncode == 1
    assert message in result.stderr


def test_generator_ignores_unannotated_vendored_skills(tmp_path: Path) -> None:
    _registry(tmp_path)
    _skill(tmp_path, "anthropic-pdf", description="Vendored third-party PDF skill.")

    result = _generate(tmp_path)

    assert result.returncode == 0, result.stderr
    envelope = json.loads((tmp_path / "dist/dex-lens-catalog-latest.json").read_text())
    assert [entry["capability_id"] for entry in envelope["catalogue"]["capabilities"]] == ["daily-plan"]


def test_generator_orders_active_entries_by_discovery_not_registry(tmp_path: Path) -> None:
    _registry(tmp_path)
    alpha_bytes = _skill(tmp_path, "alpha-skill", description="Use alpha safely.")
    portability_path = tmp_path / "core/harnesses/portability.json"
    portability = json.loads(portability_path.read_text())
    portability["skills"]["alpha-skill"] = {
        "classification": "portable",
        "reason": "Synthetic portable skill used to prove deterministic ordering.",
    }
    _write(portability_path, json.dumps(portability))
    registry_path = tmp_path / "core/lens-catalog/registry.json"
    data = json.loads(registry_path.read_text())
    alpha = json.loads(json.dumps(data["entries"][0]))
    alpha["id"] = "alpha-skill"
    alpha["source"] = {
        "kind": "active-skill",
        "path": ".claude/skills/alpha-skill/SKILL.md",
        "sha256": hashlib.sha256(alpha_bytes).hexdigest(),
        "byte_size": len(alpha_bytes),
    }
    alpha["evidence"][0]["reference"] = ".claude/skills/alpha-skill/SKILL.md"
    alpha["evidence"][0].pop("coverage", None)
    alpha["evidence"][0]["kind"] = "runtime-path"
    data["entries"].append(alpha)
    _write(registry_path, json.dumps(data))

    result = _generate(tmp_path)

    assert result.returncode == 0, result.stderr
    envelope = json.loads((tmp_path / "dist/dex-lens-catalog-latest.json").read_text())
    assert [entry["capability_id"] for entry in envelope["catalogue"]["capabilities"]] == [
        "alpha-skill",
        "daily-plan",
    ]


def test_enriched_preview_requires_a_lens_0_1_9_schema(tmp_path: Path) -> None:
    missing = _generate_enriched(tmp_path / "missing")

    assert missing.returncode == 1
    assert "requires --lens-schema" in missing.stderr
    assert _lens_artifacts(tmp_path) == []


def test_released_lens_0_1_9_schema_still_accepts_the_legacy_phase1_shape(
    tmp_path: Path, signing_key_b64: str
) -> None:
    _registry(tmp_path)
    result = _generate_signed(tmp_path, signing_key_b64)

    assert result.returncode == 0, result.stderr
    envelope = json.loads((tmp_path / "dist/dex-lens-catalog-latest.json").read_text())
    schema = json.loads(RELEASED_LENS_SCHEMA.read_text())
    jsonschema.Draft202012Validator(schema).validate(envelope)


def test_enriched_preview_refuses_signing_and_release_names(tmp_path: Path) -> None:
    result = _generate_enriched(
        tmp_path / "dist", "--lens-schema", str(RELEASED_LENS_SCHEMA), "--sign"
    )

    assert result.returncode == 1
    assert "enriched previews cannot be signed or published" in result.stderr
    assert not (tmp_path / "dist").exists()


@pytest.mark.parametrize(
    "signing_options",
    [
        ("--test-deterministic-signature",),
        ("--signing-key-env", "UNUSED_PREVIEW_KEY"),
        ("--key-id", "preview-key-must-not-be-overridden"),
    ],
)
def test_enriched_preview_refuses_every_signing_option(
    tmp_path: Path, signing_options: tuple[str, ...]
) -> None:
    result = _generate_enriched(
        tmp_path / "dist",
        "--lens-schema",
        str(RELEASED_LENS_SCHEMA),
        *signing_options,
    )

    assert result.returncode == 1
    assert "enriched previews cannot use signing options" in result.stderr
    assert not (tmp_path / "dist").exists()


@pytest.mark.parametrize(
    "abbreviated_options",
    [
        ("--test",),
        ("--test-deterministic-signatur",),
        ("--signing-key-e", "UNUSED_PREVIEW_KEY"),
        ("--key", "preview-key-must-not-be-overridden"),
    ],
)
def test_enriched_preview_refuses_abbreviated_signing_options(
    tmp_path: Path, abbreviated_options: tuple[str, ...]
) -> None:
    result = _generate_enriched(
        tmp_path / "dist",
        "--lens-schema",
        str(RELEASED_LENS_SCHEMA),
        *abbreviated_options,
    )

    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr
    assert not (tmp_path / "dist").exists()


def test_enriched_preview_rejects_an_id_already_used_by_a_skill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    generator = _load_generator_module()
    registry = json.loads((REPO_ROOT / "core/lens-catalog/enriched-registry.json").read_text())
    collision = json.loads(json.dumps(registry["entries"][0]))
    collision["id"] = "daily-plan"
    registry["entries"].append(collision)
    registry_path = tmp_path / "enriched-registry.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(generator, "ENRICHED_REGISTRY_PATH", registry_path)

    with pytest.raises(generator.LensCatalogError, match="duplicates existing capability id 'daily-plan'"):
        generator._build_enriched_catalogue(REPO_ROOT)


@pytest.mark.parametrize(
    ("discovery_name", "capability_class"),
    [
        ("discover_mcp_servers", "mcp-server"),
        ("discover_scheduled_automations", "scheduled-automation"),
        ("discover_system_engines", "system-engine"),
    ],
)
def test_enriched_preview_rejects_duplicate_discovered_capability_ids(
    monkeypatch: pytest.MonkeyPatch,
    discovery_name: str,
    capability_class: str,
) -> None:
    generator = _load_generator_module()
    discover = getattr(generator, discovery_name)
    candidate = discover(REPO_ROOT)[0]
    monkeypatch.setattr(generator, discovery_name, lambda _root: (candidate, candidate))

    with pytest.raises(
        generator.LensCatalogError,
        match=rf"{capability_class} discovery produced duplicate capability id {candidate.capability_id!r}",
    ):
        generator._build_enriched_catalogue(REPO_ROOT)


def test_vendored_lens_schema_matches_pinned_producer_bytes() -> None:
    schema_bytes = RELEASED_LENS_SCHEMA.read_bytes()
    schema = json.loads(schema_bytes)

    assert hashlib.sha256(schema_bytes).hexdigest() == LENS_PRODUCER_SCHEMA_SHA256
    assert schema["x-dex-lens-minimum-version"] == "0.1.9"
    assert [
        branch["$ref"].rsplit("/", 1)[1]
        for branch in schema["$defs"]["CatalogueCapabilityEntryV2"]["oneOf"]
    ] == [
        "LegacySkillCapabilityEntryV2",
        "ActiveSkillCapabilityEntryV2",
        "McpServerCapabilityEntryV2",
        "ScheduledAutomationCapabilityEntryV2",
        "SystemEngineCapabilityEntryV2",
    ]


def test_released_enriched_schema_declares_capability_id_uniqueness() -> None:
    schema = json.loads(RELEASED_LENS_SCHEMA.read_text(encoding="utf-8"))
    capabilities = schema["$defs"]["CatalogueV2"]["properties"]["capabilities"]

    assert capabilities["uniqueItems"] is True
    assert capabilities["x-dex-lens-unique-by"] == "capability_id"


def test_enriched_catalogue_emits_every_discovered_mcp_tool_in_canonical_order() -> None:
    generator = _load_generator_module()

    _catalog_version, _release_version, catalogue = generator._build_enriched_catalogue(
        REPO_ROOT
    )

    emitted = {
        entry["capability_id"]: entry
        for entry in catalogue["capabilities"]
        if entry["capability_class"] == "mcp-server"
    }
    discovered = {
        candidate.capability_id: candidate for candidate in discover_mcp_servers(REPO_ROOT)
    }
    assert set(emitted) == set(discovered)
    for capability_id, candidate in discovered.items():
        assert emitted[capability_id]["tools"] == candidate.tools
        assert emitted[capability_id]["tool_inventory"] == "complete"
        assert emitted[capability_id]["tool_count"] == len(candidate.tools)
        assert set(emitted[capability_id]["example_tools"]) <= set(candidate.tools)

    assert len(emitted["dex-work-mcp"]["tools"]) == 50
    assert len(emitted["dex-career-mcp"]["tools"]) == 8


def test_enriched_catalogue_emits_the_validated_significant_family_contract() -> None:
    generator = _load_generator_module()
    significant = json.loads(
        (REPO_ROOT / "core/lens-catalog/significant-capabilities.json").read_text(
            encoding="utf-8"
        )
    )

    _catalog_version, _release_version, catalogue = generator._build_enriched_catalogue(
        REPO_ROOT
    )

    assert catalogue["capability_aliases"] == significant["capability_aliases"]
    assert catalogue["capability_families"] == significant["families"]
    assert len(catalogue["capability_families"]) == 14
    assert {family["family_id"] for family in catalogue["capability_families"]} == {
        "meeting-follow-through",
        "living-people-company-context",
        "durable-task-continuity",
        "external-task-interoperability",
        "connected-work-context",
        "pipedrive-pipeline-continuity",
        "daily-weekly-operating-rhythm",
        "durable-work-memory",
        "proactive-health-and-recovery",
        "backup-and-restore-confidence",
        "safe-change-and-rewind",
        "capability-discovery-and-adoption",
        "privacy-safe-feedback-loop",
        "career-growth-evidence",
    }


def test_committed_significant_preview_is_exact_generated_output(tmp_path: Path) -> None:
    assert (
        hashlib.sha256(PROPOSED_SIGNIFICANT_LENS_SCHEMA.read_bytes()).hexdigest()
        == PROPOSED_SIGNIFICANT_LENS_SCHEMA_SHA256
    )

    result = _generate_enriched(
        tmp_path,
        "--lens-schema",
        str(PROPOSED_SIGNIFICANT_LENS_SCHEMA),
    )

    assert result.returncode == 0, result.stderr
    assert (
        tmp_path / "dex-lens-catalog-enriched-preview.json"
    ).read_bytes() == ENRICHED_EXAMPLE.read_bytes()


def test_complete_mcp_inventory_gate_rejects_emitted_tool_drift() -> None:
    generator = _load_generator_module()
    _catalog_version, _release_version, catalogue = generator._build_enriched_catalogue(
        REPO_ROOT
    )
    broken = json.loads(json.dumps(catalogue))
    work = next(
        entry
        for entry in broken["capabilities"]
        if entry["capability_id"] == "dex-work-mcp"
    )
    work["tools"].pop()

    with pytest.raises(generator.LensCatalogError, match="MCP tool inventory mismatch.*dex-work-mcp"):
        generator._assert_complete_mcp_inventory(
            discover_mcp_servers(REPO_ROOT), broken["capabilities"]
        )


def test_release_coverage_gate_validates_significant_registry_before_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = _load_generator_module()
    events: list[str] = []

    def validate(payload: object, *, release_root: Path) -> None:
        assert isinstance(payload, dict)
        assert release_root == REPO_ROOT
        events.append("significant")

    def build(release_root: Path) -> tuple[int, str, dict[str, object]]:
        assert release_root == REPO_ROOT
        events.append("catalogue")
        return 6, "1.97.6", {}

    monkeypatch.setattr(generator, "validate_significant_capability_registry", validate)
    monkeypatch.setattr(generator, "_build_enriched_catalogue", build)

    generator.validate_release_coverage(REPO_ROOT)

    assert events == ["significant", "catalogue"]


def test_release_coverage_gate_reports_significant_registry_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generator = _load_generator_module()

    def reject(_payload: object, *, release_root: Path) -> None:
        assert release_root == REPO_ROOT
        raise generator.SignificantCapabilityRegistryError("provider identity disappeared")

    monkeypatch.setattr(generator, "validate_significant_capability_registry", reject)

    with pytest.raises(
        generator.LensCatalogError,
        match="significant capability coverage is invalid.*provider identity disappeared",
    ):
        generator.validate_release_coverage(REPO_ROOT)


def test_enriched_preview_fails_honestly_against_stale_released_schema(tmp_path: Path) -> None:
    output = tmp_path / "dist"
    result = _generate_enriched(output, "--lens-schema", str(RELEASED_LENS_SCHEMA))

    assert result.returncode == 1
    assert "complete MCP tool inventory" in result.stderr
    assert "released Lens contract" in result.stderr
    assert not output.exists()


def test_stale_schema_refusal_does_not_overwrite_the_committed_preview(tmp_path: Path) -> None:
    before = ENRICHED_EXAMPLE.read_bytes()
    result = _generate_enriched(tmp_path, "--lens-schema", str(RELEASED_LENS_SCHEMA))

    assert result.returncode == 1
    assert not (tmp_path / "dex-lens-catalog-enriched-preview.json").exists()
    assert ENRICHED_EXAMPLE.read_bytes() == before


def test_signed_enriched_release_path_is_blocked_until_exact_lens_contract_is_vendored(
    tmp_path: Path, signing_key_b64: str
) -> None:
    result = _generate_enriched_release(tmp_path, signing_key_b64)

    assert result.returncode == 1
    assert "signing and publication remain blocked" in result.stderr
    assert "exact tagged Lens contract" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_unsigned_enriched_release_path_is_also_blocked(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--release-root",
            str(REPO_ROOT),
            "--output-dir",
            str(tmp_path),
            "--enriched",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "signing and publication remain blocked" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_generator_rejects_unshipped_or_stale_source(tmp_path: Path) -> None:
    _registry(tmp_path)
    data = json.loads((tmp_path / "core/lens-catalog/registry.json").read_text())
    data["entries"][0]["source"]["path"] = ".claude/skills/missing/SKILL.md"
    _write(tmp_path / "core/lens-catalog/registry.json", json.dumps(data))

    missing = _generate(tmp_path)
    assert missing.returncode == 1
    assert "missing or not a regular file" in missing.stderr

    _registry(tmp_path)
    data = json.loads((tmp_path / "core/lens-catalog/registry.json").read_text())
    data["entries"][0]["source"]["sha256"] = "0" * 64
    _write(tmp_path / "core/lens-catalog/registry.json", json.dumps(data))

    stale = _generate(tmp_path)
    assert stale.returncode == 1
    assert "do not match the authoritative sha256 or byte_size" in stale.stderr


def _adoptable_registry(root: Path, source_kind: str) -> Path:
    """Append a dormant lifecycle or room annotation beside the active fixture."""
    _registry(root)
    registry_path = root / "core/lens-catalog/registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entry = json.loads(json.dumps(registry["entries"][0]))
    if source_kind == "lifecycle-skill":
        entry_id = "account-plan"
        relative = ".claude/skills/_available/sales/account-plan/SKILL.md"
        payload = (
            "---\nname: account-plan\ndescription: Use when planning a strategic account from sourced evidence.\n---\n"
        ).encode()
        _write(root / relative, payload.decode())
        _write(
            root / "core/lifecycle/catalog/official-capabilities.json",
            json.dumps(
                {
                    "catalog_source_version": 1,
                    "items": [
                        {
                            "id": entry_id,
                            "kind": "skill",
                            "version": "1.0.0",
                            "files": [
                                {
                                    "path": f".claude/skills/{entry_id}/SKILL.md",
                                    "source_path": relative,
                                    "sha256": hashlib.sha256(payload).hexdigest(),
                                    "byte_size": len(payload),
                                }
                            ],
                            "dependencies": [],
                            "capabilities": [],
                        }
                    ],
                }
            ),
        )
        entry["source"] = {"kind": source_kind, "item_id": entry_id}
    else:
        entry_id = "career-setup"
        relative = ".claude/skills/_available/capabilities/career/skills/career-setup/SKILL.md"
        payload = (
            "---\nname: career-setup\ndescription: Use when creating a consented career evidence space.\n---\n"
        ).encode()
        _write(root / relative, payload.decode())
        _write(
            root / "packages/dex-contracts/dist/portable-vault.contract.json",
            json.dumps(
                {
                    "capabilities": {
                        "career": {
                            "folders": ["05-Areas/Career"],
                            "skills": [entry_id],
                            "default_enabled": True,
                            "skill_sources": [
                                {
                                    "room": "career",
                                    "skill": entry_id,
                                    "source_path": relative,
                                    "target_path": f".claude/skills/{entry_id}/SKILL.md",
                                    "sha256": hashlib.sha256(payload).hexdigest(),
                                    "byte_size": len(payload),
                                    "previous_payloads": [],
                                }
                            ],
                        }
                    }
                }
            ),
        )
        entry["source"] = {
            "kind": source_kind,
            "room": "career",
            "skill": entry_id,
        }
    entry["id"] = entry_id
    entry["availability"] = "dormant"
    entry["impact_tier"] = "medium"
    registry["entries"].append(entry)
    _write(registry_path, json.dumps(registry))
    return root / relative


@pytest.mark.parametrize("source_kind", ("lifecycle-skill", "room-skill"))
def test_generator_validates_but_does_not_publish_dormant_skill_source(tmp_path: Path, source_kind: str) -> None:
    source = _adoptable_registry(tmp_path, source_kind)

    result = _generate(tmp_path)

    assert result.returncode == 0, result.stderr
    envelope = json.loads((tmp_path / "dist/dex-lens-catalog-latest.json").read_text(encoding="utf-8"))
    assert [capability["capability_id"] for capability in envelope["catalogue"]["capabilities"]] == ["daily-plan"]
    assert source.is_file(), "the dormant source was not actually present for resolver validation"


def test_generator_rejects_mutated_room_source_before_signing_or_publication(
    tmp_path: Path, signing_key_b64: str
) -> None:
    source = _adoptable_registry(tmp_path, "room-skill")
    source.write_text("changed after the room authority was pinned\n", encoding="utf-8")

    result = _generate_signed(tmp_path, signing_key_b64)

    assert result.returncode == 1
    assert "source identity" in result.stderr
    assert "sha256 or byte_size" in result.stderr
    assert _lens_artifacts(tmp_path) == []


def test_generator_rejects_vendored_third_party_skill_sources(tmp_path: Path) -> None:
    """Dex must never present a vendored third-party skill as its own capability.

    Sixteen `.claude/skills/anthropic-*` skills ship in the tree, and without the
    structural guard the producer signs and publishes them as Dex capabilities --
    verified by removing the guard and watching this fixture build cleanly.

    The entry id deliberately MATCHES the vendored path. With a mismatched id the
    entry-id/path check refuses first, so the test would pass with the guard
    deleted and prove nothing: the exact registry shape that actually slips
    through is the one where the id agrees with the path. The negative assertions
    below hold this property in place.
    """
    _registry(tmp_path)
    vendored_bytes = _skill(tmp_path, "anthropic-pdf", description="Vendored third-party PDF skill.")
    data = json.loads((tmp_path / "core/lens-catalog/registry.json").read_text())
    data["entries"][0]["id"] = "anthropic-pdf"
    data["entries"][0]["source"] = {
        "kind": "active-skill",
        "path": ".claude/skills/anthropic-pdf/SKILL.md",
        "sha256": hashlib.sha256(vendored_bytes).hexdigest(),
        "byte_size": len(vendored_bytes),
    }
    _write(tmp_path / "core/lens-catalog/registry.json", json.dumps(data))

    result = _generate(tmp_path)

    assert result.returncode == 1
    assert "must not be a vendored skill" in result.stderr
    # The guard is the reason, not some other check that happens to fire first.
    assert "must match entry id" not in result.stderr
    assert "must be a shipped skill SKILL.md" not in result.stderr
    # Fails closed: nothing left for the release job's upload steps to publish.
    assert _lens_artifacts(tmp_path) == []


def test_signing_requires_environment_secret_and_never_generates_a_key(tmp_path: Path) -> None:
    _registry(tmp_path)

    missing = _generate(tmp_path, "--sign", "--signing-key-env", "DEX_LENS_TEST_KEY")
    assert missing.returncode == 1
    assert "environment secret DEX_LENS_TEST_KEY is not set" in missing.stderr

    key = base64.b64encode(b"test-only-not-a-real-ed25519-private-key").decode("ascii")
    signed = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--release-root",
            str(tmp_path),
            "--output-dir",
            str(tmp_path / "dist"),
            "--issued-at",
            "2026-08-11T12:00:00Z",
            "--sign",
            "--signing-key-env",
            "DEX_LENS_TEST_KEY",
            "--key-id",
            "test-key",
            "--test-deterministic-signature",
        ],
        cwd=REPO_ROOT,
        env={"DEX_LENS_TEST_KEY": key},
        capture_output=True,
        text=True,
    )
    assert signed.returncode == 0, signed.stderr
    envelope = json.loads((tmp_path / "dist/dex-lens-catalog-v1.94.0.json").read_text())
    assert envelope["metadata"]["key_id"] == "test-key"
    assert len(base64.b64decode(envelope["signature"], validate=True)) == 64


def test_deterministic_test_signature_is_unreachable_in_ci(tmp_path: Path) -> None:
    _registry(tmp_path)
    key = base64.b64encode(b"test-only-not-a-real-ed25519-private-key").decode("ascii")

    signed = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--release-root",
            str(tmp_path),
            "--output-dir",
            str(tmp_path / "dist"),
            "--issued-at",
            "2026-08-11T12:00:00Z",
            "--sign",
            "--signing-key-env",
            "DEX_LENS_TEST_KEY",
            "--key-id",
            "test-key",
            "--test-deterministic-signature",
        ],
        cwd=REPO_ROOT,
        env={"DEX_LENS_TEST_KEY": key, "GITHUB_ACTIONS": "true"},
        capture_output=True,
        text=True,
    )

    assert signed.returncode == 1
    assert "deterministic test signature mode is disabled in CI" in signed.stderr


def test_real_ed25519_signing_hook_uses_only_environment_key(tmp_path: Path) -> None:
    _registry(tmp_path)
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        Encoding.PEM,
        PrivateFormat.PKCS8,
        NoEncryption(),
    )

    signed = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--release-root",
            str(tmp_path),
            "--output-dir",
            str(tmp_path / "dist"),
            "--issued-at",
            "2026-08-11T12:00:00Z",
            "--sign",
            "--signing-key-env",
            "DEX_LENS_TEST_KEY",
            "--key-id",
            "ed25519-test-key",
        ],
        cwd=REPO_ROOT,
        env={"DEX_LENS_TEST_KEY": base64.b64encode(private_pem).decode("ascii")},
        capture_output=True,
        text=True,
    )
    assert signed.returncode == 0, signed.stderr
    envelope = json.loads((tmp_path / "dist/dex-lens-catalog-v1.94.0.json").read_text())
    signature = base64.b64decode(envelope["signature"])
    private_key.public_key().verify(signature, _signed_payload(envelope).encode("utf-8"))


def _corrupt_dropped_required_field(data: dict) -> str:
    del data["entries"][0]["value"]
    return "missing value"


def _corrupt_wrong_schema_shape(data: dict) -> str:
    data["entries"][0]["prerequisites"] = "a single string, not an array"
    return "prerequisites must be a non-empty array"


def _corrupt_stale_source_sha256(data: dict) -> str:
    data["entries"][0]["source"]["sha256"] = "1" * 64
    return "do not match the authoritative sha256 or byte_size"


def _corrupt_stale_source_byte_size(data: dict) -> str:
    data["entries"][0]["source"]["byte_size"] = 999999
    return "do not match the authoritative sha256 or byte_size"


def _corrupt_unknown_job_reference(data: dict) -> str:
    data["entries"][0]["jobs_served"] = ["job-that-does-not-exist"]
    return "unknown job reference"


def _corrupt_unknown_foundation_reference(data: dict) -> str:
    data["entries"][0]["foundation_capabilities"] = ["foundation-that-does-not-exist"]
    return "unknown foundation reference"


def _corrupt_unreleased_since_version(data: dict) -> str:
    data["entries"][0]["since_release"] = "99.0.0"
    return "since_release has no shipped source in CHANGELOG.md"


def _lens_artifacts(root: Path) -> list[str]:
    """Every file the release workflow would publish for the Lens catalogue."""
    dist = root / "dist"
    if not dist.exists():
        return []
    return sorted(path.name for path in dist.iterdir() if path.name.startswith("dex-lens-catalog"))


def _generate_signed(root: Path, key_b64: str) -> subprocess.CompletedProcess[str]:
    """Run the producer exactly as the release job does: --sign with a usable key present."""
    return subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--release-root",
            str(root),
            "--output-dir",
            str(root / "dist"),
            "--issued-at",
            "2026-08-11T12:00:00Z",
            "--sign",
            "--signing-key-env",
            "DEX_LENS_TEST_KEY",
            "--key-id",
            "dex-core-lens-1",
        ],
        cwd=REPO_ROOT,
        env={"DEX_LENS_TEST_KEY": key_b64},
        capture_output=True,
        text=True,
    )


@pytest.fixture(name="signing_key_b64")
def _signing_key_b64() -> str:
    private_pem = Ed25519PrivateKey.generate().private_bytes(
        Encoding.PEM,
        PrivateFormat.PKCS8,
        NoEncryption(),
    )
    return base64.b64encode(private_pem).decode("ascii")


def test_signed_release_path_publishes_when_the_registry_is_sound(tmp_path: Path, signing_key_b64: str) -> None:
    """Positive control: without this, the fail-closed test below could pass vacuously."""
    _registry(tmp_path)

    result = _generate_signed(tmp_path, signing_key_b64)

    assert result.returncode == 0, result.stderr
    assert _lens_artifacts(tmp_path) == [
        "dex-lens-catalog-latest.json",
        "dex-lens-catalog-latest.json.sha256",
        "dex-lens-catalog-v1.94.0.json",
        "dex-lens-catalog-v1.94.0.json.sha256",
    ]
    assert json.loads((tmp_path / "dist/dex-lens-catalog-v1.94.0.json").read_text())["signature"]


@pytest.mark.parametrize(
    ("corrupt", "label"),
    [
        (_corrupt_dropped_required_field, "dropped-required-field"),
        (_corrupt_wrong_schema_shape, "wrong-schema-shape"),
        (_corrupt_stale_source_sha256, "stale-source-sha256"),
        (_corrupt_stale_source_byte_size, "stale-source-byte-size"),
        (_corrupt_unknown_job_reference, "unknown-job-reference"),
        (_corrupt_unknown_foundation_reference, "unknown-foundation-reference"),
        (_corrupt_unreleased_since_version, "unreleased-since-version"),
    ],
)
def test_broken_registry_entry_fails_closed_before_signing_or_publication(
    tmp_path: Path, signing_key_b64: str, corrupt, label: str
) -> None:
    """A broken registry entry must stop the release producer before it signs or writes.

    The unsigned rejection tests above prove the generator complains. This proves the
    property the release job actually depends on: with a usable signing key present and
    --sign requested, a broken entry still refuses, and leaves nothing behind for the
    'Upload Dex Lens catalog' steps to publish.
    """
    _registry(tmp_path)
    registry_path = tmp_path / "core/lens-catalog/registry.json"
    data = json.loads(registry_path.read_text())
    expected_error = corrupt(data)
    _write(registry_path, json.dumps(data))

    result = _generate_signed(tmp_path, signing_key_b64)

    assert result.returncode == 1, f"{label}: expected refusal, got {result.returncode}"
    assert "Dex Lens catalog generation failed" in result.stderr
    assert expected_error in result.stderr, f"{label}: unexpected reason: {result.stderr}"
    # Fails closed: no signed envelope, no digest sidecar, nothing to upload or serve.
    assert _lens_artifacts(tmp_path) == [], f"{label}: producer left publishable output behind"


def test_broken_registry_refusal_is_not_a_signing_failure(tmp_path: Path, signing_key_b64: str) -> None:
    """The refusal must come from registry validation, not from the signing step.

    If validation ever moved after signing, the error text would change and this
    would catch it -- the producer must never reach the key for a broken registry.
    """
    _registry(tmp_path)
    registry_path = tmp_path / "core/lens-catalog/registry.json"
    data = json.loads(registry_path.read_text())
    _corrupt_stale_source_sha256(data)
    _write(registry_path, json.dumps(data))

    result = _generate_signed(tmp_path, signing_key_b64)

    assert result.returncode == 1
    assert "do not match the authoritative sha256 or byte_size" in result.stderr
    for signing_error in (
        "environment secret",
        "is not base64",
        "Ed25519 signing failed",
        "is not an Ed25519 private key",
        "cryptography>=42 is required",
    ):
        assert signing_error not in result.stderr


# --- The registry Dex actually ships ---------------------------------------
#
# Every test above builds a synthetic release tree. That proves the producer's
# logic, but it cannot see the registry Dex actually ships, so the whole file
# stays green while the real catalogue refuses to build. That happened: a skill
# was edited after its pin was written, and the first place it could have
# surfaced was the release job itself, with the release already in motion.
#
# These two tests read core/lens-catalog/registry.json against the real release
# root, so pin drift fails on the pull request that causes it.


def test_real_registry_annotates_the_complete_active_set_and_marks_dormant_entries() -> None:
    registry = json.loads(REAL_REGISTRY.read_text(encoding="utf-8"))
    discovered_ids = {candidate.capability_id for candidate in discover_active_skills(REPO_ROOT)}
    active_entries = [entry for entry in registry["entries"] if entry["availability"] == "active"]
    dormant_entries = [entry for entry in registry["entries"] if entry["availability"] == "dormant"]

    assert registry["catalog_version"] == 5
    assert tuple(job["job_id"] for job in registry["jobs"]) == CANONICAL_JOB_IDS
    assert len(registry["entries"]) == 94
    assert len(active_entries) == 65
    assert len(dormant_entries) == 29
    assert {entry["id"] for entry in active_entries} == discovered_ids
    assert all(entry["capability_class"] == "active-skill" for entry in registry["entries"])
    assert {entry["impact_tier"] for entry in registry["entries"]} <= {"core", "high", "medium", "niche"}
    assert all(set(entry["jobs_served"]) <= set(CANONICAL_JOB_IDS) for entry in registry["entries"])


def test_wave3_source_partition_is_exact_and_resolves_to_unique_targets() -> None:
    registry = json.loads(REAL_REGISTRY.read_text(encoding="utf-8"))
    by_id = {entry["id"]: entry for entry in registry["entries"]}
    wave3 = [by_id[entry_id] for entry_id in WAVE3_IDS]

    assert registry["catalog_version"] == 5
    assert len(registry["jobs"]) == 8
    assert len(registry["entries"]) == 94
    assert tuple(entry["id"] for entry in wave3) == WAVE3_IDS
    assert all(entry["capability_class"] == "active-skill" for entry in wave3)
    assert all(
        entry["availability"] == ("active" if entry["id"] in WAVE3_ACTIVE_IDS else "dormant")
        for entry in wave3
    )
    assert all(
        evidence.get("coverage") == "supporting"
        for entry in wave3
        for evidence in entry["evidence"]
        if evidence["kind"] == "test"
    )
    by_kind = {
        kind: {entry["id"] for entry in wave3 if entry["source"]["kind"] == kind}
        for kind in ("active-skill", "lifecycle-skill", "room-skill")
    }
    assert by_kind == {
        "active-skill": WAVE3_ACTIVE_IDS,
        "lifecycle-skill": WAVE3_LIFECYCLE_IDS,
        "room-skill": WAVE3_ROOM_IDS,
    }
    expected_fields = {
        "active-skill": {"kind", "path", "sha256", "byte_size"},
        "lifecycle-skill": {"kind", "item_id"},
        "room-skill": {"kind", "room", "skill"},
    }
    assert all(set(entry["source"]) == expected_fields[entry["source"]["kind"]] for entry in wave3)

    pins = [resolve_skill_source(entry["source"], REPO_ROOT) for entry in wave3]
    assert [pin.target_path for pin in pins] == [
        f".claude/skills/{entry_id}/SKILL.md" for entry_id in WAVE3_IDS
    ]
    assert len({pin.target_path for pin in pins}) == len(pins)
    pipeline = pins[WAVE3_IDS.index("pipeline-sync")]
    assert pipeline.source_path == ".claude/skills/pipeline-sync/SKILL.md"


def _registry_source_pin_drifts(registry_path: Path, release_root: Path) -> list[str]:
    entries = json.loads(registry_path.read_text(encoding="utf-8"))["entries"]
    assert entries, "the shipped registry declares no entries to check"

    drifted = []
    for index, entry in enumerate(entries):
        try:
            resolve_skill_source(entry["source"], release_root)
        except SkillSourceError as error:
            drifted.append(f"entry {index} ({entry['id']}): source authority rejected the entry: {error}")
    return drifted


def test_real_registry_source_pins_match_the_shipped_skills() -> None:
    """Every pinned skill must still hash to the digest and size the registry declares.

    This is the narrow, fast gate: it needs no signing key and no release
    metadata, so it reports pin drift as pin drift rather than as some later
    failure, and it names the corrected values so the fix is mechanical.
    """
    drifted = _registry_source_pin_drifts(REAL_REGISTRY, REPO_ROOT)
    assert not drifted, (
        "core/lens-catalog/registry.json source pins are stale, so the release job's Lens"
        " catalogue generation will refuse. Update the declared sha256 and byte_size for:\n  " + "\n  ".join(drifted)
    )


def test_real_registry_pin_check_fails_on_a_deliberately_drifted_pin(tmp_path: Path) -> None:
    registry = json.loads(REAL_REGISTRY.read_text(encoding="utf-8"))
    registry["entries"][0]["source"]["sha256"] = "0" * 64
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    drifted = _registry_source_pin_drifts(registry_path, REPO_ROOT)

    assert drifted
    assert "source authority rejected the entry" in drifted[0]


def test_shipped_registry_builds_the_release_catalogue(tmp_path: Path, signing_key_b64: str) -> None:
    """The real registry must produce a signed catalogue, invoked as the release job does.

    Broader than the pin check above: this exercises the whole producer against
    the real release root -- release version against CHANGELOG, job and
    foundation references, skill frontmatter, the vendored schema -- so any
    registry change that would only fail during a release fails here instead.
    Output goes to a temporary directory; the repository is never written to.
    """
    result = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--release-root",
            str(REPO_ROOT),
            "--output-dir",
            str(tmp_path / "dist"),
            "--issued-at",
            "2026-08-11T12:00:00Z",
            "--sign",
            "--signing-key-env",
            "DEX_LENS_TEST_KEY",
            "--key-id",
            "dex-core-lens-1",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "DEX_LENS_TEST_KEY": signing_key_b64},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        "the shipped Lens registry no longer builds, so the next release would fail to"
        f" produce its catalogue: {result.stderr}"
    )

    version = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    assert _lens_artifacts(tmp_path) == [
        "dex-lens-catalog-latest.json",
        "dex-lens-catalog-latest.json.sha256",
        f"dex-lens-catalog-v{version}.json",
        f"dex-lens-catalog-v{version}.json.sha256",
    ]

    envelope = json.loads((tmp_path / f"dist/dex-lens-catalog-v{version}.json").read_text())
    assert envelope["signature"], "the real catalogue was written without a signature"
    assert envelope["metadata"]["core_release"] == f"v{version}"
    assert [capability["capability_id"] for capability in envelope["catalogue"]["capabilities"]] == [
        candidate.capability_id for candidate in discover_active_skills(REPO_ROOT)
    ]
    assert len(envelope["catalogue"]["capabilities"]) == 65


def _rewrite_registry_evidence(root: Path, evidence: list[dict[str, str]]) -> None:
    registry_path = root / "core/lens-catalog/registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["entries"][0]["evidence"] = evidence
    registry_path.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("kind", "reference", "coverage", "expected_level"),
    (
        ("test", "core/tests/test_commitments_skill.py", "behavioral", "verified"),
        ("test", "core/tests/test_commitments_skill.py", "supporting", "supported"),
        ("runtime-path", ".claude/skills/daily-plan/SKILL.md", None, "supported"),
        ("doc", "docs/backup-restore.md", None, "supported"),
        ("release-note", "CHANGELOG.md", None, "supported"),
    ),
)
def test_only_behavioral_test_evidence_earns_the_verified_evidence_level(
    tmp_path: Path, kind: str, reference: str, coverage: str | None, expected_level: str
) -> None:
    """A test name alone must not turn supporting evidence into verified behaviour.

    The registry must say whether a test exercises the capability itself or merely
    supports a related promise. That distinction is deliberately derived by the
    producer: a review of shipped instructions, an adoption test, or a runtime
    path cannot accidentally read as behaviourally proven.
    """
    _registry(tmp_path)
    evidence = {
        "kind": kind,
        "reference": reference,
        "summary": "Evidence level derivation probe.",
    }
    if coverage is not None:
        evidence["coverage"] = coverage
    _rewrite_registry_evidence(
        tmp_path,
        [evidence],
    )

    result = _generate(tmp_path)

    assert result.returncode == 0, result.stderr
    envelope = json.loads((tmp_path / "dist/dex-lens-catalog-latest.json").read_text())
    evidence = envelope["catalogue"]["capabilities"][0]["evidence"]
    assert [item["level"] for item in evidence] == [expected_level]


def test_generator_rejects_unclassified_or_missing_test_evidence(tmp_path: Path) -> None:
    _registry(tmp_path)
    _rewrite_registry_evidence(
        tmp_path,
        [
            {
                "kind": "test",
                "reference": "core/tests/test_commitments_skill.py",
                "summary": "A test without an explicit scope must fail closed.",
            }
        ],
    )

    unclassified = _generate(tmp_path)

    assert unclassified.returncode == 1
    assert "missing coverage" in unclassified.stderr

    _registry(tmp_path)
    _rewrite_registry_evidence(
        tmp_path,
        [
            {
                "kind": "test",
                "coverage": "behavioral",
                "reference": "core/tests/missing.py",
                "summary": "A made-up test cannot be evidence.",
            }
        ],
    )

    missing = _generate(tmp_path)

    assert missing.returncode == 1
    assert "evidence 0 reference is missing or not a regular file" in missing.stderr


def test_real_test_evidence_is_explicit_and_only_behavioral_evidence_verifies(tmp_path: Path) -> None:
    """The real catalogue can only verify sources manually classified as behavioural.

    This is the release-facing guard. Every test reference must have a narrow
    coverage classification, and the emitted catalogue must match it exactly.
    That makes an instruction-contract or adoption test visibly supporting evidence
    until a behavioural test is genuinely added.
    """
    result = subprocess.run(
        [
            sys.executable,
            str(GENERATOR),
            "--release-root",
            str(REPO_ROOT),
            "--output-dir",
            str(tmp_path / "dist"),
            "--issued-at",
            "2026-08-11T12:00:00Z",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    envelope = json.loads((tmp_path / "dist/dex-lens-catalog-latest.json").read_text())
    registry = json.loads(REAL_REGISTRY.read_text(encoding="utf-8"))
    test_evidence = [
        (entry["id"], item) for entry in registry["entries"] for item in entry["evidence"] if item["kind"] == "test"
    ]
    invalid_coverage = [
        f"{entry_id}: {item['reference']} ({item.get('coverage')!r})"
        for entry_id, item in test_evidence
        if item.get("coverage") not in {"behavioral", "supporting"}
    ]
    assert not invalid_coverage, (
        "every test evidence record must say whether it exercises the capability itself "
        f"or only supports a related promise: {invalid_coverage}"
    )
    expected_verified_evidence = {
        (entry_id, f"test: {item['reference']}") for entry_id, item in test_evidence if item["coverage"] == "behavioral"
    }
    verified_evidence = {
        (capability["capability_id"], item["source"])
        for capability in envelope["catalogue"]["capabilities"]
        for item in capability["evidence"]
        if item["level"] == "verified"
    }
    assert verified_evidence == expected_verified_evidence, (
        "the released catalogue's verified evidence does not exactly match the test "
        f"records classified as behavioural: expected {sorted(expected_verified_evidence)}, "
        f"got {sorted(verified_evidence)}"
    )
